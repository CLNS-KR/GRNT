"""행정안전부 대한민국 공공서비스(혜택) 정보 API 클라이언트 (data.go.kr 15113968).

표준 라이브러리만 씁니다. 키는 `DATA_GO_KR_SERVICE_KEY` 환경변수(또는 `--key`)로만 받고,
예외 메시지·로그·응답 어디에도 키를 남기지 않습니다(서버가 되비추는 `msg` 도 마스킹).

오퍼레이션 3개
--------------
- `serviceList`        목록(페이지 1000건까지)
- `serviceDetail`      상세(서비스ID 1건)
- `supportConditions`  지원조건 — **서비스 1건당 한 행**에 JA 코드가 늘어선 넓은 표.
                       서비스ID 단건 조회가 원칙이지만, 페이지 전량 조회도 동작하므로
                       동기화는 페이지 단위(약 11회)로 받아 호출 한도를 아낀다.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional

BASE_URL = "https://api.odcloud.kr/api/gov24/v3"
DEFAULT_PER_PAGE = 1000
MAX_PER_PAGE = 1000
DATASET_ID = "15113968"

# API가 키를 되비출 수 있는 자리(예외 메시지·로그)를 가리는 데 쓴다.
MASK = "***"


class Gov24Error(RuntimeError):
    def __init__(self, message: str, *, code: Any = None, http_status: Optional[int] = None,
                 retryable: bool = False, hint_ko: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.retryable = retryable
        self.hint_ko = hint_ko


def encode_key(service_key: str) -> str:
    """인증키 인코딩. 이미 %XX 가 섞인 'Encoding 키'는 그대로 쓴다."""
    key = str(service_key or "").strip()
    if "%" in key:
        return key
    return urllib.parse.quote(key, safe="")


def _redact(text: Any, key: str) -> str:
    value = str(text or "")
    if not key:
        return value
    for variant in {key, encode_key(key), urllib.parse.quote(key)}:
        if variant:
            value = value.replace(variant, MASK)
    return value[:400]


class Gov24Client:
    def __init__(self, service_key: str, base_url: str = BASE_URL, *,
                 timeout: float = 20.0, max_retries: int = 2,
                 sleep: Callable[[float], None] = time.sleep,
                 opener: Optional[Callable[[str], bytes]] = None) -> None:
        if not str(service_key or "").strip():
            raise Gov24Error("service_key_missing",
                             hint_ko="DATA_GO_KR_SERVICE_KEY 환경변수에 인증키를 넣어 주세요.")
        self._key = str(service_key).strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep
        self._opener = opener or self._urlopen

    # --- 전송 ---------------------------------------------------------------
    def _urlopen(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={
            "User-Agent": "subsidy-kr/0.1 (+https://github.com/; data.go.kr 15113968)",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def _url(self, path: str, params: Dict[str, Any]) -> str:
        pairs = [f"serviceKey={encode_key(self._key)}"]
        for key, value in params.items():
            if value is None or value == "":
                continue
            pairs.append(f"{urllib.parse.quote(str(key), safe='[]:')}"
                         f"={urllib.parse.quote(str(value), safe='')}")
        return f"{self.base_url}/{path.lstrip('/')}?{'&'.join(pairs)}"

    def get_json(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = self._url(path, params)
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self._opener(url)
            except urllib.error.HTTPError as exc:
                status = exc.code
                # 본문은 읽어 버린다(키가 되비춰질 수 있어 메시지·로그에 남기지 않는다).
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
                last_error = Gov24Error(f"network_error: {_redact(exc, self._key)}",
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
            code = payload.get("code")
            if code not in (None, 0, "0", "00", "INFO-0"):
                raise Gov24Error(
                    "api_error", code=code,
                    hint_ko=_code_hint(code),
                )
            return payload
        raise last_error or Gov24Error("unknown_error")

    # --- 오퍼레이션 ---------------------------------------------------------
    def service_list(self, page: int = 1, per_page: int = DEFAULT_PER_PAGE,
                     conds: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"page": page,
                                  "perPage": max(1, min(int(per_page), MAX_PER_PAGE)),
                                  "returnType": "JSON"}
        for key, value in (conds or {}).items():
            params[key] = value
        return self._checked("serviceList", self.get_json("serviceList", params))

    def service_detail(self, service_id: str) -> Optional[Dict[str, Any]]:
        payload = self.get_json("serviceDetail", {
            "page": 1, "perPage": 1, "returnType": "JSON",
            "cond[서비스ID::EQ]": service_id,
        })
        rows = self._rows(payload)
        return rows[0] if rows else None

    def support_conditions_page(self, page: int = 1,
                                per_page: int = DEFAULT_PER_PAGE) -> Dict[str, Any]:
        return self._checked("supportConditions", self.get_json("supportConditions", {
            "page": page, "perPage": max(1, min(int(per_page), MAX_PER_PAGE)),
            "returnType": "JSON",
        }))

    def support_conditions(self, service_id: str) -> Optional[Dict[str, Any]]:
        payload = self.get_json("supportConditions", {
            "page": 1, "perPage": 1, "returnType": "JSON",
            "cond[서비스ID::EQ]": service_id,
        })
        rows = self._rows(payload)
        return rows[0] if rows else None

    # --- 페이지 순회 --------------------------------------------------------
    def iter_services(self, per_page: int = DEFAULT_PER_PAGE,
                      max_pages: Optional[int] = None) -> Iterator[Dict[str, Any]]:
        page = 1
        total: Optional[int] = None
        while True:
            payload = self.service_list(page=page, per_page=per_page)
            rows = self._rows(payload)
            total = payload.get("totalCount", total)
            for row in rows:
                yield row
            if not rows:
                return
            if total is not None and page * per_page >= int(total):
                return
            if len(rows) < per_page:
                return
            page += 1
            if max_pages is not None and page > max_pages:
                return

    def iter_conditions(self, per_page: int = DEFAULT_PER_PAGE,
                        max_pages: Optional[int] = None) -> Iterator[Dict[str, Any]]:
        """지원조건 전량을 페이지 단위로 순회한다(서비스 1건당 1행)."""
        page = 1
        total: Optional[int] = None
        while True:
            payload = self.support_conditions_page(page=page, per_page=per_page)
            rows = self._rows(payload)
            total = payload.get("totalCount", total)
            for row in rows:
                yield row
            if not rows:
                return
            if total is not None and page * per_page >= int(total):
                return
            if len(rows) < per_page:
                return
            page += 1
            if max_pages is not None and page > max_pages:
                return

    # --- 응답 검사 ----------------------------------------------------------
    @staticmethod
    def _rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = payload.get("data")
        if rows is None:
            return []
        if isinstance(rows, dict):
            return [rows]
        return [row for row in rows if isinstance(row, dict)]

    def _checked(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """totalCount 필드가 없으면 형식 변경·게이트웨이 오류로 보고 실패시킨다."""
        if "totalCount" not in payload:
            raise Gov24Error(
                f"{operation}: response_missing_totalCount",
                hint_ko="응답에 totalCount 가 없습니다. API 형식 변경 또는 게이트웨이 오류일 수 있습니다.",
            )
        return payload


def _http_hint(status: int) -> str:
    if status == 403:
        return ("활용신청 승인 전이거나 게이트웨이 전파 지연입니다(신청 직후 최대 수 분~수 시간). "
                "data.go.kr 마이페이지에서 15113968 승인 상태를 확인하세요.")
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
