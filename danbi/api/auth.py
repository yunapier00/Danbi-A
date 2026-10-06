"""Google 로그인 (OAuth 2.0 인가 코드 + PKCE, OpenID Connect). 설정 가이드: docs/GOOGLE_LOGIN.md

흐름: [Google로 로그인] 링크 → GET /api/auth/login (state·nonce·PKCE를 만들고 Google로 보냄)
      → Google 로그인·동의 → GET /api/auth/callback (code를 서버가 토큰으로 바꾸고 ID 토큰 검증)
      → 사용자 저장·세션 발급 → 원래 화면으로.  GET /api/me, POST /api/auth/logout.

보안 원칙
- 프론트에 Google 스크립트를 넣지 않는다 (CSP 'self' 유지). 버튼은 그냥 링크.
- 브라우저에는 무작위 세션 ID만 `__Host-` 쿠키(HttpOnly·Secure·SameSite=Lax)로 준다. 서버에는 그 SHA-256만 저장한다.
- Google 토큰은 ID 토큰 검증에만 쓰고 저장하지 않는다 (범위: openid email profile).
- ID 토큰은 서명·iss·aud·exp(google-auth) + nonce + email_verified + hd·이메일 도메인을 모두 확인한다.
- 사용자는 이메일이 아니라 Google `sub`로 식별한다. 로그인 후 이동 주소는 같은 사이트의 상대 경로만 허용한다.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from collections.abc import Callable
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..config import AuthSettings
from ..ops.store import TraceStore

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
SESSION_COOKIE = "__Host-danbi_session"
FLOW_COOKIE = "__Host-danbi_oauth"
FLOW_TTL = 600            # 로그인 화면에서 돌아오기까지 허용 시간 (초)
MAX_PENDING = 5000        # 진행 중인 로그인 상한 (메모리 보호)
TOUCH_EVERY = 3600        # 세션 만료 연장은 1시간에 한 번만 DB에 쓴다


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def hash_session(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def safe_next(target: str | None) -> str:
    """로그인 후 이동할 곳: 같은 사이트의 상대 경로만 (//evil.com, https://… 같은 오픈 리다이렉트 차단)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


def default_verifier(token: str, client_id: str) -> dict:
    """Google 공개키로 ID 토큰 서명·발급자·대상·만료를 검증한다 (google-auth, 키는 라이브러리가 캐시)."""
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, g_requests.Request(), audience=client_id)


class Auth:
    def __init__(self, store: TraceStore, settings: AuthSettings, *, client_of: Callable[[Request], str],
                 http: httpx.AsyncClient | None = None, verifier: Callable[[str, str], dict] | None = None):
        self.store = store
        self.settings = settings
        self.client_of = client_of
        self._http = http
        self.verifier = verifier or default_verifier
        self._pending: dict[str, tuple[str, str, str, float]] = {}  # state → (nonce, code_verifier, next, 만든 시각)

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=10)
        return self._http

    # --- 세션 ------------------------------------------------------------------------

    def current_user(self, request: Request) -> dict | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token or len(token) > 200:
            return None
        h = hash_session(token)
        user = self.store.session_user(h)
        if user is not None and time.time() - user["session_last_seen_at"] > TOUCH_EVERY:
            self.store.touch_session(h, self.settings.session_days * 86400)
        return user

    def admin_status(self, request: Request) -> tuple[str | None, str | None]:
        """('ok' | 'stale' | 'not_admin' | None, 이메일). 개발자 페이지는 관리자 목록 + 최근 로그인만."""
        user = self.current_user(request)
        if user is None:
            return None, None
        email = user["email"].lower()
        if email not in self.settings.admin_emails:
            return "not_admin", email
        if time.time() - user["session_created_at"] > self.settings.admin_session_hours * 3600:
            return "stale", email
        return "ok", email

    # --- 로그인 흐름 ---------------------------------------------------------------------

    def redirect_uri(self, request: Request) -> str:
        base = self.settings.public_url
        if not base:  # 로컬 개발: 요청한 주소 그대로 (Vite 프록시를 거치면 localhost:5173)
            base = str(request.base_url).rstrip("/")
        return base + "/api/auth/callback"

    def _prune(self) -> None:
        now = time.time()
        for s in [s for s, v in self._pending.items() if now - v[3] > FLOW_TTL]:
            del self._pending[s]
        while len(self._pending) > MAX_PENDING:
            self._pending.pop(next(iter(self._pending)))

    def start(self, request: Request, next_path: str | None) -> RedirectResponse:
        self._prune()
        state, nonce, verifier = _b64(secrets.token_bytes(24)), _b64(secrets.token_bytes(24)), _b64(secrets.token_bytes(48))
        self._pending[state] = (nonce, verifier, safe_next(next_path), time.time())
        params = {
            "client_id": self.settings.client_id, "redirect_uri": self.redirect_uri(request), "response_type": "code",
            "scope": "openid email profile", "state": state, "nonce": nonce,
            "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
            "hd": self.settings.allowed_domain,  # 학교 계정을 먼저 보여주는 힌트일 뿐, 검증은 콜백에서 한다
            "prompt": "select_account",
        }
        resp = RedirectResponse(f"{AUTH_URL}?{urlencode(params)}", status_code=302)
        # 이 브라우저에서 시작한 로그인인지 묶어 둔다 (다른 사람이 만든 state로 로그인시키는 공격 방지)
        resp.set_cookie(FLOW_COOKIE, state, max_age=FLOW_TTL, httponly=True, secure=True, samesite="lax", path="/")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def check_claims(self, claims: dict, nonce: str) -> str | None:
        """ID 토큰 내용 확인. 문제가 있으면 오류 코드를 돌려준다."""
        domain = self.settings.allowed_domain.lower()
        email = str(claims.get("email") or "").lower()
        if claims.get("iss") not in ISSUERS or claims.get("aud") != self.settings.client_id:
            return "token"
        if not secrets.compare_digest(str(claims.get("nonce") or "").encode(), nonce.encode()):  # 바이트로 (비ASCII면 str 비교가 예외)
            return "token"
        if claims.get("email_verified") is not True:
            return "unverified"
        if domain and (str(claims.get("hd") or "").lower() != domain or not email.endswith("@" + domain)):
            return "domain"
        if not claims.get("sub"):
            return "token"
        return None

    async def finish(self, request: Request) -> RedirectResponse:
        q = request.query_params
        state = q.get("state", "")
        pending = self._pending.pop(state, None) if state else None
        cookie_state = request.cookies.get(FLOW_COOKIE, "")
        if pending is None or not cookie_state or not secrets.compare_digest(cookie_state.encode(), state.encode()) \
                or time.time() - pending[3] > FLOW_TTL:
            return self._fail("state")
        nonce, verifier, next_path, _ = pending
        if q.get("error") or not q.get("code"):
            return self._fail("cancelled" if q.get("error") == "access_denied" else "google")
        try:
            res = await self.http().post(TOKEN_URL, data={
                "code": q["code"], "client_id": self.settings.client_id, "client_secret": self.settings.client_secret,
                "redirect_uri": self.redirect_uri(request), "grant_type": "authorization_code", "code_verifier": verifier})
            res.raise_for_status()
            raw_id_token = res.json()["id_token"]
            claims = await asyncio.to_thread(self.verifier, raw_id_token, self.settings.client_id)
        except Exception as e:  # 네트워크·검증 실패 (메시지에 토큰이 섞이지 않게 종류만 남긴다)
            log.warning("Google 로그인 토큰 교환·검증 실패: %s", type(e).__name__)
            return self._fail("google")
        if err := self.check_claims(claims, nonce):
            log.info("Google 로그인 거부: %s (%s)", err, claims.get("hd") or "도메인 없음")
            return self._fail(err)
        ip = self.client_of(request)
        user = self.store.upsert_user(google_sub=str(claims["sub"]), email=str(claims["email"]),
                                      name=claims.get("name"), hd=claims.get("hd"), ip=ip)
        if user["blocked"]:
            return self._fail("blocked")
        token = secrets.token_urlsafe(32)  # 로그인할 때마다 새 세션 (세션 고정 공격 방지)
        old = request.cookies.get(SESSION_COOKIE)
        if old:
            self.store.delete_session(hash_session(old))
        self.store.create_session(user["id"], hash_session(token), self.settings.session_days * 86400, ip)
        resp = RedirectResponse(next_path, status_code=302)
        resp.set_cookie(SESSION_COOKIE, token, max_age=int(self.settings.session_days * 86400), httponly=True,
                        secure=True, samesite="lax", path="/")
        resp.delete_cookie(FLOW_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def _fail(self, code: str) -> RedirectResponse:
        resp = RedirectResponse(f"/?login_error={code}", status_code=302)
        resp.delete_cookie(FLOW_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def logout(self, request: Request, resp) -> None:
        if token := request.cookies.get(SESSION_COOKIE):
            self.store.delete_session(hash_session(token))
        resp.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


def mount_auth(app: FastAPI, auth: Auth, *, allow_anonymous: bool, remaining_of: Callable[[dict | None, Request], int | None]):
    def require_config():
        if not auth.enabled:
            raise HTTPException(503, "로그인이 설정되지 않았습니다 (GOOGLE_CLIENT_ID·GOOGLE_CLIENT_SECRET).")

    @app.get("/api/auth/login", include_in_schema=False)
    def login(request: Request, next: str | None = None):
        require_config()
        return auth.start(request, next)

    @app.get("/api/auth/callback", include_in_schema=False)
    async def callback(request: Request):
        require_config()
        return await auth.finish(request)

    @app.post("/api/auth/logout")
    def logout(request: Request):
        from fastapi.responses import JSONResponse
        resp = JSONResponse({"ok": True})
        auth.logout(request, resp)
        return resp

    @app.get("/api/me")
    def me(request: Request):
        user = auth.current_user(request) if auth.enabled else None
        return {
            "user": {"email": user["email"], "name": user["name"]} if user else None,
            "login_enabled": auth.enabled, "anonymous_allowed": allow_anonymous,
            "domain": auth.settings.allowed_domain,
            "remaining": remaining_of(user, request) if (user or allow_anonymous) else None,
        }
