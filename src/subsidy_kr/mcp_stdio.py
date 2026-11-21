"""stdio MCP 엔트리포인트 — `python -m subsidy_kr.mcp_stdio`.

Glama·mcp.so 같은 로컬 실행형 디렉터리는 "클라이언트가 프로세스를 띄워 stdin/stdout
으로 대화하는 서버"를 기본으로 봅니다. HTTP 서버와 **같은 툴·같은 JSON-RPC 로직**을
재사용하고 전송만 줄 단위 JSON-RPC 로 바꿉니다.

전송
----
- stdin: 한 줄에 JSON-RPC 2.0 한 건(빈 줄 무시)
- stdout: 요청(id 있음)에 대한 응답 1줄. notification 에는 아무것도 쓰지 않는다.
- 로그는 전부 stderr 로.

환경변수
--------
- `SUBSIDY_KR_DATA` : 동기화 카탈로그 디렉터리(기본 `data/gov24`). 없으면 내장 샘플.
- `SUBSIDY_KR_DB`   : 익명 카운터용 SQLite(없으면 `:memory:`)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional, TextIO

from . import mcp_http
from .api import mcp_tools
from .catalog import load_catalog
from .store import Store
from .version import __version__


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def serve(stdin: TextIO, stdout: TextIO, *, catalog: Any, store: Any = None,
          client_id: str = "stdio") -> int:
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps(mcp_http.error_response(None, -32700, "parse_error")) + "\n")
            stdout.flush()
            continue
        try:
            if isinstance(payload, list):
                out = mcp_http.batch(payload, catalog=catalog, store=store, client_id=client_id)
                if out:
                    stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
                    stdout.flush()
                continue
            response = mcp_http.handle(payload, catalog=catalog, store=store, client_id=client_id)
        except Exception:  # noqa: BLE001 - 내부 정보를 노출하지 않고 JSON-RPC 오류로만
            response = mcp_http.error_response(
                payload.get("id") if isinstance(payload, dict) else None,
                -32603, "internal_error")
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m subsidy_kr.mcp_stdio",
        description="GRNT stdio MCP 서버 — 개인·창업 통합 지원금 자격 판정",
    )
    parser.add_argument("--data-dir", default="", help="동기화 카탈로그 디렉터리")
    parser.add_argument("--db", default="", help="카운터용 SQLite 경로(기본 :memory:)")
    parser.add_argument("--version", action="version", version=f"grnt {__version__}")
    args = parser.parse_args(argv)

    catalog = load_catalog(os.path.join(args.data_dir, "catalog.json") if args.data_dir else None)
    db_path = (args.db or os.environ.get("SUBSIDY_KR_DB") or "").strip() or ":memory:"
    store = Store(db_path)
    _log(f"GRNT stdio MCP ready (v{__version__}, tools={len(mcp_tools())}, "
         f"catalog={catalog.meta.get('catalog_state')}, services={len(catalog)})")
    try:
        return serve(sys.stdin, sys.stdout, catalog=catalog, store=store)
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
