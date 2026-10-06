"""로그인 사용자별 대화 기록: 목록·내용 조회, 남의 대화 차단, 지난 대화 이어 쓰기."""

from fastapi.testclient import TestClient

from danbi.agent.loop import Agent
from danbi.agent.tools import Tool, ToolRegistry
from danbi.api.main import create_app, history_from_runs
from danbi.config import AuthSettings, LimitSettings
from danbi.llm.base import ToolSpec
from danbi.ops import TraceRecorder, TraceStore

from .fakes import FakeProvider, Reply
from .test_api import ITEM_RESULT, SCHEMA, events
from .test_auth import FakeGoogle, env, login  # noqa: F401  (env는 pytest fixture)


def make(env, replies, memory=True):
    store = TraceStore(None)
    tools = ToolRegistry([Tool(ToolSpec("get_item", "d", SCHEMA), lambda q: ITEM_RESULT)])
    provider = FakeProvider(replies)
    agent = Agent(provider, tools)
    google = FakeGoogle()
    app = create_app(agent, recorder=TraceRecorder(store, agent), auth=AuthSettings(), auth_http=google.http,
                     auth_verifier=google.verify, limits=LimitSettings(per_user_per_day=10), memory=memory)
    client = TestClient(app, base_url="https://testserver")
    login(client, google)
    return client, app, provider, google


def ask(client, text, sid=None):
    evs = events(client.post("/api/chat", json={"message": text, "session_id": sid}))
    return evs[0][1]["session_id"], evs


def test_list_and_open_conversations(env):
    client, _, _, _ = make(env, [Reply(calls=[("get_item", {"q": "1"})]), Reply(text="**9/30**까지입니다."),
                                 Reply(text="두 번째 답"), Reply(text="다른 대화 답")])
    sid, _ = ask(client, "졸업시험 기한?")
    ask(client, "그럼 장소는?", sid)
    other, _ = ask(client, "학식 메뉴?")
    items = client.get("/api/conversations").json()["items"]
    assert [(c["id"], c["title"], c["turns"]) for c in items] == [(other, "학식 메뉴?", 1), (sid, "졸업시험 기한?", 2)]
    msgs = client.get(f"/api/conversations/{sid}").json()["messages"]
    assert [(m["turn"], m["question"], m["answer"]) for m in msgs] == [
        (1, "졸업시험 기한?", "**9/30**까지입니다."), (2, "그럼 장소는?", "두 번째 답")]
    assert msgs[0]["sources"] == [{"title": "졸업시험 공지", "url": "https://x/post/1"}] and msgs[1]["sources"] == []
    assert msgs[0]["id"] and msgs[0]["status"] == "ok" and msgs[0]["tool_calls"] == 1
    assert "user_key" not in msgs[0]


def test_other_users_cannot_see_or_continue(env):
    client, app, provider, google = make(env, [Reply(text="내 답"), Reply(text="남의 답")])
    sid, _ = ask(client, "내 질문")
    other = TestClient(app, base_url="https://testserver")
    login(other, google, sub="999", email="other@dankook.ac.kr")
    assert other.get("/api/conversations").json()["items"] == []
    assert other.get(f"/api/conversations/{sid}").status_code == 404
    app.state.sessions.reset(sid)                       # 메모리에서 사라진 뒤 남이 그 ID로 이어 쓰려 해도
    other_sid, _ = ask(other, "끼어들기", sid)
    assert other_sid != sid and [m.text for m in provider.requests[-1] if m.role == "assistant"] == []


def test_resume_old_conversation_after_memory_loss(env):
    client, app, provider, _ = make(env, [Reply(text="첫 답"), Reply(text="이어서 답")])
    sid, _ = ask(client, "첫 질문")
    app.state.sessions.reset(sid)                       # 1시간 지나 세션이 사라지거나 서버가 재시작한 상황
    again, evs = ask(client, "이어서 질문", sid)
    assert again == sid and evs[-1][0] == "done"
    texts = [(m.role, m.text) for m in provider.requests[-1]]
    assert ("user", "첫 질문") in texts and ("assistant", "첫 답") in texts   # 저장된 기록으로 맥락을 이어 감
    msgs = client.get(f"/api/conversations/{sid}").json()["messages"]
    assert [m["turn"] for m in msgs] == [1, 2]


def test_history_requires_login(env):
    client, app, _, _ = make(env, [Reply(text="답")])
    anon = TestClient(app, base_url="https://testserver")
    assert anon.get("/api/conversations").status_code == 401
    assert anon.get("/api/conversations/whatever").status_code == 401


def test_history_from_runs_skips_unanswered():
    runs = [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": None}, {"question": "q3", "answer": "a3"}]
    assert [(m.role, m.text) for m in history_from_runs(runs)] == [
        ("user", "q1"), ("assistant", "a1"), ("user", "q3"), ("assistant", "a3")]


def test_memory_off_sends_no_previous_turns_but_keeps_history(env):
    client, app, provider, _ = make(env, [Reply(text="첫 답"), Reply(text="둘째 답"), Reply(text="셋째 답")], memory=False)
    sid, _ = ask(client, "첫 질문")
    again, _ = ask(client, "둘째 질문", sid)
    assert again == sid                                             # 같은 대화로 묶여 저장되고
    assert [m.role for m in provider.requests[-1]] == ["user"]      # LLM에는 이번 질문만 간다
    assert "둘째 질문" in provider.requests[-1][0].text
    app.state.sessions.reset(sid)                                   # 메모리에서 사라진 대화를 이어 써도
    ask(client, "셋째 질문", sid)
    assert [m.role for m in provider.requests[-1]] == ["user"]      # DB에서 되살리지 않는다
    msgs = client.get(f"/api/conversations/{sid}").json()["messages"]
    assert [m["question"] for m in msgs] == ["첫 질문", "둘째 질문", "셋째 질문"]


def test_memory_setting_defaults_off():
    from danbi.config import AgentSettings, load_settings
    assert AgentSettings().memory is False and load_settings().agent.memory is False
