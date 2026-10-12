"""학교 서버를 존중하는 HTTP 클라이언트.

- 호스트당 동시 요청 1개, 요청 간격 min_interval 이상 (에이전트가 도구를 병렬로 불러도 같은 호스트는 순서대로)
- 5xx·연결 오류만 재시도, 4xx는 즉시 실패
- robots.txt 확인, User-Agent에 단비 식별자
- 예외: 사용자 위임 요청 (설계 §1-7). 사용자가 직접 등록한 자기 자료를 그 사용자가 물을 때만 받는다.
  USER_DELEGATED 허용 목록에 맞는 주소만 robots.txt 확인을 건너뛰고, 속도 제한은 똑같이 지킨다.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger(__name__)

# 사용자 위임 요청으로 받을 수 있는 주소. 크롤링·탐색에는 쓰지 않는다
USER_DELEGATED = [
    re.compile(r"^https://canvas\.dankook\.ac\.kr/feeds/calendars/user_[A-Za-z0-9]{20,100}\.ics$"),  # eclass 캘린더 피드
]


class FetchError(Exception):
    def __init__(self, message: str, url: str, status: int | None = None):
        super().__init__(message)
        self.url = url
        self.status = status


class HttpClient:
    def __init__(self, user_agent: str, *, min_interval: float = 1.0, timeout: float = 20, retries: int = 2,
                 session: requests.Session | None = None):
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._guard = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    def _host_lock(self, host: str) -> threading.Lock:
        with self._guard:
            return self._host_locks.setdefault(host, threading.Lock())

    def _wait_turn(self, host: str) -> None:
        """호스트 락을 잡은 상태에서 호출한다."""
        wait = self._last.get(host, 0) + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _allowed(self, url: str) -> bool:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self._robots:
            rp = RobotFileParser()
            try:
                r = self._request(f"{origin}/robots.txt", check_robots=False, retries=0)
                rp.parse(r.text.splitlines())
            except FetchError as e:
                # robots.txt가 없거나(404) 읽을 수 없으면 제한 없음으로 본다
                log.info("robots.txt 없음/읽기 실패 (%s): %s", origin, e)
                rp = None
            self._robots[origin] = rp
        rp = self._robots[origin]
        return rp is None or rp.can_fetch(self.user_agent, url)

    def get(self, url: str) -> requests.Response:
        return self._request(url, check_robots=True, retries=self.retries)

    def get_delegated(self, url: str, *, max_bytes: int = 1_000_000) -> requests.Response:
        """사용자 위임 요청. USER_DELEGATED에 맞는 주소만 받는다 (robots.txt 대신 허용 목록)."""
        if not any(p.match(url) for p in USER_DELEGATED):
            raise FetchError("허용되지 않은 사용자 자료 주소입니다", url)
        return self._request(url, check_robots=False, retries=self.retries, max_bytes=max_bytes)

    def _request(self, url: str, *, check_robots: bool, retries: int, max_bytes: int | None = None) -> requests.Response:
        if check_robots and not self._allowed(url):
            raise FetchError("robots.txt가 이 주소의 수집을 허용하지 않습니다", url)
        host = urlparse(url).netloc
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            with self._host_lock(host):
                self._wait_turn(host)
                try:
                    extra = {"stream": True} if max_bytes is not None else {}
                    r = self.session.get(url, timeout=self.timeout, **extra)
                    if max_bytes is not None and r.status_code < 400:
                        body = r.raw.read(max_bytes + 1, decode_content=True)
                        r.close()
                        if len(body) > max_bytes:
                            raise FetchError(f"응답이 너무 큽니다 ({max_bytes:,}바이트 초과)", url)
                        r._content = body  # 크기를 제한해 읽은 본문으로 .text·.content를 쓴다
                except requests.RequestException as e:
                    last_error = e
                    r = None
                finally:
                    self._last[host] = time.monotonic()
            if r is not None:
                if r.status_code < 400:
                    r.encoding = r.encoding or "utf-8"
                    return r
                if r.status_code < 500:
                    raise FetchError(f"HTTP {r.status_code}", url, r.status_code)
                last_error = FetchError(f"HTTP {r.status_code}", url, r.status_code)
            if max_bytes is not None:  # 사용자 위임 주소는 비밀값이라 로그에 호스트만 남긴다
                log.warning("요청 실패 (%d/%d) %s (사용자 자료): %s", attempt + 1, retries + 1, host, type(last_error).__name__)
            else:
                log.warning("요청 실패 (%d/%d) %s: %s", attempt + 1, retries + 1, url, last_error)
            if attempt < retries:
                time.sleep(self.min_interval * (attempt + 1))
        status = last_error.status if isinstance(last_error, FetchError) else None
        raise FetchError(f"학교 사이트 응답 없음: {last_error}", url, status)
