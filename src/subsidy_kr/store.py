"""SQLite 저장소 — API 스냅샷(7일 TTL)·익명 일별 카운터·동기화 상태.

개인정보는 여기에 들어오지 않습니다. 프로필·질의문·IP·쿠키를 저장하는 열 자체를
만들지 않았고, 판정은 요청 처리 중에만 메모리에서 계산됩니다.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

KST = timezone(timedelta(hours=9))
DEFAULT_TTL_HOURS = 24 * 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT NOT NULL,
    query_key    TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'ok'
);
CREATE INDEX IF NOT EXISTS idx_snapshots_lookup
    ON snapshots(source_id, query_key, fetched_at DESC);

CREATE TABLE IF NOT EXISTS usage_daily (
    day        TEXT NOT NULL,
    kind       TEXT NOT NULL,
    key        TEXT NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (day, kind, key)
);

CREATE TABLE IF NOT EXISTS sync_state (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def now_kst() -> datetime:
    return datetime.now(KST)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def age_hours(stamp: Optional[str]) -> float:
    try:
        then = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return 1e9
    if then.tzinfo is None:
        then = then.replace(tzinfo=KST)
    return max(0.0, (now_kst() - then).total_seconds() / 3600.0)


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        if path != ":memory:":
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA busy_timeout=5000")
            except sqlite3.Error:
                pass
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # --- 스냅샷 -------------------------------------------------------------
    def put_snapshot(self, source_id: str, query_key: str, payload: Dict[str, Any],
                     status: str = "ok") -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO snapshots(source_id, query_key, payload_json, fetched_at, status) "
                "VALUES (?,?,?,?,?)",
                (source_id, query_key, json.dumps(payload, ensure_ascii=False),
                 iso(now_kst()), status),
            )
            self.conn.commit()

    def latest_snapshot(self, source_id: str, query_key: str) -> Optional[sqlite3.Row]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM snapshots WHERE source_id=? AND query_key=? AND status='ok' "
                "ORDER BY fetched_at DESC LIMIT 1",
                (source_id, query_key),
            )
            return cur.fetchone()

    def get_cached_snapshot(self, source_id: str, query_key: str,
                            ttl_hours: float = DEFAULT_TTL_HOURS) -> Optional[Tuple[Dict[str, Any], float]]:
        row = self.latest_snapshot(source_id, query_key)
        if row is None:
            return None
        hours = age_hours(row["fetched_at"])
        if ttl_hours >= 0 and hours > ttl_hours:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload, hours

    # --- 익명 카운터 ---------------------------------------------------------
    def bump_usage(self, day: str, kind: str, key: str, amount: int = 1) -> None:
        stamp = iso(now_kst())
        with self._lock:
            self.conn.execute(
                "INSERT INTO usage_daily(day, kind, key, count, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(day, kind, key) DO UPDATE SET count = count + ?, updated_at = ?",
                (day, kind, key, int(amount), stamp, int(amount), stamp),
            )
            self.conn.commit()

    def usage_rows(self, start_day: str, end_day: str) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT day, kind, key, count FROM usage_daily WHERE day BETWEEN ? AND ? "
                "ORDER BY day, kind, key",
                (start_day, end_day),
            )
            return [dict(row) for row in cur.fetchall()]

    def usage_total(self) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(count), 0) AS c FROM usage_daily"
            ).fetchone()
        return int(row["c"])

    # --- 동기화 상태 ---------------------------------------------------------
    def set_state(self, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO sync_state(key, value_json, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=?, updated_at=?",
                (key, json.dumps(value, ensure_ascii=False), iso(now_kst()),
                 json.dumps(value, ensure_ascii=False), iso(now_kst())),
            )
            self.conn.commit()

    def get_state(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self.conn.execute(
                "SELECT value_json FROM sync_state WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row["value_json"])
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None
