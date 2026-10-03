"""전체 학과 목록 수집 (설계 §10.4) → config/dept_list.yaml

학교 메인 사이트 '대학' 메뉴의 단과대학 페이지마다 학과(전공)별 deptData JSON이 있다.
  .venv/Scripts/python -m scripts.collect_dept_list
LLM을 쓰지 않는다. 학교 사이트에 약 25건 요청 (1초 간격).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date
from urllib.parse import unquote, urljoin, urlparse

import yaml
from bs4 import BeautifulSoup

from danbi.config import PROJECT_ROOT, load_settings
from danbi.crawler.http import FetchError, HttpClient

log = logging.getLogger("collect_dept_list")

HOME = "https://www.dankook.ac.kr/web/kor/home"
COLLEGES_MENU = "/web/kor/대학"
AGGREGATE_PAGE = "학부"  # 전체 학과를 모아 놓은 페이지 제목
OUT = PROJECT_ROOT / "config" / "dept_list.yaml"

# 전화번호가 없을 때 쓰는 단과대학 → 캠퍼스 (2026-10-02 수집 결과에서 확인)
JUKJEON = {"문과대학", "법과대학", "사회과학대학", "경영경제대학", "공과대학", "AI융합대학", "사범대학",
           "음악·예술대학", "음악ㆍ예술대학", "프리무스국제대학"}
CHEONAN = {"외국어대학", "과학기술대학", "바이오융합대학", "예술대학", "스포츠과학대학", "의과대학", "공공인재대학",
           "보건과학대학", "간호대학", "치과대학", "약학대학"}


def campus_of(tel: str, college: str) -> str | None:
    tel = (tel or "").strip()
    if tel.startswith("031-8005") or tel.startswith("031)8005"):
        return "죽전"
    if tel.startswith("041"):
        return "천안"
    if college in JUKJEON:
        return "죽전"
    if college in CHEONAN:
        return "천안"
    return None


def normalize_homepage(url: str) -> str | None:
    """http→https, 끝의 /·/home 제거, /web/{slug}까지만."""
    url = (url or "").strip()
    if not url:
        return None
    if not re.match(r"https?://", url):
        url = "https://" + url
    p = urlparse(url)
    host = p.netloc.lower()
    path = unquote(p.path)
    m = re.match(r"(/web/[^/]+)", path)
    if m:
        path = m.group(1)
    else:
        path = re.sub(r"/(home)?$", "", path)
    return f"https://{host}{path}"


def classify(homepage: str | None) -> tuple[str, str]:
    """(platform, source_id). platform: dku_cms | dku_www | external | none"""
    if not homepage:
        return "none", ""
    p = urlparse(homepage)
    m = re.match(r"/web/([^/]+)$", p.path)
    if p.netloc == "cms.dankook.ac.kr" and m:
        return "dku_cms", m.group(1)
    if p.netloc in ("www.dankook.ac.kr", "dankook.ac.kr") and m:
        return "dku_www", m.group(1)  # 같은 Liferay 플랫폼으로 보임. 탐색해서 확인
    return "external", p.netloc.split(".")[0]


def college_pages(http: HttpClient) -> list[str]:
    soup = BeautifulSoup(http.get(HOME).text, "lxml")
    anchor = next((a for a in soup.select("a[href]") if unquote(a["href"]).rstrip("/").endswith(COLLEGES_MENU)), None)
    if anchor is None or anchor.find_parent("li") is None:
        raise RuntimeError("메인 페이지에서 '대학' 메뉴를 찾지 못했습니다 (사이트 구조 변경?)")
    urls = []
    for a in anchor.find_parent("li").select("a[href]"):
        url = urljoin(HOME, a["href"]).split("?")[0].split("#")[0]
        if not unquote(url).rstrip("/").endswith(COLLEGES_MENU) and url not in urls:
            urls.append(url)
    return urls


def parse_college(html: str) -> tuple[str, list[dict]]:
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True).split(" - ")[0] if soup.title else ""
    depts = []
    for sc in soup.select('#main-content script[id$="deptData"]'):
        try:
            d = json.loads(sc.string or "null")
        except json.JSONDecodeError:
            continue
        if d and d.get("orgzNm"):
            depts.append(d)
    return title, depts


def build(entries: list[tuple[str, dict]]) -> dict:
    """(단과대학 페이지 제목, deptData) 목록 → 사이트 단위로 묶은 dept_list."""
    seen_org: set[str] = set()
    out: dict[str, dict] = {}
    for college_title, d in entries:
        org_id = str(d.get("orgId") or "")
        if org_id in seen_org:
            continue
        seen_org.add(org_id)
        major = (d.get("orgzPrtNm") or d["orgzNm"]).strip()
        full = d["orgzNm"].strip()
        college = full[: -len(major)].strip() if full.endswith(major) and full != major else college_title
        homepage = normalize_homepage(d.get("hpUrl"))
        platform, sid = classify(homepage)
        key = sid or f"org-{org_id}"
        if key in out and out[key]["homepage"] != homepage:
            key = f"{key}-{org_id}"  # 같은 slug, 다른 사이트 (드묾)
        office = {k: v for k, v in (("tel", (d.get("telNo") or "").strip()), ("room", (d.get("roomNm") or "").strip())) if v}
        if key in out:  # 한 사이트를 여러 전공이 공유
            e = out[key]
            if major not in e["majors"]:
                e["majors"].append(major)
            e["org_ids"].append(org_id)
            continue
        out[key] = {
            "name": major, "college": college, "campus": campus_of(office.get("tel", ""), college),
            "platform": platform, "homepage": homepage, "majors": [major], "office": office, "org_ids": [org_id],
        }
    for e in out.values():
        if len(e["majors"]) > 1:
            e["name"] = "·".join(e["majors"])
    return out


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="전체 학과 목록 수집 → config/dept_list.yaml")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    c = load_settings().crawler
    http = HttpClient(c.user_agent, min_interval=c.min_interval, timeout=c.timeout, retries=c.retries)
    pages = []
    for url in college_pages(http):
        try:
            title, depts = parse_college(http.get(url).text)
        except FetchError as e:
            log.warning("단과대학 페이지 실패 %s: %s", url, e)
            continue
        log.info("%s: 학과 %d개", title, len(depts))
        pages.append((title, depts))
    # '학부' 페이지는 전체 학과 모음이라 옛 조직(예: SW융합대학 소프트웨어학과)이 섞여 있다.
    # 실제 단과대학 페이지를 먼저 처리해 현재 소속이 우선되게 한다.
    pages.sort(key=lambda p: p[0] == AGGREGATE_PAGE)
    entries = [(title, d) for title, depts in pages for d in depts]

    depts = build(entries)
    counts: dict[str, int] = {}
    for e in depts.values():
        counts[e["platform"]] = counts.get(e["platform"], 0) + 1
    header = (
        f"# 전체 학과 목록 — scripts/collect_dept_list.py가 {date.today()} 자동 생성. 직접 고치지 말고 다시 수집한다.\n"
        f"# 출처: {HOME} '대학' 메뉴의 단과대학 페이지 deptData\n"
        f"# 사이트 {len(depts)}개 (전공 {sum(len(e['majors']) for e in depts.values())}개) — "
        + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + "\n"
        "# platform: dku_cms(자동 탐색 대상) | dku_www(메인 사이트 하위, 탐색해서 확인) | external(별도 사이트) | none(홈페이지 없음)\n\n"
    )
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(header + yaml.safe_dump(depts, allow_unicode=True, sort_keys=False, width=200))
    log.info("저장: %s (사이트 %d개, %s)", args.out, len(depts), counts)


if __name__ == "__main__":
    main()
