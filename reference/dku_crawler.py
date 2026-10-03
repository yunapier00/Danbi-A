"""단국대학교 학과 홈페이지(cms.dankook.ac.kr, Liferay 기반) 크롤러.

시작 URL 하위 경로의 페이지를 BFS로 탐색하며 세 종류의 페이지를 처리한다.
  - 게시판(BBS): 목록을 페이지 단위로 넘기며 게시글 상세를 수집
  - JSON 포틀릿: 학과소개/교수소개/교과과정처럼 데이터가 <script type="application/json">에 들어있는 페이지
  - 일반 페이지: #main-content 본문을 마크다운으로 변환

사용 예:
  python crawler/dku_crawler.py https://cms.dankook.ac.kr/web/mobilesystems --max-board-pages 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Comment
from markdownify import markdownify

log = logging.getLogger("dku_crawler")

USER_AGENT = "DanbiX-Crawler/0.1 (Dankook AI assistant prototype)"
BBS = "_dku_bbs_web_BbsPortlet_"
BBS_LIST_QUERY = (
    "?p_p_id=dku_bbs_web_BbsPortlet&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
    f"&{BBS}cur={{page}}&{BBS}action=view&{BBS}orderBy=createDate"
)
BBS_VIEW_QUERY = (
    "?p_p_id=dku_bbs_web_BbsPortlet&p_p_lifecycle=0"
    f"&{BBS}action=view_message&{BBS}bbsMessageId={{msg_id}}"
)


@dataclass
class Document:
    url: str
    doc_type: str  # page | board_post | data_page
    title: str
    content_md: str
    site: str
    breadcrumbs: list[str] = field(default_factory=list)
    board: str | None = None
    post_id: int | None = None
    author: str | None = None
    posted_at: str | None = None
    modified_at: str | None = None
    attachments: list[dict] = field(default_factory=list)
    crawled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def doc_id(self) -> str:
        if self.post_id is not None:
            return f"{self.site}-post-{self.post_id}"
        return f"{self.site}-{hashlib.sha1(self.url.encode()).hexdigest()[:12]}"


# ---------------------------------------------------------------------------
# HTML -> Markdown helpers
# ---------------------------------------------------------------------------

def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def html_to_md(el) -> str:
    """본문 요소를 마크다운으로 변환. 한글(HWP) 붙여넣기 시 섞여 들어오는 주석/스타일을 제거한다."""
    el = BeautifulSoup(str(el), "lxml")
    for c in el.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for t in el(["script", "style", "noscript", "link", "button", "form", "select", "input"]):
        t.decompose()
    md = markdownify(str(el), heading_style="ATX", strip=["img"])
    md = md.replace("\xa0", " ")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


# ---------------------------------------------------------------------------
# JSON 포틀릿 포맷터 (학과소개 / 교수소개 / 교과과정)
# ---------------------------------------------------------------------------

def _crlf(s: str) -> str:
    return (s or "").replace("\r\n", "\n").strip()


def format_dept(d: dict) -> str:
    if not d:
        return ""
    parts = [f"## {d.get('orgzNm', '학과 정보')}"]
    for key, label in [
        ("introCont", "학과 소개"),
        ("eduGoalCont", "교육 목표"),
        ("eduGoalEngCont", "교육 목표(영문)"),
        ("careerCont", "졸업 후 진로"),
        ("aptitCont", "적성"),
        ("almCont", "동문"),
        ("excCont", "기타"),
    ]:
        if _crlf(d.get(key)):
            parts.append(f"### {label}\n{_crlf(d[key])}")
    info = [f"- {label}: {d[key]}" for key, label in [
        ("roomNm", "학과 사무실"), ("telNo", "전화"), ("faxNo", "팩스"), ("email", "이메일"),
        ("hpAddr", "홈페이지"), ("ltstUpdDm", "정보 수정일"),
    ] if d.get(key)]
    if info:
        parts.append("### 연락처\n" + "\n".join(info))
    return "\n\n".join(parts)


def format_professors(items: list) -> str:
    lines = ["## 교수 목록"]
    for p in items:
        lines.append(f"### {p.get('nm', '')} ({p.get('wkgrKnm', '')})")
        for key, label in [
            ("egNm", "영문명"), ("repnPosn", "보직"), ("orgzNm", "소속"), ("buildingLoc", "연구실"),
            ("telNo", "전화"), ("eml", "이메일"), ("hpAddr", "홈페이지"), ("majorFld", "전공분야"),
        ]:
            if p.get(key):
                lines.append(f"- {label}: {p[key]}")
        for e in p.get("educations") or []:
            lines.append(f"- 학력: {clean_text(' '.join(str(v) for v in e.values() if isinstance(v, str)))}")
        if p.get("detailUrl"):
            lines.append(f"- 상세: {p['detailUrl']}")
    return "\n".join(lines)


_SEM_FLAGS = [
    ("fstFst", "1-1"), ("fstScnd", "1-2"), ("scndFst", "2-1"), ("scndScnd", "2-2"),
    ("thrdFst", "3-1"), ("thrdScnd", "3-2"), ("frthFst", "4-1"), ("frthScnd", "4-2"),
    ("ffthFst", "5-1"), ("ffthScnd", "5-2"), ("sxthFst", "6-1"), ("sxthScnd", "6-2"),
]
_CURRI_TYPES = {
    "cmm": "정규 교과과정", "mod": "모듈형 교육과정",
    "mic": "마이크로전공", "trk": "트랙 교육과정", "ext": "비교과",
}


def format_curriculum(data: dict) -> str:
    parts = []
    for type_key, groups in data.items():
        if not groups:
            continue
        parts.append(f"## {_CURRI_TYPES.get(type_key, type_key)}")
        for g in groups:
            parts.append(f"### {g.get('keyName', '')}")
            if _crlf(g.get("keyIntro")):
                parts.append(_crlf(g["keyIntro"]))
            rows = ["| 과목명 | 영문명 | 이수구분 | 학점 | 개설 학년-학기 | 개요 |", "|---|---|---|---|---|---|"]
            for c in g.get("curriculums") or []:
                sems = ", ".join(lbl for k, lbl in _SEM_FLAGS if str(c.get(k, "0")) not in ("0", "", "None"))
                summary = clean_text(c.get("subjSmryKnm") or c.get("subjSmryEnm") or "").replace("|", "/")
                rows.append(
                    f"| {c.get('subjNm', '')} | {c.get('subjEnm', '')} | {c.get('curiCparNm', '')} "
                    f"| {c.get('crd', '')} | {sems} | {summary} |"
                )
            parts.append("\n".join(rows))
    return "\n\n".join(parts)


def format_generic_json(data, depth: int = 0) -> str:
    """알 수 없는 포틀릿 데이터: 비어있지 않은 문자열 값만 key: value 형태로 펼친다."""
    out = []
    pad = "  " * depth
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                sub = format_generic_json(v, depth + 1)
                if sub:
                    out.append(f"{pad}- {k}:\n{sub}")
            elif v not in (None, "", 0):
                out.append(f"{pad}- {k}: {_crlf(str(v))}")
    elif isinstance(data, list):
        for item in data:
            sub = format_generic_json(item, depth)
            if sub:
                out.append(sub)
    return "\n".join(out)


def format_portlet_json(script_id: str, data) -> str:
    if script_id.endswith("professorsData"):
        return format_professors(data)
    if script_id.endswith("curriculumsByTypeData"):
        return format_curriculum(data)
    if script_id.endswith("deptData"):
        return format_dept(data)
    return format_generic_json(data)


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

class DkuCrawler:
    def __init__(self, start_url: str, out_dir: Path, *, delay: float = 1.0, max_pages: int = 200,
                 max_board_pages: int | None = 3, download_attachments: bool = False,
                 refresh: bool = False):
        self.start_url = start_url.rstrip("/")
        parsed = urlparse(self.start_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.scope_path = parsed.path  # 예: /web/mobilesystems
        self.site = parsed.path.rstrip("/").split("/")[-1]
        self.out_dir = out_dir
        self.delay = delay
        self.max_pages = max_pages
        self.max_board_pages = max_board_pages
        self.download_attachments = download_attachments
        self.refresh = refresh

        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.robots = RobotFileParser(urljoin(self.origin, "/robots.txt"))
        try:
            self.robots.read()
        except Exception as e:  # robots.txt를 못 읽어도 크롤링은 진행
            log.warning("robots.txt 읽기 실패: %s", e)
            self.robots = None

        self.visited: set[str] = set()
        self.seen_posts: set[int] = set()
        self.stats = {"pages": 0, "posts": 0, "boards": 0, "skipped_existing": 0, "errors": 0}

        (self.out_dir / "docs").mkdir(parents=True, exist_ok=True)
        (self.out_dir / "md").mkdir(parents=True, exist_ok=True)
        if download_attachments:
            (self.out_dir / "attachments").mkdir(parents=True, exist_ok=True)

    # --- HTTP -------------------------------------------------------------

    def fetch(self, url: str, retries: int = 3) -> requests.Response | None:
        if self.robots and not self.robots.can_fetch(USER_AGENT, url):
            log.info("robots.txt 차단: %s", url)
            return None
        for attempt in range(1, retries + 1):
            try:
                time.sleep(self.delay)
                r = self.session.get(url, timeout=20)
                r.raise_for_status()
                r.encoding = r.encoding or "utf-8"
                return r
            except requests.HTTPError as e:
                if e.response is not None and 400 <= e.response.status_code < 500:
                    log.warning("건너뜀 (%d): %s", e.response.status_code, url)
                    break  # 404 등 클라이언트 오류는 재시도해도 같은 결과
                log.warning("요청 실패(%d/%d) %s: %s", attempt, retries, url, e)
                time.sleep(self.delay * attempt * 2)
            except requests.RequestException as e:
                log.warning("요청 실패(%d/%d) %s: %s", attempt, retries, url, e)
                time.sleep(self.delay * attempt * 2)
        self.stats["errors"] += 1
        return None

    # --- URL handling -----------------------------------------------------

    def in_scope(self, url: str) -> bool:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or p.netloc != urlparse(self.origin).netloc:
            return False
        path = unquote(p.path)
        # 영문 번역판(/en/web/...)은 구글 번역 결과라 제외
        return path == self.scope_path or path.startswith(self.scope_path + "/")

    @staticmethod
    def page_key(url: str) -> str:
        """포틀릿 파라미터를 제거한 페이지 식별자 (같은 페이지의 정렬/페이징 링크 중복 방지)."""
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{quote(unquote(p.path))}"

    @staticmethod
    def post_id_from_url(url: str) -> int | None:
        qs = parse_qs(urlparse(url).query)
        v = qs.get(f"{BBS}bbsMessageId")
        return int(v[0]) if v and v[0].isdigit() else None

    # --- Persistence ------------------------------------------------------

    def doc_path(self, doc_id: str) -> Path:
        return self.out_dir / "docs" / f"{doc_id}.json"

    def save(self, doc: Document) -> None:
        data = asdict(doc) | {"doc_id": doc.doc_id}
        self.doc_path(doc.doc_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        header = [f"# {doc.title}", "", f"- URL: {doc.url}", f"- 유형: {doc.doc_type}"]
        if doc.breadcrumbs:
            header.append(f"- 경로: {' > '.join(doc.breadcrumbs)}")
        if doc.board:
            header.append(f"- 게시판: {doc.board}")
        if doc.posted_at:
            header.append(f"- 작성일: {doc.posted_at}" + (f" (수정일: {doc.modified_at})" if doc.modified_at else ""))
        for a in doc.attachments:
            header.append(f"- 첨부: [{a['name']}]({a['url']})")
        (self.out_dir / "md" / f"{doc.doc_id}.md").write_text(
            "\n".join(header) + "\n\n---\n\n" + doc.content_md + "\n", encoding="utf-8")

    # --- Page parsing -----------------------------------------------------

    @staticmethod
    def page_title(soup: BeautifulSoup) -> str:
        t = soup.title.get_text(strip=True) if soup.title else ""
        return t.split(" - ")[0].strip() or t

    @staticmethod
    def breadcrumbs(soup: BeautifulSoup) -> list[str]:
        # 각 단계의 현재 메뉴명은 첫 span, 같은 레벨의 형제 메뉴는 숨김 목록(.lp-breadcrumb-sibiling)에 있다
        items = soup.select("nav[id*=breadcrumbs] .lp-breadcrumb-item-inner > span:first-child")
        return [clean_text(s.get_text()) for s in items if clean_text(s.get_text())]

    def extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        links = []
        for a in soup.select("#content a[href]"):
            href = a["href"].strip()
            if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            links.append(urljoin(base_url, href))
        return links

    def parse_post(self, url: str, soup: BeautifulSoup, board: str) -> Document | None:
        main = soup.select_one("#main-content")
        table = main.select_one("table") if main else None
        if not table:
            return None
        title_th = table.select_one("tr th[colspan]")
        meta, attachments = {}, []
        for tr in table.select(":scope > tbody > tr, :scope > tr"):
            th, td = tr.find("th", recursive=False), tr.find("td", recursive=False)
            if not th or not td:
                continue
            label = clean_text(th.get_text(" ")).split()[-1]  # 아이콘 텍스트(person_book 등) 제거
            if label == "파일첨부":
                for a in td.select("a[href]"):
                    attachments.append({"name": clean_text(a.get_text()), "url": urljoin(url, a["href"])})
            else:
                meta[label] = clean_text(td.get_text(" "))
        body = table.select_one("td.r_cont .content-wrap") or table.select_one("td.r_cont")
        posted, modified = meta.get("날짜", ""), None
        m = re.search(r"\(수정일\s*:\s*([\d.]+)\)", posted)
        if m:
            modified = m.group(1)
            posted = posted[: m.start()].strip()
        return Document(
            url=url, doc_type="board_post", site=self.site,
            title=clean_text(title_th.get_text(" ")) if title_th else self.page_title(soup),
            content_md=html_to_md(body) if body else "",
            breadcrumbs=self.breadcrumbs(soup), board=board,
            post_id=self.post_id_from_url(url), author=meta.get("작성자"),
            posted_at=posted or None, modified_at=modified, attachments=attachments,
        )

    def parse_page(self, url: str, soup: BeautifulSoup) -> Document | None:
        main = soup.select_one("#main-content")
        if not main:
            return None
        sections = []
        json_scripts = main.select('script[type="application/json"]')
        for sc in json_scripts:
            try:
                data = json.loads(sc.string or "null")
            except json.JSONDecodeError:
                continue
            if data:
                text = format_portlet_json(sc.get("id", ""), data)
                if text.strip():
                    sections.append(text)
        if not sections:
            md = html_to_md(main)
            if md:
                sections.append(md)
        if not sections:
            return None
        return Document(
            url=url, doc_type="data_page" if json_scripts else "page", site=self.site,
            title=self.page_title(soup), content_md="\n\n".join(sections),
            breadcrumbs=self.breadcrumbs(soup),
        )

    # --- Board crawling ---------------------------------------------------

    @staticmethod
    def is_board_list(soup: BeautifulSoup) -> bool:
        return soup.select_one("#main-content .dku-list-body") is not None

    @staticmethod
    def board_post_ids(soup: BeautifulSoup) -> list[int]:
        ids = []
        for a in soup.select("#main-content .dku-list-body a[onclick]"):
            m = re.search(r"viewMessage\((\d+)", a["onclick"])
            if m:
                ids.append(int(m.group(1)))
        return ids

    @staticmethod
    def board_total_pages(soup: BeautifulSoup) -> int:
        header = soup.select_one("#main-content .dku-list-header")
        m = re.search(r"페이지\s*\d+\s*/\s*(\d+)", header.get_text(" ") if header else "")
        return int(m.group(1)) if m else 1

    def crawl_board(self, board_url: str, first_soup: BeautifulSoup) -> None:
        board_name = self.page_title(first_soup)
        total = self.board_total_pages(first_soup)
        limit = total if self.max_board_pages is None else min(total, self.max_board_pages)
        log.info("게시판 [%s] 전체 %d페이지 중 %d페이지 수집", board_name, total, limit)
        self.stats["boards"] += 1

        soup = first_soup
        for page in range(1, limit + 1):
            if page > 1:
                r = self.fetch(board_url + BBS_LIST_QUERY.format(page=page))
                if not r:
                    continue
                soup = BeautifulSoup(r.text, "lxml")
            for post_id in self.board_post_ids(soup):
                self.crawl_post(board_url, post_id, board_name)

    def crawl_post(self, board_url: str, post_id: int, board_name: str | None = None) -> None:
        if post_id in self.seen_posts:
            return
        self.seen_posts.add(post_id)
        doc_id = f"{self.site}-post-{post_id}"
        if not self.refresh and self.doc_path(doc_id).exists():
            self.stats["skipped_existing"] += 1
            return
        url = board_url + BBS_VIEW_QUERY.format(msg_id=post_id)
        r = self.fetch(url)
        if not r:
            return
        soup = BeautifulSoup(r.text, "lxml")
        doc = self.parse_post(url, soup, board_name or self.page_title(soup))
        if not doc:
            log.warning("게시글 파싱 실패: %s", url)
            return
        self.save(doc)
        self.stats["posts"] += 1
        log.info("  게시글 %d: %s", post_id, doc.title[:50])
        if self.download_attachments:
            self.fetch_attachments(doc)

    def fetch_attachments(self, doc: Document) -> None:
        for i, a in enumerate(doc.attachments):
            r = self.fetch(a["url"])
            if not r:
                continue
            name = re.sub(r'[\\/:*?"<>|]', "_", a["name"])
            path = self.out_dir / "attachments" / f"{doc.doc_id}_{i}_{name}"
            path.write_bytes(r.content)
            a["local_path"] = str(path)
        self.save(doc)

    # --- Main loop --------------------------------------------------------

    def run(self) -> dict:
        queue = deque([self.start_url])
        while queue and self.stats["pages"] < self.max_pages:
            url = queue.popleft()

            post_id = self.post_id_from_url(url)
            if post_id is not None:  # 메인 화면 등에 노출된 게시글 링크
                self.crawl_post(self.page_key(url), post_id)
                continue

            key = self.page_key(url)
            if key in self.visited:
                continue
            self.visited.add(key)

            r = self.fetch(key)
            if not r:
                continue
            final_key = self.page_key(r.url)  # 상위 메뉴는 첫 하위 메뉴로 리다이렉트됨
            if final_key != key and final_key in self.visited:
                continue
            self.visited.add(final_key)
            self.stats["pages"] += 1

            soup = BeautifulSoup(r.text, "lxml")
            log.info("[%d] %s (%s)", self.stats["pages"], self.page_title(soup), unquote(final_key))

            if self.is_board_list(soup):
                self.crawl_board(final_key, soup)
            elif final_key == self.page_key(self.start_url):
                pass  # 홈 화면은 최신글 목록·바로가기 링크 모음이라 문서로 저장하지 않고 링크만 따라간다
            else:
                doc = self.parse_page(final_key, soup)
                if doc:
                    self.save(doc)

            for link in self.extract_links(soup, final_key):
                if self.in_scope(link) and (self.post_id_from_url(link) or self.page_key(link) not in self.visited):
                    queue.append(link)

        self.write_index()
        return self.stats

    def write_index(self) -> None:
        """수집된 전체 문서를 한 파일(JSONL)로 합친다. DB 적재 단계의 입력으로 사용."""
        docs = sorted((self.out_dir / "docs").glob("*.json"))
        with open(self.out_dir / "documents.jsonl", "w", encoding="utf-8") as f:
            for p in docs:
                f.write(json.dumps(json.loads(p.read_text(encoding="utf-8")), ensure_ascii=False) + "\n")
        log.info("인덱스 작성: %d건 -> %s", len(docs), self.out_dir / "documents.jsonl")


def main() -> None:
    ap = argparse.ArgumentParser(description="단국대 학과 홈페이지 크롤러")
    ap.add_argument("start_url", help="예: https://cms.dankook.ac.kr/web/mobilesystems")
    ap.add_argument("--out", default="data/crawl", help="출력 폴더 (기본: data/crawl)")
    ap.add_argument("--delay", type=float, default=1.0, help="요청 간 대기 시간(초)")
    ap.add_argument("--max-pages", type=int, default=200, help="방문할 일반 페이지 최대 수")
    ap.add_argument("--max-board-pages", type=int, default=3,
                    help="게시판별 목록 페이지 최대 수 (0 = 전체)")
    ap.add_argument("--download-attachments", action="store_true", help="첨부파일도 내려받기")
    ap.add_argument("--refresh", action="store_true", help="이미 수집한 게시글도 다시 수집")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    out_dir = Path(args.out) / urlparse(args.start_url).path.rstrip("/").split("/")[-1]
    crawler = DkuCrawler(
        args.start_url, out_dir, delay=args.delay, max_pages=args.max_pages,
        max_board_pages=args.max_board_pages or None,
        download_attachments=args.download_attachments, refresh=args.refresh,
    )
    stats = crawler.run()
    log.info("완료: %s", stats)


if __name__ == "__main__":
    main()
