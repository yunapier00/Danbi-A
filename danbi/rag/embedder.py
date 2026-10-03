"""질문 임베딩. DB를 만든 설정과 같아야 한다.

DB는 LangChain GoogleGenerativeAIEmbeddings로 만들어졌다: 문서는 RETRIEVAL_DOCUMENT, 질의는 RETRIEVAL_QUERY.
(2026-10-02 검증: 저장된 청크를 RETRIEVAL_DOCUMENT로 다시 임베딩하면 저장된 벡터와 코사인 1.0)
"""

from __future__ import annotations

from collections import OrderedDict

from google import genai
from google.genai import types

from ..config import EmbeddingSettings


class GeminiEmbedder:
    def __init__(self, settings: EmbeddingSettings, client: genai.Client | None = None, cache_size: int = 512):
        if settings.provider != "gemini":
            raise ValueError(f"지원하지 않는 임베딩 공급자: {settings.provider}")
        self.model = settings.model
        self.dimensions = settings.dimensions
        self.client = client or genai.Client()
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size

    async def embed_query(self, text: str) -> list[float]:
        key = " ".join(text.split())
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        vec = await self._embed(key, "RETRIEVAL_QUERY")
        self._cache[key] = vec
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return vec

    async def embed_document(self, text: str) -> list[float]:
        """검증용 (DB 저장 벡터와 비교). 검색에는 쓰지 않는다."""
        return await self._embed(text, "RETRIEVAL_DOCUMENT")

    async def _embed(self, text: str, task_type: str) -> list[float]:
        r = await self.client.aio.models.embed_content(
            model=self.model,
            contents=text,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=self.dimensions),
        )
        return list(r.embeddings[0].values)
