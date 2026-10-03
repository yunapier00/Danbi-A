"""단비 에이전트 루프 (공급자 중립).

LLM 호출 → 도구 호출이 있으면 병렬 실행 → 결과를 대화에 추가 → 반복.
도구 호출 상한·시간 상한에 닿으면 남은 호출에 오류 결과를 돌려주고 지금까지의 근거로 답하게 한다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date

from ..llm.base import (
    Done,
    LLMError,
    LLMEvent,
    LLMOptions,
    LLMProvider,
    Message,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)
from .prompts import SYSTEM_PROMPT
from .tools.registry import ToolRegistry

log = logging.getLogger(__name__)

FALLBACK_ANSWER = "죄송합니다. 지금은 답변을 만들 수 없습니다. 잠시 후 다시 시도해 주세요."
LIMIT_ANSWER = "검색 횟수 상한에 도달해 답변을 마무리하지 못했습니다. 질문을 더 구체적으로 나눠서 다시 물어봐 주세요."


# --- 에이전트 이벤트 (API 서버가 SSE로 변환) -------------------------------------

@dataclass
class TokenEvent:
    text: str


@dataclass
class ToolStartEvent:
    calls: list[ToolCall]  # 동시에 실행되는 호출 묶음
    llm_seq: int = 0       # 이 호출을 요청한 LLM 호출 번호


@dataclass
class ToolEndEvent:
    result: ToolResult
    started: float = 0.0   # 벽시계 시각 (time.time) — 추적·워터폴용
    ended: float = 0.0
    llm_seq: int = 0


@dataclass
class LLMCallEvent:
    """LLM 요청 1회(재시도 포함 각 시도)가 끝날 때마다 나온다. 추적(ops) 기록용."""
    seq: int               # 질문 안에서 몇 번째 LLM 호출인지 (1부터)
    attempt: int           # 재시도 번호 (0 = 첫 시도)
    started: float
    ended: float
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: str | None = None


@dataclass
class _Attempt:
    attempt: int
    started: float
    ended: float
    error: str | None = None


@dataclass
class FinalEvent:
    text: str
    messages: list[Message]  # 이번 질문까지 포함한 전체 대화 기록 (다음 질문의 history)
    stop_reason: str         # end | max_tokens | refused | limit | error
    tool_calls_used: int
    usage: Usage = field(default_factory=Usage)
    elapsed: float = 0.0
    error: str | None = None


AgentEvent = TokenEvent | ToolStartEvent | ToolEndEvent | LLMCallEvent | FinalEvent


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        *,
        system: str = SYSTEM_PROMPT,
        options: LLMOptions | None = None,
        max_tool_calls: int = 10,
        timeout_seconds: float = 60,
        max_llm_retries: int = 2,
    ):
        self.provider = provider
        self.tools = tools
        self.system = system
        self.options = options or LLMOptions()
        self.max_tool_calls = max_tool_calls
        self.timeout_seconds = timeout_seconds
        self.max_llm_retries = max_llm_retries

    async def run(
        self,
        user_text: str,
        history: list[Message] | None = None,
        today: date | None = None,
    ) -> AsyncIterator[AgentEvent]:
        today = today or date.today()
        # 날짜는 시스템 프롬프트가 아니라 사용자 메시지에 붙인다 (프롬프트 캐싱 유지)
        messages = list(history or []) + [Message(role="user", text=f"[오늘: {today.isoformat()}]\n{user_text}")]
        start = time.monotonic()
        deadline = start + self.timeout_seconds
        used = 0
        blocked_rounds = 0
        usage = Usage()

        def final(text: str, stop: str, error: str | None = None) -> FinalEvent:
            return FinalEvent(text, messages, stop, used, usage, time.monotonic() - start, error)

        seq = 0
        while True:
            seq += 1
            done: Done | None = None
            last: _Attempt | None = None
            try:
                async for ev in self._stream_with_retry(messages):
                    if isinstance(ev, TextDelta):
                        yield TokenEvent(ev.text)
                    elif isinstance(ev, Done):
                        done = ev
                    elif isinstance(ev, _Attempt):
                        last = ev
                        if ev.error:
                            yield LLMCallEvent(seq, ev.attempt, ev.started, ev.ended, error=ev.error)
            except LLMError as e:
                log.error("LLM 호출 실패: %s", e)
                yield final(FALLBACK_ANSWER, "error", str(e))
                return
            if done is None:
                yield final(FALLBACK_ANSWER, "error", "LLM 응답이 Done 없이 끝났습니다")
                return
            if last is not None:
                yield LLMCallEvent(seq, last.attempt, last.started, last.ended, done.usage, done.stop_reason,
                                   done.message.text, list(done.message.tool_calls))

            usage += done.usage
            messages.append(done.message)
            if done.stop_reason != "tool_calls":
                yield final(done.message.text, done.stop_reason)
                return
            if blocked_rounds:  # 상한을 알렸는데도 또 도구를 부르면 끝낸다
                yield final(done.message.text or LIMIT_ANSWER, "limit")
                return

            calls = done.message.tool_calls
            remaining = deadline - time.monotonic()
            allowed = max(0, self.max_tool_calls - used) if remaining > 0 else 0
            run_calls = calls[:allowed]
            if len(run_calls) < len(calls):
                blocked_rounds += 1

            if run_calls:
                yield ToolStartEvent(run_calls, seq)
            timed = await self._execute(run_calls, timeout=remaining)
            used += len(run_calls)
            limit_msg = (
                f"도구 호출 상한({self.max_tool_calls}회)에 도달했습니다." if remaining > 0
                else f"시간 상한({self.timeout_seconds:.0f}초)에 도달했습니다."
            ) + " 더 이상 도구를 호출하지 말고 지금까지 찾은 근거로 답변하세요."
            now = time.time()
            timed += [(ToolResult(c.id, c.name, limit_msg, True), now, now) for c in calls[allowed:]]

            for r, t0, t1 in timed:
                yield ToolEndEvent(r, t0, t1, seq)
            messages.append(Message(role="tool", tool_results=[r for r, _, _ in timed]))

    async def _stream_with_retry(self, messages: list[Message]) -> AsyncIterator[LLMEvent]:
        for attempt in range(self.max_llm_retries + 1):
            emitted = False
            started = time.time()
            try:
                async for ev in self.provider.stream(self.system, messages, self.tools.specs(), self.options):
                    if not isinstance(ev, Done):
                        emitted = True
                    yield ev
                yield _Attempt(attempt, started, time.time())
                return
            except LLMError as e:
                yield _Attempt(attempt, started, time.time(), str(e))
                # 이미 사용자에게 내보낸 출력이 있으면 재시도하면 중복되므로 그대로 실패시킨다
                if not e.retryable or emitted or attempt == self.max_llm_retries:
                    raise
                log.warning("LLM 재시도 (%d/%d): %s", attempt + 1, self.max_llm_retries, e)
                await asyncio.sleep(2**attempt)

    async def _execute(self, calls: list[ToolCall], timeout: float) -> list[tuple[ToolResult, float, float]]:
        """독립 호출은 동시에 실행한다. 시간 안에 끝나지 않은 호출은 오류 결과로 바꾼다.
        결과 순서 = 호출 순서. 각 결과에 시작·종료 벽시계 시각을 붙인다."""
        if not calls:
            return []

        async def timed(c: ToolCall) -> tuple[ToolResult, float, float]:
            t0 = time.time()
            r = await self.tools.execute(c)
            return r, t0, time.time()

        batch_start = time.time()
        tasks = [asyncio.create_task(timed(c)) for c in calls]
        _, pending = await asyncio.wait(tasks, timeout=max(timeout, 0.1))
        for t in pending:
            t.cancel()
        now = time.time()
        return [
            t.result() if t not in pending
            else (ToolResult(c.id, c.name, "시간 상한 안에 결과를 받지 못했습니다. 다른 소스의 결과로 답변하세요.", True),
                  batch_start, now)
            for c, t in zip(calls, tasks)
        ]
