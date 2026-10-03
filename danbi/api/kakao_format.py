"""카카오톡 챗봇(오픈빌더 스킬) 응답 만들기.

카카오 말풍선은 마크다운을 그리지 못한다(굵게·표·제목이 기호 그대로 보인다). 그래서 답변 마크다운을 읽기 좋은
일반 텍스트로 바꾸고, 제한에 맞춰 나눈다: 말풍선(outputs) 최대 3개, simpleText 최대 1,000자,
textCard 설명 최대 400자·버튼 최대 3개, 바로가기(quickReplies) 최대 10개.
"""

from __future__ import annotations

import re

MAX_OUTPUTS = 3
MAX_TEXT = 1000
MAX_CARD_DESC = 400
MAX_BUTTONS = 3
MAX_BUTTON_LABEL = 14
RESET_LABEL = "새 대화"
TRUNCATED = "\n…(답변이 길어 일부만 보여 드려요)"

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _table_rows(lines: list[str]) -> list[str]:
    """마크다운 표 → '• 머리1: 값1 · 머리2: 값2' 줄."""
    cells = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    if len(cells) >= 2 and all(re.fullmatch(r":?-{2,}:?", c) for c in cells[1] if c):
        head, body = cells[0], cells[2:]
    else:
        head, body = [], cells
    out = []
    for row in body:
        if head:
            pairs = [f"{h}: {v}" if h else v for h, v in zip(head, row) if v]
            out.append("• " + " · ".join(pairs))
        else:
            out.append("• " + " · ".join(v for v in row if v))
    return out


def md_to_text(md: str) -> str:
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out += _table_rows(block)
            continue
        i += 1
        s = line.rstrip()
        if re.fullmatch(r"\s*(```|~~~).*", s):
            continue                                   # 코드 펜스 기호만 뺀다
        if re.fullmatch(r"\s*([-*_])\1{2,}\s*", s):
            out.append("")                             # 가로줄
            continue
        s = _IMAGE.sub("", s)
        s = _LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", s)
        if m := re.match(r"\s*#{1,6}\s+(.*)", s):
            s = f"■ {m.group(1)}"
        s = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", s)       # 글머리표
        s = re.sub(r"^\s*>\s?", "│ ", s)               # 인용
        s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)      # 굵게
        s = re.sub(r"(?<![A-Za-z0-9*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![A-Za-z0-9*])", r"\1", s)  # 기울임 (*글*까지 처럼 조사가 붙어도)
        s = s.replace("`", "")
        out.append(s)
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_text(text: str, limit: int = MAX_TEXT) -> list[str]:
    """문단 경계를 우선해서 limit 이하 조각으로 나눈다."""
    chunks: list[str] = []
    cur = ""
    for para in text.split("\n\n"):
        piece = para if not cur else cur + "\n\n" + para
        if len(piece) <= limit:
            cur = piece
            continue
        if cur:
            chunks.append(cur)
        while len(para) > limit:                       # 한 문단이 너무 길면 줄 단위로, 그래도 길면 글자로
            cut = para.rfind("\n", 0, limit)
            cut = cut if cut > limit // 2 else limit
            chunks.append(para[:cut].rstrip())
            para = para[cut:].lstrip("\n")
        cur = para
    if cur:
        chunks.append(cur)
    return chunks or [""]


def _quick_replies() -> list[dict]:
    return [{"label": RESET_LABEL, "action": "message", "messageText": RESET_LABEL}]


def text_response(message: str) -> dict:
    return {"version": "2.0", "template": {"outputs": [{"simpleText": {"text": message[:MAX_TEXT]}}],
                                           "quickReplies": _quick_replies()}}


def _label(title: str, n: int) -> str:
    t = re.sub(r"\s+", " ", title or "").strip() or f"원문 {n}"
    return t if len(t) <= MAX_BUTTON_LABEL else t[:MAX_BUTTON_LABEL - 1] + "…"


def answer_response(answer_md: str, sources: list[dict], remaining: int | None = None) -> dict:
    """답변 + 출처 버튼 + 남은 횟수 → 스킬 응답."""
    text = md_to_text(answer_md) or "답변을 만들지 못했어요."
    if remaining is not None:
        text += f"\n\n오늘 남은 질문: {remaining}회"
    links = [s for s in sources if s.get("url")][:MAX_BUTTONS]
    room = MAX_OUTPUTS - (1 if links else 0)
    chunks = split_text(text)
    if len(chunks) > room:
        chunks = chunks[:room]
        chunks[-1] = chunks[-1][: MAX_TEXT - len(TRUNCATED)].rstrip() + TRUNCATED
    outputs: list[dict] = [{"simpleText": {"text": c}} for c in chunks]
    if links:
        desc = "\n".join(f"{n}. {s.get('title') or s['url']}" for n, s in enumerate(links, 1))
        outputs.append({"textCard": {
            "title": "원문 링크",
            "description": desc[:MAX_CARD_DESC],
            "buttons": [{"label": _label(s.get("title", ""), n), "action": "webLink", "webLinkUrl": s["url"]}
                        for n, s in enumerate(links, 1)],
        }})
    return {"version": "2.0", "template": {"outputs": outputs, "quickReplies": _quick_replies()}}
