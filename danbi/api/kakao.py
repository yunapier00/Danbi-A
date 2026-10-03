"""카카오톡 챗봇 스킬 엔드포인트 (POST /api/kakao/skill). 설정 가이드: docs/KAKAO_SETUP.md

- 인증: 카카오 스킬 요청에는 서명이 없으므로, 오픈빌더 스킬 설정의 헤더에 넣은 비밀값
  (X-Danbi-Kakao-Secret = KAKAO_SKILL_SECRET)을 확인한다. 비밀값이 설정되지 않으면 엔드포인트 자체를 열지 않는다.
- 5초 제한: 스킬은 5초 안에 응답해야 한다. 콜백이 켜져 있으면(userRequest.callbackUrl) 바로 useCallback으로 답하고,
  백그라운드에서 답을 만든 뒤 콜백 URL(5분간 1회 유효)로 보낸다. 콜백이 없으면 sync_timeout 안에 끝낼 때만 답한다.
- 사용자: 카카오 사용자 키는 그대로 저장하지 않고 해시(user_key)로만 쓴다. 대화 기록·분당/하루 제한이 이 키 기준이다.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request

from ..agent.loop import Agent, FinalEvent, ToolEndEvent
from ..config import KakaoSettings
from ..ops import TraceRecorder, new_run_id
from ..ops.sources import extract_sources
from .kakao_format import answer_response, text_response

log = logging.getLogger(__name__)

SECRET_HEADER = "x-danbi-kakao-secret"
RESET_WORDS = {"새 대화", "처음으로", "/reset", "다시 시작"}
WAITING_TEXT = "자료를 찾아보고 있어요. 잠시만 기다려 주세요!"
CALLBACK_DEADLINE = 270  # 콜백 URL 유효 시간(5분) 안에 보내야 한다


def user_key_of(kakao_user_id: str, salt: str) -> str:
    return "kakao:" + hashlib.sha256(f"{salt}:{kakao_user_id}".encode()).hexdigest()[:24]


def allowed_callback(url: str, hosts: list[str]) -> bool:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and any(host == h or host.endswith("." + h) for h in hosts)


def mount_kakao(app: FastAPI, agent: Agent, recorder: TraceRecorder | None, settings: KakaoSettings, *,
                guard, sessions, http: httpx.AsyncClient | None = None) -> None:
    secret = settings.secret
    if not secret:
        return  # 설정 전에는 엔드포인트가 없다 (404)
    salt = settings.user_salt or secret
    tasks: set[asyncio.Task] = set()  # 백그라운드 작업이 가비지 컬렉션되지 않게 붙잡아 둔다
    app.state.kakao_tasks = tasks
    client_holder: dict[str, httpx.AsyncClient] = {}

    def http_client() -> httpx.AsyncClient:
        if http is not None:
            return http
        if "c" not in client_holder:
            client_holder["c"] = httpx.AsyncClient(timeout=10)
        return client_holder["c"]

    async def run_agent(question: str, ukey: str, session) -> tuple[str, list[dict]]:
        """에이전트 실행 → (답변 마크다운, 출처 링크). 세션 기록을 저장하고 '답변 중' 표시를 푼다."""
        events = agent.run(question, history=session.history)
        if recorder is not None:
            events = recorder.record(events, run_id=new_run_id(), question=question, channel="kakao",
                                     conversation_id=ukey, user_key=ukey)
        try:
            async with guard.slots:
                links: dict[str, dict] = {}
                final: FinalEvent | None = None
                async for ev in events:
                    if isinstance(ev, ToolEndEvent) and not ev.result.is_error:
                        for ref in extract_sources(ev.result.name, ev.result.content):
                            if ref.url:
                                links.setdefault(ref.url, {"title": ref.title, "url": ref.url})
                    elif isinstance(ev, FinalEvent):
                        final = ev
                if final is None:
                    return "답변을 만들지 못했어요. 잠시 후 다시 물어봐 주세요.", []
                sessions.save(session, final.messages)
                return final.text, list(links.values())
        finally:
            session.busy_since = None
            await events.aclose()  # 시간 초과로 취소돼도 기록기가 'aborted'로 마무리하게 한다

    async def answer_then_callback(callback_url: str, question: str, ukey: str, session, remaining: int | None):
        try:
            text, links = await asyncio.wait_for(run_agent(question, ukey, session), timeout=CALLBACK_DEADLINE)
            payload = answer_response(text, links, remaining)
        except asyncio.TimeoutError:
            payload = text_response("답변을 만드는 데 너무 오래 걸렸어요. 질문을 조금 더 구체적으로 다시 물어봐 주세요.")
        except Exception:
            log.exception("카카오 답변 생성 실패")
            payload = text_response("답변을 만들지 못했어요. 잠시 후 다시 물어봐 주세요.")
        try:
            res = await http_client().post(callback_url, json=payload)
            if res.status_code >= 400:
                log.warning("카카오 콜백 응답 %s: %s", res.status_code, res.text[:200])
        except httpx.HTTPError as e:
            log.warning("카카오 콜백 전송 실패: %s", e)

    @app.post("/api/kakao/skill", include_in_schema=False)
    async def skill(request: Request):
        if not hmac.compare_digest(request.headers.get(SECRET_HEADER, "").encode(), secret.encode()):
            raise HTTPException(401, "unauthorized")
        try:
            body = await request.json()
        except ValueError as e:
            raise HTTPException(400, "invalid json") from e
        ur = body.get("userRequest") or {}
        question = str(ur.get("utterance") or "").strip()[:1000]
        kakao_id = str((ur.get("user") or {}).get("id") or "")
        if not kakao_id:
            return text_response("사용자 정보를 확인할 수 없어요.")
        ukey = user_key_of(kakao_id, salt)
        if question in RESET_WORDS:
            sessions.reset(ukey)
            return text_response("새 대화를 시작할게요. 무엇이 궁금하세요?")
        if not question:
            return text_response("궁금한 점을 입력해 주세요.")

        blocked, remaining = guard.check(ukey, user_key=ukey)
        if blocked:
            return text_response(blocked)
        if guard.slots.locked():
            return text_response(guard.BUSY_MSG)
        session = sessions.get_or_create(ukey)
        if session.busy:
            return text_response("이전 질문에 아직 답하는 중이에요. 잠시만 기다려 주세요.")
        session.busy_since = time.monotonic()

        callback_url = ur.get("callbackUrl")
        if callback_url and not allowed_callback(callback_url, settings.callback_hosts):
            log.warning("허용되지 않은 카카오 콜백 주소: %s", urlparse(callback_url).hostname)
            callback_url = None
        if callback_url:
            task = asyncio.create_task(answer_then_callback(callback_url, question, ukey, session, remaining))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            return {"version": "2.0", "useCallback": True, "data": {"text": WAITING_TEXT}}

        # 콜백을 못 쓰면 5초 제한 안에 끝날 때만 답한다 (대부분의 질문은 넘으므로 콜백 활성화가 필요하다)
        try:
            text, links = await asyncio.wait_for(run_agent(question, ukey, session), timeout=settings.sync_timeout)
        except asyncio.TimeoutError:
            return text_response("답변을 만드는 데 시간이 걸리고 있어요. 잠시 후 다시 물어봐 주세요.")
        return answer_response(text, links, remaining)
