"""웹 푸시: 화면을 떠난 사이 답변이 끝나면 질문한 기기에 알린다 (가짜 발송기, 네트워크 없음)."""

import json
import time

from fastapi.testclient import TestClient

from danbi.agent.loop import Agent
from danbi.agent.tools import Tool, ToolRegistry
from danbi.api.main import create_app
from danbi.config import AuthSettings
from danbi.llm.base import LLMError, ToolSpec
from danbi.ops import TraceRecorder, TraceStore
from danbi.personal.push import PushService, generate_private_key, is_push_endpoint, public_key_of

from .fakes import FakeProvider, Reply
from .test_api import events
from .test_auth import FakeGoogle, env, login  # noqa: F401  (env는 pytest 픽스처)

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"
P256DH = "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM"
AUTH = "tBHItJI5svbpez7KI4CCXg"
SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}


class FakeSender:
    def __init__(self, status=201):
        self.status, self.sent = status, []

    def __call__(self, info, data):
        self.sent.append((info, json.loads(data)))
        return self.status


def test_keys_and_endpoint_rules():
    key = generate_private_key()
    pub = public_key_of(key)
    assert len(pub) == 87 and pub.startswith("B")   # 65바이트 비압축 점 (0x04로 시작)
    assert is_push_endpoint(ENDPOINT)
    assert is_push_endpoint("https://web.push.apple.com/QGuQ")
    assert is_push_endpoint("https://updates.push.services.mozilla.com/wpush/v2/x")
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example/x", "https://fcm.googleapis.com.evil.example/x",
                "https://127.0.0.1/x"):
        assert not is_push_endpoint(bad), bad


def test_generated_key_signs_with_py_vapid():
    from py_vapid import Vapid

    key = generate_private_key()
    headers = Vapid.from_string(key).sign({"aud": "https://fcm.googleapis.com", "sub": "mailto:a@b.c",
                                           "exp": int(time.time()) + 3600})
    assert headers["Authorization"].startswith("vapid t=")
    assert public_key_of(key) in headers["Authorization"]


def test_disabled_without_key_or_subject():
    store = TraceStore(None)
    assert not PushService(store, None, "mailto:a@b.c").enabled
    assert not PushService(store, generate_private_key(), None).enabled
    assert not PushService(store, "not-a-key!!", "mailto:a@b.c").enabled


def make(replies, sender, *, tool=None):
    store = TraceStore(None)
    tools = ToolRegistry([tool] if tool else [])
    agent = Agent(FakeProvider(replies), tools)
    google = FakeGoogle()
    push = PushService(store, generate_private_key(), "mailto:ops@example.com", sender=sender)
    app = create_app(agent, recorder=TraceRecorder(store, agent), auth=AuthSettings(), auth_http=google.http,
                     auth_verifier=google.verify, push=push)
    client = TestClient(app, base_url="https://testserver")
    return client, google, store


def subscribe(client):
    return client.put("/api/push", json={"endpoint": ENDPOINT, "keys": {"p256dh": P256DH, "auth": AUTH}})


def test_subscribe_and_unsubscribe(env):  # noqa: F811
    client, google, store = make([], FakeSender())
    assert client.get("/api/push").status_code == 401
    login(client, google)
    status = client.get("/api/push").json()
    assert status["available"] is True and len(status["public_key"]) == 87
    bad = client.put("/api/push", json={"endpoint": "https://evil.example/x", "keys": {"p256dh": P256DH, "auth": AUTH}})
    assert bad.status_code == 400
    assert subscribe(client).status_code == 200 and store.get_push(ENDPOINT) is not None
    assert client.put("/api/push", json={"endpoint": ENDPOINT, "keys": {"p256dh": P256DH, "auth": AUTH}},
                      headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.request("DELETE", "/api/push", json={"endpoint": ENDPOINT}).json() == {"ok": True}
    assert store.get_push(ENDPOINT) is None


def test_no_push_while_user_is_watching(env):  # noqa: F811
    sender = FakeSender()
    client, google, _ = make([Reply(text="답")], sender)
    login(client, google)
    subscribe(client)
    evs = events(client.post("/api/chat", json={"message": "졸업 요건?", "push_endpoint": ENDPOINT}))
    assert evs[-1][0] == "done" and sender.sent == []


def hide_during_answer(client, store, hidden=True):
    """도구가 실행되는 동안(답변 중) 사용자가 홈 키를 눌렀다고 알린다."""
    def tool(q):
        run_id = store._all("SELECT id FROM runs WHERE status = 'running'")[0]["id"]
        client.post("/api/chat/visibility", json={"run_id": run_id, "hidden": hidden})
        return "결과"
    return Tool(ToolSpec("look", "d", SCHEMA), tool)


def test_push_when_hidden_at_finish(env):  # noqa: F811
    sender = FakeSender()
    holder = {}
    tool = Tool(ToolSpec("look", "d", SCHEMA), lambda q: holder["t"].func(q))
    client, google, store = make([Reply(calls=[("look", {"q": "1"})]), Reply(text="답")], sender, tool=tool)
    holder["t"] = hide_during_answer(client, store)
    login(client, google)
    subscribe(client)
    evs = events(client.post("/api/chat", json={"message": "  졸업   요건이\n뭐야?", "push_endpoint": ENDPOINT}))
    sid = evs[0][1]["session_id"]
    assert len(sender.sent) == 1
    info, payload = sender.sent[0]
    assert info == {"endpoint": ENDPOINT, "keys": {"p256dh": P256DH, "auth": AUTH}}
    assert payload == {"title": "단비 답변이 준비됐어요", "body": "졸업 요건이 뭐야?", "conversation_id": sid}
    assert store.get_push(ENDPOINT)["last_ok_at"] is not None


def test_failed_answer_is_notified_and_gone_subscription_removed(env):  # noqa: F811
    sender = FakeSender(status=410)
    holder = {}
    tool = Tool(ToolSpec("look", "d", SCHEMA), lambda q: holder["t"].func(q))
    client, google, store = make([Reply(calls=[("look", {"q": "1"})]), Reply(error=LLMError("400 bad"))], sender,
                                 tool=tool)
    holder["t"] = hide_during_answer(client, store)
    login(client, google)
    subscribe(client)
    client.post("/api/chat", json={"message": "q", "push_endpoint": ENDPOINT})
    assert sender.sent[0][1]["title"] == "단비가 답변을 만들지 못했어요"
    assert store.get_push(ENDPOINT) is None          # 410: 구독이 끝났으므로 지운다


def test_came_back_before_finish_means_no_push(env):  # noqa: F811
    sender = FakeSender()
    holder = {}

    def tool_fn(q):
        holder["hide"].func(q)
        holder["show"].func(q)
        return "결과"
    tool = Tool(ToolSpec("look", "d", SCHEMA), tool_fn)
    client, google, store = make([Reply(calls=[("look", {"q": "1"})]), Reply(text="답")], sender, tool=tool)
    holder["hide"], holder["show"] = hide_during_answer(client, store), hide_during_answer(client, store, hidden=False)
    login(client, google)
    subscribe(client)
    client.post("/api/chat", json={"message": "q", "push_endpoint": ENDPOINT})
    assert sender.sent == []


def test_someone_elses_endpoint_is_ignored(env):  # noqa: F811
    sender = FakeSender()
    holder = {}
    tool = Tool(ToolSpec("look", "d", SCHEMA), lambda q: holder["t"].func(q))
    client, google, store = make([Reply(calls=[("look", {"q": "1"})]), Reply(text="답")], sender, tool=tool)
    holder["t"] = hide_during_answer(client, store)
    login(client, google)
    other = store.upsert_user(google_sub="other", email="b@dankook.ac.kr", name="B", hd="dankook.ac.kr", ip=None)
    store.save_push(other["id"], ENDPOINT, P256DH, AUTH)    # 다른 사용자의 구독
    client.post("/api/chat", json={"message": "q", "push_endpoint": ENDPOINT})
    assert sender.sent == []


async def test_push_when_connection_dropped(env):  # noqa: F811
    """홈 키를 누른 순간 화면이 숨김을 알리지 못하고 연결만 끊겨도 알림이 간다."""
    import asyncio
    import time as _t

    def slow(q):
        _t.sleep(0.3)
        return "결과"

    sender = FakeSender()
    client, google, store = make([Reply(calls=[("look", {"q": "1"})]), Reply(text="답")], sender,
                                 tool=Tool(ToolSpec("look", "d", SCHEMA), slow))
    login(client, google)
    subscribe(client)
    cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
    body = json.dumps({"message": "q", "push_endpoint": ENDPOINT}).encode()
    got, sent = asyncio.Event(), []

    async def receive():
        if not sent:
            sent.append(1)
            return {"type": "http.request", "body": body, "more_body": False}
        await got.wait()
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.body" and msg.get("body"):
            got.set()

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "https",
             "path": "/api/chat", "raw_path": b"/api/chat", "query_string": b"", "root_path": "",
             "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                         (b"cookie", cookie.encode())],
             "client": ("127.0.0.1", 1), "server": ("testserver", 443)}
    await asyncio.wait_for(client.app(scope, receive, send), 5)
    for _ in range(60):
        if sender.sent:
            break
        await asyncio.sleep(0.05)
    assert [p["title"] for _, p in sender.sent] == ["단비 답변이 준비됐어요"]
