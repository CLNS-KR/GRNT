"""실데이터 동기화 — `python -m subsidy_kr.sync_gov24`.

세 데이터셋을 한 카탈로그로 모읍니다.

| 옵션 | 데이터셋 | 트랙 |
|---|---|---|
| `--sources gov24`(기본) | 15113968 보조금24 | 개인·가구 |
| `--sources startup` | 15125364 K-Startup | 창업·기업 |
| `--sources bizinfo` | 15157820 기업마당 | 창업·기업 |
| `--sources all` | 셋 다 + 일자별 스냅샷 | 통합 |
| `--local-portals` | 지자체 자체 복지포털(부평·인천·서울·경기·세종·브라보) | 통합 |

`15113968` 활용신청이 승인되면 이 스크립트 한 번으로 `serviceList` 전량 +
`supportConditions` 전량을 받아 `data/gov24/catalog.json` 을 만듭니다. `--sources all` 은
여기에 K-Startup 공고와 기업마당 공고를 더하고, `data/gov24/snapshots/{날짜}.json` 에
**비교용 스냅샷**을 남깁니다(변경 이력 추적).

설계 요점
--------
- **호출 한도**: 개발계정은 10,000건/일. `serviceList` 는 11페이지면 끝나지만
  `supportConditions` 를 서비스ID 단건으로 받으면 1만 콜이 넘습니다. 그래서 기본값은
  **페이지 전량 조회**(cond 없이 page/perPage)입니다. 이 방식이 막히면
  `--conditions-mode per-id` 로 단건 조회(필요한 ID만, `--ids`)로 전환합니다.
- **캐시**: 원본 응답을 `data/gov24/cache/` 에 7일 TTL 로 남깁니다. TTL 안이면
  네트워크 없이 `--from-cache` 로 카탈로그만 다시 만들 수 있습니다.
- **지난 공고 정리**: K-Startup 은 2016년부터 3만 건이 오고 서버가 기간 필터를 적용하지
  않습니다. 그래서 받은 뒤 `programs.is_current()` 로 **마감 30일 지난 공고**를 뺍니다
  (`--grace-days`, `--include-expired`).
- **키**: 인자 또는 `DATA_GO_KR_SERVICE_KEY` 환경변수. 파일·로그에 남기지 않습니다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from . import catalog as catalog_module
from . import bizinfo, programs, snapshots, startup
from .cache import JsonCache, now_iso
from .gov24 import DEFAULT_PER_PAGE, Gov24Client, Gov24Error

DEFAULT_TTL_HOURS = 24 * 7
SOURCE_ID = "gov24"
CATALOG_FILE = "catalog.json"
SERVICES_CACHE = "gov24_services"
CONDITIONS_CACHE = "gov24_conditions"
PROGRAM_SOURCES = ("startup", "bizinfo")
PROGRAM_CACHE = {"startup": "kstartup_programs", "bizinfo": "bizinfo_programs"}
# 소스 이름(옵션) ↔ 레코드의 source 값
PROGRAM_SOURCE_VALUES = {"startup": "kstartup", "bizinfo": "bizinfo"}
PROGRAM_LABELS = {SOURCE_ID: "정부24 보조금24", "startup": "창업진흥원 K-Startup",
                  "bizinfo": "중소벤처기업부 기업마당"}
# 지자체 포털 항목의 서비스ID 접두어(BOKJION·ICBENEFIT·IC1IN·SEOULWIS·GG24·SEJONG·BROSO)
_LOCAL_ID_PREFIX_RE = re.compile(r"^[A-Z0-9]+")


def project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def default_data_dir() -> str:
    return os.environ.get("SUBSIDY_KR_DATA") or os.path.join(project_root(), "data", "gov24")


def _key_from_env() -> str:
    return (os.environ.get("DATA_GO_KR_SERVICE_KEY")
            or os.environ.get("GOV24_SERVICE_KEY") or "").strip()


def _extract_conditions(row: Dict[str, Any]) -> Dict[str, Any]:
    from .conditions import CODE_CATALOG, is_on

    return {code: row.get(code) for code in CODE_CATALOG if is_on(row.get(code))}


def merge_records(services: List[Dict[str, Any]],
                  conditions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """목록 행 + 지원조건 행을 서비스ID 로 잇는다."""
    cond_map: Dict[str, Dict[str, Any]] = {}
    for row in conditions:
        sid = str(row.get("서비스ID") or "").strip()
        if not sid:
            continue
        cond_map[sid] = _extract_conditions(row)

    merged: List[Dict[str, Any]] = []
    for row in services:
        sid = str(row.get("서비스ID") or "").strip()
        if not sid:
            continue
        record = dict(row)
        record["conditions"] = cond_map.get(sid, {})
        merged.append(record)
    return merged


def build_catalog_payload(merged: List[Dict[str, Any]], *, api_calls: int = 0,
                          elapsed: float = 0.0, warnings: Optional[List[str]] = None,
                          condition_calls: int = 0) -> Dict[str, Any]:
    normalized = [catalog_module.normalize_service(row, source="gov24") for row in merged]
    cat = catalog_module.Catalog(normalized, {})
    stats = cat.stats()
    meta = {
        "dataset_id": "15113968",
        "name_ko": "행정안전부_대한민국 공공서비스(혜택) 정보",
        "source": "공공데이터포털(data.go.kr) 오픈API · 이용허락범위 제한 없음",
        "data_state": "live_sync",
        "catalog_state": "synced",
        "generated_on": now_iso(),
        "api_calls": api_calls,
        "condition_calls": condition_calls,
        "elapsed_s": round(elapsed, 2),
        "warnings": warnings or [],
        "stats": stats,
        "note_ko": (
            "`serviceList` 전량과 `supportConditions` 전량을 서비스ID로 결합했습니다. "
            "지자체 제도의 선정기준 공백은 원본 그대로 두었습니다(엔진이 '확인 필요'로 표시)."
        ),
    }
    return {"meta": meta, "services": merged}


def sync(service_key: Optional[str] = None, *, data_dir: Optional[str] = None,
         ttl_hours: float = DEFAULT_TTL_HOURS, force: bool = False,
         per_page: int = DEFAULT_PER_PAGE, max_services: Optional[int] = None,
         max_pages: Optional[int] = None, with_conditions: bool = True,
         conditions_mode: str = "paged", ids: Optional[List[str]] = None,
         from_cache: bool = False, delay: float = 0.0, dry_run: bool = False,
         collect: bool = False,
         log: Callable[[str], None] = lambda message: None) -> Dict[str, Any]:
    """동기화 1회 실행. 결과 요약 dict 를 돌려준다(예외 대신 상태로 알린다)."""
    root = data_dir or default_data_dir()
    cache = JsonCache(os.path.join(root, "cache"))
    started = time.time()
    warnings: List[str] = []
    api_calls = 0
    condition_calls = 0

    # 1) 캐시가 신선하면 네트워크를 건너뛴다(force·from_cache 아닐 때).
    services: List[Dict[str, Any]] = []
    conditions: List[Dict[str, Any]] = []
    cache_state = "network"

    cached_services, services_age = cache.load(SERVICES_CACHE, ttl_hours)
    if (cached_services or {}).get("data") and not force:
        services = list(cached_services["data"])
        cache_state = "cache"
        log(f"목록 캐시 사용({services_age:.1f}시간 경과, {len(services)}건)")
    elif from_cache:
        stored, _age = cache.load_any(SERVICES_CACHE)
        if not (stored or {}).get("data"):
            return _failure("cache_missing", "캐시된 목록이 없습니다. 먼저 네트워크 동기화를 실행하세요.")
        services = list(stored["data"])
        cache_state = "stale_cache"
        warnings.append(f"캐시가 {_age:.1f}시간 지났습니다(TTL {ttl_hours}시간).")

    if not services and not from_cache:
        key = (service_key or _key_from_env())
        if not key:
            return _failure(
                "service_key_missing",
                "인증키가 없습니다. data.go.kr 에서 15113968 활용신청(자동승인) 후 "
                "`DATA_GO_KR_SERVICE_KEY` 환경변수 또는 `--key` 로 넣어 주세요.",
            )
        try:
            client = Gov24Client(key)
            collected: List[Dict[str, Any]] = []
            page = 1
            total = None
            while True:
                payload = client.service_list(page=page, per_page=per_page)
                api_calls += 1
                rows = Gov24Client._rows(payload)
                total = payload.get("totalCount", total)
                for row in rows:
                    collected.append(_slim_service_row(row))
                    if max_services and len(collected) >= max_services:
                        break
                log(f"serviceList page {page}: {len(rows)}건 (누적 {len(collected)}"
                    f"{f'/{total}' if total is not None else ''})")
                if max_services and len(collected) >= max_services:
                    break
                if not rows or len(rows) < per_page:
                    break
                if total is not None and page * per_page >= int(total):
                    break
                page += 1
                if max_pages is not None and page > max_pages:
                    break
                if delay:
                    time.sleep(delay)
            services = collected
            cache.save(SERVICES_CACHE, {"data": services, "totalCount": total,
                                        "api_calls": api_calls, "source": "serviceList"})
        except Gov24Error as exc:
            return _failure("gov24_error", str(exc), hint_ko=exc.hint_ko,
                            http_status=exc.http_status, code=exc.code)
        except Exception as exc:  # noqa: BLE001 - 키·경로 등 내부 정보를 노출하지 않는다
            return _failure("unexpected_error", f"{type(exc).__name__}: {exc}")

    if not services:
        return _failure("empty_result", "serviceList 응답이 0건입니다. API 상태를 확인하세요.")

    # 2) 지원조건
    if with_conditions:
        cached_conditions, cond_age = cache.load(CONDITIONS_CACHE, ttl_hours)
        if (cached_conditions or {}).get("data") and not force:
            conditions = list(cached_conditions["data"])
            log(f"지원조건 캐시 사용({cond_age:.1f}시간 경과, {len(conditions)}건)")
        else:
            key = (service_key or _key_from_env())
            if not key:
                warnings.append("인증키가 없어 지원조건 수집을 건너뛰었습니다(자격 판정 불가).")
                conditions = []
            else:
                try:
                    client = Gov24Client(key)
                    if conditions_mode == "per-id":
                        targets = ids or [str(row.get("서비스ID")) for row in services]
                        if len(targets) > 500 and not ids:
                            warnings.append(
                                "per-id 모드는 1만 콜을 넘길 수 있어 500건으로 제한했습니다. "
                                "--ids 로 대상을 지정하거나 페이지 모드를 쓰세요."
                            )
                            targets = targets[:500]
                        collected = []
                        for sid in targets:
                            row = client.support_conditions(sid)
                            condition_calls += 1
                            if row:
                                collected.append(row)
                            if delay:
                                time.sleep(delay)
                        conditions = collected
                    else:
                        conditions = list(client.iter_conditions(per_page=per_page))
                        # iter_conditions 는 내부적으로 페이지 수만큼 호출한다(약 11회).
                        condition_calls += max(1, (len(conditions) + per_page - 1) // per_page)
                    cache.save(CONDITIONS_CACHE, {"data": conditions,
                                                  "source": "supportConditions",
                                                  "mode": conditions_mode})
                    log(f"supportConditions {len(conditions)}건 수집")
                except Gov24Error as exc:
                    warnings.append(f"지원조건 수집 실패: {exc} ({exc.hint_ko})")
                    if conditions_mode == "paged":
                        warnings.append(
                            "페이지 조회가 막혔습니다. `--conditions-mode per-id --ids ...` 로 "
                            "필요한 제도만 받을 수 있습니다."
                        )
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"지원조건 수집 중 오류: {type(exc).__name__}: {exc}")

    merged = merge_records(services, conditions)
    if conditions:
        matched = sum(1 for row in merged if row.get("conditions"))
        if matched < len(merged):
            warnings.append(
                f"지원조건이 붙지 않은 제도 {len(merged) - matched}건은 자격 코드 없이 저장됩니다"
                "(엔진은 '확인 필요'로 처리)."
            )

    elapsed = time.time() - started
    payload = build_catalog_payload(merged, api_calls=api_calls, elapsed=elapsed,
                                    warnings=warnings, condition_calls=condition_calls)
    report: Dict[str, Any] = {
        "ok": True,
        "state": cache_state,
        "dry_run": dry_run,
        "data_dir": root,
        **payload["meta"],
        "saved_files": [],
    }
    if collect:
        report["records"] = merged

    if not dry_run:
        os.makedirs(root, exist_ok=True)
        target = os.path.join(root, CATALOG_FILE)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, target)
        report["saved_files"] = [target, cache.path(SERVICES_CACHE),
                                 cache.path(CONDITIONS_CACHE)]
    return report


# ---------------------------------------------------------------------------
# 창업·기업 트랙 — K-Startup(15125364) · 기업마당(15157820)
# ---------------------------------------------------------------------------
def _cached_programs(cache: JsonCache, name: str, ttl_hours: float, *,
                     force: bool, from_cache: bool,
                     log: Callable[[str], None]) -> tuple:
    """(records, state, warnings). 네트워크를 부를 수 없으면 빈 목록을 돌려준다."""
    if not force:
        payload, age = cache.load(name, ttl_hours)
        if (payload or {}).get("data"):
            records = list(payload["data"])
            log(f"{name} 캐시 사용({age:.1f}시간 경과, {len(records)}건)")
            return records, "cache", []
    if from_cache:
        payload, age = cache.load_any(name)
        if (payload or {}).get("data"):
            return (list(payload["data"]), "stale_cache",
                    [f"{name} 캐시가 {age:.1f}시간 지났습니다."])
        return [], "missing", [f"{name} 캐시가 없어 건너뛰었습니다."]
    return [], "network", []


def collect_programs(service_key: Optional[str] = None, *, data_dir: Optional[str] = None,
                     ttl_hours: float = DEFAULT_TTL_HOURS, force: bool = False,
                     from_cache: bool = False, sources: tuple = PROGRAM_SOURCES,
                     grace_days: int = 30, include_expired: bool = False,
                     max_records: Optional[int] = None, per_page: int = 1000,
                     delay: float = 0.0,
                     log: Callable[[str], None] = lambda message: None) -> Dict[str, Any]:
    """K-Startup·기업마당 공고 수집 → 정규화 레코드.

    지난 공고는 `programs.is_current()` 로 걸러 냅니다(기본 마감 30일 전까지 유지).
    """
    root = data_dir or default_data_dir()
    cache = JsonCache(os.path.join(root, "cache"))
    key = (service_key or _key_from_env()).strip()
    records: List[Dict[str, Any]] = []
    warnings: List[str] = []
    stats: Dict[str, Any] = {}

    for source in sources:
        name = PROGRAM_CACHE.get(source)
        if not name:
            warnings.append(f"알 수 없는 소스 '{source}' 는 건너뛰었습니다.")
            continue
        cached, cache_state, cache_warnings = _cached_programs(
            cache, name, ttl_hours, force=force, from_cache=from_cache, log=log)
        warnings.extend(cache_warnings)
        fetched: List[Dict[str, Any]] = []
        state = cache_state
        if cached:
            fetched = cached
        elif cache_state == "network":
            if not key:
                warnings.append(
                    f"인증키가 없어 {PROGRAM_LABELS[source]} 수집을 건너뛰었습니다."
                    "(카탈로그에는 기존 데이터가 있으면 그대로 씁니다)")
                state = "skipped"
            else:
                try:
                    if source == "startup":
                        client = startup.KStartupClient(key)
                        fetched = client.records(per_page=per_page,
                                                 max_records=max_records)
                    else:
                        client = bizinfo.BizinfoClient(key)
                        fetched = client.records(per_page=min(per_page, 100),
                                                 max_records=max_records)
                    cache.save(name, {"data": fetched, "source": source,
                                      "dataset_id": (startup.DATASET_ID if source == "startup"
                                                     else bizinfo.DATASET_ID)})
                    state = "network"
                    log(f"{PROGRAM_LABELS[source]} {len(fetched)}건 수집")
                except Gov24Error as exc:
                    warnings.append(f"{PROGRAM_LABELS[source]} 수집 실패: {exc} ({exc.hint_ko})")
                    state = "failed"
                except Exception as exc:  # noqa: BLE001 - 키·경로를 노출하지 않는다
                    warnings.append(f"{PROGRAM_LABELS[source]} 수집 중 오류: "
                                    f"{type(exc).__name__}: {exc}"[:300])
                    state = "failed"
                if delay:
                    time.sleep(delay)
        kept = [row for row in fetched
                if include_expired or programs.is_current(row, grace_days=grace_days)]
        dropped = len(fetched) - len(kept)
        if dropped:
            log(f"{PROGRAM_LABELS[source]}: 지난 공고 {dropped}건 제외({len(kept)}건 유지)")
        records.extend(kept)
        stats[source] = {"label": PROGRAM_LABELS[source], "state": state,
                         "fetched": len(fetched), "kept": len(kept),
                         "dropped_expired": dropped}
    return {"records": records, "stats": stats, "warnings": warnings}


def _local_portal_prefix(service_id: Any) -> str:
    """지자체 포털 행의 서비스ID 접두어("BOKJION-1792" → "BOKJION") — 어느 포털 항목인지 구분한다."""
    match = _LOCAL_ID_PREFIX_RE.match(str(service_id or "").upper())
    return match.group(0) if match else ""


def _local_portal_key(service_id: Any) -> str:
    """병합 단위 키 — 브라보(BROSO)는 시·도별로 나눠 센다.

    브라보는 17개 시·도가 모두 `BROSO-` 접두어를 쓰므로 접두어로만 묶으면 한 시·도가
    통째로 실패해도(예: 세종 0건) 전체 브라보가 2% 줄었을 뿐이라 감소 보호가 걸리지
    않는다. 그래서 `BROSO-{시도}` 를 키로 써서 지역 단위 손실을 잡는다.
    """
    parts = str(service_id or "").upper().split("-")
    if parts and parts[0] == "BROSO" and len(parts) >= 2 and parts[1]:
        return f"BROSO-{parts[1]}"
    return _local_portal_prefix(service_id)


# 기존 행을 보존할 "비정상 감소" 기준 — 한 포털(브라보는 시·도)의 수집 건수가 기존보다
# 20% 넘게 그리고 5건 넘게 줄면 페이지 상한·포털 개편 같은 수집 사고로 본다.
# 마감 제외처럼 정상적인 감소는 이 선을 넘지 않게 잡았다(하루 만에 한 포털이 20%씩
# 줄어드는 것은 정상 마감 속도가 아니다).
LOCAL_SHRINK_RATIO = 0.2
LOCAL_SHRINK_MIN_ITEMS = 5


def _local_prefix_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        key = _local_portal_key(row.get("서비스ID"))
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _merge_local_rows(new_rows: List[Dict[str, Any]],
                      existing_rows: List[Dict[str, Any]], *,
                      grace_days: int = 30,
                      include_expired: bool = False,
                      shrink_ratio: float = LOCAL_SHRINK_RATIO,
                      shrink_min: int = LOCAL_SHRINK_MIN_ITEMS) -> tuple:
    """이번 수집 결과로 기존 지자체 행을 교체하되, **증발한 행은 함부로 지우지 않는다**.

    두 가지를 본다.

    1. **0건인 포털(브라보는 시·도)** — 포털 개편·차단·타임아웃은 흔하다. 한 건도 못 받은
       단위는 일시 실패로 보고 기존 행을 그대로 둔다.
    2. **큰 폭으로 줄어든 포털(브라보는 시·도)** — 받긴 했는데 기존 대비 20%·5건 넘게 줄면 페이지 상한에
       잘렸거나 응답이 일부만 온 것이다(2026-11-22 브라보 상한 8페이지 → 987→741건).
       이때는 새로 받은 행으로 교체하면서, 이번에 보이지 않은 기존 행을 보존한다.
       마감된 공고는 `programs.is_current`(grace_days)로 걸러 다시 살아나지 않게 한다.

    반환: (병합 행, 0건으로 기존 유지한 키, {키: 보존한 행 수})
    """
    new_ids = {str(row.get("서비스ID") or "").strip() for row in new_rows}
    new_counts = _local_prefix_counts(new_rows)
    existing_counts = _local_prefix_counts(existing_rows)

    kept: List[Dict[str, Any]] = []
    kept_prefixes: set = set()
    guarded: Dict[str, int] = {}
    for row in existing_rows:
        key = _local_portal_key(row.get("서비스ID"))
        if not key:
            continue
        if key not in new_counts:
            kept.append(row)
            kept_prefixes.add(key)
            continue
        old_count = existing_counts.get(key, 0)
        drop = old_count - new_counts.get(key, 0)
        if old_count <= 0 or drop < max(1, shrink_min) or drop / old_count < shrink_ratio:
            continue  # 정상 범위의 감소 — 새 수집 결과를 그대로 쓴다
        service_id = str(row.get("서비스ID") or "").strip()
        if service_id in new_ids:
            continue  # 이미 새 행에 있다
        if not include_expired and not programs.is_current(row, grace_days=grace_days):
            continue  # 마감이 지난 행은 되살리지 않는다
        kept.append(row)
        guarded[key] = guarded.get(key, 0) + 1
    return list(new_rows) + kept, kept_prefixes, guarded


def _existing_rows(root: str) -> List[Dict[str, Any]]:
    """이미 있는 카탈로그(원본 우선, 없으면 압축본)의 원본 행 목록.

    부분 실패 때 기존 데이터를 그대로 되쓰기 위한 것이므로 `.gz` 까지 본다
    (CI 클론에는 압축본만 있고, 그것이 배포 데이터의 원본이다).
    """
    for name in (CATALOG_FILE, "catalog.json.gz"):
        target = os.path.join(root, name)
        if not os.path.exists(target):
            continue
        try:
            payload = catalog_module.read_catalog_payload(target)
        except (OSError, EOFError, ValueError, TypeError, json.JSONDecodeError):
            continue
        rows = payload.get("services") if isinstance(payload, dict) else None
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def sync_all(service_key: Optional[str] = None, *, data_dir: Optional[str] = None,
             ttl_hours: float = DEFAULT_TTL_HOURS, force: bool = False,
             from_cache: bool = False,
             sources: tuple = ("gov24",) + PROGRAM_SOURCES,
             per_page: int = DEFAULT_PER_PAGE, with_conditions: bool = True,
             conditions_mode: str = "paged", ids: Optional[List[str]] = None,
             max_services: Optional[int] = None, max_pages: Optional[int] = None,
             grace_days: int = 30, include_expired: bool = False,
             max_records: Optional[int] = None, delay: float = 0.0,
             include_local_portals: bool = False, broso_max_pages: Optional[int] = None,
             dry_run: bool = False,
             log: Callable[[str], None] = lambda message: None) -> Dict[str, Any]:
    """세 데이터셋을 하나의 카탈로그로 합치고 일자별 스냅샷을 남긴다."""
    root = data_dir or default_data_dir()
    warnings: List[str] = []
    source_stats: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []

    if "gov24" in sources:
        report = sync(service_key, data_dir=root, ttl_hours=ttl_hours, force=force,
                      per_page=per_page, max_services=max_services, max_pages=max_pages,
                      with_conditions=with_conditions, conditions_mode=conditions_mode,
                      ids=ids, from_cache=from_cache, delay=delay, dry_run=True,
                      collect=True, log=log)
        warnings.extend([f"보조금24: {item}" for item in (report.get("warnings") or [])])
        if report.get("ok"):
            gov24_rows = list(report.get("records") or [])
            source_stats["gov24"] = {"label": PROGRAM_LABELS["gov24"],
                                     "state": report.get("state"),
                                     "services": len(gov24_rows)}
        else:
            gov24_rows = [row for row in _existing_rows(root)
                          if str(row.get("source") or "gov24") == "gov24"]
            warnings.append(f"보조금24 동기화 실패({report.get('error')}): "
                            f"기존 카탈로그 {len(gov24_rows)}건을 유지합니다.")
            source_stats["gov24"] = {"label": PROGRAM_LABELS["gov24"],
                                     "state": "failed", "services": len(gov24_rows)}
        rows.extend(gov24_rows)

    program_sources = tuple(source for source in sources if source in PROGRAM_SOURCES)
    if program_sources:
        collected = collect_programs(service_key, data_dir=root, ttl_hours=ttl_hours,
                                     force=force, from_cache=from_cache,
                                     sources=program_sources, grace_days=grace_days,
                                     include_expired=include_expired,
                                     max_records=max_records, delay=delay, log=log)
        warnings.extend(collected["warnings"])
        source_stats.update(collected["stats"])
        rows.extend(collected["records"])
        for source, stat in collected["stats"].items():
            if stat.get("state") in ("skipped", "failed", "missing"):
                source_value = PROGRAM_SOURCE_VALUES.get(source, source)
                existing = [row for row in _existing_rows(root)
                            if str(row.get("source") or "") == source_value]
                if existing:
                    rows.extend(existing)
                    stat["services"] = len(existing)
                    stat["state"] = f"{stat['state']}+기존유지"

    local_counts: Dict[str, Any] = {}
    if include_local_portals:
        # 지자체 자체 복지포털(부평복지ON·인천·서울·경기24·세종·브라보)은 공공데이터 API 밖이라
        # 별도 수집기가 필요하다. 실패하면 기존 지자체 행을 그대로 유지한다(부분 실패 허용).
        from . import local_portals

        # None 이면 수집기 기본값(시·도별 전체 페이지를 덮는 상한)을 쓴다 — 상한을 한 곳에서만 정한다.
        max_pages_per_sido = (int(broso_max_pages) if broso_max_pages
                              else int(local_portals.BROSO_MAX_PAGES_DEFAULT))
        try:
            collected_local = local_portals.collect_all_local_portals(
                include_expired=include_expired, broso_max_pages=max_pages_per_sido)
        except Exception as exc:  # noqa: BLE001 - 포털 개편·차단은 흔한 실패다
            collected_local = {"records": [], "counts": {}}
            warnings.append(f"지자체 포털 수집 실패({type(exc).__name__}): 기존 항목을 유지합니다.")
        local_rows = [row for row in collected_local.get("records") or []
                      if isinstance(row, dict)]
        existing_local = [row for row in _existing_rows(root)
                          if str(row.get("source") or "") == "local_portal"]
        merged_local, kept_prefixes, guarded_prefixes = _merge_local_rows(
            local_rows, existing_local, grace_days=grace_days,
            include_expired=include_expired)
        local_counts = dict(collected_local.get("counts") or {})
        if kept_prefixes:
            local_counts["kept_from_previous"] = sorted(kept_prefixes)
            warnings.append(
                "지자체 포털 " + ", ".join(sorted(kept_prefixes))
                + " 에서 새 항목을 받지 못해 기존 행을 유지했습니다.")
        if guarded_prefixes:
            preserved = sum(guarded_prefixes.values())
            judged = _local_prefix_counts(local_rows)
            local_counts["preserved_on_shrink"] = dict(sorted(guarded_prefixes.items()))
            warnings.append(
                "지자체 포털 " + ", ".join(f"{prefix}({judged.get(prefix, 0)}건)"
                                          for prefix in sorted(guarded_prefixes))
                + f" 수집이 기존보다 크게 줄어 이번에 보이지 않은 기존 행 {preserved}건을 "
                "유지했습니다(페이지 상한·포털 개편 여부를 확인하세요).")
        truncated = [slug for slug in (local_counts.get("broso_truncated") or [])]
        if truncated:
            warnings.append(
                "지역사회서비스포털 " + ", ".join(truncated)
                + " 이 시·도별 페이지 상한에 걸려 전체를 읽지 못했습니다"
                f"(broso_max_pages={max_pages_per_sido}).")
        local_errors = [slug for slug in (local_counts.get("broso_errors") or [])]
        if local_errors:
            warnings.append(
                "지역사회서비스포털 " + ", ".join(local_errors)
                + " 응답을 받지 못했습니다(일시 오류일 수 있어 기존 행을 유지합니다).")
        partial = [slug for slug in (local_counts.get("broso_partial") or [])
                   if slug not in local_errors]
        if partial:
            warnings.append(
                "지역사회서비스포털 " + ", ".join(partial)
                + " 일부 페이지를 읽지 못했습니다(가져온 만큼만 반영).")
        if merged_local:
            rows.extend(merged_local)
            source_stats["local_portal"] = {
                "label": "지자체 자체 복지포털",
                "state": ("network+기존유지" if (kept_prefixes or guarded_prefixes)
                          else "network"),
                "services": len(merged_local),
                "counts": local_counts,
            }
        else:
            source_stats["local_portal"] = {"label": "지자체 자체 복지포털",
                                            "state": "empty", "services": 0}
            warnings.append("지자체 포털에서 새 항목을 받지 못했고 기존 항목도 없습니다.")

    if not rows:
        return _failure("empty_result", "수집된 제도가 0건입니다. 인증키·승인 상태를 확인하세요.",
                        warnings=warnings, data_dir=root)

    # 중복 ID 정리(같은 공고가 두 번 오는 경우 마지막 것을 쓴다)
    by_id: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        service_id = str(row.get("서비스ID") or "").strip()
        if service_id:
            by_id[service_id] = row
    merged = list(by_id.values())

    normalized = [catalog_module.normalize_service(row, source=str(row.get("source") or "gov24"))
                  for row in merged]
    cat = catalog_module.Catalog(normalized, {})
    # 통계·트렉은 **모든 병합이 끝난 배열**에서 낸다(보조금24 → K-Startup·기업마당 →
    # 지자체 자체 포털 local_portal). 지자체 행을 더하기 전 값을 meta 에 남기면
    # 홈·/v1/meta 는 12,429건, /llms.txt·/healthz 는 13,416건으로 갈린다(0.4.5 실제).
    stats = catalog_module.stats_from_rows(normalized)
    day = now_iso()[:10]
    payload = {
        "meta": {
            "dataset_id": "+".join({"gov24": "15113968", "startup": "15125364",
                                      "bizinfo": "15157820"}[source]
                                     for source in sources if source in PROGRAM_LABELS),
            "name_ko": "개인·창업 통합 지원금 카탈로그",
            "source": ("공공데이터포털 오픈API — 정부24 보조금24(15113968) · "
                       "K-Startup(15125364) · 기업마당(15157820)"
                       + (" · 지자체 자체 복지포털" if include_local_portals else "")),
            "data_state": "live_sync",
            "catalog_state": "synced",
            "generated_on": now_iso(),
            "snapshot_day": day,
            "tracks": stats["by_track"],
            "sources": source_stats,
            "local_portal_counts": local_counts,
            "stats": stats,
            "warnings": warnings,
            "note_ko": (
                "개인(보조금24 JA 코드)과 창업·기업(K-Startup·기업마당 공고)을 한 카탈로그로 "
                "합쳤습니다. 지난 공고는 동기화 때 제외하고, 비교용 스냅샷을 snapshots/ 에 "
                "남깁니다. 기업마당 공고는 원문 문구를 그대로 보존합니다(변경금지 조건)."
                + (" 지자체 자체 복지포털(부평·인천·서울·경기·세종·브라보) 항목도 함께 담았습니다."
                   if include_local_portals else "")
            ),
        },
        "services": merged,
    }

    saved: List[str] = []
    if not dry_run:
        os.makedirs(root, exist_ok=True)
        target = os.path.join(root, CATALOG_FILE)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, target)
        saved.append(target)

        snap = snapshots.build_snapshot(cat.services, day)
        available = [str(item.get("day")) for item in snapshots.list_snapshots(
            snapshots.snapshot_dir(root)) if item.get("day")]
        previous = next((value for value in reversed(available) if value != day), None)
        saved.append(snapshots.save_snapshot(snap, snapshots.snapshot_dir(root)))
        if previous and previous != day:
            before = snapshots.load_snapshot(previous, snapshots.snapshot_dir(root))
            if before:
                diff = snapshots.diff_snapshots(before, snap)
                changes = {"compared_to": previous, **diff["counts"]}
            else:
                changes = {"compared_to": previous, "added": None, "removed": None,
                           "changed": None}
        else:
            changes = {"compared_to": None, "added": None, "removed": None, "changed": None}
    else:
        changes = {"compared_to": None, "added": None, "removed": None, "changed": None,
                   "note_ko": "dry-run 은 스냅샷을 쓰지 않습니다."}

    return {
        "ok": True,
        "state": "synced",
        "dry_run": dry_run,
        "data_dir": root,
        "snapshot_day": day,
        "stats": stats,
        "sources": source_stats,
        "warnings": warnings,
        "changes": changes,
        "saved_files": saved,
    }


def _slim_service_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """목록 응답에서 판정·표시에 쓰는 필드만 남긴다(저장 크기·개인정보 최소화)."""
    keep = ("서비스ID", "서비스명", "서비스목적요약", "소관기관명", "소관기관코드",
            "소관기관유형", "서비스분야", "사용자구분", "지원대상", "선정기준", "지원내용",
            "지원유형", "신청방법", "신청기한", "접수기관", "전화문의", "상세조회URL",
            "온라인신청사이트URL", "수정일시", "조회수", "등록일시", "부서명")
    return {key: row.get(key) for key in keep if row.get(key) not in (None, "")}


def _failure(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": False, "state": "failed", "error": code, "message": message, **extra}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m subsidy_kr.sync_gov24",
        description=("지원금 카탈로그 동기화 — 보조금24(15113968) · K-Startup(15125364) · "
                     "기업마당(15157820) → data/gov24/catalog.json"),
    )
    parser.add_argument("--key", default="", help="data.go.kr 인증키(없으면 DATA_GO_KR_SERVICE_KEY)")
    parser.add_argument("--data-dir", default="", help="산출물 디렉터리(기본 data/gov24)")
    parser.add_argument("--ttl-days", type=float, default=7.0, help="캐시 유효기간(일)")
    parser.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE, help="페이지 크기(최대 1000)")
    parser.add_argument("--max-services", type=int, default=0, help="수집 건수 제한(시험용, 0=전량)")
    parser.add_argument("--max-pages", type=int, default=0, help="페이지 제한(시험용, 0=전량)")
    parser.add_argument("--force", action="store_true", help="TTL 을 무시하고 다시 받기")
    parser.add_argument("--from-cache", action="store_true", help="네트워크 없이 캐시로 카탈로그 재생성")
    parser.add_argument("--no-conditions", action="store_true", help="지원조건 수집 생략")
    parser.add_argument("--conditions-mode", choices=("paged", "per-id"), default="paged")
    parser.add_argument("--ids", default="", help="per-id 모드에서 받을 서비스ID(쉼표 구분)")
    parser.add_argument("--sources", default="gov24",
                        help="comma list: gov24,startup,bizinfo 또는 all")
    parser.add_argument("--grace-days", type=int, default=30,
                        help="마감 후 며칠까지 카탈로그에 남길지(기본 30)")
    parser.add_argument("--include-expired", action="store_true",
                        help="지난 공고도 모두 보관(스냅샷 용량 증가)")
    parser.add_argument("--max-programs", type=int, default=0,
                        help="창업·기업 공고 수집 건수 제한(시험용)")
    parser.add_argument("--delay", type=float, default=0.0, help="호출 간 대기(초)")
    parser.add_argument("--local-portals", action="store_true",
                        help="지자체 자체 복지포털도 함께 수집(부평·인천·서울·경기·세종·브라보)")
    parser.add_argument("--broso-max-pages", type=int, default=0,
                        help="지역사회서비스포털 시·도별 최대 페이지(0=기본 40, 시·도 전체 순회)")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 결과만 확인")
    parser.add_argument("--json", action="store_true", help="요약을 JSON 으로 출력")
    args = parser.parse_args(argv)

    raw_sources = [item.strip().lower() for item in str(args.sources).split(",") if item.strip()]
    if "all" in raw_sources:
        sources = ("gov24",) + PROGRAM_SOURCES
    else:
        sources = tuple(dict.fromkeys(raw_sources)) or ("gov24",)
    unknown = [source for source in sources if source not in PROGRAM_LABELS]
    if unknown:
        print(f"실패: 알 수 없는 소스 {', '.join(unknown)} (사용: gov24, startup, bizinfo, all)")
        return 2

    if sources == ("gov24",):
        report = sync(
            args.key or None,
            data_dir=args.data_dir or None,
            ttl_hours=args.ttl_days * 24,
            force=args.force,
            per_page=args.per_page,
            max_services=args.max_services or None,
            max_pages=args.max_pages or None,
            with_conditions=not args.no_conditions,
            conditions_mode=args.conditions_mode,
            ids=[item.strip() for item in args.ids.split(",") if item.strip()] or None,
            from_cache=args.from_cache,
            delay=args.delay,
            dry_run=args.dry_run,
            log=lambda message: print(f"· {message}", file=sys.stderr, flush=True),
        )
    else:
        report = sync_all(
            args.key or None,
            data_dir=args.data_dir or None,
            ttl_hours=args.ttl_days * 24,
            force=args.force,
            from_cache=args.from_cache,
            sources=sources,
            per_page=args.per_page,
            with_conditions=not args.no_conditions,
            conditions_mode=args.conditions_mode,
            ids=[item.strip() for item in args.ids.split(",") if item.strip()] or None,
            max_services=args.max_services or None,
            max_pages=args.max_pages or None,
            grace_days=max(0, args.grace_days),
            include_expired=args.include_expired,
            max_records=args.max_programs or None,
            delay=args.delay,
            include_local_portals=args.local_portals,
            broso_max_pages=args.broso_max_pages or None,
            dry_run=args.dry_run,
            log=lambda message: print(f"· {message}", file=sys.stderr, flush=True),
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        if not report.get("ok"):
            print(f"실패: {report.get('error')} — {report.get('message')}")
            if report.get("hint_ko"):
                print(f"힌트: {report['hint_ko']}")
            return 1
        stats = report["stats"]
        if sources == ("gov24",):
            print(f"완료: {stats['services']}건 "
                  f"(자격코드 있음 {stats['with_conditions']}건, "
                  f"지자체 {stats['local_services']}건)")
            print(f"상태: {report['state']} · API 호출 {report['api_calls']}회 · "
                  f"{report['elapsed_s']}초")
        else:
            print(f"완료: {stats['services']}건 "
                  f"(개인 {stats['by_track'].get('personal', 0)}건 · "
                  f"창업·기업 {stats['by_track'].get('business', 0)}건)")
            for source, stat in (report.get("sources") or {}).items():
                print(f"  · {stat.get('label', source)}: {stat.get('state')} "
                      f"{stat.get('services', stat.get('kept', 0))}건")
            print(f"스냅샷: {report.get('snapshot_day')} · "
                  f"변경 {report.get('changes', {}).get('changed')}건")
        for warning in report.get("warnings") or []:
            print(f"주의: {warning}")
        for path in report.get("saved_files") or []:
            print(f"저장: {path}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
