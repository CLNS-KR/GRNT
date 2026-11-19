"""카탈로그 로딩·정규화 테스트(샘플 ↔ 동기화 산출물)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import catalog as catalog_module  # noqa: E402
from subsidy_kr import sample_data, sample_programs  # noqa: E402


class SampleCatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog_module.sample_catalog()

    def test_loads_every_sample_service(self):
        self.assertEqual(len(self.catalog.services),
                         len(sample_data.services()) + len(sample_programs.services()))
        self.assertGreaterEqual(len(self.catalog.services), 20)
        self.assertEqual(self.catalog.meta["catalog_state"], "sample")

    def test_ids_unique_and_lookup(self):
        ids = [svc.service_id for svc in self.catalog.services]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIsNotNone(self.catalog.get("SMP-0001"))
        self.assertIsNone(self.catalog.get("SMP-9999"))

    def test_regions_parsed_from_agency(self):
        local = self.catalog.get("SMP-0015")
        self.assertEqual((local.region["sido"], local.region["sigungu"]), ("인천광역시", "서구"))
        national = self.catalog.get("SMP-0001")
        self.assertEqual(national.region["level"], "national")

    def test_tags_and_fields(self):
        service = self.catalog.get("SMP-0001")
        self.assertIn("youth", service.tags)
        self.assertIn("housing", service.tags)
        self.assertEqual(service.field_label, "주거")

    def test_deadline_is_parsed(self):
        service = self.catalog.get("SMP-0001")
        self.assertEqual(service.deadline["state"], "date_range")
        self.assertEqual(service.deadline["end_date"], "2026-12-31")

    def test_criteria_state_flags(self):
        self.assertFalse(self.catalog.get("SMP-0015").has_criteria)
        self.assertTrue(self.catalog.get("SMP-0001").has_criteria)
        self.assertIn("재산 기준 포함", self.catalog.get("SMP-0001").criteria_flags)

    def test_stats(self):
        stats = self.catalog.stats()
        self.assertEqual(stats["services"], len(self.catalog.services))
        self.assertGreater(stats["local_services"], 0)
        self.assertGreater(stats["local_missing_criteria"], 0)
        # 두 번 호출해도 같은 딕셔너리를 재사용한다(캐시)
        self.assertIs(self.catalog.stats(), stats)

    def test_by_region(self):
        services = self.catalog.by_region("인천광역시", "서구")
        names = {svc.name for svc in services}
        self.assertIn("인천광역시 서구 청년월세 지원", names)
        self.assertIn("청년월세 한시 특별지원", names)      # 전국 제도 포함
        self.assertNotIn("부산광역시 청년 주거비 지원", names)

    def test_search_ranking(self):
        hits = self.catalog.search("청년월세")
        self.assertTrue(hits)
        self.assertIn("청년월세", hits[0].name)


class SyncedCatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "catalog.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)

    def test_reads_synced_catalog(self):
        raw = sample_data.services()[0]
        raw = dict(raw)
        raw["서비스ID"] = "REAL-1"
        self._write({"meta": {"generated_on": "2026-11-19T00:00:00+09:00",
                              "stats": {"services": 1}},
                     "services": [raw]})
        catalog = catalog_module.load_catalog(self.path)
        self.assertEqual(catalog.meta["catalog_state"], "synced")
        self.assertEqual(catalog.get("REAL-1").source, "gov24")
        self.assertEqual(catalog.meta["data_state"], "live_sync")

    def test_broken_file_falls_back_to_sample(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        catalog = catalog_module.load_catalog(self.path)
        self.assertEqual(catalog.meta["catalog_state"], "sample")
        self.assertIn("fallback_reason_ko", catalog.meta)
        self.assertGreaterEqual(len(catalog.services), 20)

    def test_empty_catalog_falls_back(self):
        self._write({"meta": {}, "services": []})
        catalog = catalog_module.load_catalog(self.path)
        self.assertEqual(catalog.meta["catalog_state"], "sample")

    def test_missing_file_is_sample(self):
        catalog = catalog_module.load_catalog(os.path.join(self.tmp, "nope.json"))
        self.assertEqual(catalog.meta["catalog_state"], "sample")


class NormalizeTest(unittest.TestCase):
    def test_alternate_field_names(self):
        service = catalog_module.normalize_service({
            "SVC_ID": "X1", "서비스명": "테스트", "소관기관명": "부산광역시 해운대구",
            "접수기관명": "해운대구청", "문의처": "051-000-0000", "지원유형": "현금",
            "conditions": {"JA0201": "Y"},
        })
        self.assertEqual(service.service_id, "X1")
        self.assertEqual(service.receipt_agency, "해운대구청")
        self.assertEqual(service.contact, "051-000-0000")
        self.assertEqual(service.region["sigungu"], "해운대구")

    def test_missing_fields_are_blank_not_none(self):
        service = catalog_module.normalize_service({"서비스ID": "X2", "서비스명": "빈 값"})
        for value in (service.agency, service.target, service.criteria, service.contact,
                      service.detail_url, service.deadline_text):
            self.assertEqual(value, "")
        self.assertFalse(service.has_criteria)
        self.assertEqual(service.deadline["state"], "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
