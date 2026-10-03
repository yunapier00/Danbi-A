"""search_site / latest_items / get_item: 가짜 어댑터로 도구 로직 검증."""

from datetime import date

import pytest

from danbi.agent.tools import ToolError
from danbi.agent.tools.site import SiteTools
from danbi.crawler.adapters.base import Attachment, Item, ItemSummary, ListPage, SiteAdapter
from danbi.crawler.http import FetchError
from danbi.sources.models import Section, Source
from danbi.sources.registry import SourceRegistry

PAGE_SIZE = 3


def summary(i, d, pinned=False):
    return ItemSummary(id=i, title=f"글{i}", date=d, url=f"u{i}", pinned=pinned)


class FakeAdapter(SiteAdapter):
    supports = {"search", "list", "get_item"}

    def __init__(self, source, items, item=None, fail=False):
        super().__init__(source)
        self.items, self.item, self.fail = items, item, fail
        self.calls = []

    def _page(self, items, page):
        if self.fail:
            raise FetchError("HTTP 503", "https://x/board", 503)
        chunk = items[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        return ListPage(chunk, len(items), page, max(1, -(-len(items) // PAGE_SIZE)))

    def search(self, section, keyword, field="title", page=1):
        self.calls.append(("search", section.id, page))
        return self._page(self.items, page)

    def list(self, section, page=1):
        self.calls.append(("list", section.id, page))
        return self._page(self.items, page)

    def get_item(self, section, item_id):
        return self.item


def make(items, item=None, fail=False):
    src = Source(
        id="t", type="dku_cms", name="테스트학과", base_url="https://cms.dankook.ac.kr/web/t",
        aliases=["테학"], campus="죽전", description="공지·규정",
        sections={
            "notice": Section("notice", "공지사항", "/web/t/-1"),
            "rules": Section("rules", "규정A", "/web/t/-2"),
            "rules_sw": Section("rules_sw", "규정B", "/web/t/-3", same_as="rules"),
        },
        reviewed_at=date(2026, 10, 2),
    )
    adapter = FakeAdapter(src, items, item, fail)
    return SiteTools(SourceRegistry([src]), {"t": adapter}), adapter


ITEMS = [summary(1, "2026.04.02"), summary(2, "2026.01.01"), summary(3, "2024.04.16"),
         summary(4, "2023.12.21"), summary(5, "2021.07.08"), summary(6, "2020.01.01")]


def test_specs_are_generated_from_registry():
    tools, _ = make(ITEMS)
    specs = {t.spec.name: t.spec for t in tools.tools()}
    assert set(specs) == {"search_site", "latest_items", "get_item", "read_attachment"}  # 데이터·페이지 없음
    desc = specs["search_site"].description
    assert "- t: 테스트학과 [테학] (죽전) — 공지·규정 / 섹션: notice(공지사항), rules(규정A + rules_sw:규정B)" in desc
    props = specs["get_item"].parameters["properties"]
    assert props["source"]["enum"] == ["t"]
    assert props["section"]["enum"] == ["notice", "rules", "rules_sw"]


def test_search_without_year_shows_first_page():
    tools, adapter = make(ITEMS)
    out = tools.search_site(source="t", section="notice", keyword="예비군")
    assert "제목 검색 \"예비군\" — 전체 6건" in out
    assert "- [1] 2026.04.02 | 글1" in out and "[4]" not in out
    assert "최근 3건만 표시" in out
    assert adapter.calls == [("search", "notice", 1)]


def test_search_year_found_pages_until_older():
    tools, adapter = make(ITEMS)
    out = tools.search_site(source="t", section="notice", keyword="x", year=2023)
    assert "2023년 작성 글 1건" in out and "[4] 2023.12.21" in out
    assert [c[2] for c in adapter.calls] == [1, 2]  # 2페이지에서 2023년보다 오래된 글이 나와 멈춤


def test_search_year_missing_shows_nearest():
    tools, _ = make(ITEMS)
    out = tools.search_site(source="t", section="notice", keyword="예비군", year=2025)
    assert "2025년에 작성된 글은 없습니다" in out
    nearest = out.split("가장 가까운 글:")[1]
    assert "[2] 2026.01.01" in nearest and "[3] 2024.04.16" in nearest and "[1]" not in nearest


def test_search_role_skips_same_as_section():
    tools, adapter = make(ITEMS[:1])
    tools.search_site(source="t", section="rules", keyword="졸업")
    assert [c[1] for c in adapter.calls] == ["rules"]


def test_latest_items_pages_and_puts_pinned_last():
    items = [summary(9, "2020.01.01", pinned=True)] + ITEMS
    tools, adapter = make(items)
    out = tools.latest_items(source="t", section="notice", limit=4)
    ids = [ln.split("]")[0] for ln in out.splitlines() if ln.startswith("- ")]
    assert ids == ["- [1", "- [2", "- [3", "- [4"]  # 고정 글은 최신순이 아니므로 뒤로 밀린다
    assert [c[2] for c in adapter.calls] == [1, 2]
    out = tools.latest_items(source="t", section="notice", limit=10)
    assert out.splitlines()[-1].startswith("- [9]") and "고정" in out.splitlines()[-1]


def test_get_item_formats_and_notes_attachment_only_body():
    item = Item(id=7, title="졸업시험 공지", url="https://x/7", posted_at="2026.09.22", modified_at="2026.09.25",
                author="학과", body_md="", attachments=[Attachment("공고.hwp", "https://x/a")])
    tools, _ = make(ITEMS, item=item)
    out = tools.get_item(source="t", section="notice", item_id=7)
    assert "작성일: 2026.09.22 (수정일: 2026.09.25)" in out
    assert "첨부: (0) 공고.hwp" in out
    assert "내용은 첨부파일에 있습니다" in out


def test_errors_become_tool_errors():
    tools, _ = make(ITEMS, fail=True)
    guarded = {t.spec.name: t.func for t in tools.tools()}
    with pytest.raises(ToolError, match="테스트학과 사이트에 접속할 수 없었습니다"):
        guarded["search_site"](source="t", section="notice", keyword="x")
    with pytest.raises(ToolError, match="섹션이 없습니다"):
        guarded["latest_items"](source="t", section="jobs")
    with pytest.raises(ToolError, match="알 수 없는 소스"):
        guarded["latest_items"](source="zz", section="notice")


# --- Phase 4: query_data, get_page, read_attachment ---------------------------------

from pathlib import Path

from danbi.crawler.adapters.base import PageDoc
from danbi.crawler.cache import Cache
from danbi.sources.models import DatasetEntry, Page

ATTACH = Path(__file__).parent / "fixtures" / "attachments"

CURRICULUM = [
    {"org": "A대학", "program": "정규 교과과정", "group": "전공필수", "category": "전공필수", "name": "자료구조",
     "eng_name": "Data Structure", "credit": "3", "semesters": ["2-1"], "summary": "배열, 스택", "year": "2026"},
    {"org": "A대학", "program": "정규 교과과정", "group": "전공선택", "category": "전공선택", "name": "운영체제",
     "eng_name": "Operating Systems", "credit": "3", "semesters": ["3-1"], "summary": "", "year": "2026"},
    {"org": "B대학", "program": "트랙 교육과정", "group": "IoT시스템트랙", "category": "트랙2", "name": "디지털논리회로",
     "eng_name": "", "credit": "3", "semesters": ["2-1", "2-2"], "summary": "", "year": "2026"},
]
PROFESSORS = [{"name": "유시환", "eng_name": "Yoo", "position": "교수", "role": "", "org": "학과", "office": "국제관 615호",
               "tel": "031-8005-3240", "email": "a@b", "homepage": "", "detail_url": "", "education": []}]


class FullAdapter(FakeAdapter):
    supports = FakeAdapter.supports | {"get_page", "get_dataset", "get_attachment"}
    downloads = 0

    def get_dataset(self, kind, path, org=None):
        return {"curriculum": CURRICULUM, "professors": PROFESSORS}[kind]

    def get_page(self, path):
        return PageDoc("졸업요건", "https://x" + path, "### 졸업요건\n본문")

    def get_attachment(self, url):
        self.downloads += 1
        return (ATTACH / url.rsplit("/", 1)[1]).read_bytes()


def make_full(item=None):
    src = Source(
        id="t", type="dku_cms", name="테스트학과", base_url="https://cms.dankook.ac.kr/web/t",
        sections={"notice": Section("notice", "공지사항", "/web/t/-1")},
        datasets={"curriculum": [DatasetEntry("/web/t/-3", "A대학")], "professors": [DatasetEntry("/web/t/-5")]},
        pages={"graduation": Page("graduation", "졸업요건", "/web/t/-38")},
        reviewed_at=date(2026, 10, 2),
    )
    adapter = FullAdapter(src, [], item)
    return SiteTools(SourceRegistry([src]), {"t": adapter}, cache=Cache(None)), adapter


def test_phase4_tools_and_catalog():
    tools, _ = make_full()
    specs = {t.spec.name: t.spec for t in tools.tools()}
    assert set(specs) == {"search_site", "latest_items", "get_item", "read_attachment", "query_data", "get_page"}
    assert specs["query_data"].parameters["properties"]["dataset"]["enum"] == ["curriculum", "professors"]
    assert "section" not in specs["get_page"].parameters["properties"]
    assert "데이터: curriculum(A대학), professors / 페이지: graduation(졸업요건)" in specs["search_site"].description


def test_query_data_curriculum_filters():
    tools, _ = make_full()
    out = tools.query_data(source="t", dataset="curriculum", grade=2, semester=1)
    assert "조건: grade=2, semester=1 — 2건 (2026학년도 기준)" in out
    assert "| A대학 | 정규 교과과정 | 전공필수 | 자료구조 (Data Structure) | 3 | 2-1 |" in out
    assert "| B대학 | 트랙 교육과정 IoT시스템트랙 | 트랙2 | 디지털논리회로 | 3 | 2-1, 2-2 |" in out
    assert "운영체제" not in out
    assert "- 자료구조: 배열, 스택" in out  # 결과가 적으면 개요도 보여준다

    assert "1건" in tools.query_data(source="t", dataset="curriculum", category="트랙")
    assert "1건" in tools.query_data(source="t", dataset="curriculum", org="B대학")
    none = tools.query_data(source="t", dataset="curriculum", grade=4)
    assert "해당하는 데이터가 없습니다 (전체 3건)" in none


def test_query_data_professors_and_missing_dataset():
    tools, _ = make_full()
    out = tools.query_data(source="t", dataset="professors", name="유 시환")
    assert "- 유시환 (Yoo) — 교수" in out and "연구실: 국제관 615호" in out
    with pytest.raises(ToolError, match="'dept_info' 데이터가 없습니다"):
        tools.query_data(source="t", dataset="dept_info")


def test_get_page():
    tools, _ = make_full()
    out = tools.get_page(source="t", page="graduation")
    assert out.startswith("[source: t / page: graduation(졸업요건)] 졸업요건\nURL: https://x/web/t/-38")
    with pytest.raises(ToolError, match="페이지가 없습니다"):
        tools.get_page(source="t", page="faq")


def test_read_attachment_extracts_and_caches():
    item = Item(id=7, title="예비군 공고", url="https://x/7", posted_at="2026.04.02",
                attachments=[Attachment("공고.hwp", "https://x/reserve_training.hwp"),
                             Attachment("사진.jpg", "https://x/photo.jpg")])
    tools, adapter = make_full(item)
    out = tools.read_attachment(source="t", section="notice", item_id=7, attachment_index=0)
    assert "게시글 7 첨부 (0) 공고.hwp" in out and "| 05.08.(금) |" in out
    tools.read_attachment(source="t", section="notice", item_id=7, attachment_index=0)
    assert adapter.downloads == 1  # 두 번째는 캐시

    with pytest.raises(ToolError, match=r"첨부 \(5\)이\(가\) 없습니다. 첨부 목록: \(0\) 공고.hwp, \(1\) 사진.jpg"):
        tools.read_attachment(source="t", section="notice", item_id=7, attachment_index=5)


def test_read_attachment_unsupported_format(monkeypatch):
    item = Item(id=7, title="t", url="https://x/7", attachments=[Attachment("사진.jpg", "https://x/photo.jpg")])
    tools, adapter = make_full(item)
    monkeypatch.setattr(adapter, "get_attachment", lambda url: b"\xff\xd8\xff\xe0")
    with pytest.raises(ToolError, match="읽을 수 없습니다.*원문 URL을 안내하세요: https://x/7"):
        tools.read_attachment(source="t", section="notice", item_id=7, attachment_index=0)


# --- Phase 7: list_sources, 요약 설명 ------------------------------------------------------

from danbi.sources.dept_list import Department


def make_with_departments(inline_limit=20):
    src = Source(id="t", type="dku_cms", kind="department", name="테스트학과", base_url="https://cms.dankook.ac.kr/web/t",
                 aliases=["테학"], campus="죽전", college="공과대학", office={"tel": "031-8005-1111"},
                 sections={"notice": Section("notice", "공지사항", "/web/t/-1")}, reviewed_at=date(2026, 10, 2))
    pending = Source(id="p", type="dku_cms", name="검토전학과", base_url="https://cms.dankook.ac.kr/web/p",
                     sections={"notice": Section("notice", "공지", "/web/p/-1")})
    depts = {
        "t": Department("t", "테스트학과", "공과대학", "죽전", "dku_cms", "https://cms.dankook.ac.kr/web/t", ["테스트학과"]),
        "p": Department("p", "검토전학과", "공과대학", "죽전", "dku_cms", "https://cms.dankook.ac.kr/web/p", ["검토전학과"],
                        {"tel": "031-8005-2222"}),
        "chemistry": Department("chemistry", "화학과", "과학기술대학", "천안", "dku_cms",
                                "https://cms.dankook.ac.kr/web/chemistry", ["화학과"], {"tel": "041-550-3430", "room": "225호"}),
        "film": Department("film", "연극전공·영화전공", "음악·예술대학 공연영화학부", "죽전", "dku_cms", None, ["연극전공", "영화전공"]),
    }
    reg = SourceRegistry([src, pending])
    adapter = FakeAdapter(src, ITEMS)
    return SiteTools(reg, {"t": adapter}, inline_source_limit=inline_limit, departments=depts)


def test_list_sources_supported_and_unsupported():
    tools = make_with_departments()
    assert "list_sources" in {t.spec.name for t in tools.tools()}
    out = tools.list_sources(query="테학")
    assert "[검색 지원] t: 테스트학과 (공과대학, 죽전)" in out and "섹션: notice(공지사항)" in out
    out = tools.list_sources(query="화학")
    assert "[검색 미지원] chemistry: 화학과 (과학기술대학, 천안)" in out
    assert "학과 사무실: 전화 041-550-3430, 사무실 225호" in out and "연락처·홈페이지를 안내하세요" in out
    assert "film" not in out  # '공연영화학부'의 '화학'은 일치로 보지 않는다
    # 레지스트리에 있지만 검토 전인 소스는 미지원으로, dept_list의 연락처와 함께
    out = tools.list_sources(query="검토전")
    assert "[검색 미지원] p: 검토전학과" in out and "031-8005-2222" in out


def test_list_sources_filters():
    tools = make_with_departments()
    assert "chemistry" not in tools.list_sources(campus="죽전")
    assert "4건" in tools.list_sources()
    assert "film" in tools.list_sources(query="음악·예술대학")  # '대학'을 넣으면 단과대학으로도 찾는다
    assert "해당하는 학과·소스가 없습니다" in tools.list_sources(query="없는과")
    assert "홈페이지: 없음" in tools.list_sources(query="연극")


def test_summary_catalog_when_many_sources():
    tools = make_with_departments(inline_limit=0)
    desc = {t.spec.name: t.spec for t in tools.tools()}["search_site"].description
    assert "검색 가능한 웹 소스 1개 (학과 1개)" in desc and "list_sources" in desc
    assert "- t: 테스트학과" not in desc


def test_apply_departments_fills_missing_fields():
    src = Source(id="t", type="dku_cms", name="테스트학과", base_url="https://cms.dankook.ac.kr/web/t")
    reg = SourceRegistry([src])
    reg.apply_departments({"t": Department("t", "테스트학과", "공과대학", "죽전", office={"tel": "1"})})
    assert (src.college, src.campus, src.office) == ("공과대학", "죽전", {"tel": "1"})


def test_calendar_and_menu_filters():
    from danbi.agent.tools.data import filter_records, format_records
    cal = [{"title": "2학기 기말고사", "start": "2026-12-09", "end": "2026-12-21", "calendar": "Portal"},
           {"title": "겨울 계절학기", "start": "2026-12-28", "end": "2027-01-20", "calendar": "Portal"},
           {"title": "1학기 개강", "start": "2026-03-03", "end": "2026-03-03", "calendar": "Portal"}]
    assert [r["title"] for r in filter_records("calendar", cal, month=1)] == ["겨울 계절학기"]
    assert [r["title"] for r in filter_records("calendar", cal, on_date="2026-12-15")] == ["2학기 기말고사"]
    assert [r["title"] for r in filter_records("calendar", cal, keyword="기말")] == ["2학기 기말고사"]
    assert format_records("calendar", cal[2:]) == "- 2026-03-03 | 1학기 개강"
    menu = [{"org": "죽전", "corner": "경성카츠", "name": "왕돈카츠", "price": 8900, "sold_out": True},
            {"org": "천안", "corner": "도쿄야", "name": "우동", "price": 5000, "sold_out": False}]
    hits = filter_records("menu", menu, org="죽전", keyword="돈카츠")
    assert format_records("menu", hits) == "### 죽전 · 경성카츠\n- 왕돈카츠 8,900원 (품절)"
