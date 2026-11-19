"""동기화 파이프라인 테스트 — 가짜 클라이언트로 네트워크 없이."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import catalog as catalog_module  # noqa: E402
from subsidy_kr import sync_gov24  # noqa: E402

SERVICES = [
    {"서비스ID": "R-1", "서비스명": "청년 월세 지원", "소관기관명": "국토교통부",
     "소관기관유형": "중앙행정기관", "지원대상": "만 19~34세 청년", "선정기준": "소득 기준 충족",
     "지원내용": "월 20만 원", "신청기한": "2026. 1. 1. ~ 2026. 12. 31.", "전화문의": "1600-0000",
     "상세조회URL": "https://www.gov.kr/x", "수정일시": "2026-11-01"},
    {"서비스ID": "R-2", "서비스명": "지역 청년 수당", "소관기관명": "인천광역시 서구",
     "소관기관유형": "지방자치단체", "지원대상": "청년", "선정기준": "",
     "지원내용": "50만 원", "신청기한": "상시신청", "수정일시": "2026-10-01"},
    {"서비스ID": "R-3", "서비스명": "지역 농업인 지원", "소관기관명": "전라남도",
     "소관기관유형": "지방자치단체", "지원대상": "농업인", "선정기준": "거주 요건",
     "지원내용": "보조금", "신청기한": "별도 공고", "수정일시": "2026-09-01"},
]

CONDITIONS = [
    {"서비스ID": "R-1", "서비스명": "청년 월세 지원", "JA0110": 19.0, "JA0111": 34.0,
     "JA0203": "Y", "JA0412": "Y"},
    {"서비스ID": "R-2", "서비스명": "지역 청년 수당", "JA0110": 19.0, "JA0111": 39.0},
]


class FakeClient:
    calls = {"list": 0, "conditions": 0}

    def __init__(self, key):
        self.key = key

    @staticmethod
    def _rows(payload):
        return list(payload.get("data") or [])

    def service_list(self, page=1, per_page=1000, conds=None):
        FakeClient.calls["list"] += 1
        start = (page - 1) * per_page
        return {"data": SERVICES[start:start + per_page], "totalCount": len(SERVICES),
                "currentCount": len(SERVICES), "page": page, "perPage": per_page}

    def iter_conditions(self, per_page=1000, max_pages=None):
        FakeClient.calls["conditions"] += 1
        for row in CONDITIONS:
            yield row

    def support_conditions(self, service_id):
        FakeClient.calls["conditions"] += 1
        return next((row for row in CONDITIONS if row["서비스ID"] == service_id), None)


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._original = sync_gov24.Gov24Client
        sync_gov24.Gov24Client = FakeClient
        FakeClient.calls = {"list": 0, "conditions": 0}

    def tearDown(self):
        sync_gov24.Gov24Client = self._original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_sync_writes_catalog(self):
        report = sync_gov24.sync("TESTKEY", data_dir=self.tmp, force=True, per_page=2)
        self.assertTrue(report["ok"])
        self.assertEqual(report["stats"]["services"], 3)
        self.assertEqual(report["stats"]["with_conditions"], 2)
        self.assertEqual(report["stats"]["local_services"], 2)
        self.assertEqual(report["stats"]["local_missing_criteria"], 1)
        target = os.path.join(self.tmp, "catalog.json")
        self.assertTrue(os.path.exists(target))
        self.assertIn(target, report["saved_files"])
        self.assertEqual(FakeClient.calls["list"], 2)   # per_page=2 → 2페이지

        catalog = catalog_module.load_catalog(target)
        self.assertEqual(catalog.meta["catalog_state"], "synced")
        self.assertEqual(len(catalog.services), 3)
        service = catalog.get("R-1")
        self.assertEqual(service.age["min_age"], 19)
        self.assertTrue(service.has_criteria)
        self.assertFalse(catalog.get("R-2").has_criteria)
        self.assertEqual(catalog.get("R-2").region["sigungu"], "서해구")
        self.assertEqual(service.conditions["JA0412"], "Y")

    def test_second_run_uses_cache_without_calls(self):
        sync_gov24.sync("TESTKEY", data_dir=self.tmp, force=True)
        list_calls = FakeClient.calls["list"]
        report = sync_gov24.sync("TESTKEY", data_dir=self.tmp)
        self.assertTrue(report["ok"])
        self.assertEqual(report["state"], "cache")
        self.assertEqual(FakeClient.calls["list"], list_calls)

    def test_from_cache_after_ttl(self):
        sync_gov24.sync("TESTKEY", data_dir=self.tmp, force=True, ttl_hours=0)
        report = sync_gov24.sync(None, data_dir=self.tmp, from_cache=True, ttl_hours=0)
        self.assertTrue(report["ok"])
        self.assertEqual(report["state"], "stale_cache")
        self.assertTrue(report["warnings"])

    def test_missing_key_and_no_cache(self):
        report = sync_gov24.sync(None, data_dir=self.tmp)
        self.assertFalse(report["ok"])
        self.assertEqual(report["error"], "service_key_missing")
        self.assertIn("15113968", report["message"])

    def test_dry_run_does_not_write(self):
        report = sync_gov24.sync("TESTKEY", data_dir=self.tmp, force=True, dry_run=True)
        self.assertTrue(report["ok"])
        self.assertEqual(report["saved_files"], [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "catalog.json")))

    def test_per_id_mode(self):
        report = sync_gov24.sync("TESTKEY", data_dir=self.tmp, force=True,
                                 conditions_mode="per-id", ids=["R-1"])
        self.assertTrue(report["ok"])
        catalog = catalog_module.load_catalog(os.path.join(self.tmp, "catalog.json"))
        self.assertTrue(catalog.get("R-1").conditions)
        self.assertFalse(catalog.get("R-2").conditions)

    def test_no_conditions_flag(self):
        report = sync_gov24.sync("TESTKEY", data_dir=self.tmp, force=True, with_conditions=False)
        self.assertTrue(report["ok"])
        self.assertEqual(report["stats"]["with_conditions"], 0)

    def test_max_services_limit(self):
        report = sync_gov24.sync("TESTKEY", data_dir=self.tmp, force=True, max_services=1,
                                 per_page=1000)
        self.assertTrue(report["ok"])
        self.assertEqual(report["stats"]["services"], 1)


class MergeTest(unittest.TestCase):
    def test_conditions_merged_by_service_id(self):
        merged = sync_gov24.merge_records(SERVICES, CONDITIONS)
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[0]["conditions"]["JA0203"], "Y")
        self.assertEqual(merged[1]["conditions"], {"JA0110": 19.0, "JA0111": 39.0})
        self.assertEqual(merged[2]["conditions"], {})

    def test_rows_without_id_are_skipped(self):
        merged = sync_gov24.merge_records([{"서비스명": "아이디 없음"}], [])
        self.assertEqual(merged, [])

    def test_unknown_codes_are_dropped(self):
        merged = sync_gov24.merge_records(
            [{"서비스ID": "X"}],
            [{"서비스ID": "X", "JA9999": "Y", "JA0302": "Y"}])
        self.assertEqual(merged[0]["conditions"], {"JA0302": "Y"})


class CliTest(unittest.TestCase):
    def test_main_returns_error_without_key(self):
        original = sync_gov24.Gov24Client
        sync_gov24.Gov24Client = FakeClient
        tmp = tempfile.mkdtemp()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = sync_gov24.main(["--data-dir", tmp, "--no-conditions"])
            self.assertEqual(code, 1)   # 키가 없으면 실패 코드
            with contextlib.redirect_stdout(io.StringIO()):
                code = sync_gov24.main(["--key", "TESTKEY", "--data-dir", tmp, "--json",
                                        "--max-services", "1"])
            self.assertEqual(code, 0)
            report = json.loads(open(os.path.join(tmp, "catalog.json"), encoding="utf-8").read())
            self.assertIn("meta", report)
        finally:
            sync_gov24.Gov24Client = original
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
