"""학교 홈페이지 안내 페이지 스냅숏 → rag_sources/학교 홈페이지 안내.md (RAG 원본)

편의시설 운영시간, 증명서·학생증 발급, 주차, 학사 절차(수강신청·다전공·전부과 …), 장학·병무 같은
학교 메인 사이트(dankook.ac.kr)의 공개 안내 페이지를 모아 RAG 문서 하나로 만든다.
  .venv/Scripts/python -m scripts.collect_main_pages
  .venv/Scripts/python -m scripts.build_rag            # 그다음 RAG DB에 반영
LLM을 쓰지 않는다. 페이지 수만큼 요청 (1초 간격, robots.txt 확인). 학기마다 또는 페이지가 바뀌면 다시 돌린다.

자주 바뀌는 게시판(일반공지)은 여기 넣지 않는다 — config/sources.yaml의 dku_main 게시판으로 실시간 조회한다.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import date

from danbi.config import PROJECT_ROOT, load_settings
from danbi.crawler.adapters.dku_cms import parse_page
from danbi.crawler.http import FetchError, HttpClient

log = logging.getLogger("collect_main_pages")

BASE = "https://dankook.ac.kr"
OUT = PROJECT_ROOT / "rag_sources" / "학교 홈페이지 안내.md"

# (경로, 문서 안 제목). 학생이 자주 묻는 것 위주로 골랐다 (2026-11-02). 소개·홍보 페이지는 넣지 않는다
PAGES = [
    ("/-525", "죽전캠퍼스 편의시설"),
    ("/-526", "천안캠퍼스 편의시설"),
    ("/-68", "주차요금 안내"),
    ("/-70", "불법주정차 안내"),
    ("/-468", "증명서 발급"),
    ("/-469", "학생증 발급"),
    ("/-119", "국제학생증 발급"),
    ("/-452", "수강신청 안내"),
    ("/-455", "계절학기 안내"),
    ("/-454", "학점교류 안내"),
    ("/-457", "다전공 안내"),
    ("/-459", "캠퍼스 내 전부(과) 안내"),
    ("/-register2", "제적·재입학·자퇴 안내"),
    ("/-389", "학사경고·제적 및 유급 안내"),
    ("/-463", "졸업인증 안내"),
    ("/-450", "장학금 지급기준"),
    ("/-475", "병무 안내"),
    ("/-476", "예비군 안내"),
]

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# 페이지에 섞여 나오는 머티리얼 아이콘 글자 (링크 옆 화살표 등)
_ICON_WORDS = re.compile(r"\s*\b(?:chevron\\?_right|arrow\\?_forward|open\\?_in\\?_new|keyboard\\?_arrow\\?_right)\b")
MIN_BODY = 40   # 이보다 짧은 페이지(준비 중 등)는 넣지 않는다


def to_rag_markdown(title: str, url: str, body_md: str) -> str:
    """페이지 본문 마크다운 → RAG 문서 한 덩어리.

    - '사이트 경로' 같은 탐색용 구획은 뺀다.
    - 본문의 가장 큰 제목 단계를 ##로 맞춘다 (build_rag의 parse_markdown이 ## 단위로 조각낸다).
    - ## 아래마다 '원문: <url>' 줄을 넣어, 검색 결과에서 출처 링크로 쓰이게 한다.
    - 맨 위는 '# <title>'. 본문에 제목이 없으면 '## <title>' 하나로 감싼다.
    """
    lines = body_md.replace("\r\n", "\n").split("\n")
    kept: list[str] = []
    skipping = False
    for ln in lines:
        m = _HEADING.match(ln)
        if m:
            skipping = "사이트 경로" in m.group(2)
            if skipping:
                continue
        if not skipping:
            kept.append(_ICON_WORDS.sub("", ln).rstrip())
    levels = [len(m.group(1)) for ln in kept if (m := _HEADING.match(ln))]
    shift = (min(levels) - 2) if levels else 0
    normalized = []
    for ln in kept:
        m = _HEADING.match(ln)
        normalized.append(f"{'#' * max(2, len(m.group(1)) - shift)} {m.group(2).strip()}" if m else ln)

    # ## 구획으로 나눈다. 첫 ## 앞의 글은 제목 없는 머리 구획
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for ln in normalized:
        if ln.startswith("## "):
            sections.append((ln[3:], []))
        else:
            sections[-1][1].append(ln)

    out = [f"# {title}", ""]
    head = "\n".join(sections[0][1]).strip()
    if head:  # 첫 제목 앞 본문도 출처 링크가 붙도록
        out += [f"원문: {url}", head, ""] if levels else [f"## {title}", f"원문: {url}", head, ""]
    for name, body in sections[1:]:
        for sub_name, sub_body in _split_long(name, body):
            out += [f"## {sub_name}", f"원문: {url}", *sub_body, ""]
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


LONG_SECTION = 1200   # 이보다 긴 ## 구획은 ### 단위로 나눠 조각이 너무 커지지 않게 한다


def _split_long(name: str, body: list[str]) -> list[tuple[str, list[str]]]:
    if len("\n".join(body)) <= LONG_SECTION or not any(ln.startswith("### ") for ln in body):
        return [(name, body)]
    parts: list[tuple[str, list[str]]] = [(name, [])]
    for ln in body:
        if ln.startswith("### "):
            parts.append((f"{name} · {ln[4:].strip()}", []))
        else:
            parts[-1][1].append(ln)
    return [(n, b) for i, (n, b) in enumerate(parts) if i > 0 or "\n".join(b).strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    c = load_settings().crawler
    http = HttpClient(c.user_agent, min_interval=c.min_interval, timeout=c.timeout, retries=c.retries)
    parts, failed = [], []
    for path, title in PAGES:
        url = BASE + path
        try:
            page = parse_page(http.get(url).text, url)
        except (FetchError, ValueError) as e:
            log.warning("%s %s: 실패 (%s)", path, title, e)
            failed.append(path)
            continue
        if len(page.body_md.strip()) < MIN_BODY:
            log.warning("%s %s: 본문이 거의 없어 건너뜀", path, title)
            failed.append(path)
            continue
        parts.append(to_rag_markdown(title, url, page.body_md))
        log.info("%s %s: %d자", path, title, len(page.body_md))
    if not parts:
        log.error("페이지를 하나도 못 모았습니다. 기존 파일을 그대로 둡니다.")
        return 1
    # '>' 줄은 build_rag가 건너뛴다 (조각에 섞이지 않는 머리말)
    header = (f"> 생성 파일 — 직접 고치지 말 것. scripts/collect_main_pages.py가 {date.today().isoformat()}에 "
              f"학교 홈페이지({BASE})의 공개 안내 페이지에서 만들었다.\n"
              "> 운영시간·절차는 바뀔 수 있으니 답변할 때 수집일과 원문 링크를 함께 안내한다.\n\n")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(parts))
    log.info("저장: %s (페이지 %d개%s)", args.out, len(parts), f", 실패 {failed}" if failed else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
