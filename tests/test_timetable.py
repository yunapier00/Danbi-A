import json
from datetime import date
from pathlib import Path

import pytest

from danbi.agent.tools.site import SiteTools
from danbi.crawler.adapters.dku_cms import DkuCmsAdapter
from danbi.sources.models import DatasetEntry, Source
from danbi.sources.registry import SourceRegistry
from danbi.sources.timetable import (PAGE_URL, build_sections, load_timetable, parse_html, parse_room, parse_slots,
                                     period_time)
from scripts import build_timetable

# 2026-10-05 사람이 브라우저에서 저장한 시간표 화면에서 몇 강좌만 잘라 냄 (숨은 입력값 제거)
FIX = Path(__file__).parent / "fixtures" / "timetable"
FILES = [FIX / "liberal.html", FIX / "major.html", FIX / "basic.html"]


def test_period_times_match_official_table():
    assert period_time(1) == ("09:00", "09:30")
    assert period_time(18) == ("17:30", "18:00")
    assert period_time(19) == ("18:00", "18:50")       # 야간은 50분 단위
    assert period_time(24) == ("22:35", "23:25")


def test_parse_room_and_slots():
    assert parse_room("소프트406") == ("소프트웨어 ICT관", "406")
    assert parse_room("체B104") == ("체육관", "B104")
    assert parse_room("대학원동319") == ("법학관/대학원동", "319")
    assert parse_room("자연1관120") == (None, "자연1관120")       # 모르는 줄임말은 그대로
    s = parse_slots(["월16~18(인문320)", "금19~20", "수5(사범101)"])
    assert [(x["day"], x["from"], x["to"], x["building"], x["room"]) for x in s] == [
        ("월", "16:30", "18:00", "인문관", "320"), ("금", "18:00", "19:45", None, ""), ("수", "11:00", "11:30", "사범관", "101")]


def test_parse_html_rows_and_extra_column():
    rows = parse_html((FIX / "basic.html").read_text(encoding="utf-8"))
    assert rows and all(r["subj_id"] == "388080" and r["name"] == "이산수학" for r in rows)
    assert rows[0]["main_org"]                                  # 학문기초 검색에만 있는 '주수강조직'
    lib = parse_html((FIX / "liberal.html").read_text(encoding="utf-8"))
    ct = next(r for r in lib if r["subj_id"] == "528520")
    assert ct["name"] == "Critical Thinking" and ct["english"] and ct["credits"] == 3 and ct["main_org"] == ""
    assert [s["day"] for s in ct["slots"]] == ["월", "화"]
    with pytest.raises(ValueError):
        parse_html("<html><body>로그인이 필요합니다</body></html>")


def test_build_sections_merges_rows_and_files():
    rows = [r for f in FILES for r in parse_html(f.read_text(encoding="utf-8"))]
    secs = build_sections(rows)
    keys = [(s["subj_id"], s["section"]) for s in secs]
    assert len(keys) == len(set(keys))                          # 파일·수강조직이 겹쳐도 강좌는 하나
    dm = [s for s in secs if s["subj_id"] == "388080"]
    assert len(dm) == 6 and len(dm[0]["targets"]) > 3
    assert any(s["english"] for s in dm)                        # 6분반만 영어강의
    ai101 = next(s for s in secs if s["subj_id"] == "569220")
    assert ai101["slots"][0]["room_raw"] == ""                  # 강의실 미정


@pytest.fixture
def tools(tmp_path):
    out = tmp_path / "timetable.json"
    build_timetable.main([*map(str, FILES), "--term", "2026-2", "--saved", "2026-10-05", "--out", str(out)])
    src = Source(id="tt", type="dku_cms", name="종합강의시간표", base_url="https://webinfo.dankook.ac.kr", kind="campus",
                 datasets={"timetable": [DatasetEntry("/tiac/univ/lssn/lpci/views/lssnPopup/tmtbl.do")]},
                 reviewed_at=date(2026, 10, 5))
    adapter = DkuCmsAdapter(src, http=None, cache=None, snapshots={"timetable": load_timetable(out)})
    return SiteTools(SourceRegistry([src]), {"tt": adapter})


def q(tools, **kw):
    return tools.query_data(source="tt", dataset="timetable", **kw)


def test_query_by_course_name(tools):
    out = q(tools, name="이산수학")
    assert "(2026-2학기) (2026-10-05 저장본)" in out and f"원문: {PAGE_URL}" in out
    assert "### 이산수학 · 388080 · 3학점 · 학문기초" in out
    assert "- 1분반 김형돈 | 월 09:00–12:00 (1~6교시) 소프트웨어 ICT관 307호" in out
    assert "18:00–20:40 (19~21교시)" in out and "영어강의" in out


def test_query_by_professor_day_and_room(tools):
    assert "2분반 김형돈" in q(tools, name="김형돈") and "이경복" not in q(tools, name="김형돈")
    fri = q(tools, keyword="금요일")
    assert "금 " in fri and "월 09:00" not in fri
    assert "Critical Thinking" in q(tools, keyword="인문320")


def test_query_by_org_grade_category_puts_match_first(tools):
    out = q(tools, org="컴퓨터공학과", grade=3, category="전공필수")
    assert "기본컴퓨터공학실험2" in out and "이산수학" not in out
    sw = q(tools, name="이산수학", org="인공지능학과")
    assert "대상: 1학년 AI융합대학 인공지능학과" in sw


def test_no_room_and_no_result(tools):
    assert "인공지능101" in q(tools, name="인공지능101") and "금 15:00–18:00 (13~18교시) |" in q(tools, name="인공지능101")
    none = q(tools, name="없는과목")
    assert "0건" in none and "해당하는 데이터가 없습니다" in none


def test_snapshot_json_has_no_hidden_ids(tmp_path):
    out = tmp_path / "t.json"
    build_timetable.main([*map(str, FILES), "--term", "2026-2", "--out", str(out)])
    text = out.read_text(encoding="utf-8")
    assert "pfltId" not in text and "opOrgid" not in text
    assert json.loads(text)["term"] == "2026-2"


def test_missing_snapshot_is_empty(tmp_path):
    assert load_timetable(tmp_path / "none.json") == []
