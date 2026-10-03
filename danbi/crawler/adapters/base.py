"""SiteAdapter 인터페이스. 지원하지 않는 동작은 NotSupported를 던진다."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...sources.models import Section, Source


class NotSupported(Exception):
    pass


@dataclass
class ItemSummary:
    id: int
    title: str
    date: str  # 작성일 (YYYY.MM.DD)
    url: str
    author: str | None = None
    has_attachment: bool = False
    closed: bool = False   # 제목의 [마감]
    pinned: bool = False   # 번호 대신 '공지' 등으로 고정된 글

    @property
    def year(self) -> int | None:
        return int(self.date[:4]) if self.date[:4].isdigit() else None


@dataclass
class ListPage:
    items: list[ItemSummary]
    total_count: int
    page: int
    total_pages: int


@dataclass
class Attachment:
    name: str
    url: str


@dataclass
class Item:
    id: int
    title: str
    url: str
    posted_at: str | None = None
    modified_at: str | None = None
    author: str | None = None
    body_md: str = ""
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class PageDoc:
    title: str
    url: str
    body_md: str


# 데이터셋 레코드는 어댑터가 사이트별 JSON을 아래 공통 키로 정규화한 dict다 (query_data가 필터링·출력).
#   professors: name, eng_name, position, role, org, office, tel, email, homepage, detail_url, education(list)
#   curriculum: org, program, group, category, name, eng_name, credit, semesters(list, 예: "2-1"), summary, year
#   dept_info:  name, updated, sections(dict 제목→본문), contact(dict 항목→값)
#   calendar:   title, start(YYYY-MM-DD), end(YYYY-MM-DD), calendar   — 학사일정 (학년도 = 3월~다음 해 2월)
#   menu:       org(캠퍼스), corner, name, price(int, 원), sold_out(bool)   — 학생식당(푸드코트) 메뉴
DATASET_KINDS = ("dept_info", "professors", "curriculum", "calendar", "menu")
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


class SiteAdapter:
    """소스 하나를 담당한다. 섹션·경로 해석은 레지스트리가, 사이트별 URL·파싱은 어댑터가 맡는다."""

    supports: set[str] = set()  # search | list | get_item | get_page | get_dataset | get_attachment

    def __init__(self, source: Source):
        self.source = source

    def get_page(self, path: str) -> PageDoc:
        raise NotSupported("get_page")

    def get_dataset(self, kind: str, path: str, org: str | None = None) -> list[dict]:
        raise NotSupported("get_dataset")

    def get_attachment(self, url: str) -> bytes:
        raise NotSupported("get_attachment")

    def search(self, section: Section, keyword: str, field: str = "title", page: int = 1) -> ListPage:
        raise NotSupported("search")

    def list(self, section: Section, page: int = 1) -> ListPage:
        raise NotSupported("list")

    def get_item(self, section: Section, item_id: int) -> Item:
        raise NotSupported("get_item")
