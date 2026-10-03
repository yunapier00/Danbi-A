"""search_knowledge: 학교 문서 자료(Chroma RAG) 의미 검색.

도구 설명의 "들어 있는 자료" 목록은 DB의 출처 값과 settings.yaml의 출처 매핑에서 자동으로 만든다.
"""

from __future__ import annotations

import asyncio
import re

from ...llm.base import ToolSpec
from ...rag.chroma_store import ChromaStore, Chunk, UnknownSourceError
from ...rag.embedder import GeminiEmbedder
from .registry import Tool, ToolError

MAX_TOP_K = 20
KEYWORD_LIMIT = 3
_ARTICLE = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?")  # "제29조", "제 3 조의 2"


def build_description(store: ChromaStore) -> str:
    lines = [
        "단국대학교 학교 문서 자료(규정·학사 자료 DB)를 의미 검색한다. 들어 있는 자료 (짧은 이름: 내용 / 기준 시점 / 청크 수):"
    ]
    for filename, info in store.info.items():
        detail = " / ".join(x for x in (info.content, info.as_of) if x)
        lines.append(f"- {info.short}: {detail} / {store.counts[filename]}건" if detail else f"- {info.short}: {store.counts[filename]}건")
    lines.append(
        "위 목록에 없는 자료는 들어 있지 않다. 문서에 작성일이 없으므로 답변에는 기준 시점을 밝힌다. "
        "특정 자료만 찾으려면 sources로 좁힌다. 조항 번호(예: 제29조)를 query에 넣으면 정확히 일치하는 조항도 함께 찾는다."
    )
    return "\n".join(lines)


def _format(store: ChromaStore, query: str, chunks: list[Chunk]) -> str:
    if not chunks:
        return f"[source: {store.collection_name}] 문서 검색 결과 없음 — 질의: {query}"
    out = [f"[source: {store.collection_name}] 문서 검색 결과 {len(chunks)}건 — 질의: {query}"]
    for n, c in enumerate(chunks, 1):
        info = store.info.get(c.source)
        doc = info.label if info else c.source
        if info and info.as_of:
            doc += f" [{info.as_of}]"
        loc = " > ".join([doc, *c.headings])
        extra = [f"p.{c.page}"] if c.page is not None else []
        extra.append("키워드 일치" if c.distance is None else f"거리 {c.distance:.3f}")
        out.append(f"\n({n}) {loc} | {' | '.join(extra)}\n{c.text.strip()}")
    return "\n".join(out)


def make_search_knowledge(store: ChromaStore, embedder: GeminiEmbedder, default_top_k: int = 8) -> Tool:
    spec = ToolSpec(
        name="search_knowledge",
        description=build_description(store),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색할 내용 (자연어 질문이나 핵심어)"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": store.short_names()},
                    "description": "검색할 자료의 짧은 이름. 생략하면 전체 검색",
                },
                "top_k": {"type": "integer", "description": f"결과 수 (기본 {default_top_k}, 최대 {MAX_TOP_K})"},
            },
            "required": ["query"],
        },
    )

    async def search_knowledge(query: str, sources: list[str] | None = None, top_k: int | None = None) -> str:
        if not query.strip():
            raise ToolError("query가 비어 있습니다")
        try:
            files = store.resolve_sources(sources)
        except UnknownSourceError as e:
            raise ToolError(str(e)) from e
        k = max(1, min(int(top_k or default_top_k), MAX_TOP_K))

        embedding = await embedder.embed_query(query)
        terms = list(dict.fromkeys(re.sub(r"\s+", "", m) for m in _ARTICLE.findall(query)))
        semantic, *keyword = await asyncio.gather(
            asyncio.to_thread(store.query, embedding, k, files),
            *(asyncio.to_thread(store.keyword_search, t, KEYWORD_LIMIT, files) for t in terms),
        )
        # 조항 번호 정확 일치를 앞에 두고, 의미 검색 결과와 중복을 제거한다
        seen: set[str] = set()
        chunks = []
        for c in [*(c for group in keyword for c in group), *semantic]:
            if c.id not in seen:
                seen.add(c.id)
                chunks.append(c)
        return _format(store, query, chunks)

    def status(args: dict) -> str:
        scope = "·".join(args.get("sources") or []) or "학교 규정·학사"
        return f"{scope} 자료에서 '{args.get('query', '')}' 검색 중"

    return Tool(spec, search_knowledge, status)
