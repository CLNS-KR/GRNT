"""사업자·대리인 리포트(세무사·노무사용) 테스트.

검증하는 것
-----------
1. 규모 판단 — 상시근로자 수·연매출·업종으로 소상공인 기준을 옳게 가르는가
2. 분류·우선순위 — 소상공인/중소기업/고용·노무/정책자금·세제 묶음과 D-7 강조
3. 리포트 조립 — 네 묶음이 고르게 담기고 요약 수치가 서로 맞는가
4. 내보내기 — CSV 열 순서·BOM·수식 주입 방지, 인쇄용 HTML escape
5. 엔드포인트 — 툴 응답과 `/v1/report/*` GET·POST
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import agent_report, api  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.server import make_handler  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402


def _row(**overrides):
    """`_report_row` 에 넣는 판정 결과 1건(엔진 없이 만드는 최소 형태)."""
    base = {
        "service_id": "SMP-1",
        "name": "2026년 소상공인 고용장려금 지원 공고",
        "agency": "중소벤처기업부",
        "support_type": "현금",
        "field_label": "기타",
        "business": {"hashtags": ["소상공인"], "industries": []},
        "business_summary_ko": "소상공인",
        "region": {"level": "nationwide", "label": "전국"},
        "verdict": {"code": "eligible_likely", "label_ko": "받을 가능성 높음"},
        "application": {
            "deadline_text": "2026. 11. 1. ~ 2026. 12. 1.",
            "deadline": {"end_date": "2026-12-01", "days_left": None,
                         "closing_soon": False, "label_ko": "2026.11.1~12.1"},
            "how": "온라인",
        },
        "online_url": "https://example.org/apply",
        "detail_url": "https://example.org/detail",
        "contact": "000-0000-0000",
    }
    base.update(overrides)
    return base


class SizeEstimateTest(unittest.TestCase):
    def test_food_three_employees_two_eok_is_small_business(self):
        size = agent_report.size_estimate("food", 3, 200_000_000, "operating")
        self.assertTrue(size["small_business_likely"])
        self.assertEqual(size["employee_limit"], 5)
        self.assertEqual(size["revenue_limit_krw"], 1_500_000_000)
        self.assertIn("충족할 가능성이 높습니다", size["summary_ko"])

    def test_food_five_employees_fails_five_under_rule(self):
        size = agent_report.size_estimate("food", 5, 200_000_000, "operating")
        self.assertFalse(size["small_business_likely"])
        self.assertTrue(any("5명 미만" in note for note in size["notes_ko"]))

    def test_manufacturing_uses_ten_under_rule(self):
        self.assertTrue(agent_report.size_estimate("manufacturing", 9, 1_000_000_000)
                        ["small_business_likely"])
        self.assertFalse(agent_report.size_estimate("manufacturing", 10, 1_000_000_000)
                         ["small_business_likely"])

    def test_revenue_over_limit_blocks(self):
        size = agent_report.size_estimate("food", 2, 2_000_000_000, "operating")
        self.assertFalse(size["small_business_likely"])
        self.assertTrue(any("연매출" in note for note in size["notes_ko"]))

    def test_employees_ten_or_more_always_out(self):
        size = agent_report.size_estimate("retail", 12, 100_000_000, "operating")
        self.assertFalse(size["small_business_likely"])
        self.assertTrue(any("10명 미만" in note for note in size["notes_ko"]))

    def test_partial_input_says_unknown(self):
        size = agent_report.size_estimate("food", 3, None, "operating")
        self.assertIsNone(size["small_business_likely"])
        self.assertEqual(size["status"], "partial")

    def test_no_input_returns_insufficient(self):
        size = agent_report.size_estimate("food", None, None, "operating")
        self.assertEqual(size["status"], "insufficient_info")
        self.assertIsNone(size["small_business_likely"])

    def test_pre_startup_is_not_judged(self):
        size = agent_report.size_estimate("food", 3, 200_000_000, "pre")
        self.assertEqual(size["status"], "pre_startup")
        self.assertIsNone(size["small_business_likely"])

    def test_basis_cites_law(self):
        size = agent_report.size_estimate("food", 3, 200_000_000, "operating")
        self.assertIn("소상공인기본법", size["basis_ko"])
        self.assertIn("별표 3", size["basis_ko"])


class IndustryResolveTest(unittest.TestCase):
    def test_aliases(self):
        cases = {
            "음식숙박": "food", "음식점": "food", "food": "food",
            "제조": "manufacturing", "제조업": "manufacturing",
            "도소매": "retail", "유통": "retail",
            "IT·서비스": "ict", "it": "ict", "정보통신": "ict",
            "서비스": "service", "건설": "construction",
            "음식·숙박": "food", "정보통신업": "ict",
        }
        for raw, expected in cases.items():
            self.assertEqual(agent_report.resolve_industry(raw), expected, raw)

    def test_unknown_industry_is_none(self):
        self.assertIsNone(agent_report.resolve_industry("우주항공서비스"))
        self.assertIsNone(agent_report.resolve_industry(""))

    def test_startup_input_sets_pre_status(self):
        spec = agent_report._parse_inputs({"industry": "창업"})
        self.assertTrue(spec["startup_only"])
        self.assertEqual(spec["status"], "pre")
        self.assertIsNone(spec["industry"])


class CategoryTest(unittest.TestCase):
    def test_small_business_announcement(self):
        row = _row(name="2026년 소상공인 디지털 전환 지원", business={"hashtags": []},
                   business_summary_ko="소상공인")
        self.assertEqual(agent_report.classify_row(row)[0], agent_report.CATEGORY_SMALL_BUSINESS)

    def test_labor_beats_generic_sme_audience(self):
        row = _row(name="2026년 중소기업 고용장려금 지원 공고", support_type="현금",
                   business_summary_ko="중소기업")
        self.assertEqual(agent_report.classify_row(row)[0], agent_report.CATEGORY_LABOR)

    def test_finance_tax(self):
        row = _row(name="2026년 소상공인 정책자금 융자", business_summary_ko="소상공인")
        self.assertEqual(agent_report.classify_row(row)[0], agent_report.CATEGORY_FINANCE_TAX)

    def test_export_exhibition_is_not_finance(self):
        row = _row(name="2027년 미국 시카고 레스토랑 전시회 한국관 참가기업 모집",
                   business_summary_ko="수출", support_type="기타",
                   business={"hashtags": []})
        self.assertEqual(agent_report.classify_row(row)[0], agent_report.CATEGORY_SME)

    def test_links_are_normalised_and_safe(self):
        def row_link(**overrides):
            return agent_report._report_row(_row(**overrides), size={}, industry=None,
                                            region={})["link"]
        self.assertEqual(row_link(online_url="https://example.org/a", detail_url=""),
                         "https://example.org/a")
        self.assertEqual(row_link(online_url="", detail_url="http://example.org/b"),
                         "http://example.org/b")
        self.assertEqual(row_link(online_url="forms.gle/abc123", detail_url=""),
                         "https://forms.gle/abc123")
        self.assertEqual(row_link(online_url="javascript:alert(1)", detail_url=""), "")
        self.assertEqual(row_link(online_url="", detail_url=""), "")

    def test_priority_marks_d7_and_small_business_fit(self):
        size = agent_report.size_estimate("food", 3, 200_000_000, "operating")
        row = agent_report._report_row(
            _row(application={"deadline_text": "~ 11. 25.", "how": "온라인",
                              "deadline": {"end_date": "2026-11-25", "days_left": 3,
                                           "closing_soon": True, "label_ko": "~11.25"}}),
            size=size, industry="food", region={"level": "nationwide"})
        self.assertEqual(row["d_day"], "D-3")
        self.assertTrue(row["closing_soon"])
        self.assertEqual(row["priority"]["tier"], "high")
        self.assertTrue(any("마감 D-3" in reason for reason in row["priority"]["reasons_ko"]))

    def test_dday_formats(self):
        def labelled(days):
            return agent_report._report_row(
                _row(application={"deadline_text": "", "how": "",
                                  "deadline": {"days_left": days, "label_ko": ""}}),
                size={}, industry=None, region={})["d_day"]
        self.assertEqual(labelled(0), "D-DAY")
        self.assertEqual(labelled(7), "D-7")
        self.assertEqual(labelled(-2), "마감(D+2)")
        self.assertEqual(labelled(None), "미기재")


class ReportBuildTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_scenario_food_three_employees(self):
        report = agent_report.build_report(self.catalog, {
            "sido": "인천광역시", "sigungu": "서해구", "industry": "음식숙박",
            "employees": 3, "annual_revenue_krw": 200_000_000, "biz_years": 4,
        })
        client = report["client"]
        self.assertEqual(client["industry"], "food")
        self.assertEqual(client["industry_label"], "음식·숙박")
        self.assertEqual(client["annual_revenue_label"], "2억 원")
        self.assertEqual(client["region_label"], "인천광역시 서해구")
        self.assertEqual(report["size_estimate"]["status"], "likely_small_business")
        self.assertEqual(report["schema_version"], "1.0")
        self.assertTrue(report["disclaimer_ko"])

    def test_sections_are_ordered_and_consistent(self):
        report = agent_report.build_report(self.catalog, {
            "industry": "food", "employees": 3, "annual_revenue_krw": 200_000_000, "limit": 20,
        })
        slugs = [section["category"] for section in report["sections"]]
        self.assertEqual(slugs, [slug for slug in agent_report.CATEGORY_ORDER if slug in slugs])
        shown = sum(section["count"] for section in report["sections"])
        self.assertEqual(shown, report["summary"]["total"])
        for section in report["sections"]:
            self.assertEqual(section["count"], len(section["rows"]))
            self.assertLessEqual(section["count"], section["available"])
            for row in section["rows"]:
                self.assertEqual(row["category"], section["category"])
        self.assertLessEqual(report["summary"]["total"], 20)

    def test_interest_filter(self):
        report = agent_report.build_report(self.catalog, {
            "industry": "food", "employees": 3,
            "interest": ["small_business", "sme"], "limit": 20,
        })
        slugs = [section["category"] for section in report["sections"]]
        self.assertTrue(slugs)
        for slug in slugs:
            self.assertIn(slug, ("small_business", "sme"))
        self.assertEqual(set(report["summary"]["by_category"]), {"small_business", "sme"})

    def test_d7_rows_are_within_seven_days(self):
        report = agent_report.build_report(self.catalog, {"industry": "food", "employees": 3,
                                                          "limit": 40})
        for row in report["d7"]:
            self.assertIsNotNone(row["days_left"])
            self.assertGreaterEqual(row["days_left"], 0)
            self.assertLessEqual(row["days_left"], agent_report.D7_DAYS)

    def test_meta_or_missing_inputs_do_not_crash(self):
        report = agent_report.build_report(self.catalog, {})
        self.assertEqual(report["client"]["industry_label"], "미지정")
        self.assertEqual(report["size_estimate"]["status"], "insufficient_info")
        self.assertIn("sections", report)

    def test_pre_startup_report(self):
        report = agent_report.build_report(self.catalog, {"industry": "창업", "limit": 10})
        self.assertEqual(report["client"]["biz_status"], "pre")
        self.assertEqual(report["size_estimate"]["status"], "pre_startup")
        self.assertTrue(any("예비창업자" in note for note in report["notes_ko"]))

    def test_revenue_from_eok_and_string(self):
        self.assertEqual(agent_report._revenue_krw({"annual_revenue_eok": 2}), 200_000_000)
        self.assertEqual(agent_report._revenue_krw({"annual_revenue": "3억"}), 300_000_000)
        self.assertEqual(agent_report._revenue_krw({"annual_revenue_krw": "1,500,000,000"}),
                         1_500_000_000)

    def test_markdown_summary_mentions_groups(self):
        report = agent_report.build_report(self.catalog, {"industry": "food", "employees": 3,
                                                          "limit": 20})
        text = agent_report.to_markdown(report)
        self.assertIn("후보", text)
        self.assertIn("마감임박", text)


class CsvExportTest(unittest.TestCase):
    def _report(self):
        return agent_report.build_report(sample_catalog(),
                                         {"industry": "food", "employees": 3, "limit": 12})

    def test_header_and_bom(self):
        text = agent_report.to_csv(self._report())
        self.assertTrue(text.startswith("\ufeff"))
        lines = text.split("\r\n")
        self.assertIn("GRNT 사업자·대리인 리포트", lines[0])
        self.assertEqual(lines[2].split(",")[:7],
                         ["구분", "공고명", "소관기관", "지원유형", "마감일", "D-day", "신청 링크"])

    def test_row_count_matches_report(self):
        csv_module = __import__("csv")
        report = self._report()
        text = agent_report.to_csv(report)
        rows = list(csv_module.reader(text.lstrip("\ufeff").splitlines()))
        data = [row for row in rows[3:] if len(row) > 2 and row[1]]
        expected = sum(section["count"] for section in report["sections"])
        self.assertEqual(len(data), expected)

    def test_formula_injection_is_neutralised(self):
        report = {
            "checked_at": "2026-11-20T10:00:00+09:00",
            "client": {"industry_label": "음식·숙박", "employees": 3,
                       "annual_revenue_label": "2억 원", "region_label": "전국"},
            "disclaimer_ko": "참고용",
            "sections": [{
                "category": "labor", "category_label": "고용·노무", "count": 1,
                "rows": [_row(name='=HYPERLINK("http://x","x")')],
            }],
        }
        text = agent_report.to_csv(report)
        self.assertIn("'=HYPERLINK", text)

    def test_filename_has_no_identifiers(self):
        report = self._report()
        name = agent_report.filename_for(report, "csv")
        self.assertTrue(name.startswith("grnt-report-"))
        self.assertTrue(name.endswith(".csv"))
        self.assertNotIn(" ", name)


class PrintViewTest(unittest.TestCase):
    def test_escapes_user_content(self):
        report = {
            "checked_at": "2026-11-20T10:00:00+09:00",
            "client": {"industry_label": "음식·숙박", "employees": 3,
                       "annual_revenue_label": "2억 원", "region_label": "인천광역시 서해구",
                       "entity_label": "소상공인", "biz_years": 4},
            "size_estimate": {"summary_ko": "기준 충족"},
            "summary": {"total": 1, "d7_count": 1},
            "disclaimer_ko": "참고용 사전 점검",
            "notes_ko": ["업종을 고르면 정확해집니다."],
            "sections": [{
                "category": "labor", "category_label": "<script>alert(1)</script>",
                "duty_ko": "노무 담당", "count": 1,
                "rows": [_row(name="<img src=x onerror=alert(1)>",
                              agency="<b>기관</b>",
                              link='javascript:alert(1)',
                              online_url='javascript:alert(1)')],
            }],
        }
        html = agent_report.to_print_html(report)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;b&gt;기관&lt;/b&gt;", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("@import", html)

    def test_print_view_has_tables(self):
        report = agent_report.build_report(sample_catalog(),
                                           {"industry": "food", "employees": 3, "limit": 12})
        html = agent_report.to_print_html(report)
        self.assertIn("<!doctype html>", html)
        self.assertIn("@media print", html)
        self.assertIn("공고명", html)
        self.assertIn("참고용 사전 점검", html)
        self.assertIn("소상공인 담당", html)

    def test_print_view_shows_d7_when_present(self):
        report = agent_report.build_report(sample_catalog(),
                                           {"industry": "food", "employees": 3, "limit": 12})
        soon = agent_report._report_row(
            _row(application={"deadline_text": "~ 11. 24.", "how": "온라인",
                              "deadline": {"end_date": "2026-11-24", "days_left": 2,
                                           "closing_soon": True, "label_ko": "~11.24"}}),
            size={}, industry=None, region={})
        report["d7"] = [soon]
        html = agent_report.to_print_html(report)
        self.assertIn("마감 임박(D-7)", html)
        self.assertIn("D-2", html)


class ToolTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_tool_is_registered(self):
        names = [definition["name"] for definition in api.TOOL_DEFS]
        self.assertIn("business_report", names)

    def test_call_returns_envelope(self):
        result = api.call_tool("business_report", {
            "industry": "음식숙박", "employees": 3, "annual_revenue_krw": 200_000_000,
            "limit": 12,
        }, self.catalog, store=self.store)
        self.assertTrue(result["ok"])
        payload = result["result"]
        self.assertEqual(result["tool"], "business_report")
        self.assertIn("catalog", payload)
        self.assertIn("checked_at", payload)
        self.assertEqual(payload["export"]["csv_url"], "/v1/report/export.csv")
        self.assertEqual(payload["export"]["print_url"], "/v1/report/print.html")
        self.assertTrue(payload["summary_ko"])

    def test_call_handles_empty_arguments(self):
        result = api.call_tool("business_report", {}, self.catalog, store=self.store)
        self.assertTrue(result["ok"])
        payload = result["result"]
        self.assertEqual(payload["size_estimate"]["status"], "insufficient_info")
        self.assertIn("sections", payload)
        self.assertEqual(payload["summary"]["total"],
                         sum(section["count"] for section in payload["sections"]))

    def test_export_csv_helper(self):
        export = api.report_export({"industry": "food", "employees": 3, "limit": 5},
                                   self.catalog, "csv")
        self.assertIn("text/csv", export["content_type"])
        self.assertFalse(export["inline"])
        self.assertTrue(export["body"].startswith("\ufeff"))

    def test_export_print_helper(self):
        export = api.report_export({"industry": "food", "employees": 3, "limit": 5},
                                   self.catalog, "html")
        self.assertIn("text/html", export["content_type"])
        self.assertTrue(export["inline"])
        self.assertIn("<!doctype html>", export["body"])

    def test_service_meta_lists_tool(self):
        result = api.call_tool("get_service_meta", {}, self.catalog, store=self.store)
        self.assertIn("business_report", result["result"]["tools"])

    def test_text_summary_is_human_readable(self):
        result = api.call_tool("business_report", {
            "industry": "음식숙박", "employees": 3, "annual_revenue_krw": 200_000_000,
            "limit": 12,
        }, self.catalog, store=self.store)
        text = api.text_summary(result)
        self.assertIn("후보", text)
        self.assertIn("마감임박", text)
        self.assertNotIn("결과 0건", text)


class HttpReportExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.store = Store(":memory:")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.catalog, cls.store))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.read().decode("utf-8"), dict(response.headers)

    def _post_raw(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                         method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8"), dict(response.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), dict(exc.headers)

    def test_get_csv_with_query(self):
        query = urllib.parse.urlencode({
            "industry": "음식숙박", "employees": 3, "annual_revenue_krw": 200000000, "limit": 8,
        })
        status, body, headers = self._get("/v1/report/export.csv?" + query)
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers["Content-Type"])
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("noindex", headers["X-Robots-Tag"])
        self.assertIn("공고명", body)

    def test_get_print_inline(self):
        query = urllib.parse.urlencode({"industry": "food", "employees": 3, "limit": 5})
        status, body, headers = self._get("/v1/report/print.html?" + query)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("inline", headers["Content-Disposition"])
        self.assertIn("<!doctype html>", body)

    def test_post_body_matches_tool(self):
        payload = {"industry": "food", "employees": 3, "interest": ["small_business"],
                   "limit": 6}
        status, body, headers = self._post_raw("/v1/report/export.csv", payload)
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers["Content-Type"])
        self.assertIn("소상공인", body)
        self.assertNotIn("정책자금·세제", body)

    def test_bad_json_is_400(self):
        url = f"http://127.0.0.1:{self.port}/v1/report/export.csv"
        request = urllib.request.Request(url, data=b"{not json", method="POST",
                                         headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    def test_web_page_has_agent_tab_and_export_buttons(self):
        status, body, _ = self._get("/")
        self.assertEqual(status, 200)
        for marker in ('value="agent"', 'id="agent-fields"', 'id="agent_employees"',
                       'name="interest"', 'id="report-card"', "/v1/report/export.csv"):
            self.assertIn(marker, body)


if __name__ == "__main__":
    unittest.main()
