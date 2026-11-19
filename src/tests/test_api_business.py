"""창업·기업 트랙 API 툴 테스트 — deadline_calendar · compare_ledgers · meta."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import api, snapshots  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402

BUSINESS_PROFILE = {
    "track": "business", "age": 33, "sex": "male",
    "region": {"sido": "인천광역시", "sigungu": "서구"},
    "business": {"status": "pre", "entity": "pre_startup"},
}


class BusinessToolTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()
        self.store = Store(":memory:")
        self.tmp = tempfile.mkdtemp()
        self._env = os.environ.get("SUBSIDY_KR_DATA")
        os.environ["SUBSIDY_KR_DATA"] = self.tmp

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._env is None:
            os.environ.pop("SUBSIDY_KR_DATA", None)
        else:
            os.environ["SUBSIDY_KR_DATA"] = self._env

    def call(self, name, args):
        return api.call_tool(name, args, self.catalog, store=self.store)

    # --- search --------------------------------------------------------
    def test_business_search_envelope(self):
        out = self.call("search_subsidies", {"profile": BUSINESS_PROFILE, "limit": 5})
        self.assertTrue(out["ok"])
        result = out["result"]
        self.assertEqual(result["track"], "business")
        self.assertEqual(result["track_counts"]["personal"], 0)
        self.assertIn("track_note_ko", result)
        self.assertTrue(result["results"])
        first = result["results"][0]
        self.assertEqual(first["track"], "business")
        self.assertIn("business_summary_ko", first)
        self.assertIn("attribution_ko", first)

    def test_all_track_without_business_info_is_personal_only(self):
        out = self.call("search_subsidies", {"profile": {"age": 30, "income_band": "JA0203",
                                                         "situations": []}})
        self.assertEqual(out["result"]["track_counts"]["business"], 0)
        self.assertIn("track_note_ko", out["result"])

    def test_include_closed(self):
        profile = dict(BUSINESS_PROFILE,
                       region={"sido": "경기도", "sigungu": "수원시 장안구"},
                       business={"status": "operating", "entity": "sme", "years": 2})
        open_only = self.call("search_subsidies", {"profile": profile,
                                                   "include_closed": False, "limit": 20})
        self.assertGreater(open_only["result"]["closed_hidden"], 0)
        with_closed = self.call("search_subsidies", {"profile": profile,
                                                     "include_closed": True, "limit": 20})
        self.assertIn("경기도 스타트업",
                      " ".join(row["name"] for row in with_closed["result"]["results"]))

    def test_flat_business_args(self):
        out = self.call("search_subsidies", {"track": "business", "age": 33,
                                             "biz_status": "pre", "sido": "인천광역시"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["profile"]["business"]["status"], "pre")

    # --- deadline_calendar --------------------------------------------
    def test_deadline_calendar_orders_by_date(self):
        out = self.call("deadline_calendar", {"days": 90, "track": "business"})
        self.assertTrue(out["ok"])
        result = out["result"]
        self.assertGreater(result["total"], 0)
        dates = [row["date"] for row in result["calendar"]]
        self.assertEqual(dates, sorted(dates))
        for day in result["calendar"]:
            self.assertIn(day["weekday_ko"], "월화수목금토일")
            for service in day["services"]:
                self.assertGreaterEqual(service["days_left"], 0)
        self.assertGreater(result["without_date_count"], 0)   # 상시·예산소진 등

    def test_deadline_calendar_track_filter(self):
        personal = self.call("deadline_calendar", {"days": 120, "track": "personal"})
        tracks = {service["track"] for day in personal["result"]["calendar"]
                  for service in day["services"]}
        self.assertEqual(tracks, {"personal"})

    def test_deadline_calendar_limit(self):
        out = self.call("deadline_calendar", {"days": 120, "limit": 2})
        shown = sum(day["count"] for day in out["result"]["calendar"])
        self.assertLessEqual(shown, 2)

    def test_deadline_calendar_region_filter(self):
        out = self.call("deadline_calendar", {"days": 120, "sido": "인천광역시",
                                              "sigungu": "서구", "track": "business"})
        names = [service["name"] for day in out["result"]["calendar"]
                 for service in day["services"]]
        self.assertNotIn("2026년 경기도 스타트업 육성 지원", names)

    # --- compare_ledgers ----------------------------------------------
    def _write_snapshot(self, day, services):
        payload = snapshots.build_snapshot(services, day)
        snapshots.save_snapshot(payload, snapshots.snapshot_dir(self.tmp))

    def test_compare_ledgers_without_snapshots(self):
        out = self.call("compare_ledgers", {})
        self.assertTrue(out["ok"])
        self.assertIn("스냅샷", out["result"]["reason_ko"])
        self.assertEqual(out["result"]["available_days"], [])

    def test_compare_ledgers_reports_changes(self):
        services = self.catalog.services
        self._write_snapshot("2026-11-01", services)
        changed = []
        for service in services:
            if service.service_id == "KSU-900001":
                from subsidy_kr.catalog import normalize_service

                raw = {**service.summary(detail=True), "business": service.business}
                raw["지원내용"] = "사업화 자금 최대 1억 5천만 원(예시)"
                raw["source"] = service.source
                raw["track"] = service.track
                changed.append(normalize_service(raw, source=service.source))
            else:
                changed.append(service)
        self._write_snapshot("2026-11-02", changed)

        out = self.call("compare_ledgers", {"from_date": "2026-11-01",
                                            "to_date": "2026-11-02"})
        self.assertTrue(out["ok"])
        result = out["result"]
        self.assertEqual(result["counts"]["changed"], 1)
        self.assertEqual(result["changed"][0]["service_id"], "KSU-900001")
        self.assertIn("amount", result["changed"][0]["changes"])
        self.assertIn("summary_ko", result)

    def test_compare_ledgers_single_service(self):
        services = self.catalog.services
        self._write_snapshot("2026-11-01", services[:-1])
        self._write_snapshot("2026-11-02", services)
        out = self.call("compare_ledgers", {"service_id": "KSU-900006"})
        self.assertTrue(out["ok"])
        self.assertLessEqual(out["result"]["counts"]["added"], 1)

    # --- meta / region -------------------------------------------------
    def test_meta_describes_tracks_and_sources(self):
        result = self.call("get_service_meta", {})["result"]
        keys = [row["key"] for row in result["tracks"]]
        self.assertEqual(keys, ["personal", "business"])
        labels = [row["label_ko"] for row in result["sources"]]
        self.assertIn("창업진흥원 K-Startup", labels)
        self.assertIn("business_entities", result)
        self.assertIn("business", result["profile_fields"])
        self.assertEqual(result["service"], "GRNT")

    def test_list_region_track_filter(self):
        out = self.call("list_region_subsidies", {"sido": "인천광역시", "track": "business"})
        self.assertTrue(out["ok"])
        self.assertTrue(all(row["track"] == "business"
                            for row in out["result"]["services"]))
        self.assertEqual(out["result"]["track"], "business")

    def test_profile_schema_has_track_and_business(self):
        props = api.PROFILE_SCHEMA["properties"]
        self.assertIn("track", props)
        self.assertIn("business", props)
        self.assertIn("status", props["business"]["properties"])

    def test_text_summary_for_new_tools(self):
        calendar = self.call("deadline_calendar", {"days": 30})
        text = api.text_summary(calendar)
        self.assertIn("마감 임박", text)
        missing = self.call("compare_ledgers", {})
        self.assertIn("스냅샷", api.text_summary(missing))


if __name__ == "__main__":
    unittest.main(verbosity=2)
