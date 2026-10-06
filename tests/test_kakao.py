import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from danbi.agent.loop import Agent
from danbi.agent.tools import Tool, ToolRegistry
from danbi.api.kakao import allowed_callback, user_key_of
from danbi.api.kakao_format import MAX_OUTPUTS, MAX_TEXT, answer_response, md_to_text, split_text
from danbi.api.main import create_app
from danbi.config import KakaoSettings, LimitSettings
from danbi.llm.base import ToolSpec
from danbi.ops import TraceRecorder, TraceStore

from .fakes import FakeProvider, Reply
from .test_api import ITEM_RESULT, SCHEMA, events

SECRET = "s3cret"
HEAD = {"x-danbi-kakao-secret": SECRET}
CALLBACK = "https://bot-api.kakao.com/v1/callback/abc"


def skill_body(text: str, uid: str = "u1", callback: str | None = None) -> dict:
    ur = {"utterance": text, "user": {"id": uid, "type": "botUserKey"}}
    if callback:
        ur["callbackUrl"] = callback
    return {"userRequest": ur, "bot": {"id": "b"}, "action": {"params": {}}}


def make_app(replies, monkeypatch, *, secret=SECRET, limits=None, http=None, store=None, memory=True):
    if secret:
        monkeypatch.setenv("KAKAO_SKILL_SECRET", secret)
    else:
        monkeypatch.delenv("KAKAO_SKILL_SECRET", raising=False)
    monkeypatch.delenv("KAKAO_USER_SALT", raising=False)
    tools = ToolRegistry([Tool(ToolSpec("get_item", "d", SCHEMA), lambda q: ITEM_RESULT)])
    agent = Agent(FakeProvider(replies), tools)
    store = store or TraceStore(None)
    app = create_app(agent, recorder=TraceRecorder(store, agent), limits=limits or LimitSettings(),
                     kakao=KakaoSettings(), kakao_http=http, memory=memory)
    app.state.provider = agent.provider
    return app, store


def texts(res: dict) -> list[str]:
    return [o["simpleText"]["text"] for o in res["template"]["outputs"] if "simpleText" in o]


# ---- 응답 변환 ----

def test_md_to_text_flattens_markdown():
    md = "## 신청 방법\n\n**기한**은 *9/30*까지입니다.\n- [공지](https://x/1) 참고\n\n| 구분 | 날짜 |\n|---|---|\n| 신청 | 9/30 |\n"
    out = md_to_text(md)
    assert "■ 신청 방법" in out and "기한은 9/30까지입니다." in out
    assert "• 공지 (https://x/1) 참고" in out and "• 구분: 신청 · 날짜: 9/30" in out
    assert "*" not in out and "|" not in out


def test_split_and_answer_respect_kakao_limits():
    long = "\n\n".join("가" * 600 for _ in range(10))
    assert all(len(c) <= MAX_TEXT for c in split_text(long))
    links = [{"title": f"아주 긴 공지 제목 번호 {i}", "url": f"https://x/{i}"} for i in range(5)]
    res = answer_response(long, links, remaining=2)
    outs = res["template"]["outputs"]
    assert len(outs) == MAX_OUTPUTS and "textCard" in outs[-1]
    assert all(len(t) <= MAX_TEXT for t in texts(res)) and "일부만" in texts(res)[-1]
    card = outs[-1]["textCard"]
    assert len(card["buttons"]) == 3 and all(len(b["label"]) <= 14 for b in card["buttons"])
    assert res["template"]["quickReplies"][0]["messageText"] == "새 대화"
    short = answer_response("답", [], remaining=1)
    assert texts(short) == ["답\n\n오늘 남은 질문: 1회"]


def test_user_key_and_callback_host():
    assert user_key_of("u1", "a") == user_key_of("u1", "a") != user_key_of("u1", "b")
    assert "u1" not in user_key_of("u1", "a")
    assert allowed_callback(CALLBACK, ["kakao.com"])
    assert not allowed_callback("http://bot-api.kakao.com/x", ["kakao.com"])       # https만
    assert not allowed_callback("https://evilkakao.com/x", ["kakao.com"])
    assert not allowed_callback("https://kakao.com.evil.io/x", ["kakao.com"])


# ---- 엔드포인트 ----

def test_endpoint_absent_without_secret_and_rejects_bad_secret(monkeypatch):
    app, _ = make_app([Reply(text="답")], monkeypatch, secret=None)
    assert TestClient(app).post("/api/kakao/skill", json=skill_body("q")).status_code in (404, 405)
    app, store = make_app([Reply(text="답")], monkeypatch)
    client = TestClient(app)
    assert client.post("/api/kakao/skill", json=skill_body("q")).status_code == 401
    assert client.post("/api/kakao/skill", json=skill_body("q"), headers={"x-danbi-kakao-secret": "x"}).status_code == 401
    assert store.list_runs()["total"] == 0


def test_sync_answer_records_hashed_user(monkeypatch):
    app, store = make_app([Reply(calls=[("get_item", {"q": "1"})]), Reply(text="**기한**은 9/30입니다.")], monkeypatch)
    res = TestClient(app).post("/api/kakao/skill", json=skill_body("졸업시험 기한?"), headers=HEAD).json()
    assert res["version"] == "2.0"
    assert texts(res)[0].startswith("기한은 9/30입니다.") and "오늘 남은 질문: 2회" in texts(res)[0]
    card = res["template"]["outputs"][-1]["textCard"]
    assert card["buttons"][0]["webLinkUrl"] == "https://x/post/1"
    run = store.list_runs()["items"][0]
    assert run["channel"] == "kakao"
    detail = store.run_detail(run["id"])["run"]
    assert detail["user_key"] == user_key_of("u1", SECRET) and detail["client_ip"] is None


def test_reset_clears_conversation(monkeypatch):
    app, _ = make_app([Reply(text="첫 답"), Reply(text="새 답")], monkeypatch)
    client = TestClient(app)
    client.post("/api/kakao/skill", json=skill_body("하나"), headers=HEAD)
    sessions = app.state.sessions
    key = user_key_of("u1", SECRET)
    assert sessions.get_or_create(key).history
    res = client.post("/api/kakao/skill", json=skill_body("새 대화"), headers=HEAD).json()
    assert "새 대화" in texts(res)[0] and not sessions.get_or_create(key).history


def test_daily_limit_three_per_user(monkeypatch):
    app, store = make_app([Reply(text="답")] * 5, monkeypatch, limits=LimitSettings(per_user_per_day=3))
    client = TestClient(app)
    seen = [texts(client.post("/api/kakao/skill", json=skill_body(f"q{i}"), headers=HEAD).json())[0] for i in range(4)]
    assert [s.rsplit(" ", 1)[-1] for s in seen[:3]] == ["2회", "1회", "0회"]
    assert "3번까지" in seen[3]                                    # 4번째는 200 + 안내 문구
    assert store.list_runs()["total"] == 3
    other = client.post("/api/kakao/skill", json=skill_body("q", uid="u2"), headers=HEAD).json()
    assert "오늘 남은 질문: 2회" in texts(other)[0]                  # 다른 사람은 따로 센다


def test_web_daily_limit_three_per_ip(monkeypatch):
    app, _ = make_app([Reply(text="답")] * 5, monkeypatch, limits=LimitSettings(per_user_per_day=3))
    client = TestClient(app)
    remaining = [events(client.post("/api/chat", json={"message": f"q{i}"}))[-1][1]["remaining"] for i in range(3)]
    assert remaining == [2, 1, 0]
    res = client.post("/api/chat", json={"message": "q4"})
    assert res.status_code == 429 and "3번까지" in res.json()["detail"]


async def test_callback_flow_posts_answer(monkeypatch):
    sent: list[tuple[str, dict]] = []

    def handler(request: httpx.Request):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"taskId": "t", "status": "SUCCESS"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app, store = make_app([Reply(calls=[("get_item", {"q": "1"})]), Reply(text="콜백 답")], monkeypatch, http=http)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        res = (await c.post("/api/kakao/skill", json=skill_body("q", callback=CALLBACK), headers=HEAD)).json()
        assert res["useCallback"] is True and res["data"]["text"]
        await asyncio.gather(*list(app.state.kakao_tasks))
    assert len(sent) == 1 and sent[0][0] == CALLBACK
    assert texts(sent[0][1])[0].startswith("콜백 답")
    assert store.list_runs()["items"][0]["status"] == "ok"
    await http.aclose()


async def test_disallowed_callback_host_falls_back_to_sync(monkeypatch):
    app, _ = make_app([Reply(text="바로 답")], monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        res = (await c.post("/api/kakao/skill", json=skill_body("q", callback="https://evil.example/cb"),
                            headers=HEAD)).json()
    assert "useCallback" not in res and texts(res)[0].startswith("바로 답")


@pytest.mark.parametrize("body", [{}, {"userRequest": {"utterance": "q"}}])
def test_missing_user_is_handled(monkeypatch, body):
    app, _ = make_app([Reply(text="답")], monkeypatch)
    res = TestClient(app).post("/api/kakao/skill", json=body, headers=HEAD)
    assert res.status_code == 200 and "사용자" in texts(res.json())[0]


def test_service_daily_cap_counts_web_and_kakao(monkeypatch):
    app, store = make_app([Reply(text="답")] * 3, monkeypatch, limits=LimitSettings(daily_questions=1))
    client = TestClient(app)
    assert events(client.post("/api/chat", json={"message": "q"}))[-1][0] == "done"
    res = client.post("/api/kakao/skill", json=skill_body("q"), headers=HEAD).json()
    assert "모두 썼어요" in texts(res)[0] and store.list_runs()["total"] == 1


def test_kakao_memory_off_answers_each_question_alone(monkeypatch):
    app, _ = make_app([Reply(text="첫 답"), Reply(text="둘째 답")], monkeypatch, memory=False)
    client = TestClient(app)
    client.post("/api/kakao/skill", json=skill_body("첫 질문"), headers=HEAD)
    client.post("/api/kakao/skill", json=skill_body("둘째 질문"), headers=HEAD)
    assert [m.role for m in app.state.provider.requests[-1]] == ["user"]
