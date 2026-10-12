"""사용자 본인 자료 도구: my_schedule (eclass 캘린더 피드).

도구 정의는 늘 같다 (프롬프트 캐시). 누구의 자료인지는 인자가 아니라 personal.CURRENT_USER에서만 읽는다.
연결이 없으면 오류가 아니라 '연결 필요' 결과를 돌려준다. 첫 줄의 CONNECT_MARK를 보고 웹 화면이 연결 버튼을 띄운다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ...llm.base import ToolSpec
from ...personal.context import CURRENT_USER
from ...personal.eclass import CALENDAR_URL, EclassError, EclassService, NotConnected
from ...personal.ics import KST
from .registry import Tool, ToolError

CONNECT_MARK = "[eclass 연결 필요]"
DEFAULT_DAYS = 14
MAX_ITEMS = 30
WEEKDAYS = "월화수목금토일"

SPEC = ToolSpec(
    name="my_schedule",
    description=(
        "질문한 사용자 본인의 eclass(Canvas) 캘린더에서 과제 마감·강의 일정을 찾는다. "
        "사용자가 웹 화면에서 자기 eclass 캘린더를 연결해 둔 경우에만 결과가 있고, 연결이 없으면 그 사실과 연결 방법을 돌려준다. "
        "들어 있는 것: 과제명·과목·마감 날짜(시각이 있으면 시각)·설명 앞부분. "
        "들어 있지 않은 것: 제출 여부, 성적, 강의 공지 — 이미 냈는지는 알 수 없다고 안내한다. "
        "마감 시각이 없는 항목은 시각을 추측하지 않는다. 기간을 주지 않으면 오늘부터 14일."
    ),
    parameters={
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "시작 날짜 YYYY-MM-DD (기본: 오늘). 지난 과제를 물으면 과거 날짜"},
            "end": {"type": "string", "description": "끝 날짜 YYYY-MM-DD (포함, 기본: 시작 + 14일)"},
            "keyword": {"type": "string", "description": "과목명·과제명 일부 (예: '심리학', '보고서')"},
        },
    },
)


def _day(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ToolError(f"{name}은 YYYY-MM-DD 형식이어야 합니다: {value}")


def _norm(s: str) -> str:
    return "".join(s.split()).lower()


def make_my_schedule(service: EclassService | None) -> Tool:
    def my_schedule(start: str | None = None, end: str | None = None, keyword: str | None = None) -> str:
        user = CURRENT_USER.get()
        if user is None:
            return ("eclass 일정은 웹 채팅에 학교 Google 계정으로 로그인하고 eclass 캘린더를 연결한 사용자만 볼 수 있습니다. "
                    "지금 사용 중인 곳(카카오톡 등)에서는 개인 일정을 확인할 수 없다고 안내하세요.")
        if service is None or not service.enabled:
            return "이 서버에서는 eclass 연결 기능이 꺼져 있습니다. 개인 일정은 eclass에서 직접 확인하도록 안내하세요."
        try:
            fetched = service.events(user.user_id)
        except NotConnected:
            return (f"{CONNECT_MARK} 이 사용자는 아직 eclass 캘린더를 연결하지 않았습니다. "
                    "웹 화면 왼쪽 사이드바의 'eclass 일정 연결'에서 Canvas 캘린더 피드 주소를 등록하면 "
                    "과제 마감을 물어볼 수 있다고 안내하세요. (답변 아래에 연결 버튼이 표시됩니다)")
        except EclassError as e:
            raise ToolError(str(e))

        today = datetime.now(KST).date()
        lo = _day(start, "start") or today
        hi = _day(end, "end") or lo + timedelta(days=DEFAULT_DAYS)
        if hi < lo:
            lo, hi = hi, lo
        kw = _norm(keyword or "")
        hits = [e for e in fetched.events if lo <= e.day <= hi and (not kw or kw in _norm(f"{e.course} {e.title}"))]
        got = datetime.fromtimestamp(fetched.fetched_at, KST).strftime("%m-%d %H:%M")
        note = " — eclass에서 새로 받지 못해 이전에 받은 결과입니다" if fetched.stale else ""
        cond = f"{lo} ~ {hi}" + (f", '{keyword}'" if keyword else "")
        head = (f"[source: eclass] 내 eclass 캘린더 ({cond}) — {len(hits)}건 "
                f"(전체 {len(fetched.events)}건 중, {got} 기준{note})\n원문: {CALENDAR_URL}\n"
                "제출 여부·성적은 이 자료에 없습니다. '시각 미표기'는 eclass가 날짜만 준 마감입니다.")
        if not hits:
            later = [e for e in fetched.events if e.day > hi]
            nxt = f" 다음 일정: {later[0].day} {later[0].title}" if later else ""
            return head + f"\n이 기간에 해당하는 일정이 없습니다.{nxt}"
        lines = []
        for e in hits[:MAX_ITEMS]:
            when = f"{e.day.isoformat()}({WEEKDAYS[e.day.weekday()]}) {e.time or '시각 미표기'}"
            line = f"- {when} [{e.kind}] {e.title}" + (f" · {e.course}" if e.course else "")
            if e.description:
                line += f"\n  설명: {e.description}"
            lines.append(line)
        more = f"\n…(그 밖에 {len(hits) - MAX_ITEMS}건. 기간을 좁혀 다시 찾으세요)" if len(hits) > MAX_ITEMS else ""
        return head + "\n" + "\n".join(lines) + more

    return Tool(SPEC, my_schedule, status=lambda args: "eclass 일정을 확인하는 중")
