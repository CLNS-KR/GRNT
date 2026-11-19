"""창업·기업 트랙 판정·검색 테스트."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import engine, models  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402

TODAY = date(2026, 11, 19)


def profile(**kwargs):
    kwargs.setdefault("situations", [])
    return engine.normalize_profile(kwargs, today=TODAY)


def business_profile(**overrides):
    biz = {"status": "pre", "entity": "pre_startup"}
    biz.update(overrides.pop("business", {}))
    base = {"track": "business", "age": 33, "sex": "male",
            "region": {"sido": "인천광역시", "sigungu": "서구"}, "business": biz}
    base.update(overrides)
    return profile(**base)


class ProfileBusinessTest(unittest.TestCase):
    def test_status_and_entity_normalized(self):
        prof = business_profile()
        self.assertEqual(prof["track"], "business")
        self.assertTrue(prof["business"]["declared"])
        self.assertEqual(prof["business"]["status"], "pre")
        self.assertEqual(prof["business"]["entity"], "pre_startup")
        self.assertEqual(prof["business"]["entity_label"], "예비창업자")

    def test_pre_status_implies_entity(self):
        prof = profile(track="business", business={"status": "pre"})
        self.assertEqual(prof["business"]["entity"], "pre_startup")

    def test_invalid_values_are_dropped(self):
        prof = profile(track="business", business={"status": "weird", "entity": "nope",
                                                   "years": 99, "industry": "space"})
        self.assertIsNone(prof["business"]["status"])
        self.assertIsNone(prof["business"]["entity"])
        self.assertIsNone(prof["business"]["years"])
        self.assertIsNone(prof["business"]["industry"])

    def test_missing_core_is_track_aware(self):
        personal = profile().get("missing_core")
        keys = {item["key"] for item in personal}
        self.assertIn("age", keys)
        self.assertIn("income_band", keys)

        business = profile(track="business").get("missing_core")
        biz_keys = {item["key"] for item in business}
        self.assertIn("biz_status", biz_keys)
        self.assertNotIn("income_band", biz_keys)

        operating = profile(track="business", business={"status": "operating"}).get("missing_core")
        self.assertIn("biz_years", {item["key"] for item in operating})

    def test_explain_profile_has_no_raw_input(self):
        explained = engine.explain_profile(business_profile())
        self.assertEqual(explained["track"], "business")
        self.assertEqual(explained["business"]["status"], "pre")
        self.assertNotIn("profile", explained)


class BusinessVerdictTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def _id(self, name_part):
        for service in self.catalog.services:
            if name_part in service.name:
                return service.service_id
        raise AssertionError(name_part)

    def _row(self, name_part, prof):
        return engine.evaluate_service(self.catalog.get(self._id(name_part)), prof)

    def test_pre_startup_matches_pre_package(self):
        row = self._row("예비창업패키지", business_profile())
        self.assertEqual(row["verdict"]["code"], models.VERDICT_ELIGIBLE)
        self.assertEqual(row["track"], "business")
        self.assertTrue(any("신청자격" in note for note in row["notes_ko"]))

    def test_operating_business_cannot_use_pre_only(self):
        row = self._row("예비창업패키지", business_profile(
            business={"status": "operating", "entity": "small_business", "years": 2}))
        self.assertEqual(row["verdict"]["code"], models.VERDICT_INELIGIBLE)
        self.assertTrue(any(rule["group"] == "business" and rule["state"] == "fail"
                            for rule in row["why"]))

    def test_business_years_limit(self):
        over = self._row("초기창업패키지", business_profile(
            business={"status": "operating", "entity": "sme", "years": 5}))
        self.assertEqual(over["verdict"]["code"], models.VERDICT_INELIGIBLE)
        within = self._row("초기창업패키지", business_profile(
            business={"status": "operating", "entity": "sme", "years": 2}))
        self.assertEqual(within["verdict"]["code"], models.VERDICT_ELIGIBLE)

    def test_missing_years_is_insufficient(self):
        row = self._row("초기창업패키지", business_profile(
            business={"status": "operating", "entity": "sme"}))
        self.assertEqual(row["verdict"]["code"], models.VERDICT_INSUFFICIENT)
        self.assertIn("biz_years", {item["key"] for item in row["missing_information"]})

    def test_age_limit(self):
        too_old = self._row("청년창업사관학교", business_profile(age=45))
        self.assertEqual(too_old["verdict"]["code"], models.VERDICT_INELIGIBLE)

    def test_female_only_program(self):
        female = self._row("여성기업 창업", business_profile(sex="female"))
        self.assertEqual(female["verdict"]["code"], models.VERDICT_ELIGIBLE)
        male = self._row("여성기업 창업", business_profile(sex="male"))
        self.assertEqual(male["verdict"]["code"], models.VERDICT_INELIGIBLE)
        unknown = self._row("여성기업 창업", business_profile(sex=None))
        self.assertEqual(unknown["verdict"]["code"], models.VERDICT_INSUFFICIENT)

    def test_regional_program_rejects_other_region(self):
        row = self._row("인천 청년창업", business_profile(
            region={"sido": "서울특별시", "sigungu": "강남구"}))
        self.assertEqual(row["verdict"]["code"], models.VERDICT_INELIGIBLE)

    def test_closed_recruitment_is_check_needed(self):
        row = self._row("경기도 스타트업", business_profile(
            region={"sido": "경기도"}, business={"status": "operating", "entity": "sme",
                                                "years": 2}))
        self.assertEqual(row["verdict"]["code"], models.VERDICT_CHECK)
        self.assertTrue(any("마감" in rule["reason_ko"] for rule in row["why"]))

    def test_result_carries_business_metadata(self):
        row = self._row("예비창업패키지", business_profile())
        for key in ("track", "track_label", "source", "attribution_ko", "business",
                    "business_summary_ko", "fingerprint"):
            self.assertIn(key, row)
        self.assertEqual(row["data_state"], "sample")

    def test_personal_service_is_not_judged_by_business_rules(self):
        personal = profile(age=34, income_band="JA0203", situations=["no_home"])
        row = engine.evaluate_service(self.catalog.get("SMP-0001"), personal)
        self.assertEqual(row["track"], "personal")
        self.assertFalse(any(rule["group"] == "business" for rule in row["why"]))


class TrackSearchTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_personal_track_excludes_business(self):
        result = engine.search(self.catalog, profile(age=30), include_ineligible=True, limit=50)
        self.assertTrue(result["results"])
        self.assertTrue(all(row["track"] == "personal" for row in result["results"]))
        self.assertEqual(result["track_counts"]["business"], 0)

    def test_business_track_excludes_personal(self):
        result = engine.search(self.catalog, business_profile(), include_ineligible=True, limit=50)
        self.assertTrue(result["results"])
        self.assertTrue(all(row["track"] == "business" for row in result["results"]))
        self.assertEqual(result["track_counts"]["personal"], 0)

    def test_all_without_business_info_shows_personal_only(self):
        result = engine.search(self.catalog, profile(age=30), include_ineligible=True, limit=50)
        self.assertEqual(result["track_counts"]["business"], 0)

    def test_all_with_business_info_shows_both(self):
        prof = business_profile()
        prof["track"] = "all"
        result = engine.search(self.catalog, prof, include_ineligible=True, limit=200)
        self.assertGreater(result["track_counts"]["business"], 0)
        self.assertGreater(result["track_counts"]["personal"], 0)

    def test_closed_programs_hidden_by_default(self):
        prof = business_profile(region={"sido": "경기도", "sigungu": "수원시 장안구"})
        hidden = engine.search(self.catalog, prof, include_ineligible=True, limit=200)
        names = {row["name"] for row in hidden["results"]}
        self.assertNotIn("2026년 경기도 스타트업 육성 지원", names)
        self.assertGreater(hidden["closed_hidden"], 0)
        shown = engine.search(self.catalog, prof, include_ineligible=True, limit=200,
                              include_closed=True)
        self.assertIn("2026년 경기도 스타트업 육성 지원",
                      {row["name"] for row in shown["results"]})

    def test_tag_filter_on_business(self):
        result = engine.search(self.catalog, business_profile(), tag="finance",
                               include_ineligible=True, limit=50)
        for row in result["results"]:
            self.assertIn("finance", row["tags"])

    def test_counts_cover_scanned(self):
        result = engine.search(self.catalog, business_profile(), limit=10)
        self.assertEqual(sum(result["counts"].values()), result["scanned"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
