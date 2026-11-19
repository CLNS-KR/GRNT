"""data.go.kr 오픈API 공통 클라이언트 — 표준 라이브러리만.

보조금24(`gov24.py`)가 먼저 있었고, 창업진흥원 K-Startup(`15125364`)과
중소벤처기업부 기업마당(`15157820`)이 합류하면서 **키 처리·재시도·키 마스킹·
응답 봉투 해석**이 세 번 반복될 상황이 됐습니다. 그래서 그 부분만 여기로 모았습니다.

응답 봉투는 데이터셋마다 조금씩 다릅니다.
- `{"data": [{...}], "totalCount": n}` (15113968·15125364)
- `{"data": {"data": [{...}]}}` (중첩형)
- `{"response": {"body": {"items": {"item": [...]}}}}` (구형 표준)
`rows()` 가 셋 다 받아 줍니다.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from .gov24 import Gov24Error, encode_key

MAX_PER_PAGE = 1000


def redact(text: Any, key: str) -> str:
    """예외 메시지·로그에 키가 되비춰지는 것을 막는다."""
    value = str(text or "")
    if not key:
        return value[:400]
    for variant in {key, encode_key(key), urllib.parse.quote(key)}:
        if variant:
            value = value.replace(variant, "***")
    return value[:400]


class DataGoKrClient:
    """한 인증키로 여러 데이터셋을 부르는 최소 클라이언트."""

    def __init__(self, service_key: str, base_url: str, *,
                 timeout: float = 20.0, max_retries: int = 2,
                 sleep: Callable[[float], None] = time.sleep,
                 opener: Optional[Callable[[str], bytes]] = None,
                 user_agent: str = "grnt/0.2 (+data.go.kr)") -> None:
        if not str(service_key or "").strip():
            raise Gov24Error(
                "service_key_missing",
                hint_ko="DATA_GO_KR_SERVICE_KEY 환경변수에 인증키를 넣어 주세요.",
            )
        self._key = str(service_key).strip()
        self.base_url = str(base_url).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep
        self._opener = opener or self._urlopen
        self.user_agent = user_agent

    # --- 전송 ---------------------------------------------------------------
    def _urlopen(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def url(self, params: Dict[str, Any]) -> str:
        pairs = [f"serviceKey={encode_key(self._key)}"]
        for key, value in params.items():
            if value is None or value == "":
                continue
            pairs.append(f"{urllib.parse.quote(str(key), safe='[]:')}"
                         f"={urllib.parse.quote(str(value), safe='')}")
        return f"{self.base_url}?{'&'.join(pairs)}"

    def get_json(self, params: Dict[str, Any]) -> Dict[str, Any]:
        target = self.url(params)
        last_error: Optional[Gov24Error] = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self._opener(target)
            except urllib.error.HTTPError as exc:
                status = exc.code
                try:
                    exc.read()
                except Exception:  # noqa: BLE001 - 본문을 못 읽어도 상태코드는 남긴다
                    pass
                last_error = Gov24Error(
                    f"HTTP {status}", http_status=status,
                    retryable=status in (429, 500, 502, 503, 504),
                    hint_ko=_http_hint(status),
                )
                if last_error.retryable and attempt < self.max_retries:
                    self._sleep(1.5 * (attempt + 1))
                    continue
                raise last_error from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = Gov24Error(f"network_error: {redact(exc, self._key)}",
                                        retryable=True,
                                        hint_ko="네트워크 오류입니다. 잠시 뒤 다시 시도하세요.")
                if attempt < self.max_retries:
                    self._sleep(1.5 * (attempt + 1))
                    continue
                raise last_error from None
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise Gov24Error(
                    "invalid_json_response",
                    hint_ko="인증키가 승인되지 않았거나 응답 형식이 다릅니다(평문 403 포함).",
                ) from None
            code = payload.get("code") if isinstance(payload, dict) else None
            if code not in (None, 0, "0", "00", "INFO-0"):
                raise Gov24Error("api_error", code=code, hint_ko=_code_hint(code))
            if not isinstance(payload, dict):
                raise Gov24Error("invalid_json_response",
                                 hint_ko="응답이 JSON 객체가 아닙니다.")
            return payload
        raise last_error or Gov24Error("unknown_error")

    # --- 응답 해석 ----------------------------------------------------------
    @staticmethod
    def rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        data: Any = payload.get("data") if isinstance(payload, dict) else None
        if data is None and isinstance(payload, dict):
            body = (payload.get("response") or {}).get("body") or {}
            items = body.get("items") or {}
            data = items.get("item") if isinstance(items, dict) else items
        if isinstance(data, dict) and "data" in data:
            data = data.get("data")
        if data is None:
            return []
        if isinstance(data, dict):
            return [data]
        return [row for row in data if isinstance(row, dict)]

    @staticmethod
    def total(payload: Dict[str, Any]) -> Optional[int]:
        for key in ("totalCount", "matchCount"):
            value = payload.get(key)
            if value not in (None, ""):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        body = (payload.get("response") or {}).get("body") or {}
        if body.get("totalCount") not in (None, ""):
            try:
                return int(body["totalCount"])
            except (TypeError, ValueError):
                return None
        return None


def _http_hint(status: int) -> str:
    if status == 403:
        return ("활용신청 승인 전이거나 게이트웨이 전파 지연입니다(신청 직후 최대 수 분~수 시간). "
                "data.go.kr 마이페이지에서 승인 상태를 확인하세요.")
    if status == 401:
        return "인증키가 거부되었습니다. Encoding/Decoding 키를 바꿔 보세요."
    if status == 429:
        return "호출 한도(개발계정 10,000건/일)를 넘었습니다."
    return f"HTTP {status}."


def _code_hint(code: Any) -> str:
    text = str(code)
    if text in ("-401", "401"):
        return "인증 실패입니다. 키 승인 상태와 Encoding/Decoding 형식을 확인하세요."
    return "API가 오류 코드를 반환했습니다."
