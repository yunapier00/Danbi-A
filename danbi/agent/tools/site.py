"""웹 소스 도구: search_site, latest_items, get_item, read_attachment, query_data, get_page.

모든 웹 소스가 같은 도구를 쓴다. source·section·dataset·page enum과 소스 목록은 레지스트리에서 자동 생성하므로
소스를 추가해도 이 파일은 바뀌지 않는다. 도구 함수는 동기(크롤링)이며 ToolRegistry가 스레드에서 실행한다.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Callable

from ...crawler.adapters.base import ItemSummary, ListPage, NotSupported, SiteAdapter
from ...crawler.cache import TTL_ATTACHMENT, Cache
from ...crawler.extract.documents import UnsupportedDocument, extract_text
from ...crawler.http import FetchError
from ...llm.base import ToolSpec
from ...sources.dept_list import Department
from ...sources.models import Section, Source
from ...sources.registry import SourceLookupError, SourceRegistry
from .data import SUMMARY_ROWS, filter_records, format_records
from .registry import Tool, ToolError

log = logging.getLogger(__name__)

MAX_YEAR_PAGES = 4   # year 필터 시 섹션당 최대 검색 결과 페이지 수 (페이지당 15건)
MAX_LATEST = 30
BODY_LIMIT = 8000
ATTACHMENT_LIMIT = 12000
FIELD_LABEL = {"title": "제목", "content": "본문", "writer": "작성자"}
OP_ALTERNATIVES = {
    "search": "latest_items나 get_page를 쓰세요",
    "list": "search_site를 쓰세요",
    "get_item": "목록 결과의 URL을 안내하세요",
    "get_page": "search_site나 latest_items를 쓰세요",
    "get_dataset": "get_page나 search_site를 쓰세요",
    "get_attachment": "게시글 URL을 안내하세요",
}
KIND_LABEL = {"department": "학과", "campus": "학교 공통", "dku_cms": "학교 사이트", "static_page": "안내 페이지",
              "library": "도서관"}
MAX_LIST_SOURCES = 15


class SiteTools:
    def __init__(self, registry: SourceRegistry, adapters: dict[str, SiteAdapter], inline_source_limit: int = 20,
                 cache: Cache | None = None, departments: dict[str, Department] | None = None):
        self.registry = registry
        self.adapters = adapters
        self.cache = cache  # 첨부 텍스트 캐시
        self.departments = departments or {}  # 학교 공식 학과 목록 (config/dept_list.yaml)
        self.sources = [s for s in registry.web_sources() if s.id in adapters]
        # 소스가 많으면 도구 설명에는 요약만 넣고 list_sources로 찾게 한다 (설계 §6.5)
        self.inline = len(self.sources) <= inline_source_limit

    # --- 도구 정의 ------------------------------------------------------------

    def _section_values(self) -> list[str]:
        values = set()
        for s in self.sources:
            for sec in s.sections.values():
                if sec.role != "ignore":
                    values |= {sec.role, sec.id}
        return sorted(values)

    def _catalog(self) -> str:
        if not self.inline:
            kinds: dict[str, int] = {}
            for s in self.sources:
                kinds[s.kind or s.type] = kinds.get(s.kind or s.type, 0) + 1
            summary = ", ".join(f"{KIND_LABEL.get(k, k)} {n}개" for k, n in kinds.items())
            return (f"검색 가능한 웹 소스 {len(self.sources)}개 ({summary}). 소스 ID와 섹션·데이터·페이지는 "
                    "list_sources로 학과·기관 이름(줄임말 가능)을 검색해 확인한다.")
        lines = ["검색 가능한 소스 (ID: 이름 [별칭] (캠퍼스) — 내용 / 섹션 / 데이터 / 페이지):"]
        lines += [self._source_line(s) for s in self.sources]
        return "\n".join(lines)

    @staticmethod
    def _contents(s: Source) -> str:
        groups: dict[str, list[str]] = {}
        for sec in s.sections.values():
            if sec.role != "ignore":
                groups.setdefault(sec.role, []).append(sec.title if sec.id == sec.role else f"{sec.id}:{sec.title}")
        parts = []
        if groups:
            parts.append("섹션: " + ", ".join(f"{role}({' + '.join(titles)})" for role, titles in groups.items()))
        if s.datasets:
            ds = [k + (f"({', '.join(e.org for e in v if e.org)})" if any(e.org for e in v) else "") for k, v in s.datasets.items()]
            parts.append(f"데이터: {', '.join(ds)}")
        if s.pages:
            parts.append(f"페이지: {', '.join(f'{p.id}({p.title})' for p in s.pages.values())}")
        return " / ".join(parts)

    def _source_line(self, s: Source) -> str:
        alias = f" [{', '.join(s.aliases)}]" if s.aliases else ""
        campus = f" ({s.campus})" if s.campus else ""
        return f"- {s.id}: {s.name}{alias}{campus} — {s.description} / {self._contents(s)}"

    def _params(self, extra: dict, required: list[str], *, section: bool = True) -> dict:
        props: dict = {"source": {"type": "string", "enum": [s.id for s in self.sources], "description": "소스 ID"}}
        if section:
            props["section"] = {
                "type": "string", "enum": self._section_values(),
                "description": "섹션 역할(notice, jobs, rules …) 또는 섹션 ID. 역할을 주면 같은 역할의 게시판을 모두 다룬다",
            }
        return {
            "type": "object",
            "properties": {**props, **extra},
            "required": ["source", *(["section"] if section else []), *required],
        }

    def tools(self) -> list[Tool]:
        tools = []
        if self.departments or (self.sources and not self.inline):
            tools.append(Tool(ToolSpec(
                name="list_sources",
                description=(
                    "학과·전공·기관 이름(줄임말·일부 가능)으로 소스를 찾는다. 단비가 검색을 지원하는 소스는 ID·섹션·데이터·페이지를, "
                    "아직 지원하지 않는 학과는 학교 공식 학과 목록의 소속 단과대학·캠퍼스·학과 사무실 연락처·홈페이지를 돌려준다. "
                    "질문한 학과가 소스 목록에 없을 때, 같은 이름의 학과가 캠퍼스별로 있는지 확인할 때 쓴다."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "학과·전공·기관 이름 (예: 컴퓨터공학, 행정학과, 화학)"},
                        "campus": {"type": "string", "enum": ["죽전", "천안"]},
                    },
                    "required": [],
                },
            ), self.list_sources, lambda a: f"'{a.get('query') or '전체'}' 학과 정보 찾는 중"))
        if not self.sources:
            return tools
        if any(s.sections for s in self.sources):
            tools += self._board_tools()
        datasets = sorted({k for s in self.sources for k in s.datasets})
        if datasets:
            tools.append(Tool(ToolSpec(
                name="query_data",
                description=(
                    "웹 소스의 정형 데이터를 조회한다. professors(교수 목록: 직급, 연구실, 전화, 이메일), "
                    "curriculum(교과과정: 이수구분, 학점, 개설 학년-학기, 과목 개요), dept_info(학과 소개·교육목표·진로·사무실 연락처), "
                    "calendar(학교 학사일정: 실시간, 올해 학년도 3월~다음 해 2월, 일정별 시작·종료일), "
                    "menu(학생식당 푸드코트 메뉴·가격·품절 여부, 캠퍼스별. 날짜별 식단표가 아니라 판매 메뉴 목록), "
                    "campus_map(학교 공식 캠퍼스맵: 건물 위치와 카카오맵 지도 링크, 건물별 층·호수·부서·편의시설. "
                    "name=건물, keyword=부서·시설·호수·층(예: 학사팀, 편의점, 301, 2층), category=분류(행정지원, 편의시설, 금융/보건, 식당/매점). "
                    "건물 사이 걷는 경로는 없으므로 길 안내는 지도 링크로 대신한다), "
                    "timetable(종합강의시간표 저장본: 강좌별 교강사, 요일·시각, 강의실, 학점, 이수구분, 수강대상, 비고. "
                    "name=과목명 또는 교강사, keyword=요일(예: 월요일)·강의실·교과목번호·비고, grade=학년, category=이수구분, "
                    "org=수강조직(학과). 저장 시점 이후 변경은 반영되지 않으므로 결과의 저장일을 함께 알린다). "
                    "조건을 주면 해당하는 것만 돌려준다. 소스별 데이터 목록은 search_site 설명이나 list_sources를 따른다. "
                    "교과과정은 소속(단과대학)별로 다를 수 있으니 결과의 소속을 구분해서 답한다."
                ),
                parameters=self._params({
                    "dataset": {"type": "string", "enum": datasets},
                    "name": {"type": "string", "description": "교수 이름, 과목명 또는 건물 이름 (일부만 써도 됨)"},
                    "keyword": {"type": "string", "description": "과목명·개요(교과과정), 직급·보직·연구실(교수) 또는 부서·시설·호수·층(캠퍼스맵)에서 찾을 말"},
                    "grade": {"type": "integer", "description": "교과과정·강의시간표: 학년 (1~6)"},
                    "semester": {"type": "integer", "description": "교과과정: 학기 (1 또는 2)"},
                    "category": {"type": "string", "description": "교과과정: 이수구분·과정 (예: 전공필수, 전공선택, 교양, 마이크로전공, 트랙). 캠퍼스맵: 시설 분류"},
                    "org": {"type": "string", "description": "소속 또는 캠퍼스 (예: 프리무스국제대학, 죽전, 천안)"},
                    "month": {"type": "integer", "description": "학사일정: 이 달(1~12)과 기간이 겹치는 일정"},
                    "date": {"type": "string", "description": "학사일정: 이 날짜(YYYY-MM-DD)에 진행 중인 일정"},
                }, ["dataset"], section=False),
            ), self._guard(self.query_data), self._status_data))
        pages = sorted({k for s in self.sources for k in s.pages})
        if pages:
            tools.append(Tool(ToolSpec(
                name="get_page",
                description="웹 소스의 고정 안내 페이지(졸업요건, 장학금 안내, 오시는 길 등) 본문을 가져온다. 소스별 페이지 목록은 search_site 설명을 따른다.",
                parameters=self._params({"page": {"type": "string", "enum": pages}}, ["page"], section=False),
            ), self._guard(self.get_page), self._status_page))
        return tools

    def _board_tools(self) -> list[Tool]:
        search_spec = ToolSpec(
            name="search_site",
            description=(
                "학교 웹 사이트(학과 홈페이지 등)의 게시판을 사이트 자체 검색 기능으로 검색한다. 실시간 자료이며 게시글마다 작성일이 있다. "
                "결과는 게시글 목록(ID, 작성일, 제목, 마감·첨부 여부)이다. 답하기 전에 근거가 되는 글은 get_item으로 본문을 확인한다. "
                "제목 검색(field=title, 기본)으로 결과가 없거나 부족하면 본문 검색(field=content)이나 동의어로 다시 검색한다. "
                "특정 연도의 글을 찾을 때는 year를 준다.\n" + self._catalog()
            ),
            parameters=self._params({
                "keyword": {"type": "string", "description": "검색어 (짧은 핵심어. 예: 예비군, 졸업시험)"},
                "field": {"type": "string", "enum": ["title", "content", "writer"], "description": "검색 대상 (기본 title)"},
                "year": {"type": "integer", "description": "이 연도에 작성된 글만 (예: 2025)"},
            }, ["keyword"]),
        )
        latest_spec = ToolSpec(
            name="latest_items",
            description="웹 소스 게시판의 최신 글 목록을 작성일 순으로 가져온다 (예: \"최근 공지 뭐 있어?\"). 소스·섹션은 search_site 설명의 목록을 따른다.",
            parameters=self._params({
                "limit": {"type": "integer", "description": f"가져올 글 수 (기본 10, 최대 {MAX_LATEST})"},
            }, []),
        )
        item_spec = ToolSpec(
            name="get_item",
            description="웹 소스 게시글의 상세(제목, 작성일·수정일, 본문, 첨부 목록, URL)를 가져온다. item_id는 search_site·latest_items 결과의 ID.",
            parameters=self._params({
                "item_id": {"type": "integer", "description": "게시글 ID"},
            }, ["item_id"]),
        )
        attachment_spec = ToolSpec(
            name="read_attachment",
            description=(
                "게시글 첨부파일(PDF, HWP, HWPX)의 텍스트를 읽는다. 표는 마크다운 표로 돌려준다. "
                "본문이 비어 있거나 본문만으로 답이 부족하고 첨부에 내용이 있을 때 쓴다. "
                "attachment_index는 get_item 결과의 첨부 번호. 한 번에 첨부 1개만 읽는다."
            ),
            parameters=self._params({
                "item_id": {"type": "integer", "description": "게시글 ID"},
                "attachment_index": {"type": "integer", "description": "첨부 번호 (get_item 결과의 (0), (1) …)"},
            }, ["item_id", "attachment_index"]),
        )
        return [
            Tool(search_spec, self._guard(self.search_site),
                 lambda a: f"{self._where(a)}에서 '{a.get('keyword', '')}' 검색 중"),
            Tool(latest_spec, self._guard(self.latest_items), lambda a: f"{self._where(a)} 최신 글 확인 중"),
            Tool(item_spec, self._guard(self.get_item), lambda a: f"{self._where(a)} 게시글 읽는 중"),
            Tool(attachment_spec, self._guard(self.read_attachment), lambda a: f"{self._where(a)} 첨부파일 읽는 중"),
        ]

    # --- 진행 상태 문구 -----------------------------------------------------------

    def _where(self, args: dict) -> str:
        src = next((s for s in self.sources if s.id == args.get("source")), None)
        if src is None:
            return "학교 사이트"
        sec = src.sections.get(args.get("section", "")) or next(
            (x for x in src.sections.values() if x.role == args.get("section")), None)
        return f"{src.name} {sec.title}" if sec else src.name

    _DATASET_LABEL = {"professors": "교수 정보", "curriculum": "교과과정", "dept_info": "학과 소개",
                      "calendar": "학사일정", "menu": "학식 메뉴", "campus_map": "캠퍼스맵", "timetable": "강의시간표"}

    def _status_data(self, args: dict) -> str:
        label = self._DATASET_LABEL.get(args.get("dataset", ""), "데이터")
        return f"{self._where({'source': args.get('source')})} {label} 확인 중"

    def _status_page(self, args: dict) -> str:
        src = next((s for s in self.sources if s.id == args.get("source")), None)
        page = src.pages.get(args.get("page", "")) if src else None
        return f"{src.name if src else '학교 사이트'} {page.title if page else '안내 페이지'} 확인 중"

    # --- 공통 ---------------------------------------------------------------

    def _guard(self, fn: Callable[..., str]) -> Callable[..., str]:
        """사이트·레지스트리 오류를 에이전트가 읽을 수 있는 ToolError로 바꾼다."""
        @functools.wraps(fn)
        def wrapper(**kwargs) -> str:
            try:
                return fn(**kwargs)
            except SourceLookupError as e:
                raise ToolError(str(e)) from e
            except FetchError as e:
                name = next((s.name for s in self.sources if s.id == kwargs.get("source")), kwargs.get("source"))
                raise ToolError(f"{name} 사이트에 접속할 수 없었습니다 ({e}). 원문 주소: {e.url}") from e
            except NotSupported as e:
                op = str(e)
                raise ToolError(f"이 소스는 {op} 동작을 지원하지 않습니다. {OP_ALTERNATIVES.get(op, '')}") from e
            except ValueError as e:  # 파싱 실패 = 사이트 구조 변경 가능성
                log.error("사이트 파싱 실패 %s(%s): %s", fn.__name__, kwargs, e)
                raise ToolError(f"사이트 내용을 읽지 못했습니다 (구조가 바뀌었을 수 있음): {e}") from e
        return wrapper

    def _source(self, source: str) -> tuple[Source, SiteAdapter]:
        src = self.registry.get(source)
        adapter = self.adapters.get(src.id)
        if adapter is None:
            raise SourceLookupError(f"{src.name}은(는) 아직 검색을 지원하지 않습니다")
        return src, adapter

    def _resolve(self, source: str, section: str) -> tuple[Source, list[Section], SiteAdapter]:
        src, adapter = self._source(source)
        return src, self.registry.resolve_sections(src, section), adapter

    @staticmethod
    def _line(i: ItemSummary) -> str:
        flags = [f for f, on in (("첨부", i.has_attachment), ("마감", i.closed), ("고정", i.pinned)) if on]
        return f"- [{i.id}] {i.date} | {i.title}" + (f" | {', '.join(flags)}" if flags else "")

    @staticmethod
    def _header(src: Source, sec: Section) -> str:
        return f"[source: {src.id} / section: {sec.id}({sec.title})] 게시판: {src.url(sec.path)}"

    # --- 도구 구현 ------------------------------------------------------------

    def search_site(self, source: str, section: str, keyword: str, field: str = "title", year: int | None = None) -> str:
        keyword = keyword.strip()
        if not keyword:
            raise ToolError("keyword가 비어 있습니다")
        if field not in FIELD_LABEL:
            raise ToolError("field는 title, content, writer 중 하나입니다")
        src, sections, adapter = self._resolve(source, section)
        if "search" not in adapter.supports:
            raise NotSupported("search")
        year = int(year) if year else None

        blocks = []
        for sec in sections:
            first = adapter.search(sec, keyword, field)
            items = list(first.items)
            page = 1
            # 결과는 작성일 내림차순 → 요청 연도보다 오래된 글이 나올 때까지만 넘긴다
            while year and items and (items[-1].year or 0) >= year and page < min(first.total_pages, MAX_YEAR_PAGES):
                page += 1
                items += adapter.search(sec, keyword, field, page).items

            head = f"{self._header(src, sec)}\n{FIELD_LABEL[field]} 검색 \"{keyword}\" — 전체 {first.total_count}건"
            if not items:
                blocks.append(f"{head}\n결과 없음")
            elif year:
                blocks.append(head + "\n" + self._year_filter(items, year, first, page))
            else:
                more = f"\n(최근 {len(items)}건만 표시. 더 오래된 글은 year로 좁히거나 검색어를 바꾸세요)" if first.total_count > len(items) else ""
                blocks.append(head + "\n" + "\n".join(self._line(i) for i in items) + more)
        return "\n\n".join(blocks)

    def _year_filter(self, items: list[ItemSummary], year: int, first: ListPage, pages: int) -> str:
        hits = [i for i in items if i.year == year]
        if hits:
            return f"{year}년 작성 글 {len(hits)}건:\n" + "\n".join(self._line(i) for i in hits)
        newer = [i for i in items if (i.year or 0) > year]
        older = [i for i in items if i.year is not None and i.year < year]
        lines = [f"{year}년에 작성된 글은 없습니다."]
        if not older and first.total_pages > pages:  # 페이지 상한에 걸려 해당 연도까지 내려가지 못함
            lines = [f"최근 {len(items)}건 안에는 {year}년 글이 없습니다 (더 오래된 결과는 확인하지 않음). 검색어를 좁혀 보세요."]
        nearest = ([newer[-1]] if newer else []) + ([older[0]] if older else [])
        if nearest:
            lines.append("가장 가까운 글:")
            lines += [self._line(i) for i in nearest]
        return "\n".join(lines)

    def latest_items(self, source: str, section: str, limit: int | None = None) -> str:
        src, sections, adapter = self._resolve(source, section)
        if "list" not in adapter.supports:
            raise NotSupported("list")
        n = max(1, min(int(limit or 10), MAX_LATEST))
        blocks = []
        for sec in sections:
            first = adapter.list(sec)
            items = list(first.items)
            page = 1
            while len(items) < n and page < first.total_pages:
                page += 1
                items += adapter.list(sec, page).items
            # 고정 글은 최신순이 아니므로 뒤로 보낸다
            items = sorted(items, key=lambda i: i.pinned)[:n]
            body = "\n".join(self._line(i) for i in items) or "글 없음"
            blocks.append(f"{self._header(src, sec)}\n최신 글 {len(items)}건 (전체 {first.total_count}건):\n{body}")
        return "\n\n".join(blocks)

    def get_item(self, source: str, section: str, item_id: int) -> str:
        src, sections, adapter = self._resolve(source, section)
        if "get_item" not in adapter.supports:
            raise NotSupported("get_item")
        sec = sections[0]
        item = adapter.get_item(sec, int(item_id))
        date = item.posted_at or "미상"
        if item.modified_at:
            date += f" (수정일: {item.modified_at})"
        lines = [
            f"[source: {src.id} / section: {sec.id}({sec.title})] 게시글 {item.id}",
            f"제목: {item.title}",
            f"작성일: {date}",
            f"작성자: {item.author or '미상'}",
            f"URL: {item.url}",
        ]
        if item.attachments:
            lines.append("첨부: " + ", ".join(f"({n}) {a.name}" for n, a in enumerate(item.attachments)))
        body = item.body_md.strip()
        if len(body) > BODY_LIMIT:
            body = body[:BODY_LIMIT] + f"\n…(본문 {len(item.body_md):,}자 중 앞부분만 표시)"
        if not body:
            body = "(본문 없음)"
            if item.attachments:
                body += " 내용은 첨부파일에 있습니다. read_attachment로 첨부를 읽으세요."
        return "\n".join(lines) + "\n---\n" + body

    def read_attachment(self, source: str, section: str, item_id: int, attachment_index: int) -> str:
        src, sections, adapter = self._resolve(source, section)
        if "get_attachment" not in adapter.supports:
            raise NotSupported("get_attachment")
        sec = sections[0]
        item = adapter.get_item(sec, int(item_id))
        idx = int(attachment_index)
        if not 0 <= idx < len(item.attachments):
            listed = ", ".join(f"({n}) {a.name}" for n, a in enumerate(item.attachments)) or "없음"
            raise ToolError(f"게시글 {item.id}에 첨부 ({idx})이(가) 없습니다. 첨부 목록: {listed}")
        att = item.attachments[idx]

        key = f"attachment_text:{att.url}"
        text = self.cache.get(key) if self.cache else None
        if text is None:
            try:
                text = extract_text(att.name, adapter.get_attachment(att.url))
            except UnsupportedDocument as e:
                raise ToolError(f"첨부 '{att.name}'을(를) 읽을 수 없습니다: {e}. 원문 URL을 안내하세요: {item.url}") from e
            if self.cache:
                self.cache.set(key, text, TTL_ATTACHMENT)
        if len(text) > ATTACHMENT_LIMIT:
            text = text[:ATTACHMENT_LIMIT] + f"\n…(첨부 텍스트 {len(text):,}자 중 앞부분만 표시)"
        return (f"[source: {src.id} / section: {sec.id}({sec.title})] 게시글 {item.id} 첨부 ({idx}) {att.name}\n"
                f"게시글 제목: {item.title} | 작성일: {item.posted_at or '미상'}\n게시글 URL: {item.url}\n---\n"
                + (text or "(추출된 텍스트 없음)"))

    def query_data(self, source: str, dataset: str, name: str | None = None, keyword: str | None = None,
                   grade: int | None = None, semester: int | None = None, category: str | None = None,
                   org: str | None = None, month: int | None = None, date: str | None = None) -> str:
        src, adapter = self._source(source)
        entries = src.datasets.get(dataset)
        if not entries:
            available = ", ".join(src.datasets) or "없음"
            raise ToolError(f"{src.name}에는 '{dataset}' 데이터가 없습니다. 이 소스의 데이터: {available}")
        if "get_dataset" not in adapter.supports:
            raise NotSupported("get_dataset")
        records = [r for e in entries for r in adapter.get_dataset(dataset, e.path, e.org)]
        if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
            raise ToolError("date는 YYYY-MM-DD 형식입니다")
        filters = {k: v for k, v in dict(name=name, keyword=keyword, grade=int(grade) if grade else None,
                                          semester=int(semester) if semester else None,
                                          category=category, org=org, month=int(month) if month else None,
                                          on_date=date).items() if v}
        hits = filter_records(dataset, records, **filters)
        cond = ", ".join(f"{'date' if k == 'on_date' else k}={v}" for k, v in filters.items()) or "없음"
        urls = ", ".join(src.url(e.path) for e in entries)
        years = sorted({r["year"] for r in hits if r.get("year")})
        collected = sorted({r["collected_at"] for r in hits if r.get("collected_at")})
        terms = sorted({r["term"] for r in hits if r.get("term")})
        basis = ((f" ({', '.join(years)}학년도 기준)" if years else "") + (f" ({', '.join(terms)}학기)" if terms else "")
                 + (f" ({collected[-1]} {'저장본' if terms else '수집'})" if collected else ""))
        head = f"[source: {src.id} / dataset: {dataset}] 조건: {cond} — {len(hits)}건{basis}\n원문: {urls}"
        if not hits:
            return f"{head}\n해당하는 데이터가 없습니다 (전체 {len(records)}건)."
        verbose = bool(keyword or name) or len(hits) <= SUMMARY_ROWS
        return f"{head}\n{format_records(dataset, hits, verbose=verbose)}"

    def get_page(self, source: str, page: str) -> str:
        src, adapter = self._source(source)
        p = src.pages.get(page)
        if p is None:
            available = ", ".join(f"{x.id}({x.title})" for x in src.pages.values()) or "없음"
            raise ToolError(f"{src.name}에는 '{page}' 페이지가 없습니다. 이 소스의 페이지: {available}")
        if "get_page" not in adapter.supports:
            raise NotSupported("get_page")
        doc = adapter.get_page(p.path)
        body = doc.body_md.strip() or "(본문 없음)"
        if len(body) > BODY_LIMIT:
            body = body[:BODY_LIMIT] + f"\n…(본문 {len(doc.body_md):,}자 중 앞부분만 표시)"
        return f"[source: {src.id} / page: {p.id}({p.title})] {doc.title}\nURL: {doc.url}\n---\n{body}"

    def list_sources(self, query: str | None = None, campus: str | None = None) -> str:
        """등록 소스(검색 지원) + 학교 공식 학과 목록(미지원 학과 포함)에서 이름·별칭·전공으로 찾는다."""
        def norm(s: str) -> str:
            return re.sub(r"\s+", "", s or "").lower()

        q = norm(query or "")
        by_college = "대학" in q  # 단과대학 이름은 '대학'을 넣어 물을 때만 비교 ('공연영화학부'가 '화학'에 걸리지 않게)
        rows: list[tuple[int, str]] = []
        seen: set[str] = set()
        for src in self.registry.web_sources(reviewed_only=False):
            dept = self.departments.get(src.id)
            names = [src.id, src.name, *src.aliases, *(dept.majors if dept else [])] + ([src.college or ""] if by_college else [])
            if (q and not any(q in norm(n) for n in names)) or (campus and src.campus != campus):
                continue
            seen.add(src.id)
            supported = src.reviewed and src.id in self.adapters
            office = self._office(src.office or (dept.office if dept else {}))
            where = ", ".join(x for x in (src.college or (dept.college if dept else ""), src.campus) if x)
            if supported:
                line = f"- [검색 지원] {src.id}: {src.name}" + (f" ({where})" if where else "")                     + (f" 별칭: {', '.join(src.aliases)}" if src.aliases else "")
                line += f"\n  {self._contents(src)}" + (f"\n  {office}" if office else "") + f"\n  홈페이지: {src.base_url}"
                rows.append((0, line))
            else:
                rows.append((1, self._unsupported_line(src.id, src.name, where, office, src.base_url)))
        for dept in self.departments.values():
            if dept.id in seen:
                continue
            names = [dept.id, dept.name, *dept.majors] + ([dept.college] if by_college else [])
            if (q and not any(q in norm(n) for n in names)) or (campus and dept.campus != campus):
                continue
            where = ", ".join(x for x in (dept.college, dept.campus) if x)
            rows.append((1, self._unsupported_line(dept.id, dept.name, where, self._office(dept.office), dept.homepage)))

        cond = ", ".join(x for x in (f"'{query}'" if query else "", campus or "") if x) or "전체"
        if not rows:
            return (f"[source: list_sources] {cond}: 해당하는 학과·소스가 없습니다. "
                    "이름을 줄이거나(예: '컴퓨터공학과' → '컴퓨터') 다른 표기로 다시 찾아보세요.")
        rows.sort(key=lambda r: r[0])
        shown = rows[:MAX_LIST_SOURCES]
        more = f"\n…(전체 {len(rows)}건 중 {len(shown)}건만 표시. 이름을 더 구체적으로 주세요)" if len(rows) > len(shown) else ""
        return (f"[source: list_sources] {cond} — {len(rows)}건 (학과 정보 출처: 학교 메인 사이트 단과대학 페이지)\n"
                + "\n".join(line for _, line in shown) + more)

    @staticmethod
    def _office(office: dict) -> str:
        parts = [f"전화 {office['tel']}" if office.get("tel") else "", f"사무실 {office['room']}" if office.get("room") else ""]
        return "학과 사무실: " + ", ".join(p for p in parts if p) if any(parts) else ""

    @staticmethod
    def _unsupported_line(sid: str, name: str, where: str, office: str, homepage: str | None) -> str:
        line = f"- [검색 미지원] {sid}: {name}" + (f" ({where})" if where else "")
        line += f"\n  {office}" if office else ""
        line += f"\n  홈페이지: {homepage}" if homepage else "\n  홈페이지: 없음"
        return line + "\n  → 단비는 이 학과 사이트를 검색하지 못합니다. 위 연락처·홈페이지를 안내하세요."
