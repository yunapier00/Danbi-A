"""query_data의 필터링·출력. 레코드 형식은 crawler/adapters/base.py 주석 참고."""

from __future__ import annotations

import re
from collections import OrderedDict

from ...sources.campus_map import floor_label, map_link

MAX_ROWS = 100
SUMMARY_ROWS = 8  # 결과가 이 수 이하이거나 keyword 검색이면 과목 개요도 보여준다
SUMMARY_CHARS = 150


def _has(text: str, needle: str) -> bool:
    return needle.replace(" ", "").lower() in (text or "").replace(" ", "").lower()


def filter_records(kind: str, records: list[dict], *, name: str | None = None, keyword: str | None = None,
                   grade: int | None = None, semester: int | None = None, category: str | None = None,
                   org: str | None = None, month: int | None = None, on_date: str | None = None) -> list[dict]:
    out = []
    for r in records:
        if org and not _has(r.get("org", ""), org):
            continue
        if kind == "calendar":
            if keyword and not _has(r["title"], keyword):
                continue
            if month and not _overlaps_month(r, month):
                continue
            if on_date and not (r["start"] <= on_date <= r["end"]):
                continue
            out.append(r)
            continue
        if kind == "campus_map":
            if _campus_match(r, name, keyword, category):
                out.append(r)
            continue
        if kind == "timetable":
            if _timetable_match(r, name, keyword, grade, category, org):
                if grade or category or org:  # 조건에 맞는 수강대상을 앞으로 (레코드는 공유되므로 복사본에서)
                    hit = lambda t: _target_hit(t, grade, category, org)  # noqa: E731
                    r = {**r, "targets": sorted(r["targets"], key=lambda t: not hit(t))}
                out.append(r)
            continue
        if kind == "menu":
            if (keyword or name) and not _has(r["name"], keyword or name):
                continue
            if category and not _has(r["corner"], category):
                continue
            out.append(r)
            continue
        if kind == "professors":
            if name and not (_has(r["name"], name) or _has(r["eng_name"], name)):
                continue
            if keyword and not any(_has(str(r.get(k, "")), keyword) for k in ("position", "role", "office", "name")):
                continue
        elif kind == "curriculum":
            if name and not (_has(r["name"], name) or _has(r["eng_name"], name)):
                continue
            if keyword and not any(_has(r.get(k, ""), keyword) for k in ("name", "eng_name", "summary")):
                continue
            if category and not any(_has(r.get(k, ""), category) for k in ("category", "group", "program")):
                continue
            if grade or semester:
                want = [s for s in r["semesters"]
                        if (not grade or s.startswith(f"{grade}-")) and (not semester or s.endswith(f"-{semester}"))]
                if not want:
                    continue
        out.append(r)
    return out


_FLOOR_Q = re.compile(r"(지하\s*|B)?(\d+)\s*층", re.I)


def _building_match(r: dict, q: str) -> bool:
    return _has(r["building"], q) or any(_has(a, q) for a in r["aliases"])


def _room_match(r: dict, q: str) -> bool:
    if r["kind"] != "room":
        return False
    if m := _FLOOR_Q.fullmatch(q.strip()):
        return r["floor"].upper() == (f"B{m.group(2)}" if m.group(1) else m.group(2))
    return (_has(r["name"], q) or (bool(r["eng_name"]) and _has(r["eng_name"], q))
            or (bool(r["category"]) and _has(r["category"], q))  # '식당' → 식당/매점 분류의 1947_commons
            or r["room"].upper() == q.strip().removesuffix("호").upper())


def _campus_match(r: dict, name: str | None, keyword: str | None, category: str | None) -> bool:
    """name=건물, keyword=부서·시설·호수·층, category=분류. 한 가지만 주면 건물 이름이나 호실 어느 쪽이든 맞으면 된다.
    건물 자체가 맞으면 그 건물 레코드와 호실 전체를, 호실만 맞으면 그 호실만 고른다. 조건이 없으면 건물 목록만."""
    if category and not (r["kind"] == "room" and (_has(r["category"], category) or _has(r["name"], category))):
        return False
    if name and keyword:
        return _building_match(r, name) and _room_match(r, keyword)
    q = name or keyword
    if q:
        return _building_match(r, q) or _room_match(r, q)
    return bool(category) or r["kind"] == "building"


def _overlaps_month(r: dict, month: int) -> bool:
    """일정 기간이 그 달(어느 해든 학년도 안의 그 달)과 겹치는지."""
    start, end = r["start"][:7], r["end"][:7]
    year = int(r["start"][:4])
    for y in (year, year + 1):
        ym = f"{y}-{month:02d}"
        if start <= ym <= end:
            return True
    return False


def format_records(kind: str, records: list[dict], *, verbose: bool = False) -> str:
    if kind == "campus_map":
        return _campus_map(records)
    if kind == "timetable":
        return _timetable(records)
    if kind == "calendar":
        lines = [f"- {r['start']}" + (f" ~ {r['end']}" if r["end"] != r["start"] else "") + f" | {r['title']}"
                 for r in records[:MAX_ROWS]]
        if len(records) > MAX_ROWS:
            lines.append(f"…(전체 {len(records)}건 중 {MAX_ROWS}건만 표시. month·keyword로 좁히세요)")
        return "\n".join(lines)
    if kind == "menu":
        lines, group = [], None
        for r in records[:MAX_ROWS * 2]:
            if (r["org"], r["corner"]) != group:
                group = (r["org"], r["corner"])
                lines.append(f"### {r['org']} · {r['corner']}" if r["org"] else f"### {r['corner']}")
            price = f"{r['price']:,}원" if isinstance(r.get("price"), int) else "가격 미상"
            lines.append(f"- {r['name']} {price}" + (" (품절)" if r["sold_out"] else ""))
        return "\n".join(lines)
    if kind == "professors":
        return "\n".join(_professor(r) for r in records)
    if kind == "dept_info":
        return "\n\n".join(_dept(r) for r in records)
    if kind == "curriculum":
        return _curriculum(records, verbose)
    return "\n".join(str(r) for r in records)


def _professor(r: dict) -> str:
    head = f"- {r['name']}" + (f" ({r['eng_name']})" if r["eng_name"] else "") + f" — {r['position']}"
    fields = [("보직", r["role"]), ("소속", r["org"]), ("연구실", r["office"]), ("전화", r["tel"]),
              ("이메일", r["email"]), ("홈페이지", r["homepage"]), ("교수 정보", r["detail_url"])]
    lines = [head] + [f"  {k}: {v}" for k, v in fields if v]
    lines += [f"  학력: {e}" for e in r.get("education") or [] if e]
    return "\n".join(lines)


def _dept(r: dict) -> str:
    parts = [f"## {r['name']}" + (f" (정보 수정일: {r['updated']})" if r.get("updated") else "")]
    parts += [f"### {k}\n{v}" for k, v in r["sections"].items()]
    if r["contact"]:
        parts.append("### 연락처\n" + "\n".join(f"- {k}: {v}" for k, v in r["contact"].items()))
    return "\n\n".join(parts)


def _curriculum(records: list[dict], verbose: bool) -> str:
    rows = ["| 소속 | 구분 | 이수구분 | 과목명 | 학점 | 개설 학년-학기 |", "|---|---|---|---|---|---|"]
    for r in records[:MAX_ROWS]:
        program = r["program"] if r["group"] in ("", r["category"]) else f"{r['program']} {r['group']}"
        name = r["name"] + (f" ({r['eng_name']})" if r["eng_name"] and r["eng_name"] != r["name"] else "")
        rows.append(f"| {r['org']} | {program} | {r['category']} | {name} | {r['credit']} | {', '.join(r['semesters']) or '-'} |")
    out = "\n".join(rows)
    if len(records) > MAX_ROWS:
        out += f"\n…(전체 {len(records)}과목 중 {MAX_ROWS}과목만 표시. 학년·학기·이수구분으로 좁히세요)"
    if verbose:
        summaries = [
            f"- {r['name']}: {r['summary'][:SUMMARY_CHARS]}" + ("…" if len(r["summary"]) > SUMMARY_CHARS else "")
            for r in records[:SUMMARY_ROWS] if r["summary"]
        ]
        if summaries:
            out += "\n\n과목 개요:\n" + "\n".join(summaries)
    return out


CAMPUS_LIST_LIMIT = 8      # 건물이 이보다 많으면 링크 없이 이름만 나열한다
FLOOR_CHARS = 300          # 건물 전체를 보여줄 때 층별 줄의 최대 길이


def _room_no(r: dict) -> str:
    room = r["room"]
    return "" if not room or re.fullmatch(r"0+\d*", room) else f"{room}호"  # 0001 같은 번호는 시설 표시용


def _campus_map(records: list[dict]) -> str:
    groups: OrderedDict[tuple, list[dict]] = OrderedDict()
    for r in records:
        groups.setdefault((r["org"], r["building"]), []).append(r)
    if len(groups) > CAMPUS_LIST_LIMIT and all(r["kind"] == "building" for r in records):
        lines = [f"- {r['org']} · {r['building']}" + (f" (별칭: {', '.join(r['aliases'])})" if r["aliases"] else "")
                 for r in records]
        return "\n".join(lines + ["(건물 이름을 name으로 주면 지도 링크와 층별 호실을 보여줍니다)"])
    full = [k for k, rs in groups.items() if any(r["kind"] == "building" for r in rs)]
    expand = len(full) == 1  # 건물 하나가 통째로 맞았을 때만 층별 호실을 펼친다 (여러 건물이면 너무 길다)
    out, shown = [], 0
    for key, rs in groups.items():
        first = rs[0]
        alias = f" (별칭: {', '.join(first['aliases'])})" if first["aliases"] else ""
        out.append(f"### {first['org']} · {first['building']}{alias}")
        out.append(f"지도: {map_link(first['building'], first['lat'], first['lng'])}")
        if desc := next((r["desc"] for r in rs if r["kind"] == "building" and r["desc"]), ""):
            out.append(f"설명: {desc}")
        rooms = [r for r in rs if r["kind"] == "room" and r["name"] != r["building"]]  # 곰상 = 곰상 같은 중복 제외
        if key in full and not expand:
            if rooms:
                out.append(f"(호실 {len(rooms)}곳 — 건물을 하나로 좁히면 층별로 보여줍니다)")
            continue
        if key in full:
            out += _floors(rooms)
            continue
        for r in rooms:
            if shown >= MAX_ROWS:
                break
            shown += 1
            where = " ".join(x for x in (floor_label(r["floor"]), _room_no(r)) if x)
            out.append(f"- {where + ' · ' if where else ''}{r['name']}" + (f" [{r['category']}]" if r["category"] else ""))
    rooms_total = sum(1 for r in records if r["kind"] == "room")
    if shown >= MAX_ROWS and rooms_total > shown:
        out.append(f"…(호실 {rooms_total}곳 중 {MAX_ROWS}곳만 표시. name·keyword로 좁히세요)")
    return "\n".join(out)


def _floors(rooms: list[dict]) -> list[str]:
    """건물 전체: 층별 한 줄 ('강의실'처럼 같은 이름이 여럿이면 묶는다)."""
    by_floor: OrderedDict[str, OrderedDict[str, list[str]]] = OrderedDict()
    for r in rooms:
        by_floor.setdefault(r["floor"], OrderedDict()).setdefault(r["name"], []).append(_room_no(r))
    lines = []
    for floor, names in by_floor.items():
        parts = []
        for nm, nos in names.items():
            nos = [n for n in nos if n]
            parts.append(f"{nm} {nos[0]}" if len(nos) == 1 else f"{nm}({len(nos)}곳)" if nos else nm)
        text = ", ".join(parts)
        if len(text) > FLOOR_CHARS:
            text = text[:FLOOR_CHARS].rsplit(", ", 1)[0] + " …"
        lines.append(f"- {floor_label(floor) or '층 미상'}: {text}")
    return lines


# ---- 강의시간표 ----

MAX_SECTIONS = 40          # 분반이 이보다 많으면 앞부분만 보여주고 좁히라고 안내한다
TARGETS_SHOWN = 2          # 분반마다 보여줄 수강대상 수 (나머지는 '외 n곳')
_DAY_Q = re.compile(r"([월화수목금토일])(?:요일)?")


def _timetable_match(r: dict, name: str | None, keyword: str | None, grade: int | None,
                     category: str | None, org: str | None) -> bool:
    """name=과목명·교강사, keyword=요일·강의실·교과목번호·비고. 학년·이수구분·수강조직은 같은 수강대상 하나가 모두 맞아야 한다."""
    if name and not (_has(r["name"], name) or _has(r["professor"], name)):
        return False
    if keyword:
        kw = keyword.strip().removesuffix("호")
        if m := _DAY_Q.fullmatch(kw):
            if not any(s["day"] == m.group(1) for s in r["slots"]):
                return False
        elif not (any(_has(r[k], kw) for k in ("name", "professor", "subj_id", "note", "change", "mode"))
                  or any(_has(s["room_raw"], kw) or _has(f"{s['building'] or ''}{s['room']}", kw) for s in r["slots"])):
            return False
    if grade or category or org:
        return any(_target_hit(t, grade, category, org) for t in r["targets"])
    return True


def _target_hit(t: dict, grade: int | None, category: str | None, org: str | None) -> bool:
    return ((not grade or t["grade"] == str(grade)) and (not category or _has(t["category"], category))
            and (not org or _has(t["org"], org)))


def _slot_text(s: dict) -> str:
    where = f"{s['building']} {s['room']}호" if s["building"] else s["room_raw"]
    return f"{s['day']} {s['from']}–{s['to']} ({s['start']}~{s['end']}교시)" + (f" {where}" if where else "")


def _targets_text(targets: list[dict]) -> str:
    shown = [f"{t['grade']}학년 {t['org']}" if t["grade"] and t["grade"] != "0" else t["org"] for t in targets]
    shown = list(dict.fromkeys(shown))
    more = f" 외 {len(shown) - TARGETS_SHOWN}곳" if len(shown) > TARGETS_SHOWN else ""
    return ", ".join(shown[:TARGETS_SHOWN]) + more


def _timetable(records: list[dict]) -> str:
    """과목별로 묶고 분반마다 한 줄: 교강사 | 요일·시각·강의실 | 수강대상 | 비고."""
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for r in records[:MAX_SECTIONS]:
        groups.setdefault(r["subj_id"], []).append(r)
    out = []
    for rs in groups.values():
        first = rs[0]
        cats = list(dict.fromkeys(t["category"] for r in rs for t in r["targets"] if t["category"]))
        credit = f"{first['credits']}학점" + (f"(설계 {first['design']})" if first["design"] else "")
        out.append(f"### {first['name']} · {first['subj_id']} · {credit}" + (f" · {'/'.join(cats[:3])}" if cats else ""))
        for r in rs:
            times = " / ".join(_slot_text(s) for s in r["slots"]) or "시간 미정"
            extra = [x for x in ("영어강의" if r["english"] else "", r["mode"] if r["mode"] != "대면수업" else "",
                                 f"비고: {r['note']}" if r["note"] else "", f"변경: {r['change']}" if r["change"] else "") if x]
            out.append(f"- {r['section']}분반 {r['professor'] or '교강사 미정'} | {times} | 대상: {_targets_text(r['targets'])}"
                       + (f" | {' | '.join(extra)}" if extra else ""))
    if len(records) > MAX_SECTIONS:
        out.append(f"…(분반 {len(records)}개 중 {MAX_SECTIONS}개만 표시. 과목명·교강사·학년·수강조직(org)·요일로 좁히세요)")
    return "\n".join(out)
