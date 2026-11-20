"""학번별 졸업요건 오답(2026-11-20) 재발 방지.

21학번 모시공 질문에 단비가 현행 학칙의 120학점(프리무스국제대학 기준)을 답했다.
정답 140학점은 강의시간표 안내자료의 입학년도별 이수기준표에 있었는데, 소스 설명에
이수기준표가 없어 모델이 그 소스를 검색하지 않았다.
"""
from danbi.agent.prompts import SYSTEM_PROMPT
from danbi.config import load_settings


def test_timetable_guide_description_mentions_entry_year_criteria():
    sources = load_settings().rag.sources
    guide = next(info for name, info in sources.items() if "강의시간표 안내자료" in name)
    assert "입학년도별" in guide.content
    assert "졸업요구학점" in guide.content


def test_prompt_checks_entry_year_rules():
    assert "입학년도별 기준" in SYSTEM_PROMPT
    assert "출처를 넓혀 다시 검색" in SYSTEM_PROMPT


def test_prompt_names_no_specific_source():
    # 프롬프트에는 특정 소스 이름을 넣지 않는다 (prompts.py 머리말)
    for name in ("강의시간표", "학칙 시행세칙", "mobilesystems", "모바일시스템"):
        assert name not in SYSTEM_PROMPT
