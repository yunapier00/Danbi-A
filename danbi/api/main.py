"""API 서버 (FastAPI + SSE).

  .venv/Scripts/python -m danbi.api            # http://127.0.0.1:8000  (웹 채팅 UI 포함)

POST /api/chat  {"message": "...", "session_id": "...(선택)"}  → text/event-stream
  event: session  {"session_id"}                   첫 이벤트. 다음 요청에 같은 session_id를 보내면 대화가 이어진다
  event: status   {"text", "tools"}                도구 실행 중 (병렬 호출은 한 번에)
  event: token    {"text"}                         답변 텍스트 조각
  event: sources  {"items": [{"title", "url"}]}    도구 결과에서 모은 원문 링크
  event: done     {"run_id", "stop_reason", "tool_calls", "elapsed", "usage"}
  event: error    {"message"}
POST /api/reset {"session_id"}                     대화 기록 삭제
POST /api/feedback {"run_id", "rating": 1|-1, "comment"}   답변 평가 (추적 DB에 저장)
GET  /dev                                          개발자 전용 LLMOps 페이지 (admin.py)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agent.loop import FALLBACK_ANSWER, LIMIT_ANSWER, Agent, FinalEvent, TokenEvent, ToolEndEvent, ToolStartEvent
from ..config import KakaoSettings, LimitSettings
from ..llm.base import Message
from ..ops import TraceRecorder, new_run_id
from ..ops.sources import extract_sources
from .admin import mount_admin
from .kakao import mount_kakao

log = logging.getLogger(__name__)

WEB = Path(__file__).parent / "web"  # React 빌드 결과 (frontend/에서 npm run build)
NOT_BUILT = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>단비</title>
<body style="font-family:system-ui,sans-serif;max-width:640px;margin:10vh auto;padding:0 16px">
<h1>단비</h1><p>웹 화면이 아직 빌드되지 않았습니다. 프로젝트 폴더에서 다음을 실행하세요.</p>
<pre>cd frontend
npm install
npm run build</pre><p>API는 그대로 동작합니다 (<code>/api/docs</code>).</p></body></html>"""
MAX_MESSAGE_CHARS = 1000
BUSY_TIMEOUT = 180  # 이보다 오래 '답변 중'이면 끊긴 요청으로 본다


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    session_id: str | None = Field(default=None, max_length=64)


class ResetRequest(BaseModel):
    session_id: str = Field(max_length=64)


class FeedbackRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=64)
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=1000)


@dataclass
class Session:
    history: list[Message] = field(default_factory=list)
    updated: float = field(default_factory=time.monotonic)
    busy_since: float | None = None

    @property
    def busy(self) -> bool:
        return self.busy_since is not None and time.monotonic() - self.busy_since < BUSY_TIMEOUT


class SessionStore:
    """메모리 세션 저장소. 오래된 세션은 TTL·최대 개수로 정리한다. (서버 재시작 시 사라짐)"""

    def __init__(self, ttl: float = 60 * 60, max_sessions: int = 1000, max_turns: int = 10):
        self.ttl, self.max_sessions, self.max_turns = ttl, max_sessions, max_turns
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def get(self, session_id: str | None) -> tuple[str, Session]:
        self._expire()
        if session_id and session_id in self._sessions:
            self._sessions.move_to_end(session_id)
            return session_id, self._sessions[session_id]
        sid = uuid.uuid4().hex
        self._sessions[sid] = Session()
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)
        return sid, self._sessions[sid]

    def save(self, session: Session, history: list[Message]) -> None:
        # 최근 max_turns개 질문만 남긴다 (질문 = role user 메시지). 도구 결과가 쌓여 요청이 커지는 것을 막는다
        starts = [i for i, m in enumerate(history) if m.role == "user"]
        if len(starts) > self.max_turns:
            history = history[starts[-self.max_turns]:]
        session.history = history
        session.updated = time.monotonic()

    def get_or_create(self, key: str) -> Session:
        """정해진 키(예: 카카오 사용자)로 세션을 찾거나 만든다."""
        self._expire()
        if key not in self._sessions:
            self._sessions[key] = Session()
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
        self._sessions.move_to_end(key)
        return self._sessions[key]

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _expire(self) -> None:
        now = time.monotonic()
        for sid in [k for k, s in self._sessions.items() if now - s.updated > self.ttl and not s.busy]:
            del self._sessions[sid]


class RateLimiter:
    """키(IP)별 슬라이딩 윈도 요청 제한. 오래된 키는 주기적으로 정리한다."""

    def __init__(self, max_requests: int = 10, window: float = 60):
        self.max_requests, self.window = max_requests, window
        self._hits: dict[str, deque[float]] = {}
        self._calls = 0

    def _clean(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window:
            hits.popleft()
        return hits

    def check(self, key: str) -> bool:
        return len(self._clean(key, time.monotonic())) < self.max_requests

    def hit(self, key: str) -> None:
        now = time.monotonic()
        self._clean(key, now).append(now)
        self._calls += 1
        if self._calls % 1000 == 0:  # 메모리가 IP 수만큼 계속 늘지 않게
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                del self._hits[k]

    def allow(self, key: str) -> bool:
        if not self.check(key):
            return False
        self.hit(key)
        return True


class MultiLimiter:
    """여러 창(분당·하루)을 함께 건다. 하나라도 막히면 어느 창의 몫도 쓰지 않는다."""

    def __init__(self, *limiters: RateLimiter):
        self.limiters = limiters

    def allow(self, key: str) -> bool:
        if not all(lim.check(key) for lim in self.limiters):
            return False
        for lim in self.limiters:
            lim.hit(key)
        return True


KST = timezone(timedelta(hours=9))


def kst_midnight(now: float | None = None) -> float:
    d = datetime.fromtimestamp(now or time.time(), KST)
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class Guard:
    """웹·카카오가 함께 쓰는 남용·비용 방어: 분당 제한, 1인 하루 제한, 서비스 전체 하루 상한, 동시 처리 슬롯."""

    DAILY_USER_MSG = "오늘은 질문을 {n}번까지 할 수 있어요. 내일 다시 이용해 주세요."
    DAILY_TOTAL_MSG = "오늘 준비된 사용량을 모두 썼어요. 내일 다시 이용해 주세요."
    MINUTE_MSG = "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
    BUSY_MSG = "지금 질문이 많아요. 잠시 후 다시 시도해 주세요."

    def __init__(self, limits: LimitSettings, recorder: TraceRecorder | None, minute_limiter=None):
        self.limits = limits
        self.recorder = recorder
        self.minute = minute_limiter or RateLimiter(limits.per_ip_per_minute, 60)
        self.slots = asyncio.Semaphore(max(1, limits.max_concurrent))

    def check(self, key: str, *, client_ip: str | None = None, user_key: str | None = None) -> tuple[str | None, int | None]:
        """(막는 이유, 이번 질문 뒤 남는 횟수). 막지 않으면 이유는 None. 추적 DB가 없으면 하루 제한은 건너뛴다."""
        if not self.minute.allow(key):
            return self.MINUTE_MSG, None
        if self.recorder is None:
            return None, None
        store, since = self.recorder.store, kst_midnight()
        used = store.usage_since(since)
        if used["runs"] >= self.limits.daily_questions or used["tokens"] >= self.limits.daily_tokens:
            log.warning("하루 사용량 상한 도달: %s", used)
            return self.DAILY_TOTAL_MSG, None
        mine = store.count_user_since(since, client_ip=client_ip, user_key=user_key)
        if mine >= self.limits.per_user_per_day:
            return self.DAILY_USER_MSG.format(n=self.limits.per_user_per_day), 0
        return None, self.limits.per_user_per_day - mine - 1


SECURITY_HEADERS = {
    # SPA는 자기 출처의 스크립트·스타일·글꼴만 쓴다. 답변 HTML은 DOMPurify로 정제하고, 스크립트는 CSP로 한 번 더 막는다.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
        "object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def client_ip(request: Request, trust_proxy: bool = False, hops: int = 1) -> str:
    """요청 IP. 프록시 헤더는 trust_proxy일 때만 믿는다 (아니면 누구나 위조할 수 있다).

    X-Forwarded-For는 왼쪽이 사용자가 보낸 값(위조 가능), 오른쪽이 각 프록시가 덧붙인 값이다.
    앞단 프록시가 hops개면 오른쪽에서 hops 번째가 실제 클라이언트다.
    """
    if trust_proxy:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if parts:
            return parts[-min(max(1, hops), len(parts))][:64]
    return request.client.host if request.client else "unknown"


def create_app(agent: Agent, *, sessions: SessionStore | None = None,
               limiter: RateLimiter | MultiLimiter | None = None, recorder: TraceRecorder | None = None,
               admin_token: str | None = None, store_client_ip: bool = True, trust_proxy: bool = False,
               proxy_hops: int = 1, limits: LimitSettings | None = None, enable_docs: bool = False,
               kakao: KakaoSettings | None = None, kakao_http=None) -> FastAPI:
    """recorder를 주면 모든 대화를 추적 DB에 기록하고 개발자 페이지(/dev)를 연다."""
    app = FastAPI(title="단비 API", docs_url="/api/docs" if enable_docs else None,
                  openapi_url="/api/openapi.json" if enable_docs else None, redoc_url=None)
    limits = limits or LimitSettings()
    sessions = sessions or SessionStore()
    guard = Guard(limits, recorder, limiter)
    app.state.guard, app.state.sessions = guard, sessions
    slots = guard.slots
    ip_of = lambda request: client_ip(request, trust_proxy, proxy_hops)  # noqa: E731
    if recorder is not None:
        mount_admin(app, recorder.store, admin_token, client_of=ip_of,
                    fail_limiter=RateLimiter(limits.admin_auth_failures, 600))
    if kakao is not None:  # KAKAO_SKILL_SECRET이 있을 때만 /api/kakao/skill이 열린다
        mount_kakao(app, agent, recorder, kakao, guard=guard, sessions=sessions, http=kakao_http)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api/docs"):  # Swagger UI는 CDN 스크립트를 쓴다 (켜 둔 경우만)
            for k, v in SECURITY_HEADERS.items():
                response.headers.setdefault(k, v)
        if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    # 웹 화면 (React SPA): "/"와 "/dev"는 같은 index.html, 나머지 정적 파일은 /assets
    if (WEB / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    def spa(no_store: bool = False):
        if not (WEB / "index.html").exists():
            return HTMLResponse(NOT_BUILT, status_code=503)
        headers = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"} if no_store else {"Cache-Control": "no-cache"}
        return FileResponse(WEB / "index.html", headers=headers)

    @app.get("/", include_in_schema=False)
    async def index():
        return spa()

    @app.get("/dev", include_in_schema=False)
    async def dev_page():
        return spa(no_store=True)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.post("/api/reset")
    async def reset(req: ResetRequest):
        sessions.reset(req.session_id)
        return {"ok": True}

    @app.post("/api/feedback")
    async def feedback(req: FeedbackRequest):
        if recorder is None or req.rating == 0:
            raise HTTPException(400, "피드백을 저장할 수 없습니다.")
        if not recorder.store.add_feedback(req.run_id, req.rating, req.comment):
            raise HTTPException(404, "답변을 찾을 수 없습니다.")
        return {"ok": True}

    @app.post("/api/chat")
    async def chat(req: ChatRequest, request: Request):
        client = ip_of(request)
        # 1인 하루 제한은 저장된 IP로 센다. IP 저장을 껐으면 IP 해시를 사용자 키로 대신 저장한다.
        ip, ukey = (client, None) if store_client_ip else (None, "ip:" + hashlib.sha256(client.encode()).hexdigest()[:24])
        blocked, remaining = guard.check(client, client_ip=ip, user_key=ukey)
        if blocked:
            raise HTTPException(429, blocked)
        sid, session = sessions.get(req.session_id)
        if session.busy:
            raise HTTPException(409, "이전 질문에 아직 답하는 중입니다.")
        session.busy_since = time.monotonic()  # 응답 생성 전에 표시해야 동시 요청을 막을 수 있다
        return StreamingResponse(_stream(sid, session, req.message.strip(), ip, ukey, remaining),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def _stream(sid: str, session: Session, message: str, ip: str | None, ukey: str | None,
                      remaining: int | None = None) -> AsyncIterator[str]:
        # 동시 처리 상한: 슬롯이 없으면 기다리지 않고 바로 알린다 (응답이 시작된 뒤에 잡아야 슬롯이 새지 않는다)
        if slots.locked():
            session.busy_since = None
            yield _sse("error", {"message": "지금 질문이 많아요. 잠시 후 다시 시도해 주세요."})
            return
        async with slots:
            async for chunk in _answer(sid, session, message, ip, ukey, remaining):
                yield chunk

    async def _answer(sid: str, session: Session, message: str, ip: str | None, ukey: str | None,
                      remaining: int | None) -> AsyncIterator[str]:
        run_id = new_run_id()
        links: dict[str, dict] = {}
        final: FinalEvent | None = None
        events = agent.run(message, history=session.history)
        if recorder is not None:
            events = recorder.record(events, run_id=run_id, question=message, channel="web", conversation_id=sid,
                                     client_ip=ip, user_key=ukey)
        try:
            yield _sse("session", {"session_id": sid})
            async for ev in events:
                if isinstance(ev, TokenEvent):
                    yield _sse("token", {"text": ev.text})
                elif isinstance(ev, ToolStartEvent):
                    texts = list(dict.fromkeys(agent.tools.describe(c) for c in ev.calls))
                    yield _sse("status", {"text": " · ".join(texts), "tools": [c.name for c in ev.calls]})
                elif isinstance(ev, ToolEndEvent) and not ev.result.is_error:
                    for ref in extract_sources(ev.result.name, ev.result.content):
                        if ref.url:
                            links.setdefault(ref.url, {"title": ref.title, "url": ref.url})
                elif isinstance(ev, FinalEvent):
                    final = ev
            if final is None:
                yield _sse("error", {"message": "답변을 만들지 못했습니다."})
                return
            if final.text in (FALLBACK_ANSWER, LIMIT_ANSWER) or not final.text:  # 스트리밍되지 않은 대체 답변
                yield _sse("token", {"text": final.text or "답변을 만들지 못했습니다."})
            sessions.save(session, final.messages)
            if links:
                yield _sse("sources", {"items": list(links.values())})
            yield _sse("done", {"run_id": run_id if recorder is not None else None, "stop_reason": final.stop_reason,
                                "tool_calls": final.tool_calls_used, "elapsed": round(final.elapsed, 2),
                                "usage": asdict(final.usage), "remaining": remaining})
        except Exception as e:  # 스트림 도중 오류는 HTTP 상태로 알릴 수 없으므로 이벤트로 보낸다
            log.exception("채팅 처리 실패")
            yield _sse("error", {"message": f"오류가 발생했습니다: {type(e).__name__}"})
        finally:
            session.busy_since = None
            await events.aclose()  # 클라이언트가 끊었을 때도 기록기가 'aborted'로 마무리하게 한다

    return app


def build_default_app() -> FastAPI:
    from ..bootstrap import build_agent, build_recorder
    from ..config import load_settings

    settings = load_settings()
    agent = build_agent(settings)
    return create_app(agent, recorder=build_recorder(settings, agent), admin_token=settings.ops.admin_token,
                      store_client_ip=settings.ops.store_client_ip, trust_proxy=settings.ops.trust_proxy_headers,
                      proxy_hops=settings.ops.proxy_hops, limits=settings.limits, enable_docs=settings.enable_docs,
                      kakao=settings.kakao)
