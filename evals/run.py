"""평가 실행기. 실제 LLM API를 호출하므로 비용이 든다 → 실행할 질문을 반드시 고른다.

  python -m evals.run --list                     # 질문 목록만 보기 (API 호출 없음)
  python -m evals.run --ids facility-shuttle,professor-office
  python -m evals.run --type 학칙 --limit 3
  python -m evals.run --all                      # 전체 (비용 주의)
  python -m evals.run --ids ... --model gemini-2.5-flash
  python -m evals.run --rescore evals/results/<파일>.json   # 기대값만 고친 뒤 다시 채점 (API 호출 없음)
결과는 evals/results/<시각>_<모델>.json 에 저장된다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import yaml

from danbi.agent.loop import FinalEvent, ToolEndEvent, ToolStartEvent
from danbi.bootstrap import build_agent, build_recorder
from danbi.config import PROJECT_ROOT, load_settings
from danbi.llm.base import ToolCall, Usage
from danbi.ops import new_run_id

from .scoring import score

QUESTIONS = PROJECT_ROOT / "evals" / "questions.yaml"
RESULTS = PROJECT_ROOT / "evals" / "results"


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    qs = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    ids = [q["id"] for q in qs]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"질문 ID 중복: {dupes}")
    return qs


def select(qs: list[dict], ids: str | None, qtype: str | None, limit: int | None) -> list[dict]:
    if ids:
        wanted = [i.strip() for i in ids.split(",") if i.strip()]
        unknown = set(wanted) - {q["id"] for q in qs}
        if unknown:
            raise SystemExit(f"없는 질문 ID: {', '.join(sorted(unknown))}")
        qs = [q for q in qs if q["id"] in wanted]
    if qtype:
        qs = [q for q in qs if q.get("type") == qtype]
    return qs[:limit] if limit else qs


async def run_one(agent, q: dict, recorder=None, batch: str = "") -> dict:
    calls: list[ToolCall] = []
    errors: list[str] = []
    final: FinalEvent | None = None
    t0 = time.monotonic()
    run_id = new_run_id()
    events = agent.run(q["question"])
    if recorder is not None:
        events = recorder.record(events, run_id=run_id, question=q["question"], channel="eval",
                                 tags={"eval_id": q["id"], "eval_type": q.get("type"), "batch": batch})
    async for ev in events:
        if isinstance(ev, ToolStartEvent):
            calls += ev.calls
        elif isinstance(ev, ToolEndEvent) and ev.result.is_error:
            errors.append(f"{ev.result.name}: {ev.result.content[:200]}")
        elif isinstance(ev, FinalEvent):
            final = ev
    s = score(q.get("expect") or {}, final.text if final else "", calls)
    return {
        "id": q["id"], "type": q.get("type"), "question": q["question"], "run_id": run_id,
        "answer": final.text if final else "",
        "stop_reason": final.stop_reason if final else "error",
        "tool_calls": [{"name": c.name, "arguments": c.arguments} for c in calls],
        "tool_errors": errors,
        "usage": asdict(final.usage) if final else asdict(Usage()),
        "elapsed": round(time.monotonic() - t0, 2),
        "passed": s.passed, "answer_ok": s.answer_ok, "source_ok": s.source_ok,
        "calls_ok": s.calls_ok, "no_result_ok": s.no_result_ok, "failures": s.failures,
    }


def summarize(results: list[dict], pricing: dict) -> str:
    n = len(results)
    if not n:
        return "결과 없음"

    def rate(key: str, rows=results) -> str:
        rows = [r for r in rows if r[key] is not None]
        return f"{sum(r[key] for r in rows)}/{len(rows)}" if rows else "-"

    tokens_in = sum(r["usage"]["input_tokens"] for r in results)
    tokens_out = sum(r["usage"]["output_tokens"] for r in results)
    lines = [
        "| ID | 유형 | 통과 | 답변 | 소스 | 호출 수 | 시간(초) | 실패 사유 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = lambda ok: "O" if ok else "X"  # noqa: E731
        lines.append(f"| {r['id']} | {r['type']} | {mark(r['passed'])} | {mark(r['answer_ok'])} | {mark(r['source_ok'])} "
                     f"| {len(r['tool_calls'])} | {r['elapsed']} | {'; '.join(r['failures'])} |")
    lines += [
        "",
        f"- 통과: {rate('passed')} · 정답률: {rate('answer_ok')} · 소스 선택 정확도: {rate('source_ok')} "
        f"· 결과 없음 처리: {rate('no_result_ok')} · 호출 수 상한 준수: {rate('calls_ok')}",
        f"- 평균 도구 호출 {sum(len(r['tool_calls']) for r in results) / n:.1f}회 · "
        f"평균 응답 {sum(r['elapsed'] for r in results) / n:.1f}초 · 토큰 입력 {tokens_in:,} / 출력 {tokens_out:,}",
    ]
    if pricing.get("input_per_mtok") is not None and pricing.get("output_per_mtok") is not None:
        cost = tokens_in / 1e6 * pricing["input_per_mtok"] + tokens_out / 1e6 * pricing["output_per_mtok"]
        lines.append(f"- 추정 비용: ${cost:.4f} (질문당 ${cost / n:.4f})")
    return "\n".join(lines)


def rescore(path: Path, qs: list[dict], pricing: dict) -> None:
    """저장된 답변을 현재 questions.yaml 기대값으로 다시 채점한다 (API 호출 없음)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    expects = {q["id"]: q.get("expect") or {} for q in qs}
    for r in data["results"]:
        calls = [ToolCall("", c["name"], c["arguments"]) for c in r["tool_calls"]]
        s = score(expects.get(r["id"], {}), r["answer"], calls)
        r.update(passed=s.passed, answer_ok=s.answer_ok, source_ok=s.source_ok, calls_ok=s.calls_ok,
                 no_result_ok=s.no_result_ok, failures=s.failures)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{data['model']} · {data['run_at']} (재채점)\n\n" + summarize(data["results"], pricing))


async def main_async(args: argparse.Namespace) -> None:
    qs = load_questions()
    if args.rescore:
        rescore(Path(args.rescore), qs, load_settings().llm.pricing)
        return
    if args.list:
        for q in qs:
            print(f"{q['id']:<26} [{q.get('type', '')}] {q['question']}")
        return
    if not (args.ids or args.type or args.limit or args.all):
        raise SystemExit("실행할 질문을 고르세요: --ids, --type, --limit 또는 --all (--list로 목록 보기). API 비용이 듭니다.")
    selected = qs if args.all else select(qs, args.ids, args.type, args.limit)
    if not selected:
        raise SystemExit("조건에 맞는 질문이 없습니다")

    settings = load_settings()
    if args.model:
        settings.llm.model = args.model
    agent = build_agent(settings)
    recorder = build_recorder(settings, agent)
    batch = f"{datetime.now():%Y%m%d-%H%M%S}"
    print(f"{settings.llm.provider}/{settings.llm.model} · 질문 {len(selected)}개", flush=True)

    results = []
    for q in selected:
        r = await run_one(agent, q, recorder, batch)
        results.append(r)
        print(f"  {'O' if r['passed'] else 'X'} {q['id']} ({len(r['tool_calls'])}회, {r['elapsed']}초)"
              + (f" — {'; '.join(r['failures'])}" if r["failures"] else ""), flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y%m%d-%H%M%S}_{settings.llm.model.replace('/', '_')}.json"
    out.write_text(json.dumps({
        "model": f"{settings.llm.provider}/{settings.llm.model}",
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + summarize(results, settings.llm.pricing))
    print(f"\n결과 저장: {out.relative_to(PROJECT_ROOT)}")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="단비 평가 실행 (API 비용 발생)")
    ap.add_argument("--list", action="store_true", help="질문 목록만 출력")
    ap.add_argument("--ids", help="쉼표로 구분한 질문 ID")
    ap.add_argument("--type", help="질문 유형 (예: 학칙)")
    ap.add_argument("--limit", type=int, help="최대 질문 수")
    ap.add_argument("--all", action="store_true", help="전체 질문 실행")
    ap.add_argument("--model", help="settings.yaml의 llm.model 대신 사용할 모델")
    ap.add_argument("--rescore", metavar="RESULT_JSON", help="저장된 결과를 다시 채점 (API 호출 없음)")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
