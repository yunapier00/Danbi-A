"""평가 채점: 도구 호출 → 사용한 소스, 기대 결과와 비교."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from danbi.llm.base import ToolCall
from danbi.sources.models import section_role

NO_RESULT_PHRASES = (
    "없습니다", "없어요", "없으며", "없고", "찾지 못", "찾을 수 없", "확인되지 않", "등록되어 있지 않",
    "게시되지 않", "운영되지 않", "운영하지 않", "존재하지 않",
)


def used_sources(calls: list[ToolCall]) -> set[str]:
    used: set[str] = set()
    for c in calls:
        a = c.arguments
        if c.name == "search_knowledge":
            used.add("rag")
            filters = a.get("sources") or []
            used |= {f"rag:{s}" for s in filters} if filters else {"rag:*"}
        elif c.name in ("search_site", "latest_items", "get_item", "read_attachment"):
            src, sec = a.get("source", "?"), a.get("section", "?")
            used |= {f"site:{src}", f"site:{src}/{section_role(sec)}"}
            if c.name == "read_attachment":
                used.add("attachment")
        elif c.name == "query_data":
            used |= {f"data:{a.get('source', '?')}/{a.get('dataset', '?')}", f"site:{a.get('source', '?')}"}
        elif c.name == "list_sources":
            used.add("list_sources")
        elif c.name == "get_page":
            used |= {f"page:{a.get('source', '?')}/{a.get('page', '?')}", f"site:{a.get('source', '?')}"}
        else:
            used.add(f"tool:{c.name}")
    return used


def _satisfied(spec: str, used: set[str]) -> bool:
    if spec == "none":
        return not used
    if spec in used:
        return True
    if spec.startswith("rag:") and "rag:*" in used:
        return True
    return any(u.startswith(spec + "/") for u in used)


def _matches_prefix(spec: str, used: set[str]) -> bool:
    return any(u == spec or u.startswith(spec + ":") or u.startswith(spec + "/") for u in used)


@dataclass
class Score:
    answer_ok: bool
    source_ok: bool
    calls_ok: bool
    no_result_ok: bool | None  # no_result 질문만
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.answer_ok and self.source_ok and self.calls_ok


def score(expect: dict[str, Any], answer: str, calls: list[ToolCall]) -> Score:
    used = used_sources(calls)
    failures: list[str] = []

    missing = [s for s in expect.get("sources", []) if not _satisfied(s, used)]
    forbidden = [s for s in expect.get("forbid", []) if _matches_prefix(s, used)]
    if missing:
        failures.append(f"써야 할 소스 미사용: {', '.join(missing)}")
    if forbidden:
        failures.append(f"쓰면 안 되는 소스 사용: {', '.join(forbidden)}")

    answer_ok = True
    lacks = [w for w in expect.get("include", []) if w not in answer]
    if lacks:
        answer_ok = False
        failures.append(f"답변에 없음: {', '.join(lacks)}")
    any_of = expect.get("include_any", [])
    if any_of and not any(w in answer for w in any_of):
        answer_ok = False
        failures.append(f"답변에 다음 중 하나도 없음: {', '.join(any_of)}")
    bad = [w for w in expect.get("exclude", []) if w in answer]
    if bad:
        answer_ok = False
        failures.append(f"답변에 있으면 안 되는 말: {', '.join(bad)}")

    no_result_ok = None
    if expect.get("no_result"):
        no_result_ok = any(p in answer for p in NO_RESULT_PHRASES)
        if not no_result_ok:
            answer_ok = False
            failures.append("'없다'고 답하지 않음")

    max_calls = expect.get("max_tool_calls")
    calls_ok = max_calls is None or len(calls) <= max_calls
    if not calls_ok:
        failures.append(f"도구 호출 {len(calls)}회 > 상한 {max_calls}회")

    return Score(answer_ok, not missing and not forbidden, calls_ok, no_result_ok, failures)
