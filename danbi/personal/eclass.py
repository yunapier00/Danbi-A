"""eclass(Canvas) 캘린더 피드 연동.

사용자가 웹 사이드바에서 자기 캘린더 피드 주소를 등록하면, 그 사용자가 물을 때만 받아 온다 (사용자 위임 요청, 설계 §1-7).
- 주소는 USER_DELEGATED 허용 목록 형식만 받는다 (아무 주소나 받으면 서버가 엉뚱한 곳에 요청하게 된다).
- 주소는 비밀번호와 같아서 암호화해 저장한다 (Fernet, 키 = DANBI_SECRET_KEY). 키가 없으면 기능을 끈다.
- 받아 온 일정은 메모리에만 사용자별로 잠깐(cache_minutes) 둔다. 공용 크롤링 캐시에는 넣지 않는다.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import threading
import time
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from ..crawler.http import USER_DELEGATED, FetchError, HttpClient
from .ics import CalendarEvent, parse_ics

log = logging.getLogger(__name__)

KIND = "eclass_ics"
CALENDAR_URL = "https://canvas.dankook.ac.kr/calendar"


class EclassError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 메시지를 담는다."""


class NotConnected(EclassError):
    pass


def normalize_feed_url(raw: str) -> str:
    """붙여 넣은 피드 주소를 정리하고 형식을 확인한다. 맞지 않으면 EclassError."""
    url = (raw or "").strip().strip("<>\"'")
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not any(p.match(url) for p in USER_DELEGATED):
        raise EclassError("eclass 캘린더 피드 주소가 아니에요. "
                          "https://canvas.dankook.ac.kr/feeds/calendars/user_….ics 형식의 주소를 붙여 넣어 주세요.")
    return url


def make_cipher(secret: str) -> Fernet:
    """아무 길이의 비밀값에서 Fernet 키를 만든다 (DANBI_SECRET_KEY는 긴 임의 문자열이면 된다)."""
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest()))


@dataclass
class Fetched:
    events: list[CalendarEvent]
    fetched_at: float          # time.time()
    stale: bool = False        # 새로 받지 못해 예전 결과를 쓰는 중


class EclassService:
    def __init__(self, store, http: HttpClient | None, secret_key: str | None, cache_minutes: float = 30):
        self.store = store
        self.http = http
        self.cipher = make_cipher(secret_key) if secret_key else None
        self.ttl = cache_minutes * 60
        self._cache: dict[int, tuple[float, Fetched]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.cipher is not None and self.store is not None and self.http is not None

    # --- 연결 관리 (API) ----------------------------------------------------------------

    def status(self, user_id: int) -> dict:
        row = self.store.get_integration(user_id, KIND) if self.enabled else None
        return {"available": self.enabled, "connected": row is not None,
                "connected_at": row["created_at"] if row else None,
                "last_ok_at": row["last_ok_at"] if row else None,
                "last_error": row["last_error"] if row else None}

    def connect(self, user_id: int, raw_url: str) -> Fetched:
        """주소를 확인(한 번 받아 보기)한 뒤 암호화해 저장한다."""
        self._require()
        url = normalize_feed_url(raw_url)
        fetched = Fetched(self._download(url), time.time())
        self.store.save_integration(user_id, KIND, self.cipher.encrypt(url.encode()).decode())
        self.store.mark_integration(user_id, KIND, ok=True)
        with self._lock:
            self._cache[user_id] = (time.monotonic(), fetched)
        return fetched

    def disconnect(self, user_id: int) -> None:
        with self._lock:
            self._cache.pop(user_id, None)
        if self.store is not None:
            self.store.delete_integration(user_id, KIND)

    # --- 조회 (도구) ---------------------------------------------------------------------

    def events(self, user_id: int) -> Fetched:
        self._require()
        with self._lock:
            hit = self._cache.get(user_id)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        row = self.store.get_integration(user_id, KIND)
        if row is None:
            raise NotConnected("eclass가 연결되지 않았습니다.")
        try:
            url = self.cipher.decrypt(row["secret"].encode()).decode()
        except InvalidToken:  # 서버 키가 바뀌었다
            raise EclassError("저장된 eclass 연결을 읽을 수 없습니다. 사이드바의 'eclass 일정 연결'에서 다시 등록해 주세요.")
        try:
            fetched = Fetched(self._download(url), time.time())
        except EclassError as e:
            self.store.mark_integration(user_id, KIND, ok=False, error=str(e))
            if hit:  # 받아 오지 못하면 전에 받은 결과라도 알린다 (오래됐다고 표시)
                return Fetched(hit[1].events, hit[1].fetched_at, stale=True)
            raise
        self.store.mark_integration(user_id, KIND, ok=True)
        with self._lock:
            self._cache[user_id] = (time.monotonic(), fetched)
        return fetched

    # --- 내부 -----------------------------------------------------------------------------

    def _require(self) -> None:
        if not self.enabled:
            raise EclassError("이 서버에서는 eclass 연결 기능이 꺼져 있습니다.")

    def _download(self, url: str) -> list[CalendarEvent]:
        try:
            text = self.http.get_delegated(url).text
        except FetchError as e:
            if e.status in (401, 403, 404, 410):
                raise EclassError("eclass 피드 주소가 더 이상 유효하지 않아요. Canvas 캘린더에서 피드 주소를 다시 복사해 "
                                  "사이드바의 'eclass 일정 연결'에서 새로 등록해 주세요.") from e
            log.warning("eclass 피드 받기 실패: HTTP %s", e.status)  # 주소(비밀값)는 로그에 남기지 않는다
            raise EclassError("eclass에서 일정을 받아 오지 못했어요. 잠시 후 다시 시도해 주세요.") from e
        if "BEGIN:VCALENDAR" not in text[:2000]:
            raise EclassError("받은 내용이 캘린더 형식이 아니에요. 피드 주소를 다시 확인해 주세요.")
        return parse_ics(text)
