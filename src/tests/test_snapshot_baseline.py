"""기준일 스냅샷 회귀 테스트 — `compare_ledgers` 가 프로덕션에서 비지 않게 한 보강(0.4.6).

확인하는 것
- 무압축(`.json`)과 압축(`.json.gz`) 스냅샷을 같은 날짜로 읽고 쓴다(저장소·이미지에 넣는 기준일용).
- 색인(`index.json`)에 없어도 디스크에 있는 압축 스냅샷을 날짜 목록에 넣는다.
- 기준일이 1장뿐이면 `snapshot_missing` 이 아니라 `state: "baseline_only"` 로 답한다.
- 기동 시 기준일이 없으면 지금 카탈로그로 1장 적재하고, 있으면 다시 쓰지 않는다.
- 카탈로그 갱신(`refresh_catalog`)이 그날 스냅샷을 남긴다.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import api, refresh_catalog, snapshots  # noqa: E402
from subsidy_kr.catalog import Catalog, normalize_service  # noqa: E402


def _service(service_id: str, name: str, deadline: str = "2026-12-31 ~ 2027-01-31"):
    return normalize_service({
        "서비스ID": service_id,
        "서비스명": name,
        "소관기관명": "테스트기관",
        "지원대상": "전국 만 19세 이상",
        "지원내용": "테스트 지원금",
        "신청기한": deadline,
    }, source="gov24")


class SnapshotBaselineTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="grnt-snap-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.dir = snapshots.snapshot_dir(self.root)
        self.services = [_service("T-1", "제도 하나"), _service("T-2", "제도 둘")]

    # --- 읽기·쓰기 ---------------------------------------------------------
    def test_gzip_snapshot_roundtrip(self):
        path = snapshots.write_snapshot(self.services, "2026-11-20", self.dir, compress=True)
        self.assertTrue(path.endswith(".json.gz"), path)
        self.assertLess(os.path.getsize(path), 4096)
        payload = snapshots.load_snapshot("2026-11-20", self.dir)
        self.assertIsNotNone(payload)
        self.assertEqual(set(payload["services"]), {"T-1", "T-2"})
        self.assertEqual(snapshots.latest_day(self.dir), "2026-11-20")

    def test_compressed_and_plain_same_day_do_not_duplicate(self):
        snapshots.write_snapshot(self.services, "2026-11-20", self.dir, compress=False)
        snapshots.write_snapshot(self.services, "2026-11-20", self.dir, compress=True)
        names = sorted(os.listdir(self.dir))
        self.assertIn("2026-11-20.json.gz", names)
        self.assertNotIn("2026-11-20.json", names)
        self.assertEqual(len(snapshots.list_snapshots(self.dir)), 1)

    def test_disk_only_snapshot_is_listed_without_index(self):
        snapshots.write_snapshot(self.services, "2026-11-19", self.dir, compress=True)
        os.remove(os.path.join(self.dir, snapshots.INDEX_FILE))
        rows = snapshots.list_snapshots(self.dir)
        self.assertEqual([row["day"] for row in rows], ["2026-11-19"])
        self.assertEqual(rows[0]["services"], 2)

    # --- 비교 -------------------------------------------------------------
    def test_single_day_reports_baseline_only(self):
        snapshots.write_snapshot(self.services, "2026-11-19", self.dir)
        diff = snapshots.compare_days(None, None, self.dir)
        self.assertTrue(diff["ok"])
        self.assertEqual(diff["state"], "baseline_only")
        self.assertEqual(diff["to_day"], "2026-11-19")
        self.assertEqual(diff["counts"], {"added": 0, "removed": 0, "changed": 0})
        self.assertIn("1장", diff["message_ko"])

    def test_no_snapshot_keeps_missing_error(self):
        diff = snapshots.compare_days(None, None, self.dir)
        self.assertFalse(diff["ok"])
        self.assertEqual(diff["error"], "snapshot_missing")

    def test_two_days_compare_changes(self):
        snapshots.write_snapshot(self.services, "2026-11-19", self.dir)
        changed = [_service("T-1", "제도 하나"), _service("T-3", "새 제도")]
        snapshots.write_snapshot(changed, "2026-11-20", self.dir)
        diff = snapshots.compare_days(None, None, self.dir)
        self.assertTrue(diff["ok"])
        self.assertNotIn("state", diff)
        self.assertEqual(diff["counts"], {"added": 1, "removed": 1, "changed": 0})

    def test_tool_envelope_for_baseline_only(self):
        snapshots.write_snapshot(self.services, "2026-11-19", self.dir)
        catalog = Catalog(self.services, {})
        # 이 툴은 `SUBSIDY_KR_DATA` 아래 snapshots/ 를 읽는다 — 작업 트리의 기준일 스냅샷
        # 수에 기대지 않도록 검사용 디렉터리를 명시한다.
        with mock.patch.dict(os.environ, {"SUBSIDY_KR_DATA": self.root}):
            out = api.call_tool("compare_ledgers", {}, catalog)
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["state"], "baseline_only")
        self.assertIn("기준일", out["result"]["summary_ko"])
        self.assertIn("기준일", api.text_summary(out))

    # --- 기동 시 적재 -----------------------------------------------------
    def test_ensure_baseline_writes_once(self):
        first = snapshots.ensure_baseline(self.services, self.dir, day="2026-11-21")
        self.assertTrue(first)
        before = os.path.getmtime(first)
        second = snapshots.ensure_baseline(self.services, self.dir, day="2026-11-21")
        self.assertIsNone(second)
        self.assertEqual(os.path.getmtime(first), before)

    def test_ensure_baseline_skips_empty_catalog(self):
        self.assertIsNone(snapshots.ensure_baseline([], self.dir, day="2026-11-21"))
        self.assertEqual(snapshots.days_on_disk(self.dir), [])

    # --- 카탈로그 갱신 ----------------------------------------------------
    def test_refresh_writes_snapshot(self):
        payload = {"meta": {"dataset_id": "TEST", "catalog_state": "synced"},
                   "services": [{"서비스ID": "T-1", "서비스명": "제도 하나",
                                 "소관기관명": "테스트기관", "신청기한":
                                     f"{date.today()} ~ {date.today().replace(year=date.today().year + 1)}"}]}
        with open(os.path.join(self.root, "catalog.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        report = refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)
        self.assertTrue(report["ok"], report)
        snapshot = report["snapshot"]
        self.assertTrue(snapshot["path"].endswith(".json.gz"), snapshot)
        self.assertEqual(snapshot["available_days"], 1)
        self.assertIn(snapshot["path"], report["files"])
        day = snapshots.today_kst()
        loaded = snapshots.load_snapshot(day, self.dir)
        self.assertIsNotNone(loaded)
        self.assertEqual(list(loaded["services"]), ["T-1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
