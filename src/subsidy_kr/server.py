"""표준 라이브러리만으로 동작하는 HTTP 서버 — 웹 UI + JSON API + MCP.

환경변수
--------
- `HOST`(기본 0.0.0.0) · `PORT`(기본 8787)
- `SUBSIDY_KR_DATA` 동기화 카탈로그 디렉터리(기본 `data/gov24`)
- `SUBSIDY_KR_DB`   카운터·스냅샷 SQLite(기본 `data/app.sqlite`)
- `GRNT_STATS_PATH` 익명 카운터·문의 접수를 따로 둘 SQLite 경로(영속 디스크·백업용, 선택)
- `PUBLIC_BASE_URL` robots/llms/sitemap 의 공개 주소
- `GOOGLE_SITE_VERIFICATION`·`NAVER_SITE_VERIFICATION` 구글·네이버 소유확인 메타태그 값
- `SITE_VERIFICATION_FILES` 루트에 서빙할 확인 파일 JSON(`{"naverXXXX.html": "..."}`)

경로
----
`GET /` 웹 UI · `/s/`·`/s/{slug}` 주제·지역 페이지 · `/regions/`·`/regions/{slug}` 시·도별 허브 ·
`/guides/`·`/guides/{slug}` 질문형 가이드 ·
`/healthz` · `/v1/meta` · `/v1/stats` ·
`/v1/mcp`(매니페스트) · `/mcp`·`/v1/mcp`(POST JSON-RPC) · `/v1/tools/{tool}`(POST) ·
`/v1/batch-match`(POST JSON·CSV — 거래처 일괄 익명 매칭) ·
`/v1/batch-match/export.csv`·`/v1/batch-match/reports.html`(POST) ·
`/v1/batch-match/sample.csv`(GET) ·
`/v1/inquiry`(POST JSON — 사전 신청·문의 접수) ·
`/v1/report/export.csv`·`/v1/report/print.html`(POST 본문 또는 GET 쿼리 — 거래처 전달용 리포트) ·
`/robots.txt` · `/llms.txt` · `/sitemap.xml` · `/.well-known/mcp/server-card.json` ·
`/{확인파일}.html`(환경변수로 등록한 경우)

보안
----
- API 키를 쓰지 않습니다(공개 읽기 전용 판정). 비밀값이 응답·페이지·로그에 나가지 않습니다.
- 페이지는 인라인 CSS/JS 만 쓰고 CSP 로 외부 로드를 막습니다.
- 처리되지 않은 예외는 스택트레이스 없이 `internal_error`.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Deque, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import (batch_client, guides, mcp_http, pseo, regions, site_verification,
               static_files, usage)
from .api import batch_export, call_tool, mcp_manifest, report_export, submit_inquiry
from .catalog import Catalog, data_dir_from_env, load_catalog
from .store import Store
from .version import __version__
from .web_ui import render_not_found, render_page

MAX_BODY = 64 * 1024
MAX_BATCH_BODY = 512 * 1024
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8787
MCP_PATHS = ("/mcp", "/v1/mcp")
REPORT_EXPORT_PATHS = ("/v1/report/export.csv", "/v1/report/print.html")
BATCH_MATCH_PATH = "/v1/batch-match"
BATCH_EXPORT_PATHS = ("/v1/batch-match/export.csv", "/v1/batch-match/reports.html")
BATCH_SAMPLE_PATH = "/v1/batch-match/sample.csv"
INQUIRY_PATH = "/v1/inquiry"
INQUIRY_ERROR_STATUS = {"daily_cap_reached": 429, "store_unavailable": 503}

# 동시 처리·요청 빈도 상한 — Render 무료(0.1 vCPU·512MB)에서 요청이 몰릴 때
# 메모리·CPU 가 함께 터지는 것을 막는다(막는 방식은 응답을 거절이 아니라 대기/429로).
MAX_CONCURRENCY_DEFAULT = 4
SEMAPHORE_WAIT_SECONDS = 20.0
RATE_LIMIT_DEFAULT = 300          # 분당 일반 요청(GET 페이지·메타)
RATE_LIMIT_HEAVY_DEFAULT = 120    # 분당 무거운 요청(검색·MCP·배치·문의)
RATE_LIMIT_KEYS_MAX = 4096        # 기억하는 IP 수 상한(메모리 보호)


def _int_env_default(env: Dict[str, str], key: str, fallback: int) -> int:
    try:
        value = int(str(env.get(key, "")).strip())
    except (TypeError, ValueError):
        return fallback
    return value if value >= 0 else fallback


class _RateLimiter:
    """IP별 분당 요청 수 제한 — 메모리만 쓰는 슬라이딩 윈도.

    쿠키·식별자를 남기지 않는다(IP 는 메모리에만, 60초 뒤 버린다). `limit <= 0` 이면 끈다.
    """

    def __init__(self, limit: int) -> None:
        self.limit = int(limit)
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: Optional[float] = None) -> float:
        """허용되면 0, 아니면 기다려야 할 초를 돌려준다."""
        if self.limit <= 0:
            return 0.0
        moment = time.monotonic() if now is None else now
        window_start = moment - 60.0
        with self._lock:
            if key not in self._hits and len(self._hits) >= RATE_LIMIT_KEYS_MAX:
                self._hits.clear()   # 기억 상한을 넘으면 통째로 비운다(오래된 키는 어차피 만료)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= window_start:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(0.5, round(60.0 - (moment - hits[0]), 1))
            hits.append(moment)
            return 0.0

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return {"keys": len(self._hits), "limit_per_minute": self.limit}


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


def default_stats_path() -> str:
    """익명 카운터·문의 접수 SQLite 경로 — `GRNT_STATS_PATH` 가 있으면 그곳(영속 디스크)을 쓴다.

    무료 플랜은 영구 디스크가 없어 재배포 시 카운터가 초기화된다. 외부 유료 DB 없이
    살리려면 Render 디스크(또는 다른 영속 볼륨)를 `GRNT_STATS_PATH` 로 마운트하면 된다.
    """
    return os.path.join(project_root(), "data", "app.sqlite")


def _int_env(value: Optional[str], fallback: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return parsed if 0 <= parsed <= 65535 else fallback


def config_from_env(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env = os.environ if env is None else env
    db_path = (env.get("SUBSIDY_KR_DB") or "").strip() or default_stats_path()
    stats_path = (env.get("GRNT_STATS_PATH") or "").strip() or db_path
    return {
        "host": (env.get("HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST,
        "port": _int_env(env.get("PORT"), DEFAULT_PORT),
        "db_path": db_path,
        "stats_path": stats_path,
        "data_dir": data_dir_from_env(),
    }


def _days_param(query: str) -> int:
    try:
        return int((parse_qs(query or "").get("days") or [""])[0])
    except (TypeError, ValueError):
        return usage.DEFAULT_DAYS


def report_args_from_query(path: str) -> Dict[str, Any]:
    """CSV·인쇄 뷰의 GET 쿼리를 `business_report` 인자로 바꿔 준다.

    웹 화면이 `<a href>`·`window.open` 으로 바로 열 수 있게 하려는 통로이며, 숫자는
    문자열 그대로 넘겨도 `agent_report` 가 숫자로 읽는다.
    """
    params = parse_qs(urlparse(path).query or "", keep_blank_values=False)
    args: Dict[str, Any] = {}
    for key, values in params.items():
        value = values[-1]
        if key in ("interest", "categories"):
            args[key] = values
        elif key == "include_closed":
            args[key] = value.strip().lower() in ("1", "true", "yes", "y")
        else:
            args[key] = value
    return args


def make_handler(catalog: Catalog, store: Optional[Store] = None,
                 *, max_concurrency: Optional[int] = None,
                 rate_limit: Optional[int] = None,
                 rate_limit_heavy: Optional[int] = None):
    """요청 핸들러 클래스 — 서버 하나당 동시 처리·요청 빈도 상한을 함께 가진다."""
    concurrency = (MAX_CONCURRENCY_DEFAULT if max_concurrency is None
                   else max(1, int(max_concurrency)))
    limiter = _RateLimiter(RATE_LIMIT_DEFAULT if rate_limit is None else rate_limit)
    heavy_limiter = _RateLimiter(RATE_LIMIT_HEAVY_DEFAULT if rate_limit_heavy is None
                                 else rate_limit_heavy)
    slots = threading.BoundedSemaphore(concurrency)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"grnt/{__version__}"
        sys_version = ""

        def version_string(self) -> str:
            return self.server_version

        # --- 헬퍼 ------------------------------------------------------------
        def _common_headers(self) -> None:
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            for key, value in CORS_HEADERS.items():
                self.send_header(key, value)

        def _send_bytes(self, status: int, body: bytes, content_type: str,
                        cache: str, *, compressible: bool = True) -> None:
            """공통 응답 쓰기 — 브라우저가 gzip 을 받으면 1KB 이상 본문을 압축한다.

            판정 결과 200건(~900KB)을 그대로 보내면 모바일에서 느리다. 압축하면 ~76KB 다.
            urllib 같은 클라이언트는 `Accept-Encoding: identity` 라 예전과 같은 본문을 받는다.
            """
            encoded = False
            accepts = str(self.headers.get("Accept-Encoding") or "").lower()
            if compressible and len(body) >= 1024 and "gzip" in accepts:
                body = gzip.compress(body, compresslevel=6)
                encoded = True
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            if encoded:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: Any, cache: str = "no-store",
                       extra_headers: Optional[Dict[str, str]] = None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if extra_headers:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache)
                for key, value in extra_headers.items():
                    self.send_header(key, value)
                self._common_headers()
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_bytes(status, body, "application/json; charset=utf-8", cache)

        def _send_text(self, status: int, text: str, content_type: str,
                       cache: str = "public, max-age=3600") -> None:
            self._send_bytes(status, text.encode("utf-8"), content_type, cache)

        def _send_html(self, status: int, html: str, cache: str = "no-cache") -> None:
            self._send_bytes(status, html.encode("utf-8"), "text/html; charset=utf-8", cache)

        def _send_empty(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self._common_headers()
            self.end_headers()

        def _send_redirect(self, location: str, status: int = 301) -> None:
            self.send_response(status)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "public, max-age=86400")
            self._common_headers()
            self.end_headers()

        def _send_not_found(self, reason: str = "") -> None:
            """사람이 잘못 들어온 주소는 HTML 안내로, `/v1/` 기계 경로는 JSON 404 로 답한다."""
            path = urlparse(self.path).path
            if path == "/v1" or path.startswith("/v1/"):
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            self._send_html(404, render_not_found(path, reason=reason), cache="no-store")

        def log_message(self, fmt: str, *args: Any) -> None:  # 조용한 로그
            return

        # --- 동시 처리·요청 빈도 -------------------------------------------------
        def _client_ip(self) -> str:
            """요청 IP — Render 뒤에서는 X-Forwarded-For 첫 값. 저장하지 않고 메모리에서만 쓴다."""
            forwarded = str(self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            if forwarded:
                return forwarded[:64]
            try:
                return str(self.client_address[0])[:64]
            except (IndexError, TypeError):
                return "unknown"

        def _enter(self, path: str, *, heavy: bool) -> bool:
            """빈도·동시성 문을 지난다. 상한을 넘으면 429/503 으로 바로 답하고 False.

            `/healthz` 는 통과시킨다 — 플랫폼 헬스체크가 부하 때문에 죽은 서비스로 보이면 안 된다.
            """
            if path == "/healthz":
                return True
            wait = (heavy_limiter if heavy else limiter).check(self._client_ip())
            if wait > 0:
                self._send_json(429, {
                    "ok": False, "error": "rate_limited", "retry_after_seconds": wait,
                    "message_ko": "요청이 너무 많습니다. 잠시 뒤 다시 시도해 주세요.",
                }, extra_headers={"Retry-After": str(int(max(1, round(wait))))})
                return False
            if not slots.acquire(timeout=SEMAPHORE_WAIT_SECONDS):
                self._send_json(503, {
                    "ok": False, "error": "busy",
                    "message_ko": "지금 요청이 몰리고 있습니다. 잠시 뒤 다시 시도해 주세요.",
                }, extra_headers={"Retry-After": "1"})
                return False
            self._slot_held = True
            return True

        def _leave(self) -> None:
            if getattr(self, "_slot_held", False):
                self._slot_held = False
                try:
                    slots.release()
                except ValueError:   # 이미 반납됐다 — 두 번 반납하지 않는다
                    pass

        # --- 라우팅 ----------------------------------------------------------
        def do_HEAD(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if (path in ("/", "/index.html", "/s", "/s/", "/guides", "/guides/",
                        "/regions", "/regions/")
                    or path.startswith("/s/") or path.startswith("/guides/")
                    or path.startswith("/regions/")):
                self._head(200, "text/html; charset=utf-8")
            elif path == "/healthz":
                self._head(200, "application/json; charset=utf-8")
            elif path in ("/v1/stats", "/v1/meta", "/v1/mcp",
                          "/.well-known/mcp/server-card.json"):
                self._head(200, "application/json; charset=utf-8")
            elif path in ("/robots.txt", "/llms.txt"):
                self._head(200, "text/plain; charset=utf-8")
            elif path == BATCH_SAMPLE_PATH:
                self._head(200, "text/csv; charset=utf-8")
            elif path == "/sitemap.xml":
                self._head(200, "application/xml; charset=utf-8")
            elif site_verification.file_body(path) is not None:
                # 검색엔진 소유확인용 HTML 파일(환경변수 SITE_VERIFICATION_FILES 로만 열린다).
                self._head(200, "text/html; charset=utf-8")
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
            if not self._enter(path, heavy=path in REPORT_EXPORT_PATHS):
                return
            try:
                if path in ("/", "/index.html"):
                    self._send_html(200, render_page(catalog.meta))
                elif path in ("/s", "/s/"):
                    self._send_html(200, pseo.render_index(catalog), cache="public, max-age=600")
                elif path.startswith("/s/"):
                    slug = path[len("/s/"):].strip("/")
                    if slug in regions.LEGACY_SIDO_SLUGS:
                        # 2026-07-01 통합 전 슬러그 — 색인된 주소를 새 주제 페이지로 돌린다.
                        self._send_redirect(f"/s/{regions.LEGACY_SIDO_SLUGS[slug]}")
                        return
                    page = pseo.render_item(slug, catalog)
                    if page is None:
                        self._send_not_found("unknown_page")
                    else:
                        self._send_html(200, page, cache="public, max-age=600")
                elif path in ("/guides", "/guides/"):
                    self._send_html(200, guides.render_index(catalog),
                                    cache="public, max-age=600")
                elif path.startswith("/guides/"):
                    slug = path[len("/guides/"):].strip("/")
                    page = guides.render_item(slug, catalog)
                    if page is None:
                        self._send_not_found("unknown_guide")
                    else:
                        self._send_html(200, page, cache="public, max-age=600")
                elif path in ("/regions", "/regions/"):
                    self._send_html(200, regions.render_index(catalog),
                                    cache="public, max-age=600")
                elif path.startswith("/regions/"):
                    slug = path[len("/regions/"):].strip("/")
                    if slug in regions.LEGACY_SIDO_SLUGS:
                        # 2026-07-01 통합 전 슬러그(gwangju·jeonnam) — 색인된 주소를 살린다.
                        self._send_redirect(f"/regions/{regions.LEGACY_SIDO_SLUGS[slug]}")
                        return
                    page = regions.render_item(slug, catalog)
                    if page is None:
                        self._send_not_found("unknown_region")
                    else:
                        self._send_html(200, page, cache="public, max-age=600")
                elif path == "/favicon.ico":
                    self._send_empty(204)
                elif path == "/healthz":
                    stats = catalog.stats()
                    self._send_json(200, {
                        "ok": True, "service": "grnt",
                        "catalog_state": catalog.meta.get("catalog_state", "sample"),
                        # `len(catalog.services)` 는 SQLite 1.3만 행을 매번 메모리에 올렸다(10~14초).
                        # 통계는 한 번만 계산해 재사용한다.
                        "services": int(stats.get("services") or len(catalog)),
                        "tracks": stats.get("by_track"),
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
                elif path == BATCH_SAMPLE_PATH:
                    body = batch_client.sample_csv().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Content-Disposition",
                                     'attachment; filename="grnt-batch-sample.csv"')
                    self.send_header("Cache-Control", "public, max-age=600")
                    self._common_headers()
                    self.end_headers()
                    self.wfile.write(body)
                elif path in REPORT_EXPORT_PATHS:
                    self._handle_report_export(path, report_args_from_query(self.path))
                elif path == INQUIRY_PATH:
                    self.send_response(405)  # 문의는 POST 로만 받는다
                    self.send_header("Allow", "POST, OPTIONS")
                    self.send_header("Content-Length", "0")
                    self._common_headers()
                    self.end_headers()
                elif site_verification.file_body(path) is not None:
                    # 검색엔진 소유확인용 HTML 파일(환경변수 SITE_VERIFICATION_FILES 로만 열린다).
                    self._send_text(200, site_verification.file_body(path) or "",
                                    "text/html; charset=utf-8")
                elif path.rstrip("/") == "/mcp":
                    self.send_response(405)  # SSE GET 은 제공하지 않는다(스펙 허용)
                    self.send_header("Allow", "POST, OPTIONS")
                    self.send_header("Content-Length", "0")
                    self._common_headers()
                    self.end_headers()
                else:
                    self._send_not_found("unknown_path")
            except Exception:  # noqa: BLE001 - 내부 정보를 노출하지 않는다
                self._send_json(500, {"ok": False, "error": "internal_error"})
            finally:
                self._leave()

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            usage.record_request(store, "POST", path)
            if not self._enter(path, heavy=True):
                return
            try:
                self._do_post(path)
            finally:
                self._leave()

        def _do_post(self, path: str) -> None:
            if path == BATCH_MATCH_PATH or path in BATCH_EXPORT_PATHS:
                self._handle_batch(path)
                return
            if path in REPORT_EXPORT_PATHS:
                self._handle_report_export(path)
                return
            if path == INQUIRY_PATH:
                self._handle_inquiry()
                return
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

        def _handle_inquiry(self) -> None:
            """사전 신청·문의 접수 — 본문 `{contact, topic, message}` 만 받는다.

            연락처·내용은 저장만 하고 응답에 되돌리지 않는다(같은 브라우저·중간 캐시에
            개인정보를 한 번 더 남기지 않기 위해서). 거절 사유는 `error` 코드로만 알린다.
            """
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self._send_json(400, {"ok": False, "error": "invalid_content_length"})
                return
            if length > MAX_BODY:
                self._send_json(413, {"ok": False, "error": "payload_too_large"})
                return
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "error": "invalid_json"})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"ok": False, "error": "invalid_argument",
                                      "message": "request_body_must_be_object"})
                return
            try:
                result = submit_inquiry(payload, store)
            except Exception:  # noqa: BLE001 - 내부 정보를 노출하지 않는다
                self._send_json(500, {"ok": False, "error": "internal_error"})
                return
            if result.get("ok"):
                # 문의는 재배포 시 카운터·DB 와 함께 사라질 수 있다(무료 플랜은 영구 디스크가 없다).
                # 접수번호·주제만 로그에 남겨(연락처·내용 없이) 최소한 "들어왔다는 사실"은 잃지 않게 한다.
                print(f"inquiry accepted receipt={result.get('receipt') or '-'} "
                      f"topic={result.get('topic')} duplicate={bool(result.get('duplicate'))}",
                      flush=True)
                self._send_json(200, result)
                return
            status = INQUIRY_ERROR_STATUS.get(str(result.get("error") or ""), 400)
            self._send_json(status, result)

        def _handle_batch(self, path: str) -> None:
            """거래처 일괄 매칭 — JSON 본문·JSON 배열·CSV 텍스트를 모두 받는다.

            본문이 `{` 또는 `[` 로 시작하지 않거나 Content-Type 이 text/csv 이면 CSV 로 읽습니다.
            민감 열은 `batch_client` 가 값을 꺼내지 않고 버리며, 서버에는 아무것도 저장하지 않습니다.
            """
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self._send_json(400, {"ok": False, "error": "invalid_content_length"})
                return
            if length > MAX_BATCH_BODY:
                self._send_json(413, {"ok": False, "error": "payload_too_large",
                                      "message": "batch_body_limit_512kb"})
                return
            raw = self.rfile.read(length) if length else b""
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                self._send_json(400, {"ok": False, "error": "invalid_encoding"})
                return
            content_type = str(self.headers.get("Content-Type") or "")
            stripped = text.strip()
            if not stripped:
                self._send_json(400, {"ok": False, "error": "invalid_argument",
                                      "message": "csv_or_clients_required"})
                return
            if "text/csv" in content_type or stripped[:1] not in ("{", "["):
                args: Any = {"csv": text}
            else:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    self._send_json(400, {"ok": False, "error": "invalid_json"})
                    return
                if isinstance(payload, list):
                    args = {"clients": payload}
                elif isinstance(payload, dict):
                    args = payload
                else:
                    self._send_json(400, {"ok": False, "error": "invalid_argument",
                                          "message": "request_body_must_be_object_or_array"})
                    return
            if not isinstance(args, dict):
                self._send_json(400, {"ok": False, "error": "invalid_argument"})
                return
            try:
                if path == BATCH_MATCH_PATH:
                    args = {**args, "include_report_html": True, "include_csv": True}
                    result = call_tool("batch_match_clients", args, catalog,
                                       client_id=self._client(), store=store)
                    status = 200 if result.get("ok") is not False else 400
                    self._send_json(status, result)
                    return
                fmt = "csv" if path.endswith(".csv") else "html"
                export = batch_export(args, catalog, fmt)
            except Exception:  # noqa: BLE001 - 내부 정보를 노출하지 않는다
                self._send_json(500, {"ok": False, "error": "internal_error"})
                return
            body = export["body"].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", export["content_type"])
            self.send_header("Content-Length", str(len(body)))
            disposition = "inline" if export.get("inline") else "attachment"
            self.send_header("Content-Disposition",
                             f'{disposition}; filename="{export["filename"]}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def _handle_report_export(self, path: str, args: Optional[Dict[str, Any]] = None) -> None:
            """거래처 전달용 CSV·인쇄용 HTML — 요청 본문은 `/v1/tools/business_report` 와 같다.

            POST(JSON 본문)와 GET(쿼리 문자열)을 모두 받는다. GET 은 웹 화면의 다운로드·
            인쇄 버튼이 브라우저 기본 동작으로 열기 위해 필요하다.
            """
            if args is None:
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
            fmt = "csv" if path.endswith(".csv") else "html"
            try:
                export = report_export(args, catalog, fmt)
            except Exception:  # noqa: BLE001 - 내부 정보를 노출하지 않는다
                self._send_json(500, {"ok": False, "error": "internal_error"})
                return
            body = export["body"].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", export["content_type"])
            self.send_header("Content-Length", str(len(body)))
            disposition = "inline" if export.get("inline") else "attachment"
            self.send_header("Content-Disposition",
                             f'{disposition}; filename="{export["filename"]}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

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


def _warm_catalog(catalog: Catalog) -> None:
    """첫 방문자가 브랜드·지역 페이지를 처음 만드는 비용을 대신 치르게 한다(백그라운드).

    `/s/` 는 1.3만 건을 한 번 훑어 페이지 목록을 만들고(스트림, 약 1.5초), `/regions/` 는
    시·도별 집계를 만든다. 둘 다 요청과 무관한 캐시라 서버가 뜬 뒤 미리 계산해 두면
    첫 크롤러·첫 방문자가 수 초를 기다리지 않는다. 헬스체크는 이 작업을 기다리지 않는다.
    """
    try:
        catalog.stats()
        pseo.items(catalog)
        regions.hub_summary(catalog)
    except Exception:  # noqa: BLE001 - 미리 계산은 실패해도 서비스에 지장이 없어야 한다
        pass


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, db_path: str = "",
          data_dir: Optional[str] = None, stats_path: str = "") -> None:
    # 카운터는 `GRNT_STATS_PATH`(영속 디스크) → `SUBSIDY_KR_DB` → data/app.sqlite 순으로 둔다.
    db_path = stats_path or db_path or default_stats_path()
    directory = os.path.dirname(os.path.abspath(db_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    catalog = load_catalog(os.path.join(data_dir, "catalog.json") if data_dir else None)
    store = Store(db_path)
    usage._known_paths()  # 시작 시 1회 계산해 첫 요청이 카탈로그를 다시 읽지 않게 한다
    usage.purge_inquiries(store)  # 회신 목적이 끝난 문의 연락처를 보관 기간 뒤 지운다
    env = os.environ
    handler = make_handler(
        catalog, store,
        max_concurrency=_int_env_default(env, "GRNT_MAX_CONCURRENCY", MAX_CONCURRENCY_DEFAULT),
        rate_limit=_int_env_default(env, "GRNT_RATE_LIMIT", RATE_LIMIT_DEFAULT),
        rate_limit_heavy=_int_env_default(env, "GRNT_RATE_LIMIT_HEAVY", RATE_LIMIT_HEAVY_DEFAULT),
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"GRNT listening on http://{host}:{port} "
          f"(catalog={catalog.meta.get('catalog_state')}, services={len(catalog)}, "
          f"db={db_path})", flush=True)
    threading.Thread(target=_warm_catalog, args=(catalog,), name="warm-catalog",
                     daemon=True).start()
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
          db_path=args.db or cfg["db_path"], data_dir=args.data_dir or cfg["data_dir"],
          stats_path=cfg["stats_path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
