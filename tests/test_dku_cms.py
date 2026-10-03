"""dku_cms 파서 회귀 테스트 (2026-10-02 저장한 실제 HTML 샘플)."""

from pathlib import Path

import pytest

from danbi.crawler.adapters.dku_cms import item_url, parse_dataset, parse_item, parse_list, parse_page

FIX = Path(__file__).parent / "fixtures" / "dku_cms"
SECTION_URL = "https://cms.dankook.ac.kr/web/mobilesystems/-8"


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_parse_board_list():
    page = parse_list(read("list_notice.html"), SECTION_URL)
    assert (page.total_count, page.page, page.total_pages) == (767, 1, 52)
    assert len(page.items) == 15
    first = page.items[0]
    assert first.id == 185236 and first.date == "2026.09.30" and first.has_attachment
    assert first.title == "2026학년도 역량 체계 및 역량진단검사 개편 안내"
    assert first.url == item_url(SECTION_URL, 185236)
    closed = page.items[2]
    assert closed.closed and closed.title.startswith("[마감]")
    # 제목 칸의 'H' 표시가 제목에 섞이지 않는다
    hot = next(i for i in page.items if i.id == 180112)
    assert hot.title == "2026년 가을 학위수여식 일정 및 졸업가운 대여 안내" and not hot.has_attachment
    assert not any(i.pinned for i in page.items)


def test_parse_search_results():
    page = parse_list(read("search_title_yebigun.html"), SECTION_URL)
    assert page.total_count == 11 and page.total_pages == 1
    assert [i.id for i in page.items[:2]] == [171180, 59285]
    assert [i.year for i in page.items[:3]] == [2026, 2024, 2023]


def test_parse_post():
    url = item_url(SECTION_URL, 171180)
    item = parse_item(read("post_171180.html"), url, 171180)
    assert item.title == "2026년도 예비군 기본 1차훈련 안내"
    assert item.posted_at == "2026.04.02" and item.modified_at is None
    assert item.author == "모바일시스템공학과"
    assert [a.name for a in item.attachments] == ["2026년 예비군 기본 1차훈련 공고.hwp"]
    assert "/documents/portlet_file_entry/" in item.attachments[0].url
    assert "예비군교육훈련 공고" in item.body_md
    assert "| 05.08.(금) |" in item.body_md  # 본문 안의 표가 마크다운 표로 변환된다
    assert "hwpjson" not in item.body_md


def test_parse_professors():
    profs = parse_dataset(read("data_professors.html"), "professors")
    assert len(profs) == 7
    yoo = next(p for p in profs if p["name"] == "유시환")
    assert yoo["office"] == "국제관 615호" and yoo["tel"] == "031-8005-3240"
    assert yoo["position"] == "교수" and yoo["role"] == "SW중심대학사업단 부단장"


def test_parse_curriculum():
    primus = parse_dataset(read("data_curriculum_primus.html"), "curriculum", org="프리무스국제대학")
    assert all(r["org"] == "프리무스국제대학" for r in primus)
    ds = next(r for r in primus if r["name"] == "자료구조")
    assert (ds["category"], ds["credit"], ds["semesters"], ds["program"]) == ("전공필수", "3", ["2-1"], "정규 교과과정")
    assert any(r["program"] == "마이크로전공" for r in primus)
    sw = parse_dataset(read("data_curriculum_sw.html"), "curriculum", org="SW융합대학")
    assert {r["program"] for r in sw} == {"트랙 교육과정"}  # SW융합대학 쪽은 트랙만 남아 있다
    assert {r["group"] for r in sw} == {"IoT시스템트랙", "모바일지능정보트랙"}


def test_parse_dept_info_skips_empty_portlets():
    depts = parse_dataset(read("data_dept.html"), "dept_info")
    assert len(depts) == 1  # 빈 deptData 포틀릿은 건너뛴다
    d = depts[0]
    assert d["name"] == "프리무스국제대학 모바일시스템공학과"
    assert "학과 소개" in d["sections"] and d["updated"].startswith("2025-03-14")


def test_parse_page():
    page = parse_page(read("page_chem_graduation.html"), "https://cms.dankook.ac.kr/web/chem/-38")
    assert page.title == "졸업요건"
    assert "### 학위논문 심사절차" in page.body_md
    assert "| 1 | 논문 심사신청 및 서류제출 | 매년 4월/10월 초 | 대학원생 |" in page.body_md


def test_not_a_board_raises():
    with pytest.raises(ValueError):
        parse_list("<html><div id='main-content'><p>일반 페이지</p></div></html>", SECTION_URL)
    with pytest.raises(ValueError):
        parse_item("<html><div id='main-content'></div></html>", "u", 1)


# --- 학교 공통: 학식 메뉴·학사일정 ------------------------------------------------------------

import json as _json
from datetime import date as _date

from danbi.crawler.adapters.dku_cms import (academic_year, academic_year_range_ms, calendar_group_id,
                                            parse_calendar_events)


def test_parse_menu():
    menu = parse_dataset(read("menu_cheonan.html"), "menu", org="천안")
    assert {r["org"] for r in menu} == {"천안"}
    katsu = [r for r in menu if r["corner"] == "경성카츠"]
    assert len(katsu) == 9 and all(isinstance(r["price"], int) for r in katsu)
    assert any(r["sold_out"] for r in parse_dataset(read("menu_jukjeon.html"), "menu", org="죽전"))


def test_parse_calendar_events():
    payload = _json.loads(read("calendar_events_2026.json"))
    events = parse_calendar_events(payload)
    assert len(events) == 117
    first = events[0]
    assert (first["start"], first["end"], first["title"]) == ("2026-03-03", "2026-03-03", "2026학년도 1학기 개강")
    final = next(e for e in events if e["title"] == "2026학년도 2학기 기말고사")
    assert (final["start"], final["end"]) == ("2026-12-09", "2026-12-21")
    assert [e["start"] for e in events] == sorted(e["start"] for e in events)
    with pytest.raises(ValueError):
        parse_calendar_events({"status": False, "data": []})


def test_academic_year_and_group_id():
    assert academic_year(_date(2026, 10, 3)) == 2026 and academic_year(_date(2027, 2, 10)) == 2026
    start, end = academic_year_range_ms(2026)
    assert start == 1772290800000                       # 2026-03-01 00:00 KST
    assert end == 1803826800000 - 1                     # 2027-03-01 00:00 KST 직전
    assert calendar_group_id('Liferay.ThemeDisplay = { getScopeGroupId: function() { return "20118"; } }') == "20118"
