"""질문 이용권: 하루 한도 늘리기(daily)·추가 횟수(credits), 운영 CLI (LLM 없이)."""

import os
import subprocess
import sys
import time
from pathlib import Path

from danbi.llm.base import LLMError
from danbi.ops import TraceStore

from .fakes import Reply
from .test_api import events
from .test_auth import env, login, make  # noqa: F401  (env는 pytest 픽스처)

ROOT = Path(__file__).resolve().parent.parent
EMAIL = "student@dankook.ac.kr"   # test_auth.login이 로그인시키는 계정


def ask(client, text="질문"):
    r = client.post("/api/chat", json={"message": text})
    return r.status_code, (events(r) if r.status_code == 200 else r.json()["detail"])


def done_of(evs):
    return next(d for e, d in evs if e == "done")


# ---- 저장소 ----

def test_active_grants_filters_and_counts_credits():
    store = TraceStore(None)
    now = time.time()
    g_ok = store.add_grant(email=" Student@Dankook.ac.kr ", kind="credits", amount=3, starts_at=now - 10,
                           expires_at=None, created_by="t")
    store.add_grant(email=EMAIL, kind="daily", amount=9, starts_at=now - 10, expires_at=now - 1, created_by="t")  # 만료
    store.add_grant(email=EMAIL, kind="daily", amount=9, starts_at=now + 99, expires_at=None, created_by="t")     # 시작 전
    g_rev = store.add_grant(email=EMAIL, kind="daily", amount=9, starts_at=now - 10, expires_at=None, created_by="t")
    assert store.revoke_grant(g_rev, "t") and not store.revoke_grant(g_rev, "t")
    active = store.active_grants(EMAIL)
    assert [g["id"] for g in active] == [g_ok] and active[0]["left"] == 3
    # 차감: 진행 중(실행 기록 없음)은 세고, 오류로 끝난 실행은 빼고
    store.consume_credit(g_ok, "google:1", "run-a")
    store.consume_credit(g_ok, "google:1", "run-b")
    store.start_run("run-b", conversation_id=None, channel="web", question="q", provider="f", model="f",
                    system_hash="", tools_hash="", started_at=now)
    store.finish_run("run-b", status="error", stop_reason=None, answer=None, error="x", ended_at=now,
                     first_token_at=None, input_tokens=0, output_tokens=0, cached_tokens=0, cost_usd=None)
    assert store.active_grants(EMAIL)[0]["left"] == 2
    store.refund_credit("run-a")
    assert store.active_grants(EMAIL)[0]["left"] == 3
    for bad in (dict(kind="weekly", amount=1), dict(kind="credits", amount=0)):
        try:
            store.add_grant(email=EMAIL, starts_at=now, expires_at=None, created_by="t", **bad)
        except ValueError:
            continue
        raise AssertionError(bad)


# ---- 웹 채팅 ----

def test_daily_grant_raises_limit_even_before_first_login(env):  # noqa: F811
    client, store, google = make(env, replies=[Reply(text="답")] * 10)
    store.add_grant(email=EMAIL, kind="daily", amount=5, starts_at=time.time() - 1, expires_at=None, created_by="t")
    login(client, google)
    assert client.get("/api/me").json()["remaining"] == 5
    for left in (4, 3, 2, 1, 0):
        status, evs = ask(client)
        assert status == 200 and done_of(evs)["remaining"] == left and done_of(evs)["credits"] == 0
    status, detail = ask(client)
    assert status == 429 and "5번까지" in detail


def test_credits_used_after_daily_limit(env):  # noqa: F811
    client, store, google = make(env, replies=[Reply(text="답")] * 10)
    gid = store.add_grant(email=EMAIL, kind="credits", amount=2, starts_at=time.time() - 1, expires_at=None,
                          created_by="t")
    login(client, google)
    me = client.get("/api/me").json()
    assert (me["remaining"], me["credits"]) == (5, 2)
    seen = []
    for _ in range(5):
        status, evs = ask(client)
        assert status == 200
        seen.append((done_of(evs)["remaining"], done_of(evs)["credits"]))
    assert seen == [(4, 2), (3, 2), (2, 2), (1, 1), (0, 0)]   # 무료 3회 다음에 이용권
    status, detail = ask(client)
    assert status == 429 and "3번까지" in detail
    ledger = store._all("SELECT * FROM credit_ledger")
    assert len(ledger) == 2 and {r["grant_id"] for r in ledger} == {gid} and ledger[0]["user_key"] == "google:1"
    runs = {r["id"] for r in store._all("SELECT id FROM runs")}
    assert {r["run_id"] for r in ledger} <= runs                # 차감 기록은 실제 실행과 같은 ID


def test_failed_or_rejected_questions_give_credit_back(env):  # noqa: F811
    replies = [Reply(text="답")] * 3 + [Reply(error=LLMError("고장"))] + [Reply(text="답")] * 3
    client, store, google = make(env, replies=replies)
    store.add_grant(email=EMAIL, kind="credits", amount=1, starts_at=time.time() - 1, expires_at=None, created_by="t")
    login(client, google)
    for _ in range(3):
        ask(client)
    status, evs = ask(client)                                  # 이용권으로 물었지만 우리 쪽 오류
    assert status == 200 and store.active_grants(EMAIL)[0]["left"] == 1
    client.app.state.guard.slots._value = 0                    # 동시 처리 자리 없음 → 시작도 못 함
    status, evs = ask(client)
    assert ("error", {"message": "지금 질문이 많아요. 잠시 후 다시 시도해 주세요."}) in evs
    ledger = store._all("SELECT l.run_id, r.status FROM credit_ledger l LEFT JOIN runs r ON r.id = l.run_id")
    assert store.active_grants(EMAIL)[0]["left"] == 1
    assert [r["status"] for r in ledger] == ["error"]           # 오류 실행의 기록은 남지만 세지 않고, 거절된 것은 지운다


def test_other_users_are_not_affected(env):  # noqa: F811
    client, store, google = make(env, replies=[Reply(text="답")] * 5)
    store.add_grant(email="someone@dankook.ac.kr", kind="daily", amount=50, starts_at=time.time() - 1,
                    expires_at=None, created_by="t")
    login(client, google)
    me = client.get("/api/me").json()
    assert (me["remaining"], me["credits"]) == (3, 0)


# ---- 운영 CLI ----

def cli(tmp_path, *args):
    e = {**os.environ, "DANBI_DATA_DIR": str(tmp_path), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "-m", "danbi.ops", *args], cwd=ROOT, env=e, capture_output=True,
                          text=True, encoding="utf-8")


def test_cli_grant_list_revoke(tmp_path):
    r = cli(tmp_path, "grant", "--email", "TA@dankook.ac.kr", "--daily", "20", "--until", "2099-12-31", "--note", "조교")
    assert r.returncode == 0 and "이용권 1: ta@dankook.ac.kr 하루 20회, 2099-12-31 23:59까지" in r.stdout
    r = cli(tmp_path, "grant", "--email", "x@gmail.com", "--credits", "5", "--days", "30")
    assert "주의: dankook.ac.kr 계정이 아닙니다" in r.stdout
    out = cli(tmp_path, "grants").stdout
    assert "[1] 유효 · ta@dankook.ac.kr · 하루 20회 · 2099-12-31 23:59까지 · admin · 조교" in out
    assert "[2] 유효 · x@gmail.com · 추가 5회 (남은 5회)" in out
    assert cli(tmp_path, "revoke", "1").returncode == 0 and cli(tmp_path, "revoke", "1").returncode != 0
    assert "[1]" not in cli(tmp_path, "grants").stdout and "[1] 취소됨" in cli(tmp_path, "grants", "--all").stdout
    store = TraceStore(tmp_path / "danbi_ops.sqlite")
    assert [a["action"] for a in store.audit_rows()][:3] == ["revoke_grant", "grant", "grant"]  # 감사 로그 (최신순)
    assert store.verify_audit()["ok"]
