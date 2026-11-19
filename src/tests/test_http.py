"""HTTP 스모크 테스트 — 실제 소켓으로 라우팅·헤더·JSON-RPC 를 검증."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.server import make_handler  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402


class HttpTest(unittest.TestCase):
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

    # --- 헬퍼 ---------------------------------------------------------------
    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode("utf-8"), dict(response.headers)

    def _post(self, path, payload, raw=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def _status(self, path, method="GET"):
        url = f"http://127.0.0.1:{self.port}{path}"
        request = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    # --- 테스트 -------------------------------------------------------------
    def test_home_page(self):
        status, body, headers = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("지원금", body)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")

    def test_healthz(self):
        status, body, _ = self._get("/healthz")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["catalog_state"], "sample")
        from subsidy_kr.catalog import sample_catalog
        self.assertEqual(payload["services"], len(sample_catalog().services))
        self.assertEqual(payload["tracks"]["personal"], 20)

    def test_seo_files(self):
        _, robots, _ = self._get("/robots.txt")
        self.assertIn("Sitemap:", robots)
        _, sitemap, _ = self._get("/sitemap.xml")
        self.assertIn("<urlset", sitemap)
        _, llms, _ = self._get("/llms.txt")
        self.assertIn("search_subsidies", llms)
        _, card, _ = self._get("/.well-known/mcp/server-card.json")
        self.assertEqual(len(json.loads(card)["tools"]), 7)

    def test_pseo_routes(self):
        status, body, _ = self._get("/s/")
        self.assertEqual(status, 200)
        self.assertIn("주제별 지원금", body)
        status, body, _ = self._get("/s/cheongnyeon")
        self.assertEqual(status, 200)
        self.assertIn("청년", body)
        self.assertEqual(self._status("/s/does-not-exist"), 404)

    def test_manifest_and_meta(self):
        _, body, _ = self._get("/v1/mcp")
        self.assertEqual(len(json.loads(body)["tools"]), 7)
        _, body, _ = self._get("/v1/meta")
        meta = json.loads(body)["result"]
        self.assertEqual(len(meta["verdicts"]), 4)

    def test_tool_post(self):
        status, body = self._post("/v1/tools/search_subsidies", {"profile": {
            "age": 34, "income_band": "JA0203", "situations": ["no_home"]}})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(sum(body["result"]["counts"].values()), body["result"]["scanned"])

    def test_tool_post_errors(self):
        self.assertEqual(self._status("/v1/tools/nope", "POST"), 404)
        status, body = self._post("/v1/tools/check_eligibility", {})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_argument")

    def test_invalid_json(self):
        url = f"http://127.0.0.1:{self.port}/v1/tools/get_service_meta"
        request = urllib.request.Request(url, data=b"{oops", method="POST",
                                         headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)

    def test_mcp_json_rpc(self):
        status, body = self._post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["serverInfo"]["name"], "grnt")
        status, body = self._post("/v1/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                              "params": {"name": "get_service_meta",
                                                         "arguments": {}}})
        self.assertEqual(status, 200)
        self.assertTrue(body["result"]["structuredContent"]["ok"])

    def test_mcp_notification_returns_202(self):
        url = f"http://127.0.0.1:{self.port}/mcp"
        request = urllib.request.Request(
            url, data=json.dumps({"jsonrpc": "2.0",
                                  "method": "notifications/initialized"}).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 202)
            self.assertEqual(response.read(), b"")

    def test_mcp_batch(self):
        _, body = self._post("/mcp", [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        self.assertEqual(len(body), 2)

    def test_mcp_get_is_405(self):
        self.assertEqual(self._status("/mcp", "GET"), 405)

    def test_options_preflight(self):
        self.assertEqual(self._status("/mcp", "OPTIONS"), 204)
        self.assertEqual(self._status("/v1/tools/search_subsidies", "OPTIONS"), 204)

    def test_head_requests(self):
        for path in ("/", "/healthz", "/s/", "/robots.txt", "/sitemap.xml", "/v1/stats"):
            self.assertEqual(self._status(path, "HEAD"), 200, path)

    def test_unknown_route_and_payload_limit(self):
        self.assertEqual(self._status("/nope"), 404)
        url = f"http://127.0.0.1:{self.port}/v1/tools/get_service_meta"
        request = urllib.request.Request(url, data=b"{}" + b" " * (70 * 1024), method="POST",
                                         headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 413)

    def test_stats_are_anonymous_and_counted(self):
        self._get("/")
        self._post("/v1/tools/get_service_meta", {})
        _, body, _ = self._get("/v1/stats?days=1")
        stats = json.loads(body)
        self.assertFalse(stats["privacy"]["stores_ip"])
        self.assertFalse(stats["privacy"]["stores_profile"])
        self.assertGreaterEqual(stats["totals"]["requests"], 2)
        self.assertIn("get_service_meta", stats["totals"]["tools"])
        # 경로 키에 질의문·식별자가 남지 않는다
        for key in stats["totals"]["paths"]:
            self.assertNotIn("?", key)
            self.assertTrue(key.startswith("/"))

    def test_verdict_counts_recorded(self):
        self._post("/v1/tools/check_eligibility", {
            "service_id": "SMP-0001",
            "profile": {"age": 34, "income_band": "JA0203", "situations": ["no_home"]}})
        _, body, _ = self._get("/v1/stats?days=1")
        verdicts = json.loads(body)["totals"]["verdicts"]
        self.assertIn("eligible_likely", verdicts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
