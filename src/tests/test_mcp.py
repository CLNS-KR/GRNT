"""MCP JSON-RPC 2.0 프로토콜 테스트 (전송 없이 핸들러만)."""
from __future__ import annotations

import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import mcp_http, mcp_stdio  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402


class McpProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.store = Store(":memory:")

    @classmethod
    def tearDownClass(cls):
        cls.store.close()

    def handle(self, payload):
        return mcp_http.handle(payload, catalog=self.catalog, store=self.store)

    def test_initialize(self):
        out = self.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(out["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(out["result"]["serverInfo"]["name"], "grnt")
        self.assertIn("capabilities", out["result"])
        self.assertIn("자격", out["result"]["instructions"])

    def test_initialize_negotiates_known_version(self):
        out = self.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "9999-01-01"}})
        self.assertEqual(out["result"]["protocolVersion"], "2025-06-18")

    def test_notifications_have_no_response(self):
        self.assertIsNone(self.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(self.handle({"jsonrpc": "2.0", "method": "notifications/cancelled"}))
        self.assertIsNone(self.handle({"jsonrpc": "2.0", "method": "unknown/notification"}))

    def test_ping(self):
        out = self.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(out["result"], {})

    def test_tools_list(self):
        out = self.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        tools = out["result"]["tools"]
        self.assertEqual(len(tools), 8)
        self.assertEqual(tools[0]["name"], "search_subsidies")
        self.assertIn("inputSchema", tools[0])

    def test_tools_call_search(self):
        out = self.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "search_subsidies",
            "arguments": {"profile": {"age": 34, "income_band": "JA0203",
                                      "situations": ["no_home"]}}}})
        result = out["result"]
        self.assertEqual(result["isError"], False)
        self.assertTrue(result["content"][0]["text"])
        self.assertEqual(result["structuredContent"]["tool"], "search_subsidies")
        self.assertIn("results", result["structuredContent"]["result"])

    def test_tools_call_invalid_argument_is_tool_error(self):
        out = self.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "check_eligibility", "arguments": {}}})
        self.assertEqual(out["result"]["isError"], True)
        self.assertEqual(out["result"]["structuredContent"]["error"], "invalid_argument")

    def test_unknown_tool_is_protocol_error(self):
        out = self.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
            "name": "nope", "arguments": {}}})
        self.assertEqual(out["error"]["code"], -32602)
        self.assertEqual(out["error"]["data"]["tool"], "nope")

    def test_invalid_params_and_method(self):
        out = self.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                           "params": {"name": 1, "arguments": {}}})
        self.assertEqual(out["error"]["code"], -32602)
        out = self.handle({"jsonrpc": "2.0", "id": 8, "method": "no/such"})
        self.assertEqual(out["error"]["code"], -32601)

    def test_invalid_request(self):
        self.assertEqual(self.handle({"id": 9, "method": "ping"})["error"]["code"], -32600)
        self.assertEqual(self.handle("string")["error"]["code"], -32600)

    def test_resources_and_prompts(self):
        self.assertEqual(self.handle({"jsonrpc": "2.0", "id": 10,
                                      "method": "resources/list"})["result"]["resources"], [])
        self.assertEqual(self.handle({"jsonrpc": "2.0", "id": 11,
                                      "method": "prompts/list"})["result"]["prompts"], [])

    def test_batch(self):
        out = mcp_http.batch([
            {"jsonrpc": "2.0", "id": 12, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 13, "method": "tools/list"},
        ], catalog=self.catalog, store=self.store)
        self.assertEqual(len(out), 2)


class StdioTest(unittest.TestCase):
    def test_line_protocol(self):
        catalog = sample_catalog()
        store = Store(":memory:")
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
            + "{broken json\n"
        )
        stdout = io.StringIO()
        code = mcp_stdio.serve(stdin, stdout, catalog=catalog, store=store)
        stdout.seek(0)
        lines = [json.loads(line) for line in stdout.read().splitlines() if line.strip()]
        store.close()
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "grnt")
        self.assertEqual(len(lines[1]["result"]["tools"]), 8)
        self.assertEqual(lines[2]["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main(verbosity=2)
