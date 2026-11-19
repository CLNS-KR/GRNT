"""검색엔진 소유확인 회귀 테스트 — 구글 서치콘솔·네이버 서치어드바이저.

확인 항목
- `GOOGLE_SITE_VERIFICATION`·`NAVER_SITE_VERIFICATION` 메타태그가 `/` 와 `/s/`·`/s/{slug}` head 에 들어가는가
- `SITE_VERIFICATION_FILES` 로 등록한 HTML 파일이 루트 경로에서 그대로 서빙되는가(GET/HEAD)
- 환경변수가 없으면 기존 응답과 완전히 같은가(빈 태그·404)
- 화이트리스트 밖 문자·경로 이탈(`../`, 슬래시 포함 이름)은 거부되는가

실행: python3 -m unittest src.tests.test_site_verification   (네트워크 불필요)
"""
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

from subsidy_kr import pseo, site_verification, web_ui  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.server import make_handler  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402

GOOGLE_TOKEN = "GgOoGgLlEe-token_1234.abc"
NAVER_TOKEN = "naver1234abcd5678efgh"
GOOGLE_FILE = {"google1a2b3c4d5e6f.html": "google-site-verification: google1a2b3c4d5e6f.html"}
NAVER_FILE = {"naver1a2b3cdef4567gh8i9jk0lmnop12qrs3.html":
              "naver-site-verification: naver1a2b3cdef4567gh8i9jk0lmnop12qrs3.html"}
ENV_KEYS = (site_verification.ENV_GOOGLE, site_verification.ENV_NAVER,
            site_verification.ENV_FILES)


class VerificationEnvMixin(unittest.TestCase):
    """환경변수 3개를 테스트마다 깨끗하게 세팅/복원한다."""

    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class MetaTagTest(VerificationEnvMixin):
    def test_no_env_means_no_tag(self):
        self.assertEqual(site_verification.meta_tags(), "")
        page = web_ui.render_page()
        self.assertNotIn("google-site-verification", page)
        self.assertNotIn("naver-site-verification", page)

    def test_tags_reach_home_and_pseo_pages(self):
        os.environ[site_verification.ENV_GOOGLE] = GOOGLE_TOKEN
        os.environ[site_verification.ENV_NAVER] = NAVER_TOKEN
        expected_google = f'<meta name="google-site-verification" content="{GOOGLE_TOKEN}">'
        expected_naver = f'<meta name="naver-site-verification" content="{NAVER_TOKEN}">'
        catalog = sample_catalog()
        html_pages = [web_ui.render_page(catalog.meta), pseo.render_index(catalog)]
        item = pseo.render_item(pseo.slugs(catalog)[0], catalog)
        self.assertIsNotNone(item)
        html_pages.append(item)
        for html in html_pages:
            self.assertIn(expected_google, html)
            self.assertIn(expected_naver, html)
            self.assertLess(html.index(expected_google), html.index("</head>"))
            self.assertLess(html.index(expected_naver), html.index("</head>"))

    def test_only_configured_engine_is_emitted(self):
        os.environ[site_verification.ENV_NAVER] = NAVER_TOKEN
        tags = site_verification.meta_tags()
        self.assertIn("naver-site-verification", tags)
        self.assertNotIn("google-site-verification", tags)

    def test_token_is_sanitized(self):
        os.environ[site_verification.ENV_GOOGLE] = '"><script>alert(1)</script>'
        token = site_verification._token(os.environ[site_verification.ENV_GOOGLE])
        allowed = set("0123456789abcdefghijklmnopqrstuvwxyz"
                      "ABCDEFGHIJKLMNOPQRSTUVWXYZ._:-")
        self.assertEqual(set(token) - allowed, set())
        tags = site_verification.meta_tags()
        self.assertNotIn("<script", tags)
        self.assertEqual(tags.count('"'), 4)   # name="…" content="…" 한 쌍뿐


class VerificationFileTest(VerificationEnvMixin):
    def test_files_are_normalized(self):
        os.environ[site_verification.ENV_FILES] = json.dumps({**GOOGLE_FILE, **NAVER_FILE})
        files = site_verification.files()
        self.assertEqual(set(files), {"/" + name for name in list(GOOGLE_FILE) + list(NAVER_FILE)})

    def test_bad_entries_are_dropped(self):
        os.environ[site_verification.ENV_FILES] = json.dumps({
            "../etc/passwd.html": "x",
            "nested/path.html": "x",
            "ok.html": "fine",
            "no-extension": "x",
            "empty.html": "   ",
        })
        self.assertEqual(site_verification.files(), {"/ok.html": "fine"})

    def test_invalid_json_is_ignored(self):
        os.environ[site_verification.ENV_FILES] = "{not json"
        self.assertEqual(site_verification.files(), {})

    def test_body_is_sanitized(self):
        os.environ[site_verification.ENV_FILES] = json.dumps(
            {"x.html": "naver-site-verification: <script>x</script>"})
        body = site_verification.files()["/x.html"]
        self.assertNotIn("<", body)
        self.assertNotIn(">", body)


class VerificationHttpTest(VerificationEnvMixin):
    def setUp(self):
        super().setUp()
        os.environ[site_verification.ENV_FILES] = json.dumps({**GOOGLE_FILE, **NAVER_FILE})
        os.environ[site_verification.ENV_GOOGLE] = GOOGLE_TOKEN
        self.catalog = sample_catalog()
        self.store = Store(":memory:")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                         make_handler(self.catalog, self.store))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.close()
        super().tearDown()

    def _request(self, path, method="GET"):
        url = f"http://127.0.0.1:{self.port}{path}"
        request = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    def test_google_file_is_served(self):
        status, body, headers = self._request("/google1a2b3c4d5e6f.html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertEqual(body.decode(), GOOGLE_FILE["google1a2b3c4d5e6f.html"])

    def test_naver_file_is_served(self):
        path = "/" + list(NAVER_FILE)[0]
        status, body, _ = self._request(path)
        self.assertEqual(status, 200)
        self.assertEqual(body.decode(), list(NAVER_FILE.values())[0])

    def test_head_is_answered(self):
        status, body, _ = self._request("/google1a2b3c4d5e6f.html", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    def test_unknown_path_is_404(self):
        status, _, _ = self._request("/google-not-registered.html")
        self.assertEqual(status, 404)

    def test_home_page_carries_tag(self):
        status, body, _ = self._request("/")
        self.assertEqual(status, 200)
        self.assertIn(GOOGLE_TOKEN.encode(), body)
        self.assertIn(b"</head>", body)

    def test_file_without_env_is_404(self):
        os.environ[site_verification.ENV_FILES] = ""
        status, _, _ = self._request("/google1a2b3c4d5e6f.html")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
