"""공급자 중립 LLM 인터페이스와 공통 타입.

에이전트 루프는 이 파일의 타입만 사용한다. 공급자별 형식 변환은 각 어댑터가 맡는다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant", "tool"]
StopReason = Literal["end", "tool_calls", "max_tokens", "refused"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Role
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)    # role=assistant
    tool_results: list[ToolResult] = field(default_factory=list)  # role=tool
    # 공급자가 다음 요청에 그대로 돌려받아야 하는 원본 응답 (예: Gemini thought signature).
    # 키는 공급자 이름. 다른 공급자는 이 값을 무시하고 공통 필드로 변환한다.
    provider_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON 스키마 (type: object)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cached_tokens + other.cached_tokens,
        )


@dataclass
class LLMOptions:
    temperature: float = 0.0
    max_output_tokens: int = 4096
    extra: dict[str, Any] = field(default_factory=dict)  # 공급자 전용 옵션


# --- 스트리밍 이벤트 ---------------------------------------------------------

@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallEvent:
    call: ToolCall


@dataclass
class Done:
    stop_reason: StopReason
    usage: Usage
    message: Message  # 이번 응답 전체를 담은 assistant 메시지 (대화 기록에 그대로 추가)


LLMEvent = TextDelta | ToolCallEvent | Done


class LLMError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def stream(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        options: LLMOptions,
    ) -> AsyncIterator[LLMEvent]:
        """응답을 스트리밍한다. 마지막 이벤트는 항상 Done이다.

        한 응답에 도구 호출이 여러 개면 ToolCallEvent가 여러 번 오고 Done.message.tool_calls에 모두 담긴다.
        오류는 LLMError(retryable=...)로 던진다.
        """
