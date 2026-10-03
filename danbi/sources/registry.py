"""sources.yaml 읽기·검증, 소스·섹션 해석."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .models import SECTION_ROLES, SOURCE_TYPES, DatasetEntry, Page, Section, Source


class RegistryError(ValueError):
    pass


class SourceLookupError(LookupError):
    """에이전트가 잘못된 소스·섹션을 지정했을 때. 메시지는 에이전트에게 그대로 전달된다."""


def _parse_source(sid: str, raw: dict[str, Any], filename: str = "sources.yaml") -> Source:
    def err(msg: str) -> RegistryError:
        return RegistryError(f"{filename} [{sid}]: {msg}")

    for key in ("type", "name"):
        if not raw.get(key):
            raise err(f"필수 필드 누락: {key}")
    if raw["type"] not in SOURCE_TYPES:
        raise err(f"알 수 없는 type: {raw['type']} (가능: {', '.join(sorted(SOURCE_TYPES))})")

    sections = {}
    for sec_id, s in (raw.get("sections") or {}).items():
        sections[sec_id] = Section(id=sec_id, title=s.get("title", sec_id), path=s.get("path", ""), same_as=s.get("same_as"))
    datasets = {}
    for ds_id, entries in (raw.get("datasets") or {}).items():
        entries = entries if isinstance(entries, list) else [entries]
        datasets[ds_id] = [DatasetEntry(path=e.get("path", ""), org=e.get("org")) for e in entries]
    pages = {pid: Page(id=pid, title=p.get("title", pid), path=p.get("path", "")) for pid, p in (raw.get("pages") or {}).items()}

    reviewed = raw.get("reviewed_at")
    if reviewed is not None and not isinstance(reviewed, date):
        raise err(f"reviewed_at은 날짜(YYYY-MM-DD)여야 합니다: {reviewed!r}")

    src = Source(
        id=sid,
        type=raw["type"],
        name=raw["name"],
        description=raw.get("description") or "",
        kind=raw.get("kind"),
        college=raw.get("college"),
        campus=raw.get("campus"),
        aliases=list(raw.get("aliases") or []),
        office=dict(raw.get("office") or {}),
        base_url=(raw.get("base_url") or "").rstrip("/") or None,
        sections=sections,
        datasets=datasets,
        pages=pages,
        freshness=raw.get("freshness"),
        reviewed_at=reviewed,
        reviewed_by=raw.get("reviewed_by"),
    )

    if src.is_web:
        if not src.base_url or not src.base_url.startswith("https://"):
            raise err("웹 소스에는 https:// base_url이 필요합니다")
        paths = [s.path for s in sections.values()] + [p.path for p in pages.values()]
        paths += [e.path for entries in datasets.values() for e in entries]
        for p in paths:
            if not p.startswith("/"):
                raise err(f"경로는 /로 시작해야 합니다: {p!r}")
        for sec in sections.values():
            if sec.role not in SECTION_ROLES:
                raise err(f"섹션 {sec.id}: 알 수 없는 역할 {sec.role} (가능: {', '.join(sorted(SECTION_ROLES))})")
            if sec.same_as and sec.same_as not in sections:
                raise err(f"섹션 {sec.id}: same_as 대상이 없습니다: {sec.same_as}")
    return src


class SourceRegistry:
    def __init__(self, sources: list[Source]):
        self._sources = {s.id: s for s in sources}

    @classmethod
    def load(cls, *paths: str | Path) -> SourceRegistry:
        """여러 파일을 합쳐 읽는다 (없는 파일은 건너뜀). 같은 ID가 두 파일에 있으면 오류."""
        sources: dict[str, Source] = {}
        for path in paths:
            p = Path(path)
            if not p.exists():
                continue
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for sid, body in raw.items():
                if str(sid) in sources:
                    raise RegistryError(f"소스 ID 중복: {sid} ({p.name})")
                sources[str(sid)] = _parse_source(str(sid), body or {}, p.name)
        return cls(list(sources.values()))

    def apply_departments(self, departments: dict) -> None:
        """학교 공식 학과 목록(dept_list.yaml)으로 비어 있는 단과대학·캠퍼스·사무실 연락처를 채운다."""
        for src in self._sources.values():
            dept = departments.get(src.id)
            if dept is None:
                continue
            src.college = src.college or dept.college or None
            src.campus = src.campus or dept.campus
            src.office = src.office or dict(dept.office)

    def all(self) -> list[Source]:
        return list(self._sources.values())

    def web_sources(self, reviewed_only: bool = True) -> list[Source]:
        return [s for s in self._sources.values() if s.is_web and (s.reviewed or not reviewed_only)]

    def get(self, source_id: str) -> Source:
        src = self._sources.get(source_id)
        if src is None or not src.is_web:
            known = ", ".join(s.id for s in self.web_sources())
            raise SourceLookupError(f"알 수 없는 소스: {source_id}. 사용 가능: {known}")
        if not src.reviewed:
            raise SourceLookupError(f"{src.name}({src.id})은(는) 아직 단비에서 검색을 지원하지 않습니다. "
                                    f"{_contact(src)}")
        return src

    def resolve_sections(self, source: Source, section: str) -> list[Section]:
        """섹션 ID 또는 역할 → 섹션 목록. 역할로 지정하면 같은 역할의 섹션을 모두 돌려주되 same_as로 묶인 것은 한 번만."""
        if section in source.sections and section not in SECTION_ROLES:
            return [source.sections[section]]  # 접미사가 붙은 섹션 ID (예: rules_sw)
        matched = [s for s in source.sections.values() if s.role == section and s.role != "ignore"]
        matched = [s for s in matched if not (s.same_as and s.same_as in {m.id for m in matched})]
        if not matched:
            available = ", ".join(f"{s.id}({s.title})" for s in source.sections.values() if s.role != "ignore") or "없음"
            raise SourceLookupError(f"{source.name}에는 '{section}' 섹션이 없습니다. 이 소스의 섹션: {available}")
        return matched


def _contact(src: Source) -> str:
    parts = []
    if src.office.get("tel"):
        parts.append(f"전화 {src.office['tel']}")
    if src.office.get("room"):
        parts.append(f"사무실 {src.office['room']}")
    if src.base_url:
        parts.append(f"홈페이지 {src.base_url}")
    return ("문의: " + ", ".join(parts)) if parts else ""
