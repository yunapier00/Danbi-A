"""저장한 종합강의시간표 화면 → config/timetable.json (네트워크 요청 없음)

webinfo.dankook.ac.kr은 robots.txt가 수집을 막으므로, 학기마다 사람이 브라우저에서 시간표 조회 화면을
'교양 검색'·'전공 검색'·'학문기초 검색'으로 각각 조회해 저장(Ctrl+S 또는 응답 본문 저장)한 뒤 이 스크립트에 넘긴다.
  .venv/Scripts/python -m scripts.build_timetable tmtbl.do tmtb2l.do tmtbl3.do --term 2026-2 --saved 2026-10-05
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from danbi.config import load_settings
from danbi.sources.timetable import PAGE_URL, build_sections, parse_html

log = logging.getLogger("build_timetable")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path, help="저장한 시간표 화면 파일들")
    ap.add_argument("--term", required=True, help="학년도-학기 (예: 2026-2)")
    ap.add_argument("--saved", default=None, help="화면을 저장한 날짜 YYYY-MM-DD (기본: 가장 최근 파일의 수정일)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    rows = []
    for f in args.files:
        part = parse_html(f.read_text(encoding="utf-8"))
        log.info("%s: %d행", f, len(part))
        rows += part
    sections = build_sections(rows)
    saved = args.saved or date.fromtimestamp(max(f.stat().st_mtime for f in args.files)).isoformat()
    out = args.out or load_settings().sources.timetable_path
    payload = {"_comment": "생성 파일 — 직접 고치지 말 것. scripts/build_timetable.py가 저장한 시간표 화면에서 만든다.",
               "source": PAGE_URL, "term": args.term, "saved_at": saved, "sections": sections}
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    unknown = sorted({s["room_raw"] for sec in sections for s in sec["slots"] if s["room_raw"] and not s["building"]})
    log.info("저장: %s (강좌 %d, %s 저장본)", out, len(sections), saved)
    if unknown:
        log.info("건물을 모르는 강의실 표기 %d개: %s (danbi/sources/timetable.py ROOM_BUILDINGS)", len(unknown),
                 ", ".join(unknown[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
