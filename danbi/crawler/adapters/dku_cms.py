"""cms.dankook.ac.kr (Liferay) 어댑터. 사이트 구조: docs/DANBI_DESIGN.md §9.2

학과 사이트와 메인 사이트(www.dankook.ac.kr/web/kor)의 게시판 포틀릿(dku_bbs_web_BbsPortlet)을 다룬다.
파싱 함수(parse_list, parse_item)는 HTML만 받으므로 저장해 둔 샘플로 회귀 테스트한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from ...sources.models import Section, Source
from ..cache import TTL_ITEM, TTL_LIST, TTL_MENU, TTL_PAGE, TTL_SEARCH, Cache
from ..extract.html import clean_text, html_to_md
from ..http import HttpClient
from .base import MAX_ATTACHMENT_BYTES, Attachment, Item, ItemSummary, ListPage, PageDoc, SiteAdapter

BBS = "_dku_bbs_web_BbsPortlet_"
_BASE_QUERY = "?p_p_id=dku_bbs_web_BbsPortlet&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
LIST_QUERY = _BASE_QUERY + f"&{BBS}action=view&{BBS}cur={{page}}&{BBS}orderBy=createDate"
SEARCH_QUERY = _BASE_QUERY + f"&{BBS}action=view&{BBS}cur={{page}}&{BBS}sKeyType={{field}}&{BBS}sKeyword={{keyword}}"
VIEW_QUERY = _BASE_QUERY + f"&{BBS}action=view_message&{BBS}bbsMessageId={{item_id}}"

SEARCH_FIELDS = ("title", "content", "writer")
_DEFAULT_COLUMNS = ["번호", "제목", "작성자", "작성일", "조회수", "파일첨부"]


def item_url(section_url: str, item_id: int) -> str:
    return section_url + VIEW_QUERY.format(item_id=item_id)


def parse_list(html: str, section_url: str) -> ListPage:
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one("#main-content")
    if main is None or main.select_one(".dku-list-body") is None:
        raise ValueError("게시판 목록 구조를 찾을 수 없습니다 (.dku-list-body)")

    header = main.select_one(".dku-list-header")
    header_text = header.get_text(" ") if header else ""
    m_total = re.search(r"전체\s*([\d,]+)\s*건", header_text)
    m_pages = re.search(r"페이지\s*(\d+)\s*/\s*(\d+)", header_text)

    rows = main.select(".dku-list-body .dku-list-body-item")
    columns = _DEFAULT_COLUMNS
    head_row = next((r for r in rows if "header" in (r.get("class") or [])), None)
    if head_row is not None:
        columns = [clean_text(c.get_text()) for c in head_row.select(".dku-list-body-item-col")]

    def col(cells, name):
        i = columns.index(name) if name in columns else -1
        return cells[i] if 0 <= i < len(cells) else None

    items = []
    for row in rows:
        if row is head_row:
            continue
        a = row.select_one("a[onclick]")
        m = re.search(r"viewMessage\((\d+)", a.get("onclick", "")) if a else None
        if not m:
            continue
        item_id = int(m.group(1))
        cells = row.select(".dku-list-body-item-col")
        title = clean_text(a.get("title") or a.get_text())  # 제목 칸에는 'H' 같은 표시가 섞여 있어 title 속성을 쓴다
        number = col(cells, "번호")
        author = col(cells, "작성자")
        date = col(cells, "작성일")
        attach = col(cells, "파일첨부") or col(cells, "첨부")
        items.append(ItemSummary(
            id=item_id,
            title=title,
            date=clean_text(date.get_text()) if date else "",
            url=item_url(section_url, item_id),
            author=clean_text(author.get_text()) if author else None,
            has_attachment=bool(attach and attach.find("img")),
            closed=title.startswith("[마감]"),
            pinned=bool(number) and not clean_text(number.get_text()).isdigit(),
        ))
    return ListPage(
        items=items,
        total_count=int(m_total.group(1).replace(",", "")) if m_total else len(items),
        page=int(m_pages.group(1)) if m_pages else 1,
        total_pages=int(m_pages.group(2)) if m_pages else 1,
    )


def parse_item(html: str, url: str, item_id: int) -> Item:
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one("#main-content")
    table = main.select_one("table") if main else None
    if table is None:
        raise ValueError("게시글 구조를 찾을 수 없습니다 (#main-content table)")

    title_th = table.select_one("tr th[colspan]") or table.select_one("tr th")
    meta: dict[str, str] = {}
    attachments: list[Attachment] = []
    for tr in table.select(":scope > tbody > tr, :scope > tr"):  # 본문 안의 표는 건너뛴다
        th, td = tr.find("th", recursive=False), tr.find("td", recursive=False)
        if not th or not td:
            continue
        label = clean_text(th.get_text(" ")).split()[-1]  # 아이콘 텍스트(person_book 등) 제거
        if label == "파일첨부":
            attachments += [Attachment(clean_text(a.get_text()), urljoin(url, a["href"])) for a in td.select("a[href]")]
        else:
            meta[label] = clean_text(td.get_text(" "))

    posted, modified = meta.get("날짜", ""), None
    m = re.search(r"\(\s*수정일\s*:\s*([\d.]+)\s*\)", posted)
    if m:
        modified = m.group(1)
        posted = posted[: m.start()].strip()
    body = table.select_one("td.r_cont .content-wrap") or table.select_one("td.r_cont")
    return Item(
        id=item_id,
        title=clean_text(title_th.get_text(" ")) if title_th else "",
        url=url,
        posted_at=posted or None,
        modified_at=modified,
        author=meta.get("작성자"),
        body_md=html_to_md(body) if body else "",
        attachments=attachments,
    )


def parse_page(html: str, url: str) -> PageDoc:
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one("#main-content")
    if main is None:
        raise ValueError("본문 영역을 찾을 수 없습니다 (#main-content)")
    title = soup.title.get_text(strip=True).split(" - ")[0] if soup.title else ""
    return PageDoc(title=title, url=url, body_md=html_to_md(main))


def _portlet_json(html: str, suffix: str):
    soup = BeautifulSoup(html, "lxml")
    found = []
    for sc in soup.select('#main-content script[type="application/json"]'):
        if sc.get("id", "").endswith(suffix):
            try:
                data = json.loads(sc.string or "null")
            except json.JSONDecodeError:
                continue
            if data:
                found.append(data)
    return found


def _crlf(s) -> str:
    return (s or "").replace("\r\n", "\n").replace("\r", "\n").strip() if isinstance(s, str) else ""


_SEM_FLAGS = [
    ("fstFst", "1-1"), ("fstScnd", "1-2"), ("scndFst", "2-1"), ("scndScnd", "2-2"),
    ("thrdFst", "3-1"), ("thrdScnd", "3-2"), ("frthFst", "4-1"), ("frthScnd", "4-2"),
    ("ffthFst", "5-1"), ("ffthScnd", "5-2"), ("sxthFst", "6-1"), ("sxthScnd", "6-2"),
]
_PROGRAMS = {"cmm": "정규 교과과정", "mod": "모듈형 교육과정", "mic": "마이크로전공", "trk": "트랙 교육과정", "ext": "비교과"}
_DEPT_SECTIONS = [
    ("introCont", "학과 소개"), ("eduGoalCont", "교육 목표"), ("careerCont", "졸업 후 진로"),
    ("aptitCont", "적성"), ("speclPgmCont", "특성화 프로그램"), ("almCont", "동문"), ("excCont", "기타"),
]
_DEPT_CONTACT = [("roomNm", "학과 사무실"), ("telNo", "전화"), ("faxNo", "팩스"), ("hpUrl", "홈페이지")]


def parse_dataset(html: str, kind: str, org: str | None = None) -> list[dict]:
    """데이터 페이지의 JSON → 공통 레코드 (base.py 주석의 키)."""
    if kind == "professors":
        records = []
        for data in _portlet_json(html, "professorsData"):
            for p in data:
                records.append({
                    "name": p.get("nm") or "", "eng_name": p.get("egNm") or "",
                    "position": p.get("wkgrKnm") or "", "role": p.get("repnPosn") or "",
                    "org": p.get("orgzNm") or "", "office": p.get("buildingLoc") or "",
                    "tel": p.get("telNo") or "", "email": p.get("eml") or "",
                    "homepage": p.get("hpAddr") or "", "detail_url": p.get("detailUrl") or "",
                    "education": [clean_text(" ".join(str(v) for v in e.values() if isinstance(v, str)))
                                  for e in p.get("educations") or []],
                })
        return records
    if kind == "curriculum":
        records = []
        for data in _portlet_json(html, "curriculumsByTypeData"):
            for prog_key, groups in data.items():
                for g in groups or []:
                    for c in g.get("curriculums") or []:
                        records.append({
                            "org": org or c.get("orgAnm") or "",
                            "program": _PROGRAMS.get(prog_key, prog_key),
                            "group": g.get("keyName") or "",
                            "category": c.get("curiCparNm") or "",
                            "name": c.get("subjNm") or "", "eng_name": c.get("subjEnm") or "",
                            "credit": c.get("crd") or "",
                            "semesters": [lbl for k, lbl in _SEM_FLAGS if str(c.get(k, "0")) not in ("0", "", "None")],
                            "summary": clean_text(c.get("subjSmryKnm") or c.get("subjSmryEnm")),
                            "year": c.get("yy") or "",
                        })
        return records
    if kind == "menu":
        records = []
        for data in _portlet_json(html, "menusData"):
            for corner in data:
                for m in corner.get("menus") or []:
                    records.append({
                        "org": org or "", "corner": m.get("corner") or corner.get("corner") or "",
                        "name": m.get("alias") or "", "price": m.get("price"), "sold_out": bool(m.get("isSoldOut")),
                    })
        return records
    if kind == "dept_info":
        records = []
        for d in _portlet_json(html, "deptData"):
            records.append({
                "name": d.get("orgzNm") or "",
                "updated": d.get("ltstUpdDm") or "",
                "sections": {label: _crlf(d.get(k)) for k, label in _DEPT_SECTIONS if _crlf(d.get(k))},
                "contact": {label: d[k] for k, label in _DEPT_CONTACT if d.get(k)},
            })
        return records
    raise ValueError(f"알 수 없는 데이터셋 종류: {kind}")


KST = timezone(timedelta(hours=9))
CALENDAR_REST = "/o/dku_calendar-rest/calendar/events/{group}/{start}/{end}"
PORTAL_CALENDAR_GROUP = "0"  # 포털 공통 달력 (학교 학사일정이 여기에 있다)


def academic_year(today: date) -> int:
    """학년도: 3월 1일 ~ 다음 해 2월 말. 1·2월은 전년도 학년도."""
    return today.year if today.month >= 3 else today.year - 1


def academic_year_range_ms(year: int) -> tuple[int, int]:
    start = datetime(year, 3, 1, tzinfo=KST)
    end = datetime(year + 1, 3, 1, tzinfo=KST) - timedelta(milliseconds=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def calendar_group_id(html: str) -> str | None:
    m = re.search(r"getScopeGroupId[^0-9]{0,40}(\d+)", html)
    return m.group(1) if m else None


def parse_calendar_events(payload: dict) -> list[dict]:
    """달력 REST 응답 → calendar 레코드 (시작일 순)."""
    if not payload or not payload.get("status"):
        raise ValueError("학사일정 응답이 올바르지 않습니다")
    out = []
    for ev in payload.get("data") or []:
        try:
            start = datetime.fromtimestamp(int(ev["startTime"]) / 1000, KST).date()
            end = datetime.fromtimestamp(int(ev["endTime"]) / 1000, KST).date()
        except (KeyError, ValueError, TypeError):
            continue
        out.append({"title": clean_text(ev.get("title")), "start": start.isoformat(), "end": end.isoformat(),
                    "calendar": ev.get("calendar") or ""})
    return sorted(out, key=lambda r: (r["start"], r["end"], r["title"]))


def _list_from_dict(d: dict) -> ListPage:
    return ListPage(**{**d, "items": [ItemSummary(**i) for i in d["items"]]})


def _item_from_dict(d: dict) -> Item:
    return Item(**{**d, "attachments": [Attachment(**a) for a in d["attachments"]]})


class DkuCmsAdapter(SiteAdapter):
    supports = {"search", "list", "get_item", "get_page", "get_dataset", "get_attachment"}

    def __init__(self, source: Source, http: HttpClient, cache: Cache,
                 snapshots: dict[str, list[dict]] | None = None):
        super().__init__(source)
        self.http = http
        self.cache = cache
        self.snapshots = snapshots or {}

    def _list_page(self, url: str, section_url: str, ttl: float) -> ListPage:
        key = f"dku_cms:list:{url}"
        if (hit := self.cache.get(key)) is not None:
            return _list_from_dict(hit)
        result = parse_list(self.http.get(url).text, section_url)
        self.cache.set(key, asdict(result), ttl)
        return result

    def search(self, section: Section, keyword: str, field: str = "title", page: int = 1) -> ListPage:
        if field not in SEARCH_FIELDS:
            raise ValueError(f"field는 {', '.join(SEARCH_FIELDS)} 중 하나여야 합니다")
        section_url = self.source.url(section.path)
        url = section_url + SEARCH_QUERY.format(page=page, field=field, keyword=quote(keyword))
        return self._list_page(url, section_url, TTL_SEARCH)

    def list(self, section: Section, page: int = 1) -> ListPage:
        section_url = self.source.url(section.path)
        return self._list_page(section_url + LIST_QUERY.format(page=page), section_url, TTL_LIST)

    def get_item(self, section: Section, item_id: int) -> Item:
        url = item_url(self.source.url(section.path), item_id)
        key = f"dku_cms:item:{url}"
        if (hit := self.cache.get(key)) is not None:
            return _item_from_dict(hit)
        item = parse_item(self.http.get(url).text, url, item_id)
        self.cache.set(key, asdict(item), TTL_ITEM)
        return item

    def get_page(self, path: str) -> PageDoc:
        url = self.source.url(path)
        key = f"dku_cms:page:{url}"
        if (hit := self.cache.get(key)) is not None:
            return PageDoc(**hit)
        page = parse_page(self.http.get(url).text, url)
        self.cache.set(key, asdict(page), TTL_PAGE)
        return page

    def get_dataset(self, kind: str, path: str, org: str | None = None) -> list[dict]:
        if kind in self.snapshots:  # 미리 모아 둔 스냅숏 (캠퍼스맵: 건물마다 요청해야 해서 질문할 때 부르기엔 느리다)
            return [r for r in self.snapshots[kind] if not org or r.get("org") == org]
        url = self.source.url(path)
        key = f"dku_cms:dataset:{kind}:{org}:{url}"
        if (hit := self.cache.get(key)) is not None:
            return hit
        if kind == "calendar":
            records, ttl = self._calendar(url), TTL_PAGE
        else:
            # 학식은 품절 표시가 실시간으로 바뀌므로 짧게 캐시한다
            records, ttl = parse_dataset(self.http.get(url).text, kind, org), (TTL_MENU if kind == "menu" else TTL_PAGE)
        self.cache.set(key, records, ttl)
        return records

    def _calendar(self, page_url: str) -> list[dict]:
        """학사일정 페이지가 브라우저에서 부르는 달력 REST를 그대로 부른다 (올해 학년도, 학교·포털 달력)."""
        group = calendar_group_id(self.http.get(page_url).text)
        start, end = academic_year_range_ms(academic_year(datetime.now(KST).date()))
        records: list[dict] = []
        for g in dict.fromkeys(x for x in (group, PORTAL_CALENDAR_GROUP) if x):
            payload = self.http.get(self.source.origin + CALENDAR_REST.format(group=g, start=start, end=end)).json()
            records += parse_calendar_events(payload)
        unique = {(r["title"], r["start"], r["end"]): r for r in records}
        return sorted(unique.values(), key=lambda r: (r["start"], r["end"], r["title"]))

    def get_attachment(self, url: str) -> bytes:
        if urlparse(url).netloc != urlparse(self.source.origin).netloc:
            raise ValueError(f"소스 사이트 밖의 첨부 주소입니다: {url}")
        data = self.http.get(url).content
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"첨부파일이 너무 큽니다 ({len(data) // 1024 // 1024}MB)")
        return data
