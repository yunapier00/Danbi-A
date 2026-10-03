"""HTTP 클라이언트(속도 제한·재시도·robots)와 캐시."""

import threading
import time

import pytest
import requests

from danbi.crawler.cache import Cache
from danbi.crawler.http import FetchError, HttpClient


class FakeResponse:
    def __init__(self, status, text=""):
        self.status_code, self.text, self.encoding = status, text, "utf-8"


class FakeSession:
    def __init__(self, routes):
        self.routes = routes  # url → [status, ...] (차례대로 소비) 또는 (status, text)
        self.headers = {}
        self.log: list[tuple[str, float]] = []
        self._lock = threading.Lock()

    def get(self, url, timeout):
        with self._lock:
            self.log.append((url, time.monotonic()))
        if url.endswith("/robots.txt"):
            return FakeResponse(200, self.routes.get("robots", ""))
        statuses = self.routes[url]
        status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        if status == "err":
            raise requests.ConnectionError("down")
        return FakeResponse(status, "ok")


def client(routes, interval=0.1):
    return HttpClient("DanbiBot/test", min_interval=interval, retries=2, session=FakeSession(routes))


def test_same_host_requests_are_serialized_and_spaced():
    c = client({"https://a.kr/1": [200], "https://a.kr/2": [200], "https://a.kr/3": [200]})
    threads = [threading.Thread(target=c.get, args=(f"https://a.kr/{i}",)) for i in (1, 2, 3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    times = [t for url, t in c.session.log]  # robots.txt 포함 4건
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert len(times) == 4 and min(gaps) >= 0.09


def test_retry_5xx_and_connection_errors_but_not_4xx():
    c = client({"https://a.kr/x": [503, "err", 200], "https://a.kr/404": [404]}, interval=0.01)
    assert c.get("https://a.kr/x").status_code == 200
    with pytest.raises(FetchError) as e:
        c.get("https://a.kr/404")
    assert e.value.status == 404
    assert sum(1 for url, _ in c.session.log if url.endswith("/404")) == 1


def test_gives_up_after_retries():
    c = client({"https://a.kr/x": [500]}, interval=0.01)
    with pytest.raises(FetchError, match="응답 없음"):
        c.get("https://a.kr/x")
    assert sum(1 for url, _ in c.session.log if url.endswith("/x")) == 3


def test_robots_disallow():
    robots = "User-agent: *\nDisallow: /private/\n\nUser-agent: Googlebot\nDisallow: /documents/\n"
    c = client({"robots": robots, "https://a.kr/documents/f": [200], "https://a.kr/private/p": [200]}, interval=0.01)
    assert c.get("https://a.kr/documents/f").status_code == 200  # Googlebot 전용 규칙은 적용되지 않음
    with pytest.raises(FetchError, match="robots.txt"):
        c.get("https://a.kr/private/p")


def test_cache_ttl(tmp_path):
    cache = Cache(tmp_path / "c.sqlite")
    cache.set("k", {"a": [1, "한글"]}, ttl=60)
    cache.set("old", 1, ttl=-1)
    assert cache.get("k") == {"a": [1, "한글"]}
    assert cache.get("old") is None and cache.get("none") is None
    assert cache.purge_expired() == 1
