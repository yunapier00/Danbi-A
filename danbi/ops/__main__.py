"""추적 DB 운영 명령.

  python -m danbi.ops stats [--days 7]     # 최근 기간 요약
  python -m danbi.ops verify               # 감사 로그 해시 체인 무결성 검사
  python -m danbi.ops purge [--days N]     # 보관 기간(기본: ops.retention_days)이 지난 실행 삭제, ops.ip_retention_days가 지난 IP 비움 (감사 로그는 남김)
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time

from ..config import load_settings
from .store import TraceStore


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="단비 추적 DB 운영")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stats")
    s.add_argument("--days", type=float, default=7)
    sub.add_parser("verify")
    p = sub.add_parser("purge")
    p.add_argument("--days", type=float, help="이보다 오래된 실행 삭제 (기본: ops.retention_days)")
    args = ap.parse_args()

    settings = load_settings()
    store = TraceStore(settings.ops.db_path)
    actor = f"cli:{getpass.getuser()}"
    if args.cmd == "stats":
        t = store.overview(since=time.time() - args.days * 86400)["totals"]
        print(json.dumps(t, ensure_ascii=False, indent=2))
    elif args.cmd == "verify":
        result = store.verify_audit()
        store.audit(actor, "verify_audit", "", {"ok": result["ok"], "rows": result["rows"]})
        print(("무결성 확인: " if result["ok"] else f"무결성 경고: {result['broken_at']}번 행부터 불일치, ") + f"{result['rows']}행")
        sys.exit(0 if result["ok"] else 1)
    elif args.cmd == "purge":
        days = args.days if args.days is not None else settings.ops.retention_days
        n = store.purge(days, settings.ops.ip_retention_days)
        store.audit(actor, "purge", f"older_than_days={days}",
                    {"deleted_runs": n, "ip_older_than_days": settings.ops.ip_retention_days})
        print(f"{days}일보다 오래된 실행 {n}건을 삭제했습니다 (감사 로그는 유지).")


if __name__ == "__main__":
    main()
