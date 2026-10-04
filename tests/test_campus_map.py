import json
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml

from danbi.agent.tools.site import SiteTools
from danbi.crawler.adapters.dku_cms import DkuCmsAdapter
from danbi.ops.sources import extract_sources
from danbi.sources.campus_map import (aliases_of, floor_label, load_campus_map, map_link, parse_facility_detail,
                                      parse_facility_list)
from danbi.sources.models import DatasetEntry, Source
from danbi.sources.registry import SourceRegistry
from scripts import collect_campus_map

FIX = Path(__file__).parent / "fixtures" / "dku_cms"
LIST = json.loads((FIX / "campusmap_data_jukjeon.json").read_text(encoding="utf-8"))
DETAIL = json.loads((FIX / "campusmap_facility_1007.json").read_text(encoding="utf-8"))


# ---- 공식 캠퍼스맵 JSON 파싱 (2026-10-04 저장) ----

def test_parse_facility_list():
    fs = parse_facility_list(LIST)
    assert len(fs) == 42 and fs[0]["name"] == "정문"
    bj = next(f for f in fs if f["id"] == "1007")
    assert bj["name"] == "범정관(대학본부)" and 37.3 < bj["lat"] < 37.4 and 127.1 < bj["lng"] < 127.2
    with pytest.raises(ValueError):
        parse_facility_list({"status": False})


def test_parse_facility_detail_sorts_and_keeps_category():
    d = parse_facility_detail(DETAIL)
    rooms = d["rooms"]
    hak = next(r for r in rooms if r["name"] == "학사팀")
    assert (hak["floor"], hak["room"], hak["category"]) == ("1", "117", "행정지원")
    floors = [r["floor"] for r in rooms]
    assert floors == sorted(floors, key=lambda f: int(f.lstrip("B")) * (-1 if f.startswith("B") else 1))
    with pytest.raises(ValueError):
        parse_facility_detail({"data": {}, "status": False})


def test_parse_skips_dormitory_rooms():
    payload = {"status": True, "data": {"rooms": [
        {"flrId": "3", "roomNb": "301", "roomHpKnm": "사생실(2인실)"},
        {"flrId": "1", "roomNb": "", "roomHpKnm": "복도 및 계단"},
        {"flrId": "1", "roomNb": "101", "roomHpKnm": "편의점", "hpClsfNm": "식당/매점"}]}}
    assert [r["name"] for r in parse_facility_detail(payload)["rooms"]] == ["편의점"]


def test_aliases_floor_label_and_map_link():
    assert aliases_of("혜당관(학생회관)") == ["혜당관", "학생회관", "학관"]
    assert aliases_of("법학관/대학원동") == ["법학관", "대학원동"]
    assert aliases_of("웅비홀(남자)") == ["웅비홀", "기숙사"]                # '남자'는 별칭이 아니다
    assert aliases_of("설립자상(범정 장형 선생)") == ["설립자상"]           # 공백 있는 설명도 아니다
    assert aliases_of("상경관") == []
    assert (floor_label("B1"), floor_label("3"), floor_label("71"), floor_label("")) == ("지하 1층", "3층", "", "")
    link = map_link("소프트웨어 ICT관", 37.32, 127.12)
    assert link.startswith("https://map.kakao.com/link/map/") and " " not in link and link.endswith(",37.32,127.12")
    # '/'가 들어간 이름은 카카오에서 404가 난다 (2026-10-05 확인) → '·'로 바꾼다. ','도 좌표 구분자라 뺀다
    slash = map_link("법학관/대학원동", 37.3211, 127.1292)
    assert "%2F" not in slash and quote("법학관·대학원동", safe="") in slash
    assert map_link("가,나", 1, 2).count(",") == 2


# ---- 스냅숏 → query_data ----

@pytest.fixture
def tools(tmp_path):
    bj = parse_facility_detail(DETAIL)
    snap = {"collected_at": "2026-10-04", "campuses": {"죽전": [
        {"id": "1007", "name": "범정관(대학본부)", "lat": 37.3219622, "lng": 127.1265635, **bj},
        {"id": "1013", "name": "인문관", "lat": 37.3217, "lng": 127.1290, "desc": "",
         "rooms": [{"floor": "3", "room": "301", "name": "강의실", "eng_name": "", "category": ""},
                   {"floor": "1", "room": "101", "name": "편의점", "eng_name": "", "category": "식당/매점"}]},
        {"id": "1018", "name": "제1공학관", "lat": 37.321, "lng": 127.126, "desc": "",
         "rooms": [{"floor": "2", "room": "201", "name": "강의실", "eng_name": "", "category": ""}]},
        {"id": "1019", "name": "제2공학관", "lat": 37.3206, "lng": 127.1265, "desc": "", "rooms": []},
        {"id": "1033", "name": "곰상", "lat": 37.31997, "lng": 127.12896, "desc": "",
         "rooms": [{"floor": "71", "room": "001", "name": "곰상", "eng_name": "", "category": ""}]},
    ]}}
    path = tmp_path / "campus_map.yaml"
    path.write_text(yaml.safe_dump(snap, allow_unicode=True), encoding="utf-8")
    src = Source(id="main", type="dku_cms", name="학교 공통", base_url="https://dankook.ac.kr", kind="campus",
                 datasets={"campus_map": [DatasetEntry("/campusmap", "죽전")]}, reviewed_at=date(2026, 10, 4))
    adapter = DkuCmsAdapter(src, http=None, cache=None, snapshots={"campus_map": load_campus_map(path)})
    return SiteTools(SourceRegistry([src]), {"main": adapter})


def q(tools, **kw):
    return tools.query_data(source="main", dataset="campus_map", **kw)


def test_department_lookup_by_keyword(tools):
    out = q(tools, keyword="학사팀")
    assert "(2026-10-04 수집)" in out and "원문: https://dankook.ac.kr/campusmap" in out
    assert "### 죽전 · 범정관(대학본부) (별칭: 범정관, 대학본부, 본관)" in out
    assert "- 1층 117호 · 학사팀 [행정지원]" in out


def test_building_by_alias_expands_floors(tools):
    out = q(tools, name="대학본부")
    assert "지도: https://map.kakao.com/link/map/" in out
    assert "- 1층: " in out and "학사팀 117호" in out and "- 2층: " in out
    assert "현금지급기(우리)" in out and "0001호" not in out          # 시설 표시용 번호는 숨긴다


def test_name_and_keyword_floor_and_room_number(tools):
    assert "- 3층 301호 · 강의실" in q(tools, name="인문관", keyword="301호")
    floor2 = q(tools, name="범정관", keyword="2층")
    assert "2층" in floor2 and "1층" not in floor2


def test_keyword_across_buildings_and_category(tools):
    out = q(tools, keyword="식당")                                      # 분류(식당/매점)로도 찾는다
    assert "인문관" in out and "- 1층 101호 · 편의점 [식당/매점]" in out
    fin = q(tools, category="금융/보건")
    assert "현금지급기" in fin and "인문관" not in fin


def test_several_buildings_collapse_and_listing(tools):
    out = q(tools, name="공학관")
    assert out.count("### ") == 2 and "(호실 1곳 — 건물을 하나로 좁히면" in out and "201호" not in out
    listing = q(tools)
    assert "- 죽전 · 곰상" not in listing or "지도:" in listing      # 건물 5곳(≤8)이면 지도 링크까지 보여준다
    assert listing.count("### ") == 5


def test_outdoor_facility_without_junk_floor(tools):
    out = q(tools, name="곰상")
    assert "### 죽전 · 곰상" in out and "71층" not in out and "\n- " not in out


def test_map_links_become_sources_first(tools):
    refs = extract_sources("query_data", q(tools, keyword="강의실"))
    assert [r.title for r in refs[:2]] == ["인문관 지도", "제1공학관 지도"]
    assert refs[0].url.startswith("https://map.kakao.com/link/map/") and "," in refs[0].url
    assert refs[-1].url == "https://dankook.ac.kr/campusmap"


def test_missing_snapshot_is_empty(tmp_path):
    assert load_campus_map(tmp_path / "none.yaml") == []


# ---- 수집 스크립트 ----

class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class FakeHttp:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if "cmd=data" in url:
            return FakeResp({"status": True, "data": [
                {"type": "facility", "id": "1007", "name": "범정관(대학본부)", "lat": 37.32, "lng": 127.12},
                {"type": "facility", "id": "1033", "name": "곰상", "lat": 37.31, "lng": 127.12},
                {"type": "parking", "id": "9", "name": "주차장", "lat": 1, "lng": 1}]})
        return FakeResp(DETAIL if url.endswith("id=1007") else {"data": {}, "status": False})


def test_collect_script_uses_list_then_each_facility():
    http = FakeHttp()
    out = collect_campus_map.collect(http, "죽전")
    assert [b["name"] for b in out] == ["범정관(대학본부)", "곰상"]
    assert len(out[0]["rooms"]) > 10 and out[1]["rooms"] == []          # 호실 정보 없는 시설은 위치만
    assert len(http.urls) == 3 and "tab=1" in http.urls[0]
