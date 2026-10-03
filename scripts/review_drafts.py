"""초안 1차 검토 (Claude 검토 기준을 코드로) → config/sources_departments.yaml + docs/department_review.md

  .venv/Scripts/python -m scripts.review_drafts

config/drafts/*.yaml(discover_source 결과)에 아래 기준을 적용하고, config/review_overrides.yaml의 예외를 덮어쓴다.
결과 파일은 매번 다시 생성되므로 직접 고치지 말고 overrides를 고친다. 네트워크·LLM을 쓰지 않는다.

기준
- 게시판: 커뮤니티성(학생회·동문·자유게시판·Q&A)·사진·글 3건 미만(공지 제외) 게시판은 뺀다.
  역할을 못 정한 게시판은 보강 규칙(워크숍·세미나 → activity 등)으로 다시 정하고, 그래도 모르면 빼고 보고한다.
  같은 역할 게시판이 둘 이상이면 모두 남기되, 글 수가 같고 제목이 비슷하면 same_as로 묶는다(같은 글을 공유하는 게시판).
- 안내 페이지: 표준 종류(졸업요건·내규·장학·FAQ·오시는 길·연구실·조교·학석연계·진로·자격증·이수체계)만 표준 ID로 남긴다.
  대학원 메뉴 아래면 grad_ 접두어. 나머지(인사말·연혁·학회·연구소 소개 등)는 뺀다.
- 공개: 게시판이나 데이터가 하나라도 있으면 reviewed_at을 넣고 reviewed_by: claude로 표시한다(사람 2차 검토 대상).
  남는 게 없거나 탐색이 거의 안 된 사이트는 보류(reviewed_at: null)하고 보고서에 이유를 적는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from danbi.config import PROJECT_ROOT

DRAFTS = PROJECT_ROOT / "config" / "drafts"
OVERRIDES = PROJECT_ROOT / "config" / "review_overrides.yaml"
OUT = PROJECT_ROOT / "config" / "sources_departments.yaml"
REPORT = PROJECT_ROOT / "docs" / "department_review.md"

DROP_BOARD_WORDS = ("학생회", "동문", "자유게시판", "자유 게시판", "자유롭게", "Q&A", "Q & A", "QnA", "묻고", "질문",
                    "건의사항", "건의함", "방명록",  # '건의'만 쓰면 '보건의료'에 걸린다
                    "사진", "갤러리", "gallery", "앨범", "포토", "photo", "동아리", "club",
                    "MT", "체육대회", "새내기", "입학식", "졸업식", "답사", "소통", "의 밤", "보유장비")
EXTRA_ROLE_RULES = [  # 초안에서 역할을 못 정한 게시판에만 적용 (앞에서부터)
    ("archive", ("faq", "인증")),
    ("jobs", ("취창업", "창업", "일자리", "채용", "인턴", "현장실습", "고시", "회계사", "세무사", "구인", "career")),
    ("rules", ("졸업요건", "졸업")),
    ("activity", ("워크숍", "세미나", "특강", "학회", "행사", "소식", "뉴스", "이벤트", "공모", "동정", "튜터링",
                  "홍보", "실습", "전시")),
    ("archive", ("서식", "양식", "자료")),
    ("notice", ("학사", "알림", "안내", "news", "notice")),
]
MIN_POSTS = 3
SAME_AS_TITLE_RATIO = 0.6  # '임용자료'·'원전자료'(0.5)처럼 글 수만 우연히 같은 게시판을 묶지 않게
PAGE_KEEP = [  # (표준 ID, 제목 키워드)
    ("graduation", ("졸업요건", "졸업 요건", "졸업기준", "졸업 기준", "졸업인증", "졸업 안내", "졸업안내")),
    ("rules", ("내규", "규정", "규칙", "지침")),
    ("scholarship", ("장학",)),
    ("faq", ("faq", "자주 묻는", "자주묻는")),
    ("location", ("오시는", "찾아오시는", "찾아오는", "위치", "location")),
    ("labs", ("연구실",)),
    ("staff", ("조교", "교직원", "행정실")),
    ("bs_ms", ("학석", "학·석", "학석사", "연계과정")),
    ("career", ("진로", "취업 안내", "취업안내")),
    ("certificate", ("자격증", "자격 ")),
    ("curriculum_guide", ("이수체계", "로드맵", "이수 안내", "이수안내", "전공 안내", "교과과정 안내")),
]
PAGE_SKIP_WORDS = ("연구소", "학회", "인사말", "연혁")  # 키워드가 겹쳐도 남기지 않는 페이지 (예: '연구소 규정')
MIN_PAGE_CHARS = 100
# 확실히 쓰이는 줄임말만 (학과명 → 별칭)
KNOWN_ALIASES = {
    "컴퓨터공학과": ["컴공", "컴퓨터공학"], "국어국문학과": ["국문과"], "정치외교학과": ["정외과"],
    "전자전기공학부": ["전전"], "기계공학과": ["기계과"], "경영학부": ["경영"], "경제학과": ["경제"],
    "행정학과": ["행정"], "통계데이터사이언스학과": ["통계"], "사이버보안학과": ["사이버보안"], "법학과": ["법대", "법학"],
}
DATASET_LABEL = {"professors": "교수", "curriculum": "교과과정", "dept_info": "학과 소개"}

_LINE = re.compile(r'^\s{4}(\S+): \{ title: (".*?"), path: (".*?") \}(?:\s+# (.*))?$')


@dataclass
class Item:
    id: str
    title: str
    path: str
    count: int | None = None   # 게시판 글 수
    chars: int | None = None   # 페이지 글자 수
    area: str = ""             # 메뉴 최상위


@dataclass
class Result:
    sid: str
    entry: dict
    published: bool
    hold_reason: str = ""
    kept_sections: list[str] = field(default_factory=list)
    dropped_sections: list[str] = field(default_factory=list)
    kept_pages: list[str] = field(default_factory=list)
    dropped_pages: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    peek: list[tuple[str, str]] = field(default_factory=list)  # (제목, 경로) 최신 글 제목을 확인할 게시판
    peeked: dict[str, list[str]] = field(default_factory=dict)
    draft_paths: set[str] = field(default_factory=set)  # 초안에 있던 게시판 경로


def parse_draft(text: str) -> tuple[str, dict, dict[str, list[Item]]]:
    """초안 YAML + 줄 끝 주석(글 수·글자 수·메뉴)을 읽는다."""
    data = yaml.safe_load(text)
    sid, entry = next(iter(data.items()))
    items: dict[str, list[Item]] = {"sections": [], "pages": []}
    block = None
    for line in text.splitlines():
        if re.match(r"^\s{2}(sections|pages):\s*$", line):
            block = line.strip()[:-1]
            continue
        if re.match(r"^\s{2}\S", line):
            block = None
        m = _LINE.match(line)
        if block and m:
            note = m.group(4) or ""
            cnt = re.search(r"([\d,]+)건", note)
            chars = re.search(r"([\d,]+)자", note)
            area = re.search(r"메뉴: (.+?)(?: \[|$)", note)
            items[block].append(Item(
                id=m.group(1), title=json.loads(m.group(2)), path=json.loads(m.group(3)),
                count=int(cnt.group(1).replace(",", "")) if cnt else None,
                chars=int(chars.group(1).replace(",", "")) if chars else None,
                area=area.group(1).strip() if area else "",
            ))
    return str(sid), entry, items


def _role_of(item: Item) -> str:
    return item.id.split("_", 1)[0]


def _guess(rules, title: str) -> str | None:
    t = title.lower()
    return next((r for r, words in rules if any(w.lower() in t for w in words)), None)


def review(sid: str, entry: dict, items: dict[str, list[Item]], overrides: dict, today: date) -> Result:
    ov = overrides.get(sid) or {}
    res = Result(sid, {}, False)
    res.draft_paths = {it.path for it in items["sections"]}

    # --- 게시판 ---
    chosen: list[tuple[str, Item]] = []
    for it in items["sections"]:
        role = (ov.get("roles") or {}).get(it.path) or _role_of(it)
        why = ""
        if role == "drop":
            why = "overrides"
        elif role == "ignore" or any(w.lower() in it.title.lower() for w in DROP_BOARD_WORDS):
            why = "커뮤니티·사진"
        elif it.count == 0 or (role != "notice" and it.count is not None and it.count < MIN_POSTS):
            why = f"글 {it.count}건"
        elif role == "review":
            role = _guess(EXTRA_ROLE_RULES, it.title) or "review"
            if role == "review":
                why = "역할 불명"
                res.flags.append(f"역할 불명 게시판 제외: {it.title} ({it.path}, {it.count}건) — 필요하면 overrides roles에 역할 지정")
                if (it.count or 0) >= 10:
                    res.peek.append((it.title, it.path))
        if why:
            res.dropped_sections.append(f"{it.title} ({why})")
            continue
        chosen.append((role, it))

    sections: dict[str, dict] = {}
    by_role: dict[str, list[tuple[str, Item]]] = {}
    for role, it in chosen:
        n = len(by_role.setdefault(role, [])) + 1
        sec_id = role if n == 1 else f"{role}_{n}"
        spec = {"title": it.title, "path": it.path}
        first = by_role[role][0] if by_role[role] else None
        if (first and first[1].count is not None and first[1].count == it.count
                and SequenceMatcher(None, first[1].title, it.title).ratio() >= SAME_AS_TITLE_RATIO):
            spec["same_as"] = first[0]  # 글 수가 같고 제목이 비슷하면 같은 글을 공유하는 게시판으로 본다
            res.flags.append(f"same_as 추정: {it.title} = {first[1].title} ({it.count}건)")
        by_role[role].append((sec_id, it))
        sections[sec_id] = spec
        res.kept_sections.append(f"{sec_id}: {it.title}" + (f" ({it.count:,}건)" if it.count is not None else ""))
    if "notice" not in {r for r, _ in chosen}:
        res.flags.append("학과 공지(notice) 게시판 없음")

    # --- 데이터 ---
    datasets = entry.get("datasets") or {}
    for kind, entries in datasets.items():
        for e in entries:
            if "p_p_id" in e.get("path", ""):
                res.flags.append(f"{kind} 경로에 포틀릿 파라미터가 섞임: {e['path'][:60]}… (동작은 함, 정리 권장)")

    # --- 안내 페이지 ---
    pages: dict[str, dict] = {}
    keep_paths = set(ov.get("keep_pages") or [])
    for it in items["pages"]:
        pid = _guess(PAGE_KEEP, it.title)
        skip = any(w in it.title for w in PAGE_SKIP_WORDS) and it.path not in keep_paths
        if it.path in keep_paths and not pid:
            pid = (ov.get("page_ids") or {}).get(it.path) or "info"
        if not pid or skip or (it.chars is not None and it.chars < MIN_PAGE_CHARS and it.path not in keep_paths):
            res.dropped_pages.append(it.title)
            continue
        if "대학원" in it.area or "대학원" in it.title:
            pid = f"grad_{pid}"
        base, n = pid, 2
        while pid in pages:
            pid, n = f"{base}_{n}", n + 1
        pages[pid] = {"title": it.title, "path": it.path}
        res.kept_pages.append(f"{pid}: {it.title}")

    # --- 기본 정보 ---
    name = entry["name"]
    aliases = list(dict.fromkeys([*entry.get("aliases", []), *KNOWN_ALIASES.get(name, []),
                                  *(ov.get("aliases") or [])]))
    stripped = re.sub(r"(과|부|전공)$", "", name)  # 컴퓨터공학과 → 컴퓨터공학, 행정학과 → 행정학
    if stripped != name and len(stripped) >= 2 and "·" not in name:
        aliases.append(stripped)
    aliases = [a for a in dict.fromkeys(aliases) if a != name]

    parts = [s["title"] for s in sections.values()] + [DATASET_LABEL.get(k, k) for k in datasets] + [p["title"] for p in pages.values()]
    campus = entry.get("campus")
    description = ov.get("description") or (f"{name}" + (f"({campus})" if campus else "") + " " + "·".join(dict.fromkeys(parts)))

    if ov.get("hold"):
        res.hold_reason = f"overrides: {ov['hold']}"
    elif not sections and not datasets:
        res.hold_reason = "남은 게시판·데이터 없음"
    res.published = not res.hold_reason

    out = {
        "type": entry["type"], "kind": entry.get("kind", "department"), "name": name,
        "college": entry.get("college"), "aliases": aliases, "campus": campus,
        "office": entry.get("office") or {}, "base_url": entry["base_url"], "description": description,
    }
    if sections:
        out["sections"] = sections
    if datasets:
        out["datasets"] = datasets
    if pages:
        out["pages"] = pages
    out["freshness"] = "realtime"
    out["reviewed_at"] = today if res.published else None
    out["reviewed_by"] = "claude"
    res.entry = out
    return res


class _NoAliasDumper(yaml.SafeDumper):
    """같은 date 객체를 여러 번 써도 &id001 앵커 대신 값을 그대로 쓴다 (사람이 읽는 파일)."""

    def ignore_aliases(self, data):
        return True


def write_outputs(results: list[Result], out_path: Path, report_path: Path, today: date) -> None:
    pub = [r for r in results if r.published]
    header = (
        f"# 학과 일괄 등록 — scripts/review_drafts.py가 {today} 생성 (초안 + config/review_overrides.yaml).\n"
        "# 직접 고치지 말고 overrides를 고친 뒤 다시 생성한다. reviewed_by: claude = Claude 1차 검토, 사람 2차 검토 대상.\n"
        f"# 공개 {len(pub)}개 · 보류 {len(results) - len(pub)}개 (보류 = reviewed_at: null, 검색에 쓰지 않음)\n\n"
    )
    body = {r.sid: r.entry for r in sorted(results, key=lambda r: (r.entry.get("campus") or "", r.sid))}
    out_path.write_text(header + yaml.dump(body, Dumper=_NoAliasDumper, allow_unicode=True, sort_keys=False, width=200,
                                           default_flow_style=None), encoding="utf-8")

    lines = [f"# 학과 소스 1차 검토 보고서 ({today})", "",
             "Claude가 `scripts/review_drafts.py` 기준으로 1차 검토한 결과. 사람 2차 검토 때 **확인 필요** 항목부터 본다.",
             "수정은 `config/review_overrides.yaml`에 적고 `python -m scripts.review_drafts`로 다시 생성한다.", "",
             f"- 공개 {len(pub)}개 · 보류 {len(results) - len(pub)}개", ""]
    held = [r for r in results if not r.published]
    if held:
        lines += ["## 보류", *(f"- {r.sid} {r.entry['name']}: {r.hold_reason}" for r in held), ""]
    flagged = [r for r in results if r.flags]
    if flagged:
        lines.append("## 확인 필요")
        for r in flagged:
            lines.append(f"- **{r.sid}** {r.entry['name']}")
            lines += [f"  - {f}" for f in r.flags]
            for title, path in r.peek:
                if path in r.peeked:
                    lines.append(f"  - 최신 글 ({title}): " + " / ".join(r.peeked[path]))
        lines.append("")
    lines.append("## 학과별 상세")
    for r in sorted(results, key=lambda r: (r.entry.get("campus") or "", r.sid)):
        status = "공개" if r.published else "보류"
        lines.append(f"### {r.sid} {r.entry['name']} ({r.entry.get('campus') or '?'}, {status})")
        lines.append(f"- 게시판: {', '.join(r.kept_sections) or '없음'}")
        if r.dropped_sections:
            lines.append(f"- 뺀 게시판: {', '.join(r.dropped_sections)}")
        lines.append(f"- 데이터: {', '.join(r.entry.get('datasets', {})) or '없음'}")
        lines.append(f"- 페이지: {', '.join(r.kept_pages) or '없음'}")
        if r.dropped_pages:
            lines.append(f"- 뺀 페이지: {', '.join(r.dropped_pages)}")
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def check_notice_links(base_url: str, http, draft_paths: set[str] | frozenset = frozenset()) -> list[str]:
    """공지 게시판이 없는 학과: 홈 메뉴의 '공지' 링크를 열어 이유를 확인한다 (비공개/탐색 누락/링크 없음)."""
    from urllib.parse import unquote, urljoin

    from bs4 import BeautifulSoup

    from danbi.crawler.http import FetchError
    from scripts.discover_source import is_denied_board

    soup = BeautifulSoup(http.get(base_url).text, "lxml")
    scope = unquote(base_url.split("://", 1)[1].split("/", 1)[1])
    links = []
    for a in soup.select("a[href]"):
        url = urljoin(base_url, a["href"]).split("#")[0]
        if ("공지" in a.get_text() or "notice" in url.lower()) and "?" not in url and scope in unquote(url) and url not in links:
            links.append(url)
    if not links:
        return ["→ 홈 메뉴에 공지 링크 없음 (학과 공지를 사이트에 따로 두지 않음)"]
    notes = []
    for url in links[:3]:
        path = "/" + unquote(url.split("://", 1)[1].split("/", 1)[1])
        try:
            main = BeautifulSoup(http.get(url).text, "lxml").select_one("#main-content")
        except FetchError as e:
            notes.append(f"→ 공지 링크 열기 실패: {path} ({e})")
            continue
        if main is not None and is_denied_board(main):
            notes.append(f"→ 공지 게시판 비공개(로그인 필요, 접근 거부): {path} — 등록 불가")
        elif main is not None and main.select_one(".dku-list-body") and path in draft_paths:
            notes.append(f"→ 공지 게시판은 초안에 있었지만 1차 검토에서 뺌 (글 수 부족 등): {path}")
        elif main is not None and main.select_one(".dku-list-body"):
            notes.append(f"→ 공지 게시판이 탐색에서 빠짐: {path} — overrides에 추가하거나 재탐색")
        else:
            text = main.get_text(" ", strip=True)[:30] if main is not None else ""
            notes.append(f"→ 공지 링크가 게시판이 아님: {path} (내용: {text or '비어 있음'})")
    return notes


def peek_titles(results: list[Result]) -> None:
    from danbi.config import load_settings
    from danbi.crawler.adapters.dku_cms import parse_list
    from danbi.crawler.http import FetchError, HttpClient

    c = load_settings().crawler
    http = HttpClient(c.user_agent, min_interval=c.min_interval, timeout=c.timeout, retries=c.retries)
    for r in results:
        origin = r.entry["base_url"].split("/web/")[0]
        if "학과 공지(notice) 게시판 없음" in r.flags:
            r.flags.extend(check_notice_links(r.entry["base_url"], http, r.draft_paths))
        for _, path in r.peek:
            try:
                page = parse_list(http.get(origin + path).text, origin + path)
                r.peeked[path] = [f"{i.title} ({i.date})" for i in page.items[:5]]
            except (FetchError, ValueError) as e:
                r.peeked[path] = [f"(확인 실패: {e})"]


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="초안 1차 검토 → sources_departments.yaml + 보고서")
    ap.add_argument("--peek", action="store_true",
                    help="역할 불명 게시판의 최신 글 제목 5개를 가져와 보고서에 붙인다 (학교 사이트 요청)")
    args = ap.parse_args()
    today = date.today()
    overrides = yaml.safe_load(OVERRIDES.read_text(encoding="utf-8")) if OVERRIDES.exists() else {}
    results = []
    for f in sorted(DRAFTS.glob("*.yaml")):
        sid, entry, items = parse_draft(f.read_text(encoding="utf-8"))
        results.append(review(sid, entry, items, overrides or {}, today))
    if args.peek:
        peek_titles(results)
    write_outputs(results, OUT, REPORT, today)
    print(f"공개 {sum(r.published for r in results)} · 보류 {sum(not r.published for r in results)} · "
          f"확인 필요 {sum(bool(r.flags) for r in results)} → {OUT.relative_to(PROJECT_ROOT)}, {REPORT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
