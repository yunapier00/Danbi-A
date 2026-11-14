"""외부 웹 검색 백엔드 (web_search 도구가 쓴다).

검색은 검색 API가 하고, 단비는 그 결과(제목·주소·스니펫·날짜)만 받는다. 결과 페이지를 직접 가져오지 않으므로
robots.txt를 따질 일이 없다. 백엔드는 SearchBackend 하나만 맞추면 바꿀 수 있다 (지금은 Tavily).

Gemini Google Search grounding은 쓰지 않는다: 약관이 결과 수정·다른 내용과 섞기·캐시·분석을 금지하고
'Search Suggestions'를 그대로 보여주도록 요구해서, 결과를 다른 자료와 합쳐 다시 쓰고 추적 DB에 남기는
단비 구조와 맞지 않는다 (2026-11-14 확인).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


class WebSearchError(Exception):
    """검색 API 실패. 메시지는 에이전트에게 그대로 보인다."""


@dataclass
class WebResult:
    title: str
    url: str
    snippet: str
    published: str = ""   # YYYY-MM-DD (검색 API가 추정한 게시·수정일, 없으면 빈 값)


class SearchBackend(Protocol):
    name: str

    def search(self, query: str, max_results: int) -> list[WebResult]: ...


class TavilyBackend:
    """Tavily 검색 API (https://docs.tavily.com). basic 검색 1회 = 1크레딧."""

    name = "tavily"
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str, *, timeout: float = 15, exclude_domains: list[str] | None = None,
                 session: requests.Session | None = None):
        self.api_key = api_key
        self.timeout = timeout
        self.exclude_domains = list(exclude_domains or [])
        self.session = session or requests.Session()

    def search(self, query: str, max_results: int) -> list[WebResult]:
        body = {
            "query": query,
            "search_depth": "basic",        # auto_parameters는 크레딧이 더 들어 쓰지 않는다
            "max_results": max_results,
            "chunks_per_source": 2,
            "topic": "general",
            "country": "south korea",       # 한국 자료를 앞으로 (거르지는 않음)
            "include_published_date": True,
            "include_answer": False,        # 답은 단비가 쓴다
        }
        if self.exclude_domains:
            body["exclude_domains"] = self.exclude_domains
        try:
            r = self.session.post(self.URL, json=body, timeout=self.timeout,
                                  headers={"Authorization": f"Bearer {self.api_key}"})
        except requests.RequestException as e:
            raise WebSearchError(f"웹 검색 서비스에 연결하지 못했습니다 ({type(e).__name__})") from e
        if r.status_code in (401, 432, 433):
            log.error("웹 검색 API 키·한도 오류: HTTP %s", r.status_code)
            raise WebSearchError("웹 검색 서비스 사용 한도를 넘었거나 설정에 문제가 있습니다")
        if r.status_code == 429:
            raise WebSearchError("웹 검색 요청이 많아 잠시 쓸 수 없습니다")
        if r.status_code >= 400:
            raise WebSearchError(f"웹 검색 서비스 오류 (HTTP {r.status_code})")
        out = []
        for item in r.json().get("results") or []:
            url = str(item.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            out.append(WebResult(title=str(item.get("title") or "").strip() or url,
                                 url=url,
                                 snippet=" ".join(str(item.get("content") or "").split()),
                                 published=_date(item.get("published_date"))))
        return out


def _date(value) -> str:
    """'Mon, 18 May 2026 05:00:00 GMT'(Tavily 실제 형식) 또는 ISO → 'YYYY-MM-DD'. 못 읽으면 빈 값."""
    from email.utils import parsedate_to_datetime

    s = str(value or "").strip()
    if not s:
        return ""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        return ""


class WebSearch:
    """백엔드 + 캐시 + 하루 상한. 같은 검색어는 캐시에서 돌려주고, 하루(한국 시간) 검색 수를 센다.

    횟수는 크롤링 캐시(SQLite, 배포 시 볼륨)에 두어 재시작해도 이어진다.
    """

    def __init__(self, backend: SearchBackend, cache, *, max_results: int = 5, daily_limit: int = 100,
                 cache_minutes: float = 60):
        self.backend = backend
        self.cache = cache
        self.max_results = max_results
        self.daily_limit = daily_limit
        self.cache_ttl = cache_minutes * 60
        self._lock = threading.Lock()

    @staticmethod
    def _norm(query: str) -> str:
        return " ".join(query.split()).lower()

    def _count_key(self) -> str:
        return f"websearch_count:{datetime.now(KST).date().isoformat()}"

    def used_today(self) -> int:
        return int(self.cache.get(self._count_key()) or 0)

    def search(self, query: str) -> tuple[list[WebResult], bool]:
        """(결과, 캐시에서 왔는지). 하루 상한을 넘으면 WebSearchError."""
        key = f"websearch:{self.backend.name}:{self.max_results}:{self._norm(query)}"
        if (hit := self.cache.get(key)) is not None:
            return [WebResult(**r) for r in hit], True
        with self._lock:
            used = self.used_today()
            if used >= self.daily_limit:
                raise WebSearchError("오늘 웹 검색 한도를 모두 썼습니다")
            self.cache.set(self._count_key(), used + 1, 2 * 24 * 3600)
        started = time.monotonic()
        results = self.backend.search(query, self.max_results)
        log.info("웹 검색 %d건 (%.1f초, 오늘 %d/%d회)", len(results), time.monotonic() - started,
                 used + 1, self.daily_limit)
        self.cache.set(key, [r.__dict__ for r in results], self.cache_ttl)
        return results, False


def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify(url: str, official_domains: list[str]) -> str:
    """'공식' (학교 도메인) 또는 '외부'. 외부는 영상·SNS를 따로 표시한다."""
    host = host_of(url)
    if any(host == d or host.endswith("." + d) for d in official_domains):
        return "공식"
    if host in ("youtube.com", "m.youtube.com", "youtu.be"):
        return "외부·영상"
    if host in ("instagram.com", "facebook.com", "x.com", "twitter.com", "threads.net", "threads.com"):
        return "외부·SNS"
    return "외부"
