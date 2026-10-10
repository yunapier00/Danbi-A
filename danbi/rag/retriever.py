"""search_knowledge의 검색 로직. 평가(evals/retrieval_run.py)와 도구가 같은 코드를 쓴다.

기존 Chroma DB는 읽기만 한다. 시작할 때 청크 전체(약 2천 개)를 한 번 읽어 메모리에 두고,
벡터 검색(Chroma)과 키워드 검색(메모리)을 섞은 뒤 잡음을 뒤로 미루고 조각난 청크를 합쳐 돌려준다.

2026-10-10 검색 평가(evals/retrieval.yaml 44문항) 기준선 → 개선 수치는 docs/RETRIEVAL.md 참고.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import defaultdict
from dataclasses import dataclass, replace

from .chroma_store import ChromaStore, Chunk

_ARTICLE = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?")  # "제29조", "제 3 조의 2"
ARTICLE_LIMIT = 3
RRF_K = 60

# 학생들이 쓰는 줄임말·구어 → 문서에 쓰인 공식 용어 (키워드 검색에만 쓴다. 임베딩은 질문 그대로)
GLOSSARY: dict[str, list[str]] = {
    "학고": ["학사경고"], "조졸": ["조기졸업"], "복전": ["복수전공", "다전공"], "부전": ["부전공", "다전공"],
    "다전": ["다전공"], "전필": ["전공필수"], "전선": ["전공선택"], "교필": ["교양필수"], "계절": ["계절학기"],
    "자퇴": ["자퇴", "등록금 등의 반환"], "재수강": ["재수강", "동일과목 재수강"], "F": ["재수강"],
    "학관": ["혜당관", "학생회관"], "중도": ["퇴계기념중앙도서관", "중앙도서관"], "곰상": ["곰상", "평화의 광장"],
    "본관": ["범정관"], "학교버스": ["셔틀버스"], "버스": ["셔틀버스"], "셔틀": ["셔틀버스"],
    "토익": ["공인외국어", "TOEIC"], "졸업요건": ["졸업요건", "졸업학점"], "휴학횟수": ["휴학횟수"],
    "밤새": ["24시간"], "열람실": ["열람실"], "군대": ["입대휴학"], "입대": ["입대휴학"],
}

# 질문에 흔한데 검색에는 도움이 안 되는 말 (조사 떼기 전 원형 기준)
STOPWORDS = {
    "알려줘", "알려주세요", "어디", "어디야", "어디에", "언제", "언제야", "어떻게", "몇", "뭐야", "뭐", "있어", "있나요",
    "돼", "되나요", "하려면", "해야", "해", "수", "있는", "대한", "관련", "내용", "방법", "정도", "어느", "무엇",
    "조건", "기준", "가능해", "가능", "할", "하면", "들으면", "받으면", "맞으면", "나와", "없어", "넘게", "때",
}
# 조사·동사 어미 (긴 것부터 떼야 '제한되는' → '제한', '신청하려면' → '신청')
_JOSA = ("하려면", "되려면", "되는지", "하는지", "에서는", "으로는", "되는", "하는", "되면", "하면", "된다", "한다",
         "에서", "으로", "까지", "부터", "에는", "이면", "은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "로",
         "야", "요", "된", "한")
VECTOR_KEEP = 2   # 벡터 검색 상위 몇 개는 섞은 뒤에도 결과에 반드시 남긴다 (RRF는 한쪽 목록에만 있는 1위를 밀어낼 수 있다)


@dataclass(frozen=True)
class RetrievalOptions:
    """검색 방식. 각 항목을 끄고 켜서 효과를 따로 잴 수 있다 (evals/retrieval_run.py --compare)."""
    # 기본값은 2026-10-10 검색 평가(조정용 44문항 + 검증용 10문항)로 고른 것 (docs/RETRIEVAL.md)
    hybrid: bool = True       # 키워드 검색을 벡터 검색과 RRF로 섞는다
    glossary: bool = True     # 줄임말 → 공식 용어 (키워드 검색)
    denoise: bool = True      # 제목만 있는 청크·OCR 잡음·부칙을 뒤로
    merge: bool = True        # 같은 조항·항목의 조각을 합친다
    clean: bool = True        # 표의 빈 칸([: 없음]) 등을 지운다
    max_per_heading: int = 2  # 같은 제목의 청크는 결과에 이 수까지만 (0 = 제한 없음)
    candidates: int = 30      # 섞기 전에 방식마다 뽑는 후보 수
    keyword_weight: float = 0.3   # RRF에서 키워드 순위의 비중 (벡터 = 1). 1.0이면 흔한 단어가 엉뚱한 조항을 끌어올린다
    bm25_b: float = 0.0           # 키워드 본문 일치의 길이 보정 세기. 이 DB는 청크 길이 차이(40~1000자)가 커서 0.3 이상이면 오히려 나빠졌다
    expand_embed: bool = True     # 줄임말이 있으면 공식 용어를 덧붙여 임베딩 ('학고 …' → '학고 … (학사경고)'). 가장 효과가 컸다

    @staticmethod
    def baseline() -> "RetrievalOptions":
        """2026-10-10 이전 동작: 벡터 상위 k + 조항 번호 정확 일치."""
        return RetrievalOptions(hybrid=False, glossary=False, denoise=False, merge=False, clean=False, expand_embed=False,
                                max_per_heading=0)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


class Retriever:
    def __init__(self, store: ChromaStore, embedder):
        self.store = store
        self.embedder = embedder
        rows = store.col.get(include=["documents", "metadatas"])  # 읽기만 한다
        self.chunks: dict[str, Chunk] = {}
        self.meta: dict[str, dict] = {}
        self.groups: dict[tuple, list[str]] = defaultdict(list)
        for i, d, m in zip(rows["ids"], rows["documents"], rows["metadatas"]):
            self.chunks[i] = store._chunk(i, d, m, None)
            self.meta[i] = m
            self.groups[self._group_key(m)].append(i)
        # 키워드 검색용: 청크별 제목·본문(공백 제거)과 단어 문서빈도
        self._head = {i: _norm(" ".join(c.headings)) for i, c in self.chunks.items()}
        self._body = {i: _norm(c.text) for i, c in self.chunks.items()}
        self._n = len(self.chunks)
        self._df_cache: dict[str, int] = {}
        self._avg_len = sum(len(b) for b in self._body.values()) / max(1, self._n)

    @staticmethod
    def _group_key(m: dict) -> tuple:
        return (m.get("출처"), m.get("대제목"), m.get("중제목"))

    # --- 키워드 ---------------------------------------------------------------------

    def _df(self, term: str) -> int:
        if term not in self._df_cache:
            self._df_cache[term] = sum(1 for i in self.chunks if term in self._body[i] or term in self._head[i])
        return self._df_cache[term]

    def terms(self, query: str, glossary: bool) -> list[str]:
        """질문 → 검색어. 조사를 떼고, DB에 있는 가장 긴 앞부분으로 맞춘다 ('휴학은' → '휴학')."""
        out: list[str] = [_norm(m) for m in _ARTICLE.findall(query)]
        for raw in re.findall(r"[0-9A-Za-z가-힣]+", query):
            if raw in STOPWORDS:
                continue
            if glossary:
                for key, expands in GLOSSARY.items():
                    if raw.startswith(key):
                        out += [_norm(e) for e in expands]
            word = raw
            for j in _JOSA:
                if word.endswith(j) and len(word) - len(j) >= 2:
                    word = word[: -len(j)]
                    break
            if word in STOPWORDS:
                continue
            # 가장 긴, DB에 실제로 있는 앞부분 (2글자 이상)
            for end in range(len(word), 1, -1):
                if self._df(word[:end]) > 0:
                    out.append(word[:end])
                    break
        return [t for t in dict.fromkeys(out) if len(t) >= 2 or t.isascii()]

    def expansions(self, query: str) -> list[str]:
        """질문에 든 줄임말의 공식 용어 (임베딩 확장용)."""
        out: list[str] = []
        for raw in re.findall(r"[0-9A-Za-z가-힣]+", query):
            for key, expands in GLOSSARY.items():
                if raw.startswith(key):
                    out += [e for e in expands if e not in query]
        return list(dict.fromkeys(out))

    def keyword_rank(self, terms: list[str], files: list[str] | None, b: float = 0.0) -> list[str]:
        """제목 일치는 3배. 드문 말일수록 무겁게 (idf).
        본문 일치는 BM25처럼 길이로 나눈다: 긴 청크(PDF 표 덩어리 등)는 아무 단어나 품고 있어 점수가 부풀기 때문이다."""
        if not terms:
            return []
        weights = {t: math.log(1 + self._n / (1 + self._df(t))) for t in terms}
        scores: dict[str, float] = {}
        for i in self.chunks:
            if files and self.chunks[i].source not in files:
                continue
            norm = 1 - b + b * len(self._body[i]) / self._avg_len
            s = 0.0
            for t, w in weights.items():
                if t in self._head[i]:
                    s += 3 * w
                elif t in self._body[i]:
                    s += w / norm
            if s > 0:
                scores[i] = s
        return sorted(scores, key=lambda i: -scores[i])

    # --- 잡음 --------------------------------------------------------------------------

    def is_noise(self, cid: str, query: str) -> bool:
        c, m = self.chunks[cid], self.meta[cid]
        body = re.sub(r"^#+ .*$", "", c.text, flags=re.M).strip()
        if len(body) < 8:                                   # 제목만 있는 청크
            return True
        if str(m.get("대제목", "")).startswith("부칙") and not re.search(r"부칙|경과|시행일", query):
            return True
        if c.source.endswith(".pdf") and not c.headings:   # 제목이 없는 PDF 조각은 대부분 OCR 잡음
            hangul_words = re.findall(r"[가-힣]{2,}", body)
            if len(hangul_words) < len(body) / 25:
                return True
        return False

    # --- 검색 --------------------------------------------------------------------------

    async def search(self, query: str, k: int, files: list[str] | None,
                     opts: RetrievalOptions = RetrievalOptions()) -> list[Chunk]:
        if opts == RetrievalOptions.baseline():
            return await self._baseline(query, k, files)
        text = query
        if opts.expand_embed and (extra := self.expansions(query)):
            text = f"{query} ({', '.join(extra)})"
        embedding = await self.embedder.embed_query(text)
        vec = await asyncio.to_thread(self.store.query, embedding, max(k, opts.candidates), files)
        distance = {c.id: c.distance for c in vec}
        ranks: list[tuple[float, list[str]]] = [(1.0, [c.id for c in vec])]
        if opts.hybrid:
            ranks.append((opts.keyword_weight,
                          self.keyword_rank(self.terms(query, opts.glossary), files, opts.bm25_b)[: opts.candidates]))
        fused: dict[str, float] = defaultdict(float)
        for weight, ranking in ranks:
            for r, cid in enumerate(ranking, 1):
                fused[cid] += weight / (RRF_K + r)
        # 조항 번호 정확 일치(제목)는 맨 앞
        articles = [_norm(m) for m in _ARTICLE.findall(query)]
        article_hits = [cid for cid in fused if any(a and f"{a}(" in self._head[cid] for a in articles)]
        for cid in article_hits:
            fused[cid] += 1
        order = sorted(fused, key=lambda i: -fused[i])
        if opts.denoise:
            order = [i for i in order if not self.is_noise(i, query)] + [i for i in order if self.is_noise(i, query)]
        if opts.hybrid:
            # 벡터 상위 VECTOR_KEEP개가 섞는 과정에서 k 밖으로 밀렸으면 마지막 자리로 끌어올린다
            keep = {c.id for c in vec[:VECTOR_KEEP] if not (opts.denoise and self.is_noise(c.id, query))}
            protected = keep | set(article_hits)
            head, tail = order[:k], order[k:]
            # 자리는 보호 대상(벡터 상위·조항 번호 일치)이 아닌 항목 중 순위가 가장 낮은 것부터 비운다
            for g in [g for g in tail if g in keep]:
                drop = next((i for i in reversed(range(len(head))) if head[i] not in protected), None)
                if drop is None:
                    break
                tail.insert(0, head.pop(drop))
                head.append(g)
                tail.remove(g)
            rank = {cid: n for n, cid in enumerate(order)}   # 잡음 뒤로 보낸 순서를 그대로 유지
            order = sorted(head, key=rank.__getitem__) + sorted(tail, key=rank.__getitem__)
        out: list[Chunk] = []
        used_groups: set[tuple] = set()
        per_heading: dict[tuple, int] = defaultdict(int)
        for cid in order:
            if len(out) >= k:
                break
            if opts.max_per_heading:
                # 같은 제목의 청크(예: PDF 표의 행마다 반복된 '주요 내용')가 자리를 다 차지하지 않게
                # 섹션(대·중제목) 기준: 연도별 이수기준표처럼 소제목만 다른 비슷한 표도 함께 센다
                hk = (self.chunks[cid].source, tuple(self.chunks[cid].headings[:2]))
                if self.chunks[cid].headings and per_heading[hk] >= opts.max_per_heading:
                    continue
                per_heading[hk] += 1
            chunk = replace(self.chunks[cid], distance=distance.get(cid))
            if opts.merge:
                key = self._group_key(self.meta[cid])
                if key in used_groups:
                    continue
                merged = self._merged(cid, key)
                if merged is not None:
                    used_groups.add(key)
                    chunk = replace(merged, distance=distance.get(cid))
            if opts.clean:
                chunk = replace(chunk, text=clean_text(chunk.text))
            out.append(chunk)
        return out

    MERGE_MAX_PARTS = 8
    MERGE_MAX_CHARS = 800
    MERGE_IF_SHORTER = 200   # 이보다 짧은 조각일 때만 합친다 (충분히 긴 조항은 그대로)

    def _merged(self, cid: str, key: tuple) -> Chunk | None:
        """같은 (출처, 대제목, 중제목) 조각을 하나로. 묶음이 너무 크거나(PDF 표 등) 제목이 없으면 그대로."""
        ids = self.groups.get(key, [])
        if len(ids) < 2 or len(ids) > self.MERGE_MAX_PARTS or not key[2] \
                or len(self.chunks[cid].text) >= self.MERGE_IF_SHORTER:
            return None
        parts, seen = [], set()
        for i in sorted(ids, key=lambda x: (self.meta[x].get("소제목") or "", x != cid)):
            text = self.chunks[i].text.strip()
            if text and text not in seen:
                seen.add(text)
                parts.append(text)
        text = "\n".join(parts)
        if len(text) > self.MERGE_MAX_CHARS:
            text = text[: self.MERGE_MAX_CHARS] + " …"
        base = self.chunks[cid]
        heads = [h for h in (self.meta[cid].get("대제목"), self.meta[cid].get("중제목")) if h]
        return replace(base, text=text, headings=heads, parts=list(ids))

    async def _baseline(self, query: str, k: int, files: list[str] | None) -> list[Chunk]:
        embedding = await self.embedder.embed_query(query)
        terms = list(dict.fromkeys(_norm(m) for m in _ARTICLE.findall(query)))
        semantic, *keyword = await asyncio.gather(
            asyncio.to_thread(self.store.query, embedding, k, files),
            *(asyncio.to_thread(self.store.keyword_search, t, ARTICLE_LIMIT, files) for t in terms),
        )
        seen: set[str] = set()
        out = []
        for c in [*(c for group in keyword for c in group), *semantic]:
            if c.id not in seen:
                seen.add(c.id)
                out.append(c)
        return out


def clean_text(text: str) -> str:
    """표 조각의 빈 칸·반복을 지운다: '[: 없음] [: 없음] …', '[열: 없음]'."""
    text = re.sub(r"\[[^\[\]:\n]{0,20}:[ \t]*없음\][ \t]*", "", text)   # 줄바꿈은 남긴다
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def format_chunks(store: ChromaStore, query: str, chunks: list[Chunk]) -> str:
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
        if c.distance is not None:
            extra.append(f"거리 {c.distance:.3f}")
        out.append(f"\n({n}) {loc}" + (f" | {' | '.join(extra)}" if extra else "") + f"\n{c.text.strip()}")
    return "\n".join(out)
