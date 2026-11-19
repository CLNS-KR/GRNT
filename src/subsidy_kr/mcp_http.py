"""MCP Streamable HTTP(JSON-RPC 2.0) 최소 구현 — 표준 라이브러리만.

`POST /mcp` · `POST /v1/mcp` 로 들어온 JSON-RPC 2.0 한 건(또는 배치)을 처리합니다.
지원: `initialize`, `notifications/initialized`, `notifications/cancelled`, `ping`,
`tools/list`, `tools/call`, `resources/list`, `prompts/list`.

정직한 한계
-----------
- 응답은 `application/json` 한 덩어리입니다(SSE 스트리밍 없음). MCP 스펙은 스트리밍을
  강제하지 않으므로 대부분의 클라이언트가 그대로 동작합니다.
- 세션·인증이 없습니다. 툴 호출에 키도 필요 없습니다(공개 읽기 전용).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .api import call_tool, mcp_tools, text_summary
from .version import __version__

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "grnt"
SERVER_VERSION = __version__

INSTRUCTIONS_KO = (
    "GRNT — 한국 개인·창업 지원금 자격 판정. 나이·거주지·소득구간·상황(임신·출산·무주택·구직·장애 등) "
    "또는 사업자 조건(예비창업자/운영 중, 업력, 소상공인·중소기업, 업종)을 받아 공개 자격 코드와 "
    "공고 신청자격으로 후보를 판정합니다. `track` 으로 개인(personal)·창업(business)·전체(all)를 "
    "고릅니다. 결과는 4단계(가능성 높음/조건 확인 필요/정보 부족/해당 없음)이며 확정 판정이 아닙니다. "
    "'정보 부족'이면 결과의 next_questions 를 사용자에게 그대로 물어보세요. 지자체 제도는 선정기준이 "
    "비어 있어 '조건 확인 필요'가 정상이며, 창업·기업 사업의 '가능성 높음'은 신청자격 충족을 뜻하고 "
    "선정은 평가·경쟁으로 결정됩니다. 응답의 disclaimer_ko 와 scope_limits_ko 를 사용자에게 함께 "
    "전달하세요."
)


def _ok(msg_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def error_response(msg_id: Any, code: int, message: str,
                   data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": error}


def _text_result(result: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
    summary = text_summary(result)
    body = (summary + "\n\n" if summary else "") + json.dumps(result, ensure_ascii=False)
    return {
        "content": [{"type": "text", "text": body}],
        "structuredContent": result,
        "isError": is_error,
    }


def handle(payload: Any, *, catalog: Any, store: Any = None,
           client_id: str = "anonymous") -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return error_response(None, -32600, "invalid_request")

    method = payload.get("method")
    msg_id = payload.get("id")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _ok(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS_KO,
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return _ok(msg_id, {})

    if method == "tools/list":
        return _ok(msg_id, {"tools": mcp_tools()})

    if method == "resources/list":
        return _ok(msg_id, {"resources": []})

    if method == "prompts/list":
        return _ok(msg_id, {"prompts": []})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return error_response(msg_id, -32602, "invalid_params")
        result = call_tool(name, arguments, catalog, client_id=client_id, store=store)
        if isinstance(result, dict) and result.get("ok") is False:
            if result.get("error") == "unknown_tool":
                return error_response(msg_id, -32602, "unknown_tool", data={"tool": name})
            return _ok(msg_id, _text_result(result, is_error=True))
        return _ok(msg_id, _text_result(result))

    if msg_id is None:
        return None
    return error_response(msg_id, -32601, "method_not_found", data={"method": method})


def batch(payloads: List[Any], **kwargs: Any) -> List[Dict[str, Any]]:
    out = []
    for item in payloads:
        response = handle(item, **kwargs)
        if response is not None:
            out.append(response)
    return out
