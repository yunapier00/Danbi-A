"""도구 정의(ToolSpec)와 실행 함수 매핑.

도구 함수는 동기·비동기 모두 가능하다. 동기 함수(크롤링 등)는 스레드에서 실행해 병렬 호출을 막지 않는다.
실패는 예외로 새지 않고 오류 결과(ToolResult.is_error)로 돌려준다.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ...llm.base import ToolCall, ToolResult, ToolSpec

log = logging.getLogger(__name__)


class ToolError(Exception):
    """도구가 의도적으로 돌려주는 오류. 메시지는 에이전트가 읽고 대안을 고를 수 있게 쓴다."""


@dataclass
class Tool:
    spec: ToolSpec
    func: Callable[..., Any]  # (**arguments) -> str  (동기 또는 async)
    status: Callable[[dict], str] | None = None  # 인자 → 사용자에게 보여줄 진행 상태 문구


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool) -> None:
        if tool.spec.name in self._tools:
            raise ValueError(f"도구 이름 중복: {tool.spec.name}")
        self._tools[tool.spec.name] = tool

    def specs(self) -> list[ToolSpec]:
        # 등록 순서 고정 → 도구 정의가 매 요청 같은 바이트가 되어 프롬프트 캐싱이 유지된다
        return [t.spec for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def describe(self, call: ToolCall) -> str:
        tool = self._tools.get(call.name)
        if tool and tool.status:
            try:
                return tool.status(call.arguments)
            except Exception:  # 상태 문구 때문에 실행이 막히면 안 된다
                log.debug("상태 문구 생성 실패: %s", call, exc_info=True)
        return "자료를 찾는 중"

    async def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(call.id, call.name, f"알 수 없는 도구입니다: {call.name}. 사용 가능: {', '.join(self._tools)}", True)

        missing = [k for k in tool.spec.parameters.get("required", []) if k not in call.arguments]
        if missing:
            return ToolResult(call.id, call.name, f"필수 인자 누락: {', '.join(missing)}", True)
        known = tool.spec.parameters.get("properties", {})
        args = {k: v for k, v in call.arguments.items() if k in known}

        try:
            if inspect.iscoroutinefunction(tool.func):
                out = await tool.func(**args)
            else:
                out = await asyncio.to_thread(tool.func, **args)
            return ToolResult(call.id, call.name, str(out))
        except ToolError as e:
            return ToolResult(call.id, call.name, str(e), True)
        except Exception as e:
            log.exception("도구 실행 실패: %s(%s)", call.name, call.arguments)
            return ToolResult(call.id, call.name, f"도구 실행 중 오류가 발생했습니다: {type(e).__name__}: {e}", True)
