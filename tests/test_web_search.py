"""외부 웹 검색 (web_search): Tavily 요청·응답 변환, 캐시·하루 상한, 공식/외부 표시, 출처 추출 (네트워크 없이)."""

from __future__ import annotations

import pytest

from danbi.agent.loop import Agent
from danbi.agent.tools import ToolRegistry
from danbi.agent.tools.registry import ToolError
from danbi.agent.tools.web import make_web_search
from danbi.config import Settings
from danbi.crawler.cache import Cache
from danbi.ops.sources import extract_sources
from danbi.websearch import TavilyBackend, WebResult, WebSearch, WebSearchError, classify

from .fakes import FakeProvider, Reply

OFFICIAL = ["dankook.ac.kr"]


class FakeResponse:
    def __init__(self, status: int, data: dict | None = None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[dict] = []

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.response


class FakeBackend:
    name = "fake"

    def __init__(self, results: list[WebResult]):
        self.results = results
        self.queries: list[str] = []

    def search(self, query, max_results):
        self.queries.append(query)
        return self.results[:max_results]


RESULTS = [
    WebResult("[소프트웨어학과] 2026 캡스톤 페스티벌 안내", "https://cms.dankook.ac.kr/web/sw/-1?id=1",
              "2026 캡스톤 페스티벌 및 졸업작품전시회를 아래와 같이 진행합니다.", "2026-11-05"),
    WebResult("캡스톤 페스티벌 현장 스케치", "https://www.youtube.com/watch?v=abc", "단국대학교 SW중심대학 영상"),
    WebResult("단국대 캡스톤 후기", "https://blog.example.com/post/1", "작년 캡스톤 페스티벌 후기입니다. " * 30),
]


def test_tavily_request_and_parse():
    session = FakeSession(FakeResponse(200, {"results": [
        {"title": "제목", "url": "https://a.dankook.ac.kr/x", "content": "줄\n바꿈  내용", "published_date": "2026-11-05T00:00:00"},
        {"title": "", "url": "javascript:alert(1)", "content": "버림"},
        {"title": "", "url": "https://b.com/", "content": "", "published_date": "Mon, 18 May 2026 05:00:00 GMT"},
        {"title": "c", "url": "https://c.com/", "content": "", "published_date": "어제쯤"},
    ]}))
    backend = TavilyBackend("tvly-test", exclude_domains=["x.com"], session=session)
    out = backend.search("단국대 캡스톤", 5)
    call = session.calls[0]
    assert call["headers"]["Authorization"] == "Bearer tvly-test"
    assert call["json"]["search_depth"] == "basic" and call["json"]["max_results"] == 5
    assert call["json"]["include_answer"] is False and call["json"]["exclude_domains"] == ["x.com"]
    assert "auto_parameters" not in call["json"]  # 크레딧이 더 든다
    assert [r.url for r in out] == ["https://a.dankook.ac.kr/x", "https://b.com/", "https://c.com/"]
    assert out[0].snippet == "줄 바꿈 내용" and out[0].published == "2026-11-05"
    assert out[1].title == "https://b.com/" and out[1].published == "2026-05-18"  # Tavily 실제 날짜 형식
    assert out[2].published == ""


@pytest.mark.parametrize("status,word", [(401, "한도"), (432, "한도"), (429, "잠시"), (500, "HTTP 500")])
def test_tavily_errors(status, word):
    backend = TavilyBackend("k", session=FakeSession(FakeResponse(status)))
    with pytest.raises(WebSearchError, match=word):
        backend.search("q", 3)


def test_cache_and_daily_limit():
    backend = FakeBackend(RESULTS)
    web = WebSearch(backend, Cache(None), max_results=2, daily_limit=2)
    first, cached = web.search("단국대  캡스톤")
    assert len(first) == 2 and not cached
    again, cached = web.search("단국대 캡스톤")   # 공백·대소문자 정규화 후 같은 검색어
    assert cached and again == first and len(backend.queries) == 1
    web.search("다른 검색어")
    assert web.used_today() == 2
    with pytest.raises(WebSearchError, match="한도"):
        web.search("세 번째")
    assert web.search("단국대 캡스톤")[1]  # 캐시에 있는 검색은 한도와 무관


def test_classify():
    assert classify("https://cms.dankook.ac.kr/web/sw", OFFICIAL) == "공식"
    assert classify("https://www.dankook.ac.kr/", OFFICIAL) == "공식"
    assert classify("https://dankook.ac.kr.evil.com/", OFFICIAL) == "외부"
    assert classify("https://notdankook.ac.kr/", OFFICIAL) == "외부"
    assert classify("https://youtu.be/x", OFFICIAL) == "외부·영상"
    assert classify("https://www.instagram.com/p/x", OFFICIAL) == "외부·SNS"


def run(tool, **args):
    return tool.func(**args)


def test_tool_output_and_sources():
    tool = make_web_search(WebSearch(FakeBackend(RESULTS), Cache(None)), OFFICIAL)
    out = run(tool, query="단국대 캡스톤 페스티벌")
    assert out.startswith("[source: web_search] 웹 검색 '단국대 캡스톤 페스티벌' — 3건")
    assert "(1) [공식] [소프트웨어학과] 2026 캡스톤 페스티벌 안내 — cms.dankook.ac.kr | 날짜: 2026-11-05" in out
    assert "(2) [외부·영상] 캡스톤 페스티벌 현장 스케치 — youtube.com" in out
    assert "(3) [외부] 단국대 캡스톤 후기 — blog.example.com" in out
    assert "…" in out  # 긴 조각은 자른다
    refs = extract_sources("web_search", out)
    assert [(r.title, r.url) for r in refs] == [
        ("[공식] [소프트웨어학과] 2026 캡스톤 페스티벌 안내", "https://cms.dankook.ac.kr/web/sw/-1?id=1"),
        ("[외부·영상] 캡스톤 페스티벌 현장 스케치", "https://www.youtube.com/watch?v=abc"),
        ("[외부] 단국대 캡스톤 후기", "https://blog.example.com/post/1"),
    ]
    assert "최근 검색 결과 재사용" in run(tool, query="단국대 캡스톤 페스티벌")


def test_tool_errors_are_tool_errors():
    tool = make_web_search(WebSearch(FakeBackend([]), Cache(None), daily_limit=0), OFFICIAL)
    with pytest.raises(ToolError, match="한도.*다른 도구"):
        run(tool, query="아무거나")
    with pytest.raises(ToolError, match="비어"):
        run(tool, query="  ")
    empty = make_web_search(WebSearch(FakeBackend([]), Cache(None)), OFFICIAL)
    assert "검색 결과가 없습니다" in run(empty, query="없는 것")


async def test_agent_uses_web_search():
    tool = make_web_search(WebSearch(FakeBackend(RESULTS), Cache(None)), OFFICIAL)
    agent = Agent(FakeProvider([Reply(calls=[("web_search", {"query": "단국대 캡스톤"})]), Reply(text="11월 27일입니다")]),
                  ToolRegistry([tool]))
    assert agent.tools.describe(type("C", (), {"name": "web_search", "arguments": {"query": "단국대 캡스톤"}})()) \
        == "웹에서 '단국대 캡스톤' 검색하는 중"
    events = [e async for e in agent.run("캡스톤 페스티벌 언제야?")]
    assert any(getattr(e, "result", None) and "[공식]" in e.result.content for e in events)


def test_bootstrap_registers_only_with_key(monkeypatch):
    from danbi.bootstrap import build_web_search

    s = Settings()
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert build_web_search(s, Cache(None)) is None
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    assert build_web_search(s, Cache(None)) is not None
    s.web_search.enabled = False
    assert build_web_search(s, Cache(None)) is None


async def test_per_run_cap():
    """web_search는 한 질문에 2번까지: 세 번째 호출은 실행하지 않고 오류 결과로 돌려준다."""
    backend = FakeBackend(RESULTS)
    tool = make_web_search(WebSearch(backend, Cache(None)), OFFICIAL)
    replies = [Reply(calls=[("web_search", {"query": "a"}), ("web_search", {"query": "b"})]),
               Reply(calls=[("web_search", {"query": "c"})]),
               Reply(text="답")]
    agent = Agent(FakeProvider(replies), ToolRegistry([tool]))
    events = [e async for e in agent.run("질문")]
    results = [e.result for e in events if hasattr(e, "result") and hasattr(e.result, "content")]
    assert backend.queries == ["a", "b"]
    assert results[-1].is_error and "2번까지" in results[-1].content
    assert events[-1].text == "답"
