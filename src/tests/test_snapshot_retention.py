"""스냅샷 7일 보존 회귀 테스트 (v0.4.10).

무엇을 고정하나
- 일자별 스냅샷을 **최신 1장만** 남기면 `compare_ledgers` 는 매일 `baseline_only` 로만
  답한다. 그래서 보관 기간(기본 7일)을 두고, 그 안에서는 전일·며칠 전 비교가 된다.
- 보관 기간을 넘긴 날짜는 파일과 색인(`index.json`) 행을 함께 지운다 — 파일만 지우면
  색인이 유령 날짜를 계속 들고 있어 `compare_days` 가 읽을 수 없는 날짜를 기준일로 고른다.
- 기동 시 기준일 적재(`snapshots.ensure_baseline`)는 그날 스냅샷이 이미 있으면 다시 쓰지
  않는다(오늘 관측분을 기동 시점 카탈로그로 덮어쓰지 않는다).
- 재수집으로 소스별 건수가 크게 줄면 카탈로그 meta 에 경고를 남긴다(2026-11-22 지자체
  포털 페이지 상한 절단 사례).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import refresh_catalog, snapshots  # noqa: E402
from subsidy_kr.catalog import normalize_service  # noqa: E402


def _service(service_id: str, name: str, source: str = "gov24"):
    return normalize_service({
        "서비스ID": service_id,
        "서비스명": name,
        "소관기관명": "테스트기관",
        "지원대상": "전국 만 19세 이상",
        "지원내용": "테스트 지원금",
        "신청기한": "2026-12-01 ~ 2027-12-31",
        "source": source,
    }, source=source)


def _local_rows(count: int, prefix: str = "BROSO-SEOUL"):
    return [{
        "서비스ID": f"{prefix}-P{index:05d}-1",
        "서비스명": f"지자체 제도 {index}",
        "소관기관명": "테스트구청",
        "지원대상": "지역 주민",
        "지원내용": "지역 지원",
        "신청기한": "상시 (기관별 모집시기 확인)",
        "source": "local_portal",
    } for index in range(count)]


def _write_catalog(root: str, rows, meta=None) -> None:
    payload = {"meta": dict(meta or {}, catalog_state="synced"), "services": rows}
    with open(os.path.join(root, "catalog.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="grnt-retain-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.dir = snapshots.snapshot_dir(self.root)
        self.services = [_service("T-1", "제도 하나")]

    def test_keeps_last_seven_days_and_prunes_files_and_index(self):
        days = [f"2026-11-{day:02d}" for day in range(1, 11)]  # 10일
        for day in days:
            snapshots.write_snapshot(self.services, day, self.dir, compress=True)
        self.assertEqual(len(snapshots.days_on_disk(self.dir)), 10)

        result = snapshots.prune_snapshots(self.dir, keep_days=7)

        self.assertEqual(result["keep_days"], 7)
        self.assertEqual(result["removed_days"], days[:3])
        self.assertEqual(snapshots.days_on_disk(self.dir), days[3:])
        for day in days[:3]:  # 파일이 실제로 지워졌다
            self.assertFalse(os.path.exists(os.path.join(self.dir, f"{day}.json.gz")))
        with open(os.path.join(self.dir, snapshots.INDEX_FILE), encoding="utf-8") as handle:
            index = json.load(handle)
        indexed = [row["day"] for row in index["days"]]
        self.assertEqual(indexed, days[3:])
        self.assertEqual(result["index_removed"], days[:3])

    def test_protected_day_survives_even_when_it_is_old(self):
        for day in ("2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"):
            snapshots.write_snapshot(self.services, day, self.dir, compress=True)
        snapshots.prune_snapshots(self.dir, keep_days=2, protect="2026-11-01")
        self.assertIn("2026-11-01", snapshots.days_on_disk(self.dir))
        self.assertNotIn("2026-11-02", snapshots.days_on_disk(self.dir))

    def test_prune_is_idempotent(self):
        for day in ("2026-11-01", "2026-11-02", "2026-11-03"):
            snapshots.write_snapshot(self.services, day, self.dir, compress=True)
        first = snapshots.prune_snapshots(self.dir, keep_days=1)
        self.assertEqual(first["removed_days"], ["2026-11-01", "2026-11-02"])
        second = snapshots.prune_snapshots(self.dir, keep_days=1)
        self.assertEqual(second["removed_days"], [])
        self.assertEqual(snapshots.days_on_disk(self.dir), ["2026-11-03"])


class GhostIndexTest(unittest.TestCase):
    """색인에만 남은 날짜가 기준일로 뽑히지 않게 한다."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="grnt-ghost-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.dir = snapshots.snapshot_dir(self.root)
        self.services = [_service("T-1", "제도 하나"), _service("T-2", "제도 둘")]

    def test_index_row_without_file_is_ignored(self):
        snapshots.write_snapshot(self.services, "2026-11-20", self.dir, compress=True)
        with open(os.path.join(self.dir, snapshots.INDEX_FILE), encoding="utf-8") as handle:
            index = json.load(handle)
        index["days"].insert(0, {"day": "2026-11-19", "services": 2})
        with open(os.path.join(self.dir, snapshots.INDEX_FILE), "w", encoding="utf-8") as handle:
            json.dump(index, handle, ensure_ascii=False)

        self.assertEqual([row["day"] for row in snapshots.list_snapshots(self.dir)],
                         ["2026-11-20"])
        diff = snapshots.compare_days(None, None, self.dir)
        self.assertEqual(diff["state"], "baseline_only")
        self.assertEqual(diff["available_days"], ["2026-11-20"])

    def test_seven_day_window_can_compare_two_days(self):
        days = [f"2026-11-{day:02d}" for day in range(10, 18)]
        for day in days:
            snapshots.write_snapshot(self.services, day, self.dir, compress=True)
        snapshots.prune_snapshots(self.dir, keep_days=7)
        changed = [_service("T-1", "제도 하나"), _service("T-3", "새 제도")]
        snapshots.write_snapshot(changed, "2026-11-18", self.dir, compress=True)
        snapshots.prune_snapshots(self.dir, keep_days=7)

        diff = snapshots.compare_days(None, None, self.dir)
        self.assertTrue(diff["ok"], diff)
        self.assertNotIn("state", diff)  # baseline_only 가 아니다
        self.assertEqual(diff["from_day"], "2026-11-17")
        self.assertEqual(diff["to_day"], "2026-11-18")
        self.assertEqual(diff["counts"], {"added": 1, "removed": 1, "changed": 0})


class EnsureBaselineTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="grnt-baseline-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.dir = snapshots.snapshot_dir(self.root)
        self.today = snapshots.today_kst()  # KST 기준 — CI(UTC)에서도 같은 날짜를 본다

    def test_ensure_baseline_does_not_overwrite_today_snapshot(self):
        """갱신이 남긴 오늘 스냅샷을 기동 시 적재가 다시 쓰지 않는다."""
        written = snapshots.write_snapshot(
            [_service("T-1", "관측된 제도")], self.today, self.dir, compress=True,
            note_ko="갱신 시 적재")
        before_stat = os.stat(written)
        with open(written, "rb") as handle:
            before_bytes = handle.read()

        path = snapshots.ensure_baseline(
            [_service("T-9", "다른 제도")], self.dir, day=self.today, compress=True)

        self.assertIsNone(path)
        self.assertEqual(os.stat(written).st_mtime, before_stat.st_mtime)
        with open(written, "rb") as handle:
            self.assertEqual(handle.read(), before_bytes)
        loaded = snapshots.load_snapshot(self.today, self.dir)
        self.assertEqual(list(loaded["services"]), ["T-1"])


class RefreshRetentionTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="grnt-refresh-retain-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.dir = snapshots.snapshot_dir(self.root)
        self.today = datetime.strptime(snapshots.today_kst(), "%Y-%m-%d").date()

    def _old_day(self, offset: int) -> str:
        return (self.today - timedelta(days=offset)).isoformat()

    def test_refresh_prunes_old_snapshots_but_keeps_today(self):
        services = [_service("T-1", "제도 하나")]
        for offset in range(1, 10):  # 오늘 이전 9일
            snapshots.write_snapshot(services, self._old_day(offset), self.dir, compress=True)
        _write_catalog(self.root, [{
            "서비스ID": "T-1", "서비스명": "제도 하나", "소관기관명": "테스트기관",
            "지원대상": "전국", "지원내용": "지원", "신청기한": "2026-12-01 ~ 2027-12-31",
        }])

        report = refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)

        self.assertTrue(report["ok"], report)
        kept = snapshots.days_on_disk(self.dir)
        self.assertEqual(len(kept), 7)
        self.assertIn(self.today.isoformat(), kept)
        self.assertEqual(report["snapshot"]["keep_days"], 7)
        self.assertEqual(report["snapshot"]["available_days"], 7)
        self.assertEqual(len(report["snapshot"]["pruned_days"]), 3)

    def test_refresh_warns_when_a_source_shrinks_sharply(self):
        _write_catalog(self.root, _local_rows(40))
        smaller = _local_rows(10)

        def fake_sync(*_args, **_kwargs):
            _write_catalog(self.root, smaller)
            return {"ok": True, "state": "network"}

        with mock.patch.object(refresh_catalog.sync_gov24, "sync_all", fake_sync):
            report = refresh_catalog.refresh(data_dir=self.root, service_key="test-key",
                                             log=lambda _m: None)

        self.assertTrue(report["ok"], report)
        warnings = "\n".join(report["warnings"])
        self.assertIn("지자체 포털", warnings)
        self.assertIn("40건 → 10건", warnings)
        # 경고는 압축본 meta 에도 실려 다음 실행·워크플로 요약에서 보인다.
        payload = json.loads(__import__("gzip").open(
            os.path.join(self.root, "catalog.json.gz"), "rt", encoding="utf-8").read())
        self.assertTrue(any("지자체 포털" in item
                            for item in payload["meta"].get("warnings") or []))

    def test_shrink_warning_ignores_small_drops(self):
        before = {"by_source": {"local_portal": 100}}
        after = {"by_source": {"local_portal": 97}}
        self.assertEqual(refresh_catalog._shrink_warnings(before, after), [])
        grown = {"by_source": {"local_portal": 130}}
        self.assertEqual(refresh_catalog._shrink_warnings(before, grown), [])

    def test_expiry_only_drop_is_not_warned(self):
        """수집 건수는 같은데 마감 제외만 늘었으면 정상 만료다(K-Startup 2026-11-22 사례)."""
        before = {"by_source": {"kstartup": 207}}
        after = {"by_source": {"kstartup": 180}}
        before_meta = {"sources": {"startup": {"fetched": 30629, "kept": 207,
                                               "dropped_expired": 30422}}}
        after_meta = {"sources": {"startup": {"fetched": 30629, "kept": 180,
                                              "dropped_expired": 30449}}}
        self.assertEqual(refresh_catalog._shrink_warnings(before, after, before_meta,
                                                          after_meta), [])

    def test_source_returning_fewer_records_is_warned(self):
        before = {"by_source": {"bizinfo": 1335}}
        after = {"by_source": {"bizinfo": 1180}}
        before_meta = {"sources": {"bizinfo": {"fetched": 1335, "kept": 1335,
                                                "dropped_expired": 0}}}
        after_meta = {"sources": {"bizinfo": {"fetched": 1180, "kept": 1180,
                                               "dropped_expired": 0}}}
        warnings = refresh_catalog._shrink_warnings(before, after, before_meta, after_meta)
        self.assertEqual(len(warnings), 1)
        self.assertIn("기업마당", warnings[0])


class KoreanDateTest(unittest.TestCase):
    """스냅샷 날짜는 KST 기준 — CI(UTC)에서 04:00 KST 갱신이 전날 파일로 남지 않게."""

    def test_today_kst_uses_korean_time(self):
        from datetime import datetime, timezone
        # UTC 2026-11-21 16:30 = KST 2026-11-22 01:30 — UTC 날짜를 쓰면 하루 전날이 된다.
        real = datetime(2026, 11, 21, 16, 30, tzinfo=timezone.utc)
        with mock.patch.object(snapshots, "datetime") as fake:
            fake.now.side_effect = lambda tz=None: real.astimezone(tz)
            self.assertEqual(snapshots.today_kst(), "2026-11-22")


class WorkflowRetentionTest(unittest.TestCase):
    """워크플로가 다시 '최신 1장만' 으로 되돌아가지 않게 고정한다."""

    def test_workflow_keeps_seven_days(self):
        path = os.path.join(ROOT, ".github", "workflows", "refresh-catalog.yml")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("head -n -7", text)
        self.assertNotIn("tail -1", text)
        self.assertIn("git add -A -f data/gov24/snapshots", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
