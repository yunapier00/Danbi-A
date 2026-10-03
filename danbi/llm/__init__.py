from __future__ import annotations

from ..config import LLMSettings
from .base import LLMOptions, LLMProvider


def create_provider(settings: LLMSettings) -> LLMProvider:
    """설정의 provider 이름으로 어댑터를 만든다. 공급자 SDK는 필요할 때만 import한다."""
    if settings.provider == "gemini":
        from .gemini import GeminiProvider
        return GeminiProvider(settings.model)
    raise ValueError(f"지원하지 않는 LLM 공급자: {settings.provider} (현재: gemini)")


def options_from_settings(settings: LLMSettings) -> LLMOptions:
    return LLMOptions(
        temperature=settings.temperature,
        max_output_tokens=settings.max_output_tokens,
        extra=dict(settings.options),
    )
