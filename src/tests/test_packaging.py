"""배포·패키징 산출물 검증(파일 존재·내용·비밀값 부재)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)


def read(relative):
    with open(os.path.join(PROJECT, relative), "r", encoding="utf-8") as handle:
        return handle.read()


class FilesTest(unittest.TestCase):
    def test_required_files_exist(self):
        for name in ("README.md", "LICENSE", ".gitignore", ".dockerignore", ".env.example",
                     "Dockerfile", "render.yaml", "server.json", "sync_gov24.py",
                     "src/subsidy_kr/server.py", "src/subsidy_kr/mcp_stdio.py",
                     "src/subsidy_kr/sync_gov24.py", "data/gov24/.gitkeep"):
            path = os.path.join(PROJECT, name)
            self.assertTrue(os.path.exists(path), name)

    def test_no_bytecode_in_tree(self):
        for root, dirs, files in os.walk(SRC):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            for name in files:
                self.assertFalse(name.endswith(".pyc"), os.path.join(root, name))


class ServerJsonTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(read("server.json"))

    def test_registry_manifest_shape(self):
        self.assertIn("$schema", self.manifest)
        self.assertTrue(self.manifest["name"].startswith("io.github."))
        self.assertEqual(self.manifest["version"], "0.2.0")
        self.assertTrue(self.manifest["description"])
        self.assertEqual(self.manifest["remotes"][0]["type"], "streamable-http")
        self.assertTrue(self.manifest["remotes"][0]["url"].endswith("/mcp"))

    def test_registry_manifest_fits_publisher_schema(self):
        """공식 레지스트리 스키마(2025-12-11)의 제한 — 넘기면 mcp-publisher 가 거부한다."""
        description = self.manifest["description"]
        self.assertGreaterEqual(len(description), 1)
        self.assertLessEqual(len(description), 100, "description maxLength=100")
        self.assertRegex(self.manifest["name"], r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$")
        self.assertLessEqual(len(self.manifest["name"]), 200)
        self.assertTrue(self.manifest["websiteUrl"].startswith("https://"))
        self.assertTrue(self.manifest["remotes"][0]["url"].startswith("https://"))

    def test_registry_name_matches_repository(self):
        self.assertEqual(self.manifest["name"], "io.github.CLNS-KR/grnt")
        self.assertEqual(self.manifest["repository"]["url"],
                         "https://github.com/CLNS-KR/GRNT")
        readme = read("README.md")
        self.assertIn("server.json", readme)
        self.assertIn("CLNS-KR/GRNT", readme)


class DeploymentFilesTest(unittest.TestCase):
    def test_dockerfile_runs_server_without_secrets(self):
        text = read("Dockerfile")
        self.assertIn("subsidy_kr.server", text)
        self.assertIn("HEALTHCHECK", text)
        self.assertIn("USER app", text)
        self.assertNotIn("ARG ", text)
        for secret in ("DATA_GO_KR_SERVICE_KEY=", "LAW_GO_KR_OC="):
            self.assertNotIn(secret, text)

    def test_gzip_catalog_is_shipped_not_ignored(self):
        """압축 카탈로그는 git·Docker 양쪽에 들어간다(배포 환경 실데이터 부팅의 전제)."""
        gitignore = read(".gitignore")
        self.assertIn("!data/gov24/catalog.json.gz", gitignore)
        # 예외는 무시 규칙 뒤에 와야 효력이 있다
        self.assertLess(gitignore.index("data/gov24/*"),
                        gitignore.index("!data/gov24/catalog.json.gz"))
        for line in read(".dockerignore").splitlines():
            code = line.split("#", 1)[0]
            self.assertNotIn("catalog.json.gz", code, line)
        self.assertIn("COPY --chown=app:app data/ /app/data/", read("Dockerfile"))

    def test_render_blueprint(self):
        text = read("render.yaml")
        self.assertIn("healthCheckPath: /healthz", text)
        self.assertIn("runtime: docker", text)
        self.assertNotIn("value: \"1\"\n      - key: DATA", text)

    def test_public_url_matches_render_service_name(self):
        """공개 주소는 서비스명(grnt-kr)과 같은 곳을 가리켜야 한다 — 한쪽만 바뀌면 죽은 URL 로 게시된다."""
        manifest = json.loads(read("server.json"))
        self.assertEqual(manifest["websiteUrl"], "https://grnt-kr.onrender.com/")
        self.assertEqual(manifest["remotes"][0]["url"], "https://grnt-kr.onrender.com/mcp")
        render = read("render.yaml")
        self.assertIn("name: grnt-kr\n", render)
        self.assertIn("value: https://grnt-kr.onrender.com\n", render)
        self.assertIn('DEFAULT_BASE_URL = "https://grnt-kr.onrender.com"',
                      read("src/subsidy_kr/static_files.py"))
        for name in ("README.md", "server.json", "render.yaml", ".env.example"):
            self.assertNotIn("https://grnt.onrender.com", read(name), name)

    def test_env_example_has_empty_key(self):
        text = read(".env.example")
        self.assertIn("DATA_GO_KR_SERVICE_KEY=", text)
        line = [row for row in text.splitlines()
                if row.startswith("DATA_GO_KR_SERVICE_KEY=")][0]
        self.assertEqual(line.strip(), "DATA_GO_KR_SERVICE_KEY=")


class CliTest(unittest.TestCase):
    def _run(self, args):
        env = dict(os.environ, PYTHONPATH=SRC)
        return subprocess.run([sys.executable] + args, cwd=PROJECT, env=env,
                              capture_output=True, text=True, timeout=60)

    def test_sync_cli_help(self):
        result = self._run(["-m", "subsidy_kr.sync_gov24", "--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("15113968", result.stdout)

    def test_stdin_wrapper_help(self):
        result = self._run(["sync_gov24.py", "--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("data.go.kr", result.stdout)

    def test_stdio_server_answers_initialize(self):
        env = dict(os.environ, PYTHONPATH=SRC)
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {}}) + "\n"
        result = subprocess.run([sys.executable, "-m", "subsidy_kr.mcp_stdio"],
                                cwd=PROJECT, env=env, input=payload,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0)
        response = json.loads(result.stdout.strip().splitlines()[0])
        self.assertEqual(response["result"]["serverInfo"]["name"], "grnt")
        self.assertIn("GRNT", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
