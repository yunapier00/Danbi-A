"""개발자 전용 API (/api/admin/*)와 페이지(/dev).

인증: Google 로그인 + 관리자 목록(DANBI_ADMIN_EMAILS), 또는 비상용 `Authorization: Bearer <DANBI_ADMIN_TOKEN>`.
둘 다 없으면 전부 503. 로그인 쿠키를 쓰는 쓰기 요청은 main.py의 같은 출처 검사가 CSRF를 막는다 (관리 API는 읽기만 한다).

감사: 인증 실패, 개별 실행·프롬프트 원문 열람, 내보내기, 감사 로그 검증을 audit_log에 남긴다.
집계 화면(개요·목록)은 자동 새로고침이 잦아 감사 대상에서 뺐다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..ops.store import TraceStore

RANGES = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "90d": 90 * 86400, "all": None}


def _period(range_: str, since: float | None, until: float | None) -> tuple[float | None, float | None, str]:
    if since is not None or until is not None:
        return since, until, "day"
    if range_ not in RANGES:
        raise HTTPException(400, f"range는 {', '.join(RANGES)} 중 하나")
    seconds = RANGES[range_]
    return (time.time() - seconds if seconds else None), None, ("hour" if range_ == "24h" else "day")


def mount_admin(app: FastAPI, store: TraceStore, token: str | None, *,
                client_of: Callable[[Request], str] | None = None, fail_limiter=None,
                admin_status: Callable[[Request], tuple[str | None, str | None]] | None = None,
                admin_emails_set: bool = False) -> None:
    """두 가지 인증:
    - Google 로그인 + 관리자 목록(DANBI_ADMIN_EMAILS): admin_status가 ('ok', 이메일)이면 통과. 감사 로그에 이메일이 남는다.
    - 비상용 토큰(DANBI_ADMIN_TOKEN): `Authorization: Bearer …`. 비워 두면 꺼진다.
    fail_limiter: IP별 토큰 실패 허용 횟수 (RateLimiter). 넘으면 429로 막고 감사 로그도 더 쌓지 않는다."""
    router = APIRouter(prefix="/api/admin")
    fingerprint = hashlib.sha256(token.encode()).hexdigest()[:8] if token else ""
    google_admin = admin_status is not None and admin_emails_set

    def client(request: Request) -> str:
        if client_of is not None:
            return client_of(request)
        return request.client.host if request.client else ""

    def require_admin(request: Request) -> str:
        if not token and not google_admin:
            raise HTTPException(503, "개발자 페이지가 꺼져 있습니다. DANBI_ADMIN_EMAILS(Google 로그인) 또는 "
                                     "DANBI_ADMIN_TOKEN을 설정하세요.")
        ip = client(request)
        given = request.headers.get("authorization", "")
        if google_admin and not given:
            status, email = admin_status(request)
            if status == "ok":
                return f"google:{email}"
            if status == "stale":
                raise HTTPException(401, "개발자 페이지는 로그인한 지 오래되면 다시 로그인해야 합니다.")
            if status == "not_admin":
                store.audit(f"google:{email}", "auth_failed", request.url.path, client=ip)
                raise HTTPException(403, "관리자 계정이 아닙니다.")
            raise HTTPException(401, "로그인이 필요합니다.")
        if not token:
            raise HTTPException(401, "로그인이 필요합니다.")
        if fail_limiter is not None and not fail_limiter.check(ip):
            raise HTTPException(429, "토큰 입력 실패가 많습니다. 10분 뒤에 다시 시도하세요.")
        given = given[7:] if given.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(given.encode(), token.encode()):
            if fail_limiter is not None:
                fail_limiter.hit(ip)
            store.audit("anonymous", "auth_failed", request.url.path, client=ip)
            raise HTTPException(401, "토큰이 올바르지 않습니다.")
        return f"admin:{fingerprint}"

    @router.get("/whoami")
    def whoami(request: Request, actor: str = Depends(require_admin)):
        store.audit(actor, "login", "/dev", client=client(request))
        return {"actor": actor}

    @router.get("/overview")
    def overview(range: str = "7d", channel: str | None = None, since: float | None = None,
                 until: float | None = None, _: str = Depends(require_admin)):
        s, u, bucket = _period(range, since, until)
        return store.overview(s, u, channel or None, bucket)

    @router.get("/runs")
    def runs(range: str = "7d", channel: str | None = None, status: str | None = None, tool: str | None = None,
             q: str | None = None, limit: int = 50, offset: int = 0, _: str = Depends(require_admin)):
        s, u, _bucket = _period(range, None, None)
        return store.list_runs(since=s, until=u, channel=channel or None, status=status or None, tool=tool or None,
                               q=q or None, limit=max(1, min(limit, 200)), offset=max(0, offset))

    @router.get("/runs/{run_id}")
    def run(run_id: str, request: Request, actor: str = Depends(require_admin)):
        detail = store.run_detail(run_id)
        if detail is None:
            raise HTTPException(404, "실행을 찾을 수 없습니다.")
        store.audit(actor, "view_run", run_id, client=client(request))
        return detail

    @router.get("/prompts/{h}")
    def prompt(h: str, request: Request, actor: str = Depends(require_admin)):
        pv = store.prompt_version(h)
        if pv is None:
            raise HTTPException(404, "프롬프트 버전을 찾을 수 없습니다.")
        store.audit(actor, "view_prompt", h, client=client(request))
        return pv

    @router.get("/audit")
    def audit(request: Request, limit: int = 200, actor: str = Depends(require_admin)):
        result = store.verify_audit()
        store.audit(actor, "verify_audit", "", {"ok": result["ok"], "rows": result["rows"]}, client=client(request))
        return {"verify": result, "items": store.audit_rows(max(1, min(limit, 1000)))}

    @router.get("/export")
    def export(request: Request, range: str = "30d", actor: str = Depends(require_admin)):
        s, u, _bucket = _period(range, None, None)
        store.audit(actor, "export", range, client=client(request))

        def lines():
            for detail in store.export_runs(s, u):
                yield json.dumps(detail, ensure_ascii=False) + "\n"

        name = f"danbi_runs_{range}_{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        return StreamingResponse(lines(), media_type="application/x-ndjson",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    app.include_router(router)  # /dev 화면 자체는 main.py가 React 앱으로 내보낸다
