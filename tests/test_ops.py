"""추적 저장소·기록기·출처 추출 (네트워크·API 없음)."""

import asyncio
import time

import pytest

from danbi.agent.loop import Agent
from danbi.agent.tools import Tool, ToolRegistry
from danbi.llm.base import LLMError, ToolSpec
from danbi.ops import TraceRecorder, TraceStore, new_run_id
from danbi.ops.sources import extract_sources, mark_cited

from .fakes import FakeProvider, Reply

SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
RAG_RESULT = """[source: campus_rules] 문서 검색 결과 2건 — 질의: 셔틀
(1) 셔틀버스 정보 [기준일 미상] > 운행 기본 정보 | 거리 0.410
첫차 08:15
(2) 학칙 [2026.05.07 개정본] > 제47조 | 거리 0.500
졸업"""
WEB_RESULT = "[source: sw / section: notice(학과공지)] 게시글 7\n제목: 졸업시험 공지\n작성일: 2026.09.22\nURL: https://x/7\n---\n본문"


def test_extract_and_cite_sources():
    rag = extract_sources("search_knowledge", RAG_RESULT)
    assert [(r.kind, r.source_id, r.title) for r in rag] == [
        ("rag", "campus_rules", "셔틀버스 정보 [기준일 미상] > 운행 기본 정보"),
        ("rag", "campus_rules", "학칙 [2026.05.07 개정본] > 제47조"),
    ]
    web = extract_sources("get_item", WEB_RESULT)
    assert [(r.kind, r.source_id, r.title, r.url) for r in web] == [("web", "sw", "졸업시험 공지", "https://x/7")]
    refs = rag + web
    mark_cited(refs, "셔틀버스 정보에 따르면 첫차는 08:15입니다. 출처: https://x/7")
    assert [r.cited for r in refs] == [True, False, True]


def make_agent(replies, tools=None):
    tools = tools or ToolRegistry([
        Tool(ToolSpec("search_knowledge", "d", SCHEMA), lambda q: RAG_RESULT, lambda a: f"'{a['q']}' 검색 중"),
        Tool(ToolSpec("get_item", "d", SCHEMA), lambda q: WEB_RESULT),
    ])
    return Agent(FakeProvider(replies), tools)


async def drain(recorder, agent, question="질문", **kw):
    run_id = new_run_id()
    async for _ in recorder.record(agent.run(question), run_id=run_id, question=question, channel="cli", **kw):
        pass
    return run_id


async def test_recorder_writes_full_trace():
    store = TraceStore(None)
    agent = make_agent([
        Reply(calls=[("search_knowledge", {"q": "셔틀"}), ("get_item", {"q": "7"})]),
        Reply(text="셔틀버스 정보 기준 첫차는 08:15입니다."),
    ])
    rec = TraceRecorder(store, agent, {"input_per_mtok": 1.0, "output_per_mtok": 2.0})
    run_id = await drain(rec, agent, "셔틀 첫차?", conversation_id="conv1", tags={"k": "v"})

    d = store.run_detail(run_id)
    run = d["run"]
    assert (run["status"], run["channel"], run["turn"], run["tags"]) == ("ok", "cli", 1, {"k": "v"})
    assert run["llm_calls"] == 2 and run["tool_calls"] == 2 and run["tool_errors"] == 0
    assert run["input_tokens"] == 20 and run["output_tokens"] == 10   # FakeProvider: 호출당 10/5
    assert run["cost_usd"] == pytest.approx(20 / 1e6 * 1.0 + 10 / 1e6 * 2.0)
    assert run["first_token_ms"] is not None and run["latency_ms"] >= run["first_token_ms"]
    assert [c["seq"] for c in d["llm_calls"]] == [1, 2]
    assert d["llm_calls"][0]["tool_calls"][0]["name"] == "search_knowledge"
    assert {t["name"]: t["status_text"] for t in d["tool_calls"]}["search_knowledge"] == "'셔틀' 검색 중"
    assert all(t["llm_seq"] == 1 for t in d["tool_calls"])
    cited = {s["title"]: s["cited"] for s in d["sources"]}
    assert cited["셔틀버스 정보 [기준일 미상] > 운행 기본 정보"] == 1 and cited["졸업시험 공지"] == 0
    # 프롬프트·도구 정의 원문이 버전으로 남는다
    assert "단비" in store.prompt_version(run["system_hash"])["content"]
    assert "search_knowledge" in store.prompt_version(run["tools_hash"])["content"]


async def test_recorder_counts_turns_and_failures(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    store = TraceStore(None)
    agent = make_agent([Reply(error=LLMError("429", retryable=True)), Reply(text="둘째 시도 성공"),
                        Reply(error=LLMError("400 bad"))])
    rec = TraceRecorder(store, agent)
    first = await drain(rec, agent, conversation_id="c")
    second = await drain(rec, agent, conversation_id="c")
    d1, d2 = store.run_detail(first), store.run_detail(second)
    assert [(c["attempt"], c["error"] is not None) for c in d1["llm_calls"]] == [(0, True), (1, False)]
    assert d1["run"]["status"] == "ok" and d2["run"]["status"] == "error" and d2["run"]["turn"] == 2
    assert [r["turn"] for r in d2["conversation"]] == [1, 2]


async def test_aborted_stream_is_recorded():
    store = TraceStore(None)
    agent = make_agent([Reply(calls=[("get_item", {"q": "7"})]), Reply(text="답")])
    rec = TraceRecorder(store, agent)
    run_id = new_run_id()
    gen = rec.record(agent.run("q"), run_id=run_id, question="q", channel="web")
    await gen.__anext__()          # 첫 이벤트만 받고
    await gen.aclose()             # 클라이언트가 끊음
    assert store.run_detail(run_id)["run"]["status"] == "aborted"


async def test_recorder_never_breaks_the_answer(monkeypatch):
    store = TraceStore(None)
    agent = make_agent([Reply(text="답")])
    rec = TraceRecorder(store, agent)

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "add_llm_call", boom)
    monkeypatch.setattr(store, "finish_run", boom)
    texts = [ev.text async for ev in rec.record(agent.run("q"), run_id="r", question="q", channel="cli")
             if hasattr(ev, "text") and type(ev).__name__ == "FinalEvent"]
    assert texts == ["답"]


async def test_overview_and_list_filters():
    store = TraceStore(None)
    agent = make_agent([Reply(calls=[("get_item", {"q": "7"})]), Reply(text="졸업시험 공지 https://x/7"),
                        Reply(text="그냥 답")])
    rec = TraceRecorder(store, agent)
    a = await drain(rec, agent, "졸업 질문")
    b = await drain(rec, agent, "다른 질문")
    store.add_feedback(a, 1, None)
    store.add_feedback(b, -1, "틀림")
    ov = store.overview(since=time.time() - 3600, bucket="hour")
    t = ov["totals"]
    assert (t["runs"], t["failed"], t["feedback_up"], t["feedback_down"]) == (2, 0, 1, 1)
    assert t["source_refs"] == 1 and t["source_cited"] == 1
    assert ov["tools"][0]["name"] == "get_item" and ov["series"][0]["runs"] == 2
    assert ov["sources"][0]["source_id"] == "sw"
    assert store.list_runs(tool="get_item")["total"] == 1
    assert store.list_runs(q="다른")["items"][0]["id"] == b
    assert store.list_runs(status="error")["total"] == 0


def test_audit_chain_detects_tampering():
    store = TraceStore(None)
    store.audit("admin:x", "view_run", "r1")
    store.audit("admin:x", "export", "30d", {"rows": 3})
    store.audit("admin:x", "login", "/dev")
    assert store.verify_audit() == {"ok": True, "rows": 3, "broken_at": None}
    store._exec("UPDATE audit_log SET target = 'r9' WHERE id = 2")
    assert store.verify_audit() == {"ok": False, "rows": 3, "broken_at": 2}


async def test_purge_keeps_audit_log():
    store = TraceStore(None)
    agent = make_agent([Reply(text="답")])
    run_id = await drain(TraceRecorder(store, agent), agent)
    store.audit("admin:x", "view_run", run_id)
    store._exec("UPDATE runs SET started_at = started_at - 400 * 86400")
    assert store.purge(older_than_days=180) == 1
    assert store.run_detail(run_id) is None and store.verify_audit()["rows"] == 1


_real_sleep = asyncio.sleep


async def _no_sleep(seconds, *a, **kw):
    await _real_sleep(0)


def test_board_list_link_after_header():
    text = ("[source: dkupa / section: notice(공지사항)] 게시판: https://cms.dankook.ac.kr/web/dkupa/-8\n"
            "최신 글 10건 (전체 243건):\n- [1] 2026.09.30 | 공지")
    refs = extract_sources("latest_items", text)
    assert [(r.kind, r.source_id, r.title, r.url) for r in refs] == [
        ("web", "dkupa", "dkupa 공지사항", "https://cms.dankook.ac.kr/web/dkupa/-8")]
    multi = "[source: polisci / dataset: professors] 조건: 없음 — 7건\n원문: https://a/-5, https://a/-6\n- x"
    assert [r.url for r in extract_sources("query_data", multi)] == ["https://a/-5", "https://a/-6"]


def test_migrates_v1_db_and_purges_ip_first(tmp_path):
    import sqlite3
    db = tmp_path / "old.sqlite"
    con = sqlite3.connect(db)   # client_ip 컬럼이 없던 v1 스키마
    con.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, conversation_id TEXT, turn INTEGER, channel TEXT NOT NULL, "
                "question TEXT NOT NULL, answer TEXT, status TEXT NOT NULL, stop_reason TEXT, error TEXT, provider TEXT, "
                "model TEXT, system_hash TEXT, tools_hash TEXT, started_at REAL NOT NULL, ended_at REAL, latency_ms INTEGER, "
                "first_token_ms INTEGER, llm_calls INTEGER DEFAULT 0, tool_calls INTEGER DEFAULT 0, tool_errors INTEGER DEFAULT 0, "
                "input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cached_tokens INTEGER DEFAULT 0, "
                "cost_usd REAL, tags TEXT)")
    con.commit()
    con.close()
    store = TraceStore(db)
    common = dict(conversation_id=None, channel="web", question="q", provider="p", model="m",
                  system_hash="s", tools_hash="t")
    store.start_run("old", started_at=time.time() - 100 * 86400, client_ip="1.2.3.4", **common)
    store.start_run("new", started_at=time.time(), client_ip="5.6.7.8", **common)
    assert store.purge(older_than_days=180, ip_older_than_days=90) == 0
    assert store.run_detail("old")["run"]["client_ip"] is None      # 실행은 남고 IP만 비움
    assert store.run_detail("new")["run"]["client_ip"] == "5.6.7.8"
    store.finish_run("new", status="ok", stop_reason="end", answer="a", error=None, ended_at=time.time(),
                     first_token_at=None, input_tokens=0, output_tokens=0, cached_tokens=0, cost_usd=None)
    assert [r["id"] for r in store.list_runs(q="5.6.7.8")["items"]] == ["new"]   # IP로 검색
    assert store.overview()["totals"]["client_ips"] == 1
