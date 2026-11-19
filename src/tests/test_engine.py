"""판정 엔진 테스트 — 등급·경계값·누락 정보·아동 대상·지자체 공백·지역."""
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


class ProfileTest(unittest.TestCase):
    def test_age_from_birth_year_and_date(self):
        self.assertEqual(profile(birth_year=1992)["age"], 34)
        self.assertEqual(profile(birth_date="1992-12-01")["age"], 33)
        self.assertEqual(profile(birth_date="1992-04-19")["age"], 34)
        self.assertEqual(profile(age=29)["age"], 29)
        self.assertIsNone(profile()["age"])

    def test_income_percent_becomes_band(self):
        self.assertEqual(profile(income_percent=80)["income_band"], "JA0203")
        self.assertEqual(profile(income_percent="55%")["income_band"], "JA0202")
        self.assertEqual(profile(income_band="JA0201")["income_band"], "JA0201")
        self.assertIsNone(profile(income_band="BAD")["income_band"])

    def test_situations_declared_vs_omitted(self):
        declared = profile(situations=[])
        self.assertTrue(declared["situations_declared"])
        self.assertEqual(declared["situations"], [])
        omitted = engine.normalize_profile({"age": 30}, today=TODAY)
        self.assertFalse(omitted["situations_declared"])
        unknown = profile(situations=["pregnant", "not_a_tag"])
        self.assertEqual(unknown["situations"], ["pregnant"])
        self.assertEqual(unknown["ignored_situations"], ["not_a_tag"])

    def test_children_years(self):
        prof = profile(children_years=[2024, 2026])
        self.assertTrue(prof["children_declared"])
        self.assertEqual(prof["children_ages"], [2, 0])

    def test_missing_core_questions(self):
        missing = {item["key"] for item in engine.normalize_profile({}, today=TODAY)["missing_core"]}
        self.assertIn("age", missing)
        self.assertIn("region", missing)
        self.assertIn("income_band", missing)
        self.assertIn("situations", missing)

    def test_household_size_bounds(self):
        self.assertEqual(profile(household_size=4)["household_size"], 4)
        self.assertIsNone(profile(household_size=0)["household_size"])
        self.assertIsNone(profile(household_size=99)["household_size"])


class VerdictTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def _row(self, service_id, **kwargs):
        return engine.evaluate_service(self.catalog.get(service_id), profile(**kwargs))

    def test_eligible_when_all_codes_match(self):
        row = self._row("SMP-0001", age=34, region={"sido": "인천광역시", "sigungu": "서구"},
                        income_band="JA0203", situations=["no_home", "worker"])
        self.assertEqual(row["verdict"]["code"], models.VERDICT_ELIGIBLE)
        self.assertTrue(all(rule["state"] == "pass" for rule in row["why"]))

    def test_ineligible_income_and_reason(self):
        row = self._row("SMP-0002", age=34, income_band="JA0203", situations=["no_home"])
        self.assertEqual(row["verdict"]["code"], models.VERDICT_INELIGIBLE)
        failed = [rule for rule in row["why"] if rule["state"] == "fail"]
        self.assertEqual(failed[0]["group"], "income")
        self.assertIn("중위소득", failed[0]["reason_ko"])

    def test_insufficient_income(self):
        row = self._row("SMP-0002", age=34, situations=["no_home"])
        self.assertEqual(row["verdict"]["code"], models.VERDICT_INSUFFICIENT)
        keys = {item["key"] for item in row["missing_information"]}
        self.assertIn("income_band", keys)

    def test_insufficient_when_situations_omitted(self):
        service = self.catalog.get("SMP-0001")
        prof = engine.normalize_profile({"age": 30, "income_band": "JA0203"}, today=TODAY)
        row = engine.evaluate_service(service, prof)
        self.assertEqual(row["verdict"]["code"], models.VERDICT_INSUFFICIENT)
        keys = {item["key"] for item in row["missing_information"]}
        self.assertIn("situations.household", keys)
        self.assertTrue(any("가구" in item["question_ko"] for item in row["missing_information"]))

    def test_declared_no_situation_fails(self):
        row = self._row("SMP-0001", age=34, income_band="JA0203", situations=[])
        self.assertEqual(row["verdict"]["code"], models.VERDICT_INELIGIBLE)

    def test_local_missing_criteria_is_check_needed(self):
        row = self._row("SMP-0015", age=34, region={"sido": "인천광역시", "sigungu": "서구"},
                        situations=["no_home"])
        self.assertEqual(row["verdict"]["code"], models.VERDICT_CHECK)
        self.assertEqual(row["criteria_state"], "missing")
        self.assertTrue(any("선정기준" in rule["reason_ko"] for rule in row["why"]))

    def test_unpredictable_allocation_is_check_needed(self):
        row = self._row("SMP-0012", age=30, income_band="JA0203", situations=["worker"])
        self.assertEqual(row["verdict"]["code"], models.VERDICT_CHECK)
        self.assertTrue(any("선착순" in rule["reason_ko"] or "추첨" in rule["reason_ko"]
                            or "예산" in rule["reason_ko"] for rule in row["why"]))

    def test_region_mismatch(self):
        row = self._row("SMP-0017", age=30, region={"sido": "인천광역시", "sigungu": "서구"},
                        income_band="JA0203", situations=["jobseeker"])
        self.assertEqual(row["verdict"]["code"], models.VERDICT_INELIGIBLE)
        self.assertEqual(row["why"][0]["group"], "region")

    def test_child_age_subject(self):
        # 자녀 0세 + 출산 → 부모급여 대상
        row = self._row("SMP-0003", age=34, situations=["birth"], children_years=[2026])
        self.assertEqual(row["verdict"]["code"], models.VERDICT_ELIGIBLE)
        self.assertTrue(any(rule.get("subject") == "child" for rule in row["why"]))
        # 자녀 나이를 모르면 신청자 나이로 탈락시키지 않고 정보 부족
        row = self._row("SMP-0003", age=34, situations=["birth"])
        self.assertEqual(row["verdict"]["code"], models.VERDICT_INSUFFICIENT)
        self.assertIn("children_ages", {item["key"] for item in row["missing_information"]})
        # 자녀가 없다고 입력하면 해당 없음
        row = self._row("SMP-0003", age=34, situations=["birth"], children_years=[])
        self.assertEqual(row["verdict"]["code"], models.VERDICT_INELIGIBLE)

    def test_age_boundary_exact_year(self):
        # 경기도 청년기본소득은 만 24세만
        eligible = self._row("SMP-0018", age=24, region={"sido": "경기도", "sigungu": "수원시 장안구"})
        self.assertEqual(eligible["verdict"]["code"], models.VERDICT_ELIGIBLE)
        too_old = self._row("SMP-0018", age=25, region={"sido": "경기도", "sigungu": "수원시 장안구"})
        self.assertEqual(too_old["verdict"]["code"], models.VERDICT_INELIGIBLE)

    def test_open_ended_age(self):
        # 장애인연금: 18세 이상, 상한 없음(원천 JA0111=0)
        young = self._row("SMP-0007", age=17, income_band="JA0202", situations=["disabled"])
        self.assertEqual(young["verdict"]["code"], models.VERDICT_INELIGIBLE)
        adult = self._row("SMP-0007", age=18, income_band="JA0202", situations=["disabled"])
        self.assertEqual(adult["verdict"]["code"], models.VERDICT_ELIGIBLE)
        senior = self._row("SMP-0007", age=88, income_band="JA0202", situations=["disabled"])
        self.assertEqual(senior["verdict"]["code"], models.VERDICT_ELIGIBLE)

    def test_criteria_flags_surface_extra_requirements(self):
        row = self._row("SMP-0001", age=34, income_band="JA0203", situations=["no_home"])
        self.assertIn("재산 기준 포함", row["criteria_flags"])
        self.assertTrue(any("재산" in note for note in row["notes_ko"]))

    def test_sample_data_is_flagged(self):
        row = self._row("SMP-0001", age=34, income_band="JA0203", situations=["no_home"])
        self.assertEqual(row["data_state"], "sample")
        self.assertTrue(any("샘플" in note for note in row["notes_ko"]))

    def test_result_shape_is_stable(self):
        row = self._row("SMP-0001", age=34, income_band="JA0203", situations=["no_home"])
        for key in ("service_id", "name", "agency", "region", "verdict", "why",
                    "matched_conditions", "missing_information", "criteria_state",
                    "criteria_flags", "amount", "application", "contact", "detail_url",
                    "notes_ko", "data_state"):
            self.assertIn(key, row)


class SearchTest(unittest.TestCase):
    def setUp(self):
        # 검색 계약은 내장 샘플로 검증한다(실데이터는 test_live_catalog.py 에서 따로).
        self.catalog = sample_catalog()

    def test_counts_cover_every_scanned_service(self):
        result = engine.search(self.catalog, profile(age=34, income_band="JA0203",
                                                     situations=["no_home"],
                                                     region={"sido": "인천광역시", "sigungu": "서구"}))
        self.assertEqual(sum(result["counts"].values()), result["scanned"])
        self.assertTrue(result["results"])
        self.assertNotIn(models.VERDICT_INELIGIBLE,
                         [row["verdict"]["code"] for row in result["results"]])
        self.assertGreater(result["ineligible_hidden"], 0)

    def test_include_ineligible_and_limit(self):
        result = engine.search(self.catalog, profile(age=34), limit=3, include_ineligible=True)
        self.assertLessEqual(len(result["results"]), 3)
        self.assertTrue(result["truncated"])

    def test_region_filter_drops_other_provinces(self):
        result = engine.search(self.catalog, profile(age=30, situations=[],
                                                     region={"sido": "인천광역시", "sigungu": "서구"}),
                               include_ineligible=True, limit=50)
        names = {row["name"] for row in result["results"]}
        self.assertNotIn("서울특별시 청년수당", names)

    def test_tag_filter(self):
        result = engine.search(self.catalog, profile(age=30, situations=[]), tag="housing",
                               include_ineligible=True, limit=50)
        self.assertTrue(result["results"])
        for row in result["results"]:
            self.assertIn("housing", row["tags"])

    def test_keyword_filter(self):
        result = engine.search(self.catalog, profile(age=30, situations=[]),
                               keyword="월세", include_ineligible=True, limit=50)
        self.assertTrue(result["results"])
        for row in result["results"]:
            self.assertIn("월세", row["name"] + row["amount"] + row["name"])

    def test_empty_profile_never_claims_eligibility(self):
        result = engine.search(self.catalog, engine.normalize_profile({}, today=TODAY),
                               include_ineligible=False, limit=50)
        self.assertFalse(any(row["verdict"]["code"] == models.VERDICT_ELIGIBLE
                             for row in result["results"]))


class SortTest(unittest.TestCase):
    def test_verdict_order_puts_likely_first(self):
        self.assertLess(models.SORT_INDEX[models.VERDICT_ELIGIBLE],
                        models.SORT_INDEX[models.VERDICT_CHECK])
        self.assertLess(models.SORT_INDEX[models.VERDICT_CHECK],
                        models.SORT_INDEX[models.VERDICT_INSUFFICIENT])
        self.assertLess(models.SORT_INDEX[models.VERDICT_INSUFFICIENT],
                        models.SORT_INDEX[models.VERDICT_INELIGIBLE])

    def test_worst_aggregation(self):
        self.assertEqual(models.worst(["eligible_likely", "check_needed"]), "check_needed")
        self.assertEqual(models.worst(["eligible_likely", "insufficient_info"]), "insufficient_info")
        self.assertEqual(models.worst(["ineligible", "insufficient_info"]), "ineligible")


if __name__ == "__main__":
    unittest.main(verbosity=2)
