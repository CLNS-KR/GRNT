"""자격 코드(JA) 해석 단위 테스트."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import conditions  # noqa: E402


class ConditionCatalogTest(unittest.TestCase):
    def test_catalog_covers_official_groups(self):
        self.assertGreaterEqual(len(conditions.CODE_CATALOG), 48)
        for code in ("JA0101", "JA0102", "JA0110", "JA0111", "JA0201", "JA0205",
                     "JA0302", "JA0328", "JA0411", "JA0412", "JA2101"):
            self.assertIn(code, conditions.CODE_CATALOG)
        groups = {group for group, _label in conditions.CODE_CATALOG.values()}
        self.assertEqual(groups, set(conditions.GROUP_LABELS))

    def test_is_on(self):
        for value in ("Y", "y", 1, True, "1"):
            self.assertTrue(conditions.is_on(value), value)
        for value in ("", None, "N", 0, "0", "0.0", False):
            self.assertFalse(conditions.is_on(value), value)

    def test_normalize_wide_row_keeps_only_known_codes(self):
        row = {"서비스ID": "X", "서비스명": "테스트", "JA0101": "Y", "JA0110": "19.0",
               "JA9999": "Y", "JA0412": ""}
        conds = conditions.normalize_conditions(row)
        self.assertEqual(set(conds), {"JA0101", "JA0110"})
        self.assertEqual(conds["JA0110"], "19.0")

    def test_normalize_accepts_conditions_dict(self):
        conds = conditions.normalize_conditions({"conditions": {"JA0302": "Y", "JA0111": "100"}})
        self.assertEqual(set(conds), {"JA0302", "JA0111"})

    def test_age_range_boundaries(self):
        self.assertEqual(conditions.age_range({"JA0110": "19", "JA0111": "34"})["min_age"], 19)
        self.assertEqual(conditions.age_range({"JA0110": "19", "JA0111": "34"})["max_age"], 34)
        # 0 은 하한 없음
        low = conditions.age_range({"JA0110": "0", "JA0111": "1"})
        self.assertIsNone(low["min_age"])
        self.assertEqual(low["max_age"], 1)
        # 120 은 상한 없음
        high = conditions.age_range({"JA0110": "18", "JA0111": "120"})
        self.assertEqual(high["min_age"], 18)
        self.assertIsNone(high["max_age"])
        # 값이 0 이면 상한도 없음
        zero = conditions.age_range({"JA0110": "18", "JA0111": "0"})
        self.assertIsNone(zero["max_age"])
        # 연령 코드가 없으면 제한 없음
        self.assertFalse(conditions.age_range({})["limited"])

    def test_income_bands_and_percent(self):
        self.assertEqual(conditions.income_bands({"JA0203": "Y", "JA0201": "Y"}),
                         ["JA0201", "JA0203"])
        self.assertEqual(conditions.band_for_percent(0), "JA0201")
        self.assertEqual(conditions.band_for_percent(50), "JA0201")
        self.assertEqual(conditions.band_for_percent(50.5), "JA0202")
        self.assertEqual(conditions.band_for_percent(75), "JA0202")
        self.assertEqual(conditions.band_for_percent(100), "JA0203")
        self.assertEqual(conditions.band_for_percent(200), "JA0204")
        self.assertEqual(conditions.band_for_percent(250), "JA0205")
        self.assertIsNone(conditions.band_for_percent(None))
        self.assertIsNone(conditions.band_for_percent(-1))

    def test_gender_scope(self):
        self.assertEqual(conditions.gender_scope({"JA0102": "Y"}), "female")
        self.assertEqual(conditions.gender_scope({"JA0101": "Y"}), "male")
        self.assertEqual(conditions.gender_scope({"JA0101": "Y", "JA0102": "Y"}), "any")
        self.assertEqual(conditions.gender_scope({}), "any")

    def test_situations_map_to_codes(self):
        self.assertEqual(conditions.codes_for_situations(["pregnant"]),
                         {conditions.GROUP_LIFE: ["JA0302"]})
        mapping = conditions.codes_for_situations(["no_home", "multi_child"])
        self.assertEqual(mapping[conditions.GROUP_HOUSEHOLD], ["JA0412", "JA0411"])
        self.assertEqual(conditions.codes_for_situations(["unknown_key"]), {})
        # 모든 상황 태그의 코드는 카탈로그에 있어야 한다
        for key, spec in conditions.SITUATIONS.items():
            for code in spec["codes"]:
                self.assertIn(code, conditions.CODE_CATALOG, key)

    def test_group_any_codes_are_real(self):
        for codes in conditions.GROUP_ANY_CODES.values():
            for code in codes:
                self.assertIn(code, conditions.CODE_CATALOG)


if __name__ == "__main__":
    unittest.main(verbosity=2)
