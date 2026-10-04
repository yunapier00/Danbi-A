"""설정 로딩: config/settings.yaml + .env"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS = PROJECT_ROOT / "config" / "settings.yaml"


@dataclass
class LLMSettings:
    provider: str = "gemini"
    model: str = "gemini-flash-latest"
    temperature: float = 0.0
    max_output_tokens: int = 4096
    options: dict[str, Any] = field(default_factory=dict)
    pricing: dict[str, float] = field(default_factory=dict)  # input_per_mtok, output_per_mtok (USD). 평가 비용 추정용


@dataclass
class EmbeddingSettings:
    provider: str = "gemini"
    model: str = "gemini-embedding-001"
    dimensions: int = 3072


@dataclass
class RagSourceInfo:
    short: str
    label: str
    content: str = ""
    as_of: str = ""


@dataclass
class RagSettings:
    chroma_path: Path = PROJECT_ROOT / "chroma_db_dd3"
    collection: str = "campus_rules"
    top_k: int = 8
    sources: dict[str, RagSourceInfo] = field(default_factory=dict)  # 파일명 → 정보


@dataclass
class SourcesSettings:
    registry_path: Path = PROJECT_ROOT / "config" / "sources.yaml"
    extra_registry_paths: list[Path] = field(default_factory=list)  # 예: 학과 일괄 등록 파일
    dept_list_path: Path = PROJECT_ROOT / "config" / "dept_list.yaml"
    campus_map_path: Path = PROJECT_ROOT / "config" / "campus_map.yaml"  # scripts.collect_campus_map이 생성

    @property
    def registry_paths(self) -> list[Path]:
        return [self.registry_path, *self.extra_registry_paths]


@dataclass
class CrawlerSettings:
    user_agent: str = "DanbiBot/0.1 (Dankook University Q&A assistant)"
    min_interval: float = 1.0
    timeout: float = 20
    retries: int = 2
    cache_path: Path = PROJECT_ROOT / "cache" / "danbi_cache.sqlite"


@dataclass
class OpsSettings:
    db_path: Path = PROJECT_ROOT / "data" / "danbi_ops.sqlite"
    retention_days: float = 180       # 실행 기록 보관 기간 (감사 로그는 지우지 않음)
    store_client_ip: bool = True      # 웹 요청 IP를 실행 기록에 저장
    ip_retention_days: float = 90     # IP만 이보다 먼저 지운다 (purge)
    trust_proxy_headers: bool = False # 리버스 프록시 뒤일 때만 True (X-Forwarded-For를 믿음)
    proxy_hops: int = 1               # 앞단 프록시 수. X-Forwarded-For의 오른쪽에서 이 번째 값이 실제 클라이언트
    admin_token_env: str = "DANBI_ADMIN_TOKEN"  # 개발자 페이지 토큰을 읽을 환경 변수 이름 (값은 .env에만)

    @property
    def admin_token(self) -> str | None:
        import os
        return os.environ.get(self.admin_token_env) or None


@dataclass
class LimitSettings:
    """공개 채팅의 남용·비용 방어. 하루 기준은 한국 시간 자정."""
    per_ip_per_minute: int = 10       # 웹은 IP, 카카오는 사용자 키 기준 (분당)
    per_user_per_day: int = 3         # 한 사람의 하루 질문 수 (웹 = IP, 카카오 = 사용자). 추적 DB에서 센다
    daily_questions: int = 1000       # 웹 채널 전체 하루 질문 수
    daily_tokens: int = 20_000_000    # 웹 채널 전체 하루 토큰(입력+출력)
    max_concurrent: int = 4           # 동시에 답하는 질문 수
    admin_auth_failures: int = 10     # IP당 10분에 허용하는 개발자 토큰 실패 횟수


@dataclass
class KakaoSettings:
    """카카오톡 챗봇 스킬. KAKAO_SKILL_SECRET이 없으면 엔드포인트를 열지 않는다."""
    callback_hosts: list[str] = field(default_factory=lambda: ["kakao.com", "kakaoenterprise.com"])
    sync_timeout: float = 4.3         # 콜백이 없을 때 이 안에 끝나야 한다 (카카오 스킬 제한 5초)

    @property
    def secret(self) -> str | None:
        import os
        return os.environ.get("KAKAO_SKILL_SECRET") or None

    @property
    def user_salt(self) -> str | None:
        import os
        return os.environ.get("KAKAO_USER_SALT") or self.secret


@dataclass
class AgentSettings:
    max_tool_calls: int = 10
    timeout_seconds: float = 60
    inline_source_limit: int = 20


@dataclass
class Settings:
    llm: LLMSettings = field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    rag: RagSettings = field(default_factory=RagSettings)
    sources: SourcesSettings = field(default_factory=SourcesSettings)
    crawler: CrawlerSettings = field(default_factory=CrawlerSettings)
    ops: OpsSettings = field(default_factory=OpsSettings)
    limits: LimitSettings = field(default_factory=LimitSettings)
    kakao: KakaoSettings = field(default_factory=KakaoSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    enable_docs: bool = False   # /api/docs (DANBI_ENABLE_DOCS=1)


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def load_settings(path: str | Path | None = None) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    raw = yaml.safe_load(Path(path or DEFAULT_SETTINGS).read_text(encoding="utf-8")) or {}

    rag_raw = dict(raw.get("rag") or {})
    sources = {name: RagSourceInfo(**info) for name, info in (rag_raw.pop("sources", None) or {}).items()}
    if "chroma_path" in rag_raw:
        rag_raw["chroma_path"] = _resolve(rag_raw["chroma_path"])
    sources_raw = dict(raw.get("sources") or {})
    for key in ("registry_path", "dept_list_path", "campus_map_path"):
        if key in sources_raw:
            sources_raw[key] = _resolve(sources_raw[key])
    sources_raw["extra_registry_paths"] = [_resolve(p) for p in sources_raw.get("extra_registry_paths") or []]
    crawler_raw = dict(raw.get("crawler") or {})
    if "cache_path" in crawler_raw:
        crawler_raw["cache_path"] = _resolve(crawler_raw["cache_path"])

    ops_raw = dict(raw.get("ops") or {})
    if "db_path" in ops_raw:
        ops_raw["db_path"] = _resolve(ops_raw["db_path"])

    settings = Settings(
        llm=LLMSettings(**(raw.get("llm") or {})),
        embedding=EmbeddingSettings(**(raw.get("embedding") or {})),
        rag=RagSettings(**rag_raw, sources=sources),
        sources=SourcesSettings(**sources_raw),
        crawler=CrawlerSettings(**crawler_raw),
        ops=OpsSettings(**ops_raw),
        limits=LimitSettings(**(raw.get("limits") or {})),
        kakao=KakaoSettings(**(raw.get("kakao") or {})),
        agent=AgentSettings(**(raw.get("agent") or {})),
    )
    _apply_env(settings)
    return settings


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _apply_env(s: Settings) -> None:
    """배포 환경 변수로 덮어쓴다 (Railway 등). 비밀값(API 키·관리자 토큰)은 원래부터 환경 변수로만 받는다.

    DANBI_DATA_DIR      쓰기 가능한 영구 저장소 (추적 DB·크롤링 캐시). 예: Railway Volume /data
    DANBI_TRUST_PROXY   1이면 X-Forwarded-For를 믿는다 (Railway처럼 프록시 뒤일 때)
    DANBI_PROXY_HOPS    앞단 프록시 수 (기본 1)
    DANBI_ENABLE_DOCS   1이면 /api/docs를 연다
    """
    import os

    if data := os.environ.get("DANBI_DATA_DIR"):
        base = Path(data)
        s.ops.db_path = base / "danbi_ops.sqlite"
        s.crawler.cache_path = base / "cache" / "danbi_cache.sqlite"
    if "DANBI_TRUST_PROXY" in os.environ:
        s.ops.trust_proxy_headers = _truthy(os.environ["DANBI_TRUST_PROXY"])
    if hops := os.environ.get("DANBI_PROXY_HOPS"):
        s.ops.proxy_hops = max(1, int(hops))
    s.enable_docs = _truthy(os.environ.get("DANBI_ENABLE_DOCS"))
