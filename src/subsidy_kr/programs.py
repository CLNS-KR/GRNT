"""창업·소상공인·기업 지원사업 정규화 (K-Startup 15125364 · 기업마당 15157820).

두 API 는 컬럼 이름도 응답 모양도 다르지만, 판정 엔진은 `Service` 한 종류만 압니다.
그래서 여기서 보조금24와 **같은 한국어 키**(`서비스명`·`소관기관명`·`지원대상`·`신청기한`…)로
옮기고, 창업·기업에만 있는 조건은 `business` 블록에 담습니다.

`business` 블록
---------------
| 키 | 뜻 | 값 |
|---|---|---|
| `entity` | 지원 대상 기업 형태 | `pre_startup` · `startup` · `small_business` · `sme` · `corporate` · `venture` · `social_enterprise` |
| `status` | 요구 신분 | `pre`(예비창업자만) · `operating`(사업자만) · None(둘 다) |
| `max_years` | 업력 상한(년) | 정수 또는 None |
| `min_age` / `max_age` | 신청자 연령 | 정수 또는 None |
| `gender` | 성별 제한 | `female` · `male` · None |
| `industries` | 업종(표시·검색용) | 산업 슬러그 목록 |
| `industry_required` | 업종 제한이 판정 조건인가 | bool |
| `recruiting` | 모집 상태 | `open` · `closed` · `unknown` |
| `field` | 지원 분야 | 예: 사업화, 금융 |
| `hashtags` | 기업마당 해시태그 | 문자열 목록 |
| `parsed` | 구조화에 성공했는가 | bool |

원문 해석에서 조심한 것 (실호출로 확인)
-------------------------------------
- K-Startup 의 `biz_enyy`·`biz_trgt_age` 는 **단일 값이 아니라 '허용하는 조건의 목록'**입니다.
  예: `예비창업자,1년미만,2년미만,3년미만,5년미만,7년미만,10년미만`,
  `만 20세 미만,만 20세 이상 ~ 만 39세 이하,만 40세 이상`. 그래서 여러 값이 오면
  **합집합**으로 읽습니다(가장 넓은 쪽). 단일 값일 때만 제한으로 판정합니다.
- `aply_trgt`(청소년·대학생·일반인·일반기업…)는 신청자 분류라 자격 판정에 쓰지 않습니다.
- `biz_enyy` 같은 구조화 컬럼과 본문 문장이 다르면 **더 좁은 쪽**을 씁니다(놓치는 것보다 낫다).
- 기업마당 `bsnsSumryCn` 은 HTML 이 섞여 옵니다. 태그만 걷어내고 **문구는 고치지 않습니다**
  (기업마당은 출처표시·변경금지 조건).
"""
from __future__ import annotations

import html
import re
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import deadlines, regions

TRACK_PERSONAL = "personal"
TRACK_BUSINESS = "business"

TRACK_LABELS: Dict[str, str] = {
    TRACK_PERSONAL: "개인·가구",
    TRACK_BUSINESS: "창업·소상공인·기업",
}

SOURCE_KSTARTUP = "kstartup"
SOURCE_BIZINFO = "bizinfo"

SOURCE_LABELS: Dict[str, str] = {
    "sample": "내장 샘플",
    "gov24": "정부24 보조금24",
    SOURCE_KSTARTUP: "창업진흥원 K-Startup",
    SOURCE_BIZINFO: "중소벤처기업부 기업마당",
}

SOURCE_ATTRIBUTION: Dict[str, str] = {
    "gov24": "출처: 행정안전부 대한민국 공공서비스(혜택) 정보(data.go.kr 15113968)",
    SOURCE_KSTARTUP: "출처: 창업진흥원 K-Startup 지원사업 공고(data.go.kr 15125364)",
    SOURCE_BIZINFO: (
        "출처: 중소벤처기업부 중소기업 지원사업 공고(기업마당) / data.go.kr 15157820 — "
        "원문 문구 그대로(출처표시·변경금지 조건)"
    ),
}

ENTITY_LABELS: Dict[str, str] = {
    "pre_startup": "예비창업자",
    "startup": "창업기업(업력 제한)",
    "small_business": "소상공인",
    "sole_proprietor": "개인사업자",
    "sme": "중소기업",
    "corporate": "법인",
    "venture": "벤처기업",
    "social_enterprise": "사회적기업",
}

BUSINESS_ENTITIES: List[str] = [
    "pre_startup", "sole_proprietor", "small_business", "sme", "corporate",
    "venture", "social_enterprise",
]

INDUSTRY_LABELS: Dict[str, str] = {
    "manufacturing": "제조업",
    "ict": "정보통신업",
    "retail": "도소매·유통",
    "food": "음식·숙박",
    "service": "서비스업",
    "construction": "건설업",
    "logistics": "운수·물류",
    "agri": "농림어업",
    "finance": "금융·보험",
    "education": "교육",
    "health": "보건·의료",
    "culture": "문화·예술·관광",
    "energy": "환경·에너지",
    "etc": "기타",
}

INDUSTRY_WORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("manufacturing", ("제조업", "제조업체", "공장", "가공")),
    ("ict", ("정보통신", "소프트웨어", "플랫폼", "인공지능", "ICT", "IT업")),
    ("retail", ("도소매", "유통", "소매", "온라인몰", "이커머스")),
    ("food", ("음식", "외식", "식품", "숙박", "카페")),
    ("service", ("서비스업", "미용", "세탁", "수리업")),
    ("construction", ("건설업", "시공", "부동산")),
    ("logistics", ("물류", "운송", "택배", "운수업")),
    ("agri", ("농업", "농림", "어업", "축산", "임업", "농산물")),
    ("finance", ("금융업", "보험업", "핀테크")),
    ("education", ("교육", "학원", "에듀테크")),
    ("health", ("보건", "의료", "바이오", "헬스케어")),
    ("culture", ("문화", "예술", "관광", "콘텐츠", "게임", "영상")),
    ("energy", ("환경", "에너지", "탄소", "재활용", "그린")),
]

# 업종 제한이 '판정 조건'임을 알리는 표현. 이게 없으면 업종은 참고 정보로만 쓴다.
_INDUSTRY_REQUIRED_WORDS = ("업종 제한", "업종제한", "업종 한정", "업종한정", "해당 업종만",
                            "다음 업종", "업종에 한함", "업종을 영위")

_ENTITY_WORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("pre_startup", ("예비창업자", "예비 창업자", "예비창업", "창업준비")),
    ("small_business", ("소상공인", "자영업", "소규모 사업자")),
    ("sole_proprietor", ("개인사업자",)),
    ("venture", ("벤처기업", "벤처 인증", "벤처기업확인")),
    ("social_enterprise", ("사회적기업", "사회적 협동조합", "협동조합")),
    ("corporate", ("법인", "주식회사")),
    ("sme", ("중소기업", "중견기업", "중소·벤처", "중소 벤처", "일반기업")),
    ("startup", ("창업기업", "스타트업", "초기창업", "창업 후", "창업기업(창업")),
]

_YEARS_TOKEN_RE = re.compile(r"(\d{1,2})\s*년\s*(?:이내|이하|미만)")
_YEARS_IN_TEXT_RE = re.compile(r"창업\s*후?\s*(\d{1,2})\s*년\s*(?:이내|이하|미만)")
_AGE_RANGE_RE = re.compile(r"만?\s*(\d{1,2})\s*세\s*(?:이상)?\s*[~\-–]\s*만?\s*(\d{1,2})\s*세")
_AGE_LT_RE = re.compile(r"만?\s*(\d{1,2})\s*세\s*미만")
_AGE_LE_RE = re.compile(r"만?\s*(\d{1,2})\s*세\s*이하")
_AGE_OVER_RE = re.compile(r"만?\s*(\d{1,2})\s*세\s*이상")


def _text(raw: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def clean_text(value: Any, limit: int = 1200) -> str:
    """HTML 태그만 걷어내고 문구는 그대로 둔다(변경금지 조건)."""
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _tokens(value: Any) -> List[str]:
    return [token.strip() for token in re.split(r"[,，/]", str(value or "")) if token.strip()]


def parse_years(text: str) -> Dict[str, Optional[int]]:
    """업력 상한. 여러 값이 오면 **합집합(가장 넓은 쪽)** 으로 읽는다."""
    raw = str(text or "")
    tokens = _tokens(raw) or [raw]
    options: List[int] = []
    for token in tokens:
        for match in _YEARS_TOKEN_RE.finditer(token):
            try:
                value = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if 0 < value <= 30:
                options.append(value)
    if not options:
        return {"max_years": None, "min_years": None}
    return {"max_years": max(options), "min_years": None}


def parse_years_from_prose(text: str) -> Optional[int]:
    """본문 문장에서 '창업 3년 이내' 하나만 읽는다(없으면 None)."""
    values: List[int] = []
    for match in _YEARS_IN_TEXT_RE.finditer(str(text or "")):
        try:
            values.append(int(match.group(1)))
        except (TypeError, ValueError):
            continue
    return min(values) if values else None


def _age_token(token: str) -> Tuple[Optional[int], Optional[int]]:
    match = _AGE_RANGE_RE.search(token)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        return (low, high) if low <= high else (high, low)
    under = _AGE_LT_RE.search(token)
    if under:
        return (None, max(0, int(under.group(1)) - 1))
    inclusive = _AGE_LE_RE.search(token)
    if inclusive:
        return (None, int(inclusive.group(1)))
    over = _AGE_OVER_RE.search(token)
    if over:
        return (int(over.group(1)), None)
    return (None, None)


def parse_age_range(text: str) -> Dict[str, Optional[int]]:
    """신청 연령. 여러 값이 오면 합집합. 전체 연령을 덮으면 제한 없음(None)."""
    tokens = _tokens(text) or ([str(text)] if str(text or "").strip() else [])
    lows: List[Optional[int]] = []
    highs: List[Optional[int]] = []
    for token in tokens:
        low, high = _age_token(token)
        if low is None and high is None:
            continue
        lows.append(low)
        highs.append(high)
    if not lows:
        return {"min_age": None, "max_age": None}
    min_age = None if any(low is None for low in lows) else min(lows)  # type: ignore[type-var]
    max_age = None if any(high is None for high in highs) else max(highs)  # type: ignore[type-var]
    if min_age is not None and min_age <= 0:
        min_age = None
    if min_age is None and max_age is None:
        return {"min_age": None, "max_age": None}
    return {"min_age": min_age, "max_age": max_age}


def parse_entities(text: str) -> List[str]:
    """원문에서 지원 대상 기업 형태를 읽는다(중복 제거, 발견 순서 유지)."""
    compact = _compact(text)
    found: List[str] = []
    for slug, words in _ENTITY_WORDS:
        if any(_compact(word) in compact for word in words):
            if slug not in found:
                found.append(slug)
    return found


def parse_gender(text: str) -> Optional[str]:
    raw = str(text or "")
    female = "여성" in raw or "여자" in raw
    male = "남성" in raw or "남자" in raw
    if female and not male:
        return "female"
    if male and not female:
        return "male"
    return None


def parse_industries(text: str) -> List[str]:
    raw = str(text or "")
    found: List[str] = []
    for slug, words in INDUSTRY_WORDS:
        if any(word in raw for word in words):
            found.append(slug)
    return found


def parse_region_text(text: str) -> Optional[Dict[str, str]]:
    """'전국'·'서울'·'경기' → 지역 블록. 여러 곳이면 None(기관명으로 판별)."""
    raw = _compact(text)
    if not raw or "전국" in raw:
        return None
    hits: List[str] = []
    for alias in sorted(list(regions.SIDO_CODES) + list(regions.SIDO_ALIASES),
                        key=len, reverse=True):
        canonical = regions.SIDO_ALIASES.get(alias, alias)
        if alias in raw and canonical not in hits:
            hits.append(canonical)
    if len(hits) == 1:
        return regions.region_block(hits[0])
    return None


def parse_recruiting(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return "unknown"
    if raw in ("N", "NO", "FALSE", "0", "모집마감"):
        return "closed"
    if raw in ("Y", "YES", "TRUE", "1", "모집중"):
        return "open"
    return "unknown"


def _yyyymmdd(value: Any) -> Optional[str]:
    raw = re.sub(r"[^0-9]", "", str(value or ""))
    if len(raw) < 8:
        return None
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])).isoformat()
    except ValueError:
        return None


def _dot(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{year}. {int(month)}. {int(day)}."


def _period_text(start: Optional[str], end: Optional[str]) -> str:
    """마감일을 아는 경우에만 기한 문장을 만든다(시작일만 있으면 미기재로 둔다)."""
    if start and end:
        return f"{_dot(start)} ~ {_dot(end)}"
    if end:
        return f"{_dot(end)}까지"
    return ""


def _phone(value: Any) -> str:
    raw = re.sub(r"[^0-9]", "", str(value or ""))
    if len(raw) == 10 and raw.startswith("02"):
        return f"{raw[:2]}-{raw[2:6]}-{raw[6:]}"
    if len(raw) == 10:
        return f"{raw[:3]}-{raw[3:6]}-{raw[6:]}"
    if len(raw) == 11:
        return f"{raw[:3]}-{raw[3:7]}-{raw[7:]}"
    return ""


def _narrower_years(field_years: Optional[int], prose_years: Optional[int]) -> Optional[int]:
    if field_years is None:
        return prose_years
    if prose_years is None:
        return field_years
    return min(field_years, prose_years)


def _intersect_age(field: Dict[str, Optional[int]],
                   prose: Dict[str, Optional[int]]) -> Dict[str, Optional[int]]:
    low_a, high_a = field.get("min_age"), field.get("max_age")
    low_b, high_b = prose.get("min_age"), prose.get("max_age")
    if low_a is None and high_a is None:
        return {"min_age": low_b, "max_age": high_b}
    if low_b is None and high_b is None:
        return {"min_age": low_a, "max_age": high_a}
    low = max(value for value in (low_a, low_b) if value is not None) \
        if (low_a is not None or low_b is not None) else None
    highs = [value for value in (high_a, high_b) if value is not None]
    high = min(highs) if highs else None
    if low is not None and high is not None and low > high:
        return {"min_age": low_a, "max_age": high_a}
    return {"min_age": low, "max_age": high}


def business_block(*, text: str, target: str = "", field: str = "",
                   age_text: str = "", years_text: str = "",
                   region_text: str = "", recruiting: Any = "",
                   preferential: str = "", exclude: str = "",
                   hashtags: Optional[Iterable[str]] = None,
                   parsed: bool = True) -> Dict[str, Any]:
    """원문 텍스트 묶음 → 판정 가능한 `business` 블록."""
    prose = " ".join(item for item in (text, target) if item)
    entities = parse_entities(prose)
    if entities == ["pre_startup"]:
        status = "pre"
    elif "pre_startup" in entities:
        status = None          # 예비창업자와 사업자 모두 지원
    elif entities:
        status = "operating"
    else:
        status = None

    field_years = parse_years(years_text) if str(years_text or "").strip() else {"max_years": None}
    max_years = _narrower_years(field_years["max_years"], parse_years_from_prose(prose))

    field_age = parse_age_range(age_text) if str(age_text or "").strip() else {"min_age": None,
                                                                              "max_age": None}
    age = _intersect_age(field_age, parse_age_range(prose) if prose else
                        {"min_age": None, "max_age": None})

    industries = parse_industries(prose)
    industry_required = any(word in prose for word in _INDUSTRY_REQUIRED_WORDS)
    tags = [item.strip() for item in (hashtags or []) if str(item).strip()]
    return {
        "entity": entities,
        "status": status,
        "max_years": max_years,
        "min_years": None,
        "min_age": age["min_age"],
        "max_age": age["max_age"],
        "gender": parse_gender(prose),
        "industries": industries,
        "industry_required": industry_required,
        "recruiting": parse_recruiting(recruiting),
        "field": field,
        "hashtags": tags,
        "preferential": preferential,
        "exclude": exclude,
        "region_text": region_text,
        "parsed": parsed,
    }


# ---------------------------------------------------------------------------
# K-Startup (15125364) — 지원사업 공고 정보
# ---------------------------------------------------------------------------
def normalize_kstartup(row: Dict[str, Any]) -> Dict[str, Any]:
    """K-Startup 공고 1행 → 보조금24와 같은 한국어 키 + `business` 블록."""
    pbanc_sn = _text(row, "pbanc_sn", "biz_pbanc_sn", "공고일련번호")
    title = clean_text(_text(row, "biz_pbanc_nm", "pbanc_nm"), 300)
    agency = clean_text(_text(row, "pbanc_ntrp_nm", "biz_prch_dprt_nm"), 120)
    agency_type_raw = _text(row, "sprv_inst")
    department = clean_text(_text(row, "biz_prch_dprt_nm"), 120)
    field = clean_text(_text(row, "supt_biz_clsfc", "intg_pbanc_biz_nm"), 80)
    target = clean_text(_text(row, "aply_trgt_ctnt", "aply_trgt"), 1200)
    purpose = clean_text(_text(row, "pbanc_ctnt"), 600)
    content = clean_text(_text(row, "support_ctnt", "supt_biz_ctnt"), 1200)
    years_text = _text(row, "biz_enyy")
    age_text = _text(row, "biz_trgt_age")
    region_text = _text(row, "supt_regin")
    preferential = clean_text(_text(row, "prfn_matr"), 400)
    exclude = clean_text(_text(row, "aply_excl_trgt_ctnt"), 400)
    evaluation = clean_text(_text(row, "eval_method"), 600)
    start = _yyyymmdd(_text(row, "pbanc_rcpt_bgng_dt"))
    end = _yyyymmdd(_text(row, "pbanc_rcpt_end_dt"))
    how = " ".join(part for part in (
        clean_text(_text(row, "aply_mthd_onli_rcpt_istc"), 300),
        clean_text(_text(row, "aply_mthd_eml_rcpt_istc"), 200),
        clean_text(_text(row, "aply_mthd_vst_rcpt_istc"), 200),
        clean_text(_text(row, "aply_mthd_etc_istc"), 200)) if part)
    detail = _text(row, "detl_pg_url")

    criteria_parts: List[str] = []
    if target:
        criteria_parts.append(f"신청대상: {target}")
    if exclude:
        criteria_parts.append(f"신청제외: {exclude}")
    if preferential:
        criteria_parts.append(f"우대사항: {preferential}")
    if evaluation and evaluation not in ("없음", "-"):
        criteria_parts.append(f"선정방법: {evaluation}")

    business = business_block(text=title, target=target, field=field,
                              age_text=age_text, years_text=years_text,
                              region_text=region_text,
                              recruiting=_text(row, "rcrt_prgs_yn"),
                              preferential=preferential, exclude=exclude,
                              parsed=bool(target or years_text or region_text))
    region = parse_region_text(region_text)
    online = _text(row, "biz_aply_url", "biz_gdnc_url")
    if online == detail:
        online = ""
    return {
        "서비스ID": f"KSU-{pbanc_sn}" if pbanc_sn else "",
        "서비스명": title,
        "서비스목적요약": purpose,
        "소관기관명": agency,
        "소관기관코드": "",
        "소관기관유형": _agency_type(agency, agency_type_raw),
        "서비스분야": field,
        "사용자구분": "창업기업",
        "지원대상": target,
        "선정기준": " / ".join(criteria_parts),
        "지원내용": content,
        "지원유형": _support_type(field, title),
        "신청방법": how,
        "신청기한": _period_text(start, end),
        "접수기관": department or agency,
        "전화문의": _phone(_text(row, "prch_cnpl_no")),
        "상세조회URL": detail,
        "온라인신청사이트URL": online,
        "구비서류": "",
        "수정일시": "",
        "track": TRACK_BUSINESS,
        "source": SOURCE_KSTARTUP,
        "business": business,
        **({"region": region} if region else {}),
        "extra": {"공고일련번호": pbanc_sn, "지원분야": field,
                  "접수시작일": start or "", "접수종료일": end or ""},
    }


_AGENCY_TYPE_WORDS = ("공공기관", "교육기관", "지방자치단체", "중앙행정기관", "연구기관",
                      "협회", "재단", "기업")


def _agency_type(agency: str, hint: str = "") -> str:
    raw = str(hint or "").strip()
    if raw in _AGENCY_TYPE_WORDS:
        return raw
    if not agency:
        return ""
    if agency.startswith(("중소벤처기업부", "창업진흥원", "중소기업", "소상공인시장진흥공단",
                          "한국", "기술보증기금", "신용보증기금")):
        return "공공기관"
    if regions.canonical_sido(agency) or agency.endswith("도") or agency.endswith("시"):
        return "지방자치단체"
    return "공공기관"


def _support_type(field: str, title: str) -> str:
    haystack = f"{field} {title}"
    for keyword, label in (("정책자금", "자금(융자)"), ("융자", "자금(융자)"),
                           ("보조금", "자금(보조)"), ("사업화", "자금(사업화)"),
                           ("시설", "시설·공간"), ("보육", "시설·공간"),
                           ("멘토링", "멘토링·컨설팅"), ("컨설팅", "멘토링·컨설팅"),
                           ("교육", "교육"), ("행사", "행사·네트워크"),
                           ("네트워크", "행사·네트워크"), ("R&D", "R&D"),
                           ("기술개발", "R&D"), ("수출", "수출·판로")):
        if keyword in haystack:
            return label
    return field or "기타"


# ---------------------------------------------------------------------------
# 기업마당 (15157820) — 중소기업 지원사업 공고
# ---------------------------------------------------------------------------
def normalize_bizinfo(row: Dict[str, Any]) -> Dict[str, Any]:
    """기업마당 공고 1행 → 같은 한국어 키 + `business` 블록(원문 문구 보존)."""
    pblanc_id = _text(row, "pblancId", "공고ID")
    title = clean_text(_text(row, "pblancNm", "공고명"), 300)
    agency = clean_text(_text(row, "jrsdInsttNm", "소관기관명"), 120)
    executor = clean_text(_text(row, "excInsttNm", "수행기관명"), 120)
    field = clean_text(_text(row, "pldirSportRealmLclasCodeNm", "지원분야"), 80)
    target = clean_text(_text(row, "trgetNm", "지원대상"), 300)
    summary = clean_text(_text(row, "bsnsSumryCn", "사업개요내용"), 1200)
    period = clean_text(_text(row, "reqstBeginEndDe", "신청기간"), 200)
    how = clean_text(_text(row, "reqstMthPapersCn", "사업신청방법내용"), 600)
    contact = clean_text(_text(row, "refrncNm", "문의처"), 300)
    hashtags = [item.strip() for item in _text(row, "hashtags").split(",") if item.strip()]
    detail = _text(row, "pblancUrl", "기업마당URL")
    online = _text(row, "rceptEngnHmpgUrl", "사업신청URL")
    updated = clean_text(_text(row, "updtPnttm", "수정일시"), 40)
    created = clean_text(_text(row, "creatPnttm", "등록일시"), 40)

    read_text = " ".join(item for item in (target, summary) if item)
    business = business_block(text=title, target=read_text, field=field,
                              region_text=agency, recruiting="Y",
                              hashtags=hashtags,
                              parsed=bool(read_text.strip()))
    region = parse_region_text(agency)
    return {
        "서비스ID": f"BIZ-{pblanc_id}" if pblanc_id else "",
        "서비스명": title,
        "서비스목적요약": summary,
        "소관기관명": agency,
        "소관기관코드": "",
        "소관기관유형": _agency_type(agency) or "공공기관",
        "서비스분야": field,
        "사용자구분": "중소기업·소상공인",
        "지원대상": target,
        "선정기준": "",
        "지원내용": summary,
        "지원유형": _support_type(field, title),
        "신청방법": how,
        "신청기한": period,
        "접수기관": executor if executor and executor != "기초자치단체" else agency,
        "전화문의": contact,
        "상세조회URL": detail,
        "온라인신청사이트URL": online,
        "구비서류": "",
        "수정일시": updated or created,
        "track": TRACK_BUSINESS,
        "source": SOURCE_BIZINFO,
        "business": business,
        **({"region": region} if region else {}),
        "extra": {"공고ID": pblanc_id, "해시태그": hashtags},
    }


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------
def business_summary(block: Dict[str, Any]) -> str:
    """사람이 읽는 요건 한 줄(웹 UI·MCP 텍스트 요약용)."""
    parts: List[str] = []
    entities = [ENTITY_LABELS.get(slug, slug) for slug in block.get("entity") or []]
    if entities:
        parts.append("대상 " + "·".join(dict.fromkeys(entities)))
    if block.get("max_years") is not None:
        parts.append(f"업력 {block['max_years']}년 이내")
    low, high = block.get("min_age"), block.get("max_age")
    if low is not None or high is not None:
        if low is not None and high is not None:
            parts.append(f"만 {low}~{high}세")
        elif high is not None:
            parts.append(f"만 {high}세 이하")
        else:
            parts.append(f"만 {low}세 이상")
    if block.get("gender") == "female":
        parts.append("여성 대상")
    elif block.get("gender") == "male":
        parts.append("남성 대상")
    if block.get("recruiting") == "closed":
        parts.append("모집 마감")
    return " · ".join(parts)


def is_current(record: Dict[str, Any], today: Optional[date] = None,
               grace_days: int = 30) -> bool:
    """지금 신청할 수 있거나 최근 마감된 공고인가.

    지난 공고(수년 전)를 카탈로그에 쌓아 두면 검색이 과거 공고로 채워집니다.
    K-Startup 은 2016년부터 3만 건이 오므로 동기화 때 이 함수로 걸러 냅니다.
    """
    now = today or date.today()
    business = record.get("business") or {}
    if business.get("recruiting") == "closed":
        return False
    parsed = deadlines.parse_deadline(record.get("신청기한"), today=now)
    end = parsed.get("end_date")
    if not end:
        return True
    try:
        end_date = date.fromisoformat(str(end))
    except ValueError:
        return True
    return end_date >= (now - timedelta(days=max(0, grace_days)))


def track_label(track: str) -> str:
    return TRACK_LABELS.get(track, track)


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


def source_attribution(source: str) -> str:
    return SOURCE_ATTRIBUTION.get(source, "")
