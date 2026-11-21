"""버전 동기화·배포 기대값 검사.

버전이 한 곳만 올라가면 서버 카드·매니페스트·이미지 라벨·CI 스모크가 서로 다른 값을
말하게 됩니다(공식 MCP Registry 는 server.json 의 version 을 그대로 게시합니다).
여기서 version.py 를 기준으로 나머지가 같은지 확인합니다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from subsidy_kr import api, mcp_http, static_files  # noqa: E402
from subsidy_kr.version import __version__  # noqa: E402


def read(relative):
    with open(os.path.join(PROJECT, relative), "r", encoding="utf-8") as handle:
        return handle.read()


class VersionSyncTest(unittest.TestCase):
    def test_version_shape(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(__version__, "0.4.7")

    def test_server_json_matches_version_py(self):
        manifest = json.loads(read("server.json"))
        self.assertEqual(manifest["version"], __version__)

    def test_dockerfile_label_matches_version_py(self):
        text = read("Dockerfile")
        label = re.search(r'org\.opencontainers\.image\.version="([^"]+)"', text)
        self.assertIsNotNone(label, "이미지 라벨 버전이 없습니다")
        self.assertEqual(label.group(1), __version__)

    def test_http_server_header_and_manifest_use_version_py(self):
        self.assertEqual(mcp_http.SERVER_VERSION, __version__)
        manifest = api.mcp_manifest()
        self.assertEqual(manifest["version"], f"grnt/{__version__}")
        self.assertEqual(manifest["serverInfo"]["version"], f"grnt/{__version__}")
        self.assertEqual(static_files.server_card()["serverInfo"]["version"], __version__)
        # 하드코딩된 옛 버전 문자열이 남아 있지 않다
        for name in ("src/subsidy_kr/server.py", "src/subsidy_kr/api.py",
                     "src/subsidy_kr/datagokr.py", "src/subsidy_kr/bizinfo.py",
                     "src/subsidy_kr/startup.py"):
            self.assertNotIn("grnt/0.2", read(name), name)

    def test_ci_smoke_expects_current_tool_count(self):
        workflow = read(".github/workflows/test.yml")
        counts = re.findall(r'\["tools"\]\) == (\d+)', workflow)
        self.assertTrue(counts, "CI 스모크에서 툴 수 기대값을 찾지 못했습니다")
        for value in counts:
            self.assertEqual(int(value), len(api.mcp_tools()))

    def test_readme_states_current_version(self):
        readme = read("README.md")
        self.assertIn(f"v{__version__}", readme)

    def test_mcp_initialize_reports_version(self):
        from subsidy_kr.catalog import sample_catalog

        response = mcp_http.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                    "params": {}}, catalog=sample_catalog())
        self.assertEqual(response["result"]["serverInfo"]["version"], __version__)

    def test_public_url_is_one_place(self):
        self.assertEqual(static_files.base_url(""), static_files.DEFAULT_BASE_URL)
        self.assertIn(static_files.DEFAULT_BASE_URL, read("README.md"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
