"""표준 라이브러리만으로 동작하는 HTTP 서버 — 웹 UI + JSON API + MCP.

환경변수
--------
- `HOST`(기본 0.0.0.0) · `PORT`(기본 8787)
- `SUBSIDY_KR_DATA` 동기화 카탈로그 디렉터리(기본 `data/gov24`)
- `SUBSIDY_KR_DB`   카운터·스냅샷 SQLite(기본 `data/app.sqlite`)
- `PUBLIC_BASE_URL` robots/llms/sitemap 의 공개 주소

경로
----
`GET /` 웹 UI · `/s/`·`/s/{slug}` 주제·지역 페이지 · `/healthz` · `/v1/meta` · `/v1/stats` ·
`/v1/mcp`(매니페스트) · `/mcp`·`/v1/mcp`(POST JSON-RPC) · `/v1/tools/{tool}`(POST) ·
`/robots.txt` · `/llms.txt` · `/sitemap.xml` · `/.well-known/mcp/server-card.json`

보안
----
- API 키를 쓰지 않습니다(공개 읽기 전용 판정). 비밀값이 응답·페이지·로그에 나가지 않습니다.
- 페이지는 인라인 CSS/JS 만 쓰고 CSP 로 외부 로드를 막습니다.
- 처리되지 않은 예외는 스택트레이스 없이 `internal_error`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import mcp_http, pseo, static_files, usage
from .api import call_tool, mcp_manifest
from .catalog import Catalog, data_dir_from_env, load_catalog
from .store import Store
from .web_ui import render_page

MAX_BODY = 64 * 1024
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8787
MCP_PATHS = ("/mcp", "/v1/mcp")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'"
    ),
}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": (
        "Content-Type, Accept, X-Client-Id, MCP-Protocol-Version, Last-Event-ID"
    ),
    "Access-Control-Expose-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


def project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def default_db_path() -> str:
    return os.path.join(project_root(), "data", "app.sqlite")


def _int_env(value: Optional[str], fallback: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return parsed if 0 <= parsed <= 65535 else fallback


def config_from_env(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env = os.environ if env is None else env
    return {
        "host": (env.get("HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST,
        "port": _int_env(env.get("PORT"), DEFAULT_PORT),
        "db_path": (env.get("SUBSIDY_KR_DB") or "").strip() or default_db_path(),
        "data_dir": data_dir_from_env(),
    }


def _days_param(query: str) -> int:
    try:
        return int((parse_qs(query or "").get("days") or [""])[0])
    except (TypeError, ValueError):
        return usage.DEFAULT_DAYS


def make_handler(catalog: Catalog, store: Optional[Store] = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "grnt/0.2"
        sys_version = ""

        def version_string(self) -> str:
            return self.server_version

        # --- 헬퍼 ------------------------------------------------------------
        def _common_headers(self) -> None:
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            for key, value in CORS_HEADERS.items():
                self.send_header(key, value)

        def _send_json(self, status: int, payload: Any, cache: str = "no-store") -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, status: int, text: str, content_type: str,
                       cache: str = "public, max-age=3600") -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, status: int, html: str, cache: str = "no-cache") -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_empty(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self._common_headers()
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:  # 조용한 로그
            return

        # --- 라우팅 ----------------------------------------------------------
        def do_HEAD(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/index.html", "/s", "/s/") or path.startswith("/s/"):
                self._head(200, "text/html; charset=utf-8")
            elif path == "/healthz":
                self._head(200, "application/json; charset=utf-8")
            elif path in ("/v1/stats", "/v1/meta", "/v1/mcp",
                          "/.well-known/mcp/server-card.json"):
                self._head(200, "application/json; charset=utf-8")
            elif path in ("/robots.txt", "/llms.txt"):
                self._head(200, "text/plain; charset=utf-8")
            elif path == "/sitemap.xml":
                self._head(200, "application/xml; charset=utf-8")
            elif path == "/.well-known/mcp/server-card.json":
                self._head(200, "application/json; charset=utf-8")
            else:
                self._head(404, "application/json; charset=utf-8")

        def _head(self, status: int, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", "0")
            self._common_headers()
            self.end_headers()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Allow", "GET, POST, HEAD, OPTIONS")
            self.send_header("Content-Length", "0")
            self._common_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            usage.record_request(store, "GET", path)
            try:
                if path in ("/", "/index.html"):
                    self._send_html(200, render_page(catalog.meta))
                elif path in ("/s", "/s/"):
                    self._send_html(200, pseo.render_index(catalog), cache="public, max-age=600")
                elif path.startswith("/s/"):
                    slug = path[len("/s/"):].strip("/")
                    page = pseo.render_item(slug, catalog)
                    if page is None:
                        self._send_json(404, {"ok": False, "error": "not_found",
                                              "message": "unknown_page"})
                    else:
                        self._send_html(200, page, cache="public, max-age=600")
                elif path == "/favicon.ico":
                    self._send_empty(204)
                elif path == "/healthz":
                    self._send_json(200, {
                        "ok": True, "service": "grnt",
                        "catalog_state": catalog.meta.get("catalog_state", "sample"),
                        "services": len(catalog.services),
                        "tracks": catalog.stats().get("by_track"),
                        "snapshot_day": catalog.meta.get("snapshot_day"),
                        "version": mcp_http.SERVER_VERSION,
                    })
                elif path == "/robots.txt":
                    self._send_text(200, static_files.robots_txt(), "text/plain; charset=utf-8")
                elif path == "/llms.txt":
                    self._send_text(200, static_files.llms_txt(catalog),
                                    "text/plain; charset=utf-8")
                elif path == "/sitemap.xml":
                    self._send_text(200, static_files.sitemap_xml(catalog),
                                    "application/xml; charset=utf-8")
                elif path == "/.well-known/mcp/server-card.json":
                    self._send_json(200, static_files.server_card(),
                                    cache="public, max-age=300")
                elif path == "/v1/mcp":
                    self._send_json(200, mcp_manifest())
                elif path == "/v1/meta":
                    self._send_json(200, call_tool("get_service_meta", {}, catalog,
                                                   client_id=self._client(), store=store))
                elif path == "/v1/stats":
                    query = urlparse(self.path).query
                    self._send_json(200, usage.stats_payload(store, _days_param(query)),
                                    cache="public, max-age=300")
                elif path.rstrip("/") == "/mcp":
                    self.send_response(405)  # SSE GET 은 제공하지 않는다(스펙 허용)
                    self.send_header("Allow", "POST, OPTIONS")
                    self.send_header("Content-Length", "0")
                    self._common_headers()
                    self.end_headers()
                else:
                    self._send_json(404, {"ok": False, "error": "not_found"})
            except Exception:  # noqa: BLE001 - 내부 정보를 노출하지 않는다
                self._send_json(500, {"ok": False, "error": "internal_error"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            usage.record_request(store, "POST", path)
            if path.rstrip("/") in MCP_PATHS:
                self._handle_mcp()
                return
            if not path.startswith("/v1/tools/"):
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            name = path.rsplit("/", 1)[-1]
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self._send_json(400, {"ok": False, "error": "invalid_content_length"})
                return
            if length > MAX_BODY:
                self._send_json(413, {"ok": False, "error": "payload_too_large"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                args = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "error": "invalid_json"})
                return
            if not isinstance(args, dict):
                self._send_json(400, {"ok": False, "error": "invalid_argument",
                                      "message": "request_body_must_be_object"})
                return
            try:
                result = call_tool(name, args, catalog, client_id=self._client(), store=store)
            except Exception:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": "internal_error", "tool": name})
                return
            status = 200 if result.get("ok") is not False else (
                404 if result.get("error") == "unknown_tool" else 400)
            self._send_json(status, result)

        def _handle_mcp(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self._send_json(400, mcp_http.error_response(None, -32600, "invalid_content_length"))
                return
            if length > MAX_BODY:
                self._send_json(413, mcp_http.error_response(None, -32600, "payload_too_large"))
                return
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw.strip() else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(200, mcp_http.error_response(None, -32700, "parse_error"))
                return
            try:
                options = {"catalog": catalog, "store": store, "client_id": self._client()}
                if isinstance(payload, list):
                    if not payload:
                        self._send_json(200, mcp_http.error_response(None, -32600, "invalid_request"))
                        return
                    out = mcp_http.batch(payload, **options)
                    if not out:
                        self._send_empty(202)
                        return
                    self._send_json(200, out)
                    return
                out = mcp_http.handle(payload, **options)
            except Exception:  # noqa: BLE001
                self._send_json(500, mcp_http.error_response(None, -32603, "internal_error"))
                return
            if out is None:
                self._send_empty(202)
                return
            self._send_json(200, out)

        def _client(self) -> str:
            raw = str(self.headers.get("X-Client-Id") or "anonymous")
            safe = "".join(ch for ch in raw if ch.isalnum() or ch in "._:-")[:64]
            return safe or "anonymous"

    return Handler


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, db_path: str = "",
          data_dir: Optional[str] = None) -> None:
    db_path = db_path or default_db_path()
    directory = os.path.dirname(os.path.abspath(db_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    catalog = load_catalog(os.path.join(data_dir, "catalog.json") if data_dir else None)
    store = Store(db_path)
    httpd = ThreadingHTTPServer((host, port), make_handler(catalog, store))
    print(f"GRNT listening on http://{host}:{port} "
          f"(catalog={catalog.meta.get('catalog_state')}, services={len(catalog.services)}, "
          f"db={db_path})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        store.close()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m subsidy_kr.server",
        description="GRNT 서버 — 개인·창업 통합 지원금 판정 (웹 UI + JSON API + MCP)",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    cfg = config_from_env()
    serve(host=args.host or cfg["host"], port=args.port if args.port is not None else cfg["port"],
          db_path=args.db or cfg["db_path"], data_dir=args.data_dir or cfg["data_dir"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
