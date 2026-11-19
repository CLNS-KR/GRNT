"""SQLite 저장소 테스트 — 스냅샷 TTL·익명 카운터·동기화 상태."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr.store import KST, Store, age_hours  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_snapshot_roundtrip_and_ttl(self):
        self.store.put_snapshot("gov24", "key", {"rows": 3})
        hit = self.store.get_cached_snapshot("gov24", "key", ttl_hours=24 * 7)
        self.assertIsNotNone(hit)
        payload, hours = hit
        self.assertEqual(payload["rows"], 3)
        self.assertLess(hours, 1)
        # TTL 0 은 즉시 만료로 본다
        self.assertIsNone(self.store.get_cached_snapshot("gov24", "key", ttl_hours=0))
        # 음수 TTL 은 '만료 없음'(오래된 스냅샷을 상태와 함께 쓰는 용도)
        self.assertIsNotNone(self.store.get_cached_snapshot("gov24", "key", ttl_hours=-1))

    def test_error_snapshots_are_not_used_as_cache(self):
        self.store.put_snapshot("gov24", "key", {"error": "boom"}, status="error")
        self.assertIsNone(self.store.get_cached_snapshot("gov24", "key"))

    def test_usage_counter_increments(self):
        self.store.bump_usage("2026-11-19", "tool", "search_subsidies")
        self.store.bump_usage("2026-11-19", "tool", "search_subsidies")
        self.store.bump_usage("2026-11-19", "path", "/")
        rows = self.store.usage_rows("2026-11-19", "2026-11-19")
        counts = {(row["kind"], row["key"]): row["count"] for row in rows}
        self.assertEqual(counts[("tool", "search_subsidies")], 2)
        self.assertEqual(counts[("path", "/")], 1)
        self.assertEqual(self.store.usage_total(), 3)

    def test_usage_window_excludes_other_days(self):
        self.store.bump_usage("2026-11-18", "tool", "get_service_meta")
        self.store.bump_usage("2026-11-19", "tool", "get_service_meta")
        rows = self.store.usage_rows("2026-11-19", "2026-11-19")
        self.assertEqual(len(rows), 1)

    def test_sync_state_roundtrip(self):
        self.store.set_state("last_sync", {"services": 10, "ok": True})
        self.assertEqual(self.store.get_state("last_sync")["services"], 10)
        self.store.set_state("last_sync", {"services": 11})
        self.assertEqual(self.store.get_state("last_sync")["services"], 11)
        self.assertIsNone(self.store.get_state("missing"))

    def test_age_hours_handles_bad_input(self):
        self.assertGreater(age_hours("not-a-date"), 1e8)
        recent = (datetime.now(KST) - timedelta(hours=2)).isoformat(timespec="seconds")
        self.assertAlmostEqual(age_hours(recent), 2.0, delta=0.2)

    def test_file_backed_store_persists(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "app.sqlite")
        try:
            first = Store(path)
            first.bump_usage("2026-11-19", "verdict", "eligible_likely")
            first.close()
            second = Store(path)
            self.assertEqual(second.usage_total(), 1)
            second.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
