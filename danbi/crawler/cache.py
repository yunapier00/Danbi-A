"""크롤링 결과 SQLite 캐시 (자동 생성, 지워도 다시 만들어짐)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# 설계 §6.7
TTL_SEARCH = 10 * 60
TTL_LIST = 10 * 60
TTL_ITEM = 24 * 60 * 60
TTL_PAGE = 24 * 60 * 60
TTL_MENU = 10 * 60  # 학식 품절 표시
TTL_ATTACHMENT = 365 * 24 * 60 * 60  # 첨부 URL에는 파일 고유 ID가 들어 있어 내용이 바뀌지 않는다


class Cache:
    def __init__(self, path: str | Path | None):
        """path=None이면 메모리 캐시 (테스트용)."""
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL NOT NULL)")
        self._db.commit()

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._db.execute("SELECT value, expires FROM cache WHERE key = ?", (key,)).fetchone()
        if row is None or row[1] < time.time():
            return None
        return json.loads(row[0])

    def set(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires) VALUES (?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), time.time() + ttl),
            )
            self._db.commit()

    def purge_expired(self) -> int:
        with self._lock:
            n = self._db.execute("DELETE FROM cache WHERE expires < ?", (time.time(),)).rowcount
            self._db.commit()
        return n
