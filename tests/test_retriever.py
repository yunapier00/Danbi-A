"""검색기(rag/retriever.py) 단위 테스트: 임시 Chroma DB + 가짜 임베딩 (API 없음)."""

import chromadb
import pytest

from danbi.config import RagSourceInfo
from danbi.rag.chroma_store import ChromaStore
from danbi.rag.retriever import RetrievalOptions, Retriever, clean_text, format_chunks

M = "map.md"
R = "rule.md"
DOCS = [
    # 캠퍼스맵처럼 한 건물이 위치·별칭·키워드 조각으로 나뉜 경우
    ("m1", "### 위치\n정문에서 직진하면 중앙에 있는 대학본부 건물이다.", {"출처": M, "대제목": "건물", "중제목": "범정관", "소제목": "위치"}, [0.0, 1.0, 0.0]),
    ("m2", "### 별칭\n대학본부", {"출처": M, "대제목": "건물", "중제목": "범정관", "소제목": "별칭"}, [0.1, 0.9, 0.0]),
    ("m3", "### 키워드\n범정관", {"출처": M, "대제목": "건물", "중제목": "범정관", "소제목": "키워드"}, [0.05, 0.95, 0.0]),
    ("r1", "## 제27조(학사경고)\n학기 평점평균이 1.75 미만인 자에게 학사경고를 한다.", {"출처": R, "대제목": "제5장", "중제목": "제27조(학사경고)"}, [1.0, 0.0, 0.0]),
    ("r2", "## 제40조(조기졸업 신청자격)\n평점평균 4.0 이상인 자는 조기졸업을 신청할 수 있다.", {"출처": R, "대제목": "제9장", "중제목": "제40조(조기졸업 신청자격)"}, [0.0, 0.0, 1.0]),
    ("r3", "# 부칙(2012.1.16.)", {"출처": R, "대제목": "부칙(2012.1.16.)"}, [0.95, 0.05, 0.0]),
    ("r4", "## 제2조(경과조치)\n개정학칙 제27조는 2013학년도부터 적용한다.", {"출처": R, "대제목": "부칙(2012.1.16.)", "중제목": "제2조(경과조치)"}, [0.9, 0.1, 0.0]),
]
INFO = {M: RagSourceInfo(short="캠퍼스맵", label="캠퍼스 맵"), R: RagSourceInfo(short="학칙", label="학칙")}


class RecordingEmbedder:
    """질문 텍스트에 따라 벡터를 고르고, 받은 텍스트를 기록한다."""

    def __init__(self, vectors: dict[str, list[float]], default=(0.5, 0.5, 0.5)):
        self.vectors, self.default, self.seen = vectors, list(default), []

    async def embed_query(self, text):
        self.seen.append(text)
        return next((v for k, v in self.vectors.items() if k in text), self.default)


@pytest.fixture
def store(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path), settings=chromadb.Settings(anonymized_telemetry=False))
    col = client.create_collection("campus_rules", configuration={"hnsw": {"space": "l2"}})
    col.add(ids=[d[0] for d in DOCS], documents=[d[1] for d in DOCS],
            metadatas=[d[2] for d in DOCS], embeddings=[d[3] for d in DOCS])
    return ChromaStore(tmp_path, "campus_rules", INFO)


async def test_slang_is_expanded_into_the_embedding(store):
    emb = RecordingEmbedder({"학사경고": [1.0, 0.0, 0.0]}, default=(0.0, 0.0, 1.0))
    r = Retriever(store, emb)
    out = await r.search("학고 맞으면 어떻게 돼?", 3, None)
    assert emb.seen[-1] == "학고 맞으면 어떻게 돼? (학사경고)"
    assert out[0].id == "r1"
    base = await r.search("학고 맞으면 어떻게 돼?", 3, None, RetrievalOptions.baseline())
    assert emb.seen[-1] == "학고 맞으면 어떻게 돼?" and base[0].id == "r2"   # 확장 없으면 엉뚱한 조항


async def test_fragments_are_merged_once(store):
    r = Retriever(store, RecordingEmbedder({}, default=(0.0, 1.0, 0.0)))
    out = await r.search("범정관 어디야", 3, None)
    first = out[0]
    assert sorted(first.parts) == ["m1", "m2", "m3"] and first.headings == ["건물", "범정관"]
    assert "정문에서 직진" in first.text and "대학본부" in first.text
    assert sum(1 for c in out if c.parts) == 1 and not any(c.id in ("m2", "m3") for c in out[1:])


async def test_noise_goes_last_unless_asked(store):
    r = Retriever(store, RecordingEmbedder({}, default=(0.95, 0.05, 0.0)))   # 부칙 청크에 가장 가까운 질문
    out = [c.id for c in await r.search("학점 평균이 낮으면", 4, None)]
    assert out == ["r1", "r2", "m1", "r3"]          # 부칙 조항(r4)은 밀려나고, 제목만 있는 청크(r3)는 맨 뒤
    asked = [c.id for c in await r.search("부칙 경과조치 시행일", 4, None)]
    assert asked[0] == "r4"                          # 부칙을 물으면 부칙 조항이 앞으로


async def test_article_number_exact_match_first(store):
    r = Retriever(store, RecordingEmbedder({}, default=(0.0, 0.0, 1.0)))
    out = await r.search("제27조 내용", 2, None)
    assert out[0].id == "r1"


def test_terms_strip_josa_and_stopwords(store):
    r = Retriever(store, RecordingEmbedder({}))
    assert r.terms("범정관은 어디야?", glossary=False) == ["범정관"]
    assert "학사경고" in r.terms("학고 맞으면?", glossary=True)
    assert r.expansions("조졸 조건") == ["조기졸업"] and r.expansions("조기졸업 조건") == []


def test_clean_text_removes_empty_table_cells():
    raw = "[표 제목: 안내] [제도: 징병검사] [: 없음] [: 없음] [비고: 없음]\n\n\n\n다음"
    assert clean_text(raw) == "[표 제목: 안내] [제도: 징병검사] \n\n다음"   # 빈 칸만 지우고 줄바꿈은 남긴다


async def test_format_shows_merged_location(store):
    r = Retriever(store, RecordingEmbedder({}, default=(0.0, 1.0, 0.0)))
    text = format_chunks(store, "범정관", await r.search("범정관", 1, None))
    assert "(1) 캠퍼스 맵 > 건물 > 범정관" in text and "정문에서 직진" in text
