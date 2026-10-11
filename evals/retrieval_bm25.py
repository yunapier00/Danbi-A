"""키워드 점수 방식 비교: 지금 방식(simple) vs 정식 BM25(검색어 단위) vs 글자 2개 단위 BM25 (API 호출 없음, 임베딩 캐시).

  .venv/Scripts/python -m evals.retrieval_bm25 [--set retrieval_holdout.yaml]

1부: 키워드 검색만 따로 (벡터 없이) — 키워드 방식 자체의 품질
2부: 실제 검색 경로 (벡터 + 키워드 RRF, 잡음 정리 등 전부), k=6
"""

import argparse
import asyncio
from dataclasses import replace

import yaml

from danbi.config import load_settings
from danbi.rag.retriever import RetrievalOptions, Retriever, format_chunks
from evals.retrieval_run import ROOT, CachedEmbedder, is_gold, open_store

LEXICAL = [
    ("simple (지금)", RetrievalOptions()),
    ("BM25 단어 b=0", RetrievalOptions(lexical="bm25", bm25_b=0.0)),
    ("BM25 단어 b=0.3", RetrievalOptions(lexical="bm25", bm25_b=0.3)),
    ("BM25 단어 b=0.75", RetrievalOptions(lexical="bm25", bm25_b=0.75)),
    ("BM25 바이그램 b=0.3", RetrievalOptions(lexical="bm25_bigram", bm25_b=0.3)),
    ("BM25 바이그램 b=0.75", RetrievalOptions(lexical="bm25_bigram", bm25_b=0.75)),
]


def metrics(ranks: list[int | None], n: int) -> str:
    h1 = sum(f == 1 for f in ranks)
    h3 = sum(bool(f and f <= 3) for f in ranks)
    h6 = sum(bool(f and f <= 6) for f in ranks)
    mrr = sum(1 / f for f in ranks if f) / n
    return f"hit@1 {h1/n:4.0%}  hit@3 {h3/n:4.0%}  hit@6 {h6/n:4.0%}  MRR {mrr:.3f}"


async def main(set_name: str):
    s = load_settings()
    store = open_store(s)
    emb = CachedEmbedder(s)
    r = Retriever(store, emb)
    items = yaml.safe_load((ROOT / set_name).read_text(encoding="utf-8"))
    n = len(items)
    print(f"## {set_name} ({n}문항), DB {s.rag.chroma_path.name}\n")
    print("1부: 키워드 검색만 (벡터 없이, 상위 6)")
    for name, opts in LEXICAL:
        ranks = []
        for it in items:
            ids = r.lexical_rank(it["q"], None, opts)[:6]
            hits = [k for k, cid in enumerate(ids, 1) if is_gold(store, r.chunks[cid], it["gold"])]
            ranks.append(hits[0] if hits else None)
        print(f"  {name:22} {metrics(ranks, n)}")
    print("\n2부: 실제 검색 경로 (벡터 + 키워드 RRF + 정리), k=6")
    for name, base in LEXICAL:
        for w in (0.3, 0.5):
            opts = replace(base, keyword_weight=w)
            ranks, chars = [], 0
            for it in items:
                cs = await r.search(it["q"], 6, None, opts)
                hits = [k for k, c in enumerate(cs, 1) if is_gold(store, c, it["gold"], r.chunks)]
                ranks.append(hits[0] if hits else None)
                chars += len(format_chunks(store, it["q"], cs))
            print(f"  {name:22} w={w}  {metrics(ranks, n)}  글자 {chars/n:,.0f}")
    emb.save()
    if emb.calls:
        print("임베딩 API 호출", emb.calls)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="retrieval.yaml")
    asyncio.run(main(ap.parse_args().set))
