"""rag_sources/ 원본 문서 → 새 Chroma DB (chroma_db_v2, 컬렉션 danbi_docs).

기존 DB(chroma_db_dd3)는 건드리지 않는다. 새 폴더에 새로 만들고, config/settings.yaml의 rag.chroma_path·collection을 바꿔 쓴다.

  .venv/Scripts/python -m scripts.build_rag --dry-run     # 청크만 만들어 data/rag_build/chunks.jsonl로 (API 없음)
  .venv/Scripts/python -m scripts.build_rag               # 임베딩 + DB 생성 (바뀐 청크만 API 호출, 나머지는 캐시)

문서별 처리 (원본 품질 문제와 해결은 docs/RETRIEVAL.md):
- 학칙·시행세칙 PDF: 조(條) 하나 = 청크 하나. 페이지 머리말·개정 이력 표시(<개정 …>, [본조신설 …])를 지우고 끊긴 줄을 잇는다.
  긴 조항은 항(①②…) 단위로 나눈다. 부칙은 날짜별로 하나.
- 종합강의시간표 안내자료 PDF: 페이지 위 머리말의 섹션 경로 + '가.' 소항목 단위. 표는 pdfplumber로 행·열을 살려
  마크다운 표로 바꾸고, 길면 머리 행을 반복해 나눈다. 화면 캡처 이미지 페이지(글자가 거의 없음)는 건너뛴다.
- 마크다운: '##' 단위 (건물 하나·일정 하나·셔틀 시간대 묶음이 한 청크).
임베딩: gemini-embedding-001, RETRIEVAL_DOCUMENT, 3072차원 (질문 임베딩과 같은 모델).
청크 앞에 '자료 > 장 > 조' 같은 위치를 붙여 임베딩한다 (본문에는 붙이지 않는다 — 출력 머리글로 이미 나간다).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from danbi.config import PROJECT_ROOT, load_settings

log = logging.getLogger("build_rag")

SRC_DIR = PROJECT_ROOT / "rag_sources"
OUT_DB = PROJECT_ROOT / "chroma_db_v2"
COLLECTION = "danbi_docs"
WORK = PROJECT_ROOT / "data" / "rag_build"
MAX_CHARS = 1400        # 조문 청크 본문 상한 (넘으면 항 단위로 나눈다)
GUIDE_MAX_CHARS = 700   # 안내자료(표 많은 PDF) 청크 상한. 1400이면 결과 글자 수가 늘고 비슷한 표가 자리를 차지했다
MIN_PAGE_CHARS = 80     # 이보다 글자가 적은 PDF 페이지는 화면 캡처로 보고 건너뛴다
EMBED_BATCH = 50


@dataclass
class Doc:
    text: str                       # 저장·출력되는 본문
    source: str                     # 출처 파일명
    h1: str = ""                    # 대제목
    h2: str = ""                    # 중제목
    h3: str = ""                    # 소제목
    page: int | None = None
    context: list[str] = field(default_factory=list)   # 임베딩 앞에 붙일 위치 (자료 이름 등)

    def metadata(self) -> dict:
        m = {"출처": self.source}
        for k, v in (("대제목", self.h1), ("중제목", self.h2), ("소제목", self.h3)):
            if v:
                m[k] = v
        if self.page is not None:
            m["페이지"] = self.page
        return m

    def embed_text(self) -> str:
        path = " > ".join(x for x in (*self.context, self.h1, self.h2, self.h3) if x)
        return f"{path}\n{self.text}"

    def id(self, n: int) -> str:
        return hashlib.sha1(f"{self.source}|{self.h1}|{self.h2}|{self.h3}|{n}".encode()).hexdigest()[:20]


# ---------------------------------------------------------------- 학칙·시행세칙 (조문 PDF)

_AMEND = re.compile(r"<\s*(?:개정|신설|번호개정|삭제|전문개정|본조신설|제목개정)[^<>]*>")
_TAG = re.compile(r"\[\s*(?:본조신설|본조삭제|제목개정|전문개정|번호개정|본장신설|본절신설|본관신설|조번호개정|종전)[^\[\]]*\]")
_ARTICLE = re.compile(r"^(제\s*\d+\s*조(?:\s*의\s*\d+)?)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*(.*)$")
_CHAPTER = re.compile(r"^제\s*\d+\s*장\s+\S")
_SECTION = re.compile(r"^제\s*\d+\s*절\s+\S")
_ADDENDA = re.compile(r"^부\s*칙\s*(\(.*\))?\s*$|^부\s*칙\s*\(")
_ITEM_START = re.compile(r"^(?:[①-⑳]|\d+\.\s|\d+\)\s|[가-하]\.\s|※|-\s)")
_HEADER_LINES = [re.compile(p) for p in (
    r"^학\s*칙\s+2-1-1\s*/\s*\d+\s*page$", r"^학칙\s*시행세칙\s*2-1-2\s*[～~-]\s*\d+$", r"^제정\s*:", r"^개정\s*:",
    r"^주관부서\s*:", r"^유관부서\s*:", r"^학\s*칙$", r"^학칙\s*시행세칙$")]


def _clean_line(line: str) -> str:
    line = _TAG.sub("", _AMEND.sub("", line))
    return re.sub(r"\s{2,}", " ", line).strip()


def _join(lines: list[tuple[str, bool]]) -> str:
    """끊긴 줄을 잇는다. (줄, 원래 줄 끝에 공백이 있었나). 항(①)·호(1.)·목(가.)으로 시작하는 줄만 새 줄.
    PDF에서 줄 끝 공백이 남아 있으면 단어 사이에서 줄이 바뀐 것이고, 없으면 단어 중간('대학조|직')에서 끊긴 것이다."""
    out: list[str] = []
    glue = " "
    for ln, spaced in lines:
        if not ln:
            continue
        if out and not _ITEM_START.match(ln):
            out[-1] = out[-1] + glue + ln
        else:
            out.append(ln)
        glue = " " if spaced or not re.search(r"[가-힣]$", ln) else ""
    # 내용 없이 번호만 남은 항목(삭제된 호)은 지운다
    return "\n".join(x for x in out if not re.fullmatch(r"(?:[①-⑳]|\d+\.|\d+\)|[가-하]\.)\s*", x))


def parse_regulation(path: Path, label: str) -> list[Doc]:
    from pdfminer.high_level import extract_text

    raw = extract_text(str(path))
    lines = [(ln.strip(), ln.endswith(" ")) for ln in raw.splitlines()]
    docs: list[Doc] = []
    chapter = section = ""
    cur_title: str | None = None
    cur_lines: list[str] = []
    in_addenda = False
    addenda_title = ""

    def flush():
        nonlocal cur_title, cur_lines
        if cur_title is None:
            return
        # 개정 이력 표시는 여러 줄에 걸치므로 줄을 이은 뒤에 지운다
        body = _join([(re.sub(r"\s{2,}", " ", x).strip(), sp) for x, sp in cur_lines])
        body = "\n".join(_clean_line(x) for x in body.split("\n"))
        body = "\n".join(x for x in body.split("\n") if x and not re.fullmatch(r"(?:[①-⑳]|\d+\.|\d+\)|[가-하]\.)\s*", x))
        # 삭제된 조항('제23조(입대휴학 기간) [본조삭제 2025.5.28.]')은 제목만 남으므로 청크로 만들지 않는다
        rest = body[len(cur_title):].strip() if body.startswith(cur_title) else body.strip()
        if body and rest and not re.fullmatch(r"삭제\.?", rest):
            h1 = addenda_title if in_addenda else chapter
            for part, h3 in _split_paragraphs(body):
                docs.append(Doc(text=part, source=path.name, h1=h1, h2=cur_title, h3=h3,
                                context=[label] + ([section] if section and not in_addenda else [])))
        cur_title, cur_lines = None, []

    for ln, spaced in lines:
        if not ln or any(p.match(ln) for p in _HEADER_LINES):
            continue
        if _ADDENDA.match(ln.replace(" ", "")[:20]) or re.match(r"^부\s+칙", ln):
            flush()
            in_addenda = True
            addenda_title = re.sub(r"\s+", "", _clean_line(ln))
            cur_title, cur_lines = "부칙", []
            continue
        if not in_addenda and _CHAPTER.match(ln):
            flush()
            chapter, section = _clean_line(ln), ""
            continue
        if not in_addenda and _SECTION.match(ln):
            flush()
            section = _clean_line(ln)
            continue
        m = _ARTICLE.match(ln)
        if m and in_addenda:   # 부칙 안의 조항(시행일·경과조치)은 쪼개지 않고 부칙 하나로 묶는다
            cur_lines.append((ln, spaced))
            continue
        if m:
            flush()
            num = re.sub(r"\s+", "", m.group(1))
            title = re.sub(r"\s+", " ", m.group(2)).strip()   # '휴학자의  등록금' 같은 이중 공백 정리
            cur_title = f"{num}({title})"
            cur_lines = [(f"{cur_title} {m.group(3)}".strip(), spaced)]
            continue
        if re.match(r"^\[\s*별표\s*\d+", ln):
            flush()
            cur_title, cur_lines = _clean_line(ln), [(ln, spaced)]
            continue
        if cur_title is not None:
            cur_lines.append((ln, spaced))
    flush()
    return docs


def _split_paragraphs(body: str) -> list[tuple[str, str]]:
    """긴 조문은 항(①…) 경계에서 MAX_CHARS 이하로 나눈다. 소제목은 '1/3' 같은 순번."""
    if len(body) <= MAX_CHARS:
        return [(body, "")]
    parts, cur = [], ""
    for ln in body.split("\n"):
        if cur and len(cur) + len(ln) + 1 > MAX_CHARS and re.match(r"^[①-⑳]", ln):
            parts.append(cur)
            cur = ln
        else:
            cur = f"{cur}\n{ln}" if cur else ln
    if cur:
        parts.append(cur)
    if len(parts) == 1:   # 항 경계가 없으면 글자 수로
        parts = [body[i:i + MAX_CHARS] for i in range(0, len(body), MAX_CHARS)]
    head = body.split(" ", 1)[0]   # 제N조(제목)
    return [(p if i == 0 else f"{head} (이어서)\n{p}", f"{i + 1}/{len(parts)}") for i, p in enumerate(parts)]


# ---------------------------------------------------------------- 종합강의시간표 안내자료 (표가 많은 PDF)

_ROMAN = re.compile(r"([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])\.\s*")
_SUBHEAD = re.compile(r"^([가-하](?:-\d+)?)\.\s+(.+)$")
HEADER_BOTTOM = 62
FOOTER_MARGIN = 61    # 쪽 번호(- n -)는 페이지 아래에서 이만큼 안쪽 (세로 756pt 기준 695pt). 가로 페이지도 있어 높이 기준으로 잰다


def _cell(c) -> str:
    return re.sub(r"\s+", " ", (c or "").replace("\n", " ")).strip()


def table_markdown(rows: list[list]) -> list[str]:
    """pdfplumber 표 → 마크다운 행들. 병합 셀(None)은 위(행 병합) 또는 왼쪽(열 병합) 값으로 채운다."""
    grid: list[list[str]] = []
    for r, row in enumerate(rows):
        out = []
        for c, cell in enumerate(row):
            if cell is None:
                above = grid[r - 1][c] if r > 0 and c < len(grid[r - 1]) else ""
                cell = above if above else (out[-1] if out else "")
            out.append(_cell(cell))
        if any(out):
            grid.append(out)
    if not grid:
        return []
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    keep = [c for c in range(width) if any(r[c] for r in grid[1:])] or list(range(width))  # 전부 빈 열은 뺀다
    grid = [[r[c] for c in keep] for r in grid]
    width = len(keep)
    lines = ["| " + " | ".join(r + [""] * (width - len(r))) + " |" for r in grid]
    return [lines[0], "|" + "---|" * width, *lines[1:]]


def _page_header(page) -> tuple[str, str]:
    band = page.crop((0, 0, page.width, HEADER_BOTTOM)).extract_text_lines()
    texts = [b["text"].strip() for b in sorted(band, key=lambda b: b["top"])]
    roman_line = next((t for t in texts if _ROMAN.search(t)), "")
    others = "".join(t for t in texts if t != roman_line)
    # 원문 머리말에 '3, 전공신청'(쉼표)·'3 교육과정별'(기호 없음) 같은 표기 차이가 있어 모두 번호 구분으로 본다
    m = re.match(r"^\s*([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\.\s*.+?)\s+(\d+)(?:[.,]\s*|\s+)(\S.*)$", roman_line)
    if m:
        return m.group(1).strip(), f"{m.group(2)}. {m.group(3).strip()}"
    return roman_line.strip(), others.strip()


def parse_guide(path: Path, label: str) -> list[Doc]:
    import pdfplumber

    docs: list[Doc] = []
    state = {"h1": "", "h2": "", "h3": "", "page": None, "buf": []}

    def flush():
        text = "\n".join(state["buf"]).strip()
        if len(re.sub(r"\s", "", text)) >= 30:
            docs.append(Doc(text=text, source=path.name, h1=state["h1"], h2=state["h2"], h3=state["h3"],
                            page=state["page"], context=[label]))
        state["buf"] = []

    def add(line: str, page_no: int):
        size = sum(len(x) for x in state["buf"])
        if size + len(line) > GUIDE_MAX_CHARS and state["buf"]:
            flush()
        if not state["buf"]:
            state["page"] = page_no
        state["buf"].append(line)

    with pdfplumber.open(str(path)) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            footer_top = page.height - FOOTER_MARGIN
            body = page.crop((0, HEADER_BOTTOM, page.width, footer_top))
            if len((body.extract_text() or "").strip()) < MIN_PAGE_CHARS:
                continue
            h1, h2 = _page_header(page)
            if not h1:                       # 머리말이 없는 페이지(가로 표 등)는 앞 페이지의 섹션을 이어받는다
                h1, h2 = state["h1"], state["h2"]
            elif not re.match(r"^\d+\.\s*\S", h2):
                h2 = state["h2"] if h1 == state["h1"] else ""
            if (h1, h2) != (state["h1"], state["h2"]):
                flush()
                state.update(h1=h1, h2=h2, h3="")
            tables = sorted(body.find_tables(), key=lambda t: t.bbox[1])
            cursor = HEADER_BOTTOM
            segments: list[tuple[str, object]] = []
            for t in tables:
                if t.bbox[1] > cursor:
                    segments.append(("text", body.crop((0, cursor, page.width, t.bbox[1]))))
                segments.append(("table", t))
                cursor = max(cursor, t.bbox[3])
            if cursor < footer_top:
                segments.append(("text", body.crop((0, cursor, page.width, footer_top))))
            for kind, seg in segments:
                if kind == "text":
                    for ln in (seg.extract_text() or "").splitlines():
                        ln = ln.strip()
                        if not ln or ln == h2 or re.fullmatch(r"-\s*\d+\s*-", ln):
                            continue
                        m = _SUBHEAD.match(ln)
                        if m:
                            flush()
                            state["h3"] = f"{m.group(1)}. {m.group(2)}"[:60]
                        add(ln, page_no)
                else:
                    md = table_markdown(seg.extract())
                    if not md:
                        continue
                    header, rows = md[:2], md[2:]
                    if state["buf"] and sum(len(x) for x in state["buf"]) + len("".join(md)) > GUIDE_MAX_CHARS:
                        flush()   # 표는 되도록 앞 글과 떨어뜨리지 않되, 넘치면 새 청크에서 시작
                    if not state["buf"]:
                        state["page"] = page_no
                    state["buf"] += header
                    for row in rows:
                        if sum(len(x) for x in state["buf"]) + len(row) > GUIDE_MAX_CHARS and len(state["buf"]) > 2:
                            flush()
                            state["buf"] += header   # 나뉜 표 조각마다 머리 행을 다시
                            state["page"] = page_no
                        state["buf"].append(row)
    flush()
    return docs


# ---------------------------------------------------------------- 마크다운

def parse_markdown(path: Path, label: str) -> list[Doc]:
    lines = path.read_text(encoding="utf-8").splitlines()
    docs: list[Doc] = []
    h1 = ""
    h2 = ""
    buf: list[str] = []
    h3s: list[str] = []

    def flush():
        text = "\n".join(buf).strip()
        if text and (h2 or len(text) > 40):
            docs.append(Doc(text=text, source=path.name, h1=h1, h2=h2, h3=" · ".join(h3s), context=[label]))

    for ln in lines:
        if re.match(r"^#\s", ln):
            flush()
            h1, h2, buf, h3s = ln[2:].strip(), "", [], []
        elif re.match(r"^##\s", ln):
            flush()
            h2, buf, h3s = ln[3:].strip(), [ln], []
        elif re.match(r"^###\s", ln):
            h3s.append(ln[4:].strip())
            buf.append(ln)
        elif ln.strip() not in ("---",) and not ln.startswith(">"):
            buf.append(ln)
    flush()
    return docs


# ---------------------------------------------------------------- 임베딩·DB

def embed_all(docs: list[Doc], settings) -> list[list[float]]:
    from google import genai
    from google.genai import types

    cache_path = WORK / "embed_cache.jsonl"
    cache: dict[str, list[float]] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            k, v = json.loads(line)
            cache[k] = v
    model, dims = settings.embedding.model, settings.embedding.dimensions
    keys = [hashlib.sha256(f"{model}|{dims}|DOC|{d.embed_text()}".encode()).hexdigest() for d in docs]
    todo = [i for i, k in enumerate(keys) if k not in cache]
    log.info("임베딩: 전체 %d, 캐시 %d, 새로 계산 %d", len(docs), len(docs) - len(todo), len(todo))
    if todo:
        client = genai.Client()
        with cache_path.open("a", encoding="utf-8") as fp:
            for s in range(0, len(todo), EMBED_BATCH):
                batch = todo[s:s + EMBED_BATCH]
                for attempt in range(6):
                    try:
                        r = client.models.embed_content(
                            model=model, contents=[docs[i].embed_text() for i in batch],
                            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=dims))
                        break
                    except Exception as e:  # 한도 초과(429) 등은 기다렸다 다시
                        wait = 5 * (attempt + 1)
                        log.warning("임베딩 실패 (%s), %d초 뒤 다시", type(e).__name__, wait)
                        time.sleep(wait)
                else:
                    raise RuntimeError("임베딩을 계속 실패했습니다")
                for i, e in zip(batch, r.embeddings):
                    cache[keys[i]] = list(e.values)
                    fp.write(json.dumps([keys[i], cache[keys[i]]]) + "\n")
                log.info("  %d/%d", min(s + EMBED_BATCH, len(todo)), len(todo))
    return [cache[k] for k in keys]


def write_db(docs: list[Doc], vectors: list[list[float]]) -> None:
    import chromadb

    if OUT_DB.resolve() == (PROJECT_ROOT / "chroma_db_dd3").resolve():
        raise RuntimeError("기존 DB에는 쓰지 않는다")
    client = chromadb.PersistentClient(path=str(OUT_DB), settings=chromadb.Settings(anonymized_telemetry=False))
    if COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)   # 새 DB(이 스크립트가 만든 것)만 다시 만든다
    col = client.create_collection(COLLECTION, configuration={"hnsw": {"space": "cosine"}})
    ids, seen = [], {}
    for d in docs:
        n = seen.get((d.source, d.h1, d.h2, d.h3), 0)
        seen[(d.source, d.h1, d.h2, d.h3)] = n + 1
        ids.append(d.id(n))
    for s in range(0, len(docs), 200):
        col.add(ids=ids[s:s + 200], documents=[d.text for d in docs[s:s + 200]],
                metadatas=[d.metadata() for d in docs[s:s + 200]], embeddings=vectors[s:s + 200])
    log.info("저장: %s (컬렉션 %s, %d건)", OUT_DB, COLLECTION, col.count())
    # 컬렉션을 지우고 다시 만들면 옛 벡터 색인 폴더가 남는다 → 참조되지 않는 폴더를 정리 (커밋 크기 절약)
    import shutil
    import sqlite3

    with sqlite3.connect(f"file:{OUT_DB / 'chroma.sqlite3'}?mode=ro", uri=True) as db:
        used = {r[0] for r in db.execute("SELECT id FROM segments")}
    for d in OUT_DB.iterdir():
        if d.is_dir() and d.name not in used:
            shutil.rmtree(d)
            log.info("쓰지 않는 색인 폴더 정리: %s", d.name)


SOURCES = [  # (파일, 처리 방식, 임베딩 앞에 붙일 자료 이름)
    ("(2-1-1)학칙(20260831)_일부개정.pdf", parse_regulation, "학칙"),
    ("(2-1-2)학칙 시행세칙(20260615)_일부개정.pdf", parse_regulation, "학칙 시행세칙"),
    ("2026-2학기 종합강의시간표 안내자료.pdf", parse_guide, "2026-2학기 종합강의시간표 안내자료"),
    ("campus_map_.md", parse_markdown, "죽전캠퍼스 캠퍼스맵"),
    ("학사일정.md", parse_markdown, "2026학년도 학사일정"),
    ("도서관 운영 시간.md", parse_markdown, "도서관 운영 시간"),
    ("셔틀버스 정보.md", parse_markdown, "셔틀버스 정보"),
]


def build_docs() -> list[Doc]:
    docs: list[Doc] = []
    for name, fn, label in SOURCES:
        part = fn(SRC_DIR / name, label)
        lens = sorted(len(d.text) for d in part) or [0]
        log.info("%-40s 청크 %4d  (길이 중앙 %d, 최대 %d)", name, len(part), lens[len(lens) // 2], lens[-1])
        docs += part
    return docs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="청크만 만들고 임베딩·DB는 만들지 않는다")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    WORK.mkdir(parents=True, exist_ok=True)
    docs = build_docs()
    with (WORK / "chunks.jsonl").open("w", encoding="utf-8") as fp:
        for d in docs:
            fp.write(json.dumps({**asdict(d), "embed": d.embed_text()[:120]}, ensure_ascii=False) + "\n")
    log.info("청크 %d개 → %s", len(docs), WORK / "chunks.jsonl")
    if args.dry_run:
        return 0
    settings = load_settings()
    write_db(docs, embed_all(docs, settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
