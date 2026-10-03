"""scripts/collect_dept_list.py, scripts/discover_source.py (네트워크 없이)."""

from pathlib import Path

import pytest
import yaml
from bs4 import BeautifulSoup

from danbi.sources.dept_list import Department
from danbi.sources.registry import RegistryError, SourceRegistry
from scripts.collect_dept_list import build, campus_of, classify, normalize_homepage, parse_college
from scripts.discover_source import ROLE_RULES, Found, _classify, build_draft, guess

FIX = Path(__file__).parent / "fixtures" / "dku_cms"


# --- collect_dept_list --------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("http://cms.dankook.ac.kr/web/sw", "https://cms.dankook.ac.kr/web/sw"),
    ("https://cms.dankook.ac.kr/web/sw/home", "https://cms.dankook.ac.kr/web/sw"),
    ("https://cms.dankook.ac.kr/web/dkcw/일반소식/공지", "https://cms.dankook.ac.kr/web/dkcw"),
    ("https://med.dankook.ac.kr/", "https://med.dankook.ac.kr"),
    ("cms.dankook.ac.kr/web/ace/", "https://cms.dankook.ac.kr/web/ace"),
    ("", None),
])
def test_normalize_homepage(raw, expected):
    assert normalize_homepage(raw) == expected


def test_classify_and_campus():
    assert classify("https://cms.dankook.ac.kr/web/sw") == ("dku_cms", "sw")
    assert classify("https://www.dankook.ac.kr/web/communicationdesign") == ("dku_www", "communicationdesign")
    assert classify("https://law.dankook.ac.kr/web/law") == ("external", "law")
    assert classify(None) == ("none", "")
    assert campus_of("031-8005-3227", "") == "죽전"
    assert campus_of("041-550-3430", "") == "천안"
    assert campus_of("", "약학대학") == "천안"  # 전화번호가 없으면 단과대학으로


def dept(org_id, full, part, url, tel="031-8005-0000"):
    return {"orgId": org_id, "orgzNm": full, "orgzPrtNm": part, "hpUrl": url, "telNo": tel, "roomNm": "방"}


def test_build_merges_shared_sites_and_prefers_first_entry():
    entries = [
        ("AI융합대학", dept("2", "AI융합대학 소프트웨어학과", "소프트웨어학과", "http://cms.dankook.ac.kr/web/sw")),
        ("사회과학대학", dept("3", "사회과학대학 미디어커뮤니케이션학부 저널리즘전공", "저널리즘전공", "https://cms.dankook.ac.kr/web/comm")),
        ("사회과학대학", dept("4", "사회과학대학 미디어커뮤니케이션학부 광고홍보전공", "광고홍보전공", "https://cms.dankook.ac.kr/web/comm/")),
        ("학부", dept("1", "SW융합대학 소프트웨어학과", "소프트웨어학과", "https://cms.dankook.ac.kr/web/sw")),  # 옛 조직
        ("학부", dept("2", "AI융합대학 소프트웨어학과", "소프트웨어학과", "http://cms.dankook.ac.kr/web/sw")),   # 같은 orgId
        ("프리무스국제대학", dept("9", "프리무스국제대학 국제경영학과", "국제경영학과", "", tel="")),
    ]
    out = build(entries)
    assert out["sw"]["college"] == "AI융합대학" and out["sw"]["org_ids"] == ["2", "1"]
    assert out["comm"]["name"] == "저널리즘전공·광고홍보전공"
    assert out["comm"]["college"] == "사회과학대학 미디어커뮤니케이션학부"
    assert out["org-9"]["platform"] == "none" and out["org-9"]["campus"] == "죽전"


def test_parse_college_skips_empty_dept_data():
    html = """<html><title>AI융합대학 - 단국대학교</title><div id="main-content">
      <script type="application/json" id="x_deptData">{"orgzNm": "AI융합대학 소프트웨어학과", "orgId": "1"}</script>
      <script type="application/json" id="y_deptData">{}</script></div></html>"""
    title, depts = parse_college(html)
    assert title == "AI융합대학" and [d["orgId"] for d in depts] == ["1"]


# --- discover_source ------------------------------------------------------------------

@pytest.mark.parametrize("title, role", [
    ("학과공지", "notice"), ("공지사항", "notice"), ("대학원 공지", "grad"), ("장학금 공지", "scholarship"),
    ("취업 정보", "jobs"), ("모바일과(국제대) 규정", "rules"), ("자료실", "archive"), ("갤러리", "ignore"),
    ("졸업작품", "capstone"), ("교외활동", "activity"), ("Q&A", None),
])
def test_role_guess(title, role):
    assert guess(ROLE_RULES, title) == role


def classify_fixture(name: str, path: str) -> Found:
    found = Found()
    _classify(BeautifulSoup((FIX / name).read_text(encoding="utf-8"), "lxml"), path, found)
    return found


def test_classify_board_data_and_page():
    board = classify_fixture("list_notice.html", "/web/mobilesystems/-8")
    assert board.sections == [{"title": "공지사항", "path": "/web/mobilesystems/-8", "area": "게시판", "count": 767}]
    profs = classify_fixture("data_professors.html", "/web/mobilesystems/-5")
    assert profs.datasets == {"professors": [{"path": "/web/mobilesystems/-5"}]}
    curri = classify_fixture("data_curriculum_primus.html", "/web/mobilesystems/-27")
    assert curri.datasets == {"curriculum": [{"path": "/web/mobilesystems/-27", "org": "프리무스국제대학"}]}
    page = classify_fixture("page_chem_graduation.html", "/web/chem/-38")
    assert page.pages[0]["title"] == "대학원 졸업요건" and page.pages[0]["area"] == "대학원"


def test_draft_is_valid_yaml_and_blocks_unreviewed_merge(tmp_path):
    d = Department(id="t", name="테스트학과", college="공과대학", campus="죽전", platform="dku_cms",
                   homepage="https://cms.dankook.ac.kr/web/t", majors=["테스트학과"], office={"tel": "031-8005-1"})
    found = Found(
        sections=[{"title": "공지사항", "path": "/web/t/-1", "count": 10, "area": "게시판"},
                  {"title": "Q&A", "path": "/web/t/-2", "count": 3, "area": "게시판"}],
        datasets={"professors": [{"path": "/web/t/-5"}]},
        pages=[{"title": "대학원 졸업요건", "path": "/web/t/-9", "chars": 900, "area": "대학원"}],
        broken=["/web/t/없는메뉴"], visited=5,
    )
    text = build_draft("t", d, found, "dku_cms")
    data = yaml.safe_load(text)["t"]
    assert data["sections"]["notice"]["path"] == "/web/t/-1"
    assert "review" in data["sections"] and "[검토] 역할 추정 실패" in text
    assert data["pages"]["grad_graduation"]["title"] == "대학원 졸업요건"
    assert data["reviewed_at"] is None and "# 404 메뉴: /web/t/없는메뉴" in text
    # review 역할이 남은 채로 합치면 레지스트리가 거부한다
    draft = tmp_path / "t.yaml"
    draft.write_text(text, encoding="utf-8")
    with pytest.raises(RegistryError, match="알 수 없는 역할 review"):
        SourceRegistry.load(draft)


# --- recheck_sources ------------------------------------------------------------------

from datetime import date as _date

from danbi.sources.models import DatasetEntry, Page, Section, Source
from scripts.recheck_sources import Diff, compare, dept_list_changes, report


def test_recheck_compare_paths():
    src = Source(id="t", type="dku_cms", name="t", base_url="https://cms.dankook.ac.kr/web/t",
                 sections={"notice": Section("notice", "공지", "/web/t/-1"), "jobs": Section("jobs", "취업", "/web/t/-2")},
                 datasets={"professors": [DatasetEntry("/web/t/-5")]},
                 pages={"location": Page("location", "오시는 길", "/web/t/-9")}, reviewed_at=_date(2026, 10, 2))
    found = Found(sections=[{"title": "공지", "path": "/web/t/-1"}, {"title": "장학 공지", "path": "/web/t/-7"}],
                  datasets={"professors": [{"path": "/web/t/-5"}], "curriculum": [{"path": "/web/t/-3"}]},
                  pages=[{"title": "인사말", "path": "/web/t/-8"}], broken=["/web/t/없음"])
    d = compare(src, found)
    assert d.new_boards == ["장학 공지 (/web/t/-7)"]
    assert d.missing == ["/web/t/-2", "/web/t/-9"]
    assert d.new_data == ["/web/t/-3"] and d.new_pages == ["인사말 (/web/t/-8)"]
    assert d.broken_menu == ["/web/t/없음"] and d.changed
    text = report([d, Diff("u")], None)
    assert "변경 있음 1개" in text and "## t" in text and "## u" not in text


def test_dept_list_changes():
    old = {"a": Department("a", "가학과", "공대", homepage="h1"), "gone": Department("gone", "폐지학과")}
    new = {"a": {"name": "가학과", "college": "AI대", "homepage": "h1", "office": {}},
           "b": {"name": "신설학과", "college": "공대", "homepage": "h2", "office": {}}}
    lines = dept_list_changes(old, new)
    assert "- 신설/새 사이트: b 신설학과 (h2)" in lines
    assert "- 사라짐: gone 폐지학과" in lines
    assert "- 변경: a 소속 공대 → AI대" in lines


# --- review_drafts ----------------------------------------------------------------------

from scripts.review_drafts import parse_draft, review

DRAFT = '''# 등록 초안
t:
  type: dku_cms
  kind: department
  name: "테스트학과"
  college: "공과대학"
  aliases: ["테스트학과"]   # 줄임말
  campus: "죽전"
  office: { tel: "031-8005-1" }
  base_url: https://cms.dankook.ac.kr/web/t
  description: "x"
  sections:
    notice: { title: "공지사항", path: "/web/t/-1" }   # 100건 · 메뉴: 커뮤니티
    rules: { title: "학과 규정(A)", path: "/web/t/-2" }   # 3건
    rules_2: { title: "학과 규정(B)", path: "/web/t/-3" }   # 3건 [검토] rules 역할이 둘 이상
    review: { title: "융합 세미나", path: "/web/t/-4" }   # 20건 [검토] 역할 추정 실패
    review_2: { title: "재학생", path: "/web/t/-5" }   # 50건 [검토] 역할 추정 실패
    archive: { title: "자료실", path: "/web/t/-6" }   # 1건
    activity: { title: "학생회 소식", path: "/web/t/-7" }   # 30건
  datasets:
    professors:
      - { path: "/web/t/-8" }
  pages:
    page_1: { title: "학과장 인사말", path: "/web/t/-9" }   # 900자 · 메뉴: 학과소개 [검토]
    graduation: { title: "졸업요건", path: "/web/t/-10" }   # 800자 · 메뉴: 대학원
    page_3: { title: "부설 연구소 규정", path: "/web/t/-11" }   # 900자
    page_4: { title: "오시는 길", path: "/web/t/-12" }   # 50자
  freshness: realtime
  reviewed_at: null
'''


def test_parse_draft_reads_comment_notes():
    sid, entry, items = parse_draft(DRAFT)
    assert sid == "t" and entry["name"] == "테스트학과"
    notice = items["sections"][0]
    assert (notice.id, notice.count, notice.area) == ("notice", 100, "커뮤니티")
    assert items["pages"][1].area == "대학원" and items["pages"][1].chars == 800


def test_review_rules():
    sid, entry, items = parse_draft(DRAFT)
    r = review(sid, entry, items, {}, _date(2026, 10, 3))
    secs = r.entry["sections"]
    assert set(secs) == {"notice", "rules", "rules_2", "activity"}
    assert secs["rules_2"]["same_as"] == "rules"            # 글 수가 같으면 같은 글 공유로 본다
    assert secs["activity"]["title"] == "융합 세미나"         # 보강 규칙으로 역할 결정
    assert any("재학생" in f for f in r.flags)                 # 역할 불명은 빼고 보고
    assert "자료실 (글 1건)" in r.dropped_sections and "학생회 소식 (커뮤니티·사진)" in r.dropped_sections
    assert r.entry["pages"] == {"grad_graduation": {"title": "졸업요건", "path": "/web/t/-10"}}
    assert r.published and r.entry["reviewed_at"] == _date(2026, 10, 3) and r.entry["reviewed_by"] == "claude"
    assert "테스트학" in r.entry["aliases"] and "테스트학과" not in r.entry["aliases"]


def test_review_overrides():
    sid, entry, items = parse_draft(DRAFT)
    ov = {"t": {"roles": {"/web/t/-5": "notice", "/web/t/-4": "drop"}, "aliases": ["테과"],
                "keep_pages": ["/web/t/-12"]}}
    r = review(sid, entry, items, ov, _date(2026, 10, 3))
    assert r.entry["sections"]["notice_2"]["title"] == "재학생"
    assert "융합 세미나 (overrides)" in r.dropped_sections
    assert "location" in r.entry["pages"] and "테과" in r.entry["aliases"]
    held = review(sid, entry, items, {"t": {"hold": "사이트 개편 중"}}, _date(2026, 10, 3))
    assert not held.published and held.entry["reviewed_at"] is None


def test_review_output_loads_into_registry(tmp_path):
    from scripts.review_drafts import write_outputs
    sid, entry, items = parse_draft(DRAFT)
    r = review(sid, entry, items, {}, _date(2026, 10, 3))
    out, rep = tmp_path / "deps.yaml", tmp_path / "report.md"
    write_outputs([r], out, rep, _date(2026, 10, 3))
    src = SourceRegistry.load(out).get("t")  # 날짜가 문자열로 쓰이면 여기서 거부된다
    assert src.reviewed_at == _date(2026, 10, 3) and src.reviewed_by == "claude"
    assert "## 확인 필요" in rep.read_text(encoding="utf-8")


def test_same_as_needs_similar_titles():
    text = DRAFT.replace('"학과 규정(B)"', '"원전자료"').replace('"학과 규정(A)"', '"임용자료"')
    sid, entry, items = parse_draft(text)
    r = review(sid, entry, items, {}, _date(2026, 10, 3))
    assert "same_as" not in r.entry["sections"]["rules_2"]  # 글 수(3건)만 같고 제목이 다르면 묶지 않는다


def test_denied_board_is_recorded_not_skipped():
    html = """<html><title>공지사항 - 스포츠경영학과</title><div id="main-content">
      <div class="portlet-boundary dku_bbs_web_BbsPortlet" id="p_p_id_dku_bbs_web_BbsPortlet_">
        <div class="alert alert-danger"><strong>BBS 경고</strong> 접근 거부</div></div></div></html>"""
    found = Found()
    _classify(BeautifulSoup(html, "lxml"), "/web/dsm/학부-공지사항", found)
    assert found.denied == [{"title": "공지사항", "path": "/web/dsm/학부-공지사항"}]
    assert not found.sections and not found.pages


def test_generated_file_has_no_yaml_anchors(tmp_path):
    from scripts.review_drafts import write_outputs
    sid, entry, items = parse_draft(DRAFT)
    r1 = review(sid, entry, items, {}, _date(2026, 10, 3))
    r2 = review("u", {**entry, "base_url": "https://cms.dankook.ac.kr/web/u"}, items, {}, _date(2026, 10, 3))
    r2.sid = "u"
    out = tmp_path / "deps.yaml"
    write_outputs([r1, r2], out, tmp_path / "r.md", _date(2026, 10, 3))
    text = out.read_text(encoding="utf-8")
    assert "&id" not in text and "*id" not in text and text.count("reviewed_at: 2026-10-03") == 2


def test_empty_curriculum_json_is_not_a_dataset():
    html = """<html><title>교과과정 - 심리학과</title><div id="main-content">
      <script type="application/json" id="x_deptData">{"orgzNm": "보건과학대학 심리학과", "orgzPrtNm": "심리학과"}</script>
      <script type="application/json" id="x_curriculumsByTypeData">{"cmm": [], "mod": [], "mic": [], "trk": []}</script>
      <p>준비 중</p></div></html>"""
    found = Found()
    _classify(BeautifulSoup(html, "lxml"), "/web/psychology/-9", found)
    assert found.datasets == {} and found.pages == []  # 빈 교과과정 페이지를 학과 소개로 등록하지 않는다


def test_env_overrides(monkeypatch, tmp_path):
    from danbi.config import load_settings
    monkeypatch.setenv("DANBI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DANBI_TRUST_PROXY", "1")
    monkeypatch.setenv("DANBI_PROXY_HOPS", "2")
    s = load_settings()
    assert s.ops.db_path == tmp_path / "danbi_ops.sqlite"
    assert s.crawler.cache_path == tmp_path / "cache" / "danbi_cache.sqlite"
    assert s.ops.trust_proxy_headers is True and s.ops.proxy_hops == 2 and s.enable_docs is False
