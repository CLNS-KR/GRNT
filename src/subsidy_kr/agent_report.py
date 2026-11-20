"""사업자·대리인 리포트 — 세무사·노무사·소상공인 지원 담당자를 위한 매칭 모듈.

왜 따로 두는가
--------------
개인 트랙은 '내가 받을 수 있나'를 묻지만, 세무사·노무사·컨설턴트는 **거래처 여러 곳**을
맡기고 "이 사업장이 지금 신청할 만한 공고"를 표로 정리해 전달합니다. 그래서 필요한 것이
세 가지입니다.

1. **업종·규모 기준 판정** — 상시근로자 수와 연매출로 소상공인·소기업·중소기업을 가릅니다.
2. **실무 분류** — 소상공인 / 중소기업 / 고용·노무 / 정책자금·세제 네 묶음으로 나눠
   담당자(세무·노무)가 자기 영역을 바로 봅니다.
3. **전달 가능한 산출물** — 거래처에 보낼 요약 표(CSV·인쇄용 HTML)를 바로 뽑습니다.

기존 판정 엔진(`engine.search`)을 그대로 씁니다. 이 모듈은 **자격 판정을 새로 하지 않고**,
이미 판정된 결과에 규모 추정·분류·우선순위·마감임박 표시를 붙입니다. 그래야 개인 트랙과
규격이 어긋나지 않습니다.

규모 기준 근거
--------------
- 소상공인: 「소상공인기본법」 제2조 제1항 — 「중소기업기본법」상 **소기업**이면서
  상시근로자 수 10명 미만, 주된 사업 상시근로자 수가 광업·제조업·건설업·운수업 10명 미만 /
  그 밖의 업종 5명 미만(시행령 제3조 제1항).
- 소기업 매출 기준: 「중소기업기본법 시행령」 별표 3(2025-09-01 개정) 업종별 평균매출액등.
  아래 표의 금액은 그중 대표 업종 값이며, 세부 업종(한국표준산업분류 중분류)에 따라
  달라질 수 있어 **참고 기준**으로만 씁니다.
- 상시근로자 수는 임원·일용근로자·3개월 이내 기간제·월 60시간 미만 단시간근로자를 빼고,
  월 60시간 이상 단시간근로자는 0.5명으로 세어 직전 사업연도 월평균으로 계산합니다
  (시행령 제3조 제3항·제4항). 입력받는 값은 **이 계산을 마친 인원**입니다.

이 모듈은 개인 식별 정보(상호·대표자·연락처)를 받지도, 남기지도 않습니다.
"""
from __future__ import annotations

import csv
import html
import io
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import engine, programs

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# 1. 실무 분류
# ---------------------------------------------------------------------------
CATEGORY_SMALL_BUSINESS = "small_business"
CATEGORY_SME = "sme"
CATEGORY_LABOR = "labor"
CATEGORY_FINANCE_TAX = "finance_tax"

CATEGORY_ORDER: List[str] = [CATEGORY_SMALL_BUSINESS, CATEGORY_SME, CATEGORY_LABOR,
                            CATEGORY_FINANCE_TAX]

CATEGORY_LABELS_KO: Dict[str, str] = {
    CATEGORY_SMALL_BUSINESS: "소상공인",
    CATEGORY_SME: "중소기업",
    CATEGORY_LABOR: "고용·노무",
    CATEGORY_FINANCE_TAX: "정책자금·세제",
}

CATEGORY_DUTY_KO: Dict[str, str] = {
    CATEGORY_SMALL_BUSINESS: "소상공인 담당(대표·매니저)",
    CATEGORY_SME: "기업 지원·성장 담당",
    CATEGORY_LABOR: "노무 담당(고용·4대보험·훈련)",
    CATEGORY_FINANCE_TAX: "세무 담당(자금·세제·감면)",
}

# 분류 키워드. 순서가 곧 우선순위다 — 같은 공고가 여러 묶음에 걸리면 앞의 것을 주 분류로 쓴다.
_CATEGORY_WORDS: List[Tuple[str, Tuple[str, ...]]] = [
    (CATEGORY_SMALL_BUSINESS,
     ("소상공인", "자영업", "골목상권", "전통시장", "소규모 사업자", "소공인", "상권")),
    (CATEGORY_LABOR,
     ("고용", "일자리", "근로", "채용", "인력", "노무", "사회보험", "두루누리", "직업훈련",
      "훈련", "산업안전", "근로환경", "장려금", "취업", "워라밸", "대체인력")),
    (CATEGORY_FINANCE_TAX,
     ("정책자금", "융자", "대출", "보증", "세액공제", "세제", "감면", "조세", "이자지원",
      "이자", "시설자금", "운전자금", "정책보험", "보험료지원")),
    (CATEGORY_SME,
     ("중소기업", "벤처", "이노비즈", "기술혁신", "수출", "R&D", "연구", "스타트업", "창업")),
]

# 업종별 소상공인·소기업 기준.
#   employee_limit: 「소상공인기본법 시행령」 제3조 제1항의 주된 사업 상시근로자 수 상한(미만)
#   revenue_limit_krw: 「중소기업기본법 시행령」 별표 3(2025-09-01 개정) 평균매출액등 기준
SIZE_RULES: Dict[str, Dict[str, Any]] = {
    "manufacturing": {"employee_limit": 10, "revenue_limit_krw": 12_000_000_000,
                      "revenue_note_ko": "제조업 세부 업종은 120억 원(코크스·1차 금속 등은 140억 원)"},
    "construction": {"employee_limit": 10, "revenue_limit_krw": 8_000_000_000,
                     "revenue_note_ko": "건설업 80억 원"},
    "logistics": {"employee_limit": 10, "revenue_limit_krw": 10_000_000_000,
                  "revenue_note_ko": "운수·창고업 100억 원(창고업 등 세부 업종 확인 필요)"},
    "ict": {"employee_limit": 5, "revenue_limit_krw": 5_000_000_000,
            "revenue_note_ko": "정보통신업 50억 원"},
    "retail": {"employee_limit": 5, "revenue_limit_krw": 6_000_000_000,
               "revenue_note_ko": "도매·소매업 60억 원"},
    "food": {"employee_limit": 5, "revenue_limit_krw": 1_500_000_000,
             "revenue_note_ko": "숙박·음식점업 15억 원"},
    "service": {"employee_limit": 5, "revenue_limit_krw": 3_000_000_000,
                "revenue_note_ko": "전문·과학·기술 서비스업 30억 원, 수리·개인 서비스업 15억 원"},
    "education": {"employee_limit": 5, "revenue_limit_krw": 1_500_000_000,
                  "revenue_note_ko": "교육 서비스업 15억 원"},
    "health": {"employee_limit": 5, "revenue_limit_krw": 1_500_000_000,
               "revenue_note_ko": "보건·사회복지 서비스업 15억 원"},
    "culture": {"employee_limit": 5, "revenue_limit_krw": 3_000_000_000,
                "revenue_note_ko": "예술·스포츠·여가 서비스업 30억 원"},
    "agri": {"employee_limit": 5, "revenue_limit_krw": 8_000_000_000,
             "revenue_note_ko": "농업·임업·어업 80억 원"},
    "finance": {"employee_limit": 5, "revenue_limit_krw": 10_000_000_000,
                "revenue_note_ko": "금융·보험업 100억 원"},
    "energy": {"employee_limit": 5, "revenue_limit_krw": 4_000_000_000,
               "revenue_note_ko": "수도·하수·폐기물 처리업 40억 원"},
    "etc": {"employee_limit": 5, "revenue_limit_krw": 3_000_000_000,
            "revenue_note_ko": "업종 세분류 확인 필요(참고 30억 원)"},
}

# 입력 별칭 → programs.INDUSTRY_LABELS 키. 화면·API 에서 편하게 부르는 이름을 받는다.
INDUSTRY_ALIASES: Dict[str, str] = {
    "제조": "manufacturing", "제조업": "manufacturing", "manufacturing": "manufacturing",
    "도소매": "retail", "도소매업": "retail", "유통": "retail", "retail": "retail",
    "음식숙박": "food", "음식점": "food", "음식점업": "food", "외식": "food", "숙박": "food",
    "food": "food",
    "it": "ict", "it·서비스": "ict", "it서비스": "ict", "정보통신": "ict", "ict": "ict",
    "서비스": "service", "서비스업": "service", "service": "service",
    "건설": "construction", "construction": "construction",
    "물류": "logistics", "운수": "logistics", "logistics": "logistics",
    "농림어업": "agri", "농업": "agri", "agri": "agri",
    "금융": "finance", "finance": "finance",
    "교육": "education", "education": "education",
    "보건의료": "health", "의료": "health", "health": "health",
    "문화관광": "culture", "문화": "culture", "culture": "culture",
    "환경에너지": "energy", "에너지": "energy", "energy": "energy",
    "기타": "etc", "etc": "etc",
}

# '창업'을 업종으로 받으면 업종이 아니라 신분 조건이다 — 업종은 비워 두고 상태만 pre 로 둔다.
STARTUP_WORDS = ("창업", "창업기업", "예비창업", "예비창업자", "스타트업", "startup")

D7_DAYS = 7

DISCLAIMER_KO = (
    "본 리포트는 공개 데이터(정부24 보조금24·K-Startup·기업마당)를 이용한 참고용 사전 점검이며, "
    "수급·선정 자격을 확정하지 않습니다. 신청 전 소관기관 원문과 담당 부서에 확인하세요."
)

SIZE_BASIS_KO = (
    "소상공인이란 「소상공인기본법」 제2조 제1항에 따라 「중소기업기본법」상 소기업이면서 "
    "상시근로자 수 10명 미만이고, 주된 사업 상시근로자 수가 광업·제조업·건설업·운수업 10명 미만 / "
    "그 밖의 업종 5명 미만인 사업자입니다(시행령 제3조 제1항). 소기업 여부는 같은 법 시행령 "
    "별표 3(2025-09-01 개정)의 업종별 평균매출액등 기준으로 봅니다."
)

SIZE_EMPLOYEE_NOTE_KO = (
    "상시근로자는 임원·일용근로자·3개월 이내 기간제·월 60시간 미만 단시간근로자를 제외하고, "
    "월 60시간 이상 단시간근로자는 0.5명으로 세어 직전 사업연도 월평균으로 계산합니다"
    "(「소상공인기본법 시행령」 제3조 제3항·제4항). 대표자 본인은 근로자에 포함되지 않습니다."
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip().replace(",", "")))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def resolve_industry(value: Any) -> Optional[str]:
    """'음식숙박'·'food'·'음식·숙박' 같은 입력을 표준 업종 코드로 바꾼다."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw in programs.INDUSTRY_LABELS:
        return raw
    key = raw.lower().replace(" ", "")
    if key in INDUSTRY_ALIASES:
        return INDUSTRY_ALIASES[key]
    # 라벨 문자열("음식·숙박")로 들어온 경우
    compact = raw.replace("·", "").replace("ㆍ", "").replace("/", "").replace(" ", "")
    for slug, label in programs.INDUSTRY_LABELS.items():
        if compact == label.replace("·", "").replace("ㆍ", "").replace("/", "").replace(" ", ""):
            return slug
    for alias, slug in INDUSTRY_ALIASES.items():
        if alias.replace("·", "") == compact:
            return slug
    return None


def _revenue_krw(args: Dict[str, Any]) -> Optional[int]:
    """연매출을 원 단위로 읽는다. `annual_revenue_krw` 또는 `annual_revenue_eok`(억원)."""
    krw = _as_int(args.get("annual_revenue_krw"))
    if krw is None:
        revenue = args.get("annual_revenue") or args.get("revenue")
        eok = _as_float(args.get("annual_revenue_eok"))
        if eok is not None:
            krw = int(round(eok * 100_000_000))
        elif isinstance(revenue, str) and "억" in revenue:
            number = _as_float(revenue.replace("억", "").replace("원", "").strip())
            krw = int(round(number * 100_000_000)) if number is not None else None
        else:
            krw = _as_int(revenue)
    if krw is not None and krw < 0:
        krw = None
    return krw


def size_estimate(industry: Optional[str], employees: Optional[int],
                  revenue_krw: Optional[int], status: Optional[str] = None) -> Dict[str, Any]:
    """업종·상시근로자·연매출로 소상공인 해당 여부를 **추정**한다(확정하지 않는다)."""
    rule = SIZE_RULES.get(industry or "") or SIZE_RULES["etc"]
    employee_limit = int(rule["employee_limit"])
    revenue_limit = int(rule["revenue_limit_krw"])
    notes: List[str] = []

    if status == "pre":
        return {
            "status": "pre_startup",
            "small_business_likely": None,
            "employee_limit": employee_limit,
            "revenue_limit_krw": revenue_limit,
            "summary_ko": "예비창업자는 사업자등록 전이라 소상공인·소기업 판정 대상이 아닙니다. "
                          "창업 후 규모가 잡히면 다시 확인하세요.",
            "notes_ko": notes,
            "basis_ko": SIZE_BASIS_KO,
        }

    if employees is None and revenue_krw is None:
        return {
            "status": "insufficient_info",
            "small_business_likely": None,
            "employee_limit": employee_limit,
            "revenue_limit_krw": revenue_limit,
            "summary_ko": "상시근로자 수와 연매출을 넣으면 소상공인·소기업 해당 여부를 판단합니다.",
            "notes_ko": ["상시근로자 수와 연매출은 소상공인 지원사업의 1차 필터입니다."],
            "basis_ko": SIZE_BASIS_KO,
        }

    employee_ok: Optional[bool] = None
    if employees is not None:
        employee_ok = employees < 10 and employees < employee_limit
        if employees >= 10:
            notes.append(f"상시근로자 {employees}명은 소상공인 공통 요건(10명 미만)을 넘습니다.")
        elif employees >= employee_limit:
            notes.append(
                f"상시근로자 {employees}명은 이 업종 기준({employee_limit}명 미만)을 넘습니다."
            )
    revenue_ok: Optional[bool] = None
    if revenue_krw is not None:
        revenue_ok = revenue_krw <= revenue_limit
        if not revenue_ok:
            notes.append(
                f"연매출 {_krw_label(revenue_krw)}은 이 업종 소기업 기준"
                f"({_krw_label(revenue_limit)} 이하)을 넘습니다."
            )

    checks = [value for value in (employee_ok, revenue_ok) if value is not None]
    if len(checks) == 2 and all(checks):
        likely: Optional[bool] = True
        status_code = "likely_small_business"
        summary = (
            f"업종 기준(상시근로자 {employee_limit}명 미만, 연매출 "
            f"{_krw_label(revenue_limit)} 이하)을 충족할 가능성이 높습니다. 소상공인 지원사업을 "
            "우선 검토하세요."
        )
    elif checks and not any(checks):
        likely = False
        status_code = "likely_not_small_business"
        summary = (
            "소상공인 기준을 넘습니다. 중소기업·소기업 지원사업을 우선 검토하세요."
        )
    else:
        # 한 요건은 넘고 다른 요건을 모르는 경우에도 '가능'이라고 말하지 않는다.
        likely = None
        status_code = "partial"
        summary = (
            "일부 요건만 확인했습니다. 남은 값을 넣으면 소상공인·소기업 판정이 확정됩니다."
        )

    if industry in (None, "etc"):
        notes.append("업종을 고르면 적용되는 근로자·매출 기준이 달라집니다(현재는 일반 업종 기준).")
    notes.append(SIZE_EMPLOYEE_NOTE_KO)
    return {
        "status": status_code,
        "small_business_likely": likely,
        "employee_limit": employee_limit,
        "revenue_limit_krw": revenue_limit,
        "revenue_note_ko": rule.get("revenue_note_ko", ""),
        "summary_ko": summary,
        "notes_ko": notes,
        "basis_ko": SIZE_BASIS_KO,
    }


def _krw_label(value: Optional[int]) -> str:
    if value is None:
        return "미입력"
    if value >= 100_000_000:
        eok = value / 100_000_000
        return f"{eok:.0f}억 원" if abs(eok - round(eok)) < 0.05 else f"{eok:.1f}억 원"
    if value >= 10_000:
        return f"{value // 10_000:,}만 원"
    return f"{value:,}원"


# ---------------------------------------------------------------------------
# 2. 분류·우선순위
# ---------------------------------------------------------------------------
def classify_row(row: Dict[str, Any]) -> List[str]:
    """공고 1건이 걸치는 실무 묶음(주 분류가 맨 앞).

    '중소기업'처럼 거의 모든 기업 공고에 붙는 **대상 표시**는 주제가 아닙니다. 그래서
    고용·노무나 정책자금·세제 키워드가 하나라도 걸리면 그쪽을 주 분류로 삼고, 걸리지
    않을 때만 '소상공인' → '중소기업' 순서로 대상을 봅니다. 노무·세무 담당자가 자기 영역
    공고를 놓치지 않게 하려는 규칙입니다.
    """
    text = " ".join([
        str(row.get("name") or ""),
        str(row.get("field_label") or row.get("field") or ""),
        str(row.get("support_type") or ""),
        str(row.get("business_summary_ko") or ""),
        " ".join((row.get("business") or {}).get("hashtags") or []),
    ])
    scores: Dict[str, int] = {}
    for slug, words in _CATEGORY_WORDS:
        hits = [word for word in words if word in text]
        if hits:
            # 긴 키워드(더 구체적인 용어)에 가중치를 준다.
            scores[slug] = sum(len(word) for word in hits)

    subject = [slug for slug in (CATEGORY_LABOR, CATEGORY_FINANCE_TAX) if slug in scores]
    if subject:
        ordered = sorted(subject, key=lambda slug: (-scores[slug],
                                                    (CATEGORY_LABOR, CATEGORY_FINANCE_TAX).index(slug)))
    else:
        ordered = [slug for slug in (CATEGORY_SMALL_BUSINESS, CATEGORY_SME) if slug in scores]
        if not ordered:
            ordered = [CATEGORY_SME if row.get("track") == programs.TRACK_BUSINESS
                       else CATEGORY_SMALL_BUSINESS]
    rest = [slug for slug in CATEGORY_ORDER if slug not in ordered and slug in scores]
    return ordered + rest


def _deadline_days(row: Dict[str, Any]) -> Optional[int]:
    deadline = ((row.get("application") or {}).get("deadline") or {})
    days = deadline.get("days_left")
    if days is None:
        return None
    try:
        return int(days)
    except (TypeError, ValueError):
        return None


def _dday_label(row: Dict[str, Any]) -> str:
    days = _deadline_days(row)
    if days is None:
        deadline = ((row.get("application") or {}).get("deadline") or {})
        return str(deadline.get("label_ko") or row.get("application", {}).get("deadline_text") or "미기재")
    if days < 0:
        return f"마감(D+{abs(days)})"
    if days == 0:
        return "D-DAY"
    return f"D-{days}"


def _priority(row: Dict[str, Any], categories: List[str], *, size: Dict[str, Any],
              industry: Optional[str], region: Dict[str, Any]) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []
    likely = size.get("small_business_likely")
    primary = categories[0]

    if primary == CATEGORY_SMALL_BUSINESS and likely is True:
        score += 4
        reasons.append("소상공인 기준 충족 + 소상공인 대상 공고")
    elif primary == CATEGORY_SME and likely is False:
        score += 3
        reasons.append("소상공인 기준 초과 + 중소기업 대상 공고")
    elif primary == CATEGORY_SME and likely is True:
        score += 1
    elif primary == CATEGORY_LABOR:
        score += 2
        reasons.append("고용·노무 담당 영역")
    elif primary == CATEGORY_FINANCE_TAX:
        score += 2
        reasons.append("자금·세제 담당 영역")

    verdict = (row.get("verdict") or {}).get("code")
    if verdict == "eligible_likely":
        score += 2
    elif verdict == "check_needed":
        score += 1

    days = _deadline_days(row)
    if days is not None and 0 <= days <= D7_DAYS:
        score += 3
        reasons.append(f"마감 D-{days}")
    elif days is not None and days <= 30:
        score += 1

    row_industry = industry or ""
    business = row.get("business") or {}
    if row_industry and business.get("industry_required") and row_industry in (business.get("industries") or []):
        score += 2
        reasons.append("업종 요건 일치")

    level = (row.get("region") or {}).get("level")
    region_level = (region or {}).get("level")
    if level == "sigungu" and region_level == "sigungu":
        score += 1
        reasons.append("시·군·구 단위 공고")
    elif level == "sido" and region_level == "sigungu":
        score += 1

    tier = "high" if score >= 7 else ("medium" if score >= 4 else "low")
    return {
        "score": score,
        "tier": tier,
        "tier_label_ko": {"high": "우선 검토", "medium": "검토", "low": "참고"}[tier],
        "reasons_ko": reasons,
    }


def _normalize_link(url: Any) -> str:
    """공고 원문의 신청 링크를 안전한 http(s) 주소로 정리한다.

    원본 데이터에는 `forms.gle/...` 처럼 스킴이 빠진 값이 섮여 있어 그대로 쓰면 상대 경로가
    되고, `javascript:` 같은 값이 들어오면 클릭 시 실행된다. http(s) 만 통과시킨다.
    """
    text = str(url or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        return text
    if lowered.startswith("//"):
        return "https:" + text
    head = text.split("/", 1)[0]
    if "." in head and " " not in head:
        return "https://" + text
    return ""


def _report_row(row: Dict[str, Any], *, size: Dict[str, Any], industry: Optional[str],
                region: Dict[str, Any]) -> Dict[str, Any]:
    categories = classify_row(row)
    priority = _priority(row, categories, size=size, industry=industry, region=region)
    deadline = ((row.get("application") or {}).get("deadline") or {})
    online = _normalize_link(row.get("online_url"))
    detail = _normalize_link(row.get("detail_url"))
    link = online or detail
    days = _deadline_days(row)
    return {
        "service_id": row.get("service_id"),
        "name": row.get("name"),
        "agency": row.get("agency"),
        "support_type": row.get("support_type") or row.get("field_label") or "",
        "field_label": row.get("field_label"),
        "deadline_text": (row.get("application") or {}).get("deadline_text")
        or deadline.get("label_ko") or "",
        "deadline_date": deadline.get("end_date"),
        "d_day": _dday_label(row),
        "days_left": days,
        "closing_soon": bool(deadline.get("closing_soon")) or (days is not None and 0 <= days <= D7_DAYS),
        "link": link,
        "online_url": online,
        "detail_url": detail,
        "contact": row.get("contact") or "",
        "region_label": ((row.get("region") or {}).get("label") or "전국"),
        "verdict": row.get("verdict"),
        "category": categories[0],
        "category_label": CATEGORY_LABELS_KO.get(categories[0], categories[0]),
        "categories": categories,
        "priority": priority,
        "benefit_kind": row.get("benefit_kind"),
    }


def _sort_key(row: Dict[str, Any]) -> Tuple[int, int, int, str, str]:
    tier_rank = {"high": 0, "medium": 1, "low": 2}.get(row["priority"]["tier"], 3)
    days = row.get("days_left")
    urgency = 0 if (days is not None and 0 <= days <= D7_DAYS) else (1 if days is not None else 2)
    # 이름·service_id 까지 비교해 같은 점수에서도 순서가 프로세스마다 달라지지 않게 한다.
    return (tier_rank, urgency, -int(row["priority"]["score"]), str(row.get("name") or ""),
            str(row.get("service_id") or ""))


# ---------------------------------------------------------------------------
# 3. 리포트 조립
# ---------------------------------------------------------------------------
def _parse_inputs(args: Dict[str, Any]) -> Dict[str, Any]:
    industry_raw = args.get("industry") or args.get("biz_industry")
    startup = any(word in str(industry_raw or "").strip() for word in STARTUP_WORDS)
    industry = resolve_industry(industry_raw)
    employees = _as_int(args.get("employees"))
    if employees is not None and not (0 <= employees <= 100_000):
        employees = None
    revenue = _revenue_krw(args)
    years = _as_float(args.get("biz_years") if args.get("biz_years") is not None else args.get("years"))
    if years is not None and not (0 <= years <= 60):
        years = None
    status_raw = str(args.get("biz_status") or args.get("status") or "").strip().lower()
    status = {"pre": "pre", "예비": "pre", "예비창업": "pre", "예비창업자": "pre",
              "operating": "operating", "운영": "operating", "운영중": "operating"}.get(status_raw)
    if startup and status is None:
        status = "pre"
    entity_raw = str(args.get("biz_entity") or args.get("entity") or "").strip()
    entity = entity_raw if entity_raw in programs.BUSINESS_ENTITIES else None
    age = _as_int(args.get("age"))
    sido = args.get("sido")
    sigungu = args.get("sigungu")
    region_raw = args.get("region")
    if isinstance(region_raw, dict):
        sido = region_raw.get("sido") or sido
        sigungu = region_raw.get("sigungu") or sigungu
    interest_raw = args.get("interest") or args.get("categories") or []
    if isinstance(interest_raw, str):
        interest_raw = [interest_raw]
    interest = [slug for slug in interest_raw
                if slug in CATEGORY_LABELS_KO]
    return {
        "industry": industry,
        "industry_raw": industry_raw,
        "startup_only": startup,
        "employees": employees,
        "revenue_krw": revenue,
        "years": years,
        "status": status,
        "entity": entity,
        "age": age,
        "sido": sido,
        "sigungu": sigungu,
        "interest": interest,
    }


def _engine_profile(spec: Dict[str, Any], size: Dict[str, Any]) -> Dict[str, Any]:
    business: Dict[str, Any] = {}
    status = spec["status"] or ("pre" if spec["startup_only"] else "operating")
    business["status"] = status
    entity = spec["entity"]
    if entity is None and status == "operating":
        # 규모를 모를 때는 '소상공인'으로 둔다 — 소상공인은 중소기업의 부분집합이라
        # 소상공인 전용 공고와 중소기업 공고를 함께 볼 수 있는 가장 넓은 선택이다.
        entity = "sme" if size.get("small_business_likely") is False else "small_business"
    if entity is None and status == "pre":
        entity = "pre_startup"
    if entity:
        business["entity"] = entity
    if spec["years"] is not None:
        business["years"] = spec["years"]
    if spec["industry"]:
        business["industry"] = spec["industry"]
    raw: Dict[str, Any] = {"track": programs.TRACK_BUSINESS, "business": business}
    if spec["age"] is not None:
        raw["age"] = spec["age"]
    if spec["sido"] or spec["sigungu"]:
        raw["region"] = {"sido": spec["sido"], "sigungu": spec["sigungu"]}
    return engine.normalize_profile(raw)


def build_report(catalog: Any, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """거래처 1곳의 지원금 리포트를 만든다(개인 식별 정보는 받지 않는다)."""
    args = args or {}
    spec = _parse_inputs(args)
    size = size_estimate(spec["industry"], spec["employees"], spec["revenue_krw"],
                         spec["status"] or ("pre" if spec["startup_only"] else "operating"))
    profile = _engine_profile(spec, size)
    region = profile.get("region") or {}

    limit = _as_int(args.get("limit")) or 60
    limit = max(1, min(limit, 200))
    include_closed = bool(args.get("include_closed"))
    keyword = str(args.get("keyword") or "").strip() or None
    # 묶음별로 고르게 담으려면 후보를 여유 있게 받아 두고 나중에 나눠 담는다.
    scan_limit = max(limit, min(200, limit * 3))
    search = engine.search(catalog, profile, limit=scan_limit, include_closed=include_closed,
                           keyword=keyword, include_ineligible=bool(args.get("include_ineligible")))

    rows = [_report_row(row, size=size, industry=spec["industry"], region=region)
            for row in search.get("results") or []]
    if spec["interest"]:
        rows = [row for row in rows if row["category"] in spec["interest"]]
    rows.sort(key=_sort_key)

    active = spec["interest"] or list(CATEGORY_ORDER)
    by_category = {slug: [row for row in rows if row["category"] == slug] for slug in active}
    kept = _allocate(by_category, limit)
    kept_ids = {id(row) for row in kept}
    dropped = len(rows) - len(kept)

    sections: List[Dict[str, Any]] = []
    for slug in active:
        group = [row for row in by_category[slug] if id(row) in kept_ids]
        if not group:
            continue
        sections.append({
            "category": slug,
            "category_label": CATEGORY_LABELS_KO[slug],
            "duty_ko": CATEGORY_DUTY_KO[slug],
            "count": len(group),
            "available": len(by_category[slug]),
            "rows": group,
        })

    d7 = [row for row in kept if row.get("days_left") is not None
          and 0 <= int(row["days_left"]) <= D7_DAYS]
    d7.sort(key=lambda row: (int(row["days_left"]), row["priority"]["tier"], row["name"] or ""))

    summary = {
        "total": len(kept),
        "by_category": {slug: len(by_category[slug]) for slug in active},
        "shown_by_category": {section["category"]: section["count"] for section in sections},
        "high_priority": sum(1 for row in kept if row["priority"]["tier"] == "high"),
        "d7_count": len(d7),
        "eligible_likely": sum(1 for row in kept
                               if (row.get("verdict") or {}).get("code") == "eligible_likely"),
        "check_needed": sum(1 for row in kept
                            if (row.get("verdict") or {}).get("code") == "check_needed"),
        "not_shown": max(0, dropped),
    }

    client = {
        "industry": spec["industry"],
        "industry_label": programs.INDUSTRY_LABELS.get(spec["industry"] or "", "미지정"),
        "industry_input": spec["industry_raw"] if spec["industry"] is None else None,
        "employees": spec["employees"],
        "annual_revenue_krw": spec["revenue_krw"],
        "annual_revenue_label": _krw_label(spec["revenue_krw"]),
        "biz_years": spec["years"],
        "biz_status": profile.get("business", {}).get("status"),
        "entity": profile.get("business", {}).get("entity"),
        "entity_label": profile.get("business", {}).get("entity_label"),
        "region": region,
        "region_label": region.get("label") or "전국",
        "interest": spec["interest"],
    }

    payload = {
        "client": client,
        "size_estimate": size,
        "summary": summary,
        "sections": sections,
        "d7": d7,
        "scanned": search.get("scanned", 0),
        "closed_hidden": search.get("closed_hidden", 0),
        "truncated": search.get("truncated", False),
        "track_counts": search.get("track_counts"),
        "missing_core": profile.get("missing_core") or [],
        "checked_at": _now(),
        "schema_version": SCHEMA_VERSION,
        "disclaimer_ko": DISCLAIMER_KO,
        "notes_ko": _report_notes(spec, size),
    }
    return payload


def _allocate(by_category: Dict[str, List[Dict[str, Any]]], budget: int) -> List[Dict[str, Any]]:
    """예산(표시 건수)을 묶음별로 나눠 담는다 — 한 묶음이 전부 차지하지 않게."""
    present = [slug for slug in CATEGORY_ORDER if by_category.get(slug)]
    if not present:
        return []
    per = max(1, budget // len(present))
    kept: List[Dict[str, Any]] = []
    seen = set()
    for slug in present:
        for row in by_category[slug][:per]:
            kept.append(row)
            seen.add(id(row))
    if len(kept) < budget:
        rest = [row for slug in present for row in by_category[slug] if id(row) not in seen]
        rest.sort(key=_sort_key)
        kept.extend(rest[:budget - len(kept)])
    return kept


def _report_notes(spec: Dict[str, Any], size: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    if spec["employees"] is None and spec["status"] != "pre":
        notes.append("상시근로자 수를 넣으면 고용지원사업(두루누리·고용장려금 등) 판정이 정확해집니다.")
    if spec["revenue_krw"] is None and spec["status"] != "pre":
        notes.append("연매출(직전 사업연도)을 넣으면 소상공인·소기업 구분이 확정됩니다.")
    if spec["industry"] is None:
        notes.append("업종을 고르면 업종 제한 공고를 걸러 내고 기준 금액을 정확히 적용합니다.")
    if spec["status"] == "pre":
        notes.append("예비창업자 조건으로 찾았습니다. 사업자등록 후에는 운영 중 조건으로 다시 뽑으세요.")
    if size.get("small_business_likely") is False:
        notes.append("소상공인 기준을 넘어 소상공인 전용 공고는 신청 대상이 아닐 수 있습니다.")
    return notes


# ---------------------------------------------------------------------------
# 4. 내보내기 — CSV · 인쇄용 요약 뷰
# ---------------------------------------------------------------------------
CSV_COLUMNS: List[Tuple[str, str]] = [
    ("구분", "category_label"),
    ("공고명", "name"),
    ("소관기관", "agency"),
    ("지원유형", "support_type"),
    ("마감일", "deadline_date"),
    ("D-day", "d_day"),
    ("신청 링크", "link"),
    ("판정", "_verdict_label"),
    ("우선순위", "_priority_label"),
    ("지역", "region_label"),
    ("문의처", "contact"),
]

CSV_HEADER_NOTE = (
    "GRNT 사업자·대리인 리포트 · 참고용 사전 점검(선정·수급 확정 아님) · "
    "출처: 정부24 보조금24 / 창업진흥원 K-Startup / 중소벤처기업부 기업마당"
)


def _flatten_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for section in report.get("sections") or []:
        for row in section.get("rows") or []:
            item = dict(row)
            item["_verdict_label"] = (row.get("verdict") or {}).get("label_ko", "")
            item["_priority_label"] = (row.get("priority") or {}).get("tier_label_ko", "")
            flat.append(item)
    return flat


def to_csv(report: Dict[str, Any]) -> str:
    """거래처 전달용 CSV(엑셀에서 바로 열리도록 UTF-8 BOM)."""
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([CSV_HEADER_NOTE])
    client = report.get("client") or {}
    writer.writerow([
        f"{client.get('industry_label', '')} · 상시근로자 "
        f"{client.get('employees') if client.get('employees') is not None else '미입력'}명 · "
        f"연매출 {client.get('annual_revenue_label', '미입력')} · "
        f"{client.get('region_label', '')} · 기준일 {(report.get('checked_at') or '')[:10]}"
    ])
    writer.writerow([label for label, _ in CSV_COLUMNS])
    for row in _flatten_rows(report):
        writer.writerow([_csv_cell(row.get(key)) for _, key in CSV_COLUMNS])
    writer.writerow([])
    writer.writerow([report.get("disclaimer_ko", "")])
    return buffer.getvalue()


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    # 엑셀 수식 주입 방지 — 셀이 =, +, -, @ 로 시작하면 앞에 따옴표를 붙인다.
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


PRINT_CSS = """
:root{--ink:#14181f;--soft:#5a6472;--line:#d7dce4;--brand:#123a8c;--warn:#8a3b00;--warn-bg:#fdf1e2}
*{box-sizing:border-box}
body{margin:0;padding:28px 32px 40px;color:var(--ink);background:#fff;
  font-family:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;font-size:12.5px;line-height:1.5}
h1{font-size:19px;margin:0 0 4px}
.sub{margin:0;color:var(--soft);font-size:12px}
.meta{display:flex;flex-wrap:wrap;gap:6px 18px;margin:14px 0 0;padding:10px 12px;
  border:1px solid var(--line);border-radius:6px;background:#fafbfd;font-size:12px}
.meta b{font-weight:700}
h2{font-size:13.5px;margin:20px 0 6px;padding-bottom:4px;border-bottom:2px solid var(--ink)}
h2 small{font-weight:500;color:var(--soft);font-size:11.5px;margin-left:6px}
table{width:100%;border-collapse:collapse;font-size:11.5px}
th,td{border:1px solid var(--line);padding:5px 6px;text-align:left;vertical-align:top}
th{background:#eef1f6;font-weight:700;white-space:nowrap}
td.num{white-space:nowrap}
.d7{color:var(--warn);font-weight:700;background:var(--warn-bg)}
a{color:var(--brand);text-decoration:none;word-break:break-all}
.empty{color:var(--soft);font-size:12px;padding:8px 2px}
.foot{margin-top:22px;padding-top:10px;border-top:1px solid var(--line);color:var(--soft);font-size:11px}
.foot p{margin:3px 0}
.badge{display:inline-block;padding:1px 6px;border-radius:9px;border:1px solid var(--line);font-size:10.5px}
@media print{
  body{padding:10mm 12mm;font-size:10.5pt}
  .noprint{display:none}
  table{font-size:9.5pt}
  tr{page-break-inside:avoid}
  h2{page-break-after:avoid}
}
@page{size:A4;margin:12mm}
"""


def _years_label(value: Any) -> str:
    if value is None:
        return "미입력"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:g}년"


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def to_print_html(report: Dict[str, Any]) -> str:
    """인쇄용 요약 뷰(브라우저 인쇄·PDF 저장용). 외부 자원 없음, 값은 전부 escape."""
    client = report.get("client") or {}
    size = report.get("size_estimate") or {}
    summary = report.get("summary") or {}
    title = (
        f"지원금 리포트 · {client.get('industry_label') or '업종 미지정'} · "
        f"상시근로자 {client.get('employees') if client.get('employees') is not None else '미입력'}명 · "
        f"연매출 {client.get('annual_revenue_label') or '미입력'}"
    )
    parts: List[str] = [
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        f"<title>{_esc(title)}</title><style>{PRINT_CSS}</style></head><body>",
        f"<h1>{_esc(title)}</h1>",
        f"<p class=\"sub\">GRNT 사업자·대리인 리포트 · 기준일 {_esc((report.get('checked_at') or '')[:10])}"
        f" · 후보 {_esc(summary.get('total', 0))}건(마감임박 {_esc(summary.get('d7_count', 0))}건)</p>",
        "<div class=\"meta\">",
        f"<span><b>소재지</b> {_esc(client.get('region_label'))}</span>",
        f"<span><b>업종</b> {_esc(client.get('industry_label'))}</span>",
        f"<span><b>상시근로자</b> {_esc(client.get('employees') if client.get('employees') is not None else '미입력')}명</span>",
        f"<span><b>연매출</b> {_esc(client.get('annual_revenue_label'))}</span>",
        f"<span><b>업력</b> {_esc(_years_label(client.get('biz_years')))}</span>",
        f"<span><b>기업 형태</b> {_esc(client.get('entity_label') or '미지정')}</span>",
        f"<span><b>규모 판단</b> {_esc(size.get('summary_ko'))}</span>",
        "</div>",
    ]

    d7 = report.get("d7") or []
    if d7:
        parts.append("<h2>마감 임박(D-7)<small>이번 주에 신청을 끝내야 하는 공고</small></h2>")
        parts.append(_print_table(d7))

    for section in report.get("sections") or []:
        parts.append(
            f"<h2>{_esc(section.get('category_label'))}"
            f"<small>{_esc(section.get('duty_ko'))} · {_esc(section.get('count'))}건</small></h2>"
        )
        parts.append(_print_table(section.get("rows") or []))

    if not report.get("sections"):
        parts.append("<p class=\"empty\">조건에 맞는 공고가 나오지 않았습니다. 업종·규모·지역을 바꿔 다시 뽑아 보세요.</p>")

    notes = report.get("notes_ko") or []
    parts.append("<div class=\"foot\">")
    parts.append(f"<p>{_esc(report.get('disclaimer_ko'))}</p>")
    parts.append(f"<p>{_esc(SIZE_BASIS_KO)}</p>")
    for note in notes:
        parts.append(f"<p>· {_esc(note)}</p>")
    parts.append("</div></body></html>")
    return "".join(parts)


def _print_table(rows: Iterable[Dict[str, Any]]) -> str:
    head = ("<table><thead><tr><th>공고명</th><th>소관기관</th><th>지원유형</th>"
            "<th>마감일</th><th>D-day</th><th>판정</th><th>신청 링크</th></tr></thead><tbody>")
    body: List[str] = []
    for row in rows:
        soon = row.get("days_left") is not None and 0 <= int(row["days_left"]) <= D7_DAYS
        link = row.get("link") or ""
        link_cell = (f"<a href=\"{_esc(link)}\" target=\"_blank\" rel=\"noopener noreferrer\">신청</a>"
                     if link else "—")
        body.append(
            "<tr>"
            f"<td>{_esc(row.get('name'))}</td>"
            f"<td>{_esc(row.get('agency'))}</td>"
            f"<td>{_esc(row.get('support_type'))}</td>"
            f"<td class=\"num\">{_esc(row.get('deadline_date') or row.get('deadline_text') or '미기재')}</td>"
            f"<td class=\"num{' d7' if soon else ''}\">{_esc(row.get('d_day'))}</td>"
            f"<td>{_esc(((row.get('verdict') or {}).get('label_ko')))}</td>"
            f"<td>{link_cell}</td>"
            "</tr>"
        )
    return head + "".join(body) + "</tbody></table>"


def to_markdown(report: Dict[str, Any], limit: int = 5) -> str:
    """MCP 텍스트 블록용 사람이 읽는 요약."""
    client = report.get("client") or {}
    summary = report.get("summary") or {}
    lines = [
        f"{client.get('industry_label') or '업종 미지정'} · 상시근로자 "
        f"{client.get('employees') if client.get('employees') is not None else '미입력'}명 · "
        f"연매출 {client.get('annual_revenue_label') or '미입력'} · {client.get('region_label')}",
        f"후보 {summary.get('total', 0)}건 · 우선 검토 {summary.get('high_priority', 0)}건 · "
        f"마감임박(D-7) {summary.get('d7_count', 0)}건",
    ]
    for section in report.get("sections") or []:
        lines.append(f"[{section['category_label']}] {section['count']}건 — {section['duty_ko']}")
        for row in (section.get("rows") or [])[:limit]:
            lines.append(f"· {row.get('d_day')} {row.get('name')} ({row.get('agency')})")
    return "\n".join(lines)


def filename_for(report: Dict[str, Any], suffix: str) -> str:
    client = report.get("client") or {}
    stamp = (report.get("checked_at") or "")[:10].replace("-", "") or "report"
    industry = str(client.get("industry") or "all")
    # 파일명에 상호·대표자 같은 식별 정보를 넣지 않는다(업종·날짜만).
    return f"grnt-report-{industry}-{stamp}.{suffix}"
