"""에이전트 이벤트 스트림을 그대로 흘려보내면서 추적 DB에 기록한다.

  async for ev in recorder.record(agent.run(q, history=h), run_id=..., question=q, channel="web", conversation_id=sid):
      ...  # 원래 이벤트 그대로

기록 실패는 로그만 남기고 삼킨다 — 추적 때문에 사용자 답변이 막히면 안 된다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict

from ..agent.loop import Agent, AgentEvent, FinalEvent, LLMCallEvent, TokenEvent, ToolEndEvent, ToolStartEvent
from .sources import SourceRef, extract_sources, mark_cited
from .store import STATUS_OF_STOP, TraceStore

log = logging.getLogger(__name__)


def new_run_id() -> str:
    return uuid.uuid4().hex


class TraceRecorder:
    def __init__(self, store: TraceStore, agent: Agent, pricing: dict | None = None):
        self.store = store
        self.agent = agent
        self.pricing = pricing or {}
        self.provider = getattr(agent.provider, "name", type(agent.provider).__name__)
        self.model = getattr(agent.provider, "model", "")
        self.system_hash = store.save_prompt_version("system", agent.system)
        tools_json = json.dumps([asdict(s) for s in agent.tools.specs()], ensure_ascii=False, indent=1)
        self.tools_hash = store.save_prompt_version("tools", tools_json)

    def _safe(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.exception("추적 기록 실패: %s", getattr(fn, "__name__", fn))
            return None

    def cost(self, input_tokens: int, output_tokens: int) -> float | None:
        p_in, p_out = self.pricing.get("input_per_mtok"), self.pricing.get("output_per_mtok")
        if p_in is None or p_out is None:
            return None
        return round(input_tokens / 1e6 * p_in + output_tokens / 1e6 * p_out, 6)

    async def record(self, events: AsyncIterator[AgentEvent], *, run_id: str, question: str, channel: str,
                     conversation_id: str | None = None, tags: dict | None = None,
                     client_ip: str | None = None, user_key: str | None = None) -> AsyncIterator[AgentEvent]:
        started = time.time()
        self._safe(self.store.start_run, run_id, conversation_id=conversation_id, channel=channel, question=question,
                   provider=self.provider, model=self.model, system_hash=self.system_hash,
                   tools_hash=self.tools_hash, started_at=started, tags=tags, client_ip=client_ip, user_key=user_key)
        status_text: dict[str, str] = {}
        args_of: dict[str, dict] = {}
        refs: list[tuple[int, SourceRef]] = []
        first_token: float | None = None
        final: FinalEvent | None = None
        failure: str | None = None
        try:
            async for ev in events:
                if isinstance(ev, TokenEvent) and first_token is None:
                    first_token = time.time()
                elif isinstance(ev, LLMCallEvent):
                    self._safe(self.store.add_llm_call, run_id, seq=ev.seq, attempt=ev.attempt, started=ev.started,
                               ended=ev.ended, input_tokens=ev.usage.input_tokens, output_tokens=ev.usage.output_tokens,
                               cached_tokens=ev.usage.cached_tokens, stop_reason=ev.stop_reason, text=ev.text,
                               tool_calls=[{"id": c.id, "name": c.name, "arguments": c.arguments} for c in ev.tool_calls],
                               error=ev.error)
                elif isinstance(ev, ToolStartEvent):
                    for c in ev.calls:
                        status_text[c.id] = self.agent.tools.describe(c)
                        args_of[c.id] = c.arguments
                elif isinstance(ev, ToolEndEvent):
                    r = ev.result
                    row = self._safe(self.store.add_tool_call, run_id, llm_seq=ev.llm_seq, call_id=r.call_id,
                                     name=r.name, arguments=args_of.get(r.call_id, {}),
                                     status_text=status_text.get(r.call_id, ""), started=ev.started or time.time(),
                                     ended=ev.ended or time.time(), is_error=r.is_error, result=r.content)
                    if row and not r.is_error:
                        refs += [(row, ref) for ref in extract_sources(r.name, r.content)]
                elif isinstance(ev, FinalEvent):
                    final = ev
                yield ev
        except (GeneratorExit, asyncio.CancelledError):
            failure = "aborted"  # 클라이언트가 응답 도중 연결을 끊었거나 시간 초과로 취소됨
            raise
        except Exception as e:
            failure = f"{type(e).__name__}: {e}"
            raise
        finally:
            answer = final.text if final else None
            if refs:
                mark_cited([r for _, r in refs], answer or "")
                for row in dict.fromkeys(row for row, _ in refs):
                    self._safe(self.store.add_sources, run_id, row, [r for rid, r in refs if rid == row])
            if final is not None:
                status, stop, error = STATUS_OF_STOP.get(final.stop_reason, final.stop_reason), final.stop_reason, final.error
                usage = final.usage
            else:
                status = "aborted" if failure == "aborted" else "error"
                stop, error, usage = None, failure, None
            self._safe(self.store.finish_run, run_id, status=status, stop_reason=stop, answer=answer, error=error,
                       ended_at=time.time(), first_token_at=first_token,
                       input_tokens=usage.input_tokens if usage else 0,
                       output_tokens=usage.output_tokens if usage else 0,
                       cached_tokens=usage.cached_tokens if usage else 0,
                       cost_usd=self.cost(usage.input_tokens, usage.output_tokens) if usage else None)
