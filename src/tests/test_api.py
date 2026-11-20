"""툴 9종(JSON API) 테스트."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import api  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402


class ToolRegistryTest(unittest.TestCase):
    def test_tool_registry_with_schemas(self):
        self.assertEqual(len(api.TOOL_DEFS), 9)
        names = [definition["name"] for definition in api.TOOL_DEFS]
        self.assertEqual(names, ["search_subsidies", "check_eligibility", "get_subsidy_detail",
                                 "list_region_subsidies", "deadline_calendar",
                                 "compare_ledgers", "business_report",
                                 "batch_match_clients", "get_service_meta"])
        for definition in api.TOOL_DEFS:
            self.assertTrue(definition["title_ko"])
            self.assertTrue(definition["description_ko"])
            self.assertEqual(definition["input_schema"]["type"], "object")

    def test_mcp_tools_have_annotations(self):
        tools = api.mcp_tools()
        self.assertEqual(len(tools), 9)
        for tool in tools:
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            self.assertIn("inputSchema", tool)

    def test_manifest(self):
        manifest = api.mcp_manifest()
        self.assertEqual(manifest["name"], "grnt")
        self.assertEqual(len(manifest["tools"]), 9)


class ToolCallTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def _call(self, name, args):
        return api.call_tool(name, args, self.catalog, store=self.store)

    def test_search_envelope(self):
        out = self._call("search_subsidies", {"profile": {
            "age": 34, "region": {"sido": "인천광역시", "sigungu": "서구"},
            "income_band": "JA0203", "situations": ["no_home"]}})
        self.assertTrue(out["ok"])
        result = out["result"]
        for key in ("profile", "counts", "results", "next_questions", "catalog",
                    "checked_at", "disclaimer_ko", "scope_limits_ko"):
            self.assertIn(key, result)
        self.assertEqual(result["catalog"]["catalog_state"], "sample")
        self.assertEqual(sum(result["counts"].values()), result["scanned"])

    def test_search_with_flat_args(self):
        out = self._call("search_subsidies", {"age": 34, "sido": "인천광역시",
                                              "sigungu": "서구", "income_percent": 80,
                                              "situations": ["no_home"]})
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["profile"]["income_band"], "JA0203")

    def test_search_empty_profile_returns_questions(self):
        out = self._call("search_subsidies", {"profile": {}})
        self.assertTrue(out["ok"])
        keys = {item["key"] for item in out["result"]["next_questions"]}
        self.assertIn("age", keys)
        self.assertIn("region", keys)

    def test_check_eligibility(self):
        out = self._call("check_eligibility", {
            "service_id": "SMP-0001",
            "profile": {"age": 34, "income_band": "JA0203",
                        "situations": ["no_home", "worker"]}})
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["service"]["verdict"]["code"], "eligible_likely")
        self.assertIn("summary_ko", out["result"])

    def test_check_eligibility_errors(self):
        self.assertEqual(self._call("check_eligibility", {})["error"], "invalid_argument")
        missing = self._call("check_eligibility", {"service_id": "NOPE", "profile": {}})
        self.assertEqual(missing["ok"], False)
        self.assertEqual(missing["message"], "service_not_found")

    def test_detail_and_missing_criteria(self):
        out = self._call("get_subsidy_detail", {"service_id": "SMP-0015"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["criteria_state"], "missing")
        self.assertIn("확인", out["result"]["criteria_note_ko"])
        service = out["result"]["service"]
        self.assertEqual(service["region"]["sigungu"], "서해구")
        self.assertTrue(service["documents"])

    def test_detail_with_profile_adds_verdict(self):
        out = self._call("get_subsidy_detail", {
            "service_id": "SMP-0001",
            "profile": {"age": 34, "income_band": "JA0203", "situations": ["no_home"]}})
        self.assertEqual(out["result"]["verdict"]["code"], "eligible_likely")
        self.assertTrue(out["result"]["why"])

    def test_list_region(self):
        out = self._call("list_region_subsidies", {"sido": "인천광역시", "sigungu": "서구"})
        self.assertTrue(out["ok"])
        self.assertGreater(out["result"]["count"], 0)
        self.assertGreater(out["result"]["local_count"], 0)
        names = [row["name"] for row in out["result"]["services"]]
        self.assertIn("인천광역시 서구 청년월세 지원", names)

    def test_list_region_errors(self):
        self.assertEqual(self._call("list_region_subsidies", {})["error"], "invalid_argument")
        self.assertEqual(self._call("list_region_subsidies", {"sigungu": "서구"})["message"],
                         "region_unresolved")

    def test_meta(self):
        out = self._call("get_service_meta", {})
        self.assertTrue(out["ok"])
        result = out["result"]
        self.assertEqual(len(result["verdicts"]), 4)
        self.assertGreaterEqual(len(result["situations"]), 20)
        self.assertFalse(result["privacy"]["stores_profile"])
        self.assertEqual(result["tools"], [d["name"] for d in api.TOOL_DEFS])

    def test_unknown_tool(self):
        out = self._call("nope", {})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "unknown_tool")

    def test_tool_calls_are_counted_anonymously(self):
        self._call("get_service_meta", {})
        rows = self.store.usage_rows("2000-01-01", "2100-01-01")
        kinds = {(row["kind"], row["key"]) for row in rows}
        self.assertIn(("tool", "get_service_meta"), kinds)

    def test_text_summary(self):
        out = self._call("search_subsidies", {"profile": {
            "age": 34, "income_band": "JA0203", "situations": ["no_home"]}})
        text = api.text_summary(out)
        self.assertIn("후보", text)
        self.assertIn("청년월세", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
