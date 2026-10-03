"""소스 레지스트리 공통 타입."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlparse

# 섹션 역할 (설계 §10.2). 같은 역할이 둘 이상이면 접미사를 붙인다: rules, rules_sw
SECTION_ROLES = {"notice", "jobs", "grad", "scholarship", "rules", "activity", "archive", "capstone", "ignore"}
SOURCE_TYPES = {"chroma", "dku_cms", "static_page", "library"}
WEB_TYPES = SOURCE_TYPES - {"chroma"}


def section_role(section_id: str) -> str:
    """섹션 ID → 역할. 'rules_sw' → 'rules'"""
    return section_id.split("_", 1)[0]


@dataclass
class Section:
    id: str
    title: str
    path: str
    same_as: str | None = None  # 같은 글을 공유하는 섹션 ID (검색 중복 방지)

    @property
    def role(self) -> str:
        return section_role(self.id)


@dataclass
class DatasetEntry:
    path: str
    org: str | None = None  # 같은 데이터셋이 소속별로 여러 페이지에 있을 때 (예: 교과과정)


@dataclass
class Page:
    id: str
    title: str
    path: str


@dataclass
class Source:
    id: str
    type: str
    name: str
    description: str = ""
    kind: str | None = None  # department 등
    college: str | None = None
    campus: str | None = None
    aliases: list[str] = field(default_factory=list)
    office: dict[str, Any] = field(default_factory=dict)
    base_url: str | None = None
    sections: dict[str, Section] = field(default_factory=dict)
    datasets: dict[str, list[DatasetEntry]] = field(default_factory=dict)
    pages: dict[str, Page] = field(default_factory=dict)
    freshness: str | None = None
    reviewed_at: date | None = None
    reviewed_by: str | None = None  # human | claude (claude면 사람 2차 검토 대상)

    @property
    def is_web(self) -> bool:
        return self.type in WEB_TYPES

    @property
    def reviewed(self) -> bool:
        return self.reviewed_at is not None

    @property
    def origin(self) -> str:
        p = urlparse(self.base_url or "")
        return f"{p.scheme}://{p.netloc}"

    def url(self, path: str) -> str:
        return self.origin + path
