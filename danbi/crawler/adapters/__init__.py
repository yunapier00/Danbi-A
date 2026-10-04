from __future__ import annotations

from ...sources.models import Source
from ..cache import Cache
from ..http import HttpClient
from .base import SiteAdapter


def create_adapter(source: Source, http: HttpClient, cache: Cache,
                   snapshots: dict[str, list[dict]] | None = None) -> SiteAdapter:
    """snapshots: 등록 시점 스크립트가 미리 모아 둔 데이터셋 (예: campus_map). 질문할 때 사이트를 부르지 않는다."""
    if source.type == "dku_cms":
        from .dku_cms import DkuCmsAdapter
        return DkuCmsAdapter(source, http, cache, snapshots=snapshots)
    if source.type == "static_page":
        from .static_page import StaticPageAdapter
        return StaticPageAdapter(source, http, cache)
    raise ValueError(f"아직 어댑터가 없는 소스 종류: {source.type} ({source.id})")
