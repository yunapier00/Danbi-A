"""LLMOps 추적 저장소 (SQLite).

대화 → 실행(질문 1개) → LLM 호출·도구 호출 → 출처의 계층으로 저장한다. 실행마다 시스템 프롬프트·도구 정의의
해시를 남기고 원문은 prompt_versions에 한 번만 저장하므로, 어떤 답이 어떤 프롬프트·도구 정의·모델로 나왔는지
나중에 그대로 재현해 볼 수 있다.

감사 로그(audit_log)는 추가만 하고 고치지 않는다. 각 행이 이전 행의 해시를 이어받는 해시 체인이라
중간 행을 고치거나 지우면 verify_audit()가 찾아낸다.

별도 DB 서버 없이 쓰는 로컬 저장소다. 스키마는 표준 SQL만 써서 나중에 Postgres로 옮기기 쉽게 했다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 4  # 2: runs.client_ip, 3: runs.user_key, 4: users·auth_sessions (Google 로그인)
MAX_TEXT = 50_000  # 도구 결과·답변 저장 상한 (감사용으로 거의 전부 남긴다)

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    channel     TEXT NOT NULL,              -- web | cli | eval
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    turns       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS prompt_versions (
    hash        TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,              -- system | tools
    content     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    turn            INTEGER,
    channel         TEXT NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT,
    status          TEXT NOT NULL,          -- running | ok | error | limit | refused | max_tokens | aborted
    stop_reason     TEXT,
    error           TEXT,
    provider        TEXT,
    model           TEXT,
    system_hash     TEXT,
    tools_hash      TEXT,
    started_at      REAL NOT NULL,
    ended_at        REAL,
    latency_ms      INTEGER,
    first_token_ms  INTEGER,
    llm_calls       INTEGER DEFAULT 0,
    tool_calls      INTEGER DEFAULT 0,
    tool_errors     INTEGER DEFAULT 0,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cached_tokens   INTEGER DEFAULT 0,
    cost_usd        REAL,
    tags            TEXT,                   -- JSON (예: {"eval_id": "..."})
    client_ip       TEXT,                   -- 웹 채널 요청 IP (ops.ip_retention_days를 정하면 purge가 지움)
    user_key        TEXT                    -- google:<users.id> | kakao:<해시> | ip:<해시> (카카오 원래 키는 저장하지 않음)
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES runs(id),
    seq           INTEGER NOT NULL,
    attempt       INTEGER NOT NULL,
    started_at    REAL NOT NULL,
    ended_at      REAL NOT NULL,
    latency_ms    INTEGER NOT NULL,
    input_tokens  INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    stop_reason   TEXT,
    text          TEXT,
    tool_calls    TEXT,                     -- JSON [{id, name, arguments}]
    error         TEXT
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL REFERENCES runs(id),
    llm_seq      INTEGER,
    call_id      TEXT,
    name         TEXT NOT NULL,
    arguments    TEXT,                      -- JSON
    status_text  TEXT,
    started_at   REAL NOT NULL,
    ended_at     REAL NOT NULL,
    latency_ms   INTEGER NOT NULL,
    is_error     INTEGER NOT NULL DEFAULT 0,
    result       TEXT,
    result_chars INTEGER
);
CREATE TABLE IF NOT EXISTS sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL REFERENCES runs(id),
    tool_call_id INTEGER REFERENCES tool_calls(id),
    kind         TEXT NOT NULL,             -- web | rag
    source_id    TEXT,
    title        TEXT,
    url          TEXT,
    cited        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(id),
    rating      INTEGER NOT NULL,           -- 1 = 좋아요, -1 = 별로
    comment     TEXT,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          REAL NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT,
    detail      TEXT,
    client      TEXT,
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (                 -- Google 로그인 사용자 (runs.user_key = 'google:<id>')
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    google_sub    TEXT NOT NULL UNIQUE,             -- Google 고유 ID (이메일은 바뀔 수 있어 식별에 쓰지 않음)
    email         TEXT NOT NULL,
    name          TEXT,
    hd            TEXT,                             -- Google Workspace 도메인
    role          TEXT NOT NULL DEFAULT 'user',
    blocked       INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    first_ip      TEXT,
    last_login_at REAL,
    last_ip       TEXT
);
CREATE TABLE IF NOT EXISTS auth_sessions (         -- 로그인 세션. 쿠키 값은 저장하지 않고 SHA-256 해시만 둔다
    id_hash       TEXT PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    created_at    REAL NOT NULL,
    last_seen_at  REAL NOT NULL,
    expires_at    REAL NOT NULL,
    ip            TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_auth_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_runs_conv ON runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_llm_run ON llm_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_run ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_calls(name);
CREATE INDEX IF NOT EXISTS idx_sources_run ON sources(run_id);
CREATE INDEX IF NOT EXISTS idx_feedback_run ON feedback(run_id);
"""

STATUS_OF_STOP = {"end": "ok", "error": "error", "limit": "limit", "refused": "refused", "max_tokens": "max_tokens"}
GENESIS = "0" * 64


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _clip(text: str | None) -> str | None:
    if text is None:
        return None
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + f"\n…(저장 상한 {MAX_TEXT:,}자에서 잘림, 원래 {len(text):,}자)"


def _ms(a: float, b: float) -> int:
    return max(0, int(round((b - a) * 1000)))


class TraceStore:
    def __init__(self, path: str | Path | None):
        """path=None이면 메모리 DB (테스트용)."""
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        if path is not None:
            self._db.execute("PRAGMA journal_mode = WAL")
        with self._lock:
            self._db.executescript(SCHEMA)
            self._migrate()
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._db.commit()

    def _migrate(self) -> None:
        """이전 버전 DB에 없는 컬럼을 추가한다 (락을 잡은 상태에서 호출)."""
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(runs)").fetchall()}
        if "client_ip" not in cols:
            self._db.execute("ALTER TABLE runs ADD COLUMN client_ip TEXT")
        if "user_key" not in cols:
            self._db.execute("ALTER TABLE runs ADD COLUMN user_key TEXT")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_runs_ip ON runs(client_ip, started_at)")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(user_key, started_at)")

    def _exec(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    def _all(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    # --- 기록 ----------------------------------------------------------------------

    def save_prompt_version(self, kind: str, content: str) -> str:
        h = content_hash(content)
        self._exec("INSERT OR IGNORE INTO prompt_versions (hash, kind, content, created_at) VALUES (?, ?, ?, ?)",
                   (h, kind, content, time.time()))
        return h

    def start_run(self, run_id: str, *, conversation_id: str | None, channel: str, question: str,
                  provider: str, model: str, system_hash: str, tools_hash: str, started_at: float,
                  tags: dict | None = None, client_ip: str | None = None, user_key: str | None = None) -> int:
        """실행을 'running'으로 시작한다. 대화가 없으면 만들고, 이 실행의 턴 번호를 돌려준다."""
        turn = None
        with self._lock:
            if conversation_id:
                self._db.execute(
                    "INSERT INTO conversations (id, channel, created_at, updated_at, turns) VALUES (?, ?, ?, ?, 0) "
                    "ON CONFLICT(id) DO NOTHING", (conversation_id, channel, started_at, started_at))
                self._db.execute("UPDATE conversations SET turns = turns + 1, updated_at = ? WHERE id = ?",
                                 (started_at, conversation_id))
                turn = self._db.execute("SELECT turns FROM conversations WHERE id = ?", (conversation_id,)).fetchone()[0]
            self._db.execute(
                "INSERT INTO runs (id, conversation_id, turn, channel, question, status, provider, model, system_hash, "
                "tools_hash, started_at, tags, client_ip, user_key) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, conversation_id, turn, channel, question, provider, model, system_hash, tools_hash,
                 started_at, json.dumps(tags or {}, ensure_ascii=False), client_ip, user_key))
            self._db.commit()
        return turn or 0

    def add_llm_call(self, run_id: str, *, seq: int, attempt: int, started: float, ended: float,
                     input_tokens: int, output_tokens: int, cached_tokens: int, stop_reason: str | None,
                     text: str, tool_calls: list[dict], error: str | None) -> None:
        self._exec(
            "INSERT INTO llm_calls (run_id, seq, attempt, started_at, ended_at, latency_ms, input_tokens, output_tokens, "
            "cached_tokens, stop_reason, text, tool_calls, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, seq, attempt, started, ended, _ms(started, ended), input_tokens, output_tokens, cached_tokens,
             stop_reason, _clip(text), json.dumps(tool_calls, ensure_ascii=False), error))

    def add_tool_call(self, run_id: str, *, llm_seq: int, call_id: str, name: str, arguments: dict,
                      status_text: str, started: float, ended: float, is_error: bool, result: str) -> int:
        cur = self._exec(
            "INSERT INTO tool_calls (run_id, llm_seq, call_id, name, arguments, status_text, started_at, ended_at, "
            "latency_ms, is_error, result, result_chars) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, llm_seq, call_id, name, json.dumps(arguments, ensure_ascii=False), status_text, started, ended,
             _ms(started, ended), int(is_error), _clip(result), len(result)))
        return int(cur.lastrowid)

    def add_sources(self, run_id: str, tool_call_id: int, refs: list) -> None:
        with self._lock:
            self._db.executemany(
                "INSERT INTO sources (run_id, tool_call_id, kind, source_id, title, url, cited) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(run_id, tool_call_id, r.kind, r.source_id, r.title, r.url, int(r.cited)) for r in refs])
            self._db.commit()

    def finish_run(self, run_id: str, *, status: str, stop_reason: str | None, answer: str | None,
                   error: str | None, ended_at: float, first_token_at: float | None,
                   input_tokens: int, output_tokens: int, cached_tokens: int, cost_usd: float | None) -> None:
        with self._lock:
            row = self._db.execute("SELECT started_at FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return
            started = row[0]
            counts = self._db.execute(
                "SELECT (SELECT COUNT(*) FROM llm_calls WHERE run_id = :r), "
                "(SELECT COUNT(*) FROM tool_calls WHERE run_id = :r), "
                "(SELECT COUNT(*) FROM tool_calls WHERE run_id = :r AND is_error = 1)", {"r": run_id}).fetchone()
            self._db.execute(
                "UPDATE runs SET status = ?, stop_reason = ?, answer = ?, error = ?, ended_at = ?, latency_ms = ?, "
                "first_token_ms = ?, llm_calls = ?, tool_calls = ?, tool_errors = ?, input_tokens = ?, output_tokens = ?, "
                "cached_tokens = ?, cost_usd = ? WHERE id = ?",
                (status, stop_reason, _clip(answer), error, ended_at, _ms(started, ended_at),
                 _ms(started, first_token_at) if first_token_at else None, counts[0], counts[1], counts[2],
                 input_tokens, output_tokens, cached_tokens, cost_usd, run_id))
            self._db.commit()

    def usage_since(self, since: float, channels: tuple[str, ...] = ("web", "kakao")) -> dict:
        """since 이후 공개 채널의 실행 수·토큰 합 (진행 중 포함). 하루 사용량 상한 확인용 (CLI·평가는 빼고 센다)."""
        marks = ", ".join("?" * len(channels))
        row = self._one("SELECT COUNT(*) AS runs, COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens "
                        f"FROM runs WHERE started_at >= ? AND channel IN ({marks})", (since, *channels)) or {}
        return {"runs": row.get("runs", 0), "tokens": row.get("tokens", 0)}

    def count_user_since(self, since: float, *, client_ip: str | None = None, user_key: str | None = None) -> int:
        """since 이후 한 사람(웹은 IP, 카카오는 사용자 키)의 질문 수. 우리 쪽 오류(status=error)는 세지 않는다."""
        if user_key:
            col, val = "user_key", user_key
        elif client_ip:
            col, val = "client_ip", client_ip
        else:
            return 0
        row = self._one(f"SELECT COUNT(*) AS n FROM runs WHERE {col} = ? AND started_at >= ? AND status != 'error'",
                        (val, since)) or {}
        return int(row.get("n", 0))

    def add_feedback(self, run_id: str, rating: int, comment: str | None) -> bool:
        if self._one("SELECT id FROM runs WHERE id = ?", (run_id,)) is None:
            return False
        self._exec("INSERT INTO feedback (run_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
                   (run_id, 1 if rating > 0 else -1, (comment or "")[:1000] or None, time.time()))
        return True

    # --- 감사 로그 (해시 체인) ---------------------------------------------------------

    @staticmethod
    def _audit_hash(prev: str, at: float, actor: str, action: str, target: str, detail: str, client: str) -> str:
        payload = json.dumps([prev, round(at, 6), actor, action, target, detail, client], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def audit(self, actor: str, action: str, target: str = "", detail: dict | str | None = None,
              client: str = "") -> None:
        detail_s = detail if isinstance(detail, str) else json.dumps(detail or {}, ensure_ascii=False, sort_keys=True)
        with self._lock:
            last = self._db.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev = last[0] if last else GENESIS
            at = time.time()
            h = self._audit_hash(prev, at, actor, action, target, detail_s, client)
            self._db.execute(
                "INSERT INTO audit_log (at, actor, action, target, detail, client, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (at, actor, action, target, detail_s, client, prev, h))
            self._db.commit()

    def verify_audit(self) -> dict:
        """해시 체인을 처음부터 다시 계산한다. 고쳐지거나 빠진 행이 있으면 첫 위치를 알려 준다."""
        prev = GENESIS
        rows = self._all("SELECT * FROM audit_log ORDER BY id")
        for r in rows:
            expected = self._audit_hash(prev, r["at"], r["actor"], r["action"], r["target"] or "", r["detail"] or "",
                                        r["client"] or "")
            if r["prev_hash"] != prev or r["hash"] != expected:
                return {"ok": False, "rows": len(rows), "broken_at": r["id"]}
            prev = r["hash"]
        return {"ok": True, "rows": len(rows), "broken_at": None}

    def audit_rows(self, limit: int = 200) -> list[dict]:
        return self._all("SELECT id, at, actor, action, target, detail, client, hash FROM audit_log ORDER BY id DESC LIMIT ?",
                         (limit,))

    # --- 조회 ----------------------------------------------------------------------

    @staticmethod
    def _where(since: float | None, until: float | None, channel: str | None, alias: str = "r") -> tuple[str, list]:
        cond, params = [f"{alias}.status != 'running'"], []
        if since is not None:
            cond.append(f"{alias}.started_at >= ?")
            params.append(since)
        if until is not None:
            cond.append(f"{alias}.started_at < ?")
            params.append(until)
        if channel:
            cond.append(f"{alias}.channel = ?")
            params.append(channel)
        return " AND ".join(cond), params

    def overview(self, since: float | None = None, until: float | None = None, channel: str | None = None,
                 bucket: str = "day") -> dict:
        where, params = self._where(since, until, channel)
        runs = self._all(f"SELECT status, latency_ms, first_token_ms, tool_calls, input_tokens, output_tokens, "
                         f"cached_tokens, cost_usd, started_at FROM runs r WHERE {where}", params)
        latencies = sorted(r["latency_ms"] or 0 for r in runs)
        fmt = "%Y-%m-%d %H:00" if bucket == "hour" else "%Y-%m-%d"
        series = self._all(
            f"SELECT strftime('{fmt}', started_at, 'unixepoch', 'localtime') AS t, COUNT(*) AS runs, "
            f"SUM(status != 'ok') AS failed, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
            f"GROUP_CONCAT(latency_ms) AS lat FROM runs r WHERE {where} GROUP BY t ORDER BY t", params)
        for s in series:
            lat = sorted(int(x) for x in (s.pop("lat") or "").split(",") if x)
            s["p50_ms"], s["p95_ms"] = _pct(lat, 50), _pct(lat, 95)
        tools = self._all(
            f"SELECT t.name, COUNT(*) AS calls, SUM(t.is_error) AS errors, AVG(t.latency_ms) AS avg_ms "
            f"FROM tool_calls t JOIN runs r ON r.id = t.run_id WHERE {where} GROUP BY t.name ORDER BY calls DESC", params)
        top_sources = self._all(
            f"SELECT s.kind, s.source_id, COUNT(*) AS hits, SUM(s.cited) AS cited "
            f"FROM sources s JOIN runs r ON r.id = s.run_id WHERE {where} GROUP BY s.kind, s.source_id "
            f"ORDER BY hits DESC LIMIT 15", params)
        statuses = self._all(f"SELECT status, COUNT(*) AS n FROM runs r WHERE {where} GROUP BY status ORDER BY n DESC",
                             params)
        fb = self._one(
            f"SELECT SUM(f.rating > 0) AS up, SUM(f.rating < 0) AS down FROM feedback f JOIN runs r ON r.id = f.run_id "
            f"WHERE {where}", params) or {}
        cite = self._one(f"SELECT COUNT(*) AS refs, SUM(s.cited) AS cited FROM sources s JOIN runs r ON r.id = s.run_id "
                         f"WHERE {where}", params) or {}
        n = len(runs)
        costs = [r["cost_usd"] for r in runs if r["cost_usd"] is not None]
        return {
            "totals": {
                "runs": n,
                "conversations": (self._one(f"SELECT COUNT(DISTINCT conversation_id) AS c FROM runs r WHERE {where}",
                                            params) or {}).get("c", 0),
                "client_ips": (self._one(f"SELECT COUNT(DISTINCT client_ip) AS c FROM runs r WHERE {where}",
                                         params) or {}).get("c", 0),
                "failed": sum(r["status"] != "ok" for r in runs),
                "p50_ms": _pct(latencies, 50), "p95_ms": _pct(latencies, 95),
                "avg_first_token_ms": _avg([r["first_token_ms"] for r in runs if r["first_token_ms"]]),
                "avg_tool_calls": _avg([r["tool_calls"] for r in runs]),
                "input_tokens": sum(r["input_tokens"] or 0 for r in runs),
                "output_tokens": sum(r["output_tokens"] or 0 for r in runs),
                "cached_tokens": sum(r["cached_tokens"] or 0 for r in runs),
                "cost_usd": round(sum(costs), 4) if costs else None,
                "feedback_up": fb.get("up") or 0, "feedback_down": fb.get("down") or 0,
                "source_refs": cite.get("refs") or 0, "source_cited": cite.get("cited") or 0,
            },
            "series": series, "tools": tools, "sources": top_sources, "statuses": statuses, "bucket": bucket,
        }

    def list_runs(self, *, since: float | None = None, until: float | None = None, channel: str | None = None,
                  status: str | None = None, tool: str | None = None, q: str | None = None,
                  limit: int = 50, offset: int = 0) -> dict:
        where, params = self._where(since, until, channel)
        if status:
            where += " AND r.status = ?"
            params.append(status)
        if tool:
            where += " AND EXISTS (SELECT 1 FROM tool_calls t WHERE t.run_id = r.id AND t.name = ?)"
            params.append(tool)
        if q:
            where += (" AND (r.question LIKE ? OR r.answer LIKE ? OR r.id LIKE ? OR r.client_ip = ? OR r.user_key = ?"
                      " OR u.email LIKE ?)")
            params += [f"%{q}%", f"%{q}%", f"{q}%", q, q, f"%{q}%"]
        joined = f"FROM runs r LEFT JOIN users u ON r.user_key = 'google:' || u.id WHERE {where}"
        total = (self._one(f"SELECT COUNT(*) AS n {joined}", params) or {}).get("n", 0)
        rows = self._all(
            f"SELECT r.id, r.conversation_id, r.turn, r.channel, r.question, r.status, r.model, r.started_at, "
            f"r.latency_ms, r.tool_calls, r.tool_errors, r.input_tokens, r.output_tokens, r.client_ip, "
            f"u.email AS user_email, "
            f"(SELECT SUM(rating) FROM feedback f WHERE f.run_id = r.id) AS feedback "
            f"{joined} ORDER BY r.started_at DESC LIMIT ? OFFSET ?", [*params, limit, offset])
        return {"total": total, "items": rows}

    def run_detail(self, run_id: str) -> dict | None:
        run = self._one("SELECT * FROM runs WHERE id = ?", (run_id,))
        if run is None:
            return None
        run["tags"] = json.loads(run["tags"] or "{}")
        llm = self._all("SELECT * FROM llm_calls WHERE run_id = ? ORDER BY started_at, id", (run_id,))
        for c in llm:
            c["tool_calls"] = json.loads(c["tool_calls"] or "[]")
        tools = self._all("SELECT * FROM tool_calls WHERE run_id = ? ORDER BY started_at, id", (run_id,))
        for t in tools:
            t["arguments"] = json.loads(t["arguments"] or "{}")
        user = None
        if (run.get("user_key") or "").startswith("google:"):
            user = self._one("SELECT id, email, name, hd, blocked FROM users WHERE 'google:' || id = ?", (run["user_key"],))
        return {
            "run": run, "user": user, "llm_calls": llm, "tool_calls": tools,
            "sources": self._all("SELECT * FROM sources WHERE run_id = ? ORDER BY id", (run_id,)),
            "feedback": self._all("SELECT * FROM feedback WHERE run_id = ? ORDER BY id", (run_id,)),
            "conversation": self._all(
                "SELECT id, turn, question, status, started_at FROM runs WHERE conversation_id = ? ORDER BY turn",
                (run["conversation_id"],)) if run["conversation_id"] else [],
        }

    # --- 로그인 (Google) -------------------------------------------------------------

    def upsert_user(self, *, google_sub: str, email: str, name: str | None, hd: str | None, ip: str | None) -> dict:
        """로그인할 때마다 이메일·이름·마지막 IP를 갱신한다. 처음이면 만든다."""
        now = time.time()
        with self._lock:
            self._db.execute(
                "INSERT INTO users (google_sub, email, name, hd, created_at, first_ip, last_login_at, last_ip) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(google_sub) DO UPDATE SET email = excluded.email, "
                "name = excluded.name, hd = excluded.hd, last_login_at = excluded.last_login_at, last_ip = excluded.last_ip",
                (google_sub, email, name, hd, now, ip, now, ip))
            self._db.commit()
        return self._one("SELECT * FROM users WHERE google_sub = ?", (google_sub,))

    def create_session(self, user_id: int, id_hash: str, ttl: float, ip: str | None) -> None:
        now = time.time()
        self._exec("INSERT INTO auth_sessions (id_hash, user_id, created_at, last_seen_at, expires_at, ip) "
                   "VALUES (?, ?, ?, ?, ?, ?)", (id_hash, user_id, now, now, now + ttl, ip))

    def session_user(self, id_hash: str) -> dict | None:
        """유효한 세션이면 사용자 + session_created_at·session_last_seen_at. 만료·차단이면 None."""
        return self._one(
            "SELECT u.*, s.created_at AS session_created_at, s.last_seen_at AS session_last_seen_at "
            "FROM auth_sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.id_hash = ? AND s.expires_at > ? AND u.blocked = 0", (id_hash, time.time()))

    def touch_session(self, id_hash: str, ttl: float) -> None:
        """쓸 때마다 만료를 미룬다 (슬라이딩 만료)."""
        now = time.time()
        self._exec("UPDATE auth_sessions SET last_seen_at = ?, expires_at = ? WHERE id_hash = ?", (now, now + ttl, id_hash))

    def delete_session(self, id_hash: str) -> None:
        self._exec("DELETE FROM auth_sessions WHERE id_hash = ?", (id_hash,))

    def set_user_blocked(self, user_id: int, blocked: bool) -> None:
        with self._lock:
            self._db.execute("UPDATE users SET blocked = ? WHERE id = ?", (int(blocked), user_id))
            if blocked:
                self._db.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
            self._db.commit()

    def prompt_version(self, h: str) -> dict | None:
        return self._one("SELECT * FROM prompt_versions WHERE hash = ?", (h,))

    def export_runs(self, since: float | None = None, until: float | None = None):
        """실행 단위 JSON을 하나씩 돌려준다 (JSONL 내보내기용)."""
        where, params = self._where(since, until, None)
        for r in self._all(f"SELECT id FROM runs r WHERE {where} ORDER BY started_at", params):
            yield self.run_detail(r["id"])

    def purge(self, older_than_days: float | None, ip_older_than_days: float | None = None) -> int:
        """보관 기간이 지난 실행과 하위 기록을 지운다. IP는 더 짧은 기간 뒤 실행에서 지운다(비움).
        기간이 None이면 그 항목은 지우지 않는다 (무기한). 감사 로그는 지우지 않는다."""
        with self._lock:
            if ip_older_than_days is not None:
                self._db.execute("UPDATE runs SET client_ip = NULL WHERE client_ip IS NOT NULL AND started_at < ?",
                                 (time.time() - ip_older_than_days * 86400,))
            if older_than_days is None:
                self._db.commit()
                return 0
        cutoff = time.time() - older_than_days * 86400
        with self._lock:
            ids = [r[0] for r in self._db.execute("SELECT id FROM runs WHERE started_at < ?", (cutoff,)).fetchall()]
            for table in ("sources", "feedback", "tool_calls", "llm_calls"):
                self._db.execute(f"DELETE FROM {table} WHERE run_id IN (SELECT id FROM runs WHERE started_at < ?)",
                                 (cutoff,))
            self._db.execute("DELETE FROM runs WHERE started_at < ?", (cutoff,))
            self._db.execute("DELETE FROM conversations WHERE id NOT IN (SELECT DISTINCT conversation_id FROM runs "
                             "WHERE conversation_id IS NOT NULL)")
            self._db.commit()
        return len(ids)


def _pct(sorted_values: list[int], p: int) -> int | None:
    if not sorted_values:
        return None
    k = max(0, min(len(sorted_values) - 1, int(round(p / 100 * (len(sorted_values) - 1)))))
    return sorted_values[k]


def _avg(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None
