"""결정론적 자격 판정 엔진.

입력(프로필) → 제도별 자격 조건 대조 → 4단계 판정.
LLM 판단은 개입하지 않습니다. 문장(지원대상·선정기준)은 **설명과 확인 안내**에만 씁니다.

두 트랙
-------
- `personal` : 정부24 보조금24의 JA 자격 코드(성별·연령·소득·생애·가구·업종)로 판정
- `business` : K-Startup·기업마당 공고의 **구조화된 신청자격**(업력·연령·지역·대상·성별)으로 판정

판정 등급
---------
- `eligible_likely`  조건을 모두 충족
- `check_needed`     조건은 맞지만 선정기준 공백·추첨/선착순·모집마감 등 확인 필요
- `insufficient_info` 판정에 필요한 입력이 없음(무엇이 필요한지 함께 반환)
- `ineligible`       조건과 명확히 불일치(어긋난 항목 반환)

지키는 선
---------
1. 모르는 것은 **모른다고** 한다. 입력이 없으면 `insufficient_info`, 원본 기준이 비면 `check_needed`.
2. 코드로 표현되지 않은 요건(재산·거주기간·성적)은 판정을 뒤집지 않되 **항상 함께 알린다**.
3. 아동 대상 제도의 연령 코드는 **신청자가 아니라 아동의 나이**로 본다.
4. 기업 트랙의 `eligible_likely` 는 **신청자격 충족**을 뜻한다. 선정은 평가·경쟁이므로 그 사실을
   `notes_ko` 에 항상 붙인다(심사 결과를 예측하지 않는다).
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import conditions, models, programs, regions, synonyms
from .catalog import Catalog, Service

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"
NOTE = "note"

MAX_CRITERIA_EXCERPT = 240

_REASON_GROUP_LABELS = {
    "region": "거주 지역",
    "gender": "성별",
    "age": "연령",
    "income": "소득구간",
    "life": "생애·직업 상황",
    "household": "가구 형태",
    "business": "창업·사업자 조건",
    "criteria": "선정기준 원문",
}


# ---------------------------------------------------------------------------
# 프로필 정규화
# ---------------------------------------------------------------------------
def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def normalize_profile(raw: Optional[Dict[str, Any]], today: Optional[date] = None) -> Dict[str, Any]:
    """사용자 입력을 판정 가능한 형태로 정리한다(원문 입력은 보관하지 않는다)."""
    raw = raw if isinstance(raw, dict) else {}
    now = today or datetime.now().date()

    birth_year = _as_int(raw.get("birth_year"))
    age = _as_int(raw.get("age"))
    age_basis = "age"
    if age is None and raw.get("birth_date"):
        try:
            born = date.fromisoformat(str(raw["birth_date"])[:10])
            age = now.year - born.year - ((now.month, now.day) < (born.month, born.day))
            age_basis = "birth_date"
        except ValueError:
            age = None
    if age is None and birth_year:
        age = now.year - birth_year
        age_basis = "birth_year"
    if age is not None and (age < 0 or age > 120):
        age = None

    sex_raw = str(raw.get("sex") or raw.get("gender") or "").strip().lower()
    sex = {"male": "male", "m": "male", "남": "male", "남성": "male",
           "female": "female", "f": "female", "여": "female", "여성": "female"}.get(sex_raw, "unknown")

    region_raw = raw.get("region")
    if isinstance(region_raw, dict):
        sido, sigungu = region_raw.get("sido"), region_raw.get("sigungu")
    elif isinstance(region_raw, str) and region_raw.strip():
        parsed_reg = regions.parse_agency_region(region_raw.strip())
        sido = raw.get("sido") or parsed_reg.get("sido")
        sigungu = raw.get("sigungu") or parsed_reg.get("sigungu")
        if not sido and not sigungu:
            parts = region_raw.strip().split(None, 1)
            sido = parts[0]
            sigungu = parts[1] if len(parts) > 1 else None
    else:
        sido, sigungu = raw.get("sido"), raw.get("sigungu")
    region = regions.region_block(sido, sigungu)
    if region["level"] in ("sido", "sigungu") and isinstance(region_raw, dict):
        region = {**region, "level": region_raw.get("level") or region["level"]}

    situations_declared = "situations" in raw
    situations: List[str] = []
    for item in (raw.get("situations") or []):
        key = str(item).strip()
        if key in conditions.SITUATIONS and key not in situations:
            situations.append(key)
    # 알 수 없는 태그는 조용히 버리지 않고 결과에 남긴다.
    ignored = [str(item) for item in (raw.get("situations") or [])
               if str(item).strip() not in conditions.SITUATIONS]

    children_declared = "children_years" in raw or "children_ages" in raw
    child_years = [_as_int(item) for item in (raw.get("children_years") or [])]
    child_ages = [now.year - year for year in child_years if year and year > 1900]
    for item in (raw.get("children_ages") or []):
        value = _as_int(item)
        if value is not None:
            child_ages.append(value)

    income_percent = _as_float(raw.get("income_percent"))
    income_band = str(raw.get("income_band") or "").strip() or None
    if income_band and income_band not in conditions.INCOME_BANDS:
        income_band = None
    if income_band is None and income_percent is not None:
        income_band = conditions.band_for_percent(income_percent)

    household_size = _as_int(raw.get("household_size"))
    if household_size is not None and not (0 < household_size <= 20):
        household_size = None

    # --- 창업·기업 조건 -----------------------------------------------------
    track_raw = str(raw.get("track") or "").strip().lower()
    track = (track_raw if track_raw in (programs.TRACK_PERSONAL, programs.TRACK_BUSINESS)
             else "all")
    biz_raw = raw.get("business") if isinstance(raw.get("business"), dict) else {}
    biz_status_raw = str(biz_raw.get("status") or raw.get("biz_status") or "").strip().lower()
    biz_status = {"pre": "pre", "pre_startup": "pre", "예비": "pre",
                  "예비창업자": "pre", "operating": "operating", "사업자": "operating",
                  "운영": "operating", "운영중": "operating"}.get(biz_status_raw)
    biz_entity_raw = str(biz_raw.get("entity") or raw.get("biz_entity") or "").strip()
    biz_entity = biz_entity_raw if biz_entity_raw in programs.BUSINESS_ENTITIES else None
    if biz_status == "pre" and biz_entity is None:
        biz_entity = "pre_startup"
    if biz_entity == "pre_startup":
        biz_status = biz_status or "pre"
    years_raw = biz_raw.get("years") if biz_raw.get("years") is not None else raw.get("biz_years")
    biz_years = _as_float(years_raw)
    if biz_years is not None and not (0 <= biz_years <= 60):
        biz_years = None
    biz_industry = str(biz_raw.get("industry") or raw.get("biz_industry") or "").strip() or None
    if biz_industry and biz_industry not in programs.INDUSTRY_LABELS:
        biz_industry = None
    business_declared = bool(biz_raw) or any(
        raw.get(key) not in (None, "", [], {})
        for key in ("biz_status", "biz_entity", "biz_years", "biz_industry"))
    business = {
        "declared": business_declared,
        "status": biz_status,
        "entity": biz_entity,
        "entity_label": programs.ENTITY_LABELS.get(biz_entity or "", ""),
        "years": biz_years,
        "industry": biz_industry,
        "industry_label": programs.INDUSTRY_LABELS.get(biz_industry or "", ""),
    }

    profile = {
        "age": age,
        "age_basis": age_basis,
        "birth_year": birth_year,
        "sex": sex,
        "region": region,
        "household_size": household_size,
        "income_percent": income_percent,
        "income_band": income_band,
        "income_band_label": conditions.band_label(income_band) if income_band else None,
        "situations": situations,
        "situations_declared": situations_declared,
        "situation_labels": [conditions.SITUATIONS[key]["label_ko"] for key in situations],
        "ignored_situations": ignored,
        "children_declared": children_declared,
        "children_ages": child_ages,
        "track": track,
        "business": business,
    }
    profile["missing_core"] = _missing_core(profile)
    return profile


def _missing_core(profile: Dict[str, Any]) -> List[Dict[str, str]]:
    missing: List[Dict[str, str]] = []
    track = profile.get("track", "all")
    business = profile.get("business") or {}
    if track == programs.TRACK_BUSINESS:
        if business.get("status") is None:
            missing.append({"key": "biz_status",
                            "question_ko": "예비창업자인지, 사업자등록 후 운영 중인지 알려 주세요."})
        elif business.get("status") == "operating" and business.get("years") is None:
            missing.append({"key": "biz_years",
                            "question_ko": "창업 후 업력(년)을 알려 주세요(예: 2)."})
        if profile["region"]["level"] in ("national", "unknown"):
            missing.append({"key": "region",
                            "question_ko": "사업장(또는 거주) 시·도와 시·군·구를 알려 주세요."})
        return missing
    if profile["age"] is None:
        missing.append({"key": "age", "question_ko": "만 나이(또는 출생연도)를 알려 주세요."})
    if profile["region"]["level"] in ("national", "unknown"):
        missing.append({"key": "region", "question_ko": "거주 시·도와 시·군·구를 알려 주세요."})
    if profile["income_band"] is None:
        missing.append({"key": "income_band",
                        "question_ko": "가구 소득이 기준 중위소득 몇 % 구간인지 알려 주세요."})
    if not profile["situations_declared"]:
        missing.append({"key": "situations",
                        "question_ko": "임신·출산·구직·장애 등 해당하는 상황이 있는지 알려 주세요."})
    return missing


# ---------------------------------------------------------------------------
# 규칙
# ---------------------------------------------------------------------------
def _rule(group: str, state: str, reason_ko: str, **extra: Any) -> Dict[str, Any]:
    return {"group": group, "state": state, "reason_ko": reason_ko, **extra}


def _check_region(service: Service, profile: Dict[str, Any]) -> Dict[str, Any]:
    match = regions.match_region(profile["region"], service.region)
    state = {"match": PASS, "mismatch": FAIL}.get(match["state"], UNKNOWN)
    label = service.region.get("label") or "전국"
    if state == FAIL:
        return _rule("region", FAIL, match["reason_ko"], required=label,
                     user_value=profile["region"].get("label"))
    if state is UNKNOWN:
        return _rule("region", UNKNOWN, match["reason_ko"], required=label,
                     missing_key="region")
    return _rule("region", PASS, f"지역 일치({label})", required=label,
                 user_value=profile["region"].get("label"))


def _check_gender(service: Service, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    scope = service.gender_scope
    if scope == "any":
        return None
    label = "남성" if scope == "male" else "여성"
    if profile["sex"] == "unknown":
        return _rule("gender", UNKNOWN, "성별 제한이 있는 제도입니다.", required=label,
                     missing_key="sex")
    if profile["sex"] != scope:
        return _rule("gender", FAIL, f"{label}만 신청할 수 있는 제도입니다.",
                     required=label, user_value="남성" if profile["sex"] == "male" else "여성")
    return _rule("gender", PASS, f"성별 조건 충족({label})", required=label, user_value=label)


_SENIOR_KW = (
    "노인", "어르신", "경로", "만 65세", "65세 이상", "기초연금",
    "독거노인", "치매", "장기요양", "재가노인", "노인맞춤돌봄",
)
_MIDDLE_KW = ("중장년", "신중년")
_CHILD_KW = (
    "영유아", "신생아", "기저귀", "조제분유", "어린이집", "유치원",
    "가정양육수당", "부모급여", "첫만남이용권", "아동수당",
    "초등학생", "중학생", "고등학생", "청소년",
)
_FARMER_FOREST_KW = (
    "농업인", "농업기계", "스마트팜", "농산물도매", "축산", "양식업",
    "어선", "어업인", "임업인", "산림사업", "특수산림", "백두대간",
    "조림 지원", "숲가꾸기", "친환경농업", "귀농", "귀촌",
)
_VETERAN_MILITARY_KW = (
    "장병 인권", "현역병", "군인", "전사자", "유해 소재", "국가유공자", "보훈대상",
)
_NICHE_SPECIAL_KW = (
    "특별귀화", "귀화허가", "노숙인", "마약류 중독", "성범죄피해자",
    "디지털성범죄", "범죄수익환수", "낙동강수계", "금강수계", "영산강수계",
    "한강수계", "섬진강수계", "폐광", "광업자", "북한이탈주민", "탈북민",
    "입양", "산재근로자", "산재보험", "대지급금", "임금체불", "체불근로자", "장기근속", "중소기업장기근속",
    "부도 임대주택", "납북피해자",
)
_STUDENT_KW = ("고졸 후학습자", "국가장학금", "학자금 대출")


def _infer_text_target_rule(service: Service, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """자격 코드가 비어 있거나 느슨할 때 제목·대상의 명백한 특수 직군/대상 제한을 판정한다."""
    text = f"{service.name} {service.target}"
    situations = set(profile.get("situations") or [])
    declared = bool(profile.get("situations_declared"))

    if any(k in text for k in _FARMER_FOREST_KW):
        if declared and "farmer" not in situations:
            return _rule("life", FAIL,
                         "농·림·축·어업인 대상 사업으로 보입니다(농업인 미선택).",
                         required="농·림·축·어업인")
        if not declared:
            return _rule("criteria", NOTE,
                         "농·림·축·어업인 대상 사업으로 보입니다. 해당 여부를 확인하세요.")

    if any(k in text for k in _VETERAN_MILITARY_KW):
        if declared and "veteran" not in situations:
            return _rule("life", FAIL,
                         "군인·보훈·유가족 대상 사업으로 보입니다(국가보훈대상자 미선택).",
                         required="군인·보훈·유가족")
        if not declared:
            return _rule("criteria", NOTE,
                         "군인·보훈·유가족 대상 사업으로 보입니다. 해당 여부를 확인하세요.")

    if any(k in text for k in _STUDENT_KW):
        if declared and "student" not in situations:
            return _rule("criteria", NOTE,
                         "학생·후학습자 대상 사업으로 보입니다. 신청 자격을 원문에서 확인하세요.")

    if any(k in text for k in _NICHE_SPECIAL_KW):
        return _rule("criteria", NOTE,
                     "특수 대상 또는 특정 수계·폐광 지역 전용 사업입니다. 해당 여부를 원문에서 확인하세요.")

    # 장기요양·치매 등 노인 전용 키워드는 연령 코드가 넓게 잡혀 있어도 추가 확인
    if any(k in text for k in ("장기요양", "노인맞춤돌봄", "재가노인", "독거노인", "치매")):
        if profile.get("age") is not None and profile["age"] < 60:
            return _rule("age", FAIL,
                         f"만 나이 {profile['age']}세는 노인·장기요양 대상 사업에 해당하지 않습니다.",
                         required="만 60~65세 이상(노인·장기요양)",
                         user_value=f"{profile['age']}세")
    return None


def _infer_text_age_rule(service: Service, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """자격 코드에 연령이 없을 때 제목·대상 텍스트의 명백한 연령대 제한을 판정한다."""
    text = f"{service.name} {service.target}"
    if any(k in text for k in ("전 연령", "전연령", "전 주민", "전 시민", "전 구민", "누구나")):
        return None

    # 1) 노인·어르신 전용 (청년·아동이 함께 언급되지 않은 경우)
    if any(k in text for k in _SENIOR_KW) and not any(k in text for k in ("청년", "아동", "청소년", "임산부")):
        if profile["age"] is None:
            return _rule("age", UNKNOWN, "노인·어르신 대상 사업으로 보입니다. 나이를 확인해야 합니다.",
                         required="만 65세 이상(노인·어르신)", missing_key="age")
        if profile["age"] < 60:
            return _rule("age", FAIL,
                         f"만 나이 {profile['age']}세는 노인·어르신(만 60~65세 이상) 대상 사업에 해당하지 않습니다.",
                         required="만 65세 이상(노인·어르신)", user_value=f"{profile['age']}세")
        return None

    # 2) 중장년 전용 (청년이 함께 언급되지 않은 경우)
    if any(k in text for k in _MIDDLE_KW) and "청년" not in text:
        if profile["age"] is None:
            return _rule("age", UNKNOWN, "중장년 대상 사업으로 보입니다. 나이를 확인해야 합니다.",
                         required="만 40~64세(중장년)", missing_key="age")
        if profile["age"] < 40 or profile["age"] >= 65:
            return _rule("age", FAIL,
                         f"만 나이 {profile['age']}세는 중장년(만 40~64세) 대상 사업에 해당하지 않습니다.",
                         required="만 40~64세(중장년)", user_value=f"{profile['age']}세")
        return None

    # 3) 영유아·아동·청소년 전용
    if any(k in text for k in _CHILD_KW) and "청년" not in text:
        if not profile["children_declared"]:
            return _rule("age", UNKNOWN,
                         "영유아·아동·청소년 대상 사업으로 보입니다. 자녀 유무 및 나이를 확인해야 합니다.",
                         required="아동·청소년(자녀)", missing_key="children_ages",
                         subject="child", age_basis="child")
        if not profile["children_ages"]:
            return _rule("age", FAIL, "대상 아동·청소년이 없다고 입력되었습니다.",
                         required="아동·청소년(자녀)", subject="child", age_basis="child")
        return None

    return None


def _check_age(service: Service, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    age = service.age
    if not age["limited"]:
        return _infer_text_age_rule(service, profile)
    low, high = age["min_age"], age["max_age"]
    required = _age_text(low, high)
    child_subject = service.age_subject == "child"
    if child_subject:
        if not profile["children_declared"]:
            return _rule("age", UNKNOWN,
                         f"{required} 대상 아동·청소년 기준으로 보이는 제도입니다. "
                         "신청자 본인 나이가 아니라 자녀(대상자) 나이로 확인해야 합니다.",
                         required=required, missing_key="children_ages", subject="child",
                         age_basis="child")
        if not profile["children_ages"]:
            return _rule("age", FAIL, "대상 아동·청소년이 없다고 입력되었습니다.",
                         required=required, subject="child", age_basis="child")
        hits = [value for value in profile["children_ages"] if _in_range(value, low, high)]
        if hits:
            return _rule("age", PASS, f"자녀 나이 조건 충족({hits[0]}세)", required=required,
                         user_value=f"{hits[0]}세", subject="child", age_basis="child")
        return _rule("age", FAIL, f"자녀 나이가 {required} 범위에 없습니다.", required=required,
                     user_value=", ".join(f"{value}세" for value in profile["children_ages"]),
                     subject="child", age_basis="child")

    if profile["age"] is None:
        return _rule("age", UNKNOWN, "연령 조건이 있는 제도입니다.", required=required,
                     missing_key="age")
    if _in_range(profile["age"], low, high):
        return _rule("age", PASS, f"연령 조건 충족({profile['age']}세)", required=required,
                     user_value=f"{profile['age']}세")
    return _rule("age", FAIL, f"만 나이 {profile['age']}세는 {required} 범위 밖입니다.",
                 required=required, user_value=f"{profile['age']}세")


def _age_text(low: Optional[int], high: Optional[int]) -> str:
    if low is not None and high is not None:
        return f"만 {low}~{high}세"
    if low is not None:
        return f"만 {low}세 이상"
    if high is not None:
        return f"만 {high}세 이하"
    return "연령 제한 없음"


def _in_range(value: Optional[int], low: Optional[int], high: Optional[int]) -> bool:
    if value is None:
        return False
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True


# 프로필과 무관한 문구(요건 라벨·원문 발췌)는 제도별로 한 번만 만든다.
_INCOME_BASIS_ATTR = "_engine_income_basis"
_GROUP_BASIS_ATTR = "_engine_group_basis"
_EXCERPT_ATTR = "_engine_criteria_excerpt"


def _income_basis(service: Service) -> Optional[Tuple[Tuple[str, ...], str]]:
    """(소득구간 코드들, 화면·사유에 쓰는 요건 문구)."""
    cached = service.__dict__.get(_INCOME_BASIS_ATTR)
    if cached is None:
        bands = tuple(service.income_bands)
        cached = (bands, " 또는 ".join(conditions.band_label(code) for code in bands)) \
            if bands else ((), "")
        service.__dict__[_INCOME_BASIS_ATTR] = cached
    return cached if cached[0] else None


def _group_basis(service: Service, group: str) -> Optional[Tuple[Tuple[str, ...], str, bool]]:
    """(묶음 코드들, 요건 문구, '상황을 가리지 않음' 여부)."""
    cache = service.__dict__.get(_GROUP_BASIS_ATTR)
    if cache is None:
        cache = {}
        service.__dict__[_GROUP_BASIS_ATTR] = cache
    basis = cache.get(group)
    if basis is None:
        codes = tuple(service.groups.get(group, []))
        if codes:
            labels = [conditions.CODE_CATALOG.get(code, ("", code))[1] for code in codes]
            required = " · ".join(dict.fromkeys(labels))
            loose = any(code in conditions.GROUP_ANY_CODES.get(group, ()) for code in codes)
            basis = (codes, required, bool(loose))
        else:
            basis = ((), "", False)
        cache[group] = basis
    return basis if basis[0] else None


def _criteria_excerpt_for(service: Service) -> str:
    cached = service.__dict__.get(_EXCERPT_ATTR)
    if cached is None:
        cached = _criteria_excerpt(service.criteria)
        service.__dict__[_EXCERPT_ATTR] = cached
    return cached


def _check_income(service: Service, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    basis = _income_basis(service)
    if basis is None:
        return None
    bands, required = basis
    if profile["income_band"] is None:
        return _rule("income", UNKNOWN, "소득구간 조건이 있는 제도입니다.", required=required,
                     missing_key="income_band")
    if profile["income_band"] in bands:
        return _rule("income", PASS, f"소득구간 충족({conditions.band_label(profile['income_band'])})",
                     required=required, user_value=conditions.band_label(profile["income_band"]))
    return _rule("income", FAIL,
                 f"입력한 소득구간({conditions.band_label(profile['income_band'])})이 "
                 f"제도 기준({required})에 들지 않습니다.",
                 required=required, user_value=conditions.band_label(profile["income_band"]))


def _check_situation_group(service: Service, profile: Dict[str, Any],
                           group: str) -> Optional[Dict[str, Any]]:
    basis = _group_basis(service, group)
    if basis is None:
        return None
    codes, required, loose = basis
    if loose:
        return _rule(group, PASS, "특정 상황을 가리지 않는 제도입니다.", required="제한 없음")
    if not profile["situations_declared"]:
        return _rule(group, UNKNOWN,
                     f"{conditions.group_label(group)} 조건이 있는 제도입니다. "
                     f"{conditions.GROUP_QUESTIONS.get(group, '')}를 알려 주면 판정됩니다.",
                     required=required, missing_key=f"situations.{group}")
    user_codes = conditions.codes_for_situations(profile["situations"]).get(group, [])
    if set(codes) & set(user_codes):
        hit = [conditions.CODE_CATALOG.get(code, ("", code))[1] for code in codes if code in user_codes]
        return _rule(group, PASS, f"{conditions.group_label(group)} 조건 충족({', '.join(hit)})",
                     required=required, user_value=", ".join(hit))
    if not user_codes:
        return _rule(group, FAIL,
                     f"{conditions.group_label(group)} 요건({required})에 해당한다고 입력된 항목이 없습니다.",
                     required=required, user_value="해당 없음으로 입력")
    return _rule(group, FAIL,
                 f"{conditions.group_label(group)} 요건은 {required}인데, "
                 f"입력된 상황({', '.join(profile['situation_labels'])})과 맞지 않습니다.",
                 required=required, user_value=", ".join(profile["situation_labels"]))


def _check_business_entity(service: Service, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """예비창업자/소상공인/중소기업 등 기업 형태 요건."""
    allowed = list(service.business.get("entity") or [])
    if not allowed:
        return None
    required = " · ".join(dict.fromkeys(programs.ENTITY_LABELS.get(slug, slug)
                                       for slug in allowed))
    user = profile.get("business") or {}
    status = user.get("status")
    if status is None:
        return _rule("business", UNKNOWN,
                     "예비창업자인지, 사업자등록 후 운영 중인지에 따라 대상이 갈립니다.",
                     required=required, missing_key="biz_status")
    if status == "pre":
        if "pre_startup" in allowed:
            return _rule("business", PASS, "예비창업자 대상 사업입니다.", required=required,
                         user_value="예비창업자")
        return _rule("business", FAIL, "예비창업자는 대상이 아닙니다(사업자등록 후 신청 가능).",
                     required=required, user_value="예비창업자")

    operating = [slug for slug in allowed if slug != "pre_startup"]
    if not operating:
        return _rule("business", FAIL, "예비창업자만 신청할 수 있는 사업입니다.",
                     required=required, user_value="사업자(운영 중)")
    entity = user.get("entity")
    if entity is None:
        return _rule("business", UNKNOWN, "사업자 형태(소상공인·중소기업·법인 등)를 알려 주면 판정됩니다.",
                     required=required, missing_key="biz_entity")
    user_label = programs.ENTITY_LABELS.get(entity, entity)
    if entity in operating:
        return _rule("business", PASS, f"기업 형태 조건 충족({user_label})", required=required,
                     user_value=user_label)
    # '창업기업' 요건은 업력 요건과 함께 오는 경우가 많다. 업력을 영위하는 기업이면
    # 형태 자체로는 막지 않고, 업력은 별도 규칙이 판정한다.
    if "startup" in operating and entity in ("small_business", "sole_proprietor", "sme",
                                              "corporate", "venture", "social_enterprise",
                                              "startup"):
        return _rule("business", PASS, f"기업 형태 조건 충족({user_label} → 창업기업)",
                     required=required, user_value=user_label)
    # 소상공인·개인사업자는 중소기업의 부분집합이다(법령상).
    if "sme" in operating and entity in ("small_business", "sole_proprietor"):
        return _rule("business", PASS, f"기업 형태 조건 충족({user_label} → 중소기업)",
                     required=required, user_value=user_label)
    if entity == "corporate" and "venture" in operating:
        return _rule("business", PASS, f"기업 형태 조건 충족({user_label})", required=required,
                     user_value=user_label)
    return _rule("business", FAIL, f"{user_label}은 대상 기업 형태({required})에 들지 않습니다.",
                 required=required, user_value=user_label)


def _check_business_years(service: Service, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    max_years = service.business.get("max_years")
    if max_years is None:
        return None
    required = f"창업 {max_years}년 이내"
    user = profile.get("business") or {}
    status = user.get("status")
    if status is None:
        return _rule("business", UNKNOWN, "업력 요건이 있는 사업입니다.", required=required,
                     missing_key="biz_status")
    if status == "pre":
        return _rule("business", PASS, "예비창업자는 업력 요건을 충족합니다(업력 0년).",
                     required=required, user_value="예비창업자")
    years = user.get("years")
    if years is None:
        return _rule("business", UNKNOWN, "업력(창업 후 경과 연수)을 알려 주면 판정됩니다.",
                     required=required, missing_key="biz_years")
    shown = f"{years:g}년"
    if years <= max_years:
        return _rule("business", PASS, f"업력 조건 충족({shown})", required=required,
                     user_value=shown)
    return _rule("business", FAIL, f"업력 {shown}는 {required} 요건 밖입니다.",
                 required=required, user_value=shown)


def _check_business_age(service: Service, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    low = service.business.get("min_age")
    high = service.business.get("max_age")
    if low is None and high is None:
        return None
    required = _age_text(low, high)
    if profile["age"] is None:
        return _rule("business", UNKNOWN, "연령 요건이 있는 사업입니다.", required=required,
                     missing_key="age")
    if _in_range(profile["age"], low, high):
        return _rule("business", PASS, f"연령 조건 충족({profile['age']}세)",
                     required=required, user_value=f"{profile['age']}세")
    return _rule("business", FAIL, f"만 {profile['age']}세는 {required} 범위 밖입니다.",
                 required=required, user_value=f"{profile['age']}세")


def _check_business_gender(service: Service, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    scope = service.business.get("gender")
    if scope not in ("female", "male"):
        return None
    label = "여성" if scope == "female" else "남성"
    if profile["sex"] == "unknown":
        return _rule("business", UNKNOWN, f"{label} 대상 사업입니다.", required=label,
                     missing_key="sex")
    if profile["sex"] == scope:
        return _rule("business", PASS, f"성별 조건 충족({label})", required=label,
                     user_value=label)
    return _rule("business", FAIL, f"{label} 대상 사업입니다.", required=label,
                 user_value="남성" if profile["sex"] == "male" else "여성")


def _check_business_industry(service: Service, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not service.business.get("industry_required"):
        return None
    wanted = list(service.business.get("industries") or [])
    if not wanted:
        return None
    required = " · ".join(dict.fromkeys(programs.INDUSTRY_LABELS.get(slug, slug)
                                       for slug in wanted))
    industry = (profile.get("business") or {}).get("industry")
    if industry is None:
        return _rule("business", UNKNOWN, "업종 요건이 있는 사업입니다.", required=required,
                     missing_key="biz_industry")
    label = programs.INDUSTRY_LABELS.get(industry, industry)
    if industry in wanted:
        return _rule("business", PASS, f"업종 조건 충족({label})", required=required,
                     user_value=label)
    return _rule("business", FAIL, f"{label}은 대상 업종({required})이 아닙니다.",
                 required=required, user_value=label)


def _check_business_criteria(service: Service) -> List[Dict[str, Any]]:
    """기업 트랙: 선정기준 공백 대신 **모집 상태·구조화 실패**를 확인 사유로 삼는다."""
    rules: List[Dict[str, Any]] = []
    business = service.business or {}
    if business.get("recruiting") == "closed":
        rules.append(_rule("criteria", NOTE,
                           "모집이 마감된 공고입니다. 다음 차수 공고를 확인해야 합니다.",
                           criteria_state="present", recruiting="closed"))
    if not business.get("parsed") and not service.has_criteria:
        rules.append(_rule("criteria", NOTE,
                           "공고문의 신청자격을 구조화하지 못해 원문 확인이 필요합니다.",
                           criteria_state="missing"))
    if service.unpredictable_allocation:
        rules.append(_rule("criteria", NOTE,
                           "선착순·추첨·예산 소진 등 결과를 미리 알 수 없는 요건이 있습니다.",
                           criteria_state="present"))
    return rules


# 원문 대상 문구에 자주 나오는 '특정 집단' 요건 → 그 요건을 뜻하는 자격 코드.
# 코드가 코드표에 아예 없는 항목(군 복무·선원)은 None 으로 두고, 문구가 있으면
# '코드로 확인할 수 없음'을 항상 알린다.
TARGET_REQUIREMENT_HINTS: List[tuple] = [
    ("군 복무", None), ("상근예비역", None), ("전역", None), ("선원", None),
    ("재학", ("JA0317", "JA0318", "JA0319", "JA0320")),
    ("대학생", ("JA0320",)),
    ("장애", ("JA0328",)),
    ("임신", ("JA0301", "JA0302")), ("임산부", ("JA0302",)),
    ("출산", ("JA0303",)), ("입양", ("JA0303",)),
    ("한부모", ("JA0403",)), ("조손", ("JA0403",)),
    ("다문화", ("JA0401",)), ("북한이탈", ("JA0402",)),
    ("다자녀", ("JA0411",)), ("1인가구", ("JA0404",)), ("무주택", ("JA0412",)),
    ("농업인", ("JA0313",)), ("농가", ("JA0313",)),
    ("어업인", ("JA0314",)), ("어민", ("JA0314",)),
    ("보훈", ("JA0329",)), ("국가유공", ("JA0329",)),
    ("질환", ("JA0330",)), ("환자", ("JA0330",)),
    ("구직", ("JA0327",)), ("미취업", ("JA0327",)),
    ("근로자", ("JA0326",)), ("직장인", ("JA0326",)),
]


def _uncoded_requirements(service: Service) -> List[str]:
    """대상 문구에는 있는데 자격 코드에는 없는 요건(최대 3개)."""
    if service.is_business:
        return []
    text = f"{service.target} {service.name}"
    found: List[str] = []
    for word, codes in TARGET_REQUIREMENT_HINTS:
        if word not in text:
            continue
        if codes and any(code in service.conditions for code in codes):
            continue
        if word not in found:
            found.append(word)
        if len(found) >= 3:
            break
    return found


def _has_discriminating_conditions(service: Service) -> bool:
    """자격 코드가 실제로 대상을 구분하는가.

    원본에는 "제한 없음"을 뜻하는 코드만 채워진 제도가 많습니다
    (성별 코드 둘 다, 중위소득 5구간 전부, `해당사항없음`). 그것을
    '누구나 가능'으로 읽으면 엉뚱한 제도를 '받을 가능성 높음'으로 올리게 됩니다.
    그래서 **어느 묶음 하나라도 실제로 좁히는 코드**가 있을 때만 판정 근거로 인정합니다.
    """
    if service.age["limited"]:
        return True
    bands = service.income_bands
    if bands and len(bands) < len(conditions.INCOME_BANDS):
        return True
    if service.gender_scope != "any":
        return True
    any_codes = {code for codes in conditions.GROUP_ANY_CODES.values() for code in codes}
    for group in ("life", "household", "business"):
        if any(code not in any_codes for code in service.groups.get(group, [])):
            return True
    return False


def _check_criteria(service: Service) -> List[Dict[str, Any]]:
    """선정기준 원문 상태 → 확인 필요 사유."""
    rules: List[Dict[str, Any]] = []
    if not service.is_business and not _has_discriminating_conditions(service):
        rules.append(_rule(
            "criteria", NOTE,
            "공개된 자격 코드가 대상자를 구분하지 못해(제한 없음 코드만 있음) "
            "원문 기준으로 확인해야 합니다.",
            criteria_state="present" if service.has_criteria else "missing",
            no_conditions=True,
        ))
    if not service.has_criteria:
        rules.append(_rule(
            "criteria", NOTE,
            "소관기관 원본의 선정기준이 비어 있어, 공개된 자격 코드만으로 판정했습니다. "
            "세부 기준은 소관기관에 확인해야 합니다.",
            criteria_state="missing",
        ))
    uncoded = _uncoded_requirements(service)
    if uncoded:
        rules.append(_rule(
            "criteria", NOTE,
            "원문 대상 문구에 " + ", ".join(uncoded) + " 요건이 있지만 공개된 자격 코드에는 "
            "담겨 있지 않습니다. 해당 여부를 원문에서 확인해야 합니다.",
            criteria_state="present", uncoded_requirements=uncoded,
        ))
    if service.unpredictable_allocation:
        rules.append(_rule(
            "criteria", NOTE,
            "선착순·추첨·예산 소진 등 결과를 미리 알 수 없는 요건이 있습니다.",
            criteria_state="present",
        ))
    return rules


def _criteria_excerpt(text: str) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= MAX_CRITERIA_EXCERPT:
        return clean
    return clean[:MAX_CRITERIA_EXCERPT].rstrip() + "…"


# 선정기준 규칙은 프로필과 무관하다. 제도 하나를 여러 번 판정해도 다시 만들지 않도록
# 서비스 객체에 붙여 둔다(cached_property 와 같은 방식, 키 이름만 엔진 전용).
_TAIL_RULES_ATTR = "_engine_criteria_rules"


def _criteria_rules(service: Service) -> Tuple[Dict[str, Any], ...]:
    cached = service.__dict__.get(_TAIL_RULES_ATTR)
    if cached is None:
        rules = (_check_business_criteria(service) if service.is_business
                 else _check_criteria(service))
        cached = tuple(rules)
        service.__dict__[_TAIL_RULES_ATTR] = cached
    return cached


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------
def structural_fail(service: Service, profile: Dict[str, Any]) -> Optional[str]:
    """구조화 요건만 보고 **명확히 어긋난** 항목의 묶음 이름을 돌려준다(없으면 None).

    `evaluate_service` 가 쓰는 검사 함수를 그대로 부르므로, 여기서 걸러진 제도는 정밀
    판정에서도 `ineligible` 이 됩니다. 그래서 거래처 일괄 매칭처럼 수백 프로필 × 수천 공고를
    훑을 때 **결과를 바꾸지 않는** 1차 필터로 쓸 수 있습니다(판정을 새로 만들지 않습니다).
    """
    checks: List[Optional[Dict[str, Any]]] = [_check_region(service, profile)]
    if service.is_business:
        checks.extend((
            _check_business_entity(service, profile),
            _check_business_years(service, profile),
            _check_business_age(service, profile),
            _check_business_gender(service, profile),
            _check_business_industry(service, profile),
        ))
    for rule in checks:
        if rule and rule.get("state") == FAIL:
            return str(rule.get("group") or "criteria")
    return None


def evaluate_service(service: Service, profile: Dict[str, Any],
                     today: Optional[date] = None) -> Dict[str, Any]:
    rules: List[Dict[str, Any]] = []
    rules.append(_check_region(service, profile))
    if not service.is_business and _profile_is_empty(profile):
        rules.append(_rule(
            "criteria", UNKNOWN,
            "판정에 쓸 조건이 하나도 입력되지 않았습니다. 나이·지역·소득구간·상황 중 "
            "하나라도 알려 주면 판정합니다.",
            missing_key="profile",
        ))
    if service.is_business:
        checks = (_check_business_entity(service, profile),
                  _check_business_gender(service, profile),
                  _check_business_years(service, profile),
                  _check_business_age(service, profile),
                  _check_business_industry(service, profile))
    else:
        checks = (_check_gender(service, profile), _check_age(service, profile),
                  _check_income(service, profile))
    for check in checks:
        if check:
            rules.append(check)
    if service.is_business:
        criteria_rules: Tuple[Dict[str, Any], ...] = _criteria_rules(service)
    else:
        for group in ("life", "household", "business"):
            check = _check_situation_group(service, profile, group)
            if check:
                rules.append(check)
        target_rule = _infer_text_target_rule(service, profile)
        if target_rule:
            rules.append(target_rule)
        criteria_rules = _criteria_rules(service)
    rules.extend(criteria_rules)

    # 같은 안내 문구가 중복으로 들어가지 않게 정리한다.
    deduped_rules: List[Dict[str, Any]] = []
    seen_reasons = set()
    for r in rules:
        key = (r.get("state"), r.get("reason_ko"))
        if key in seen_reasons:
            continue
        seen_reasons.add(key)
        deduped_rules.append(r)
    rules = deduped_rules

    states = [rule["state"] for rule in rules]
    if FAIL in states:
        code = models.VERDICT_INELIGIBLE
    elif UNKNOWN in states:
        code = models.VERDICT_INSUFFICIENT
    elif NOTE in states:
        code = models.VERDICT_CHECK
    else:
        code = models.VERDICT_ELIGIBLE

    missing = _missing_information(rules, profile)
    notes = _notes(service, rules, code)
    deadline = service.deadline

    result: Dict[str, Any] = {
        "service_id": service.service_id,
        "name": service.name,
        "agency": service.agency,
        "agency_type": service.agency_type,
        "region": service.region,
        "field": service.field,
        "field_label": service.field_label,
        "benefit_kind": service.benefit_kind,
        "support_type": service.support_type,
        "track": service.track,
        "track_label": service.track_label,
        "verdict": models.verdict_block(code),
        "why": rules,
        "matched_conditions": [
            {"code": code_, "label": conditions.CODE_CATALOG.get(code_, ("", code_))[1],
             "required": True}
            for code_ in service.conditions
        ],
        "missing_information": missing,
        "criteria_state": "present" if service.has_criteria else "missing",
        "criteria_flags": service.criteria_flags,
        "criteria_excerpt": _criteria_excerpt_for(service),
        "amount": service.content,
        "application": {"how": service.how, "deadline_text": service.deadline_text,
                        "deadline": deadline, "receipt_agency": service.receipt_agency},
        "contact": service.contact,
        "detail_url": service.detail_url,
        "online_url": service.online_url,
        "documents": service.documents,
        "source_updated_at": service.updated_at,
        "tags": service.tags,
        "notes_ko": notes,
        "source": service.source,
        "source_label": programs.source_label(service.source),
        "attribution_ko": service.attribution,
        "business": service.business or None,
        "business_summary_ko": service.business_summary_text,
        "fingerprint": service.fingerprint,
        "data_state": service.source,
    }
    if service.source == "sample":
        result["notes_ko"].append(
            "이 제도의 금액·기한은 내장 샘플 값입니다. 실제 값은 원문과 소관기관 안내를 확인하세요."
        )
    return result


def _profile_is_empty(profile: Dict[str, Any]) -> bool:
    return (profile["age"] is None
            and profile["income_band"] is None
            and not profile["situations_declared"]
            and profile["region"]["level"] in ("national", "unknown"))


def _missing_information(rules: List[Dict[str, Any]], profile: Dict[str, Any]) -> List[Dict[str, str]]:
    seen: Dict[str, Dict[str, str]] = {}
    for rule in rules:
        if rule["state"] != UNKNOWN:
            continue
        key = str(rule.get("missing_key") or rule["group"])
        if key in seen:
            continue
        seen[key] = {
            "key": key,
            "group": rule["group"],
            "group_label": _REASON_GROUP_LABELS.get(rule["group"], rule["group"]),
            "question_ko": _question_for(key, rule),
            "required": str(rule.get("required") or ""),
        }
    return list(seen.values())


def _question_for(key: str, rule: Dict[str, Any]) -> str:
    if key == "profile":
        return "나이·지역·소득구간·상황 중 하나라도 알려 주세요."
    if key == "age":
        return "만 나이(또는 출생연도)를 알려 주세요."
    if key == "sex":
        return "성별을 알려 주세요(성별 제한이 있는 제도입니다)."
    if key == "income_band":
        return "가구 소득이 기준 중위소득 몇 % 구간인지 알려 주세요(예: 80%)."
    if key == "region":
        return "거주 시·도와 시·군·구를 알려 주세요."
    if key == "children_ages":
        return "자녀(대상자)의 나이 또는 출생연도를 알려 주세요."
    if key == "biz_status":
        return "예비창업자인지, 사업자등록 후 운영 중인지 알려 주세요."
    if key == "biz_years":
        return "창업 후 업력(년)을 알려 주세요(예: 2)."
    if key == "biz_entity":
        return "사업자 형태(소상공인·중소기업·법인 등)를 알려 주세요."
    if key == "biz_industry":
        return "업종(제조업·정보통신업 등)을 알려 주세요."
    if key.startswith("situations."):
        group = key.split(".", 1)[1]
        return f"{conditions.GROUP_QUESTIONS.get(group, '해당 상황')}를 알려 주세요."
    return str(rule.get("reason_ko") or "추가 정보가 필요합니다.")


def _notes(service: Service, rules: List[Dict[str, Any]], code: str) -> List[str]:
    notes: List[str] = []
    if service.is_business:
        summary = service.business_summary_text
        if summary:
            notes.append(f"공고 신청자격: {summary}.")
        if code == models.VERDICT_ELIGIBLE:
            notes.append(
                "신청자격은 충족했습니다. 모집형 사업이라 선정은 평가·경쟁으로 결정됩니다."
            )
        if service.business.get("recruiting") == "closed":
            notes.append("현재 모집이 마감된 공고입니다. 다음 차수 공고를 확인하세요.")
        preferential = str(service.business.get("preferential") or "").strip()
        if preferential:
            notes.append(f"우대사항: {preferential}")
        if service.attribution:
            notes.append(service.attribution)
        return _dedupe(notes)
    if service.age_subject == "child":
        notes.append(
            "대상자(아동·청소년)의 나이를 기준으로 판정했습니다. 신청자는 보호자일 수 있습니다."
        )
    if service.criteria_flags:
        notes.append("원문 기준에 다음 요건이 함께 있습니다: " + ", ".join(service.criteria_flags) + ".")
    if code == models.VERDICT_ELIGIBLE:
        notes.append(
            "공개된 자격 코드와 입력 조건이 일치했습니다. 최종 수급 여부는 소관기관 심사로 결정됩니다."
        )
    if any(rule["group"] == "region" and rule["state"] == UNKNOWN for rule in rules):
        notes.append("지역을 특정할 수 없어 지역 요건은 판정에서 제외했습니다.")
    return _dedupe(notes)


def _dedupe(notes: List[str]) -> List[str]:
    deduped: List[str] = []
    for note in notes:
        if note not in deduped:
            deduped.append(note)
    return deduped


# ---------------------------------------------------------------------------
# 검색
# ---------------------------------------------------------------------------
# 결과 캐시에 보관할 '돌려주는 행' 수 상한. 캐시에는 limit 만큼의 행만 남고(전국 검색도
# 반환은 최대 50행), 행 하나가 약 4.7KB 이므로 6,000행 ≈ 28MB 다. 판정한 전체 건수는
# 메모리에 남기지 않는다(세기만 하고 버린다).
SEARCH_CACHE_MAX_ROWS = 6000
# 후보 목록(필터별) 캐시 — 1.2만 건 목록의 포인터만 들고 있어 항목당 수십 KB 다.
POOL_CACHE_MAX = 32


def profile_key(profile: Dict[str, Any]) -> Tuple[Any, ...]:
    """판정에 영향을 주는 프로필 값만 뽑은 캐시 키.

    `evaluate_service` 가 읽는 값(나이·성별·지역·소득구간·상황·자녀·사업자 조건)을
    모두 담는다. 라벨처럼 파생값도 함께 넣어, 손으로 만든 프로필이 섞여도 충돌하지 않는다.
    """
    region_raw = profile.get("region")
    region = region_raw if isinstance(region_raw, dict) else {"raw": str(region_raw or "")}
    business = profile.get("business") or {}
    return (
        profile.get("age"), profile.get("birth_year"), profile.get("sex"),
        region.get("level"), region.get("sido"), region.get("sigungu"),
        region.get("label"), region.get("unresolved_sigungu"), region.get("raw"),
        profile.get("household_size"), profile.get("income_band"),
        profile.get("income_band_label"),
        tuple(profile.get("situations") or ()),
        tuple(profile.get("situation_labels") or ()),
        bool(profile.get("situations_declared")),
        bool(profile.get("children_declared")),
        tuple(profile.get("children_ages") or ()),
        business.get("declared"), business.get("status"), business.get("entity"),
        business.get("entity_label"), business.get("years"), business.get("industry"),
        business.get("industry_label"),
    )


class _ResultCache:
    """(프로필, 옵션) → 판정 결과. 돌려주는 행 수로 메모리를 묶는 LRU.

    카탈로그는 읽기 전용이고 판정은 프로필로만 결정되므로 같은 입력이면 같은 결과다.
    (결과에는 limit 만큼의 행만 담기므로, 전국 1.2만 건을 훑은 결과도 몇 KB 다.)
    """

    __slots__ = ("_entries", "_rows", "max_rows")

    def __init__(self, max_rows: int = SEARCH_CACHE_MAX_ROWS) -> None:
        self.max_rows = max_rows
        self._entries: OrderedDict[Tuple[Any, ...], Tuple[int, Dict[str, Any]]] = OrderedDict()
        self._rows = 0

    def get(self, key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
        entry = self._entries.get(key)
        if entry is None:
            return None
        try:
            self._entries.move_to_end(key)
        except KeyError:   # 다른 스레드가 방금 축출했다 — 값은 이미 손에 있으니 그대로 쓴다
            pass
        return entry[1]

    def put(self, key: Tuple[Any, ...], result: Dict[str, Any], rows: int) -> None:
        if rows > self.max_rows:
            return   # 한 건이 상한을 넘으면 담지 않는다(메모리 보호).
        old = self._entries.pop(key, None)
        if old is not None:
            self._rows -= old[0]
        self._entries[key] = (rows, result)
        self._rows += rows
        while self._rows > self.max_rows and self._entries:
            try:
                _key, entry = self._entries.popitem(last=False)
            except KeyError:   # 다른 스레드가 먼저 축출했다
                break
            self._rows -= entry[0]


def _result_cache(catalog: Catalog) -> _ResultCache:
    cache = catalog.memo.get("search_results")
    if cache is None:
        cache = _ResultCache()
        catalog.memo["search_results"] = cache
    return cache


def _copy_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """캐시에서 꺼낸 결과를 호출자가 바꿔도 캐시가 오염되지 않게 겉껍질을 복사한다."""
    copy = dict(result)
    copy["counts"] = dict(result["counts"])
    copy["track_counts"] = dict(result["track_counts"])
    copy["results"] = [dict(row) for row in result["results"]]
    return copy


def _candidate_pool(catalog: Catalog, profile: Dict[str, Any], *, max_scan: int,
                    tag: Optional[str], keyword: Optional[str],
                    include_closed: bool, expand_keyword: bool = False) -> List[Service]:
    """트랙·지역·마감·태그·검색어로 후보를 줄인 목록 — 필터 조합별로 한 번만 만든다."""
    region = profile["region"]
    key = (region.get("level"), region.get("sido"), region.get("sigungu"),
           profile.get("track", "all"), bool((profile.get("business") or {}).get("declared")),
           bool(include_closed), tag or "", keyword or "", int(max_scan),
           bool(expand_keyword))
    cache = catalog.memo.get("pools")
    if cache is None:
        cache = {}
        catalog.memo["pools"] = cache
    cached = cache.get(key)
    if cached is not None:
        return list(cached)

    if hasattr(catalog, "query_pool"):
        pool = catalog.query_pool(
            sido=region.get("sido"),
            sigungu=region.get("sigungu"),
            track=profile.get("track", "all"),
            business_declared=bool((profile.get("business") or {}).get("declared")),
            include_closed=include_closed,
            tag=tag,
            keyword=keyword,
            keyword_expand=expand_keyword,
            max_scan=max_scan,
        )
    else:
        pool = catalog.services[:max_scan]
        if region.get("level") in ("sido", "sigungu"):
            pool = catalog.by_region(region.get("sido"), region.get("sigungu"))[:max_scan]
        track = profile.get("track", "all")
        if track == programs.TRACK_BUSINESS:
            pool = [svc for svc in pool if svc.is_business]
        elif track == programs.TRACK_PERSONAL:
            pool = [svc for svc in pool if not svc.is_business]
        elif not (profile.get("business") or {}).get("declared"):
            # 트랙을 고르지 않았고 사업자 조건도 없으면 개인 제도만 보여 준다.
            pool = [svc for svc in pool if not svc.is_business]
        if not include_closed:
            pool = [svc for svc in pool if not svc.is_expired]
        if tag:
            pool = [svc for svc in pool if tag in svc.tags]
        if keyword:
            if expand_keyword:
                groups = synonyms.plan(keyword)
                pool = [svc for svc in pool
                        if synonyms.matches(
                            f"{svc.name} {svc.purpose} {svc.target} "
                            f"{' '.join(svc.business.get('hashtags') or [])}",
                            groups)]
            else:
                words = [word for word in str(keyword).split() if word]
                pool = [svc for svc in pool
                        if all(word in f"{svc.name} {svc.purpose} {svc.target} "
                                        f"{' '.join(svc.business.get('hashtags') or [])}"
                               for word in words)]

    if len(cache) >= POOL_CACHE_MAX:
        cache.clear()
    cache[key] = tuple(pool)
    return pool


def search(catalog: Catalog, profile: Dict[str, Any], *, limit: int = 20,
           include_ineligible: bool = False, tag: Optional[str] = None,
           keyword: Optional[str] = None, max_scan: int = 20000,
           include_closed: bool = False, balance_kinds: bool = False,
           expand_keyword: bool = False) -> Dict[str, Any]:
    """프로필로 후보 제도를 판정한다. 트랙·지역·마감 여부로 후보를 줄인 뒤 판정한다.

    `expand_keyword=True` 면 키워드를 `synonyms` 사전으로 넓혀 본다("전기세"→"전기요금" 등).
    넓혀 걸린 제도는 질의어를 그대로 담은 제도 뒤에 놓이고, 기본값(False)은 예전처럼
    질의어 그대로의 부분 일치 AND 만 본다 — 화면·API 처럼 사용자가 직접 검색하는 경로만 켠다.
    """
    cache = _result_cache(catalog)
    cache_key = (profile_key(profile), int(limit), bool(include_ineligible),
                 tag or "", keyword or "", int(max_scan), bool(include_closed),
                 bool(balance_kinds), bool(expand_keyword))
    hit = cache.get(cache_key)
    if hit is not None:
        return _copy_result(hit)

    pool = _candidate_pool(catalog, profile, max_scan=max_scan, tag=tag, keyword=keyword,
                           include_closed=include_closed, expand_keyword=expand_keyword)
    track = profile.get("track", "all")

    results = [evaluate_service(svc, profile) for svc in pool]
    if not include_ineligible:
        shown = [row for row in results if row["verdict"]["code"] != models.VERDICT_INELIGIBLE]
    else:
        shown = results
    if expand_keyword and keyword:
        # 동의어로 넓혀 찾은 검색은 두 줄로 세운다.
        #  1) 질의어를 그대로 담은 제도 — 예전과 같은 판정 순서(_sort_key)
        #  2) 동의어로만 걸린 제도 — 질의어에 가까운 순서 → 판정 순서
        # 넓힌 결과가 원래 결과를 밀어내지 않게 하는 장치다.
        groups = synonyms.plan(keyword)
        relevance: Dict[str, int] = {}
        strict_ids = set()
        for svc in pool:
            body = f"{svc.purpose} {svc.target} {' '.join(svc.business.get('hashtags') or [])}"
            relevance[svc.service_id] = synonyms.score(svc.name, body, groups)
            if synonyms.literal_hit(svc.name, body, keyword):
                strict_ids.add(svc.service_id)
        direct = [row for row in shown if row.get("service_id") in strict_ids]
        related = [row for row in shown if row.get("service_id") not in strict_ids]
        direct.sort(key=_sort_key)
        related.sort(key=lambda row: (-relevance.get(row.get("service_id"), 0), _sort_key(row)))
        shown = direct + related
    else:
        shown.sort(key=_sort_key)
    counts: Dict[str, int] = {code: 0 for code in models.VERDICT_ORDER}
    for row in results:
        counts[row["verdict"]["code"]] += 1
    track_counts: Dict[str, int] = {programs.TRACK_PERSONAL: 0, programs.TRACK_BUSINESS: 0}
    for row in results:
        track_counts[row["track"]] = track_counts.get(row["track"], 0) + 1

    cap = max(1, limit)
    if balance_kinds:
        grants = [r for r in shown if r.get("benefit_kind") != "program"]
        progs = [r for r in shown if r.get("benefit_kind") == "program"]
        if grants and progs and cap >= 4:
            p_quota = min(len(progs), max(1, cap // 3))
            g_quota = min(len(grants), cap - p_quota)
            if g_quota + p_quota < cap:
                p_quota = min(len(progs), cap - g_quota)
            picked = grants[:g_quota] + progs[:p_quota]
        else:
            picked = shown[:cap]
    else:
        picked = shown[:cap]

    result = {
        "counts": counts,
        "scanned": len(results),
        "results": picked,
        "truncated": len(shown) > limit,
        "ineligible_hidden": (counts[models.VERDICT_INELIGIBLE]
                              if not include_ineligible else 0),
        "track": track,
        "track_counts": track_counts,
        "closed_hidden": getattr(catalog, "expired_count", catalog.closed_business_count)
        if not include_closed else 0,
    }
    cache.put(cache_key, result, len(result["results"]))
    return _copy_result(result)


def _sort_key(row: Dict[str, Any]) -> Tuple[int, int, int, int, int, str]:
    code = row["verdict"]["code"]
    region_level = (row.get("region") or {}).get("level") or "nationwide"
    region_tier = {"sigungu": 0, "sido": 1}.get(region_level, 2)
    kind_rank = 0 if row.get("benefit_kind", "grant") == "grant" else 1
    # 내가 입력한 조건(상황·가구·성별·자녀·업종)에 직접 맞물린 제도일수록 우선 노출
    specific_hits = 0
    for r in row.get("why") or []:
        if r.get("state") == PASS and r.get("group") in ("life", "household", "business", "gender"):
            if "가리지 않는" not in (r.get("reason_ko") or ""):
                specific_hits += 1
    deadline = row.get("application", {}).get("deadline") or {}
    end = deadline.get("end_date") or "9999-12-31"
    days_left = deadline.get("days_left")
    if days_left is not None and 0 <= days_left <= 7:
        urgency = 0
    elif deadline.get("closing_soon"):
        urgency = 1
    else:
        urgency = 2
    return (models.SORT_INDEX.get(code, 9), kind_rank, -specific_hits, region_tier, urgency, end)


def evaluate_by_id(catalog: Catalog, service_id: str,
                   profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    service = catalog.get(service_id)
    if service is None:
        return None
    return evaluate_service(service, profile)


def explain_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """프로필 해석 결과(디버깅·화면 표시용). 원문 입력은 담지 않는다."""
    business = profile.get("business") or {}
    return {
        "age": profile["age"],
        "age_basis": profile["age_basis"],
        "sex": profile["sex"],
        "region": profile["region"],
        "household_size": profile["household_size"],
        "income_band": profile["income_band"],
        "income_band_label": profile["income_band_label"],
        "situations": profile["situations"],
        "situation_labels": profile["situation_labels"],
        "children_ages": profile["children_ages"],
        "track": profile.get("track", "all"),
        "track_label": programs.track_label(profile.get("track", "all"))
        if profile.get("track") in programs.TRACK_LABELS else "개인+기업",
        "business": {
            "declared": business.get("declared", False),
            "status": business.get("status"),
            "entity": business.get("entity"),
            "entity_label": business.get("entity_label"),
            "years": business.get("years"),
            "industry": business.get("industry"),
            "industry_label": business.get("industry_label"),
        },
        "missing_core": profile["missing_core"],
        "ignored_situations": profile["ignored_situations"],
        "age_note_ko": (
            "출생연도만 받은 경우 만 나이는 연도 차이로 계산해 생일 전이면 1살 차이가 날 수 있습니다."
            if profile["age_basis"] == "birth_year" else None
        ),
    }


def summarize_for_llm(rows: Iterable[Dict[str, Any]]) -> str:
    """MCP 텍스트 블록에 곁들이는 한 줄 요약(사람이 읽는 문장)."""
    lines = []
    for row in rows:
        lines.append(f"[{row['verdict']['label_ko']}] {row['name']} ({row['agency']})")
    return "\n".join(lines)
