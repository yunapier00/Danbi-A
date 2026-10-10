"""검색(RAG) 평가: evals/retrieval.yaml의 질문으로 search_knowledge 검색 결과만 채점한다 (LLM 없음).

  .venv/Scripts/python -m evals.retrieval_run --check        # 정답 기준이 DB 청크와 맞는지만 확인 (API 없음)
  .venv/Scripts/python -m evals.retrieval_run                # 현재 설정으로 채점
  .venv/Scripts/python -m evals.retrieval_run --compare      # 여러 검색 방식 비교

질문 임베딩은 Gemini API로 한 번만 계산하고 evals/results/embed_cache.json에 저장한다 (다시 돌리면 호출 없음).
지표: hit@k (정답이 상위 k개 안에 하나라도 있으면 1), MRR (첫 정답 순위의 역수 평균), 결과 글자 수(LLM 입력 크기).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml

from danbi.config import load_settings
from danbi.rag.chroma_store import ChromaStore, Chunk
from danbi.rag.retriever import RetrievalOptions, Retriever, format_chunks

ROOT = Path(__file__).parent
DBS = {"old": ("chroma_db_dd3", "campus_rules"), "new": ("chroma_db_v2", "danbi_docs")}
DB = {"name": None}   # --db로 고른 DB (None이면 settings.yaml의 rag.chroma_path·collection)


def open_store(settings) -> ChromaStore:
    if DB["name"]:
        path, col = DBS[DB["name"]]
        return ChromaStore(ROOT.parent / path, col, settings.rag.sources)
    return ChromaStore(settings.rag.chroma_path, settings.rag.collection, settings.rag.sources)
CACHE = ROOT / "results" / "embed_cache.json"
K = 8


class CachedEmbedder:
    """디스크에 저장해 두는 질의 임베딩 (같은 질문은 API를 다시 부르지 않는다)."""

    def __init__(self, settings):
        self.settings = settings
        self.cache: dict[str, list[float]] = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
        self._live = None
        self.calls = 0

    async def embed_query(self, text: str) -> list[float]:
        key = " ".join(text.split())
        if key not in self.cache:
            if self._live is None:
                from danbi.rag.embedder import GeminiEmbedder
                self._live = GeminiEmbedder(self.settings.embedding)
            self.cache[key] = await self._live.embed_query(key)
            self.calls += 1
        return self.cache[key]

    def save(self) -> None:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(self.cache), encoding="utf-8")


def is_gold(store: ChromaStore, c: Chunk, gold: list[dict], parts: dict[str, Chunk] | None = None) -> bool:
    """합친 청크(c.parts)는 원래 조각 중 하나라도 정답이면 정답 (합친 덩어리 안에 그 내용이 들어 있다)."""
    if c.parts and parts:
        return any(is_gold(store, parts[p], gold) for p in c.parts if p in parts)
    short = store.info[c.source].short if c.source in store.info else c.source
    heads = " ".join(c.headings)
    return any((not g.get("src") or g["src"] == short) and (not g.get("head") or g["head"] in heads)
               and (not g.get("text") or g["text"] in c.text) for g in gold)


def check(store: ChromaStore, items: list[dict]) -> int:
    rows = store.col.get(include=["documents", "metadatas"])
    chunks = [store._chunk(i, d, m, None) for i, d, m in zip(rows["ids"], rows["documents"], rows["metadatas"])]
    bad = 0
    for it in items:
        n = sum(is_gold(store, c, it["gold"]) for c in chunks)
        if n == 0:
            bad += 1
        print(f"{'OK ' if n else '없음'} {it['id']:18} 정답 청크 {n}개")
    return bad


async def score(retriever: Retriever, store: ChromaStore, items: list[dict], opts: RetrievalOptions,
                verbose: bool = False) -> dict:
    hits = {1: 0, 3: 0, K: 0}
    rr, chars, misses = 0.0, 0, []
    for it in items:
        chunks = await retriever.search(it["q"], K, None, opts)
        ranks = [n for n, c in enumerate(chunks, 1) if is_gold(store, c, it["gold"], retriever.chunks)]
        first = ranks[0] if ranks else None
        for k in hits:
            hits[k] += bool(first and first <= k)
        rr += 1 / first if first else 0
        chars += len(format_chunks(store, it["q"], chunks))
        if not first or first > 3:
            misses.append((it["id"], first))
        if verbose:
            print(f"  {it['id']:18} 첫 정답 {first or '-':>2}  | " + " / ".join(
                f"{(store.info[c.source].short if c.source in store.info else c.source)}:{(c.headings or ['-'])[-1][:14]}"
                for c in chunks[:4]))
    n = len(items)
    return {"hit@1": hits[1] / n, "hit@3": hits[3] / n, f"hit@{K}": hits[K] / n, "mrr": rr / n,
            "chars": chars / n, "misses": misses}


_OFF = dict(hybrid=False, glossary=False, denoise=False, merge=False, clean=False)
STRATEGIES = {
    "기준선 (벡터 + 조항번호)": RetrievalOptions.baseline(),
    "벡터 후보 30 + RRF만": RetrievalOptions(**_OFF),
    "+ 키워드(하이브리드)": RetrievalOptions(**{**_OFF, "hybrid": True}),
    "+ 키워드 + 줄임말": RetrievalOptions(**{**_OFF, "hybrid": True, "glossary": True}),
    "+ 잡음 뒤로": RetrievalOptions(**{**_OFF, "denoise": True}),
    "+ 조각 합치기": RetrievalOptions(**{**_OFF, "merge": True}),
    "+ 표 정리": RetrievalOptions(**{**_OFF, "clean": True}),
    "전부 (현재 기본값)": RetrievalOptions(),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--set", default="retrieval.yaml", help="평가 세트 파일 (검증용: retrieval_holdout.yaml)")
    ap.add_argument("--db", choices=list(DBS), help="old = 기존 chroma_db_dd3, new = scripts.build_rag로 만든 chroma_db_v2")
    args = ap.parse_args(argv)
    DB["name"] = args.db
    settings = load_settings()
    store = open_store(settings)
    items = yaml.safe_load((ROOT / args.set).read_text(encoding="utf-8"))
    if args.check:
        return 1 if check(store, items) else 0
    embedder = CachedEmbedder(settings)
    retriever = Retriever(store, embedder)
    strategies = STRATEGIES if args.compare else {"현재 기본값": RetrievalOptions()}
    try:
        for name, opts in strategies.items():
            r = asyncio.run(score(retriever, store, items, opts, args.verbose))
            print(f"\n[{name}] hit@1 {r['hit@1']:.0%}  hit@3 {r['hit@3']:.0%}  hit@{K} {r[f'hit@{K}']:.0%}  "
                  f"MRR {r['mrr']:.3f}  결과 평균 {r['chars']:,.0f}자")
            print("  3위 밖:", ", ".join(f"{i}({f or '없음'})" for i, f in r["misses"]) or "없음")
    finally:
        embedder.save()
        print(f"\n임베딩 API 호출 {embedder.calls}회 (나머지는 캐시)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
