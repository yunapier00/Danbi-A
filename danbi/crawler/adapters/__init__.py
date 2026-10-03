from __future__ import annotations

from ...sources.models import Source
from ..cache import Cache
from ..http import HttpClient
from .base import SiteAdapter


def create_adapter(source: Source, http: HttpClient, cache: Cache) -> SiteAdapter:
    if source.type == "dku_cms":
        from .dku_cms import DkuCmsAdapter
        return DkuCmsAdapter(source, http, cache)
    if source.type == "static_page":
        from .static_page import StaticPageAdapter
        return StaticPageAdapter(source, http, cache)
    raise ValueError(f"아직 어댑터가 없는 소스 종류: {source.type} ({source.id})")
