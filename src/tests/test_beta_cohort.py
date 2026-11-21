"""0.4.4 — 무료 베타 파일럿 구분 태그(`cohort`/`source`) 회귀 테스트.

`POST /v1/inquiry` 에 **선택** 필드 `cohort`(별칭 `source`)를 더했다. 무료 베타 테스터나
소개 글(CiteChart 등)에서 들어온 문의를 나중에 셀 수 있게 하는 값이며, 없으면 종전 요청과
100% 같게 동작해야 한다. 이 파일은 (1) 하위 호환, (2) 저장ㆍ미러ㆍ알림ㆍ운영 요약까지의
전달, (3) 연락처ㆍ판정 입력이 새 경로로 새지 않는 점을 고정한다.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from subsidy_kr import api, usage  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.server import make_handler  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402

CONTACT = "beta" + "@" + "grnt.test"
MESSAGE = "베타 파일럿으로 거래처 40곳을 돌려봤습니다"
PHONE = "010" + "-1111-2222"

OLD_SCHEMA = """
CREATE TABLE inquiries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    topic      TEXT NOT NULL,
    contact    TEXT NOT NULL,
    message    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


class CohortNormalizeTest(unittest.TestCase):
    def test_absent_tag_is_empty(self):
        for payload in ({"contact": CONTACT, "topic": "batch_report"},
                        {"contact": CONTACT, "topic": "other", "cohort": ""},
                        {"contact": CONTACT, "topic": "other", "cohort": "   "},
                        {"contact": CONTACT, "topic": "other", "cohort": None}):
            with self.subTest(payload=payload):
                clean, error = usage.normalize_inquiry(payload)
                self.assertIsNone(error)
                self.assertEqual(clean["cohort"], "")

    def test_cohort_and_source_alias(self):
        clean, error = usage.normalize_inquiry(
            {"contact": CONTACT, "topic": "api_mcp", "cohort": "Beta_Pilot"})
        self.assertIsNone(error)
        self.assertEqual(clean["cohort"], "beta_pilot")
        clean, error = usage.normalize_inquiry(
            {"contact": CONTACT, "topic": "api_mcp", "source": "citechart"})
        self.assertIsNone(error)
        self.assertEqual(clean["cohort"], "citechart")

    def test_cohort_wins_over_source(self):
        clean, _error = usage.normalize_inquiry(
            {"contact": CONTACT, "topic": "other", "cohort": "beta_pilot", "source": "citechart"})
        self.assertEqual(clean["cohort"], "beta_pilot")

    def test_length_boundary(self):
        clean, error = usage.normalize_inquiry(
            {"contact": CONTACT, "topic": "other", "cohort": "b" * usage.INQUIRY_COHORT_MAX})
        self.assertIsNone(error)
        self.assertEqual(len(clean["cohort"]), 40)
        _clean, error = usage.normalize_inquiry(
            {"contact": CONTACT, "topic": "other", "cohort": "b" * (usage.INQUIRY_COHORT_MAX + 1)})
        self.assertEqual(error, "invalid_cohort")

    def test_bad_values(self):
        for value in ("베타파일럿", "beta pilot", "beta/pilot", "-beta", 42, ["beta_pilot"],
                      {"tag": "beta_pilot"}, "beta\rpilot"):
            with self.subTest(value=value):
                _clean, error = usage.normalize_inquiry(
                    {"contact": CONTACT, "topic": "other", "cohort": value})
                self.assertEqual(error, "invalid_cohort", value)
        message = usage.INQUIRY_ERRORS_KO["invalid_cohort"]
        self.assertIn("베타 구분 태그", message)
        self.assertIn("beta_pilot", message)
        self.assertNotIn("{", message)

    def test_bad_tag_does_not_mask_contact_error(self):
        _clean, error = usage.normalize_inquiry(
            {"contact": "x", "topic": "other", "cohort": "beta pilot"})
        self.assertEqual(error, "contact_too_short")


class CohortStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def test_add_inquiry_defaults_and_tag(self):
        self.store.add_inquiry("2026-11-21", "batch_report", CONTACT, MESSAGE)
        self.store.add_inquiry("2026-11-21", "api_mcp", PHONE, "태그", cohort="beta_pilot")
        rows = self.store.conn.execute(
            "SELECT cohort FROM inquiries ORDER BY id").fetchall()
        self.assertEqual([row["cohort"] for row in rows], ["", "beta_pilot"])
        self.assertEqual(self.store.inquiry_cohort_counts(), {"": 1, "beta_pilot": 1})

    def test_existing_db_is_migrated(self):
        directory = tempfile.mkdtemp(prefix="grnt-legacy-")
        path = os.path.join(directory, "app.sqlite")
        conn = sqlite3.connect(path)
        conn.executescript(OLD_SCHEMA)
        conn.execute("INSERT INTO inquiries(day, topic, contact, message, created_at) "
                     "VALUES ('2026-11-20','other','old','이전 문의','2026-11-20T10:00:00')")
        conn.commit()
        conn.close()
        store = Store(path)
        self.addCleanup(store.close)
        self.assertEqual(store.inquiry_count(), 1)
        store.add_inquiry("2026-11-21", "other", CONTACT, "", cohort="citechart")
        self.assertEqual(store.inquiry_cohort_counts(), {"": 1, "citechart": 1})


class CohortSubmitTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.payload = {"contact": CONTACT, "topic": "batch_report", "message": MESSAGE}

    def test_response_echoes_tag_and_not_contact(self):
        result = api.submit_inquiry({**self.payload, "cohort": "beta_pilot"}, self.store,
                                    day="2026-11-21")
        self.assertTrue(result["ok"])
        self.assertEqual(result["cohort"], "beta_pilot")
        self.assertNotIn(CONTACT, json.dumps(result, ensure_ascii=False))
        row = self.store.conn.execute("SELECT cohort FROM inquiries").fetchone()
        self.assertEqual(row["cohort"], "beta_pilot")

    def test_response_without_tag_is_empty_string(self):
        result = api.submit_inquiry(self.payload, self.store, day="2026-11-21")
        self.assertTrue(result["ok"])
        self.assertEqual(result["cohort"], "")

    def test_invalid_tag_is_rejected_without_storing(self):
        result = api.submit_inquiry({**self.payload, "cohort": "beta pilot"}, self.store,
                                    day="2026-11-21")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_cohort")
        self.assertIn("베타 구분 태그", result["message_ko"])
        self.assertIn("beta_pilot", result["message_ko"])
        self.assertNotIn("{", result["message_ko"])
        self.assertEqual(self.store.inquiry_count(), 0)

    def test_sink_and_webhook_carry_tag(self):
        directory = tempfile.mkdtemp(prefix="grnt-sink-")
        sink = os.path.join(directory, "inquiries.jsonl")
        sent = {}

        class _Response:
            status = 200

            def close(self):
                return None

        def fake_urlopen(request, timeout=None):
            sent["body"] = json.loads(request.data.decode("utf-8"))
            return _Response()

        env = {usage.INQUIRY_SINK_ENV: sink, usage.INQUIRY_WEBHOOK_ENV: "https://hook.example.test/x"}
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            result = api.submit_inquiry({**self.payload, "source": "citechart"}, self.store,
                                        day="2026-11-21")
            import time
            for _ in range(50):
                if sent.get("body"):
                    break
                time.sleep(0.02)
        self.assertTrue(result["ok"])
        with open(sink, encoding="utf-8") as handle:
            line = json.loads(handle.readline())
        self.assertEqual(line["cohort"], "citechart")
        self.assertEqual(sent["body"]["cohort"], "citechart")
        self.assertEqual(sent["body"]["source"], "grnt")

    def test_summary_counts_by_cohort(self):
        api.submit_inquiry({**self.payload, "cohort": "beta_pilot"}, self.store, day="2026-11-21")
        api.submit_inquiry({**self.payload, "contact": "b2" + "@" + "grnt.test",
                            "source": "beta_pilot"}, self.store, day="2026-11-21")
        api.submit_inquiry({**self.payload, "contact": "c3" + "@" + "grnt.test",
                            "cohort": "citechart"}, self.store, day="2026-11-21")
        summary = usage.inquiry_summary(self.store)
        counts = {row["cohort"]: row["count"] for row in summary["by_cohort"]}
        self.assertEqual(counts["beta_pilot"], 2)
        self.assertEqual(counts["citechart"], 1)
        self.assertNotIn(CONTACT, json.dumps(summary, ensure_ascii=False))


class CohortWebFormTest(unittest.TestCase):
    def setUp(self):
        from subsidy_kr import web_ui

        self.page = web_ui.render_page(sample_catalog().meta)

    def test_form_forwards_query_param_tag(self):
        self.assertIn("function cohortTag(", self.page)
        self.assertIn("cohort: cohortTag()", self.page)
        self.assertIn("get('cohort')", self.page)
        self.assertIn("[a-z0-9][a-z0-9._:-]{0,39}", self.page)

    def test_form_still_posts_without_identity_fields(self):
        self.assertIn("fetch('/v1/inquiry'", self.page)
        self.assertNotIn('name="email"', self.page.lower())


class CohortHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                        make_handler(sample_catalog(), cls.store))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()

    def _post(self, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/inquiry",
            data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def test_post_with_cohort(self):
        status, body = self._post({"contact": CONTACT, "topic": "api_mcp",
                                   "cohort": "beta_pilot"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["cohort"], "beta_pilot")

    def test_post_without_cohort_keeps_old_contract(self):
        status, body = self._post({"contact": "old" + "@" + "grnt.test", "topic": "other"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["cohort"], "")

    def test_bad_cohort_is_400(self):
        status, body = self._post({"contact": CONTACT, "topic": "other", "cohort": "bad tag"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_cohort")


if __name__ == "__main__":
    unittest.main(verbosity=2)
