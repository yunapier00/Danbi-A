"""Google Gemini 어댑터 (google-genai SDK)."""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator

from google import genai
from google.genai import errors, types

from .base import (
    Done,
    LLMError,
    LLMEvent,
    LLMOptions,
    LLMProvider,
    Message,
    StopReason,
    TextDelta,
    ToolCall,
    ToolCallEvent,
    ToolSpec,
    Usage,
)

# Gemini가 호출 ID를 주지 않을 때 붙이는 접두사. 이 ID는 응답을 돌려줄 때 보내지 않는다.
_AUTO_ID_PREFIX = "gemini_auto_"
_REFUSED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE"}
_RETRYABLE_FINISH = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL"}


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, model: str, client: genai.Client | None = None):
        self.model = model
        self.client = client or genai.Client()  # GOOGLE_API_KEY 환경 변수 사용
        self._ids = itertools.count(1)

    # --- 공통 형식 → Gemini 형식 ----------------------------------------------

    def _to_contents(self, messages: list[Message]) -> list[types.Content]:
        contents: list[types.Content] = []
        for m in messages:
            if m.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m.text)]))
            elif m.role == "assistant":
                raw = m.provider_data.get(self.name)
                if raw is not None:
                    # 원본을 그대로 돌려줘야 thought signature가 유지된다 (Gemini 3 도구 호출 필수)
                    contents.append(raw)
                    continue
                parts = [types.Part(text=m.text)] if m.text else []
                parts += [
                    types.Part(function_call=types.FunctionCall(id=self._wire_id(c.id), name=c.name, args=c.arguments))
                    for c in m.tool_calls
                ]
                contents.append(types.Content(role="model", parts=parts))
            elif m.role == "tool":
                parts = [
                    types.Part(function_response=types.FunctionResponse(
                        id=self._wire_id(r.call_id),
                        name=r.name,
                        response={"error": r.content} if r.is_error else {"output": r.content},
                    ))
                    for r in m.tool_results
                ]
                contents.append(types.Content(role="user", parts=parts))
        return contents

    @staticmethod
    def _wire_id(call_id: str) -> str | None:
        return None if call_id.startswith(_AUTO_ID_PREFIX) else call_id

    def _config(self, system: str, tools: list[ToolSpec], options: LLMOptions) -> types.GenerateContentConfig:
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=options.temperature,
            max_output_tokens=options.max_output_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if tools:
            cfg.tools = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
                for t in tools
            ])]
            cfg.tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.AUTO)
            )
        if level := options.extra.get("thinking_level"):
            cfg.thinking_config = types.ThinkingConfig(thinking_level=str(level).upper())
        return cfg

    # --- 스트리밍 -------------------------------------------------------------

    async def stream(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        options: LLMOptions,
    ) -> AsyncIterator[LLMEvent]:
        parts: list[types.Part] = []
        text: list[str] = []
        calls: list[ToolCall] = []
        finish: str | None = None
        block_reason: str | None = None
        usage = Usage()

        try:
            stream = await self.client.aio.models.generate_content_stream(
                model=self.model,
                contents=self._to_contents(messages),
                config=self._config(system, tools, options),
            )
            async for chunk in stream:
                if chunk.usage_metadata:
                    u = chunk.usage_metadata
                    usage = Usage(
                        input_tokens=u.prompt_token_count or 0,
                        output_tokens=(u.candidates_token_count or 0) + (u.thoughts_token_count or 0),
                        cached_tokens=u.cached_content_token_count or 0,
                    )
                if chunk.prompt_feedback and chunk.prompt_feedback.block_reason:
                    block_reason = str(chunk.prompt_feedback.block_reason)
                if not chunk.candidates:
                    continue
                cand = chunk.candidates[0]
                if cand.finish_reason:
                    finish = cand.finish_reason.value if hasattr(cand.finish_reason, "value") else str(cand.finish_reason)
                for part in (cand.content.parts if cand.content and cand.content.parts else []):
                    parts.append(part)
                    if part.function_call:
                        fc = part.function_call
                        call = ToolCall(
                            id=fc.id or f"{_AUTO_ID_PREFIX}{next(self._ids)}",
                            name=fc.name or "",
                            arguments=dict(fc.args or {}),
                        )
                        calls.append(call)
                        yield ToolCallEvent(call)
                    elif part.text and not part.thought:
                        text.append(part.text)
                        yield TextDelta(part.text)
        except errors.APIError as e:
            code = getattr(e, "code", None) or 0
            raise LLMError(f"Gemini API 오류 ({code}): {e.message or e}", retryable=code == 429 or code >= 500) from e
        except (OSError, TimeoutError) as e:
            raise LLMError(f"Gemini 연결 오류: {e}", retryable=True) from e

        if finish in _RETRYABLE_FINISH:
            raise LLMError(f"Gemini 응답 형식 오류: {finish}", retryable=True)

        stop: StopReason
        if block_reason or finish in _REFUSED:
            stop = "refused"
        elif calls:
            stop = "tool_calls"
        elif finish == "MAX_TOKENS":
            stop = "max_tokens"
        else:
            stop = "end"

        message = Message(
            role="assistant",
            text="".join(text),
            tool_calls=calls,
            provider_data={self.name: types.Content(role="model", parts=parts)} if parts else {},
        )
        yield Done(stop_reason=stop, usage=usage, message=message)
