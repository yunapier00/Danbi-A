"""학교 서버를 존중하는 HTTP 클라이언트.

- 호스트당 동시 요청 1개, 요청 간격 min_interval 이상 (에이전트가 도구를 병렬로 불러도 같은 호스트는 순서대로)
- 5xx·연결 오류만 재시도, 4xx는 즉시 실패
- robots.txt 확인, User-Agent에 단비 식별자
"""

from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger(__name__)


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

    def _request(self, url: str, *, check_robots: bool, retries: int) -> requests.Response:
        if check_robots and not self._allowed(url):
            raise FetchError("robots.txt가 이 주소의 수집을 허용하지 않습니다", url)
        host = urlparse(url).netloc
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            with self._host_lock(host):
                self._wait_turn(host)
                try:
                    r = self.session.get(url, timeout=self.timeout)
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
            log.warning("요청 실패 (%d/%d) %s: %s", attempt + 1, retries + 1, url, last_error)
            if attempt < retries:
                time.sleep(self.min_interval * (attempt + 1))
        status = last_error.status if isinstance(last_error, FetchError) else None
        raise FetchError(f"학교 사이트 응답 없음: {last_error}", url, status)
