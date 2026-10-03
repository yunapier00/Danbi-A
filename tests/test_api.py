"""API 서버: 가짜 LLM으로 SSE 이벤트·세션·요청 제한·추적 기록 검증 (API 비용 없음)."""

import json

from fastapi.testclient import TestClient

from danbi.agent.loop import Agent
from danbi.agent.tools import Tool, ToolRegistry
from danbi.api.main import RateLimiter, SessionStore, create_app
from danbi.llm.base import LLMError, ToolSpec
from danbi.ops import TraceRecorder, TraceStore

from .fakes import FakeProvider, Reply

SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
ITEM_RESULT = "[source: t / section: notice(공지)] 게시글 1\n제목: 졸업시험 공지\n작성일: 2026.09.22\nURL: https://x/post/1\n---\n본문"


def make_client(replies, *, limiter=None, sessions=None, store=None, token=None):
    tools = ToolRegistry([Tool(ToolSpec("get_item", "d", SCHEMA), lambda q: ITEM_RESULT, lambda a: f"게시글 '{a['q']}' 읽는 중")])
    provider = FakeProvider(replies)
    agent = Agent(provider, tools)
    recorder = TraceRecorder(store, agent) if store is not None else None
    app = create_app(agent, limiter=limiter, sessions=sessions, recorder=recorder, admin_token=token)
    return TestClient(app), provider


def events(resp) -> list[tuple[str, dict]]:
    out = []
    for block in resp.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_chat_streams_status_tokens_sources_done():
    store = TraceStore(None)
    client, _ = make_client([Reply(calls=[("get_item", {"q": "1"})]), Reply(text="신청 기한은 9/30입니다.")],
                            store=store)
    resp = client.post("/api/chat", json={"message": "졸업시험 기한?"})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    evs = events(resp)
    assert [e for e, _ in evs] == ["session", "status", "token", "sources", "done"]
    assert evs[1][1] == {"text": "게시글 '1' 읽는 중", "tools": ["get_item"]}
    assert evs[2][1]["text"] == "신청 기한은 9/30입니다."
    assert evs[3][1]["items"] == [{"title": "졸업시험 공지", "url": "https://x/post/1"}]
    assert evs[4][1]["tool_calls"] == 1 and evs[4][1]["stop_reason"] == "end"

    run_id = evs[4][1]["run_id"]
    detail = store.run_detail(run_id)
    assert detail["run"]["question"] == "졸업시험 기한?" and detail["run"]["channel"] == "web"
    assert detail["run"]["conversation_id"] == evs[0][1]["session_id"]
    assert [t["name"] for t in detail["tool_calls"]] == ["get_item"]
    assert detail["run"]["client_ip"] == "testclient"  # TestClient의 요청 주소


def test_session_carries_history_and_reset():
    client, provider = make_client([Reply(text="첫 답"), Reply(text="둘째 답"), Reply(text="새 대화")])
    sid = events(client.post("/api/chat", json={"message": "하나"}))[0][1]["session_id"]
    events(client.post("/api/chat", json={"message": "둘", "session_id": sid}))
    assert [m.role for m in provider.requests[1]] == ["user", "assistant", "user"]
    client.post("/api/reset", json={"session_id": sid})
    new_sid = events(client.post("/api/chat", json={"message": "셋", "session_id": sid}))[0][1]["session_id"]
    assert new_sid != sid and len(provider.requests[2]) == 1


def test_session_history_is_trimmed():
    store = SessionStore(max_turns=2)
    client, provider = make_client([Reply(text=f"답{i}") for i in range(4)], sessions=store)
    sid = None
    for i in range(4):
        sid = events(client.post("/api/chat", json={"message": f"질문{i}", "session_id": sid}))[0][1]["session_id"]
    users = [m.text for m in provider.requests[3] if m.role == "user"]
    assert len(users) == 3 and users[0].endswith("질문1")  # 직전 2턴 + 이번 질문


def test_fallback_answer_is_streamed_on_llm_error():
    client, _ = make_client([Reply(error=LLMError("400 bad"))])
    evs = events(client.post("/api/chat", json={"message": "q"}))
    assert evs[1] == ("token", {"text": "죄송합니다. 지금은 답변을 만들 수 없습니다. 잠시 후 다시 시도해 주세요."})
    assert evs[-1][0] == "done" and evs[-1][1]["stop_reason"] == "error"


def test_rate_limit_and_validation():
    client, _ = make_client([Reply(text="a"), Reply(text="b")], limiter=RateLimiter(max_requests=1, window=60))
    assert client.post("/api/chat", json={"message": "q"}).status_code == 200
    assert client.post("/api/chat", json={"message": "q"}).status_code == 429
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 1001}).status_code == 422


def test_index_and_health():
    client, _ = make_client([])
    assert "단비" in client.get("/").text
    assert client.get("/api/health").json() == {"ok": True}  # 내부 정보(도구 목록)는 노출하지 않는다


# --- 피드백·개발자 API -----------------------------------------------------------------

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_feedback_is_stored():
    store = TraceStore(None)
    client, _ = make_client([Reply(text="답")], store=store)
    run_id = events(client.post("/api/chat", json={"message": "q"}))[-1][1]["run_id"]
    assert client.post("/api/feedback", json={"run_id": run_id, "rating": 1, "comment": "좋아요"}).status_code == 200
    assert client.post("/api/feedback", json={"run_id": "nope", "rating": -1}).status_code == 404
    assert store.run_detail(run_id)["feedback"][0]["rating"] == 1


def test_admin_requires_token_and_audits():
    store = TraceStore(None)
    client, _ = make_client([Reply(calls=[("get_item", {"q": "1"})]), Reply(text="답")], store=store, token=TOKEN)
    run_id = events(client.post("/api/chat", json={"message": "졸업시험"}))[-1][1]["run_id"]

    assert client.get("/api/admin/overview").status_code == 401
    assert client.get("/api/admin/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ov = client.get("/api/admin/overview?range=24h", headers=AUTH).json()
    assert ov["totals"]["runs"] == 1 and ov["bucket"] == "hour" and ov["tools"][0]["name"] == "get_item"
    runs = client.get("/api/admin/runs?q=졸업", headers=AUTH).json()
    assert runs["total"] == 1 and runs["items"][0]["id"] == run_id
    detail = client.get(f"/api/admin/runs/{run_id}", headers=AUTH).json()
    assert detail["sources"][0]["url"] == "https://x/post/1"
    prompt = client.get(f"/api/admin/prompts/{detail['run']['system_hash']}", headers=AUTH).json()
    assert prompt["kind"] == "system" and "단비" in prompt["content"]
    export = client.get("/api/admin/export?range=all", headers=AUTH)
    assert export.status_code == 200 and json.loads(export.text.splitlines()[0])["run"]["id"] == run_id

    audit = client.get("/api/admin/audit", headers=AUTH).json()
    actions = [a["action"] for a in audit["items"]]
    assert {"auth_failed", "view_run", "view_prompt", "export"} <= set(actions)
    assert audit["verify"]["ok"] is True
    assert "단비" in client.get("/dev").text


def test_admin_disabled_without_token():
    client, _ = make_client([], store=TraceStore(None), token=None)
    assert client.get("/api/admin/overview", headers=AUTH).status_code == 503


def test_client_ip_proxy_header_only_when_trusted():
    from danbi.api.main import client_ip

    class Req:
        def __init__(self, fwd):
            self.headers = {"x-forwarded-for": fwd} if fwd else {}
            self.client = type("C", (), {"host": "10.0.0.5"})()

    assert client_ip(Req("1.2.3.4, 203.0.113.7")) == "10.0.0.5"            # 기본: 헤더 무시 (위조 방지)
    # 사용자가 넣은 왼쪽 값(1.2.3.4)이 아니라 프록시가 덧붙인 오른쪽 값을 쓴다
    assert client_ip(Req("1.2.3.4, 203.0.113.7"), trust_proxy=True) == "203.0.113.7"
    assert client_ip(Req("203.0.113.7, 10.0.0.1"), trust_proxy=True, hops=2) == "203.0.113.7"
    assert client_ip(Req("203.0.113.7"), trust_proxy=True, hops=3) == "203.0.113.7"
    assert client_ip(Req(None), trust_proxy=True) == "10.0.0.5"


def test_ip_not_stored_when_disabled():
    store = TraceStore(None)
    tools = ToolRegistry([])
    agent = Agent(FakeProvider([Reply(text="답")]), tools)
    client = TestClient(create_app(agent, recorder=TraceRecorder(store, agent), store_client_ip=False))
    run_id = events(client.post("/api/chat", json={"message": "q"}))[-1][1]["run_id"]
    assert store.run_detail(run_id)["run"]["client_ip"] is None


def test_web_not_built_shows_instructions(monkeypatch, tmp_path):
    import danbi.api.main as main
    monkeypatch.setattr(main, "WEB", tmp_path / "missing")
    client, _ = make_client([])
    res = client.get("/")
    assert res.status_code == 503 and "npm run build" in res.text
    assert client.get("/dev").status_code == 503


# --- 배포 대비 방어 장치 ---------------------------------------------------------------------

from danbi.api.main import MultiLimiter, kst_midnight
from danbi.config import LimitSettings


def test_multi_limiter_does_not_spend_quota_when_blocked():
    minute, day = RateLimiter(2, 60), RateLimiter(3, 86400)
    lim = MultiLimiter(minute, day)
    assert lim.allow("a") and lim.allow("a") and not lim.allow("a")   # 분당 2회
    assert len(day._hits["a"]) == 2                                    # 막힌 요청은 하루 몫을 쓰지 않는다


def test_daily_budget_blocks_web_chat():
    store = TraceStore(None)
    tools = ToolRegistry([])
    agent = Agent(FakeProvider([Reply(text="답")] * 3), tools)
    app = create_app(agent, recorder=TraceRecorder(store, agent), limits=LimitSettings(daily_questions=1))
    client = TestClient(app)
    assert events(client.post("/api/chat", json={"message": "q"}))[-1][0] == "done"
    res = client.post("/api/chat", json={"message": "q2"})
    assert res.status_code == 429 and "오늘" in res.json()["detail"]
    assert store.usage_since(kst_midnight())["runs"] == 1


async def test_concurrency_slot_full_returns_busy_event():
    import asyncio
    import time as _t

    import httpx

    def slow(q):            # 첫 질문이 슬롯을 잡고 있는 동안 두 번째 질문을 보낸다
        _t.sleep(0.5)
        return "ok"

    tools = ToolRegistry([Tool(ToolSpec("slow", "d", SCHEMA), slow)])
    agent = Agent(FakeProvider([Reply(calls=[("slow", {"q": "1"})]), Reply(text="답")]), tools)
    app = create_app(agent, limits=LimitSettings(max_concurrent=1))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        first = asyncio.create_task(c.post("/api/chat", json={"message": "a"}))
        await asyncio.sleep(0.15)
        second = await c.post("/api/chat", json={"message": "b"})
        first_res = await first
    assert events(second)[-1] == ("error", {"message": "지금 질문이 많아요. 잠시 후 다시 시도해 주세요."})
    assert events(first_res)[-1][0] == "done"


def test_security_headers_and_docs_off():
    client, _ = make_client([Reply(text="답")])
    res = client.get("/api/health")
    assert "frame-ancestors 'none'" in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" not in res.headers
    assert client.get("/api/health", headers={"x-forwarded-proto": "https"}).headers["strict-transport-security"]
    assert client.get("/api/docs").status_code == 404 and client.get("/api/openapi.json").status_code == 404


def test_admin_locks_out_after_repeated_failures():
    store = TraceStore(None)
    tools = ToolRegistry([])
    agent = Agent(FakeProvider([]), tools)
    client = TestClient(create_app(agent, recorder=TraceRecorder(store, agent), admin_token=TOKEN,
                                   limits=LimitSettings(admin_auth_failures=2)))
    bad = {"Authorization": "Bearer nope"}
    assert [client.get("/api/admin/overview", headers=bad).status_code for _ in range(3)] == [401, 401, 429]
    assert client.get("/api/admin/overview", headers=AUTH).status_code == 429   # 잠긴 IP는 맞는 토큰도 잠시 막는다
    assert sum(a["action"] == "auth_failed" for a in store.audit_rows()) == 2   # 감사 로그가 무한정 쌓이지 않는다
