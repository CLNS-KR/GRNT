"""공공서비스 API 클라이언트 테스트 — 네트워크 없이 가짜 전송으로 검증."""
from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr.gov24 import Gov24Client, Gov24Error, encode_key  # noqa: E402

KEY = "abc123KEY+/="


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, bytes):
            return item
        return json.dumps(item, ensure_ascii=False).encode("utf-8")


def payload(rows, total=None):
    return {"page": 1, "perPage": len(rows), "totalCount": total if total is not None else len(rows),
            "currentCount": len(rows), "data": rows}


class EncodingTest(unittest.TestCase):
    def test_encoded_key_is_kept(self):
        self.assertEqual(encode_key("abc%2Bdef"), "abc%2Bdef")

    def test_special_characters_are_quoted(self):
        self.assertNotIn("/", encode_key(KEY))
        self.assertIn("%2F", encode_key(KEY))

    def test_missing_key_is_rejected(self):
        with self.assertRaises(Gov24Error):
            Gov24Client("")


class ServiceListTest(unittest.TestCase):
    def test_parses_rows_and_total(self):
        transport = FakeTransport([payload([{"서비스ID": "1", "서비스명": "가"},
                                            {"서비스ID": "2", "서비스명": "나"}], total=2)])
        client = Gov24Client(KEY, opener=transport)
        result = client.service_list(page=1, per_page=1000)
        self.assertEqual(result["totalCount"], 2)
        self.assertEqual(len(result["data"]), 2)
        self.assertIn("page=1", transport.urls[0])
        self.assertIn("perPage=1000", transport.urls[0])
        self.assertIn("returnType=JSON", transport.urls[0])

    def test_per_page_is_capped(self):
        transport = FakeTransport([payload([])])
        Gov24Client(KEY, opener=transport).service_list(per_page=99999)
        self.assertIn("perPage=1000", transport.urls[0])

    def test_missing_total_count_is_an_error(self):
        transport = FakeTransport([{"data": [{"서비스ID": "1"}]}])
        with self.assertRaises(Gov24Error) as ctx:
            Gov24Client(KEY, opener=transport).service_list()
        self.assertIn("totalCount", str(ctx.exception))

    def test_condition_filter_is_encoded(self):
        transport = FakeTransport([payload([])])
        Gov24Client(KEY, opener=transport).service_detail("000000465790")
        url = transport.urls[0]
        self.assertIn("cond[", url)
        self.assertIn("::EQ]", url)
        self.assertIn("%EC%84%9C%EB%B9%84%EC%8A%A4ID", url)

    def test_iter_services_pages_until_short_page(self):
        first = payload([{"서비스ID": str(index)} for index in range(2)], total=3)
        second = payload([{"서비스ID": "2"}], total=3)
        transport = FakeTransport([first, second])
        rows = list(Gov24Client(KEY, opener=transport).iter_services(per_page=2))
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(transport.urls), 2)


class ConditionsTest(unittest.TestCase):
    def test_support_conditions_paged(self):
        transport = FakeTransport([payload([{"서비스ID": "1", "JA0110": 19.0,
                                             "JA0203": "Y", "JA0412": "Y"}])])
        rows = list(Gov24Client(KEY, opener=transport).iter_conditions(per_page=1000))
        self.assertEqual(rows[0]["JA0203"], "Y")
        self.assertIn("supportConditions", transport.urls[0])

    def test_support_conditions_single(self):
        transport = FakeTransport([payload([{"서비스ID": "1", "JA0302": "Y"}])])
        row = Gov24Client(KEY, opener=transport).support_conditions("1")
        self.assertEqual(row["JA0302"], "Y")


class ErrorTest(unittest.TestCase):
    def test_http_403_hint_mentions_approval(self):
        transport = FakeTransport([urllib.error.HTTPError("https://x", 403, "Forbidden", {}, None)])
        with self.assertRaises(Gov24Error) as ctx:
            Gov24Client(KEY, opener=transport, max_retries=0).service_list()
        self.assertEqual(ctx.exception.http_status, 403)
        self.assertIn("승인", ctx.exception.hint_ko)

    def test_retryable_status_retries_then_fails(self):
        error = urllib.error.HTTPError("https://x", 503, "Unavailable", {}, None)
        transport = FakeTransport([error, error])
        client = Gov24Client(KEY, opener=transport, max_retries=1, sleep=lambda _s: None)
        with self.assertRaises(Gov24Error):
            client.service_list()
        self.assertEqual(len(transport.urls), 2)

    def test_network_error_masks_key(self):
        transport = FakeTransport([urllib.error.URLError(f"failed {KEY}")])
        client = Gov24Client(KEY, opener=transport, max_retries=0)
        with self.assertRaises(Gov24Error) as ctx:
            client.service_list()
        self.assertNotIn(KEY, str(ctx.exception))
        self.assertIn("***", str(ctx.exception))

    def test_api_error_code(self):
        transport = FakeTransport([{"code": -401, "msg": "unauthorized"}])
        with self.assertRaises(Gov24Error) as ctx:
            Gov24Client(KEY, opener=transport).service_list()
        self.assertEqual(str(ctx.exception.code), "-401")

    def test_plain_text_body_is_error_not_crash(self):
        transport = FakeTransport([b"<html>403 Forbidden</html>"])
        with self.assertRaises(Gov24Error) as ctx:
            Gov24Client(KEY, opener=transport).service_list()
        self.assertIn("invalid_json_response", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
