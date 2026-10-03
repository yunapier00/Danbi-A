"""실제 chroma_db_dd3 + Gemini 임베딩 검증 (설계 §7 필수 테스트).

  pytest -m live
"""

import os

import numpy as np
import pytest

from danbi.config import load_settings
from danbi.rag.chroma_store import ChromaStore
from danbi.rag.embedder import GeminiEmbedder

pytestmark = pytest.mark.live

settings = load_settings()
if not settings.rag.chroma_path.exists() or not os.environ.get("GOOGLE_API_KEY"):
    pytest.skip("chroma_db_dd3 또는 GOOGLE_API_KEY 없음", allow_module_level=True)


@pytest.fixture(scope="module")
def store():
    return ChromaStore(settings.rag.chroma_path, settings.rag.collection, settings.rag.sources)


@pytest.fixture(scope="module")
def embedder():
    return GeminiEmbedder(settings.embedding)


def cosine(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return float(a @ b / np.linalg.norm(a) / np.linalg.norm(b))


async def test_reembedding_matches_stored_vectors(store, embedder):
    """임베딩 설정(모델·task type·차원)이 DB를 만든 설정과 같은지 확인한다."""
    r = store.col.get(limit=3, offset=1000, include=["documents", "embeddings"])
    for doc, stored in zip(r["documents"], r["embeddings"]):
        assert cosine(await embedder.embed_document(doc), stored) > 0.999


def test_all_db_sources_are_mapped(store):
    unmapped = [f for f, i in store.info.items() if i.short == f]
    assert not unmapped, f"settings.yaml rag.sources에 매핑이 없는 출처: {unmapped}"


@pytest.mark.parametrize("query, expected", [
    ("죽전역 셔틀버스 첫차 시간", "셔틀버스 정보.md"),
    ("다전공 이수 제한", "(2-1-2)학칙 시행세칙(20260615)_일부개정.md"),
    ("2학기 기말고사 성적 공시 기간", "학사일정.md"),
    ("수강신청 일정과 유의사항", "2026-2학기 종합강의시간표 안내자료.pdf"),
    ("도서관 열람실 운영 시간", "도서관 운영 시간.md"),
    ("범정관 위치", "campus_map_.md"),
    ("휴학 기간과 휴학원서 제출 시기", "(2-1-2)학칙 시행세칙(20260615)_일부개정.md"),
    ("휴학", "(2-1-1)학칙(20260507)_일부개정.md"),  # 학칙 제21조(휴학)도 상위 8건 안에 든다
])
async def test_representative_queries_hit_expected_source(store, embedder, query, expected):
    chunks = store.query(await embedder.embed_query(query), top_k=settings.rag.top_k)
    assert expected in [c.source for c in chunks]
