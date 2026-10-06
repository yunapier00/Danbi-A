"""Google 로그인 흐름 (Google 서버 없이: 토큰 엔드포인트는 MockTransport, ID 토큰 검증은 가짜 함수)."""

import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from danbi.agent.loop import Agent
from danbi.agent.tools import ToolRegistry
from danbi.api.auth import SESSION_COOKIE, hash_session, safe_next
from danbi.api.main import create_app
from danbi.config import AuthSettings, LimitSettings
from danbi.ops import TraceRecorder, TraceStore

from .fakes import FakeProvider, Reply
from .test_api import events

CLIENT_ID = "test-client.apps.googleusercontent.com"
ADMIN = "admin@dankook.ac.kr"


class FakeGoogle:
    """토큰 교환 요청을 받아 두고, verifier는 지금 설정된 claims를 돌려준다."""

    def __init__(self):
        self.claims: dict = {}
        self.token_requests: list[dict] = []
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self._token))

    def _token(self, request: httpx.Request) -> httpx.Response:
        self.token_requests.append(dict(parse_qs(request.content.decode())))
        return httpx.Response(200, json={"id_token": "fake.id.token", "access_token": "x"})

    def verify(self, token: str, client_id: str) -> dict:
        assert token == "fake.id.token" and client_id == CLIENT_ID
        return dict(self.claims)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DANBI_ADMIN_EMAILS", ADMIN)
    monkeypatch.delenv("DANBI_PUBLIC_URL", raising=False)


def make(env, *, allow_anonymous=False, admin_token=None, replies=None, limits=None):
    store = TraceStore(None)
    agent = Agent(FakeProvider(replies or [Reply(text="답")] * 6), ToolRegistry([]))
    google = FakeGoogle()
    app = create_app(agent, recorder=TraceRecorder(store, agent), admin_token=admin_token,
                     auth=AuthSettings(allow_anonymous=allow_anonymous), auth_http=google.http,
                     auth_verifier=google.verify, limits=limits)
    return TestClient(app, base_url="https://testserver"), store, google


def claims_for(nonce: str, **over) -> dict:
    c = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1234567890", "email": "student@dankook.ac.kr",
         "email_verified": True, "hd": "dankook.ac.kr", "name": "김단국", "nonce": nonce}
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


def login(client, google, next_path="/", **over):
    r = client.get(f"/api/auth/login?next={next_path}", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    google.claims = claims_for(q["nonce"][0], **over)
    return r, client.get(f"/api/auth/callback?state={q['state'][0]}&code=abc", follow_redirects=False)


# ---- 로그인 흐름 ----

def test_login_redirect_uses_pkce_state_nonce_and_domain_hint(env):
    client, _, _ = make(env)
    r = client.get("/api/auth/login?next=/dev", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == [CLIENT_ID] and q["scope"] == ["openid email profile"] and q["hd"] == ["dankook.ac.kr"]
    assert q["code_challenge_method"] == ["S256"] and len(q["code_challenge"][0]) >= 43
    assert q["redirect_uri"] == ["https://testserver/api/auth/callback"]
    assert "__Host-danbi_oauth=" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]


def test_full_login_session_and_chat(env):
    client, store, google = make(env)
    _, cb = login(client, google, next_path="/")
    assert cb.status_code == 302 and cb.headers["location"] == "/"
    cookie = cb.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=") and "HttpOnly" in cookie and "Secure" in cookie
    assert "samesite=lax" in cookie.lower() and "Path=/" in cookie and "Domain" not in cookie
    tok = google.token_requests[0]
    assert tok["grant_type"] == ["authorization_code"] and tok["code_verifier"] and tok["client_secret"] == ["secret"]

    me = client.get("/api/me").json()
    assert me["user"] == {"email": "student@dankook.ac.kr", "name": "김단국"} and me["remaining"] == 3
    assert me["anonymous_allowed"] is False

    done = events(client.post("/api/chat", json={"message": "안녕"}))[-1]
    assert done[0] == "done" and done[1]["remaining"] == 2
    run = store.run_detail(done[1]["run_id"])
    assert run["run"]["user_key"] == "google:1" and run["run"]["client_ip"] == "testclient"
    assert run["user"]["email"] == "student@dankook.ac.kr"
    user = store._one("SELECT * FROM users")
    assert (user["first_ip"], user["last_ip"], user["name"]) == ("testclient", "testclient", "김단국")
    # 세션 ID 원문은 DB에 없다 (해시만)
    raw = client.cookies.get(SESSION_COOKIE)
    assert store._one("SELECT id_hash FROM auth_sessions")["id_hash"] == hash_session(raw) != raw


def test_anonymous_blocked_unless_enabled(env):
    client, _, _ = make(env)
    assert client.get("/api/me").json()["user"] is None
    res = client.post("/api/chat", json={"message": "q"})
    assert res.status_code == 401 and "로그인" in res.json()["detail"]
    open_client, store, _ = make(env, allow_anonymous=True)
    done = events(open_client.post("/api/chat", json={"message": "q"}))[-1]
    assert done[0] == "done" and done[1]["remaining"] == 2
    assert store.run_detail(done[1]["run_id"])["run"]["user_key"] is None   # 비로그인은 IP로 센다


@pytest.mark.parametrize("over, code", [
    ({"hd": "gmail.com", "email": "x@gmail.com"}, "domain"),
    ({"hd": None, "email": "x@gmail.com"}, "domain"),
    ({"email": "x@other.ac.kr"}, "domain"),               # hd는 맞는데 이메일 도메인이 다름
    ({"email_verified": False}, "unverified"),
    ({"aud": "someone-else"}, "token"),
    ({"iss": "https://evil.example"}, "token"),
])
def test_rejected_claims(env, over, code):
    client, store, google = make(env)
    _, cb = login(client, google, **over)
    assert cb.headers["location"] == f"/?login_error={code}" and SESSION_COOKIE not in cb.headers.get("set-cookie", "")
    assert store._one("SELECT COUNT(*) AS n FROM auth_sessions")["n"] == 0


def test_nonce_and_state_checks(env):
    client, _, google = make(env)
    r = client.get("/api/auth/login", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    google.claims = claims_for("다른-nonce")
    assert client.get(f"/api/auth/callback?state={q['state'][0]}&code=a",
                      follow_redirects=False).headers["location"] == "/?login_error=token"
    # 한 번 쓴 state는 다시 못 쓴다
    assert client.get(f"/api/auth/callback?state={q['state'][0]}&code=a",
                      follow_redirects=False).headers["location"] == "/?login_error=state"
    # 다른 브라우저(로그인 시작 쿠키 없음)에서 온 콜백
    r = client.get("/api/auth/login", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    other = TestClient(client.app, base_url="https://testserver")
    assert other.get(f"/api/auth/callback?state={q['state'][0]}&code=a",
                     follow_redirects=False).headers["location"] == "/?login_error=state"
    # 사용자가 Google 화면에서 취소
    r = client.get("/api/auth/login", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert client.get(f"/api/auth/callback?state={q['state'][0]}&error=access_denied",
                      follow_redirects=False).headers["location"] == "/?login_error=cancelled"


def test_safe_next_blocks_open_redirect(env):
    assert [safe_next(x) for x in ("/dev", "//evil.com", "https://evil.com", "/\\evil.com", None, "dev")] == \
           ["/dev", "/", "/", "/", "/", "/"]
    client, _, google = make(env)
    _, cb = login(client, google, next_path="//evil.com")
    assert cb.headers["location"] == "/"


def test_daily_limit_three_per_logged_in_user(env):
    client, _, google = make(env, limits=LimitSettings(per_user_per_day=3))
    login(client, google)
    for left in (2, 1, 0):
        assert events(client.post("/api/chat", json={"message": "q"}))[-1][1]["remaining"] == left
    res = client.post("/api/chat", json={"message": "q"})
    assert res.status_code == 429 and "3번까지" in res.json()["detail"]
    # 같은 IP의 다른 학생은 따로 센다
    other = TestClient(client.app, base_url="https://testserver")
    login(other, google, sub="999", email="other@dankook.ac.kr")
    assert events(other.post("/api/chat", json={"message": "q"}))[-1][1]["remaining"] == 2


def test_logout_and_blocked_user(env):
    client, store, google = make(env)
    login(client, google)
    assert client.post("/api/auth/logout").json() == {"ok": True}
    assert client.get("/api/me").json()["user"] is None
    assert store._one("SELECT COUNT(*) AS n FROM auth_sessions")["n"] == 0
    login(client, google)
    store.set_user_blocked(1, True)
    assert client.get("/api/me").json()["user"] is None                  # 차단하면 세션도 끊긴다
    _, cb = login(client, google)
    assert cb.headers["location"] == "/?login_error=blocked"


def test_cross_site_writes_rejected(env):
    client, _, google = make(env)
    login(client, google)
    res = client.post("/api/chat", json={"message": "q"}, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    ok = client.post("/api/chat", json={"message": "q"}, headers={"Origin": "https://testserver"})
    assert events(ok)[-1][0] == "done"
    assert client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403


def test_conversation_cannot_be_hijacked(env):
    client, _, google = make(env)
    login(client, google)
    sid = events(client.post("/api/chat", json={"message": "q"}))[0][1]["session_id"]
    other = TestClient(client.app, base_url="https://testserver")
    login(other, google, sub="999", email="other@dankook.ac.kr")
    other_sid = events(other.post("/api/chat", json={"message": "q", "session_id": sid}))[0][1]["session_id"]
    assert other_sid != sid


# ---- 개발자 페이지 ----

def test_admin_by_google_login(env):
    client, store, google = make(env)
    assert client.get("/api/admin/whoami").status_code == 401            # 로그인 전
    login(client, google)
    assert client.get("/api/admin/whoami").status_code == 403            # 관리자 목록에 없음
    admin = TestClient(client.app, base_url="https://testserver")
    login(admin, google, sub="42", email=ADMIN)
    assert admin.get("/api/admin/whoami").json() == {"actor": f"google:{ADMIN}"}
    assert admin.get("/api/admin/overview").status_code == 200
    actions = [(r["actor"], r["action"]) for r in store.audit_rows()]
    assert (f"google:{ADMIN}", "login") in actions and ("google:student@dankook.ac.kr", "auth_failed") in actions
    # 로그인한 지 12시간이 넘으면 다시 로그인
    store._exec("UPDATE auth_sessions SET created_at = ?", (time.time() - 13 * 3600,))
    assert admin.get("/api/admin/whoami").status_code == 401


def test_admin_emergency_token_still_works(env):
    client, _, _ = make(env, admin_token="tok")
    assert client.get("/api/admin/whoami", headers={"Authorization": "Bearer tok"}).json()["actor"].startswith("admin:")
    assert client.get("/api/admin/whoami", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_login_not_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    store = TraceStore(None)
    agent = Agent(FakeProvider([Reply(text="답")]), ToolRegistry([]))
    client = TestClient(create_app(agent, recorder=TraceRecorder(store, agent), auth=AuthSettings()),
                        base_url="https://testserver")
    assert client.get("/api/auth/login", follow_redirects=False).status_code == 503
    me = client.get("/api/me").json()
    assert me["login_enabled"] is False and me["user"] is None


def test_purge_keeps_everything_when_retention_is_unlimited():
    store = TraceStore(None)
    store.start_run("r1", conversation_id=None, channel="web", question="q", provider="p", model="m",
                    system_hash="s", tools_hash="t", started_at=time.time() - 400 * 86400, client_ip="1.2.3.4")
    assert store.purge(None, None) == 0
    assert store._one("SELECT client_ip FROM runs")["client_ip"] == "1.2.3.4"
    assert json.dumps(store.run_detail("r1")["run"]["client_ip"]) == '"1.2.3.4"'


def test_privacy_page(monkeypatch):
    monkeypatch.setenv("DANBI_PRIVACY_CONTACT", "danbi@example.com")
    monkeypatch.setenv("DANBI_OPERATOR", "<김단국>")
    store = TraceStore(None)
    agent = Agent(FakeProvider([Reply(text="답")]), ToolRegistry([]))
    res = TestClient(create_app(agent, recorder=TraceRecorder(store, agent))).get("/privacy")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/html")
    body = res.text
    assert "개인정보처리방침" in body and "mailto:danbi@example.com" in body
    assert "&lt;김단국&gt;" in body and "<김단국>" not in body          # 이름은 HTML로 이스케이프
    for item in ("이메일 주소", "접속 IP", "Gemini", "Railway", "카카오"):
        assert item in body
    assert "Content-Security-Policy" in res.headers
