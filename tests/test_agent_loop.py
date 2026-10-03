import asyncio
import time
from datetime import date

from danbi.agent.loop import Agent, FinalEvent, TokenEvent, ToolEndEvent, ToolStartEvent
from danbi.agent.tools import Tool, ToolError, ToolRegistry
from danbi.llm.base import LLMError, ToolSpec

from .fakes import FakeProvider, Reply

SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}


def make_tools(**funcs) -> ToolRegistry:
    return ToolRegistry([Tool(ToolSpec(name, f"{name} 도구", SCHEMA), f) for name, f in funcs.items()])


async def collect(agent: Agent, text: str = "질문", **kw):
    return [ev async for ev in agent.run(text, today=date(2026, 10, 2), **kw)]


async def test_plain_answer_with_date_prefix():
    provider = FakeProvider([Reply(text="안녕하세요")])
    events = await collect(Agent(provider, make_tools()), "안녕")
    assert [e.text for e in events if isinstance(e, TokenEvent)] == ["안녕하세요"]
    final = events[-1]
    assert isinstance(final, FinalEvent) and final.text == "안녕하세요" and final.stop_reason == "end"
    assert provider.requests[0][0].text == "[오늘: 2026-10-02]\n안녕"


async def test_parallel_tool_calls_run_concurrently_and_keep_order():
    async def slow(q):
        await asyncio.sleep(0.3)
        return f"slow:{q}"

    def sync_tool(q):  # 동기 함수는 스레드에서 실행된다
        time.sleep(0.3)
        return f"sync:{q}"

    provider = FakeProvider([
        Reply(calls=[("slow", {"q": "a"}), ("sync_tool", {"q": "b"})]),
        Reply(text="답"),
    ])
    agent = Agent(provider, make_tools(slow=slow, sync_tool=sync_tool))
    t0 = time.monotonic()
    events = await collect(agent)
    assert time.monotonic() - t0 < 0.55  # 순차 실행이면 0.6초 이상

    starts = [e for e in events if isinstance(e, ToolStartEvent)]
    assert len(starts) == 1 and [c.name for c in starts[0].calls] == ["slow", "sync_tool"]
    tool_msg = provider.requests[1][-1]
    assert tool_msg.role == "tool"
    assert [r.content for r in tool_msg.tool_results] == ["slow:a", "sync:b"]
    assert events[-1].tool_calls_used == 2


async def test_tool_errors_become_results():
    def bad(q):
        raise ToolError("이 소스는 검색을 지원하지 않습니다")

    def crash(q):
        raise RuntimeError("boom")

    provider = FakeProvider([
        Reply(calls=[("bad", {"q": "x"}), ("crash", {"q": "x"}), ("nope", {"q": "x"}), ("bad", {})]),
        Reply(text="답"),
    ])
    events = await collect(Agent(provider, make_tools(bad=bad, crash=crash)))
    results = [e.result for e in events if isinstance(e, ToolEndEvent)]
    assert all(r.is_error for r in results)
    assert "지원하지 않습니다" in results[0].content
    assert "RuntimeError" in results[1].content
    assert "알 수 없는 도구" in results[2].content
    assert "필수 인자 누락" in results[3].content
    assert events[-1].text == "답"


async def test_tool_call_limit():
    calls = []

    def t(q):
        calls.append(q)
        return "ok"

    provider = FakeProvider([
        Reply(calls=[("t", {"q": "1"}), ("t", {"q": "2"})]),
        Reply(calls=[("t", {"q": "3"}), ("t", {"q": "4"})]),  # 상한 3 → 4는 차단
        Reply(text="지금까지 근거로 답"),
    ])
    events = await collect(Agent(provider, make_tools(t=t), max_tool_calls=3))
    assert calls == ["1", "2", "3"]
    blocked = [e.result for e in events if isinstance(e, ToolEndEvent)][-1]
    assert blocked.is_error and "상한" in blocked.content
    assert events[-1].text == "지금까지 근거로 답" and events[-1].tool_calls_used == 3


async def test_stops_when_model_ignores_limit():
    provider = FakeProvider([Reply(calls=[("t", {"q": "x"})]) for _ in range(5)])
    events = await collect(Agent(provider, make_tools(t=lambda q: "ok"), max_tool_calls=1))
    assert events[-1].stop_reason == "limit"
    assert len(provider.requests) == 3


async def test_timeout_cuts_slow_tool():
    async def hang(q):
        await asyncio.sleep(5)

    provider = FakeProvider([Reply(calls=[("hang", {"q": "x"})]), Reply(text="부분 답")])
    t0 = time.monotonic()
    events = await collect(Agent(provider, make_tools(hang=hang), timeout_seconds=0.3))
    assert time.monotonic() - t0 < 2
    assert [e.result for e in events if isinstance(e, ToolEndEvent)][0].is_error
    assert events[-1].text == "부분 답"


async def test_retryable_llm_error_is_retried(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    provider = FakeProvider([Reply(error=LLMError("429", retryable=True)), Reply(text="성공")])
    events = await collect(Agent(provider, make_tools()))
    assert events[-1].text == "성공"


async def test_fatal_llm_error_gives_fallback():
    provider = FakeProvider([Reply(error=LLMError("400 bad request"))])
    events = await collect(Agent(provider, make_tools()))
    assert events[-1].stop_reason == "error" and "400" in events[-1].error


async def test_history_is_carried_over():
    provider = FakeProvider([Reply(text="첫 답"), Reply(text="둘째 답")])
    agent = Agent(provider, make_tools())
    first = (await collect(agent, "첫 질문"))[-1]
    await collect(agent, "둘째 질문", history=first.messages)
    assert [m.role for m in provider.requests[1]] == ["user", "assistant", "user"]


_real_sleep = asyncio.sleep


async def _no_sleep(seconds, *a, **kw):
    await _real_sleep(0)
