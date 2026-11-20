"""통합 동기화(sync_all) 테스트 — 가짜 클라이언트로 네트워크 없이."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import sync_gov24  # noqa: E402
from subsidy_kr.catalog import load_catalog  # noqa: E402

GOV24_SERVICES = [
    {"서비스ID": "R-1", "서비스명": "청년 월세 지원", "소관기관명": "국토교통부",
     "지원대상": "만 19~34세 청년", "선정기준": "소득 기준 충족", "지원내용": "월 20만 원",
     "신청기한": "2026. 1. 1. ~ 2026. 12. 31.", "수정일시": "2026-11-01"},
]
GOV24_CONDITIONS = [
    {"서비스ID": "R-1", "JA0110": 19.0, "JA0111": 34.0, "JA0203": "Y"},
]

KSTARTUP_ROWS = [
    {"pbanc_sn": "1", "biz_pbanc_nm": "예비창업패키지", "pbanc_ntrp_nm": "중소벤처기업부",
     "supt_biz_clsfc": "사업화", "aply_trgt_ctnt": "예비창업자", "supt_regin": "전국",
     "pbanc_rcpt_bgng_dt": "20261101", "pbanc_rcpt_end_dt": "20261201",
     "biz_enyy": "예비창업자", "rcrt_prgs_yn": "Y",
     "detl_pg_url": "https://www.k-startup.go.kr/x/1"},
    {"pbanc_sn": "2", "biz_pbanc_nm": "지난 창업 지원", "pbanc_ntrp_nm": "창업진흥원",
     "supt_biz_clsfc": "사업화", "aply_trgt_ctnt": "창업기업", "supt_regin": "전국",
     "pbanc_rcpt_bgng_dt": "20250101", "pbanc_rcpt_end_dt": "20250201",
     "biz_enyy": "3년미만", "rcrt_prgs_yn": "N",
     "detl_pg_url": "https://www.k-startup.go.kr/x/2"},
]
BIZINFO_ROWS = [
    {"pblancId": "PBLN-1", "pblancNm": "소상공인 경영안정자금", "jrsdInsttNm": "서울특별시",
     "excInsttNm": "서울신용보증재단", "bsnsSumryCn": "운영자금 이자 지원",
     "pldirSportRealmLclasCodeNm": "금융", "reqstBeginEndDe": "2026. 11. 1. ~ 2026. 12. 31.",
     "trgetNm": "소상공인", "hashtags": "금융,서울", "refrncNm": "02-000-0000",
     "pblancUrl": "https://www.bizinfo.go.kr/sii/1"},
]


class FakeGov24Client:
    def __init__(self, key):
        self.key = key

    @staticmethod
    def _rows(payload):
        return list(payload.get("data") or [])

    def service_list(self, page=1, per_page=1000, conds=None):
        return {"data": GOV24_SERVICES, "totalCount": len(GOV24_SERVICES),
                "currentCount": len(GOV24_SERVICES)}

    def iter_conditions(self, per_page=1000, max_pages=None):
        for row in GOV24_CONDITIONS:
            yield row

    def support_conditions(self, service_id):
        return GOV24_CONDITIONS[0] if service_id == "R-1" else None


class FakeKStartupClient:
    rows = KSTARTUP_ROWS

    def __init__(self, key, *args, **kwargs):
        self.key = key

    def records(self, **kwargs):
        from subsidy_kr import programs

        return [programs.normalize_kstartup(row) for row in self.rows]


class FakeBizinfoClient:
    rows = BIZINFO_ROWS

    def __init__(self, key, *args, **kwargs):
        self.key = key

    def records(self, **kwargs):
        from subsidy_kr import programs

        return [programs.normalize_bizinfo(row) for row in self.rows]


class SyncAllTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._gov24 = sync_gov24.Gov24Client
        self._startup = sync_gov24.startup.KStartupClient
        self._bizinfo = sync_gov24.bizinfo.BizinfoClient
        sync_gov24.Gov24Client = FakeGov24Client
        sync_gov24.startup.KStartupClient = FakeKStartupClient
        sync_gov24.bizinfo.BizinfoClient = FakeBizinfoClient

    def tearDown(self):
        sync_gov24.Gov24Client = self._gov24
        sync_gov24.startup.KStartupClient = self._startup
        sync_gov24.bizinfo.BizinfoClient = self._bizinfo
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_integrated_catalog_and_snapshot(self):
        report = sync_gov24.sync_all("TESTKEY", data_dir=self.tmp, force=True)
        self.assertTrue(report["ok"])
        self.assertEqual(report["stats"]["by_track"]["personal"], 1)
        self.assertEqual(report["stats"]["by_track"]["business"], 2)   # 지난 공고 1건 제외
        self.assertEqual(report["sources"]["startup"]["fetched"], 2)
        self.assertEqual(report["sources"]["startup"]["dropped_expired"], 1)

        catalog = load_catalog(os.path.join(self.tmp, "catalog.json"))
        self.assertEqual(catalog.meta["catalog_state"], "synced")
        self.assertTrue(catalog.get("R-1"))
        self.assertTrue(catalog.get("KSU-1"))
        self.assertTrue(catalog.get("BIZ-PBLN-1"))
        self.assertFalse(catalog.get("KSU-2"))            # 지난 공고는 카탈로그에 없다
        business = catalog.get("KSU-1")
        self.assertEqual(business.track, "business")
        self.assertEqual(business.source, "kstartup")
        self.assertEqual(business.business["status"], "pre")

        snap_dir = os.path.join(self.tmp, "snapshots")
        self.assertTrue(os.path.exists(os.path.join(snap_dir, "index.json")))
        self.assertEqual(len(os.listdir(snap_dir)), 2)     # 스냅샷 1장 + index

    def test_local_portals_are_merged(self):
        """지자체 자체 복지포털 행도 카탈로그·메타에 함께 들어간다."""
        from subsidy_kr import local_portals

        original = local_portals.collect_all_local_portals
        local_portals.collect_all_local_portals = lambda **_kwargs: {
            "records": [{"서비스ID": "LOC-1", "서비스명": "부평 청년 수당",
                         "소관기관명": "부평구청", "지원대상": "부평구 청년",
                         "지원내용": "월 10만 원", "신청기한": "상시",
                         "source": "local_portal"}],
            "counts": {"bupyeong_bokjion": 1, "total_deduped": 1},
        }
        try:
            report = sync_gov24.sync_all("TESTKEY", data_dir=self.tmp, force=True,
                                         include_local_portals=True)
        finally:
            local_portals.collect_all_local_portals = original
        self.assertTrue(report["ok"])
        with open(os.path.join(self.tmp, "catalog.json"), encoding="utf-8") as handle:
            payload = json.load(handle)
        ids = {row["서비스ID"] for row in payload["services"]}
        self.assertIn("LOC-1", ids)
        self.assertEqual(payload["meta"]["local_portal_counts"]["total_deduped"], 1)
        self.assertEqual(report["sources"]["local_portal"]["services"], 1)
        self.assertIn("지자체", payload["meta"]["source"])

    def test_local_portal_failure_keeps_existing_rows(self):
        """포털이 막혀도 이미 있던 지자체 항목을 지우지 않는다(부분 실패 허용)."""
        from subsidy_kr import local_portals

        with open(os.path.join(self.tmp, "catalog.json"), "w", encoding="utf-8") as handle:
            json.dump({"meta": {"catalog_state": "synced"},
                       "services": [{"서비스ID": "LOC-OLD", "서비스명": "기존 지자체 제도",
                                     "소관기관명": "연수구청", "지원대상": "연수구 주민",
                                     "지원내용": "바우처", "신청기한": "상시",
                                     "source": "local_portal"}]},
                      handle, ensure_ascii=False)

        def boom(**_kwargs):
            raise RuntimeError("portal blocked")

        original = local_portals.collect_all_local_portals
        local_portals.collect_all_local_portals = boom
        try:
            report = sync_gov24.sync_all("TESTKEY", data_dir=self.tmp, force=True,
                                         include_local_portals=True)
        finally:
            local_portals.collect_all_local_portals = original
        self.assertTrue(report["ok"])
        with open(os.path.join(self.tmp, "catalog.json"), encoding="utf-8") as handle:
            ids = {row["서비스ID"] for row in json.load(handle)["services"]}
        self.assertIn("LOC-OLD", ids)
        self.assertIn("기존유지", report["sources"]["local_portal"]["state"])
        self.assertTrue(any("지자체 포털" in warning for warning in report["warnings"]))

    def test_local_portal_partial_failure_keeps_that_portal(self):
        """포털 하나가 0건이면 그 포털 행만 기존 것을 유지하고, 받은 포털은 새 것으로 교체한다."""
        from subsidy_kr import local_portals

        with open(os.path.join(self.tmp, "catalog.json"), "w", encoding="utf-8") as handle:
            json.dump({"meta": {"catalog_state": "synced"},
                       "services": [
                           {"서비스ID": "SEOULWIS-1", "서비스명": "서울 기존 제도",
                            "소관기관명": "서울특별시 (서울복지포털)", "source": "local_portal"},
                           {"서비스ID": "BOKJION-1", "서비스명": "부평 옛 제도",
                            "소관기관명": "인천광역시 부평구 (부평복지ON)", "source": "local_portal"},
                       ]}, handle, ensure_ascii=False)

        original = local_portals.collect_all_local_portals
        local_portals.collect_all_local_portals = lambda **_kwargs: {
            "records": [{"서비스ID": "BOKJION-2", "서비스명": "부평 새 제도",
                         "소관기관명": "인천광역시 부평구 (부평복지ON)", "source": "local_portal"}],
            "counts": {"bupyeong_bokjion": 1, "seoul_wis": 0},
        }
        try:
            report = sync_gov24.sync_all("TESTKEY", data_dir=self.tmp, force=True,
                                         include_local_portals=True)
        finally:
            local_portals.collect_all_local_portals = original
        with open(os.path.join(self.tmp, "catalog.json"), encoding="utf-8") as handle:
            ids = {row["서비스ID"] for row in json.load(handle)["services"]}
        self.assertIn("BOKJION-2", ids)      # 새로 받은 포털은 교체
        self.assertNotIn("BOKJION-1", ids)
        self.assertIn("SEOULWIS-1", ids)     # 0건이었던 포털은 기존 유지
        self.assertIn("SEOULWIS", report["sources"]["local_portal"]["counts"]["kept_from_previous"])

    def test_second_run_reports_changes(self):
        sync_gov24.sync_all("TESTKEY", data_dir=self.tmp, force=True)
        # 하루 전 스냅샷을 흉내 낸다(공고 1건이 빠진 상태).
        from subsidy_kr import snapshots

        snap_dir = snapshots.snapshot_dir(self.tmp)
        old = snapshots.load_snapshot(report_day := list(
            {os.path.basename(name)[:-5] for name in os.listdir(snap_dir)
             if name.endswith(".json") and name != "index.json"})[0], snap_dir)
        old["meta"]["day"] = "2026-01-01"
        old["services"].pop("KSU-1", None)
        snapshots.save_snapshot(old, snap_dir)
        report = sync_gov24.sync_all("TESTKEY", data_dir=self.tmp, force=True)
        self.assertEqual(report["changes"]["added"], 1)
        self.assertEqual(report["changes"]["compared_to"], "2026-01-01")
        self.assertTrue(report_day)

    def test_include_expired_keeps_everything(self):
        report = sync_gov24.sync_all("TESTKEY", data_dir=self.tmp, force=True,
                                     include_expired=True)
        self.assertEqual(report["stats"]["by_track"]["business"], 3)

    def test_missing_key_keeps_existing_programs(self):
        sync_gov24.sync_all("TESTKEY", data_dir=self.tmp, force=True)
        report = sync_gov24.sync_all(None, data_dir=self.tmp, force=True)
        # gov24 는 키가 없어 실패하지만, 기존 카탈로그의 3건은 유지된다.
        self.assertTrue(report["ok"])
        self.assertEqual(report["stats"]["services"], 3)
        self.assertTrue(any("보조금24 동기화 실패" in item for item in report["warnings"]))

    def test_dry_run_writes_nothing(self):
        report = sync_gov24.sync_all("TESTKEY", data_dir=self.tmp, force=True, dry_run=True)
        self.assertTrue(report["ok"])
        self.assertEqual(report["saved_files"], [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "catalog.json")))

    def test_unknown_source_is_ignored_in_collect(self):
        result = sync_gov24.collect_programs("TESTKEY", data_dir=self.tmp,
                                            sources=("nope",), force=True)
        self.assertEqual(result["records"], [])
        self.assertTrue(any("알 수 없는 소스" in item for item in result["warnings"]))

    def test_cli_all_sources(self):
        code = sync_gov24.main(["--key", "TESTKEY", "--data-dir", self.tmp,
                                "--sources", "all", "--json", "--force"])
        self.assertEqual(code, 0)
        payload = json.load(open(os.path.join(self.tmp, "catalog.json"), encoding="utf-8"))
        self.assertEqual(payload["meta"]["tracks"]["personal"], 1)
        self.assertIn("snapshot_day", payload["meta"])

    def test_cli_rejects_unknown_source(self):
        code = sync_gov24.main(["--sources", "nope", "--data-dir", self.tmp])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
