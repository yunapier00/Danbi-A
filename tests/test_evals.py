"""평가 채점 로직 (API 불필요)."""

import pytest

from danbi.llm.base import ToolCall
from evals.run import load_questions, select, summarize
from evals.scoring import score, used_sources


def call(name, **args):
    return ToolCall("x", name, args)


def test_used_sources_mapping():
    used = used_sources([
        call("search_knowledge", query="q", sources=["학칙"]),
        call("search_site", source="mobilesystems", section="rules_sw", keyword="졸업"),
        call("read_attachment", source="mobilesystems", section="notice", item_id=1, attachment_index=0),
        call("query_data", source="mobilesystems", dataset="professors"),
        call("get_page", source="chem", page="graduation"),
        call("list_sources", query="화학"),
    ])
    assert used == {
        "rag", "rag:학칙", "site:mobilesystems", "site:mobilesystems/rules", "site:mobilesystems/notice",
        "attachment", "data:mobilesystems/professors", "page:chem/graduation", "site:chem", "list_sources",
    }
    assert used_sources([call("search_knowledge", query="q")]) == {"rag", "rag:*"}


def test_unfiltered_rag_search_satisfies_specific_rag_source():
    s = score({"sources": ["rag:셔틀버스"]}, "08:15", [call("search_knowledge", query="셔틀")])
    assert s.source_ok


def test_source_expectations_and_forbid():
    calls = [call("search_site", source="mobilesystems", section="notice", keyword="x")]
    assert score({"sources": ["site:mobilesystems/notice"]}, "", calls).source_ok
    assert score({"sources": ["site:mobilesystems"]}, "", calls).source_ok
    s = score({"sources": ["rag"], "forbid": ["site"]}, "", calls)
    assert not s.source_ok
    assert s.failures == ["써야 할 소스 미사용: rag", "쓰면 안 되는 소스 사용: site"]
    assert score({"sources": ["none"]}, "", []).source_ok
    assert not score({"sources": ["none"]}, "", calls).source_ok


def test_answer_checks():
    expect = {"include": ["의과대학"], "include_any": ["치과", "약학"], "exclude": ["간호"], "no_result": False}
    assert score(expect, "의과대학, 약학대학", []).answer_ok
    s = score(expect, "의과대학, 간호대학", [])
    assert not s.answer_ok and len(s.failures) == 2


def test_no_result_and_call_limit():
    s = score({"no_result": True, "max_tool_calls": 1}, "2025년 공지는 없습니다.", [call("a"), call("b")])
    assert s.no_result_ok and s.answer_ok and not s.calls_ok and not s.passed
    assert score({"no_result": True}, "여기 있습니다: ...", []).no_result_ok is False
    assert score({}, "", []).no_result_ok is None


def test_question_file_is_valid_and_selection():
    qs = load_questions()
    assert len(qs) >= 15
    allowed = {"sources", "forbid", "include", "include_any", "exclude", "no_result", "max_tool_calls"}
    assert len({q["id"] for q in qs}) == len(qs)
    for q in qs:
        assert {"id", "type", "question"} <= set(q)
        assert set(q.get("expect") or {}) <= allowed, q["id"]
    assert [q["id"] for q in select(qs, "professor-office,facility-shuttle", None, None)] == ["facility-shuttle", "professor-office"]
    assert all(q["type"] == "시설" for q in select(qs, None, "시설", None))
    assert len(select(qs, None, None, 2)) == 2
    with pytest.raises(SystemExit):
        select(qs, "nope", None, None)


def test_summary_with_and_without_pricing():
    r = {"id": "a", "type": "t", "passed": True, "answer_ok": True, "source_ok": True, "calls_ok": True,
         "no_result_ok": None, "failures": [], "tool_calls": [{}], "elapsed": 2.0,
         "usage": {"input_tokens": 1_000_000, "output_tokens": 100_000, "cached_tokens": 0}}
    text = summarize([r], {})
    assert "통과: 1/1" in text and "결과 없음 처리: -" in text and "추정 비용" not in text
    assert "추정 비용: $0.5500" in summarize([r], {"input_per_mtok": 0.3, "output_per_mtok": 2.5})
