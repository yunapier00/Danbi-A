"""등록된 웹 소스 스모크 테스트 (설계 §10.5 ⑤): 실제 사이트에서 notice 검색·상세 조회.

  pytest -m live tests/test_site_live.py
"""

import pytest

from danbi.config import load_settings
from danbi.crawler.adapters import create_adapter
from danbi.crawler.cache import Cache
from danbi.crawler.http import HttpClient
from danbi.sources.registry import SourceRegistry

pytestmark = pytest.mark.live

settings = load_settings()
registry = SourceRegistry.load(*settings.sources.registry_paths)
http = HttpClient(settings.crawler.user_agent, min_interval=settings.crawler.min_interval)


@pytest.mark.parametrize("source", [s for s in registry.web_sources() if "notice" in {x.role for x in s.sections.values()}],
                         ids=lambda s: s.id)
def test_notice_list_and_item(source):
    adapter = create_adapter(source, http, Cache(None))  # 캐시 없이 실제 사이트 확인
    section = registry.resolve_sections(source, "notice")[0]
    page = adapter.list(section)
    assert page.total_count > 0 and page.items, f"{source.id} notice 목록이 비었습니다"
    item = adapter.get_item(section, page.items[0].id)
    assert item.title and item.posted_at


@pytest.mark.parametrize("source", registry.web_sources(), ids=lambda s: s.id)
def test_all_sections_are_boards(source):
    adapter = create_adapter(source, http, Cache(None))
    for sec in source.sections.values():
        adapter.list(sec)  # 게시판이 아니면 ValueError, 404면 FetchError


@pytest.mark.parametrize("source", [s for s in registry.web_sources() if s.datasets or s.pages], ids=lambda s: s.id)
def test_datasets_and_pages_parse(source):
    adapter = create_adapter(source, http, Cache(None))
    for kind, entries in source.datasets.items():
        records = [r for e in entries for r in adapter.get_dataset(kind, e.path, e.org)]
        assert records, f"{source.id} {kind} 데이터가 비었습니다"
    for page in source.pages.values():
        assert adapter.get_page(page.path).body_md.strip(), f"{source.id} {page.id} 페이지 본문이 비었습니다"
