"""eclass(Canvas) 캘린더 피드 연동: ics 파싱, 주소 검증, 암호화 저장, my_schedule 도구, API (네트워크 없이)."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from danbi.agent.loop import Agent
from danbi.agent.tools import ToolRegistry
from danbi.api.main import create_app
from danbi.config import AuthSettings
from danbi.agent.tools.personal import CONNECT_MARK, make_my_schedule
from danbi.crawler.http import FetchError, HttpClient
from danbi.ops import TraceRecorder, TraceStore
from danbi.ops.recorder import stored_result
from danbi.ops.sources import extract_sources
from danbi.personal.context import CURRENT_USER, CurrentUser
from danbi.personal.eclass import EclassError, EclassService, normalize_feed_url
from danbi.personal.ics import KST, parse_ics

from .fakes import FakeProvider, Reply
from .test_api import events
from .test_auth import FakeGoogle, env, login  # noqa: F401  (env는 pytest 픽스처)

FEED = "https://canvas.dankook.ac.kr/feeds/calendars/user_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789.ics"


def ics(today: date) -> str:
    """Canvas 피드 모양: 날짜 전용 마감(VALUE=DATE에 시각이 붙음), UTC 시각 마감, 접힌 줄, 이스케이프."""
    d1, d2, past = today + timedelta(days=2), today + timedelta(days=5), today - timedelta(days=3)
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "X-WR-CALNAME:홍길동 캘린더 (Canvas)",
        "BEGIN:VEVENT", "UID:event-assignment-1", f"DTSTART;VALUE=DATE:{d1:%Y%m%d}T000000",
        "SUMMARY:애착유형검사 결과 제출 [사랑의심", " 리학 1분반]", "DESCRIPTION:결과를 캡쳐해서\\n업로드\\, 하세요",
        "URL:https://canvas.dankook.ac.kr/calendar?include_contexts=course_1", "END:VEVENT",
        "BEGIN:VEVENT", "UID:event-assignment-2", f"DTSTART:{d2:%Y%m%d}T145900Z",  # 23:59 KST
        "SUMMARY:중간 보고서 [소프트웨어공학 2분반]", "END:VEVENT",
        "BEGIN:VEVENT", "UID:event-calendar-event-3", f"DTSTART;VALUE=DATE:{past:%Y%m%d}",
        "SUMMARY:지난 특강", "END:VEVENT",
        "BEGIN:VEVENT", "UID:broken", "SUMMARY:날짜 없음", "END:VEVENT",
        "END:VCALENDAR", ""])


TODAY = datetime.now(KST).date()


class FakeHttp:
    def __init__(self, text: str | None = None, status: int | None = None):
        self.text, self.status, self.calls = text if text is not None else ics(TODAY), status, 0

    def get_delegated(self, url):
        self.calls += 1
        if self.status:
            raise FetchError(f"HTTP {self.status}", url, self.status)
        return SimpleNamespace(text=self.text)


def service(http=None, store=None, user_id=None):
    store = store or TraceStore(None)
    if user_id is None:
        user_id = store.upsert_user(google_sub="s1", email="a@dankook.ac.kr", name="가", hd="dankook.ac.kr", ip=None)["id"]
    return EclassService(store, http or FakeHttp(), "test-secret"), store, user_id


# ---- 파싱·검증 ----

def test_parse_canvas_ics():
    evs = parse_ics(ics(TODAY))
    assert [e.uid for e in evs] == ["event-calendar-event-3", "event-assignment-1", "event-assignment-2"]  # 날짜 순, 날짜 없는 항목은 버림
    past, a1, a2 = evs
    assert (a1.kind, a1.title, a1.course, a1.time) == ("과제", "애착유형검사 결과 제출", "사랑의심리학 1분반", None)
    assert a1.day == TODAY + timedelta(days=2) and a1.description == "결과를 캡쳐해서 업로드, 하세요"
    assert a1.url.endswith("course_1")
    assert (a2.day, a2.time, a2.course) == (TODAY + timedelta(days=5), "23:59", "소프트웨어공학 2분반")  # UTC → KST
    assert past.kind == "일정" and past.course == ""


@pytest.mark.parametrize("raw", [FEED, f"  {FEED} ", FEED.replace("https://", "webcal://")])
def test_feed_url_accepted(raw):
    assert normalize_feed_url(raw) == FEED


@pytest.mark.parametrize("raw", [
    "https://evil.example/feeds/calendars/user_AbCdEfGhIjKlMnOpQrStUvWxYz.ics",
    "https://canvas.dankook.ac.kr/courses/1",
    "https://canvas.dankook.ac.kr/feeds/calendars/user_short.ics",
    "http://canvas.dankook.ac.kr/feeds/calendars/user_AbCdEfGhIjKlMnOpQrStUvWxYz0123.ics",
    "https://canvas.dankook.ac.kr.evil.example/feeds/calendars/user_AbCdEfGhIjKlMnOpQrStUvWxYz0123.ics",
])
def test_feed_url_rejected(raw):
    with pytest.raises(EclassError):
        normalize_feed_url(raw)


def test_delegated_fetch_only_for_allowlist_and_skips_robots():
    class Session:
        headers: dict = {}
        urls: list = []

        def get(self, url, timeout, **kw):
            self.urls.append(url)
            body = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR"
            return SimpleNamespace(status_code=200, encoding="utf-8", close=lambda: None,
                                   raw=SimpleNamespace(read=lambda n, decode_content: body[:n]))

    s = Session()
    http = HttpClient("DanbiBot/test", min_interval=0, retries=0, session=s)
    with pytest.raises(FetchError):
        http.get_delegated("https://canvas.dankook.ac.kr/courses/1")
    r = http.get_delegated(FEED)
    assert r._content.startswith(b"BEGIN:VCALENDAR") and s.urls == [FEED]  # robots.txt를 묻지 않는다
    with pytest.raises(FetchError, match="너무 큽니다"):
        http.get_delegated(FEED, max_bytes=5)


# ---- 서비스: 암호화 저장·캐시·오류 ----

def test_connect_encrypts_and_caches():
    http = FakeHttp()
    svc, store, uid = service(http)
    assert svc.status(uid)["connected"] is False
    got = svc.connect(uid, FEED)
    assert len(got.events) == 3 and http.calls == 1
    row = store.get_integration(uid, "eclass_ics")
    assert FEED not in row["secret"] and "user_AbCd" not in row["secret"]  # 주소 원문은 저장하지 않는다
    assert svc.events(uid).events == got.events and http.calls == 1      # 캐시
    # 서버를 다시 띄워도(캐시 없음) 저장된 암호문으로 다시 받는다
    svc2 = EclassService(store, http, "test-secret")
    assert len(svc2.events(uid).events) == 3 and http.calls == 2
    # 키가 바뀌면 읽지 못한다고 알린다
    with pytest.raises(EclassError, match="다시 등록"):
        EclassService(store, http, "other-secret").events(uid)
    svc.disconnect(uid)
    assert svc.status(uid)["connected"] is False and store.get_integration(uid, "eclass_ics") is None


def test_dead_feed_and_stale_fallback():
    http = FakeHttp()
    svc, store, uid = service(http)
    with pytest.raises(EclassError, match="캘린더 형식"):
        EclassService(store, FakeHttp(text="<html>login</html>"), "k").connect(uid, FEED)
    svc.connect(uid, FEED)
    svc.ttl = 0                      # 캐시 만료
    http.status = 404                # 사용자가 Canvas에서 피드 주소를 새로 발급함
    stale = svc.events(uid)
    assert stale.stale and len(stale.events) == 3
    assert "유효하지 않" in store.get_integration(uid, "eclass_ics")["last_error"]
    svc._cache.clear()
    with pytest.raises(EclassError, match="새로 등록"):
        svc.events(uid)


def test_disabled_without_secret_key():
    svc = EclassService(TraceStore(None), FakeHttp(), None)
    assert not svc.enabled and svc.status(1)["available"] is False
    with pytest.raises(EclassError, match="꺼져"):
        svc.connect(1, FEED)


# ---- 도구 ----

def run_tool(tool, user, **args):
    token = CURRENT_USER.set(user)
    try:
        return tool.func(**args)
    finally:
        CURRENT_USER.reset(token)


def test_my_schedule_tool():
    svc, _, uid = service()
    tool = make_my_schedule(svc)
    me = CurrentUser(uid, f"google:{uid}")
    assert "웹 채팅에 학교 Google 계정으로 로그인" in run_tool(tool, None)       # 카카오·CLI
    assert run_tool(tool, me).startswith(CONNECT_MARK)                          # 연결 전
    assert "꺼져" in run_tool(make_my_schedule(None), me)
    svc.connect(uid, FEED)
    out = run_tool(tool, me)
    assert "— 2건 (전체 3건 중" in out and "지난 특강" not in out              # 기본: 오늘부터 14일
    d1 = TODAY + timedelta(days=2)
    assert f"{d1.isoformat()}({'월화수목금토일'[d1.weekday()]}) 시각 미표기 [과제] 애착유형검사 결과 제출 · 사랑의심리학 1분반" in out
    assert "23:59 [과제] 중간 보고서" in out and "설명: 결과를 캡쳐해서 업로드, 하세요" in out
    assert "원문: https://canvas.dankook.ac.kr/calendar" in out and "제출 여부" in out
    assert "— 1건" in run_tool(tool, me, keyword="소프트 웨어")
    past = run_tool(tool, me, start=(TODAY - timedelta(days=7)).isoformat(), end=TODAY.isoformat())
    assert "지난 특강" in past
    empty = run_tool(tool, me, start="2001-01-01", end="2001-01-31")
    assert "해당하는 일정이 없습니다" in empty and "다음 일정:" in empty
    with pytest.raises(Exception, match="YYYY-MM-DD"):
        run_tool(tool, me, start="내일")
    # 출처는 eclass 캘린더 링크 하나, 추적 DB에는 첫 줄만
    refs = extract_sources("my_schedule", out)
    assert [(r.title, r.url) for r in refs] == [("내 eclass 캘린더", "https://canvas.dankook.ac.kr/calendar")]
    kept = stored_result("my_schedule", out)
    assert kept.startswith("[source: eclass]") and "애착유형" not in kept and "개인 자료라" in kept
    assert stored_result("search_site", out) == out


# ---- API ----

def test_api_connect_chat_and_disconnect(env):  # noqa: F811
    store = TraceStore(None)
    http = FakeHttp()
    svc = EclassService(store, http, "test-secret")
    replies = [Reply(calls=[("my_schedule", {})]), Reply(text="연결해 주세요"),
               Reply(calls=[("my_schedule", {})]), Reply(text="과제 2건이 있어요")]
    agent = Agent(FakeProvider(replies), ToolRegistry([make_my_schedule(svc)]))
    google = FakeGoogle()
    app = create_app(agent, recorder=TraceRecorder(store, agent), auth=AuthSettings(), auth_http=google.http,
                     auth_verifier=google.verify, eclass=svc)
    client = TestClient(app, base_url="https://testserver")

    assert client.get("/api/integrations/eclass").status_code == 401         # 로그인 필요
    login(client, google)
    assert client.get("/api/integrations/eclass").json()["connected"] is False

    evs = events(client.post("/api/chat", json={"message": "이번 주 과제 뭐 있어?"}))
    assert ("action", {"type": "connect_eclass"}) in evs

    bad = client.put("/api/integrations/eclass", json={"url": "https://example.com/x.ics"})
    assert bad.status_code == 400 and "피드 주소" in bad.json()["detail"]
    ok = client.put("/api/integrations/eclass", json={"url": FEED})
    assert ok.status_code == 200 and ok.json()["connected"] is True and ok.json()["upcoming"] == 2

    evs = events(client.post("/api/chat", json={"message": "이번 주 과제 뭐 있어?"}))
    assert not any(e == "action" for e, _ in evs)
    sources = next(d for e, d in evs if e == "sources")["items"]
    assert sources == [{"title": "내 eclass 캘린더", "url": "https://canvas.dankook.ac.kr/calendar"}]
    run_id = next(d for e, d in evs if e == "done")["run_id"]
    tool_row = store.run_detail(run_id)["tool_calls"][0]
    assert "애착유형" not in tool_row["result"]                               # /dev에 개인 일정 원문이 남지 않는다

    cross = client.put("/api/integrations/eclass", json={"url": FEED}, headers={"Origin": "https://evil.example"})
    assert cross.status_code == 403
    assert client.delete("/api/integrations/eclass").json() == {"ok": True}
    assert client.get("/api/integrations/eclass").json()["connected"] is False
