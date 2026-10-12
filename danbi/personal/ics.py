"""iCalendar(.ics) 피드 → 일정 레코드. 외부 라이브러리 없이 eclass(Canvas)가 내보내는 만큼만 읽는다.

Canvas 피드는 표준과 조금 다르다: 날짜 전용 마감이 `DTSTART;VALUE=DATE:20260922T000000`처럼 시각까지 붙어 나온다.
그래서 VALUE=DATE면 앞 8자리만 날짜로 쓰고 시각은 없는 것으로 본다 (시각을 추측하지 않는다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
MAX_DESCRIPTION = 160
_COURSE = re.compile(r"\s*\[([^\[\]]+)\]\s*$")


@dataclass
class CalendarEvent:
    uid: str
    kind: str              # 과제 | 일정
    title: str
    course: str            # 제목 끝 [과목 분반]에서 뽑는다. 없으면 ""
    day: date              # 한국 시간 기준 날짜
    time: str | None       # "HH:MM" (한국 시간). 날짜만 있는 항목은 None
    url: str = ""
    description: str = ""


def _unfold(text: str) -> list[str]:
    # RFC 5545: 공백·탭으로 시작하는 줄은 앞 줄에 이어 붙인다
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def _unescape(value: str) -> str:
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def _split(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    name, *params = head.split(";")
    return name.upper(), {k.upper(): v for k, _, v in (p.partition("=") for p in params)}, value


def _when(params: dict[str, str], value: str) -> tuple[date, str | None] | None:
    value = value.strip()
    if not re.match(r"\d{8}", value):
        return None
    d = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    m = re.match(r"\d{8}T(\d{2})(\d{2})(\d{2})(Z?)$", value)
    if params.get("VALUE", "").upper() == "DATE" or not m:
        return d, None
    dt = datetime(d.year, d.month, d.day, int(m.group(1)), int(m.group(2)))
    if m.group(4):  # UTC → 한국 시간. TZID가 붙은 값과 떠 있는 시각은 한국 시간으로 본다 (학교 Canvas)
        dt = dt.replace(tzinfo=timezone.utc).astimezone(KST)
    return dt.date(), dt.strftime("%H:%M")


def _short(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= MAX_DESCRIPTION else text[:MAX_DESCRIPTION].rstrip() + "…"


def parse_ics(text: str) -> list[CalendarEvent]:
    """VEVENT마다 일정 하나. 날짜가 없거나 읽을 수 없는 항목은 건너뛴다. 날짜·시각 순으로 정렬한다."""
    events: list[CalendarEvent] = []
    cur: dict[str, tuple[dict[str, str], str]] | None = None
    for line in _unfold(text):
        if line.upper() == "BEGIN:VEVENT":
            cur = {}
        elif line.upper() == "END:VEVENT":
            if cur is not None:
                ev = _event(cur)
                if ev is not None:
                    events.append(ev)
            cur = None
        elif cur is not None and ":" in line:
            name, params, value = _split(line)
            cur.setdefault(name, (params, value))
    return sorted(events, key=lambda e: (e.day, e.time or "99:99", e.title))


def _event(props: dict[str, tuple[dict[str, str], str]]) -> CalendarEvent | None:
    if "DTSTART" not in props:
        return None
    when = _when(*props["DTSTART"])
    if when is None:
        return None
    uid = props.get("UID", ({}, ""))[1].strip()
    summary = _unescape(props.get("SUMMARY", ({}, ""))[1]).strip()
    m = _COURSE.search(summary)
    course = m.group(1).strip() if m else ""
    title = summary[: m.start()].strip() if m else summary
    return CalendarEvent(
        uid=uid, kind="과제" if "assignment" in uid else "일정", title=title or "(제목 없음)", course=course,
        day=when[0], time=when[1], url=props.get("URL", ({}, ""))[1].strip(),
        description=_short(_unescape(props.get("DESCRIPTION", ({}, ""))[1])),
    )
