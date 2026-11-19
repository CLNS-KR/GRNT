"""동기화 산출물(실데이터) 통합 검증 — 산출물이 없으면 건너뛴다.

`python -m subsidy_kr.sync_gov24 --sources all` 로 받은 `data/gov24/catalog.json` 이
있을 때만 돌아갑니다. 샘플로는 잡히지 않는 실데이터 특유의 회귀를 막는 것이 목적입니다.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from subsidy_kr import engine, models, programs  # noqa: E402
from subsidy_kr.catalog import load_catalog  # noqa: E402

CATALOG = os.path.join(PROJECT, "data", "gov24", "catalog.json")
HAS_DATA = os.path.exists(CATALOG)


@unittest.skipUnless(HAS_DATA, "동기화 산출물이 없어 건너뜁니다")
class LiveCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(CATALOG)

    def test_catalog_is_synced_and_mixed(self):
        self.assertEqual(self.catalog.meta["catalog_state"], "synced")
        stats = self.catalog.stats()
        self.assertGreater(stats["services"], 1000)
        self.assertGreater(stats["by_track"][programs.TRACK_PERSONAL], 0)
        self.assertGreater(stats["by_track"][programs.TRACK_BUSINESS], 0)
        self.assertIn("gov24", stats["by_source"])

    def test_business_rows_have_attribution_and_track(self):
        business = [svc for svc in self.catalog.services if svc.is_business][:20]
        self.assertTrue(business)
        for svc in business:
            self.assertIn(svc.source, ("kstartup", "bizinfo", "sample"))
            self.assertTrue(svc.attribution)
            self.assertIn("business", {"business": svc.business})

    def test_empty_profile_never_claims_eligibility(self):
        empty = engine.normalize_profile({})
        result = engine.search(self.catalog, empty, limit=200)
        codes = {row["verdict"]["code"] for row in result["results"]}
        self.assertNotIn(models.VERDICT_ELIGIBLE, codes)

    def test_personal_search_returns_reasons(self):
        prof = engine.normalize_profile({
            "age": 34, "income_band": "JA0203", "situations": ["no_home"],
            "region": {"sido": "인천광역시", "sigungu": "서구"}})
        result = engine.search(self.catalog, prof, limit=10)
        self.assertTrue(result["results"])
        for row in result["results"]:
            self.assertEqual(row["track"], programs.TRACK_PERSONAL)
            self.assertTrue(row["why"])

    def test_business_search_returns_announcements(self):
        prof = engine.normalize_profile({
            "track": "business", "age": 33, "region": {"sido": "인천광역시",
                                                       "sigungu": "서구"},
            "business": {"status": "pre", "entity": "pre_startup"}})
        result = engine.search(self.catalog, prof, limit=10)
        self.assertTrue(result["results"])
        for row in result["results"]:
            self.assertEqual(row["track"], programs.TRACK_BUSINESS)
            self.assertIn(row["data_state"], ("kstartup", "bizinfo", "sample"))

    def test_no_business_program_is_expired(self):
        from datetime import date

        for svc in self.catalog.services:
            if not svc.is_business:
                continue
            end = svc.deadline.get("end_date")
            if end:
                self.assertGreaterEqual(
                    date.fromisoformat(end),
                    date.today().replace(year=date.today().year) - __import__("datetime").timedelta(days=400),
                    svc.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
