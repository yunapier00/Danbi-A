"""도구 결과에서 출처(웹 링크·RAG 문서)를 뽑는다. API의 sources 이벤트와 추적 DB가 함께 쓴다.

도구 출력의 줄 머리(`[source: …]`, `URL:`, `게시판:`, `원문:`, `(n) 문서 > 제목 | …`)에 의존하므로
도구 출력 형식을 바꿀 때는 tests/test_ops.py도 함께 확인한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SOURCE_ID = re.compile(r"^\[source: ([\w.-]+)", re.M)
# 줄 맨 앞(get_item의 'URL:', query_data의 '원문:') 또는 헤더 뒤(게시판 목록의 '[source: …] 게시판:')
_URL_LINE = re.compile(r"(?:^|\]\s)(?:URL|게시판|원문): (https?://[^\s,]+(?:, https?://[^\s,]+)*)", re.M)
_SECTION = re.compile(r"^\[source: ([\w.-]+) / section: [\w]+\((.+?)\)\]", re.M)
_TITLE_LINE = re.compile(r"^(?:제목|게시글 제목): (.+?)(?: \| 작성일.*)?$", re.M)
_RAG_HIT = re.compile(r"^\(\d+\) (.+?) \| ", re.M)


@dataclass
class SourceRef:
    kind: str          # web | rag
    source_id: str
    title: str
    url: str = ""
    cited: bool = False


def extract_sources(tool_name: str, text: str) -> list[SourceRef]:
    m = _SOURCE_ID.search(text)
    source_id = m.group(1) if m else ""
    if tool_name == "search_knowledge":
        seen, out = set(), []
        for hit in _RAG_HIT.finditer(text):
            title = hit.group(1).strip()
            if title not in seen:
                seen.add(title)
                out.append(SourceRef("rag", source_id, title))
        return out
    title = t.group(1).strip() if (t := _TITLE_LINE.search(text)) else ""
    if not title and (sec := _SECTION.search(text)):
        title = f"{sec.group(1)} {sec.group(2)}"  # 게시판 목록: '소스 게시판이름'
    return [SourceRef("web", source_id, title, url)
            for line in _URL_LINE.finditer(text) for url in line.group(1).split(", ")]


def mark_cited(refs: list[SourceRef], answer: str) -> None:
    """답변 본문에 링크나 문서명(첫 단계)이 나오면 인용된 것으로 본다 (근사치)."""
    for r in refs:
        if r.url and r.url in answer:
            r.cited = True
        elif r.title:
            head = r.title.split(" > ")[0].split(" [")[0]
            r.cited = bool(head) and head in answer
