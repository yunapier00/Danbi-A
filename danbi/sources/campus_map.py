"""캠퍼스맵: 학교 공식 캠퍼스맵(https://dankook.ac.kr/campusmap)의 건물·호실 스냅숏.

공식 캠퍼스맵은 화면 뒤에서 JSON을 부른다 (cmd=data: 건물 목록·좌표, cmd=facility: 건물별 호실·층·분류).
건물마다 따로 불러야 해서 질문할 때 부르면 너무 느리므로, scripts/collect_campus_map.py가 주 1회
config/campus_map.yaml로 모아 두고 query_data(dataset=campus_map)가 이 파일을 읽는다.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import quote

import yaml

log = logging.getLogger(__name__)

PAGE_URL = "https://dankook.ac.kr/campusmap"
_P = "_dku_org_CampusMapPortlet_"
RESOURCE_URL = (PAGE_URL + "?p_p_id=dku_org_CampusMapPortlet&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view"
                "&p_p_cacheability=cacheLevelPage&" + _P + "cmd={cmd}")
CAMPUS_TABS = {"죽전": 1, "천안": 2}

# 공식 이름에서 자동으로 못 뽑는 흔한 부름말 (괄호 속 이름·'/'로 나뉜 이름은 자동으로 별칭이 된다)
EXTRA_ALIASES = {
    "소프트웨어 ICT관": ["ICT관", "SW관", "소프트웨어관"],
    "퇴계기념중앙도서관": ["중앙도서관", "도서관", "중도"],
    "범정관(대학본부)": ["본관"],
    "혜당관(학생회관)": ["학관"],
    "평화의광장": ["평화의 광장"],
    "곰상": ["곰 동상"],
    "집현재1": ["기숙사", "집현재"],
    "집현재2나동": ["기숙사", "집현재"],
    "웅비홀(남자)": ["기숙사"],
    "행복기숙사(진리관)": ["기숙사"],
}


# 질문에 쓸모없이 많기만 한 호실 (기숙사 방 수백 개 등)
SKIP_ROOM = re.compile(r"^(사생실|복도 및 계단$)")


def data_url(tab: int) -> str:
    return RESOURCE_URL.format(cmd="data") + f"&{_P}tab={tab}&{_P}category=0"


def facility_url(facility_id: str | int) -> str:
    return RESOURCE_URL.format(cmd="facility") + f"&{_P}id={facility_id}"


def parse_facility_list(payload: dict) -> list[dict]:
    """cmd=data 응답 → [{id, name, lat, lng}] (건물·시설만)."""
    if not payload.get("status"):
        raise ValueError("캠퍼스맵 건물 목록 응답이 실패로 왔습니다")
    out = []
    for f in payload.get("data") or []:
        if f.get("type") != "facility" or not f.get("name"):
            continue
        out.append({"id": str(f["id"]), "name": str(f["name"]).strip(),
                    "lat": round(float(f["lat"]), 7), "lng": round(float(f["lng"]), 7)})
    return out


def parse_facility_detail(payload: dict) -> dict:
    """cmd=facility 응답 → {desc, rooms: [{floor, room, name, eng_name, category}]} (층·호수 순)."""
    if not payload.get("status"):
        raise ValueError("캠퍼스맵 건물 정보 응답이 실패로 왔습니다")
    data = payload.get("data") or {}
    rooms = []
    for r in data.get("rooms") or []:
        name = (r.get("roomHpKnm") or "").strip()
        if not name or SKIP_ROOM.match(name):
            continue
        rooms.append({"floor": str(r.get("flrId") or "").strip(), "room": str(r.get("roomNb") or "").strip(),
                      "name": name, "eng_name": (r.get("roomHpEnm") or "").strip(),
                      "category": (r.get("hpClsfNm") or "").strip()})
    rooms.sort(key=lambda r: (_floor_order(r["floor"]), r["room"]))
    return {"desc": _clean(data.get("facilDesc")), "rooms": rooms}


def _clean(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(s or ""))).strip()


def _floor_order(floor: str) -> float:
    m = re.fullmatch(r"(B|-)?(\d+)", floor.upper())
    if not m:
        return 999
    n = int(m.group(2))
    return -n if m.group(1) else n


MAX_FLOOR = 30  # 야외 시설(곰상 등)에 '71' 같은 의미 없는 층 값이 들어 있다


def floor_label(floor: str) -> str:
    m = re.fullmatch(r"(B|-)?(\d+)", (floor or "").upper())
    if not m:
        return floor or ""
    if int(m.group(2)) > MAX_FLOOR:
        return ""
    return f"지하 {m.group(2)}층" if m.group(1) else f"{m.group(2)}층"


_GENERIC_PART = {"남자", "여자", "남", "여"}


def aliases_of(name: str) -> list[str]:
    """'혜당관(학생회관)' → [혜당관, 학생회관], '법학관/대학원동' → [법학관, 대학원동] + EXTRA_ALIASES.
    괄호 속이 '남자'나 '범정 장형 선생'처럼 이름이 아닌 설명이면 별칭으로 쓰지 않는다 (엉뚱한 검색에 걸린다)."""
    parts = [p.strip() for p in re.split(r"[()/]", name) if p.strip()]
    found = [p for p in parts if " " not in p and p not in _GENERIC_PART] if len(parts) > 1 else []
    found += EXTRA_ALIASES.get(name, [])
    return list(dict.fromkeys(a for a in found if a != name))


def map_link(name: str, lat: float, lng: float) -> str:
    """카카오맵 위치 링크 (열면 그 자리에 핀이 찍히고 길찾기를 할 수 있다)."""
    return f"https://map.kakao.com/link/map/{quote(name, safe='')},{lat},{lng}"


def load_campus_map(path: Path) -> list[dict]:
    """스냅숏 파일 → campus_map 레코드 (건물 1건 + 호실 n건씩). 파일이 없으면 빈 목록."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        log.warning("캠퍼스맵 스냅숏이 없습니다: %s (scripts.collect_campus_map으로 만드세요)", path)
        return []
    collected = str(raw.get("collected_at") or "")
    records: list[dict] = []
    for campus, buildings in (raw.get("campuses") or {}).items():
        for b in buildings or []:
            base = {"org": campus, "building": b["name"], "aliases": aliases_of(b["name"]),  # 별칭은 읽을 때 붙인다
                    "lat": b["lat"], "lng": b["lng"], "collected_at": collected}
            records.append({**base, "kind": "building", "desc": b.get("desc") or "", "floor": "", "room": "",
                            "name": b["name"], "eng_name": "", "category": ""})
            for r in b.get("rooms") or []:
                records.append({**base, "kind": "room", "desc": "", **r})
    return records
