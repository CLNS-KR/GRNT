"""`/healthz` 버전·`/v1/stats` 트래픽 구분 회귀 테스트 — 0.4.6.

확인하는 것
- `/healthz` 에 `version` 이 현재 버전으로 들어간다.
- `/v1/stats` 가 경로를 묶음(`traffic.by_channel`)으로, 요청 종류를 셋(`traffic.by_client`)으로 접는다.
- 구분은 익명 카운트다 — User-Agent 원문을 넘겨도 저장되지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import usage  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.server import make_handler  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402
from subsidy_kr.version import __version__  # noqa: E402


class HealthzTrafficTest(unittest.TestCase):
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

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_healthz_version(self):
        payload = self._get("/healthz")
        self.assertEqual(payload["version"], __version__)

    def test_stats_traffic_buckets(self):
        usage.record_request(self.store, "GET", "/", client="browser")
        usage.record_request(self.store, "GET", "/llms.txt", client="bot")
        usage.record_request(self.store, "POST", "/mcp", client="bot")
        usage.record_request(self.store, "GET", "/static/og.png", client="other")
        data = self._get("/v1/stats?days=7")
        traffic = data["traffic"]
        self.assertGreaterEqual(traffic["by_channel"]["web"], 1)
        self.assertGreaterEqual(traffic["by_channel"]["crawler_files"], 1)
        self.assertGreaterEqual(traffic["by_channel"]["mcp"], 1)
        self.assertGreaterEqual(traffic["by_channel"]["assets"], 1)
        self.assertGreaterEqual(traffic["by_client"]["bot"], 2)
        self.assertIn("channel_labels_ko", traffic)


class ClassificationUnitTest(unittest.TestCase):
    def test_client_class(self):
        self.assertEqual(usage.client_class("Mozilla/5.0 Chrome/131"), "browser")
        self.assertEqual(usage.client_class("Googlebot/2.1"), "bot")
        self.assertEqual(usage.client_class("httpx/0.27"), "bot")
        self.assertEqual(usage.client_class(""), "other")

    def test_channel_of(self):
        self.assertEqual(usage.channel_of("/regions/"), "web")
        self.assertEqual(usage.channel_of("/s/"), "web")
        self.assertEqual(usage.channel_of("/about"), "web")
        self.assertEqual(usage.channel_of("/sitemap.xml"), "crawler_files")
        self.assertEqual(usage.channel_of("/v1/tools"), "api")
        self.assertEqual(usage.channel_of("/mcp"), "mcp")
        self.assertEqual(usage.channel_of("/404"), "not_found")

    def test_raw_user_agent_is_not_counted(self):
        store = Store(":memory:")
        try:
            usage.record_request(store, "GET", "/", client="Mozilla/5.0 (Macintosh)")
            rows = store.usage_rows(usage.today_kst(), usage.today_kst())
        finally:
            store.close()
        self.assertEqual([row for row in rows if row["kind"] == usage.KIND_CLIENT], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
