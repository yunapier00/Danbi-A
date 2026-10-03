"""터미널 대화 (개발·디버깅용).

  python -m danbi.cli                       # 대화 모드 (/reset: 대화 초기화, /quit: 종료)
  python -m danbi.cli -q "셔틀 첫차 몇 시야?"  # 한 번만 묻기
  python -m danbi.cli -v                    # 도구 결과 미리보기 출력
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .agent.loop import (
    FALLBACK_ANSWER,
    LIMIT_ANSWER,
    Agent,
    FinalEvent,
    TokenEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from .bootstrap import build_agent, build_recorder
from .config import load_settings
from .llm.base import Message
from .ops import new_run_id

DIM, RED, RESET = "\033[2m", "\033[31m", "\033[0m"


def _fmt_call(name: str, args: dict) -> str:
    return f"{name}({', '.join(f'{k}={json.dumps(v, ensure_ascii=False)}' for k, v in args.items())})"


async def ask(agent: Agent, question: str, history: list[Message], verbose: bool,
              recorder=None, conversation_id: str | None = None) -> list[Message]:
    at_line_start = True
    events = agent.run(question, history=history)
    if recorder is not None:
        events = recorder.record(events, run_id=new_run_id(), question=question, channel="cli",
                                 conversation_id=conversation_id)
    async for ev in events:
        if isinstance(ev, TokenEvent):
            print(ev.text, end="", flush=True)
            at_line_start = ev.text.endswith("\n")
        elif isinstance(ev, ToolStartEvent):
            if not at_line_start:
                print()
            for c in ev.calls:
                print(f"{DIM}  ▸ {_fmt_call(c.name, c.arguments)}{RESET}")
            at_line_start = True
        elif isinstance(ev, ToolEndEvent):
            r = ev.result
            if r.is_error:
                print(f"{RED}  ✗ {r.name}: {r.content[:200]}{RESET}")
            elif verbose:
                preview = r.content if len(r.content) < 1500 else r.content[:1500] + " …"
                print(f"{DIM}{preview}{RESET}")
        elif isinstance(ev, FinalEvent):
            if ev.text in (FALLBACK_ANSWER, LIMIT_ANSWER):  # 스트리밍되지 않은 대체 답변
                print(ev.text, end="")
            elif not ev.text:
                print("(빈 응답)", end="")
            u = ev.usage
            detail = f"도구 {ev.tool_calls_used}회 · 토큰 입력 {u.input_tokens:,}(캐시 {u.cached_tokens:,})/출력 {u.output_tokens:,} · {ev.elapsed:.1f}초"
            if ev.stop_reason != "end":
                detail += f" · 종료: {ev.stop_reason}"
            if ev.error:
                detail += f" · {ev.error}"
            print(f"\n{DIM}[{detail}]{RESET}")
            return ev.messages
    return history


async def main_async(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    if args.model:
        settings.llm.model = args.model
    agent = build_agent(settings, with_tools=not args.no_tools)
    recorder = None if args.no_trace else build_recorder(settings, agent)
    conversation_id = new_run_id()
    print(f"{DIM}단비 — {settings.llm.provider}/{settings.llm.model} · 도구: "
          f"{', '.join(s.name for s in agent.tools.specs()) or '없음'}{RESET}")

    if args.question:
        await ask(agent, args.question, [], args.verbose, recorder, conversation_id)
        return

    history: list[Message] = []
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not q:
            continue
        if q in ("/quit", "/exit"):
            return
        if q == "/reset":
            history = []
            conversation_id = new_run_id()
            print(f"{DIM}대화를 초기화했습니다.{RESET}")
            continue
        history = await ask(agent, q, history, args.verbose, recorder, conversation_id)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="단비 터미널 대화")
    ap.add_argument("-q", "--question", help="한 번만 묻고 종료")
    ap.add_argument("--model", help="settings.yaml의 llm.model 대신 사용할 모델")
    ap.add_argument("--config", help="설정 파일 경로 (기본: config/settings.yaml)")
    ap.add_argument("--no-tools", action="store_true", help="도구 없이 대화")
    ap.add_argument("--no-trace", action="store_true", help="추적 DB(data/danbi_ops.sqlite)에 기록하지 않음")
    ap.add_argument("-v", "--verbose", action="store_true", help="도구 결과 미리보기")
    ap.add_argument("--log", default="WARNING", help="로그 레벨 (DEBUG, INFO, WARNING)")
    args = ap.parse_args()
    logging.basicConfig(level=args.log.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
