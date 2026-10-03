from datetime import date

import pytest
import yaml

from danbi.config import PROJECT_ROOT
from danbi.sources.registry import RegistryError, SourceLookupError, SourceRegistry

BASE = {
    "type": "dku_cms", "name": "테스트학과", "base_url": "https://cms.dankook.ac.kr/web/t",
    "sections": {
        "notice": {"title": "공지", "path": "/web/t/-1"},
        "rules": {"title": "규정A", "path": "/web/t/-2"},
        "rules_sw": {"title": "규정B", "path": "/web/t/-3", "same_as": "rules"},
        "jobs": {"title": "취업", "path": "/web/t/-4"},
        "jobs_2": {"title": "취업2", "path": "/web/t/-5"},
        "ignore": {"title": "갤러리", "path": "/web/t/-6"},
    },
    "reviewed_at": date(2026, 10, 2),
}


def load(tmp_path, data):
    p = tmp_path / "sources.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return SourceRegistry.load(p)


def test_project_registry_is_valid():
    reg = SourceRegistry.load(PROJECT_ROOT / "config" / "sources.yaml")
    assert "mobilesystems" in [s.id for s in reg.web_sources()]


def test_resolve_sections_by_id_and_role(tmp_path):
    reg = load(tmp_path, {"t": BASE})
    src = reg.get("t")
    assert [s.id for s in reg.resolve_sections(src, "rules")] == ["rules"]          # same_as 중복 제외
    assert [s.id for s in reg.resolve_sections(src, "rules_sw")] == ["rules_sw"]    # ID로 직접 지정
    assert [s.id for s in reg.resolve_sections(src, "jobs")] == ["jobs", "jobs_2"]  # 같은 역할 모두
    with pytest.raises(SourceLookupError, match="섹션이 없습니다"):
        reg.resolve_sections(src, "grad")
    with pytest.raises(SourceLookupError):
        reg.resolve_sections(src, "ignore")


def test_unreviewed_source_is_not_searchable(tmp_path):
    reg = load(tmp_path, {"t": {**BASE, "reviewed_at": None, "office": {"tel": "031-000-0000"}}})
    assert reg.web_sources() == []
    with pytest.raises(SourceLookupError, match="031-000-0000"):
        reg.get("t")
    with pytest.raises(SourceLookupError, match="알 수 없는 소스"):
        reg.get("nope")


@pytest.mark.parametrize("patch, msg", [
    ({"type": "wiki"}, "알 수 없는 type"),
    ({"base_url": "http://x"}, "https://"),
    ({"sections": {"news": {"title": "x", "path": "/a"}}}, "알 수 없는 역할"),
    ({"sections": {"notice": {"title": "x", "path": "web/a"}}}, "/로 시작"),
    ({"sections": {"rules_sw": {"title": "x", "path": "/a", "same_as": "rules"}}}, "same_as"),
    ({"reviewed_at": "언젠가"}, "reviewed_at"),
])
def test_validation_errors(tmp_path, patch, msg):
    with pytest.raises(RegistryError, match=msg):
        load(tmp_path, {"t": {**BASE, **patch}})


def test_load_multiple_files_and_duplicates(tmp_path):
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text(yaml.safe_dump({"t": BASE}, allow_unicode=True), encoding="utf-8")
    b.write_text(yaml.safe_dump({"u": {**BASE, "reviewed_by": "claude"}}, allow_unicode=True), encoding="utf-8")
    reg = SourceRegistry.load(a, b, tmp_path / "missing.yaml")
    assert [s.id for s in reg.all()] == ["t", "u"] and reg.get("u").reviewed_by == "claude"
    with pytest.raises(RegistryError, match="소스 ID 중복: t"):
        SourceRegistry.load(a, a)
