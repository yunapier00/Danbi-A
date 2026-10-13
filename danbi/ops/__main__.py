"""추적 DB 운영 명령.

  python -m danbi.ops stats [--days 7]     # 최근 기간 요약
  python -m danbi.ops verify               # 감사 로그 해시 체인 무결성 검사
  python -m danbi.ops purge [--days N]     # 보관 기간(기본: ops.retention_days)이 지난 실행 삭제, ops.ip_retention_days가 지난 IP 비움 (감사 로그는 남김)

질문 이용권 (웹 로그인 사용자, 이메일 기준 — 아직 로그인한 적 없는 사람에게도 줄 수 있다):
  python -m danbi.ops grant --email a@dankook.ac.kr --daily 20 --until 2026-12-31   # 그날까지 하루 20회
  python -m danbi.ops grant --email a@dankook.ac.kr --credits 50 [--days 90]        # 하루 한도를 다 쓴 뒤 쓸 50회
  python -m danbi.ops grants [--email …] [--all]                                    # 이용권 목록 (--all: 만료·취소 포함)
  python -m danbi.ops revoke <이용권 ID>                                              # 이용권 취소
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone

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
    g = sub.add_parser("grant", help="질문 이용권 주기")
    g.add_argument("--email", required=True)
    kind = g.add_mutually_exclusive_group(required=True)
    kind.add_argument("--daily", type=int, help="기간 동안 하루 질문 한도 (기본 한도보다 클 때만 의미 있음)")
    kind.add_argument("--credits", type=int, help="하루 한도를 다 쓴 뒤 쓸 추가 질문 수")
    until = g.add_mutually_exclusive_group()
    until.add_argument("--until", help="이 날짜(한국 시간)까지, YYYY-MM-DD")
    until.add_argument("--days", type=float, help="지금부터 며칠 동안")
    g.add_argument("--note", help="메모 (예: 조교, 이벤트 당첨)")
    ls = sub.add_parser("grants", help="이용권 목록")
    ls.add_argument("--email")
    ls.add_argument("--all", action="store_true", help="만료·취소된 것도")
    rv = sub.add_parser("revoke", help="이용권 취소")
    rv.add_argument("id", type=int)
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
        if days is None and settings.ops.ip_retention_days is None:
            print("보관 기간이 무기한으로 설정돼 있어 지울 것이 없습니다 (--days N으로 직접 지정 가능).")
            return
        n = store.purge(days, settings.ops.ip_retention_days)
        store.audit(actor, "purge", f"older_than_days={days}",
                    {"deleted_runs": n, "ip_older_than_days": settings.ops.ip_retention_days})
        print(f"{days}일보다 오래된 실행 {n}건을 삭제했습니다 (감사 로그는 유지)." if days is not None
              else f"{settings.ops.ip_retention_days}일보다 오래된 IP를 비웠습니다 (실행 기록은 무기한 보관).")

    elif args.cmd == "grant":
        email = args.email.strip().lower()
        domain = settings.auth.allowed_domain
        if domain and not email.endswith("@" + domain):
            print(f"주의: {domain} 계정이 아닙니다. 웹 로그인이 이 도메인만 받으므로 이 이용권은 쓰이지 않습니다.")
        expires = (_end_of_kst_day(args.until) if args.until
                   else time.time() + args.days * 86400 if args.days else None)
        kind, amount = ("daily", args.daily) if args.daily is not None else ("credits", args.credits)
        try:
            gid = store.add_grant(email=email, kind=kind, amount=amount, starts_at=time.time(), expires_at=expires,
                                  created_by=actor, note=args.note)
        except ValueError as e:
            sys.exit(f"이용권을 만들지 못했습니다: {e}")
        store.audit(actor, "grant", email, {"id": gid, "kind": kind, "amount": amount, "expires_at": expires,
                                            "note": args.note})
        print(f"이용권 {gid}: {email} {_describe(kind, amount)}, {_when(expires)}")
    elif args.cmd == "grants":
        rows = store.list_grants(args.email, include_inactive=args.all)
        if not rows:
            print("이용권이 없습니다.")
        for r in rows:
            state = "취소됨" if r["revoked_at"] else ("만료" if r["expires_at"] and r["expires_at"] <= time.time() else "유효")
            left = f" (남은 {r['left']}회)" if r["kind"] == "credits" else ""
            print(f"[{r['id']}] {state} · {r['email']} · {_describe(r['kind'], r['amount'])}{left} · {_when(r['expires_at'])}"
                  f" · {r['source']}" + (f" · {r['note']}" if r["note"] else ""))
    elif args.cmd == "revoke":
        if not store.revoke_grant(args.id, actor):
            sys.exit(f"이용권 {args.id}이(가) 없거나 이미 취소됐습니다.")
        store.audit(actor, "revoke_grant", str(args.id))
        print(f"이용권 {args.id}을(를) 취소했습니다.")


KST = timezone(timedelta(hours=9))


def _end_of_kst_day(value: str) -> float:
    d = date.fromisoformat(value)
    return datetime(d.year, d.month, d.day, tzinfo=KST).timestamp() + 86400  # 그날 자정(다음 날 00:00)까지


def _when(expires: float | None) -> str:
    if expires is None:
        return "무기한"
    return datetime.fromtimestamp(expires - 1, KST).strftime("%Y-%m-%d %H:%M까지")


def _describe(kind: str, amount: int) -> str:
    return f"하루 {amount}회" if kind == "daily" else f"추가 {amount}회"


if __name__ == "__main__":
    main()
