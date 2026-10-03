"""사이트 탐색 → 등록 초안(config/drafts/<ID>.yaml) 생성 (설계 §10.5 ②).

  .venv/Scripts/python -m scripts.discover_source --type dku_cms sw chem
  .venv/Scripts/python -m scripts.discover_source --type dku_cms --all     # dept_list의 cms 사이트 전체 (1~2시간)

메뉴 페이지만 방문한다(게시글 본문은 수집하지 않음). LLM을 쓰지 않는다.
초안은 사람이 검토(역할·description·별칭·[검토] 항목·reviewed_at)한 뒤 config/sources.yaml에 합친다.
역할을 추정하지 못한 게시판은 review_N으로 남기며, 이 상태로 합치면 레지스트리 검증에서 거부된다.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from danbi.config import PROJECT_ROOT, load_settings
from danbi.crawler.http import FetchError, HttpClient
from danbi.sources.dept_list import Department, load_dept_list
from danbi.sources.registry import SourceRegistry

log = logging.getLogger("discover_source")

DRAFTS = PROJECT_ROOT / "config" / "drafts"
MAX_PAGES = 80
MIN_PAGE_CHARS = 80  # 이보다 짧은 일반 페이지는 안내 페이지로 보지 않는다

# 게시판 이름 → 역할 (앞에서부터 먼저 맞는 것)
ROLE_RULES = [
    ("ignore", ("갤러리", "사진", "앨범", "포토")),
    ("grad", ("대학원",)),
    ("scholarship", ("장학",)),
    ("jobs", ("취업", "채용", "인턴", "진로")),
    ("rules", ("규정", "내규", "규칙", "지침")),
    ("capstone", ("졸업작품", "캡스톤")),
    ("activity", ("교외활동", "행사", "활동", "소식", "뉴스", "news")),
    ("archive", ("자료실", "서식", "양식", "자료")),
    ("notice", ("공지", "notice")),
]
PAGE_RULES = [
    ("graduation", ("졸업요건", "졸업 요건", "졸업기준")),
    ("scholarship", ("장학",)),
    ("faq", ("faq", "자주 묻는")),
    ("location", ("오시는", "찾아오시는", "위치", "location")),
    ("contact", ("연락처", "사무실")),
]
LOW_VALUE_PAGES = ("인사말", "연혁", "비전", "학과장", "갤러리", "사이트맵", "개인정보")
DATASET_LABEL = {"professors": "교수", "curriculum": "교과과정", "dept_info": "학과 소개"}


def page_key(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{quote(unquote(p.path))}"


def guess(rules, title: str) -> str | None:
    t = title.lower()
    return next((role for role, words in rules if any(w.lower() in t for w in words)), None)


@dataclass
class Found:
    sections: list[dict] = field(default_factory=list)   # {title, path, count}
    datasets: dict[str, list[dict]] = field(default_factory=dict)
    pages: list[dict] = field(default_factory=list)      # {title, path, chars}
    broken: list[str] = field(default_factory=list)
    denied: list[dict] = field(default_factory=list)     # 비공개 게시판 (로그인 필요, "BBS 경고 접근 거부") {title, path}
    visited: int = 0


def _in_scope(url: str, origin: str, scope: str) -> bool:
    p = urlparse(url)
    if f"{p.scheme}://{p.netloc}" != origin or p.query or p.fragment:
        return False
    path = unquote(p.path).rstrip("/")
    return path.startswith(scope + "/")


def _menu_links(soup: BeautifulSoup, base: str, origin: str, scope: str, *, menu_only: bool) -> list[str]:
    anchors = soup.select("nav a[href], .lp-nav-item a[href]") if menu_only else soup.select("a[href]")
    out = []
    for a in anchors:
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = urljoin(base, href).split("#")[0]
        if _in_scope(url, origin, scope):
            out.append(page_key(url))
    return list(dict.fromkeys(out))


def discover(base_url: str, http: HttpClient, max_pages: int = MAX_PAGES) -> Found:
    p = urlparse(base_url)
    origin, scope = f"{p.scheme}://{p.netloc}", unquote(p.path).rstrip("/")
    home = BeautifulSoup(http.get(base_url).text, "lxml")
    queue = deque(_menu_links(home, base_url, origin, scope, menu_only=False))
    queued, done = set(queue), set()
    found = Found()

    while queue and found.visited < max_pages:
        url = queue.popleft()
        try:
            r = http.get(url)
        except FetchError as e:
            if e.status == 404:
                found.broken.append(unquote(urlparse(url).path))
            else:
                log.warning("  실패 %s: %s", unquote(url), e)
            continue
        final = page_key(r.url)
        if final in done or not _in_scope(final, origin, scope):
            continue  # 상위 메뉴는 첫 하위 메뉴로 리다이렉트된다 → 최종 주소로 중복 제거
        done.add(final)
        found.visited += 1
        soup = BeautifulSoup(r.text, "lxml")
        _classify(soup, unquote(urlparse(final).path), found)
        for link in _menu_links(soup, final, origin, scope, menu_only=True):
            if link not in queued:
                queued.add(link)
                queue.append(link)
    return found


def _area(soup: BeautifulSoup) -> str:
    """메뉴 경로의 최상위 (예: '대학원 > 졸업요건' → '대학원'). 학부·대학원 페이지를 구분하는 데 쓴다."""
    crumbs = [c.get_text(" ", strip=True) for c in soup.select("nav[id*=breadcrumbs] .lp-breadcrumb-item-inner > span:first-child")]
    crumbs = [c for c in crumbs if c]
    return crumbs[0] if len(crumbs) > 1 else ""


def _display_title(title: str, area: str) -> str:
    """대학원·학부 메뉴 아래 페이지는 제목에 구분을 붙인다 (예: '졸업요건' → '대학원 졸업요건')."""
    for word in ("대학원", "학부"):
        if word in area and word not in title:
            return f"{word} {title}"
    return title


def _classify(soup: BeautifulSoup, path: str, found: Found) -> None:
    title = soup.title.get_text(strip=True).split(" - ")[0] if soup.title else path
    area = _area(soup)
    main = soup.select_one("#main-content")
    if main is None:
        return
    if is_denied_board(main):
        found.denied.append({"title": title, "path": path})
        log.info("  비공개  %s (%s)", title, path)
        return
    if main.select_one(".dku-list-body"):
        header = main.select_one(".dku-list-header")
        m = re.search(r"전체\s*([\d,]+)\s*건", header.get_text(" ") if header else "")
        found.sections.append({"title": title, "path": path, "area": area,
                               "count": int(m.group(1).replace(",", "")) if m else None})
        log.info("  게시판  %s (%s)", title, path)
        return
    scripts = main.select('script[type="application/json"]')
    ids = [sc.get("id", "") for sc in scripts if _has_data(sc.string)]
    curriculum_page = any(sc.get("id", "").endswith("curriculumsByTypeData") for sc in scripts)
    kinds = []
    if any(i.endswith("professorsData") for i in ids):
        kinds.append(("professors", None))
    if any(i.endswith("curriculumsByTypeData") for i in ids):
        kinds.append(("curriculum", "대학원" if "대학원" in area else _curriculum_org(main)))
    elif curriculum_page:
        log.info("  빈 교과과정  %s (%s) — 건너뜀", title, path)  # 학과 소개로 중복 등록하지 않는다
        return
    elif any(i.endswith("deptData") for i in ids):
        kinds.append(("dept_info", "대학원" if "대학원" in area else None))
    if kinds:
        for kind, org in kinds:
            found.datasets.setdefault(kind, []).append({"path": path, **({"org": org} if org else {})})
        log.info("  데이터  %s (%s): %s", title, path, ", ".join(k for k, _ in kinds))
        return
    chars = len(main.get_text(" ", strip=True))
    if chars >= MIN_PAGE_CHARS:
        found.pages.append({"title": _display_title(title, area), "path": path, "chars": chars, "area": area})
        log.info("  페이지  %s (%s)", title, path)


def is_denied_board(main) -> bool:
    """게시판 포틀릿이 '접근 거부'를 보여 주는 페이지 (로그인한 구성원만 볼 수 있는 게시판). 우회하지 않고 기록만 한다."""
    portlet = main.select_one(".dku_bbs_web_BbsPortlet, [id^='p_p_id_dku_bbs_web_BbsPortlet']")
    return bool(portlet and portlet.select_one(".alert-danger") and "접근 거부" in portlet.get_text(" "))


def _has_data(raw: str | None) -> bool:
    """JSON에 실제 내용이 있는지. 교과과정은 {"cmm": [], "mod": [], ...}처럼 키만 있고 전부 비어 있는 경우가 있다."""
    try:
        data = json.loads(raw or "null")
    except json.JSONDecodeError:
        return False
    if isinstance(data, dict):
        return any(v not in (None, "", [], {}) for v in data.values())
    return bool(data)


def _curriculum_org(main) -> str | None:
    """교과과정 페이지의 deptData orgzNm에서 소속(단과대학)을 뽑는다. 예: '프리무스국제대학 모바일시스템공학과' → '프리무스국제대학'"""
    for sc in main.select('script[id$="deptData"]'):
        try:
            d = json.loads(sc.string or "null")
        except json.JSONDecodeError:
            continue
        if d and d.get("orgzNm") and d.get("orgzPrtNm") and d["orgzNm"].endswith(d["orgzPrtNm"]):
            return d["orgzNm"][: -len(d["orgzPrtNm"])].strip() or None
    return None


# --- 초안 작성 ---------------------------------------------------------------------

def _q(s) -> str:
    return json.dumps(s, ensure_ascii=False)  # JSON 문자열은 그대로 YAML 문자열이다


def build_draft(sid: str, dept: Department, found: Found, source_type: str) -> str:
    sections: list[tuple[str, dict, str]] = []
    used: dict[str, int] = {}
    for sec in found.sections:
        role = guess(ROLE_RULES, sec["title"])
        note = f"{sec['count']:,}건" if sec["count"] is not None else ""
        if sec.get("area") and sec["area"] != "게시판":
            note += f" · 메뉴: {sec['area']}"
        if role is None:
            role = "review"
            note += " [검토] 역할 추정 실패 — notice/jobs/grad/scholarship/rules/activity/archive/capstone/ignore 중 하나로"
        used[role] = used.get(role, 0) + 1
        sec_id = role if used[role] == 1 else f"{role}_{used[role]}"
        if used[role] == 2 and role not in ("review", "ignore"):
            note += f" [검토] {role} 역할이 둘 이상 — 같은 글이면 same_as: {role}"
        sections.append((sec_id, sec, note.strip()))

    pages: list[tuple[str, dict, str]] = []
    pused: dict[str, int] = {}
    for n, pg in enumerate(found.pages, 1):
        pid = guess(PAGE_RULES, pg["title"]) or f"page_{n}"
        if "대학원" in pg.get("area", "") and not pid.startswith("page_"):
            pid = f"grad_{pid}"
        pused[pid] = pused.get(pid, 0) + 1
        if pused[pid] > 1:
            pid = f"{pid}_{pused[pid]}"
        note = f"{pg['chars']:,}자" + (f" · 메뉴: {pg['area']}" if pg.get("area") else "")
        if any(w in pg["title"] for w in LOW_VALUE_PAGES) or pid.startswith("page_"):
            note += " [검토] 답변에 필요 없으면 삭제, 남기면 ID를 의미 있게"
        pages.append((pid, pg, note))

    parts = [sec["title"] for sid_, sec, _ in sections if not sid_.startswith("ignore")]
    parts += [DATASET_LABEL[k] for k in found.datasets]
    parts += [pg["title"] for _, pg, _ in pages[:5]]
    description = f"{dept.name} " + "·".join(dict.fromkeys(parts))

    office = ", ".join(f"{k}: {_q(v)}" for k, v in dept.office.items())
    lines = [
        f"# 등록 초안 — scripts/discover_source.py가 {date.today()} 생성. 검토 후 config/sources.yaml에 합친다.",
        "# 검토할 것: ① 섹션 역할(review_N 고치기) ② description 다듬기 ③ 별칭(줄임말) 추가 ④ [검토] 항목 ⑤ reviewed_at 기입",
        f"{sid}:",
        f"  type: {source_type}",
        "  kind: department",
        f"  name: {_q(dept.name)}",
        f"  college: {_q(dept.college)}",
        f"  aliases: [{', '.join(_q(m) for m in dict.fromkeys(dept.majors))}]   # 줄임말·옛 이름을 추가하세요",
        f"  campus: {_q(dept.campus)}" if dept.campus else "  campus: null",
        f"  office: {{ {office} }}",
        f"  base_url: {dept.homepage}",
        f"  description: {_q(description)}",
    ]
    if sections:
        lines.append("  sections:")
        lines += [f"    {sid_}: {{ title: {_q(sec['title'])}, path: {_q(sec['path'])} }}" + (f"   # {note}" if note else "")
                  for sid_, sec, note in sections]
    if found.datasets:
        lines.append("  datasets:")
        for kind, entries in found.datasets.items():
            lines.append(f"    {kind}:")
            lines += ["      - { " + ", ".join(f"{k}: {_q(v)}" for k, v in e.items()) + " }" for e in entries]
    if pages:
        lines.append("  pages:")
        lines += [f"    {pid}: {{ title: {_q(pg['title'])}, path: {_q(pg['path'])} }}   # {note}" for pid, pg, note in pages]
    lines += ["  freshness: realtime", "  reviewed_at: null   # 검토를 마치면 날짜(YYYY-MM-DD)", ""]
    lines.append(f"# 탐색 기록: 메뉴 페이지 {found.visited}개 방문, 게시판 {len(found.sections)}개, "
                 f"데이터 {sum(len(v) for v in found.datasets.values())}개, 안내 페이지 {len(found.pages)}개")
    if found.broken:
        lines.append(f"# 404 메뉴: {', '.join(found.broken)}")
    if found.denied:
        lines.append("# 비공개 게시판(접근 거부): " + ", ".join(f"{d['title']} ({d['path']})" for d in found.denied))
    return "\n".join(lines) + "\n"


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="사이트 탐색 → config/drafts/<ID>.yaml")
    ap.add_argument("ids", nargs="*", help="dept_list.yaml의 사이트 ID (예: sw chem)")
    ap.add_argument("--type", default="dku_cms", choices=["dku_cms"], help="소스 종류 (현재 dku_cms만)")
    ap.add_argument("--all", action="store_true", help="dept_list의 해당 종류 사이트 전체")
    ap.add_argument("--force", action="store_true", help="이미 초안이 있거나 등록된 소스도 다시 탐색")
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    settings = load_settings()
    depts = load_dept_list(PROJECT_ROOT / "config" / "dept_list.yaml")
    if not depts:
        raise SystemExit("config/dept_list.yaml이 없습니다. 먼저 python -m scripts.collect_dept_list")
    registered = {s.id for s in SourceRegistry.load(*settings.sources.registry_paths).all()}
    if args.all:
        targets = [d for d in depts.values() if d.platform == args.type]
    else:
        unknown = [i for i in args.ids if i not in depts]
        if unknown:
            raise SystemExit(f"dept_list.yaml에 없는 ID: {', '.join(unknown)}")
        targets = [depts[i] for i in args.ids]
    if not targets:
        raise SystemExit("탐색할 사이트를 지정하세요 (ID 또는 --all)")

    c = settings.crawler
    http = HttpClient(c.user_agent, min_interval=c.min_interval, timeout=c.timeout, retries=c.retries)
    DRAFTS.mkdir(parents=True, exist_ok=True)
    for dept in targets:
        out = DRAFTS / f"{dept.id}.yaml"
        if not args.force and (out.exists() or dept.id in registered):
            log.info("건너뜀 %s (초안 있음/등록됨, --force로 다시)", dept.id)
            continue
        if not dept.homepage:
            log.info("건너뜀 %s (홈페이지 없음)", dept.id)
            continue
        log.info("탐색 %s %s", dept.id, dept.homepage)
        try:
            found = discover(dept.homepage, http, args.max_pages)
        except FetchError as e:
            log.warning("탐색 실패 %s: %s", dept.id, e)
            continue
        out.write_text(build_draft(dept.id, dept, found, args.type), encoding="utf-8")
        log.info("초안 저장 %s (게시판 %d, 데이터 %d, 페이지 %d, 404 %d)", out.relative_to(PROJECT_ROOT),
                 len(found.sections), sum(len(v) for v in found.datasets.values()), len(found.pages), len(found.broken))


if __name__ == "__main__":
    main()
