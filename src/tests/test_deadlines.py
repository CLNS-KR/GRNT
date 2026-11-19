"""신청기한 자유 텍스트 파서 테스트."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import deadlines  # noqa: E402

TODAY = date(2026, 11, 19)


class DeadlineTest(unittest.TestCase):
    def test_always(self):
        for text in ("상시신청", "상시 신청", "연중", "수시"):
            parsed = deadlines.parse_deadline(text, TODAY)
            self.assertEqual(parsed["state"], deadlines.STATE_ALWAYS, text)

    def test_not_required_and_budget(self):
        self.assertEqual(deadlines.parse_deadline("신청불필요", TODAY)["state"],
                         deadlines.STATE_NOT_REQUIRED)
        for text in ("예산 소진 시까지", "예산소진시", "예산 범위 내"):
            self.assertEqual(deadlines.parse_deadline(text, TODAY)["state"],
                             deadlines.STATE_BUDGET, text)

    def test_range(self):
        parsed = deadlines.parse_deadline("2026. 3. 2. ~ 2026. 12. 31.", TODAY)
        self.assertEqual(parsed["state"], deadlines.STATE_RANGE)
        self.assertEqual(parsed["start_date"], "2026-03-02")
        self.assertEqual(parsed["end_date"], "2026-12-31")
        self.assertEqual(parsed["days_left"], 42)
        self.assertTrue(parsed["closing_soon"] is False)

    def test_single_deadline_and_expired(self):
        parsed = deadlines.parse_deadline("2026-11-30까지", TODAY)
        self.assertEqual(parsed["state"], deadlines.STATE_DEADLINE_ONLY)
        self.assertEqual(parsed["end_date"], "2026-11-30")
        self.assertTrue(parsed["closing_soon"])

        parsed = deadlines.parse_deadline("~ 2026. 1. 31.", TODAY)
        self.assertTrue(parsed.get("expired"))
        self.assertLess(parsed["days_left"], 0)

    def test_free_text_states(self):
        self.assertEqual(deadlines.parse_deadline("접수기관 별 상이", TODAY)["state"],
                         deadlines.STATE_VARIES)
        self.assertEqual(deadlines.parse_deadline("별도 공고기한내", TODAY)["state"],
                         deadlines.STATE_VARIES)
        self.assertEqual(deadlines.parse_deadline("공고 확인", TODAY)["state"],
                         deadlines.STATE_UNKNOWN)
        self.assertEqual(deadlines.parse_deadline("", TODAY)["state"], deadlines.STATE_UNKNOWN)
        self.assertEqual(deadlines.parse_deadline(None, TODAY)["state"], deadlines.STATE_UNKNOWN)

    def test_no_guessing_on_partial_dates(self):
        # 연도 없는 표기는 확정하지 않는다(추측 금지)
        parsed = deadlines.parse_deadline("3. 2. ~ 4. 30.", TODAY)
        self.assertEqual(parsed["state"], deadlines.STATE_UNKNOWN)
        self.assertIsNone(parsed["end_date"])

    def test_sort_key_puts_dated_first(self):
        dated = deadlines.parse_deadline("2026. 1. 2. ~ 2026. 3. 31.", TODAY)
        undated = deadlines.parse_deadline("상시신청", TODAY)
        self.assertLess(deadlines.sort_key(dated), deadlines.sort_key(undated))


if __name__ == "__main__":
    unittest.main(verbosity=2)
