"""등록 소스 정기 재탐색 → 변경 보고서 (설계 §10.6). 주 1회 실행.

  .venv/Scripts/python -m scripts.recheck_sources                 # 등록된 dku_cms 소스 전체
  .venv/Scripts/python -m scripts.recheck_sources sw chem         # 일부만
  .venv/Scripts/python -m scripts.recheck_sources --dept-list     # 학과 목록(신설·폐지·변경)도 비교

레지스트리·dept_list는 자동으로 고치지 않는다. 보고서(logs/recheck_<날짜>.md)를 보고 사람이 반영한다.
LLM을 쓰지 않는다. 사이트당 메뉴 페이지 수십 건 요청 (1초 간격).
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date

from danbi.config import PROJECT_ROOT, load_settings
from danbi.crawler.http import FetchError, HttpClient
from danbi.sources.dept_list import load_dept_list
from danbi.sources.models import Source
from danbi.sources.registry import SourceRegistry

from .discover_source import Found, discover

log = logging.getLogger("recheck_sources")


@dataclass
class Diff:
    source: str
    new_boards: list[str] = field(default_factory=list)        # 메뉴에 새로 생긴 게시판 (제목 (경로))
    missing: list[str] = field(default_factory=list)           # 등록됐지만 메뉴 탐색에서 안 보이는 경로
    new_data: list[str] = field(default_factory=list)
    new_pages: list[str] = field(default_factory=list)
    broken_menu: list[str] = field(default_factory=list)       # 메뉴 링크 404
    error: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.new_boards or self.missing or self.new_data or self.new_pages or self.broken_menu or self.error)


def compare(src: Source, found: Found) -> Diff:
    """등록 내용과 탐색 결과를 경로 기준으로 비교한다."""
    sec_paths = {s.path for s in src.sections.values()}
    data_paths = {e.path for entries in src.datasets.values() for e in entries}
    page_paths = {p.path for p in src.pages.values()}
    found_boards = {s["path"]: s["title"] for s in found.sections}
    found_data = {e["path"] for entries in found.datasets.values() for e in entries}
    found_pages = {p["path"]: p["title"] for p in found.pages}
    found_all = set(found_boards) | found_data | set(found_pages)

    d = Diff(src.id)
    d.new_boards = [f"{t} ({p})" for p, t in found_boards.items() if p not in sec_paths]
    d.new_data = sorted(p for p in found_data if p not in data_paths)
    # 새 안내 페이지는 1차 검토에서 일부러 뺀 것이 많으므로 등록된 소스에는 보고만 한다
    d.new_pages = [f"{t} ({p})" for p, t in found_pages.items() if p not in page_paths]
    d.missing = sorted(p for p in sec_paths | data_paths | page_paths if p not in found_all)
    d.broken_menu = list(found.broken)
    return d


def verify_missing(src: Source, paths: list[str], http: HttpClient) -> list[str]:
    """메뉴에서 안 보이는 경로를 직접 열어 본다. 아직 열리면 '메뉴에서만 빠짐', 404면 '깨짐'."""
    out = []
    for path in paths:
        try:
            http.get(src.url(path))
            out.append(f"{path} — 메뉴에서 빠졌지만 아직 열림")
        except FetchError as e:
            out.append(f"{path} — 깨짐 ({e})")
    return out


def dept_list_changes(old: dict, new: dict) -> list[str]:
    lines = []
    for k in sorted(set(new) - set(old)):
        lines.append(f"- 신설/새 사이트: {k} {new[k]['name']} ({new[k].get('homepage')})")
    for k in sorted(set(old) - set(new)):
        lines.append(f"- 사라짐: {k} {old[k].name}")
    for k in sorted(set(old) & set(new)):
        o, n = old[k], new[k]
        for label, a, b in (("이름", o.name, n["name"]), ("소속", o.college, n["college"]),
                            ("홈페이지", o.homepage, n["homepage"]), ("사무실", o.office, n["office"])):
            if a != b:
                lines.append(f"- 변경: {k} {label} {a} → {b}")
    return lines


def report(diffs: list[Diff], dept_lines: list[str] | None) -> str:
    changed = [d for d in diffs if d.changed]
    lines = [f"# 소스 재탐색 보고서 ({date.today()})", "",
             f"확인한 소스 {len(diffs)}개 · 변경 있음 {len(changed)}개", ""]
    for d in changed:
        lines.append(f"## {d.source}")
        if d.error:
            lines.append(f"- 탐색 실패: {d.error}")
        for label, items in (("새 게시판 (등록 검토)", d.new_boards), ("새 데이터 페이지", d.new_data),
                             ("등록 경로 확인 필요", d.missing), ("메뉴 링크 404", d.broken_menu),
                             ("등록 안 된 안내 페이지 (참고)", d.new_pages)):
            if items:
                lines.append(f"- {label}:")
                lines += [f"  - {x}" for x in items]
        lines.append("")
    if dept_lines is not None:
        lines += ["## 학과 목록 변경 (config/dept_list.yaml 대비)", *(dept_lines or ["- 없음"]), ""]
    return "\n".join(lines)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="등록 소스 재탐색 → logs/recheck_<날짜>.md")
    ap.add_argument("ids", nargs="*", help="소스 ID (생략하면 등록된 dku_cms 소스 전체)")
    ap.add_argument("--dept-list", action="store_true", help="학과 목록도 다시 수집해 비교 (파일은 바꾸지 않음)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    settings = load_settings()
    registry = SourceRegistry.load(*settings.sources.registry_paths)
    # 학과 사이트만 (학교 공통 소스 base_url은 메인 사이트 루트라 메뉴 탐색이 사이트 전체로 번진다)
    targets = [s for s in registry.all() if s.type == "dku_cms" and s.kind == "department"
               and (not args.ids or s.id in args.ids)]
    c = settings.crawler
    http = HttpClient(c.user_agent, min_interval=c.min_interval, timeout=c.timeout, retries=c.retries)

    diffs = []
    for src in targets:
        log.info("재탐색 %s", src.id)
        try:
            d = compare(src, discover(src.base_url, http))
            d.missing = verify_missing(src, d.missing, http)
        except FetchError as e:
            d = Diff(src.id, error=str(e))
        diffs.append(d)

    dept_lines = None
    if args.dept_list:
        from .collect_dept_list import build, college_pages, parse_college
        pages = [parse_college(http.get(u).text) for u in college_pages(http)]
        pages.sort(key=lambda p: p[0] == "학부")
        fresh = build([(t, d) for t, ds in pages for d in ds])
        dept_lines = dept_list_changes(load_dept_list(settings.sources.dept_list_path), fresh)

    out = PROJECT_ROOT / "logs" / f"recheck_{date.today()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report(diffs, dept_lines), encoding="utf-8")
    log.info("보고서: %s (변경 %d/%d)", out.relative_to(PROJECT_ROOT), sum(d.changed for d in diffs), len(diffs))


if __name__ == "__main__":
    main()
