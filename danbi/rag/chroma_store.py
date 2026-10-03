"""기존 Chroma DB 읽기 전용 검색.

쓰기 메서드(add/update/upsert/delete)는 호출하지 않는다. 새 자료는 별도 컬렉션(별도 폴더)으로 만든다.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import chromadb

from ..config import RagSourceInfo

log = logging.getLogger(__name__)

SOURCE_KEY = "출처"
PAGE_KEY = "페이지"
HEADING_KEYS = ("대제목", "중제목", "소제목")


@dataclass
class Chunk:
    id: str
    text: str
    source: str  # 파일명 (메타데이터 출처)
    page: int | None = None
    headings: list[str] = field(default_factory=list)
    distance: float | None = None  # 키워드 검색 결과는 None


class UnknownSourceError(ValueError):
    pass


class ChromaStore:
    def __init__(self, path: Path, collection: str, source_info: dict[str, RagSourceInfo]):
        if not Path(path).exists():
            raise FileNotFoundError(f"Chroma DB 폴더가 없습니다: {path}")
        client = chromadb.PersistentClient(
            path=str(path), settings=chromadb.Settings(anonymized_telemetry=False, allow_reset=False)
        )
        self.collection_name = collection
        self.col = client.get_collection(collection)
        metas = self.col.get(include=["metadatas"])["metadatas"]
        self.counts = Counter(m.get(SOURCE_KEY, "") for m in metas)

        # 설정에 적힌 순서를 따르고, 설정에 없는 새 출처는 파일명 그대로 뒤에 붙인다
        self.info: dict[str, RagSourceInfo] = {}
        for filename, info in source_info.items():
            if filename in self.counts:
                self.info[filename] = info
            else:
                log.warning("설정의 RAG 출처가 DB에 없습니다: %s", filename)
        for filename in sorted(self.counts):
            if filename not in self.info:
                log.warning("출처 매핑이 없는 RAG 출처: %s (config/settings.yaml rag.sources에 추가하세요)", filename)
                self.info[filename] = RagSourceInfo(short=filename, label=filename)
        self._by_short = {i.short: f for f, i in self.info.items()}

    def short_names(self) -> list[str]:
        return [i.short for i in self.info.values()]

    def resolve_sources(self, names: list[str] | None) -> list[str] | None:
        """짧은 이름(또는 파일명) → 파일명. 비었으면 None(전체)."""
        if not names:
            return None
        out = []
        for n in names:
            if n in self._by_short:
                out.append(self._by_short[n])
            elif n in self.info:
                out.append(n)
            else:
                raise UnknownSourceError(f"알 수 없는 출처: {n}. 사용 가능: {', '.join(self.short_names())}")
        return out

    @staticmethod
    def _where(sources: list[str] | None) -> dict | None:
        if not sources:
            return None
        return {SOURCE_KEY: sources[0]} if len(sources) == 1 else {SOURCE_KEY: {"$in": sources}}

    @staticmethod
    def _chunk(id_: str, doc: str, meta: dict, distance: float | None) -> Chunk:
        return Chunk(
            id=id_,
            text=doc or "",
            source=meta.get(SOURCE_KEY, ""),
            page=meta.get(PAGE_KEY),
            headings=[meta[k] for k in HEADING_KEYS if meta.get(k)],
            distance=distance,
        )

    def query(self, embedding: list[float], top_k: int, sources: list[str] | None = None) -> list[Chunk]:
        r = self.col.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where=self._where(sources),
            include=["documents", "metadatas", "distances"],
        )
        return [
            self._chunk(i, d, m, dist)
            for i, d, m, dist in zip(r["ids"][0], r["documents"][0], r["metadatas"][0], r["distances"][0])
        ]

    def keyword_search(self, term: str, limit: int, sources: list[str] | None = None) -> list[Chunk]:
        """정확한 단어 검색 (조항 번호 등). DB의 전문 검색 색인을 쓴다."""
        r = self.col.get(
            where=self._where(sources),
            where_document={"$contains": term},
            limit=limit,
            include=["documents", "metadatas"],
        )
        return [self._chunk(i, d, m, None) for i, d, m in zip(r["ids"], r["documents"], r["metadatas"])]
