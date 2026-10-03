"""Gemini 어댑터의 메시지 변환 (네트워크 불필요)."""

from google.genai import types

from danbi.llm.base import Message, ToolCall, ToolResult
from danbi.llm.gemini import GeminiProvider


def provider():
    return GeminiProvider("test-model", client=object())


def test_converts_common_messages():
    contents = provider()._to_contents([
        Message(role="user", text="질문"),
        Message(role="assistant", text="찾아볼게요", tool_calls=[
            ToolCall("abc", "search_knowledge", {"query": "셔틀"}),
            ToolCall("gemini_auto_1", "search_knowledge", {"query": "도서관"}),
        ]),
        Message(role="tool", tool_results=[
            ToolResult("abc", "search_knowledge", "결과"),
            ToolResult("gemini_auto_1", "search_knowledge", "실패", is_error=True),
        ]),
    ])
    assert [c.role for c in contents] == ["user", "model", "user"]
    model_parts = contents[1].parts
    assert model_parts[0].text == "찾아볼게요"
    assert model_parts[1].function_call.id == "abc"
    assert model_parts[2].function_call.id is None  # 자동 생성 ID는 보내지 않는다
    r1, r2 = (p.function_response for p in contents[2].parts)
    assert r1.id == "abc" and r1.response == {"output": "결과"}
    assert r2.id is None and r2.response == {"error": "실패"}


def test_reuses_raw_model_content_for_thought_signatures():
    raw = types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(name="t", args={}), thought_signature=b"sig"),
    ])
    msg = Message(role="assistant", tool_calls=[ToolCall("x", "t", {})], provider_data={"gemini": raw})
    assert provider()._to_contents([msg])[0] is raw


def test_config_tools_and_thinking():
    from danbi.llm.base import LLMOptions, ToolSpec

    cfg = provider()._config(
        "sys", [ToolSpec("t", "desc", {"type": "object", "properties": {}})],
        LLMOptions(extra={"thinking_level": "low"}),
    )
    assert cfg.tools[0].function_declarations[0].name == "t"
    assert cfg.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.AUTO
    assert cfg.automatic_function_calling.disable is True
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.LOW
