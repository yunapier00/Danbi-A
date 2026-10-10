"""검색 설정 탐색 (임베딩은 캐시만 사용, API 호출 없음): 키워드 비중 × 결과 수."""

import asyncio
import sys

import yaml

from danbi.config import load_settings
from danbi.rag.chroma_store import ChromaStore
from danbi.rag.retriever import RetrievalOptions, Retriever, format_chunks
from evals.retrieval_run import ROOT, CachedEmbedder, is_gold, open_store


async def run():
    settings = load_settings()
    store = open_store(settings)
    items = yaml.safe_load((ROOT / "retrieval.yaml").read_text(encoding="utf-8"))
    emb = CachedEmbedder(settings)
    r = Retriever(store, emb)
    grid = [("벡터만 + 정리", RetrievalOptions(hybrid=False, glossary=False)),
            ("벡터만 + 정리 + 임베딩 확장", RetrievalOptions(hybrid=False, glossary=False, expand_embed=True))]
    for w in (0.3, 0.5):
        for bb in (0.0, 0.3, 0.75):
            grid.append((f"하이브리드 w={w} b={bb}", RetrievalOptions(keyword_weight=w, bm25_b=bb)))
            grid.append((f"하이브리드 w={w} b={bb} + 확장", RetrievalOptions(keyword_weight=w, bm25_b=bb, expand_embed=True)))
    print(f"{'설정':32} k  hit@1  hit@3  hit@k   MRR   글자")
    for name, opts in grid:
        for k in (6,):
            h1 = h3 = hk = 0
            rr = chars = 0.0
            for it in items:
                chunks = await r.search(it["q"], k, None, opts)
                ranks = [n for n, c in enumerate(chunks, 1) if is_gold(store, c, it["gold"], r.chunks)]
                f = ranks[0] if ranks else None
                h1 += bool(f == 1)
                h3 += bool(f and f <= 3)
                hk += bool(f)
                rr += 1 / f if f else 0
                chars += len(format_chunks(store, it["q"], chunks))
            n = len(items)
            print(f"{name:32} {k:d}  {h1/n:5.0%} {h3/n:6.0%} {hk/n:6.0%}  {rr/n:.3f} {chars/n:6,.0f}")
    if emb.calls:
        print("주의: 캐시에 없는 임베딩", emb.calls, "회 호출")
        emb.save()


if __name__ == "__main__":
    asyncio.run(run())
    sys.exit(0)
