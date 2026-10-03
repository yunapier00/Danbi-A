"""config/dept_list.yaml (scripts/collect_dept_list.py가 생성) 읽기."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Department:
    id: str
    name: str
    college: str = ""
    campus: str | None = None
    platform: str = "none"  # dku_cms | dku_www | external | none
    homepage: str | None = None
    majors: list[str] = field(default_factory=list)
    office: dict[str, str] = field(default_factory=dict)


def load_dept_list(path: str | Path) -> dict[str, Department]:
    p = Path(path)
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {
        str(k): Department(
            id=str(k), name=v.get("name", k), college=v.get("college") or "", campus=v.get("campus"),
            platform=v.get("platform") or "none", homepage=v.get("homepage"),
            majors=list(v.get("majors") or []), office=dict(v.get("office") or {}),
        )
        for k, v in raw.items()
    }
