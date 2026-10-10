"""search_knowledge 단위 테스트: 임시 Chroma DB + 가짜 임베딩 (API 키 불필요)."""

import chromadb
import pytest

from danbi.agent.tools import ToolError
from danbi.agent.tools.knowledge import make_search_knowledge
from danbi.config import RagSourceInfo
from danbi.rag.chroma_store import ChromaStore

DOCS = [
    ("a1", "제29조(이수제한) 의과대학 학생은 다전공 이수를 제한할 수 있다.", {"출처": "세칙.md", "대제목": "제3장", "중제목": "제29조(이수제한)"}, [1.0, 0.0, 0.0]),
    ("a2", "제30조(기타) 기타 사항은 총장이 정한다.", {"출처": "세칙.md", "대제목": "제3장", "중제목": "제30조"}, [0.9, 0.1, 0.0]),
    ("b1", "셔틀 첫차는 08:15이다.", {"출처": "셔틀.md", "대제목": "셔틀"}, [0.0, 1.0, 0.0]),
    ("c1", "수강신청 일정 안내", {"출처": "시간표.pdf", "페이지": 2}, [0.0, 0.0, 1.0]),
]


class FakeEmbedder:
    def __init__(self, vec):
        self.vec = vec

    async def embed_query(self, text):
        return self.vec


@pytest.fixture
def store(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path), settings=chromadb.Settings(anonymized_telemetry=False))
    col = client.create_collection("campus_rules", configuration={"hnsw": {"space": "l2"}})
    col.add(ids=[d[0] for d in DOCS], documents=[d[1] for d in DOCS],
            metadatas=[d[2] for d in DOCS], embeddings=[d[3] for d in DOCS])
    info = {
        "세칙.md": RagSourceInfo(short="시행세칙", label="학칙 시행세칙", content="세칙 조항", as_of="2026.06.15 개정본"),
        "셔틀.md": RagSourceInfo(short="셔틀버스", label="셔틀버스 정보"),
        "없는파일.md": RagSourceInfo(short="없음", label="없음"),  # DB에 없는 출처 → 경고 후 제외
    }
    return ChromaStore(tmp_path, "campus_rules", info)


def test_source_mapping_and_description(store):
    # 설정 순서 유지, 매핑 없는 출처는 파일명 그대로 뒤에 붙음, DB에 없는 출처는 제외
    assert store.short_names() == ["시행세칙", "셔틀버스", "시간표.pdf"]
    tool = make_search_knowledge(store, FakeEmbedder([1, 0, 0]))
    desc = tool.spec.description
    assert "- 시행세칙: 세칙 조항 / 2026.06.15 개정본 / 2건" in desc
    assert "- 시간표.pdf: 1건" in desc
    assert tool.spec.parameters["properties"]["sources"]["items"]["enum"] == store.short_names()


async def test_semantic_search_with_source_filter(store):
    tool = make_search_knowledge(store, FakeEmbedder([0.5, 0.5, 0.0]), default_top_k=2)
    out = await tool.func(query="첫차", sources=["셔틀버스"])
    assert "[source: campus_rules] 문서 검색 결과 1건" in out
    assert "셔틀버스 정보 > 셔틀" in out and "08:15" in out
    assert "세칙" not in out


async def test_article_keyword_match_comes_first(store):
    # 질문 벡터는 시간표 PDF에 가장 가깝지만, 조항 번호가 제목에 정확히 맞는 청크가 1위로 온다
    tool = make_search_knowledge(store, FakeEmbedder([0.0, 0.0, 1.0]), default_top_k=2)
    out = await tool.func(query="제 29 조 내용")
    first = out.split("(1)")[1].split("(2)")[0]
    assert "학칙 시행세칙 [2026.06.15 개정본] > 제3장 > 제29조(이수제한)" in first
    assert "p.2" in out.split("(2)")[1]  # 의미 검색 결과(시간표 PDF)는 그다음


async def test_unknown_source_is_tool_error(store):
    tool = make_search_knowledge(store, FakeEmbedder([1, 0, 0]))
    with pytest.raises(ToolError, match="알 수 없는 출처"):
        await tool.func(query="x", sources=["학칙"])
