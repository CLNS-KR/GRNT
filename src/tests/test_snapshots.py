"""일자별 스냅샷·변경 비교 테스트."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import snapshots  # noqa: E402
from subsidy_kr.catalog import normalize_service  # noqa: E402


def service(**overrides):
    raw = {
        "서비스ID": "SMP-0001",
        "서비스명": "청년월세 한시 특별지원",
        "소관기관명": "국토교통부",
        "지원대상": "만 19~34세 청년",
        "지원내용": "월 20만 원",
        "신청기한": "2026. 1. 2. ~ 2026. 12. 31.",
        "track": "personal",
        "source": "gov24",
    }
    raw.update(overrides)
    return normalize_service(raw, source=raw.get("source", "gov24"))


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.services = [service(),
                         service(서비스ID="KSU-1", 서비스명="예비창업패키지",
                                 소관기관명="중소벤처기업부", track="business",
                                 source="kstartup", 지원내용="사업화 자금",
                                 business={"entity": ["pre_startup"], "status": "pre",
                                           "recruiting": "open"})]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_and_save(self):
        payload = snapshots.build_snapshot(self.services, "2026-11-18")
        self.assertEqual(payload["meta"]["services"], 2)
        self.assertEqual(payload["meta"]["by_track"]["business"], 1)
        path = snapshots.save_snapshot(payload, self.tmp)
        self.assertTrue(os.path.exists(path))
        loaded = snapshots.load_snapshot("2026-11-18", self.tmp)
        self.assertEqual(loaded["services"]["SMP-0001"]["name"], "청년월세 한시 특별지원")
        self.assertIn("fingerprint", loaded["services"]["SMP-0001"])

    def test_index_tracks_days(self):
        for day in ("2026-11-17", "2026-11-18"):
            snapshots.save_snapshot(snapshots.build_snapshot(self.services, day), self.tmp)
        days = snapshots.list_snapshots(self.tmp)
        self.assertEqual([row["day"] for row in days], ["2026-11-17", "2026-11-18"])
        self.assertEqual(snapshots.latest_day(self.tmp), "2026-11-18")

    def test_diff_added_removed_changed(self):
        before = snapshots.build_snapshot(self.services, "2026-11-17")
        changed_services = [
            service(지원내용="월 25만 원"),           # 금액 변경
            service(서비스ID="SMP-0009", 서비스명="새 제도"),  # 추가
        ]
        after = snapshots.build_snapshot(changed_services, "2026-11-18")
        diff = snapshots.diff_snapshots(before, after)
        self.assertEqual([row["service_id"] for row in diff["added"]], ["SMP-0009"])
        self.assertEqual([row["service_id"] for row in diff["removed"]], ["KSU-1"])
        self.assertEqual([row["service_id"] for row in diff["changed"]], ["SMP-0001"])
        fields = diff["changed"][0]["changes"]
        self.assertIn("amount", fields)
        self.assertEqual(fields["amount"]["from"], "월 20만 원")
        self.assertEqual(fields["amount"]["to"], "월 25만 원")

    def test_diff_uses_fingerprint(self):
        before = snapshots.build_snapshot(self.services, "2026-11-17")
        after = snapshots.build_snapshot(self.services, "2026-11-18")
        diff = snapshots.diff_snapshots(before, after)
        self.assertEqual(diff["counts"], {"added": 0, "removed": 0, "changed": 0})

    def test_compare_days_needs_two(self):
        snapshots.save_snapshot(snapshots.build_snapshot(self.services, "2026-11-18"), self.tmp)
        result = snapshots.compare_days(None, None, self.tmp)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "snapshot_missing")
        self.assertIn("스냅샷", result["message_ko"])

    def test_compare_days_and_history(self):
        snapshots.save_snapshot(snapshots.build_snapshot(self.services, "2026-11-17"), self.tmp)
        snapshots.save_snapshot(snapshots.build_snapshot(
            [service(지원내용="월 25만 원")], "2026-11-18"), self.tmp)
        result = snapshots.compare_days(None, None, self.tmp)
        self.assertTrue(result["ok"])
        self.assertEqual(result["from_day"], "2026-11-17")
        self.assertEqual(result["to_day"], "2026-11-18")
        self.assertEqual(result["counts"]["changed"], 1)
        self.assertEqual(result["services"], {"from": 2, "to": 1})

        only = snapshots.compare_days(None, None, self.tmp, service_id="SMP-0001")
        self.assertEqual(only["counts"]["changed"], 1)

        rows = snapshots.history("SMP-0001", self.tmp)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["amount"], "월 25만 원")

    def test_same_day_overwrites_index_entry(self):
        for _ in range(2):
            snapshots.save_snapshot(snapshots.build_snapshot(self.services, "2026-11-18"), self.tmp)
        days = snapshots.list_snapshots(self.tmp)
        self.assertEqual(len([row for row in days if row["day"] == "2026-11-18"]), 1)

    def test_snapshot_has_no_profile_fields(self):
        payload = snapshots.build_snapshot(self.services, "2026-11-18")
        text = str(payload)
        for word in ("age", "income", "pregnant", "resident"):
            self.assertNotIn(f'"{word}"', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
