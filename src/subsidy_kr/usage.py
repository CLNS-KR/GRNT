"""익명 일별 사용 카운터.

남기는 것: `날짜(KST) · 경로 · 툴 이름 · 판정 등급 · 0건/오류 여부`의 **횟수**만.
남기지 않는 것: IP, X-Forwarded-For, User-Agent, 쿠키, Referer, 세션, 프로필,
질의문, 서비스ID 목록. 집계 키는 서버가 아는 값으로만 제한하고, 모르는 경로는 `/404`
한 칸으로 뭉갭니다(임의 문자열이 통계에 남지 않게).

한계: 무료 플랜은 영구 디스크가 없어 재배포 시 0으로 돌아갑니다(일별 집계라 감수).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, Optional

from . import models

KST = timezone(timedelta(hours=9))
MAX_DAYS = 30
DEFAULT_DAYS = 7

KIND_PATH = "path"
KIND_TOOL = "tool"
KIND_VERDICT = "verdict"
KIND_FLAG = "flag"

FLAG_ZERO = "zero_results"
FLAG_ERROR = "errors"
FLAG_SAMPLE = "sample_catalog"

FIXED_PATHS = (
    "/", "/s/", "/guides/", "/guides", "/healthz", "/robots.txt", "/llms.txt", "/sitemap.xml",
    "/.well-known/mcp/server-card.json", "/v1/meta", "/v1/mcp", "/v1/stats",
    "/v1/tools", "/v1/report/export.csv", "/v1/report/print.html",
    "/v1/batch-match", "/v1/batch-match/export.csv", "/v1/batch-match/reports.html",
    "/v1/batch-match/sample.csv", "/mcp", "/favicon.ico", "/404",
)

KEY_RE = re.compile(r"[^0-9A-Za-z._:/{}-]")
MAX_KEY = 64


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _shift(day: str, days: int) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def safe_key(value: Any) -> str:
    return KEY_RE.sub("", str(value or ""))[:MAX_KEY]


@lru_cache(maxsize=1)
def _known_paths() -> frozenset:
    paths = set(FIXED_PATHS)
    try:
        from . import guides, pseo

        for spec in pseo.TOPICS:
            paths.add(f"/s/{spec['slug']}")
        for slug in pseo.SIDO_SLUGS.values():
            paths.add(f"/s/{slug}")
        # 질문형 가이드도 슬러그별 버킷으로 남겨 어떤 질문이 유입을 만드는지 센다.
        for slug in guides.slugs():
            paths.add(f"/guides/{slug}")
    except Exception:  # noqa: BLE001 - 카탈로그가 없어도 카운터는 돌아야 한다
        pass
    # 카탈로그를 열지 않고도 정적 주제·지역 슬러그를 즉시 구성한다.
    return frozenset(paths)


def path_key(path: str) -> str:
    raw = str(path or "").split("?", 1)[0]
    if not raw.startswith("/"):
        return "/404"
    trimmed = raw.rstrip("/") or "/"
    if trimmed.startswith("/v1/tools/"):
        return "/v1/tools"
    for candidate in (raw, trimmed):
        if candidate in _known_paths():
            return candidate
    return "/404"


def record_request(store: Any, method: str, path: str, day: Optional[str] = None) -> None:
    if store is None or str(method or "").upper() not in ("GET", "POST"):
        return
    try:
        store.bump_usage(day or today_kst(), KIND_PATH, path_key(path))
    except Exception:  # noqa: BLE001 - 계측 실패가 응답을 막지 않는다
        pass


def _is_zero_result(name: str, result: Any) -> bool:
    data = result if isinstance(result, dict) else {}
    payload = data.get("result") if isinstance(data.get("result"), dict) else data
    if name == "search_subsidies" and isinstance(payload, dict):
        counts = payload.get("counts")
        if isinstance(counts, dict):
            return int(counts.get(models.VERDICT_ELIGIBLE, 0)) == 0 and \
                   int(counts.get(models.VERDICT_CHECK, 0)) == 0
    if name == "list_region_subsidies" and isinstance(payload, dict):
        return int(payload.get("count") or 0) == 0
    return False


def record_tool(store: Any, name: str, result: Any, day: Optional[str] = None) -> None:
    if store is None:
        return
    stamp = day or today_kst()
    key = safe_key(name) or "unknown"
    try:
        store.bump_usage(stamp, KIND_TOOL, key)
        data = result if isinstance(result, dict) else {}
        payload = data.get("result") if isinstance(data.get("result"), dict) else {}
        verdict = payload.get("verdict") if isinstance(payload.get("verdict"), dict) else {}
        # 단건 판정 툴
        code = str(verdict.get("code") or "")
        if code in models.VERDICT_ORDER:
            store.bump_usage(stamp, KIND_VERDICT, code)
        # 후보 목록 툴: 등급별 건수를 그대로 더한다
        counts = payload.get("counts") if isinstance(payload, dict) else None
        if isinstance(counts, dict):
            for verdict_code, value in counts.items():
                if verdict_code in models.VERDICT_ORDER and int(value or 0) > 0:
                    store.bump_usage(stamp, KIND_VERDICT, verdict_code, int(value))
        if data.get("ok") is False:
            store.bump_usage(stamp, KIND_FLAG, FLAG_ERROR)
        elif _is_zero_result(key, data):
            store.bump_usage(stamp, KIND_FLAG, FLAG_ZERO)
        meta = payload.get("catalog") if isinstance(payload, dict) else None
        if isinstance(meta, dict) and meta.get("catalog_state") == "sample":
            store.bump_usage(stamp, KIND_FLAG, FLAG_SAMPLE)
    except Exception:  # noqa: BLE001
        pass


def _empty_day(day: str) -> Dict[str, Any]:
    return {"date": day, "requests": 0, "paths": {}, "tools": {}, "verdicts": {}, "flags": {}}


def stats_payload(store: Any, days: int = DEFAULT_DAYS,
                  today: Optional[str] = None) -> Dict[str, Any]:
    try:
        window = max(1, min(MAX_DAYS, int(days)))
    except (TypeError, ValueError):
        window = DEFAULT_DAYS
    end = today or today_kst()
    start = _shift(end, -(window - 1))
    empty = [_empty_day(_shift(start, offset)) for offset in range(window)]
    by_day = {row["date"]: row for row in empty}

    if store is not None:
        try:
            rows = store.usage_rows(start, end)
        except Exception:  # noqa: BLE001
            rows = []
        for row in rows:
            target = by_day.get(str(row.get("day") or ""))
            if target is None:
                continue
            kind = str(row.get("kind") or "")
            key = safe_key(row.get("key"))
            count = int(row.get("count") or 0)
            if kind == KIND_PATH:
                target["paths"][key] = count
                target["requests"] += count
            elif kind == KIND_TOOL:
                target["tools"][key] = count
            elif kind == KIND_VERDICT:
                target["verdicts"][key] = count
            elif kind == KIND_FLAG:
                target["flags"][key] = count

    totals: Dict[str, Any] = {"requests": 0, "paths": {}, "tools": {}, "verdicts": {}, "flags": {}}
    for row in empty:
        totals["requests"] += row["requests"]
        for kind in ("paths", "tools", "verdicts", "flags"):
            for key, value in row[kind].items():
                totals[kind][key] = totals[kind].get(key, 0) + value

    return {
        "ok": True,
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "timezone": "Asia/Seoul",
        "window_days": window,
        "from": start,
        "to": end,
        "privacy": {
            "stores_ip": False,
            "stores_user_agent": False,
            "stores_cookies": False,
            "stores_profile": False,
            "stores_identifiers": False,
            "granularity": "date (YYYY-MM-DD, Asia/Seoul) · 경로 · 툴 · 판정 등급 · 0건/오류",
            "note_ko": (
                "거주지·나이·소득구간·임신 여부 같은 입력값은 저장하지 않습니다. 알 수 없는 경로는 "
                "/404 한 칸으로 합산하며, 재배포 시 카운터가 초기화될 수 있습니다."
            ),
        },
        "days": empty,
        "totals": totals,
    }
