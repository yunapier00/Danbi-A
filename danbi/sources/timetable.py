"""종합강의시간표: 사람이 브라우저에서 조회해 저장한 시간표 화면(HTML)을 강좌 데이터로 바꾼다.

webinfo.dankook.ac.kr은 robots.txt가 전체 수집을 막으므로(Disallow: /) 단비는 그 서버에 요청하지 않는다.
학기마다 사람이 시간표 조회 화면(교양·전공·학문기초 검색)을 저장하면 scripts/build_timetable.py가
config/timetable.json을 만들고, query_data(dataset=timetable)가 이 파일을 읽는다.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

PAGE_URL = "https://webinfo.dankook.ac.kr/tiac/univ/lssn/lpci/views/lssnPopup/tmtbl.do"
TABLE_ID = "mjLctTmtblDscTbl"
COLUMNS = ["학년", "이수구분", "교과목 번호", "교과목명", "분반", "영어", "학점 (설계)", "교강사", "요일/교시/강의실",
           "변경내역", "수업방법 및 비고", "수업유형", "수강조직"]  # 학문기초 검색은 끝에 '주수강조직'이 더 있다

# 교시 → 시각 (2026-2학기 종합강의시간표 안내자료 'VI-7. 강의시간표'). 주간은 09:00부터 30분 단위, 야간(19~24)은 50분 단위.
NIGHT = {19: ("18:00", "18:50"), 20: ("18:55", "19:45"), 21: ("19:50", "20:40"),
         22: ("20:45", "21:35"), 23: ("21:40", "22:30"), 24: ("22:35", "23:25")}

# 강의실 표기의 건물 줄임말 → 캠퍼스맵(죽전) 건물 이름. 모르는 줄임말은 원래 표기를 그대로 보여준다.
ROOM_BUILDINGS = {
    "1공": "제1공학관", "2공": "제2공학관", "3공": "제3공학관", "소프트": "소프트웨어 ICT관", "인문": "인문관",
    "상경": "상경관", "사범": "사범관", "국제": "국제관", "미디어": "미디어센터", "사회": "사회과학관",
    "대학원동": "법학관/대학원동", "음악": "난파음악관", "미술": "미술관", "글로컬산학협력관": "글로컬산학협력관",
    "체": "체육관", "체육": "체육관", "무용": "무용관", "학군단": "학군단", "메종트리앙글르": "메종트리앙글르",
    "종합실험동": "종합실험동",
}
DAYS = "월화수목금토일"
_SLOT = re.compile(r"([월화수목금토일])(\d+)(?:~(\d+))?(?:\((.*)\))?")
_ROOM = re.compile(r"(.*?)(B?\d[\dA-Za-z\-]*)")


def period_time(period: int) -> tuple[str, str]:
    if period in NIGHT:
        return NIGHT[period]
    start = 9 * 60 + (period - 1) * 30
    return f"{start // 60:02d}:{start % 60:02d}", f"{(start + 30) // 60:02d}:{(start + 30) % 60:02d}"


def parse_room(raw: str) -> tuple[str | None, str]:
    """'소프트406' → ('소프트웨어 ICT관', '406'), '체B104' → ('체육관', 'B104'). 모르면 (None, 원래 표기)."""
    m = _ROOM.fullmatch(raw.strip())
    if m and m.group(1) in ROOM_BUILDINGS:
        return ROOM_BUILDINGS[m.group(1)], m.group(2)
    return None, raw.strip()


def parse_slots(parts: list[str]) -> list[dict]:
    """['월16~18(인문320)', '화16~18(인문320)'] → [{day, start, end, from, to, room_raw, building, room}]."""
    slots = []
    for part in parts:
        m = _SLOT.fullmatch(part.strip())
        if not m:
            log.warning("시간표 칸을 해석하지 못했습니다: %r", part)
            continue
        start = int(m.group(2))
        end = int(m.group(3) or start)
        building, room = parse_room(m.group(4)) if m.group(4) else (None, "")
        slots.append({"day": m.group(1), "start": start, "end": end, "from": period_time(start)[0],
                      "to": period_time(end)[1], "room_raw": m.group(4) or "", "building": building, "room": room})
    return slots


def _cell_parts(td) -> list[str]:
    return [s for s in td.stripped_strings]


def parse_html(html: str) -> list[dict]:
    """저장한 시간표 화면 → 행 목록 (한 강좌가 수강조직마다 한 행씩 나온다)."""
    table = BeautifulSoup(html, "lxml").find(id=TABLE_ID)
    if table is None:
        raise ValueError(f"시간표 표(#{TABLE_ID})가 없습니다. 조회 결과가 나온 화면을 저장했는지 확인하세요")
    trs = table.find_all("tr")
    head = [c.get_text(" ", strip=True) for c in trs[0].find_all(["th", "td"])]
    if head[:len(COLUMNS)] != COLUMNS:
        raise ValueError(f"시간표 열 구성이 예상과 다릅니다: {head}")
    rows = []
    for tr in trs[1:]:
        td = tr.find_all("td", recursive=False)
        if len(td) < len(COLUMNS):
            continue
        name_cell = td[3]
        name = next(name_cell.stripped_strings, "").strip()  # 뒤의 '국문'/'ENG'는 강의계획서 버튼
        credit = re.fullmatch(r"(\d+)\((\d+)\)", td[6].get_text(strip=True))
        rows.append({
            "grade": td[0].get_text(strip=True), "category": td[1].get_text(strip=True),
            "subj_id": td[2].get_text(strip=True), "name": name, "section": td[4].get_text(strip=True),
            "english": td[5].get_text(strip=True) == "영어",
            "credits": int(credit.group(1)) if credit else None, "design": int(credit.group(2)) if credit else 0,
            "professor": td[7].get_text(" ", strip=True), "slots": parse_slots(_cell_parts(td[8])),
            "change": td[9].get_text(" ", strip=True), "note": td[10].get_text(" ", strip=True),
            "mode": td[11].get_text(strip=True), "org": " ".join(_cell_parts(td[12])),
            "main_org": " ".join(_cell_parts(td[13])) if len(td) > 13 else "",
        })
    return rows


def build_sections(rows: list[dict]) -> list[dict]:
    """행 → 강좌(교과목번호·분반)별 하나. 학년·이수구분은 수강조직마다 다를 수 있어 targets로 모은다."""
    sections: dict[tuple, dict] = {}
    for r in rows:
        key = (r["subj_id"], r["section"])
        sec = sections.get(key)
        if sec is None:
            sec = sections[key] = {k: r[k] for k in ("subj_id", "section", "name", "english", "credits", "design",
                                                    "professor", "slots", "change", "note", "mode")}
            sec["targets"], sec["main_org"] = [], ""
        target = {"grade": r["grade"], "category": r["category"], "org": r["org"]}
        if target not in sec["targets"]:
            sec["targets"].append(target)
        sec["main_org"] = sec["main_org"] or r["main_org"]
    return sorted(sections.values(), key=lambda s: (s["name"], s["subj_id"], _int(s["section"])))


def _int(s: str) -> int:
    return int(s) if s.isdigit() else 0


def load_timetable(path: Path) -> list[dict]:
    """config/timetable.json → timetable 레코드. 파일이 없으면 빈 목록."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("강의시간표 저장본이 없습니다: %s (scripts.build_timetable로 만드세요)", path)
        return []
    meta = {"term": raw.get("term", ""), "collected_at": raw.get("saved_at", "")}
    # org: 수강조직을 이어 붙인 문자열 (query_data의 org 조건이 그대로 쓴다)
    return [{**s, **meta, "org": " | ".join(dict.fromkeys(t["org"] for t in s["targets"]))}
            for s in raw.get("sections") or []]
