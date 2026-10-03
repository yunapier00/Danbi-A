"""첨부파일 텍스트 추출: PDF(텍스트형, pdfminer.six — MIT), HWPX, HWP 5.0.

PDF는 AGPL인 PyMuPDF 대신 pdfminer.six를 쓴다 (공개 서비스에서 소스 공개 의무가 생기지 않게).
압축을 푸는 형식(HWP 본문, HWPX zip)은 풀린 크기 상한을 둔다 (압축 폭탄 방지).

표는 마크다운 표로 복원한다(학사 공지의 일정·대상표가 대부분 표다).
스캔 PDF·이미지, 암호·배포용 HWP는 지원하지 않는다(UnsupportedDocument).
"""

from __future__ import annotations

import io
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field

MAX_PDF_PAGES = 60                     # 이보다 긴 PDF는 앞부분만 읽는다
MAX_UNPACKED_BYTES = 50 * 1024 * 1024  # HWP 본문·HWPX 압축을 푼 뒤의 총 크기 상한


class UnsupportedDocument(Exception):
    pass


def _md_row(cells: list[str]) -> str:
    return "| " + " | ".join(c.replace("|", "/").replace("\n", " ").strip() for c in cells) + " |"


def _grid(cells: dict[tuple[int, int], str]) -> list[list[str]]:
    """(행, 열) 주소 → 2차원 표. 병합된 칸은 빈칸으로 남겨 열 정렬을 유지한다."""
    if not cells:
        return []
    width = max(c for _, c in cells) + 1
    rows = [[""] * width for _ in range(max(r for r, _ in cells) + 1)]
    for (r, c), text in cells.items():
        rows[r][c] = text
    return rows


def _md_table(rows: list[list[str]]) -> list[str]:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [c for c in range(width) if any(r[c].strip() for r in rows)]  # 병합으로 생긴 빈 열 제거
    rows = [[r[c] for c in keep] for r in rows]
    width = len(keep)
    return [_md_row(rows[0]), _md_row(["---"] * width), *(_md_row(r) for r in rows[1:])]


def _tidy(lines: list[str]) -> str:
    text = "\n".join(line.rstrip() for line in lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --- PDF ---------------------------------------------------------------------

def extract_pdf(data: bytes) -> str:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer
    from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect

    pages = []
    try:
        for n, page in enumerate(extract_pages(io.BytesIO(data), maxpages=MAX_PDF_PAGES), 1):
            text = "".join(el.get_text() for el in page if isinstance(el, LTTextContainer)).strip()
            if text:
                pages.append(f"[p.{n}]\n{text}")
    except (PDFPasswordIncorrect, PDFEncryptionError) as e:
        raise UnsupportedDocument("암호가 걸린 PDF입니다") from e
    except Exception as e:
        raise UnsupportedDocument(f"PDF를 열 수 없습니다: {type(e).__name__}") from e
    if not pages:
        raise UnsupportedDocument("텍스트가 없는 PDF입니다 (스캔 이미지일 수 있음)")
    return _tidy(pages)


# --- HWPX (zip + XML) ----------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _hwpx_block(el) -> list[str]:
    lines: list[str] = []
    for ch in el:
        tag = _local(ch.tag)
        if tag == "p":
            lines += _hwpx_para(ch)
        elif tag == "tbl":
            lines += _hwpx_table(ch)
        else:
            lines += _hwpx_block(ch)
    return lines


def _hwpx_para(p) -> list[str]:
    text: list[str] = []
    extra: list[str] = []

    def walk(e):
        for ch in e:
            tag = _local(ch.tag)
            if tag == "t":
                text.append("".join(ch.itertext()))
            elif tag == "tbl":
                extra.extend(_hwpx_table(ch))
            elif tag == "p":  # 글상자 등 안의 문단
                extra.extend(_hwpx_para(ch))
            else:
                walk(ch)

    walk(p)
    line = "".join(text).strip()
    return ([line] if line else []) + extra


def _hwpx_table(tbl) -> list[str]:
    cells: dict[tuple[int, int], str] = {}
    for r, tr in enumerate(c for c in tbl if _local(c.tag) == "tr"):
        for c, tc in enumerate(x for x in tr if _local(x.tag) == "tc"):
            addr = next((x for x in tc if _local(x.tag) == "cellAddr"), None)
            if addr is not None:
                r_, c_ = int(addr.get("rowAddr", r)), int(addr.get("colAddr", c))
            else:
                r_, c_ = r, c
            cells[(r_, c_)] = " ".join(_hwpx_block(tc))
    return ["", *_md_table(_grid(cells)), ""]


def extract_hwpx(data: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise UnsupportedDocument("HWPX 파일이 손상되었습니다") from e
    sections = sorted(
        (n for n in zf.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)),
        key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group()),
    )
    if not sections:
        raise UnsupportedDocument("HWPX 본문(Contents/section*.xml)이 없습니다")
    if sum(zf.getinfo(n).file_size for n in sections) > MAX_UNPACKED_BYTES:
        raise UnsupportedDocument("HWPX 본문이 너무 큽니다")
    lines: list[str] = []
    for name in sections:
        lines += _hwpx_block(ET.fromstring(zf.read(name)))
    return _tidy(lines)


# --- HWP 5.0 (OLE + 레코드) ------------------------------------------------------

TAG_PARA_TEXT = 67
TAG_CTRL_HEADER = 71
TAG_LIST_HEADER = 72
_CHAR_CONTROLS = {0, 10, 13, *range(24, 32)}  # 1 WCHAR짜리 제어 문자. 나머지 32 미만은 8 WCHAR


def _hwp_records(data: bytes):
    i = 0
    while i + 4 <= len(data):
        (h,) = struct.unpack_from("<I", data, i)
        i += 4
        tag, level, size = h & 0x3FF, (h >> 10) & 0x3FF, (h >> 20) & 0xFFF
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", data, i)
            i += 4
        yield tag, level, data[i:i + size]
        i += size


def _hwp_para_text(payload: bytes) -> str:
    units = struct.unpack(f"<{len(payload) // 2}H", payload[: len(payload) // 2 * 2])
    out, i = [], 0
    while i < len(units):
        c = units[i]
        if c >= 32:
            out.append(chr(c))
            i += 1
        elif c in _CHAR_CONTROLS:
            if c in (10, 13):
                out.append("\n")
            i += 1
        else:  # 인라인·확장 제어 (표·그림 위치 표시 등)
            if c == 9:
                out.append("\t")
            i += 8
    return "".join(out).strip()


@dataclass
class _Table:
    level: int
    cells: dict[tuple[int, int], list[str]] = field(default_factory=dict)
    current: tuple[int, int] | None = None

    def lines(self) -> list[str]:
        return _md_table(_grid({addr: " ".join(t) for addr, t in self.cells.items()}))


def extract_hwp(data: bytes) -> str:
    import olefile

    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except OSError as e:
        raise UnsupportedDocument(f"HWP 파일을 열 수 없습니다: {e}") from e
    (flags,) = struct.unpack_from("<I", ole.openstream("FileHeader").read(), 36)
    if flags & 0b10:
        raise UnsupportedDocument("암호가 걸린 HWP입니다")
    if flags & 0b100:
        raise UnsupportedDocument("배포용 HWP 문서라 내용을 읽을 수 없습니다")

    sections = sorted(
        ("/".join(e) for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
        key=lambda n: int(n.rsplit("Section", 1)[1]),
    )
    lines: list[str] = []
    budget = MAX_UNPACKED_BYTES
    for name in sections:
        raw = ole.openstream(name).read()
        body = _inflate(raw, budget) if flags & 1 else raw
        budget -= len(body)
        lines += _hwp_section(body)
    return _tidy(lines)


def _inflate(raw: bytes, limit: int) -> bytes:
    """raw deflate 해제. 풀린 크기가 limit을 넘으면 중단한다 (압축 폭탄 방지)."""
    d = zlib.decompressobj(-15)
    out = d.decompress(raw, max(1, limit))
    if d.unconsumed_tail:
        raise UnsupportedDocument("HWP 본문이 너무 큽니다")
    return out


def _hwp_section(body: bytes) -> list[str]:
    doc: list[str] = []
    stack: list[_Table] = []

    def emit(texts: list[str]) -> None:
        if stack and stack[-1].current is not None:
            stack[-1].cells.setdefault(stack[-1].current, []).append(" / ".join(t for t in texts if t))
        else:
            doc.extend(texts)

    for tag, level, payload in _hwp_records(body):
        # 표 컨트롤보다 얕은(같은) 레벨의 레코드가 나오면 그 표는 끝난 것이다
        while stack and level <= stack[-1].level:
            table = stack.pop()
            emit(["", *table.lines(), ""] if not stack else table.lines())
        if tag == TAG_CTRL_HEADER and payload[:4][::-1] == b"tbl ":
            stack.append(_Table(level))
        elif tag == TAG_LIST_HEADER and stack and level == stack[-1].level + 1 and len(payload) >= 12:
            col, row = struct.unpack_from("<HH", payload, 8)
            stack[-1].current = (row, col)
            stack[-1].cells.setdefault((row, col), [])  # 빈 셀도 자리를 차지해야 열이 밀리지 않는다
        elif tag == TAG_PARA_TEXT:
            text = _hwp_para_text(payload)
            if text:
                emit([text])
    while stack:
        table = stack.pop()
        emit(["", *table.lines(), ""] if not stack else table.lines())
    return doc


# --- 진입점 ---------------------------------------------------------------------

_BY_EXT: dict[str, Callable[[bytes], str]] = {"pdf": extract_pdf, "hwpx": extract_hwpx, "hwp": extract_hwp}


def extract_text(filename: str, data: bytes) -> str:
    """파일명 확장자와 파일 시그니처로 형식을 판별한다."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if data[:4] == b"%PDF":
        ext = "pdf"
    elif data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" and ext != "hwp":
        raise UnsupportedDocument(f"지원하지 않는 형식입니다 (.{ext}, OLE 문서)")
    elif data[:2] == b"PK" and ext not in ("hwpx",):
        raise UnsupportedDocument(f"지원하지 않는 형식입니다 (.{ext})")
    if ext in ("txt", "csv"):
        return data.decode("utf-8", errors="replace").strip()
    if ext not in _BY_EXT:
        raise UnsupportedDocument(f"지원하지 않는 형식입니다 (.{ext or '확장자 없음'}). 지원: PDF, HWP, HWPX")
    return _BY_EXT[ext](data)
