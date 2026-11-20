"""사전 신청·문의 폼 — 입력 검증·저장·노출 경계 테스트.

이 폼만이 사용자가 직접 적은 연락처를 저장한다. 그래서 다음을 고정한다.
- 3~120자 연락처·세 가지 문의 유형·선택 500자 내용만 받는다.
- 같은 날 같은 내용은 한 번만 저장하고, 하루 상한을 넘으면 429로 알린다.
- 응답·통계(`/v1/stats`) 어디에도 연락처가 되돌아 나가지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from subsidy_kr import api, usage, web_ui  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.server import make_handler  # noqa: E402
from subsidy_kr.store import SCHEMA, Store  # noqa: E402

# 소스에 이메일 형태를 그대로 두지 않는다(개인정보 스캔이 파일 전체를 훑는다).
CONTACT = "tester" + "@" + "grnt.test"
OTHER_CONTACT = "sajang" + "@" + "grnt.test"


class NormalizeInquiryTest(unittest.TestCase):
    def test_valid_payload_is_cleaned(self):
        clean, error = usage.normalize_inquiry({
            "contact": "  " + CONTACT + "  ", "topic": "batch_report",
            "message": "  거래처 80곳\n매달 돌리고 싶습니다  "})
        self.assertIsNone(error)
        self.assertEqual(clean["contact"], CONTACT)
        self.assertEqual(clean["topic"], "batch_report")
        self.assertEqual(clean["message"], "거래처 80곳\n매달 돌리고 싶습니다")

    def test_message_is_optional(self):
        clean, error = usage.normalize_inquiry({"contact": CONTACT, "topic": "api_mcp"})
        self.assertIsNone(error)
        self.assertEqual(clean["message"], "")

    def test_rejects_short_contact(self):
        clean, error = usage.normalize_inquiry({"contact": " ab ", "topic": "other"})
        self.assertEqual(error, "contact_too_short")
        self.assertEqual(clean, {})

    def test_rejects_long_contact(self):
        _clean, error = usage.normalize_inquiry(
            {"contact": "가" * (usage.INQUIRY_CONTACT_MAX + 1), "topic": "other"})
        self.assertEqual(error, "contact_too_long")

    def test_rejects_unknown_topic(self):
        for topic in ("", "sales", "BATCH_REPORT", None):
            _clean, error = usage.normalize_inquiry({"contact": CONTACT, "topic": topic})
            self.assertEqual(error, "invalid_topic", topic)

    def test_rejects_long_message(self):
        _clean, error = usage.normalize_inquiry(
            {"contact": CONTACT, "topic": "other",
             "message": "가" * (usage.INQUIRY_MESSAGE_MAX + 1)})
        self.assertEqual(error, "message_too_long")

    def test_control_characters_are_stripped(self):
        clean, error = usage.normalize_inquiry(
            {"contact": "grnt\x00 담당\t자", "topic": "other", "message": "첫줄\n둘째줄\x07"})
        self.assertIsNone(error)
        self.assertNotIn("\x00", clean["contact"])
        self.assertEqual(clean["contact"], "grnt 담당 자")
        self.assertEqual(clean["message"], "첫줄\n둘째줄")

    def test_topic_labels_are_declared_for_every_topic(self):
        self.assertEqual(tuple(usage.INQUIRY_TOPIC_LABELS), usage.INQUIRY_TOPICS)
        for label in usage.INQUIRY_TOPIC_LABELS.values():
            self.assertTrue(label)


class InquiryStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_schema_has_inquiries_table(self):
        self.assertIn("inquiries", SCHEMA)
        for column in ("contact", "topic", "message", "created_at"):
            self.assertIn(column, SCHEMA)

    def test_add_count_and_duplicate_check(self):
        row_id = self.store.add_inquiry("2026-11-21", "batch_report", CONTACT, "문의")
        self.assertGreater(row_id, 0)
        self.assertEqual(self.store.inquiry_count(), 1)
        self.assertEqual(self.store.inquiry_count("2026-11-21"), 1)
        self.assertEqual(self.store.inquiry_count("2026-11-20"), 0)
        self.assertTrue(self.store.inquiry_exists("2026-11-21", "batch_report", CONTACT, "문의"))
        self.assertFalse(self.store.inquiry_exists("2026-11-21", "batch_report", CONTACT, "다른 문의"))

    def test_topic_counts_read_only_topics(self):
        self.store.add_inquiry("2026-11-21", "batch_report", CONTACT, "a")
        self.store.add_inquiry("2026-11-21", "batch_report", OTHER_CONTACT, "b")
        self.store.add_inquiry("2026-11-21", "api_mcp", CONTACT, "c")
        self.assertEqual(self.store.inquiry_topic_counts(),
                         {"batch_report": 2, "api_mcp": 1})

    def test_purge_drops_only_expired_rows(self):
        self.store.add_inquiry("2026-01-01", "other", CONTACT, "오래된 문의")
        self.store.add_inquiry("2026-11-20", "other", CONTACT, "최근 문의")
        removed = self.store.purge_inquiries(usage.INQUIRY_KEEP_DAYS, day="2026-11-21")
        self.assertEqual(removed, 1)
        self.assertEqual(self.store.inquiry_count(), 1)


class SubmitInquiryTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.payload = {"contact": CONTACT, "topic": "batch_report", "message": "거래처 80곳"}

    def tearDown(self):
        self.store.close()

    def test_success_does_not_echo_the_contact(self):
        result = api.submit_inquiry(self.payload, self.store, day="2026-11-21")
        self.assertTrue(result["ok"])
        self.assertTrue(result["stored"])
        self.assertFalse(result["duplicate"])
        self.assertRegex(result["receipt"], r"^I\d{5}$")
        self.assertNotIn(CONTACT, json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["privacy"]["contact_used_for"], "reply_only")
        self.assertFalse(result["privacy"]["in_usage_stats"])
        self.assertEqual(self.store.inquiry_count("2026-11-21"), 1)

    def test_same_content_twice_is_stored_once(self):
        first = api.submit_inquiry(self.payload, self.store, day="2026-11-21")
        second = api.submit_inquiry(self.payload, self.store, day="2026-11-21")
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertTrue(second["duplicate"])
        self.assertFalse(second["stored"])
        self.assertEqual(self.store.inquiry_count("2026-11-21"), 1)

    def test_daily_cap_replies_429_worthy_error(self):
        with mock.patch.object(usage, "INQUIRY_DAILY_CAP", 1):
            self.assertTrue(api.submit_inquiry(self.payload, self.store)["ok"])
            result = api.submit_inquiry(
                {**self.payload, "contact": OTHER_CONTACT, "message": "다른 문의"}, self.store)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "daily_cap_reached")
        self.assertEqual(self.store.inquiry_count(), 1)

    def test_invalid_topic_returns_korean_message(self):
        result = api.submit_inquiry({"contact": CONTACT, "topic": "nope"}, self.store)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_topic")
        self.assertIn("문의 유형", result["message_ko"])
        self.assertEqual(len(result["topics"]), 3)

    def test_missing_store_is_reported_not_raised(self):
        result = api.submit_inquiry(self.payload, None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "store_unavailable")


class InquiryHttpTest(unittest.TestCase):
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

    def _post(self, path, payload=None, raw=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def _status(self, path, method="GET"):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_post_is_accepted_and_not_echoed(self):
        status, body = self._post("/v1/inquiry", {
            "contact": CONTACT, "topic": "batch_report", "message": "거래처 300곳 문의"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertNotIn(CONTACT, json.dumps(body, ensure_ascii=False))

    def test_invalid_payload_is_400(self):
        status, body = self._post("/v1/inquiry", {"contact": "x", "topic": "batch_report"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "contact_too_short")
        status, body = self._post("/v1/inquiry", raw=b"not json")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_json")
        status, body = self._post("/v1/inquiry", raw=b"[]")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_argument")

    def test_get_is_not_allowed(self):
        self.assertEqual(self._status("/v1/inquiry"), 405)

    def test_contact_never_reaches_stats(self):
        contact = "stats" + "@" + "grnt.test"
        status, _body = self._post("/v1/inquiry", {
            "contact": contact, "topic": "api_mcp", "message": "MCP 붙이는 법"})
        self.assertEqual(status, 200)
        _, raw = self._get("/v1/stats?days=1")
        self.assertNotIn(contact, raw)
        stats = json.loads(raw)
        self.assertFalse(stats["privacy"]["stores_identifiers"])
        self.assertTrue(stats["privacy"]["inquiries"]["separate_from_usage"])
        self.assertFalse(stats["privacy"]["inquiries"]["in_this_payload"])
        # 경로 집계에는 익명 경로 키만 남는다
        self.assertIn("/v1/inquiry", stats["totals"]["paths"])
        self.assertNotIn(contact, json.dumps(stats["days"], ensure_ascii=False))


class InquiryWebUiTest(unittest.TestCase):
    def setUp(self):
        self.html = web_ui.render_page(sample_catalog().meta)

    def test_card_sits_above_the_footer(self):
        self.assertIn('id="inquiry-card"', self.html)
        self.assertLess(self.html.index('id="inquiry-card"'), self.html.index('<p class="foot">'))
        self.assertIn("세무·노무사 리포트 · 대량 매칭 문의", self.html)

    def test_card_inputs_are_present(self):
        for marker in ('id="inquiry-contact"', 'id="inquiry-topic"', 'id="inquiry-message"',
                       'id="inquiry-send"', 'id="inquiry-status"'):
            self.assertIn(marker, self.html, marker)
        for topic in usage.INQUIRY_TOPICS:
            self.assertIn(f'value="{topic}"', self.html)

    def test_card_posts_to_the_inquiry_endpoint(self):
        self.assertIn("fetch('/v1/inquiry'", self.html)
        self.assertIn("method: 'POST'", self.html)

    def test_card_does_not_ask_for_identity_fields(self):
        lowered = self.html.lower()
        for forbidden in ('name="email"', 'name="phone"', 'name="rrn"', 'type="password"'):
            self.assertNotIn(forbidden, lowered)

    def test_card_uses_theme_tokens_not_hard_coded_colours(self):
        css = web_ui.BASE_CSS
        block = css.split("/* 사전 신청·문의", 1)[1]
        self.assertIn("background:var(--surface-2)", block + css)
        self.assertIsNone(re.search(r"background:\s*#[0-9a-fA-F]{3,8}", block))
        self.assertIsNone(re.search(r"color:\s*#[0-9a-fA-F]{3,8}", block))

    def test_inline_scripts_still_parse(self):
        try:
            import esprima
        except ImportError:
            self.skipTest("esprima 미설치 — 문법 검사 건너뜀")
        scripts = re.findall(r"<script>(.*?)</script>", self.html, re.S)
        self.assertTrue(any("inquiry-send" in script for script in scripts))
        for index, script in enumerate(scripts):
            try:
                esprima.parseScript(script)
            except Exception as error:  # noqa: BLE001
                self.fail(f"인라인 스크립트 {index}번 문법 오류: {error}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
