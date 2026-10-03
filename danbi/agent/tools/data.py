"""query_data의 필터링·출력. 레코드 형식은 crawler/adapters/base.py 주석 참고."""

from __future__ import annotations

MAX_ROWS = 100
SUMMARY_ROWS = 8  # 결과가 이 수 이하이거나 keyword 검색이면 과목 개요도 보여준다
SUMMARY_CHARS = 150


def _has(text: str, needle: str) -> bool:
    return needle.replace(" ", "").lower() in (text or "").replace(" ", "").lower()


def filter_records(kind: str, records: list[dict], *, name: str | None = None, keyword: str | None = None,
                   grade: int | None = None, semester: int | None = None, category: str | None = None,
                   org: str | None = None, month: int | None = None, on_date: str | None = None) -> list[dict]:
    out = []
    for r in records:
        if org and not _has(r.get("org", ""), org):
            continue
        if kind == "calendar":
            if keyword and not _has(r["title"], keyword):
                continue
            if month and not _overlaps_month(r, month):
                continue
            if on_date and not (r["start"] <= on_date <= r["end"]):
                continue
            out.append(r)
            continue
        if kind == "menu":
            if (keyword or name) and not _has(r["name"], keyword or name):
                continue
            if category and not _has(r["corner"], category):
                continue
            out.append(r)
            continue
        if kind == "professors":
            if name and not (_has(r["name"], name) or _has(r["eng_name"], name)):
                continue
            if keyword and not any(_has(str(r.get(k, "")), keyword) for k in ("position", "role", "office", "name")):
                continue
        elif kind == "curriculum":
            if name and not (_has(r["name"], name) or _has(r["eng_name"], name)):
                continue
            if keyword and not any(_has(r.get(k, ""), keyword) for k in ("name", "eng_name", "summary")):
                continue
            if category and not any(_has(r.get(k, ""), category) for k in ("category", "group", "program")):
                continue
            if grade or semester:
                want = [s for s in r["semesters"]
                        if (not grade or s.startswith(f"{grade}-")) and (not semester or s.endswith(f"-{semester}"))]
                if not want:
                    continue
        out.append(r)
    return out


def _overlaps_month(r: dict, month: int) -> bool:
    """일정 기간이 그 달(어느 해든 학년도 안의 그 달)과 겹치는지."""
    start, end = r["start"][:7], r["end"][:7]
    year = int(r["start"][:4])
    for y in (year, year + 1):
        ym = f"{y}-{month:02d}"
        if start <= ym <= end:
            return True
    return False


def format_records(kind: str, records: list[dict], *, verbose: bool = False) -> str:
    if kind == "calendar":
        lines = [f"- {r['start']}" + (f" ~ {r['end']}" if r["end"] != r["start"] else "") + f" | {r['title']}"
                 for r in records[:MAX_ROWS]]
        if len(records) > MAX_ROWS:
            lines.append(f"…(전체 {len(records)}건 중 {MAX_ROWS}건만 표시. month·keyword로 좁히세요)")
        return "\n".join(lines)
    if kind == "menu":
        lines, group = [], None
        for r in records[:MAX_ROWS * 2]:
            if (r["org"], r["corner"]) != group:
                group = (r["org"], r["corner"])
                lines.append(f"### {r['org']} · {r['corner']}" if r["org"] else f"### {r['corner']}")
            price = f"{r['price']:,}원" if isinstance(r.get("price"), int) else "가격 미상"
            lines.append(f"- {r['name']} {price}" + (" (품절)" if r["sold_out"] else ""))
        return "\n".join(lines)
    if kind == "professors":
        return "\n".join(_professor(r) for r in records)
    if kind == "dept_info":
        return "\n\n".join(_dept(r) for r in records)
    if kind == "curriculum":
        return _curriculum(records, verbose)
    return "\n".join(str(r) for r in records)


def _professor(r: dict) -> str:
    head = f"- {r['name']}" + (f" ({r['eng_name']})" if r["eng_name"] else "") + f" — {r['position']}"
    fields = [("보직", r["role"]), ("소속", r["org"]), ("연구실", r["office"]), ("전화", r["tel"]),
              ("이메일", r["email"]), ("홈페이지", r["homepage"]), ("교수 정보", r["detail_url"])]
    lines = [head] + [f"  {k}: {v}" for k, v in fields if v]
    lines += [f"  학력: {e}" for e in r.get("education") or [] if e]
    return "\n".join(lines)


def _dept(r: dict) -> str:
    parts = [f"## {r['name']}" + (f" (정보 수정일: {r['updated']})" if r.get("updated") else "")]
    parts += [f"### {k}\n{v}" for k, v in r["sections"].items()]
    if r["contact"]:
        parts.append("### 연락처\n" + "\n".join(f"- {k}: {v}" for k, v in r["contact"].items()))
    return "\n\n".join(parts)


def _curriculum(records: list[dict], verbose: bool) -> str:
    rows = ["| 소속 | 구분 | 이수구분 | 과목명 | 학점 | 개설 학년-학기 |", "|---|---|---|---|---|---|"]
    for r in records[:MAX_ROWS]:
        program = r["program"] if r["group"] in ("", r["category"]) else f"{r['program']} {r['group']}"
        name = r["name"] + (f" ({r['eng_name']})" if r["eng_name"] and r["eng_name"] != r["name"] else "")
        rows.append(f"| {r['org']} | {program} | {r['category']} | {name} | {r['credit']} | {', '.join(r['semesters']) or '-'} |")
    out = "\n".join(rows)
    if len(records) > MAX_ROWS:
        out += f"\n…(전체 {len(records)}과목 중 {MAX_ROWS}과목만 표시. 학년·학기·이수구분으로 좁히세요)"
    if verbose:
        summaries = [
            f"- {r['name']}: {r['summary'][:SUMMARY_CHARS]}" + ("…" if len(r["summary"]) > SUMMARY_CHARS else "")
            for r in records[:SUMMARY_ROWS] if r["summary"]
        ]
        if summaries:
            out += "\n\n과목 개요:\n" + "\n".join(summaries)
    return out
