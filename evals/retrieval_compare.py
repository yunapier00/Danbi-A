"""검색 비교: (DB × 검색 방식)을 조정용·검증용 세트에서 함께 잰다 (임베딩은 캐시, 새 질문만 API 호출).

  .venv/Scripts/python -m evals.retrieval_compare [-v]

DB: old = 기존 chroma_db_dd3 (읽기 전용), new = scripts.build_rag로 원본 PDF에서 새로 만든 chroma_db_v2
"""

import argparse
import asyncio

import yaml

from danbi.config import load_settings
from danbi.rag.retriever import RetrievalOptions, Retriever, format_chunks
from evals.retrieval_run import DB, ROOT, CachedEmbedder, is_gold, open_store

CONFIGS = (
    ("old", "기존 DB · 기준선 k=8", RetrievalOptions.baseline(), 8),
    ("old", "기존 DB · 개선 검색 k=6", RetrievalOptions(), 6),
    ("new", "새 DB · 기준선 k=8", RetrievalOptions.baseline(), 8),
    ("new", "새 DB · 개선 검색 k=6", RetrievalOptions(), 6),
)


async def main(verbose: bool):
    s = load_settings()
    emb = CachedEmbedder(s)
    retrievers = {}
    for db in ("old", "new"):
        DB["name"] = db
        store = open_store(s)
        retrievers[db] = (store, Retriever(store, emb))
    for fname in ("retrieval.yaml", "retrieval_holdout.yaml"):
        items = yaml.safe_load((ROOT / fname).read_text(encoding="utf-8"))
        firsts: dict[str, dict[str, int | None]] = {}
        print(f"\n## {fname} ({len(items)}문항)")
        for db, name, opts, k in CONFIGS:
            store, r = retrievers[db]
            h1 = h3 = hk = 0
            rr = ch = 0.0
            for it in items:
                cs = await r.search(it["q"], k, None, opts)
                rk = [n for n, c in enumerate(cs, 1) if is_gold(store, c, it["gold"], r.chunks)]
                f = rk[0] if rk else None
                firsts.setdefault(it["id"], {})[name] = f
                h1 += f == 1
                h3 += bool(f and f <= 3)
                hk += bool(f)
                rr += 1 / f if f else 0
                ch += len(format_chunks(store, it["q"], cs))
            n = len(items)
            print(f"  {name:22} hit@1 {h1/n:4.0%}  hit@3 {h3/n:4.0%}  hit@k {hk/n:4.0%}  MRR {rr/n:.3f}  글자 {ch/n:,.0f}")
        if verbose:
            a, b = CONFIGS[0][1], CONFIGS[-1][1]
            for qid, f in firsts.items():
                if f[a] != f[b]:
                    print(f"    {qid:20} {a}: {f[a] or '-'} → {b}: {f[b] or '-'}")
    emb.save()
    if emb.calls:
        print("임베딩 API 호출", emb.calls)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    asyncio.run(main(ap.parse_args().verbose))
