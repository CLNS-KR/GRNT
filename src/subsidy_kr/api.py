"""MCP/JSON API 툴 7종.

| 툴 | 하는 일 |
|---|---|
| `search_subsidies` | 프로필 → 개인·창업 두 트랙 후보와 4단계 판정 |
| `check_eligibility` | 제도 1건 정밀 판정(사유·누락 정보 포함) |
| `get_subsidy_detail` | 제도 1건 원문 요약(선정기준·구비서류·문의처·신청기한) |
| `list_region_subsidies` | 지역(시·도·시군구) 제도 목록(트랙 선택) |
| `deadline_calendar` | 마감 임박 신청기한 캘린더(두 트랙 통합) |
| `compare_ledgers` | 일자별 카탈로그 스냅샷 비교(추가·삭제·변경) |
| `get_service_meta` | 카탈로그 상태·판정 규격·개인정보 설정 |

공통 원칙
---------
- 모든 응답에 `data_state`(`sample`|`gov24`|`kstartup`|`bizinfo`), `checked_at`,
  `disclaimer_ko`, 출처 URL/표기가 붙습니다.
- 프로필은 **응답에 되돌려 쓰지 않습니다**(해석 결과만 요약). 저장도 하지 않습니다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from . import conditions, engine, local_portals, models, programs, regions, snapshots, usage
from .catalog import Catalog

SCHEMA_VERSION = "1.1"
SCOPE_LIMITS_KO = [
    "개인 트랙 판정은 정부24 보조금24가 공개한 자격 코드(연령·성별·소득구간·생애·가구·직업)만 근거로 합니다.",
    "창업·기업 트랙 판정은 K-Startup·기업마당 공고의 구조화된 신청자격(업력·연령·지역·대상·성별)만 "
    "근거로 합니다. 공고 본문의 서술형 요건은 원문 확인 대상입니다.",
    "재산·거주기간·성적·가점 등 코드로 표현되지 않은 요건은 판정을 바꾸지 않고 '원문 확인'으로 알립니다.",
    "지자체 제도 다수는 원본의 선정기준이 비어 있습니다. 이때는 '확인 필요'로 답하며 임의 추정하지 않습니다.",
    "아동·청소년 대상 제도의 연령 코드는 신청자가 아니라 대상자(아동)의 나이입니다.",
    "창업·기업 지원사업의 '가능성 높음'은 **신청자격 충족**을 뜻합니다. 선정은 평가·경쟁·예산으로 결정됩니다.",
    "최종 수급·선정 여부와 금액은 소관기관 심사로 결정됩니다. 이 서비스는 신청을 대행하지 않습니다.",
]
DISCLAIMER_KO = (
    "본 결과는 공개 데이터(정부24 보조금24·K-Startup·기업마당)를 이용한 참고용 사전 점검이며, "
    "수급·선정 자격을 확정하지 않습니다. 신청 전 소관기관 원문과 담당 부서에 확인하세요."
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _catalog_block(catalog: Catalog) -> Dict[str, Any]:
    meta = catalog.meta
    stats = meta.get("stats") or catalog.stats()
    return {
        "catalog_state": meta.get("catalog_state", "sample"),
        "data_state": meta.get("data_state", "sample"),
        "dataset_id": meta.get("dataset_id", "SAMPLE-2026-11-19"),
        "generated_on": meta.get("generated_on") or meta.get("fetched_at"),
        "source": meta.get("source") or (
            "정부24 보조금24(15113968) · K-Startup(15125364) · 기업마당(15157820) — 내장 샘플"
        ),
        "stats": stats,
        "tracks": stats.get("by_track") if isinstance(stats, dict) else None,
        "snapshot_day": meta.get("snapshot_day"),
        "note_ko": meta.get("note_ko") or meta.get("source_note_ko"),
    }


def _envelope(tool: str, payload: Dict[str, Any], catalog: Catalog) -> Dict[str, Any]:
    payload.setdefault("catalog", _catalog_block(catalog))
    payload.setdefault("checked_at", _now())
    payload.setdefault("disclaimer_ko", DISCLAIMER_KO)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    return {"tool": tool, "ok": True, "result": payload}


def _profile_from_args(args: Dict[str, Any]) -> Dict[str, Any]:
    raw = args.get("profile")
    if isinstance(raw, dict):
        profile_input = dict(raw)
        if args.get("track") and not profile_input.get("track"):
            profile_input["track"] = args["track"]
        return engine.normalize_profile(profile_input)
    flat = {key: args.get(key) for key in (
        "age", "birth_year", "birth_date", "sex", "gender", "sido", "sigungu",
        "income_band", "income_percent", "household_size", "situations",
        "children_years", "children_ages", "track", "biz_status", "biz_entity",
        "biz_years", "biz_industry",
    ) if args.get(key) not in (None, "")}
    if isinstance(args.get("region"), (dict, str)):
        flat["region"] = args["region"]
    if isinstance(args.get("business"), dict):
        flat["business"] = args["business"]
    return engine.normalize_profile(flat)


def _result_row(row: Dict[str, Any], *, detail: bool = False) -> Dict[str, Any]:
    keys = ("service_id", "name", "agency", "agency_type", "field", "field_label",
            "benefit_kind", "region", "support_type", "track", "track_label", "verdict", "why",
            "matched_conditions", "missing_information", "criteria_state", "criteria_flags",
            "criteria_excerpt", "amount", "application", "contact", "detail_url",
            "online_url", "tags", "source", "source_label", "attribution_ko",
            "business", "business_summary_ko", "source_updated_at", "notes_ko", "data_state")
    if detail:
        keys = keys + ("documents",)
    return {key: row.get(key) for key in keys if key in row}


# ---------------------------------------------------------------------------
# 툴 1 — search_subsidies
# ---------------------------------------------------------------------------
def tool_search_subsidies(args: Dict[str, Any], catalog: Catalog, store: Any = None) -> Dict[str, Any]:
    profile = _profile_from_args(args)
    limit = int(args.get("limit") or 10)
    result = engine.search(
        catalog, profile,
        limit=max(1, min(limit, 50)),
        include_ineligible=bool(args.get("include_ineligible")),
        include_closed=bool(args.get("include_closed")),
        tag=str(args.get("tag") or "").strip() or None,
        keyword=str(args.get("keyword") or "").strip() or None,
        balance_kinds=bool(args.get("balance_kinds")),
    )
    region_info = profile.get("region") or {}
    payload: Dict[str, Any] = {
        "profile": engine.explain_profile(profile),
        "track": result["track"],
        "track_counts": result["track_counts"],
        "counts": result["counts"],
        "scanned": result["scanned"],
        "truncated": result["truncated"],
        "ineligible_hidden": result["ineligible_hidden"],
        "closed_hidden": result["closed_hidden"],
        "local_portal_status": local_portals.coverage_status(
            region_info.get("sido"), region_info.get("sigungu")
        ),
        "results": [_result_row(row) for row in result["results"]],
        "next_questions": profile["missing_core"],
        "scope_limits_ko": SCOPE_LIMITS_KO,
    }
    if result["track"] == programs.TRACK_BUSINESS:
        payload["track_note_ko"] = (
            "창업·기업 트랙입니다. '받을 가능성 높음'은 신청자격 충족을 뜻하며, 선정은 평가·경쟁으로 "
            "결정됩니다. 모집이 마감된 공고는 기본으로 숨깁니다(include_closed=true 로 포함)."
        )
    elif result["track"] == "all" and not (profile.get("business") or {}).get("declared"):
        payload["track_note_ko"] = (
            "사업자·창업 조건을 입력하지 않아 개인·가구 트랙만 보여 주었습니다. 창업·소상공인 "
            "지원사업까지 보려면 track='business' 또는 business 조건을 넣어 주세요."
        )
    if not result["results"]:
        payload["empty_note_ko"] = (
            "입력 조건에서 후보가 나오지 않았습니다. 거주 시·도(시·군·구)와 소득구간, "
            "해당 상황(임신·출산·무주택 등) 또는 사업자 조건(예비/운영, 업력)을 확인해 "
            "다시 시도해 주세요. 제도가 없다는 뜻은 아닙니다."
        )
    return _envelope("search_subsidies", payload, catalog)


# ---------------------------------------------------------------------------
# 툴 2 — check_eligibility
# ---------------------------------------------------------------------------
def tool_check_eligibility(args: Dict[str, Any], catalog: Catalog, store: Any = None) -> Dict[str, Any]:
    service_id = str(args.get("service_id") or "").strip()
    if not service_id:
        raise ValueError("service_id_required")
    service = catalog.get(service_id)
    if service is None:
        raise ValueError("service_not_found")
    profile = _profile_from_args(args)
    row = engine.evaluate_service(service, profile)
    payload: Dict[str, Any] = {
        "profile": engine.explain_profile(profile),
        "service": _result_row(row, detail=True),
        "summary_ko": (
            f"{row['name']} — {row['verdict']['label_ko']}. "
            + (" ".join(rule["reason_ko"] for rule in row["why"]
                        if rule["state"] in ("fail", "unknown")) or
               "입력 조건과 공개된 자격 코드가 일치했습니다.")
        ),
        "scope_limits_ko": SCOPE_LIMITS_KO,
    }
    return _envelope("check_eligibility", payload, catalog)


# ---------------------------------------------------------------------------
# 툴 3 — get_subsidy_detail
# ---------------------------------------------------------------------------
def tool_get_subsidy_detail(args: Dict[str, Any], catalog: Catalog, store: Any = None) -> Dict[str, Any]:
    service_id = str(args.get("service_id") or "").strip()
    if not service_id:
        raise ValueError("service_id_required")
    service = catalog.get(service_id)
    if service is None:
        raise ValueError("service_not_found")
    detail = service.summary(detail=True)
    payload: Dict[str, Any] = {
        "service": detail,
        "criteria_state": "present" if service.has_criteria else "missing",
        "criteria_note_ko": (
            "선정기준 원문이 비어 있습니다(지자체 제도에서 흔함). 소관기관에 직접 확인해야 합니다."
            if not service.has_criteria else
            "선정기준 원문을 함께 실었습니다. 코드로 표현되지 않은 요건은 이 문장을 기준으로 확인하세요."
        ),
        "condition_catalog": [
            {"code": code, "group": conditions.CODE_CATALOG[code][0],
             "label": conditions.CODE_CATALOG[code][1]}
            for code in service.conditions
        ],
        "scope_limits_ko": SCOPE_LIMITS_KO,
    }
    if isinstance(args.get("profile"), dict):
        profile = engine.normalize_profile(args["profile"])
        verdict_row = engine.evaluate_service(service, profile)
        payload["verdict"] = verdict_row["verdict"]
        payload["why"] = verdict_row["why"]
        payload["missing_information"] = verdict_row["missing_information"]
    return _envelope("get_subsidy_detail", payload, catalog)


# ---------------------------------------------------------------------------
# 툴 4 — list_region_subsidies
# ---------------------------------------------------------------------------
def tool_list_region_subsidies(args: Dict[str, Any], catalog: Catalog, store: Any = None) -> Dict[str, Any]:
    sido = str(args.get("sido") or "").strip()
    sigungu = str(args.get("sigungu") or "").strip()
    if not sido and not sigungu:
        raise ValueError("region_required")
    block = regions.region_block(sido, sigungu)
    if block["level"] not in ("sido", "sigungu"):
        raise ValueError("region_unresolved")
    include_national = bool(args.get("include_national", True))
    track = str(args.get("track") or "all").strip().lower()
    if track not in ("all", programs.TRACK_PERSONAL, programs.TRACK_BUSINESS):
        track = "all"
    limit = max(1, min(int(args.get("limit") or 50), 200))
    services = catalog.by_region(block.get("sido"), block.get("sigungu"),
                                 include_national=include_national)
    if track != "all":
        services = [svc for svc in services if svc.track == track]
    services.sort(key=lambda svc: (svc.region.get("level") == "national", svc.name))
    rows = []
    for svc in services[:limit]:
        rows.append({
            "service_id": svc.service_id,
            "name": svc.name,
            "agency": svc.agency,
            "region": svc.region,
            "track": svc.track,
            "track_label": svc.track_label,
            "field_label": svc.field_label,
            "target": svc.target,
            "amount": svc.content,
            "support_type": svc.support_type,
            "deadline": svc.deadline,
            "contact": svc.contact,
            "detail_url": svc.detail_url,
            "criteria_state": "present" if svc.has_criteria else "missing",
            "business_summary_ko": svc.business_summary_text or None,
            "source": svc.source,
            "data_state": svc.source,
        })
    payload: Dict[str, Any] = {
        "region": block,
        "track": track,
        "count": len(services),
        "shown": len(rows),
        "local_count": sum(1 for svc in services if svc.region.get("level") != "national"),
        "national_included": include_national,
        "services": rows,
        "note_ko": (
            f"{block['label']} 소관 제도와 전국 제도를 함께 표시합니다. "
            "지역 판별은 소관기관명을 기준으로 하며, '중구'처럼 여러 시도에 있는 이름은 "
            "시·도를 함께 입력해야 정확합니다. 창업·기업 공고의 지역은 지원지역(전국/시·도) "
            "표기를 씁니다."
        ),
    }
    return _envelope("list_region_subsidies", payload, catalog)


# ---------------------------------------------------------------------------
# 툴 5 — deadline_calendar
# ---------------------------------------------------------------------------
def tool_deadline_calendar(args: Dict[str, Any], catalog: Catalog,
                           store: Any = None) -> Dict[str, Any]:
    """마감 임박 지원금·지원사업 캘린더(두 트랙 통합)."""
    try:
        days = int(args.get("days") or 30)
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, 365))
    track = str(args.get("track") or "all").strip().lower()
    if track not in ("all", programs.TRACK_PERSONAL, programs.TRACK_BUSINESS):
        track = "all"
    today = date.today()
    until = today + timedelta(days=days)
    sido = str(args.get("sido") or "").strip()
    sigungu = str(args.get("sigungu") or "").strip()
    services = catalog.services
    if sido or sigungu:
        block = regions.region_block(sido, sigungu)
        if block["level"] in ("sido", "sigungu"):
            services = catalog.by_region(block.get("sido"), block.get("sigungu"),
                                         include_national=True)
    if track != "all":
        services = [svc for svc in services if svc.track == track]
    keyword = str(args.get("keyword") or "").strip()
    if keyword:
        services = [svc for svc in services if keyword in svc.name]

    by_day: Dict[str, List[Dict[str, Any]]] = {}
    unscheduled = 0
    expired = 0
    for svc in services:
        deadline = svc.deadline
        end = deadline.get("end_date")
        if not end:
            unscheduled += 1
            continue
        try:
            end_date = date.fromisoformat(str(end))
        except ValueError:
            unscheduled += 1
            continue
        if end_date < today:
            expired += 1
            continue
        if end_date > until:
            continue
        by_day.setdefault(end_date.isoformat(), []).append({
            "service_id": svc.service_id,
            "name": svc.name,
            "agency": svc.agency,
            "track": svc.track,
            "track_label": svc.track_label,
            "field_label": svc.field_label,
            "days_left": (end_date - today).days,
            "deadline_text": svc.deadline_text,
            "detail_url": svc.detail_url,
            "contact": svc.contact,
            "source": svc.source,
        })
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    calendar: List[Dict[str, Any]] = []
    total = 0
    for day in sorted(by_day):
        rows = sorted(by_day[day], key=lambda row: (row["track"], row["name"]))
        total += len(rows)
        calendar.append({
            "date": day,
            "weekday_ko": weekdays[date.fromisoformat(day).weekday()],
            "days_left": (date.fromisoformat(day) - today).days,
            "count": len(rows),
            "services": rows,
        })
    limit = max(1, min(int(args.get("limit") or 50), 200))
    payload: Dict[str, Any] = {
        "from": today.isoformat(),
        "to": until.isoformat(),
        "days": days,
        "track": track,
        "total": total,
        "shown": min(total, limit),
        "calendar": _trim_calendar(calendar, limit),
        "without_date_count": unscheduled,
        "expired_count": expired,
        "note_ko": (
            "마감일을 확실히 읽은 제도만 넣었습니다. '상시신청'·'예산 소진 시까지'·'별도 공고'는 "
            "날짜가 없어 빠졌고, 그 수를 without_date_count 로 함께 알립니다. 지난 제도는 "
            "expired_count 입니다."
        ),
    }
    return _envelope("deadline_calendar", payload, catalog)


def _trim_calendar(calendar: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    remaining = limit
    for day in calendar:
        if remaining <= 0:
            break
        rows = day["services"][:remaining]
        out.append({**day, "services": rows, "count": len(rows)})
        remaining -= len(rows)
    return out


# ---------------------------------------------------------------------------
# 툴 6 — compare_ledgers
# ---------------------------------------------------------------------------
def tool_compare_ledgers(args: Dict[str, Any], catalog: Catalog,
                         store: Any = None) -> Dict[str, Any]:
    """일자별 카탈로그 스냅샷(장부) 비교 — 추가·삭제·조건 변경."""
    from .catalog import data_dir_from_env

    directory = snapshots.snapshot_dir(data_dir_from_env())
    from_day = str(args.get("from_date") or "").strip() or None
    to_day = str(args.get("to_date") or "").strip() or None
    try:
        limit = int(args.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    diff = snapshots.compare_days(from_day, to_day, directory,
                                  limit=max(1, min(limit, 200)),
                                  service_id=str(args.get("service_id") or "").strip() or None)
    if not diff.get("ok"):
        return _envelope("compare_ledgers", {
            "available_days": diff.get("available_days") or [],
            "reason_ko": diff.get("message_ko"),
            "error": diff.get("error"),
            "scope_limits_ko": SCOPE_LIMITS_KO,
        }, catalog)
    diff["summary_ko"] = (
        f"{diff['from_day']} → {diff['to_day']} 사이에 제도 {diff['counts']['added']}건 추가, "
        f"{diff['counts']['removed']}건 삭제, {diff['counts']['changed']}건 조건 변경."
    )
    diff["scope_limits_ko"] = SCOPE_LIMITS_KO
    return _envelope("compare_ledgers", diff, catalog)


# ---------------------------------------------------------------------------
# 툴 5 — get_service_meta
# ---------------------------------------------------------------------------
def tool_get_service_meta(args: Dict[str, Any], catalog: Catalog, store: Any = None) -> Dict[str, Any]:
    latest = snapshots.latest_day(snapshots.snapshot_dir(data_dir_hint()))
    payload: Dict[str, Any] = {
        "service": "GRNT",
        "service_title_ko": "개인·창업 통합 지원금 판정기",
        "tagline": "Grants, simplified.",
        "stage": "MVP · 무료 · 결제 없음",
        "tracks": [
            {"key": programs.TRACK_PERSONAL, "label_ko": "개인·가구",
             "sources": ["gov24"],
             "basis_ko": "정부24 보조금24 자격 코드(JA)로 판정"},
            {"key": programs.TRACK_BUSINESS, "label_ko": "창업·소상공인·기업",
             "sources": ["kstartup", "bizinfo"],
             "basis_ko": "공고의 구조화된 신청자격(업력·연령·지역·대상·성별)으로 판정"},
        ],
        "sources": [
            {"key": source, "label_ko": programs.source_label(source),
             "attribution_ko": programs.source_attribution(source)}
            for source in ("gov24", programs.SOURCE_KSTARTUP, programs.SOURCE_BIZINFO, "sample")
        ],
        "verdicts": [
            {"code": code, "label_ko": models.VERDICT_LABELS_KO[code],
             "label_en": models.VERDICT_LABELS_EN[code],
             "definition_ko": models.VERDICT_DEFINITIONS_KO[code]}
            for code in models.VERDICT_ORDER
        ],
        "condition_codes": [
            {"code": code, "group": group, "label": label}
            for code, (group, label) in conditions.CODE_CATALOG.items()
        ],
        "situations": [
            {"key": key, "label_ko": spec["label_ko"], "codes": spec["codes"]}
            for key, spec in conditions.SITUATIONS.items()
        ],
        "business_entities": [
            {"key": key, "label_ko": programs.ENTITY_LABELS[key]}
            for key in programs.BUSINESS_ENTITIES
        ],
        "business_industries": [
            {"key": key, "label_ko": label} for key, label in programs.INDUSTRY_LABELS.items()
        ],
        "business_status": [
            {"key": "pre", "label_ko": "예비창업자"},
            {"key": "operating", "label_ko": "사업자등록 후 운영 중"},
        ],
        "sido_list": regions.sido_names(),
        "profile_fields": {
            "track": "all | personal | business",
            "age": "만 나이(정수)",
            "birth_year": "출생연도(만 나이 계산)",
            "sex": "male | female",
            "region": {"sido": "예: 인천광역시", "sigungu": "예: 서구"},
            "household_size": "가구원 수",
            "income_percent": "기준 중위소득 % (예: 80)",
            "income_band": "JA0201~JA0205 중 하나",
            "situations": list(conditions.SITUATIONS),
            "children_years": "자녀 출생연도 목록(아동 대상 제도 판정용)",
            "business": {
                "status": "pre(예비창업자) | operating(사업자)",
                "entity": list(programs.BUSINESS_ENTITIES),
                "years": "업력(년, 숫자)",
                "industry": list(programs.INDUSTRY_LABELS),
            },
        },
        "snapshots": {
            "available_days": len(snapshots.list_snapshots(snapshots.snapshot_dir(data_dir_hint()))),
            "latest_day": latest,
            "note_ko": (
                "`python -m subsidy_kr.sync_gov24 --sources all` 을 실행할 때마다 "
                "`snapshots/{날짜}.json` 이 쌓이고, `compare_ledgers` 로 날짜 간 변화를 비교합니다."
            ),
        },
        "privacy": {
            "stores_profile": False,
            "requires_login": False,
            "requires_resident_number": False,
            "counter_granularity": "일별 · 툴 · 판정 등급 (IP·쿠키·프로필 미저장)",
        },
        "scope_limits_ko": SCOPE_LIMITS_KO,
        "tools": [definition["name"] for definition in TOOL_DEFS],
        "stats": catalog.stats(),
    }
    return _envelope("get_service_meta", payload, catalog)


def data_dir_hint() -> Optional[str]:
    """스냅샷 디렉터리 계산용(카탈로그 경로와 같은 기본 디렉터리를 쓴다)."""
    from .catalog import data_dir_from_env

    return data_dir_from_env()


# ---------------------------------------------------------------------------
# 레지스트리
# ---------------------------------------------------------------------------
PROFILE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": (
        "판정에 쓰는 사용자 조건. 없는 항목은 '모름'으로 보고 판정하지 않습니다. "
        "개인은 나이·지역·소득·상황, 창업·기업은 business 블록(예비/운영, 업력, 업종)을 씁니다."
    ),
    "properties": {
        "track": {"type": "string", "enum": ["all", "personal", "business"],
                  "description": "개인·가구는 personal, 창업·소상공인·기업은 business. 기본 all."},
        "age": {"type": "integer", "minimum": 0, "maximum": 120, "description": "만 나이"},
        "birth_year": {"type": "integer", "minimum": 1900, "maximum": 2100},
        "sex": {"type": "string", "enum": ["male", "female"]},
        "region": {
            "type": "object",
            "properties": {"sido": {"type": "string"}, "sigungu": {"type": "string"}},
            "description": "개인은 거주지, 사업자는 사업장 소재지.",
        },
        "household_size": {"type": "integer", "minimum": 1, "maximum": 20},
        "income_percent": {"type": "number", "minimum": 0, "maximum": 1000,
                           "description": "기준 중위소득 %"},
        "income_band": {"type": "string", "enum": conditions.INCOME_BANDS},
        "situations": {
            "type": "array",
            "items": {"type": "string", "enum": conditions.situation_keys()},
            "description": "해당하는 상황 태그. 빈 배열이면 '해당 없음'으로 판정합니다.",
        },
        "children_years": {
            "type": "array", "items": {"type": "integer"},
            "description": "자녀 출생연도. 아동 대상 제도의 연령 판정에 씁니다.",
        },
        "business": {
            "type": "object",
            "description": "창업·기업 조건. status만 있어도 대부분 판정됩니다.",
            "properties": {
                "status": {"type": "string", "enum": ["pre", "operating"],
                           "description": "pre=예비창업자, operating=사업자등록 후 운영 중"},
                "entity": {"type": "string", "enum": programs.BUSINESS_ENTITIES},
                "years": {"type": "number", "minimum": 0, "maximum": 60,
                          "description": "업력(창업 후 경과 연수)"},
                "industry": {"type": "string", "enum": list(programs.INDUSTRY_LABELS)},
            },
        },
    },
}

TOOL_DEFS: List[Dict[str, Any]] = [
    {
        "name": "search_subsidies",
        "title_ko": "내 조건 맞춤 지원금 찾기",
        "description_ko": (
            "나이·성별·거주지·소득구간·상황(임신·출산·무주택·구직·장애 등)과 "
            "사업자 조건(예비창업자/운영 중, 업력, 소상공인·중소기업, 업종)을 주면 "
            "정부·지자체 지원금과 창업·소상공인·기업 지원사업 후보를 "
            "'받을 가능성 높음 / 조건 확인 필요 / 정보 부족'으로 나눠 사유·금액·신청기한·"
            "문의처와 함께 돌려줍니다. 모르는 항목은 비워 두면 '정보 부족'으로 답하고 "
            "무엇을 더 물어야 하는지 알려 줍니다."
        ),
        "handler": tool_search_subsidies,
        "input_schema": {
            "type": "object",
            "properties": {
                "profile": PROFILE_SCHEMA,
                "track": {"type": "string", "enum": ["all", "personal", "business"],
                          "description": "트랙 선택. business 면 창업·기업 공고만 봅니다."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "include_ineligible": {"type": "boolean", "default": False,
                                       "description": "해당 없음까지 포함할지"},
                "include_closed": {"type": "boolean", "default": False,
                                   "description": "모집 마감된 공고도 포함할지"},
                "tag": {"type": "string", "description": "청년·주거·창업·자금 등 주제 필터"},
                "keyword": {"type": "string", "description": "제도명·내용 키워드"},
            },
            "required": ["profile"],
        },
    },
    {
        "name": "check_eligibility",
        "title_ko": "제도 1건 정밀 판정",
        "description_ko": (
            "제도ID(service_id)와 프로필로 한 제도의 자격을 정밀 판정합니다. "
            "어긋난 항목·필요한 추가 정보·선정기준 원문·문의처를 함께 반환합니다."
        ),
        "handler": tool_check_eligibility,
        "input_schema": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "search_subsidies 결과의 service_id"},
                "profile": PROFILE_SCHEMA,
            },
            "required": ["service_id", "profile"],
        },
    },
    {
        "name": "get_subsidy_detail",
        "title_ko": "제도 상세(원문 요약)",
        "description_ko": (
            "제도 1건의 목적·지원대상·선정기준 원문·지원내용·신청방법·신청기한·구비서류·"
            "문의처·온라인 신청 링크를 반환합니다. 프로필을 함께 주면 판정도 붙습니다."
        ),
        "handler": tool_get_subsidy_detail,
        "input_schema": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string"},
                "profile": PROFILE_SCHEMA,
            },
            "required": ["service_id"],
        },
    },
    {
        "name": "list_region_subsidies",
        "title_ko": "지역 지원금 목록",
        "description_ko": (
            "시·도(또는 시·군·구) 이름으로 그 지역 소관 제도와 전국 제도를 나열합니다. "
            "지역 판별은 소관기관명을 기준으로 합니다."
        ),
        "handler": tool_list_region_subsidies,
        "input_schema": {
            "type": "object",
            "properties": {
                "sido": {"type": "string", "description": "예: 인천광역시, 경기"},
                "sigungu": {"type": "string", "description": "예: 서구, 수원시 장안구"},
                "track": {"type": "string", "enum": ["all", "personal", "business"],
                          "default": "all"},
                "include_national": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            "required": ["sido"],
        },
    },
    {
        "name": "deadline_calendar",
        "title_ko": "마감 임박 지원금 캘린더",
        "description_ko": (
            "앞으로 N일(기본 30일) 안에 마감되는 지원금·창업지원사업을 날짜별로 보여 줍니다. "
            "두 트랙(개인·창업)을 함께 또는 따로 볼 수 있고, 마감일을 확실히 읽은 것만 넣으며 "
            "'상시신청·예산 소진 시'처럼 날짜가 없는 건수도 함께 알립니다."
        ),
        "handler": tool_deadline_calendar,
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30},
                "track": {"type": "string", "enum": ["all", "personal", "business"],
                          "default": "all"},
                "sido": {"type": "string", "description": "지역으로 좁힐 때(예: 인천광역시)"},
                "sigungu": {"type": "string"},
                "keyword": {"type": "string", "description": "제도명 키워드"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            "required": [],
        },
    },
    {
        "name": "compare_ledgers",
        "title_ko": "지원금 카탈로그 변화 비교",
        "description_ko": (
            "일자별로 저장한 카탈로그 스냅샷(장부) 두 장을 비교해 새로 올라온 제도·빠진 제도·"
            "기간/금액/대상/모집상태가 바뀐 제도를 알려 줍니다. 날짜를 주지 않으면 최근 두 장을 "
            "비교합니다."
        ),
        "handler": tool_compare_ledgers,
        "input_schema": {
            "type": "object",
            "properties": {
                "from_date": {"type": "string", "description": "YYYY-MM-DD (비교 기준일)"},
                "to_date": {"type": "string", "description": "YYYY-MM-DD (기본: 최신)"},
                "service_id": {"type": "string", "description": "한 제도만 볼 때"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            "required": [],
        },
    },
    {
        "name": "get_service_meta",
        "title_ko": "서비스·데이터 상태",
        "description_ko": (
            "카탈로그 상태(실데이터/샘플), 판정 등급 정의, 자격 코드 목록, 입력 가능한 "
            "상황 태그, 개인정보 설계를 반환합니다."
        ),
        "handler": tool_get_service_meta,
        "input_schema": {"type": "object", "properties": {}},
    },
]

TOOL_INDEX: Dict[str, Dict[str, Any]] = {definition["name"]: definition for definition in TOOL_DEFS}
TOOL_ANNOTATIONS = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}


def mcp_tools() -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []
    for definition in TOOL_DEFS:
        entry: Dict[str, Any] = {
            "name": definition["name"],
            "title": definition["title_ko"],
            "description": definition["description_ko"],
            "inputSchema": definition["input_schema"],
            "annotations": {**TOOL_ANNOTATIONS, "title": definition["title_ko"]},
        }
        tools.append(entry)
    return tools


def mcp_manifest() -> Dict[str, Any]:
    return {
        "name": "grnt",
        "version": "grnt/0.2",
        "description": (
            "GRNT — 한국 개인·창업 지원금 자격 판정 MCP. 정부24 보조금24 자격 코드와 "
            "K-Startup·기업마당 공고의 신청자격으로 결정론 판정하고, 사유·누락 정보·출처를 함께 준다."
        ),
        "serverInfo": {"name": "grnt", "version": "grnt/0.2"},
        "tools": [
            {"name": d["name"], "title": d["title_ko"],
             "description": d["description_ko"], "inputSchema": d["input_schema"]}
            for d in TOOL_DEFS
        ],
    }


def call_tool(name: str, arguments: Optional[Dict[str, Any]], catalog: Catalog,
              client_id: str = "anonymous", store: Any = None) -> Dict[str, Any]:
    if name not in TOOL_INDEX:
        return {"ok": False, "error": "unknown_tool", "tool": name}
    try:
        result = TOOL_INDEX[name]["handler"](arguments or {}, catalog, store)
    except ValueError as exc:
        result = {"tool": name, "ok": False, "error": "invalid_argument",
                  "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - 공개 배포에서 내부 정보를 노출하지 않는다
        result = {"tool": name, "ok": False, "error": "internal_error",
                  "message": type(exc).__name__}
    usage.record_tool(store, name, result)
    return result


def text_summary(result: Dict[str, Any]) -> str:
    """MCP content 블록에 넣는 사람이 읽는 요약(JSON 앞에 붙인다)."""
    data = result.get("result") if isinstance(result.get("result"), dict) else {}
    if isinstance(data.get("calendar"), list):
        lines = [f"마감 임박 {data.get('total', 0)}건 "
                 f"({data.get('from')} ~ {data.get('to')})"]
        for day in data["calendar"][:5]:
            lines.append(f"· {day['date']}({day.get('weekday_ko', '')}) {day['count']}건: "
                         + ", ".join(row["name"] for row in day["services"][:3]))
        if data.get("without_date_count"):
            lines.append(f"날짜 미기재 {data['without_date_count']}건은 캘린더에서 제외했습니다.")
        return "\n".join(lines)
    if "summary_ko" in data and ("added" in data or "reason_ko" in data):
        return str(data.get("summary_ko") or data.get("reason_ko") or "")
    if data.get("reason_ko") and not data.get("results"):
        return str(data["reason_ko"])
    rows = data.get("results") or []
    if not rows and isinstance(data.get("service"), dict):
        service = data["service"]
        return f"{service.get('name')} — {service.get('verdict', {}).get('label_ko', '')}".strip(" —")
    if not rows:
        return f"결과 {data.get('count', 0) if isinstance(data, dict) else 0}건"
    counts = data.get("counts") or {}
    head = ", ".join(f"{models.VERDICT_LABELS_KO.get(code, code)} {counts.get(code, 0)}건"
                     for code in models.VERDICT_ORDER if counts.get(code))
    hidden = int(data.get("ineligible_hidden") or 0)
    total = sum(counts.values()) - hidden
    lines = [f"후보 {total}건 ({head})" if head else f"후보 {len(rows)}건"]
    for row in rows[:5]:
        lines.append(f"· [{row['verdict']['label_ko']}] {row['name']} ({row['agency']})")
    if len(rows) > 5:
        lines.append(f"… 외 {len(rows) - 5}건")
    if data.get("profile", {}).get("missing_core"):
        lines.append("추가로 알려 주시면 판정이 늘어납니다: "
                     + ", ".join(item["question_ko"] for item in data["profile"]["missing_core"][:3]))
    return "\n".join(lines)
