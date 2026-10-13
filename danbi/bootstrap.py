"""설정에서 에이전트를 조립한다 (CLI·API 서버 공용)."""

from __future__ import annotations

import logging

from .agent.loop import Agent
from .agent.tools import ToolRegistry
from .config import Settings
from .llm import create_provider, options_from_settings

log = logging.getLogger(__name__)


def build_tools(settings: Settings, eclass=None) -> ToolRegistry:
    """eclass(EclassService)가 없어도 my_schedule은 늘 등록한다 (도구 정의가 채널마다 같아야 프롬프트 캐시가 유지된다)."""
    from .agent.tools.knowledge import make_search_knowledge
    from .agent.tools.personal import make_my_schedule
    from .rag.chroma_store import ChromaStore
    from .rag.embedder import GeminiEmbedder

    registry = ToolRegistry()
    try:
        store = ChromaStore(settings.rag.chroma_path, settings.rag.collection, settings.rag.sources)
    except FileNotFoundError as e:
        log.warning("RAG 비활성화: %s", e)
    else:
        registry.register(make_search_knowledge(store, GeminiEmbedder(settings.embedding), settings.rag.top_k))

    for tool in build_site_tools(settings).tools():
        registry.register(tool)
    registry.register(make_my_schedule(eclass))
    return registry


def build_eclass(settings: Settings, store):
    """eclass 캘린더 피드 연동 (웹 로그인 사용자). DANBI_SECRET_KEY가 없으면 꺼진 상태로 만든다."""
    from .crawler.http import HttpClient
    from .personal.eclass import EclassService

    c, p = settings.crawler, settings.personal
    if not p.secret_key:
        log.info("eclass 연결 꺼짐: DANBI_SECRET_KEY 없음")
    http = HttpClient(c.user_agent, min_interval=c.min_interval, timeout=c.timeout, retries=c.retries)
    return EclassService(store, http, p.secret_key, p.eclass_cache_minutes)


def load_snapshots(settings: Settings) -> dict[str, list[dict]]:
    """등록 시점 스크립트가 미리 만들어 둔 데이터셋 (질문할 때 사이트를 부르지 않는다)."""
    from .sources.campus_map import load_campus_map
    from .sources.timetable import load_timetable

    return {"campus_map": load_campus_map(settings.sources.campus_map_path),
            "timetable": load_timetable(settings.sources.timetable_path)}


def build_site_tools(settings: Settings):
    from .agent.tools.site import SiteTools
    from .crawler.adapters import create_adapter
    from .crawler.cache import Cache
    from .crawler.http import HttpClient
    from .sources.dept_list import load_dept_list
    from .sources.registry import SourceRegistry

    sources = SourceRegistry.load(*settings.sources.registry_paths)
    departments = load_dept_list(settings.sources.dept_list_path)
    sources.apply_departments(departments)
    c = settings.crawler
    http = HttpClient(c.user_agent, min_interval=c.min_interval, timeout=c.timeout, retries=c.retries)
    cache = Cache(c.cache_path)
    snapshots = load_snapshots(settings)
    adapters = {}
    for src in sources.web_sources():
        try:
            adapters[src.id] = create_adapter(src, http, cache, snapshots)
        except ValueError as e:
            log.warning("%s", e)
    vision = None
    if settings.vision.enabled:
        from .crawler.extract.vision import VisionReader
        from .llm import create_provider

        vision = VisionReader(create_provider(settings.llm))
    return SiteTools(sources, adapters, settings.agent.inline_source_limit, cache=cache, departments=departments,
                     vision=vision, auto_images=settings.vision.auto_images)


def build_agent(settings: Settings, *, with_tools: bool = True, eclass=None) -> Agent:
    return Agent(
        create_provider(settings.llm),
        build_tools(settings, eclass) if with_tools else ToolRegistry(),
        options=options_from_settings(settings.llm),
        max_tool_calls=settings.agent.max_tool_calls,
        timeout_seconds=settings.agent.timeout_seconds,
    )


def build_recorder(settings: Settings, agent: Agent, store=None):
    """추적 DB 기록기. CLI·API·평가가 같은 DB에 채널만 달리해서 기록한다."""
    from .ops import TraceRecorder, TraceStore

    return TraceRecorder(store or TraceStore(settings.ops.db_path), agent, settings.llm.pricing)
