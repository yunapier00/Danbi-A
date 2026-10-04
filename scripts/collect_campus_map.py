"""캠퍼스맵 스냅숏 수집 → config/campus_map.yaml

학교 공식 캠퍼스맵(https://dankook.ac.kr/campusmap)이 쓰는 JSON에서 건물 목록·좌표와 건물별 호실(층·호수·부서·분류)을 모은다.
  .venv/Scripts/python -m scripts.collect_campus_map            # 죽전 (기본)
  .venv/Scripts/python -m scripts.collect_campus_map --campus 죽전 천안
LLM을 쓰지 않는다. 캠퍼스당 약 45건 요청 (1초 간격, 1분 남짓). 주 1회 정도 다시 돌린다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

import yaml

from danbi.config import load_settings
from danbi.crawler.http import FetchError, HttpClient
from danbi.sources.campus_map import (CAMPUS_TABS, PAGE_URL, data_url, facility_url, parse_facility_detail,
                                      parse_facility_list)

log = logging.getLogger("collect_campus_map")


def collect(http: HttpClient, campus: str) -> list[dict]:
    facilities = parse_facility_list(http.get(data_url(CAMPUS_TABS[campus])).json())
    out = []
    for f in facilities:
        try:
            detail = parse_facility_detail(http.get(facility_url(f["id"])).json())
        except (FetchError, ValueError) as e:  # 호실 정보가 없는 시설(광장·동상 등)은 위치만 남긴다
            log.info("%s: 호실 정보 없음 (%s)", f["name"], e)
            detail = {"desc": "", "rooms": []}
        out.append({"id": f["id"], "name": f["name"], "lat": f["lat"], "lng": f["lng"], "desc": detail["desc"], "rooms": detail["rooms"]})
        log.info("%s %s: 호실 %d", campus, f["name"], len(detail["rooms"]))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campus", nargs="+", default=["죽전"], choices=list(CAMPUS_TABS))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = load_settings()
    c = settings.crawler
    http = HttpClient(c.user_agent, min_interval=c.min_interval, timeout=c.timeout, retries=c.retries)
    campuses = {campus: collect(http, campus) for campus in args.campus}
    if not any(campuses.values()):
        log.error("건물을 하나도 못 모았습니다. 기존 파일을 그대로 둡니다.")
        return 1
    out = settings.sources.campus_map_path
    header = ("# 생성 파일 — 직접 고치지 말 것. scripts/collect_campus_map.py가 학교 공식 캠퍼스맵에서 만든다.\n"
              "# 별칭은 읽을 때 붙는다 (danbi/sources/campus_map.py의 aliases_of·EXTRA_ALIASES). 다시 생성할 필요 없음.\n")
    body = yaml.safe_dump({"source": PAGE_URL, "collected_at": date.today().isoformat(), "campuses": campuses},
                          allow_unicode=True, sort_keys=False, width=200)
    out.write_text(header + body, encoding="utf-8")
    rooms = sum(len(b["rooms"]) for bs in campuses.values() for b in bs)
    log.info("저장: %s (건물 %d, 호실 %d)", out, sum(len(bs) for bs in campuses.values()), rooms)
    return 0


if __name__ == "__main__":
    sys.exit(main())
