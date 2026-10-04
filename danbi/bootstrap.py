"""설정에서 에이전트를 조립한다 (CLI·API 서버 공용)."""

from __future__ import annotations

import logging

from .agent.loop import Agent
from .agent.tools import ToolRegistry
from .config import Settings
from .llm import create_provider, options_from_settings

log = logging.getLogger(__name__)


def build_tools(settings: Settings) -> ToolRegistry:
    from .agent.tools.knowledge import make_search_knowledge
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
    return registry


def build_site_tools(settings: Settings):
    from .agent.tools.site import SiteTools
    from .crawler.adapters import create_adapter
    from .crawler.cache import Cache
    from .crawler.http import HttpClient
    from .sources.campus_map import load_campus_map
    from .sources.dept_list import load_dept_list
    from .sources.registry import SourceRegistry

    sources = SourceRegistry.load(*settings.sources.registry_paths)
    departments = load_dept_list(settings.sources.dept_list_path)
    sources.apply_departments(departments)
    c = settings.crawler
    http = HttpClient(c.user_agent, min_interval=c.min_interval, timeout=c.timeout, retries=c.retries)
    cache = Cache(c.cache_path)
    snapshots = {"campus_map": load_campus_map(settings.sources.campus_map_path)}
    adapters = {}
    for src in sources.web_sources():
        try:
            adapters[src.id] = create_adapter(src, http, cache, snapshots)
        except ValueError as e:
            log.warning("%s", e)
    return SiteTools(sources, adapters, settings.agent.inline_source_limit, cache=cache, departments=departments)


def build_agent(settings: Settings, *, with_tools: bool = True) -> Agent:
    return Agent(
        create_provider(settings.llm),
        build_tools(settings) if with_tools else ToolRegistry(),
        options=options_from_settings(settings.llm),
        max_tool_calls=settings.agent.max_tool_calls,
        timeout_seconds=settings.agent.timeout_seconds,
    )


def build_recorder(settings: Settings, agent: Agent):
    """추적 DB 기록기. CLI·API·평가가 같은 DB에 채널만 달리해서 기록한다."""
    from .ops import TraceRecorder, TraceStore

    return TraceRecorder(TraceStore(settings.ops.db_path), agent, settings.llm.pricing)
