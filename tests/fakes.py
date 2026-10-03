"""테스트용 가짜 LLM 공급자: 미리 정한 응답을 순서대로 돌려준다."""

from __future__ import annotations

from dataclasses import dataclass, field

from danbi.llm.base import (
    Done,
    LLMError,
    LLMProvider,
    Message,
    TextDelta,
    ToolCall,
    ToolCallEvent,
    Usage,
)


@dataclass
class Reply:
    text: str = ""
    calls: list[tuple[str, dict]] = field(default_factory=list)  # (도구 이름, 인자)
    error: LLMError | None = None


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, replies: list[Reply]):
        self.replies = list(replies)
        self.requests: list[list[Message]] = []
        self._n = 0

    async def stream(self, system, messages, tools, options):
        self.requests.append(list(messages))
        reply = self.replies.pop(0)
        if reply.error:
            raise reply.error
        if reply.text:
            yield TextDelta(reply.text)
        calls = []
        for name, args in reply.calls:
            self._n += 1
            call = ToolCall(id=f"c{self._n}", name=name, arguments=args)
            calls.append(call)
            yield ToolCallEvent(call)
        yield Done(
            stop_reason="tool_calls" if calls else "end",
            usage=Usage(10, 5),
            message=Message(role="assistant", text=reply.text, tool_calls=calls),
        )
