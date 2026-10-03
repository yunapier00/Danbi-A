"""첨부 텍스트 추출 (실제 학과 공지 첨부 샘플 + 생성한 PDF)."""

import io
import zipfile
from pathlib import Path

import pytest

from danbi.crawler.extract.documents import MAX_UNPACKED_BYTES, UnsupportedDocument, _inflate, extract_text

FIX = Path(__file__).parent / "fixtures" / "attachments"


def read(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_hwp_table_keeps_column_positions():
    text = extract_text("졸업시험 신청서.hwp", read("graduation_exam_form.hwp"))
    assert text.startswith("2026학년도 2학기\nMSE 졸업시험 신청서")
    # 빈 '신청 여부' 칸이 있어도 다음 과목이 같은 열에 놓인다
    assert "| 과목 | 담당 교수 | 신청 여부 | 과목 |" in text
    assert "| 모바일이동통신 | 최수한 |  | 자료구조 |" in text


def test_hwp_body_text_and_schedule_table():
    text = extract_text("공고.hwp", read("reserve_training.hwp"))
    assert "2026년 예비군교육훈련 공고" in text
    assert "| 일 정 |" in text and "| --- |" in text
    assert "| 05.08.(금) | ·AI융합대학(SW융합대학)" in text
    assert "3. 훈련장소 : 용인 운학과학화예비군훈련장" in text


def test_hwpx_paragraphs_and_tables():
    text = extract_text("신청서.hwpx", read("self_designed_major_form.hwpx"))
    assert text.startswith("[별지서식] 자율설계전공 신청서")
    assert "| 성명 |" in text
    assert "자율설계전공 학업계획서" in text


def make_pdf(pages: list[str]) -> bytes:
    """테스트용 최소 PDF (Helvetica 한 줄씩). 빈 문자열이면 글자 없는 쪽."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_pdf_text_by_page():
    text = extract_text("a.pdf", make_pdf(["Page one text", "Page two text"]))
    assert text == "[p.1]\nPage one text\n[p.2]\nPage two text"


def test_pdf_detected_by_signature_even_with_wrong_extension():
    assert "hello" in extract_text("download", make_pdf(["hello"]))


def test_broken_pdf_is_unsupported():
    with pytest.raises(UnsupportedDocument):
        extract_text("x.pdf", b"%PDF-1.4\n garbage")


def test_inflate_limit_blocks_decompression_bombs():
    import zlib
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    bomb = c.compress(b"\0" * (2 * 1024 * 1024)) + c.flush()
    assert len(_inflate(bomb, 4 * 1024 * 1024)) == 2 * 1024 * 1024
    with pytest.raises(UnsupportedDocument, match="너무 큽니다"):
        _inflate(bomb, 1024 * 1024)
    assert MAX_UNPACKED_BYTES >= 10 * 1024 * 1024


def test_unsupported_documents():
    with pytest.raises(UnsupportedDocument, match="스캔"):
        extract_text("scan.pdf", make_pdf([""]))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<x/>")
    with pytest.raises(UnsupportedDocument, match=r"\.docx"):
        extract_text("a.docx", buf.getvalue())
    with pytest.raises(UnsupportedDocument, match="지원: PDF, HWP, HWPX"):
        extract_text("photo.jpg", b"\xff\xd8\xff\xe0")
    with pytest.raises(UnsupportedDocument, match="본문"):
        extract_text("a.hwpx", buf.getvalue())
