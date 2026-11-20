"""0건 검색어 집계 — 비식별 처리·저장·노출 회귀 테스트.

핵심 원칙
- 검색어는 **결과가 0건일 때만** 남긴다(결과가 있던 검색어는 저장하지 않는다).
- 남길 때는 전화번호·주민번호·이메일·URL·@핸들·2자리 이상 숫자·지역명을 지운다.
- 나이·소득구간·임신 여부 같은 프로필 입력값은 읽지도 저장하지도 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import api, usage  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402

KST = timezone(timedelta(hours=9))


def _day(offset: int = 0) -> str:
    return (datetime.now(KST) + timedelta(days=offset)).strftime("%Y-%m-%d")


class SanitizeQueryTest(unittest.TestCase):
    def test_phone_email_rrn_handle_removed(self):
        email = "someone" + "@" + "example.com"
        for raw, must_not in (
            ("010-1234-5678 청년 월세", ("010", "1234", "5678")),
            (email + " 전세 지원", ("someone", "example.com", "@")),
            ("900101-1234567 무주택", ("900101", "1234567")),
            ("@handle 지원금 문의", ("@handle", "handle")),
            ("https://example.com 청년", ("example.com", "http")),
        ):
            cleaned = usage.sanitize_query(raw)
            for token in must_not:
                self.assertNotIn(token, cleaned, f"{raw!r} → {cleaned!r}")

    def test_numbers_masked(self):
        self.assertNotIn("1992", usage.sanitize_query("1992년생 청년 지원"))
        self.assertNotIn("34", usage.sanitize_query("34살 청년 월세"))
        # 한 글자 숫자는 뜻이 있어 남긴다('1인 가구')
        self.assertIn("1인", usage.sanitize_query("1인 가구 지원"))

    def test_region_names_removed(self):
        for raw in ("인천 서구 청년 월세", "인천광역시 청년", "강남구 소상공인 대출",
                    "수원시 청년 월세", "인천서구 청년도약", "서울시 청년수당"):
            cleaned = usage.sanitize_query(raw)
            for token in ("인천", "서구", "강남", "수원", "서울"):
                self.assertNotIn(token, cleaned, f"{raw!r} → {cleaned!r}")

    def test_region_only_query_is_dropped(self):
        self.assertEqual(usage.sanitize_query("인천 서구"), "")
        self.assertEqual(usage.sanitize_query("서울특별시"), "")

    def test_common_words_are_not_mangled(self):
        # '무주택'의 '무주(茂朱)' 같은 지역명 조각으로 낱말을 훼손하지 않는다
        cleaned = usage.sanitize_query("무주택 청년 전세")
        self.assertIn("무주택", cleaned)
        self.assertIn("전세", cleaned)

    def test_length_capped(self):
        cleaned = usage.sanitize_query("청년" * 40)
        self.assertLessEqual(len(cleaned), usage.MAX_QUERY_CHARS)
        self.assertTrue(cleaned)

    def test_empty_and_noise_return_blank(self):
        for raw in ("", "   ", "12345", "@@@", None):
            self.assertEqual(usage.sanitize_query(raw), "")

    def test_key_roundtrip_and_tag_whitelist(self):
        key = usage.zero_query_key("청년 월세", "personal", "housing")
        self.assertEqual(usage.zero_entry(key), ("청년 월세", "personal", "housing"))
        # 카탈로그가 모르는 분야 문자열은 버린다(임의 문자열 유입 차단)
        self.assertEqual(usage.zero_entry(usage.zero_query_key("월세", "personal", "임의값")),
                         ("월세", "personal", ""))
        # 트랙도 아는 값만
        self.assertEqual(usage.zero_entry(usage.zero_query_key("월세", "hacked"))[1], "all")


class RecordZeroQueryTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def _rows(self):
        cur = self.store.conn.execute(
            "SELECT day, kind, key, count FROM usage_daily WHERE kind = ?",
            (usage.KIND_ZERO_QUERY,))
        return [dict(row) for row in cur.fetchall()]

    def test_zero_result_records_sanitized_query(self):
        result = {"ok": True, "tool": "search_subsidies",
                  "result": {"counts": {"eligible_likely": 0, "check_needed": 0},
                             "track": "personal", "results": []}}
        usage.record_tool(self.store, "search_subsidies", result,
                          {"keyword": "010-1234-5678 인천 서구 청년 1992",
                           "tag": "housing"})
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        entry = json.loads(rows[0]["key"])
        self.assertEqual(entry["q"], "청년")
        self.assertEqual(entry["t"], "personal")
        self.assertEqual(entry["g"], "housing")

    def test_field_inferred_without_tag(self):
        """분야를 고르지 않은 검색도 검색어에서 분야를 추론해 남긴다."""
        result = {"ok": True, "result": {"counts": {}, "track": "personal", "results": []}}
        usage.record_tool(self.store, "search_subsidies", result, {"keyword": "월세 보조금"})
        rows = self._rows()
        self.assertEqual(json.loads(rows[0]["key"])["g"], "housing")
        stats = usage.stats_payload(self.store, days=1)
        top = stats["zero_result_queries"]["top"][0]
        self.assertEqual(top["field"], "housing")
        self.assertEqual(top["field_label"], "주거·월세·전세")

    def test_results_present_records_nothing(self):
        result = {"ok": True, "tool": "search_subsidies",
                  "result": {"counts": {"eligible_likely": 3, "check_needed": 1},
                             "track": "personal", "results": [{"name": "x"}]}}
        usage.record_tool(self.store, "search_subsidies", result, {"keyword": "청년 월세"})
        self.assertEqual(self._rows(), [])

    def test_errors_do_not_record_query(self):
        result = {"ok": False, "error": "invalid_argument", "tool": "search_subsidies"}
        usage.record_tool(self.store, "search_subsidies", result, {"keyword": "청년 월세"})
        self.assertEqual(self._rows(), [])

    def test_same_query_accumulates_count(self):
        result = {"ok": True, "result": {"counts": {}, "track": "personal", "results": []}}
        for _ in range(3):
            usage.record_tool(self.store, "search_subsidies", result, {"keyword": "청년 월세"})
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 3)

    def test_no_keyword_records_nothing(self):
        result = {"ok": True, "result": {"count": 0, "track": "all"}}
        usage.record_tool(self.store, "list_region_subsidies", result, {"sido": "인천광역시"})
        self.assertEqual(self._rows(), [])


class CallToolPrivacyTest(unittest.TestCase):
    """실제 툴 호출 — 프로필 입력값이 통계에 새지 않는지 확인한다."""

    def setUp(self):
        self.catalog = sample_catalog()
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def _stored_text(self) -> str:
        cur = self.store.conn.execute("SELECT day || '|' || kind || '|' || key FROM usage_daily")
        return "\n".join(row[0] for row in cur.fetchall())

    def test_zero_result_search_stores_no_profile_values(self):
        profile = {"age": 34, "birth_year": 1992, "income_band": "JA0203",
                   "region": {"sido": "인천광역시", "sigungu": "서구"},
                   "situations": ["pregnant"]}
        result = api.call_tool("search_subsidies",
                               {"profile": profile,
                                "keyword": "1992년생 인천 서구 임산부 34살 특별지원"},
                               self.catalog, store=self.store)
        self.assertEqual(result.get("ok"), True)
        self.assertEqual((result.get("result") or {}).get("counts", {}).get("eligible_likely"), 0)
        stored = self._stored_text()
        self.assertIn("zero_query", stored)
        for leaked in ("1992", "JA0203", "인천", "서구", "pregnant", "34"):
            self.assertNotIn(leaked, stored, leaked)
        self.assertNotIn("임산부 34", stored)

    def test_matching_search_is_not_stored(self):
        result = api.call_tool("search_subsidies",
                               {"profile": {"age": 34, "income_band": "JA0203",
                                            "situations": ["no_home"]},
                                "keyword": "월세"},
                               self.catalog, store=self.store)
        counts = (result.get("result") or {}).get("counts") or {}
        self.assertGreater(counts.get("eligible_likely", 0), 0)
        self.assertNotIn("zero_query", self._stored_text())


class StatsPayloadTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def _bump(self, query, count=1, track="personal", tag="", day=None, kind=None):
        self.store.bump_usage(day or _day(), kind or usage.KIND_ZERO_QUERY,
                              usage.zero_query_key(query, track, tag), count)

    def test_per_day_top_list_sorted_and_capped(self):
        for index in range(25):
            self._bump(f"검색어{index:02d}", count=1)
        self._bump("자주찾는말", count=7, tag="housing")
        stats = usage.stats_payload(self.store, days=1)
        day = stats["days"][-1]
        block = day["zero_result_queries"]
        self.assertEqual(len(block["top"]), usage.TOP_ZERO_QUERIES)
        self.assertEqual(block["distinct"], 26)
        self.assertEqual(block["total"], 32)
        self.assertEqual(block["top"][0]["query"], "자주찾는말")
        self.assertEqual(block["top"][0]["field_label"], "주거·월세·전세")
        counts = [row["count"] for row in block["top"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(stats["zero_result_queries"]["distinct"], 26)
        self.assertEqual(stats["zero_result_queries"]["total"], 32)

    def test_days_are_separated(self):
        self._bump("어제검색", day=_day(-1))
        self._bump("오늘검색", day=_day())
        stats = usage.stats_payload(self.store, days=2)
        yesterday, today = stats["days"]
        self.assertEqual([row["query"] for row in yesterday["zero_result_queries"]["top"]],
                         ["어제검색"])
        self.assertEqual([row["query"] for row in today["zero_result_queries"]["top"]],
                         ["오늘검색"])
        self.assertEqual(stats["zero_result_queries"]["distinct"], 2)

    def test_existing_shape_is_kept(self):
        self.store.bump_usage(_day(), usage.KIND_PATH, "/healthz", 2)
        stats = usage.stats_payload(self.store, days=1)
        for key in ("ok", "generated_at", "timezone", "window_days", "from", "to",
                    "privacy", "days", "totals"):
            self.assertIn(key, stats)
        day = stats["days"][0]
        for key in ("date", "requests", "paths", "tools", "verdicts", "flags"):
            self.assertIn(key, day)
        self.assertEqual(stats["totals"]["paths"]["/healthz"], 2)
        for key in ("stores_ip", "stores_user_agent", "stores_cookies",
                    "stores_profile", "stores_identifiers"):
            self.assertFalse(stats["privacy"][key], key)

    def test_privacy_block_declares_zero_result_only(self):
        privacy = usage.stats_payload(None, days=1)["privacy"]
        self.assertEqual(privacy["stores_search_terms"], "zero_result_only")
        self.assertEqual(privacy["zero_result_queries"]["max_chars"], usage.MAX_QUERY_CHARS)
        self.assertTrue(privacy["zero_result_queries"]["results_are_not_stored"])
        self.assertIn("시·도", "".join(privacy["zero_result_queries"]["removed_ko"]))

    def test_corrupt_keys_are_ignored(self):
        self.store.bump_usage(_day(), usage.KIND_ZERO_QUERY, "not-json", 5)
        self.store.bump_usage(_day(), usage.KIND_ZERO_QUERY, json.dumps({"q": ""}), 2)
        stats = usage.stats_payload(self.store, days=1)
        self.assertEqual(stats["zero_result_queries"]["total"], 0)

    def test_unknown_kind_rows_do_not_break_stats(self):
        self.store.bump_usage(_day(), "weird_kind", "x", 1)
        stats = usage.stats_payload(self.store, days=1)
        self.assertTrue(stats["ok"])
        self.assertEqual(stats["days"][0]["zero_result_queries"]["top"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
