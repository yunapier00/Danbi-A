"""검색 기능이 없는 단순 안내 페이지 (본문 → 마크다운). get_page만 지원한다."""

from __future__ import annotations

from dataclasses import asdict

from bs4 import BeautifulSoup

from ...sources.models import Source
from ..cache import TTL_PAGE, Cache
from ..extract.html import html_to_md
from ..http import HttpClient
from .base import PageDoc, SiteAdapter

# 본문 후보 (앞에서부터). 없으면 body 전체에서 머리글·바닥글·메뉴를 뺀다
_MAIN_SELECTORS = ["#main-content", "main", "#content", "article", "#contents"]


def parse_static_page(html: str, url: str) -> PageDoc:
    soup = BeautifulSoup(html, "lxml")
    main = next((m for s in _MAIN_SELECTORS if (m := soup.select_one(s))), None)
    if main is None:
        main = soup.body or soup
        for t in main.select("header, footer, nav"):
            t.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    return PageDoc(title=title, url=url, body_md=html_to_md(main))


class StaticPageAdapter(SiteAdapter):
    supports = {"get_page"}

    def __init__(self, source: Source, http: HttpClient, cache: Cache):
        super().__init__(source)
        self.http = http
        self.cache = cache

    def get_page(self, path: str) -> PageDoc:
        url = self.source.url(path)
        key = f"static_page:{url}"
        if (hit := self.cache.get(key)) is not None:
            return PageDoc(**hit)
        page = parse_static_page(self.http.get(url).text, url)
        self.cache.set(key, asdict(page), TTL_PAGE)
        return page
