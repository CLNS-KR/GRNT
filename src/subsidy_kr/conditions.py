"""`supportConditions` 자격 코드 체계 (JA 코드) 해석.

보조금24(정부24 공공서비스) API의 지원조건은 **서비스 1건당 한 행**에
`JA0101` ~ `JA2299` 열이 늘어선 넓은 표(wide row)입니다. 각 열은 `Y` 또는 빈 값이고,
연령(`JA0110`·`JA0111`)만 숫자입니다.

판정 규칙(공식 코드 정의를 그대로 옮긴 것)
------------------------------------------
- 성별: `JA0101`/`JA0102` 중 **한쪽만** 켜져 있으면 그 성별만 대상. 둘 다/없음이면 제한 없음.
- 연령: `JA0110` 시작 ~ `JA0111` 종료(포함). 0 이하는 하한 없음, 100 이상(원천에 120·200이 옴)은 상한 없음.
- 중위소득: `JA0201`~`JA0205` 중 켜진 구간 안에 사용자의 소득 구간이 있어야 함(구간끼리 OR).
- 생애·가구·직업: **같은 묶음 안은 OR**(임산부 또는 출산), **묶음 사이는 AND**(임산부이면서 무주택).
- `해당사항없음`(`JA0322`·`JA0410`)이 켜져 있으면 그 묶음은 누구나 통과.

이 모듈은 코드 표만 다루고, 실제 판정은 `engine.py`가 합니다.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

GROUP_GENDER = "gender"
GROUP_AGE = "age"
GROUP_INCOME = "income"
GROUP_LIFE = "life"
GROUP_HOUSEHOLD = "household"
GROUP_BUSINESS = "business"

GROUP_LABELS: Dict[str, str] = {
    GROUP_GENDER: "성별",
    GROUP_AGE: "연령",
    GROUP_INCOME: "소득(기준 중위소득)",
    GROUP_LIFE: "생애·직업 상황",
    GROUP_HOUSEHOLD: "가구 형태",
    GROUP_BUSINESS: "사업자·소상공인",
}

# 코드 → (묶음, 표기). 2026-11-19 공공데이터포털 15113968 출력규격 기준.
CODE_CATALOG: Dict[str, Tuple[str, str]] = {
    "JA0101": (GROUP_GENDER, "남성"),
    "JA0102": (GROUP_GENDER, "여성"),
    "JA0110": (GROUP_AGE, "대상연령(시작)"),
    "JA0111": (GROUP_AGE, "대상연령(종료)"),
    "JA0201": (GROUP_INCOME, "중위소득 0~50%"),
    "JA0202": (GROUP_INCOME, "중위소득 51~75%"),
    "JA0203": (GROUP_INCOME, "중위소득 76~100%"),
    "JA0204": (GROUP_INCOME, "중위소득 101~200%"),
    "JA0205": (GROUP_INCOME, "중위소득 200% 초과"),
    "JA0301": (GROUP_LIFE, "예비부모·난임"),
    "JA0302": (GROUP_LIFE, "임산부"),
    "JA0303": (GROUP_LIFE, "출산·입양"),
    "JA0313": (GROUP_LIFE, "농업인"),
    "JA0314": (GROUP_LIFE, "어업인"),
    "JA0315": (GROUP_LIFE, "축산업인"),
    "JA0316": (GROUP_LIFE, "임업인"),
    "JA0317": (GROUP_LIFE, "초등학생"),
    "JA0318": (GROUP_LIFE, "중학생"),
    "JA0319": (GROUP_LIFE, "고등학생"),
    "JA0320": (GROUP_LIFE, "대학생·대학원생"),
    "JA0322": (GROUP_LIFE, "해당사항없음(생애)"),
    "JA0326": (GROUP_LIFE, "근로자·직장인"),
    "JA0327": (GROUP_LIFE, "구직자·실업자"),
    "JA0328": (GROUP_LIFE, "장애인"),
    "JA0329": (GROUP_LIFE, "국가보훈대상자"),
    "JA0330": (GROUP_LIFE, "질병·질환자"),
    "JA0401": (GROUP_HOUSEHOLD, "다문화가족"),
    "JA0402": (GROUP_HOUSEHOLD, "북한이탈주민"),
    "JA0403": (GROUP_HOUSEHOLD, "한부모·조손가정"),
    "JA0404": (GROUP_HOUSEHOLD, "1인가구"),
    "JA0410": (GROUP_HOUSEHOLD, "해당사항없음(가구)"),
    "JA0411": (GROUP_HOUSEHOLD, "다자녀가구"),
    "JA0412": (GROUP_HOUSEHOLD, "무주택세대"),
    "JA0413": (GROUP_HOUSEHOLD, "신규전입"),
    "JA0414": (GROUP_HOUSEHOLD, "확대가족"),
    "JA1101": (GROUP_BUSINESS, "예비창업자"),
    "JA1102": (GROUP_BUSINESS, "영업중"),
    "JA1103": (GROUP_BUSINESS, "생계곤란·폐업예정자"),
    "JA1201": (GROUP_BUSINESS, "음식업"),
    "JA1202": (GROUP_BUSINESS, "제조업"),
    "JA1299": (GROUP_BUSINESS, "기타업종"),
    "JA2101": (GROUP_BUSINESS, "중소기업"),
    "JA2102": (GROUP_BUSINESS, "사회복지시설"),
    "JA2103": (GROUP_BUSINESS, "기관·단체"),
    "JA2201": (GROUP_BUSINESS, "제조업(업종)"),
    "JA2202": (GROUP_BUSINESS, "농림어업(업종)"),
    "JA2203": (GROUP_BUSINESS, "정보통신업"),
    "JA2299": (GROUP_BUSINESS, "기타업종(업종)"),
}

# 사용자가 고르는 '상황 태그' → 자격 코드.
# 한 태그가 여러 코드에 걸릴 수 있고(농업인=JA0313), 코드가 둘로 갈리는 태그도 있다.
SITUATIONS: Dict[str, Dict[str, Any]] = {
    "pregnant": {"label_ko": "임신 중", "codes": ["JA0302"], "group": GROUP_LIFE},
    "expecting_parent": {"label_ko": "임신 준비·난임", "codes": ["JA0301"], "group": GROUP_LIFE},
    "birth": {"label_ko": "출산·입양", "codes": ["JA0303"], "group": GROUP_LIFE},
    "parenting": {"label_ko": "영유아 양육", "codes": ["JA0303"], "group": GROUP_LIFE},
    "student": {"label_ko": "초·중·고 재학", "codes": ["JA0317", "JA0318", "JA0319"], "group": GROUP_LIFE},
    "college_student": {"label_ko": "대학(원)생", "codes": ["JA0320"], "group": GROUP_LIFE},
    "worker": {"label_ko": "근로자·직장인", "codes": ["JA0326"], "group": GROUP_LIFE},
    "jobseeker": {"label_ko": "구직자·실업자", "codes": ["JA0327"], "group": GROUP_LIFE},
    "disabled": {"label_ko": "장애인", "codes": ["JA0328"], "group": GROUP_LIFE},
    "veteran": {"label_ko": "국가보훈대상자", "codes": ["JA0329"], "group": GROUP_LIFE},
    "illness": {"label_ko": "질병·질환", "codes": ["JA0330"], "group": GROUP_LIFE},
    "farmer": {"label_ko": "농업인", "codes": ["JA0313"], "group": GROUP_LIFE},
    "fisher": {"label_ko": "어업인", "codes": ["JA0314"], "group": GROUP_LIFE},
    "livestock": {"label_ko": "축산업인", "codes": ["JA0315"], "group": GROUP_LIFE},
    "forestry": {"label_ko": "임업인", "codes": ["JA0316"], "group": GROUP_LIFE},
    "multicultural": {"label_ko": "다문화가족", "codes": ["JA0401"], "group": GROUP_HOUSEHOLD},
    "north_korean": {"label_ko": "북한이탈주민", "codes": ["JA0402"], "group": GROUP_HOUSEHOLD},
    "single_parent": {"label_ko": "한부모·조손", "codes": ["JA0403"], "group": GROUP_HOUSEHOLD},
    "single_household": {"label_ko": "1인가구", "codes": ["JA0404"], "group": GROUP_HOUSEHOLD},
    "multi_child": {"label_ko": "다자녀(2명 이상)", "codes": ["JA0411"], "group": GROUP_HOUSEHOLD},
    "no_home": {"label_ko": "무주택", "codes": ["JA0412"], "group": GROUP_HOUSEHOLD},
    "new_move": {"label_ko": "최근 전입", "codes": ["JA0413"], "group": GROUP_HOUSEHOLD},
    "extended_family": {"label_ko": "확대가족", "codes": ["JA0414"], "group": GROUP_HOUSEHOLD},
    "small_business": {"label_ko": "소상공인·자영업", "codes": ["JA2101", "JA1102"], "group": GROUP_BUSINESS},
    "startup": {"label_ko": "예비창업자", "codes": ["JA1101"], "group": GROUP_BUSINESS},
    "closing": {"label_ko": "폐업 예정·생계곤란", "codes": ["JA1103"], "group": GROUP_BUSINESS},
    "food_business": {"label_ko": "음식업", "codes": ["JA1201"], "group": GROUP_BUSINESS},
    "manufacturing": {"label_ko": "제조업", "codes": ["JA1202"], "group": GROUP_BUSINESS},
    "organization": {"label_ko": "기관·단체", "codes": ["JA2103"], "group": GROUP_BUSINESS},
}

# '해당사항없음' 코드: 켜져 있으면 그 묶음을 누구나 통과한다.
GROUP_ANY_CODES: Dict[str, Tuple[str, ...]] = {
    GROUP_LIFE: ("JA0322",),
    GROUP_HOUSEHOLD: ("JA0410",),
}

INCOME_BANDS: List[str] = ["JA0201", "JA0202", "JA0203", "JA0204", "JA0205"]

INCOME_PERCENT_RANGES: Dict[str, Tuple[float, Optional[float]]] = {
    "JA0201": (0.0, 50.0),
    "JA0202": (50.01, 75.0),
    "JA0203": (75.01, 100.0),
    "JA0204": (100.01, 200.0),
    "JA0205": (200.01, None),
}

# 묶음별 '무엇을 물어야 하는지' 문구
GROUP_QUESTIONS: Dict[str, str] = {
    GROUP_LIFE: "임신·출산·구직·장애 등 해당하는 상황이 있는지",
    GROUP_HOUSEHOLD: "무주택·1인가구·다자녀·한부모 등 가구 형태",
    GROUP_BUSINESS: "사업자등록·소상공인 여부(개인만 해당)",
    GROUP_INCOME: "가구 소득이 기준 중위소득 몇 % 구간인지",
    GROUP_AGE: "만 나이(또는 출생연도)",
    GROUP_GENDER: "성별",
}


def is_on(value: Any) -> bool:
    """`Y`·숫자>0·`true` 를 켜짐으로 본다. 빈 값·`N`·0 은 꺼짐."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().upper()
    if text in ("", "N", "NO", "FALSE", "0", "0.0"):
        return False
    return True


def normalize_conditions(row: Dict[str, Any]) -> Dict[str, Any]:
    """API 한 행(넓은 표) 또는 {코드: 값} 딕셔너리 → {켜진 코드: 값} 딕셔너리."""
    if not isinstance(row, dict):
        return {}
    # 이미 {코드: 값} 형태로 들어온 경우(내장 샘플·동기화 산출물)
    if "conditions" in row and isinstance(row["conditions"], dict):
        source = row["conditions"]
    else:
        source = row
    out: Dict[str, Any] = {}
    for code in CODE_CATALOG:
        if code in source and is_on(source.get(code)):
            out[code] = source.get(code)
    return out


def group_codes(conds: Dict[str, Any]) -> Dict[str, List[str]]:
    """켜진 코드를 묶음별로 나눈다(연령 시작/끝은 연령 묶음에 함께)."""
    groups: Dict[str, List[str]] = {group: [] for group in GROUP_LABELS}
    for code, _value in conds.items():
        group = CODE_CATALOG.get(code, (None, ""))[0]
        if group:
            groups.setdefault(group, []).append(code)
    return groups


def age_range(conds: Dict[str, Any]) -> Dict[str, Any]:
    """`JA0110`·`JA0111` → {min_age, max_age, limited} (None = 제한 없음)."""
    raw_min = conds.get("JA0110")
    raw_max = conds.get("JA0111")

    def _num(value: Any) -> Optional[float]:
        if value is None or str(value).strip() == "":
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    low, high = _num(raw_min), _num(raw_max)
    min_age = int(low) if low is not None and low > 0 else None
    max_age = int(high) if high is not None and 0 < high < 100 else None
    return {
        "min_age": min_age,
        "max_age": max_age,
        "limited": min_age is not None or max_age is not None,
        "raw_min": raw_min,
        "raw_max": raw_max,
        "note_ko": ("0 이하는 하한 없음, 100 이상은 상한 없음으로 해석합니다."),
    }


def income_bands(conds: Dict[str, Any]) -> List[str]:
    return [code for code in INCOME_BANDS if code in conds]


def gender_scope(conds: Dict[str, Any]) -> str:
    """`male` · `female` · `any`."""
    male, female = "JA0101" in conds, "JA0102" in conds
    if male and not female:
        return "male"
    if female and not male:
        return "female"
    return "any"


def band_for_percent(percent: Optional[float]) -> Optional[str]:
    """중위소득 % → 구간 코드. 0 미만·비정상은 None."""
    if percent is None:
        return None
    value = float(percent)
    if value < 0:
        return None
    for code, (low, high) in INCOME_PERCENT_RANGES.items():
        if value >= low and (high is None or value <= high):
            return code
    return None


def band_label(code: Optional[str]) -> str:
    return CODE_CATALOG.get(code or "", (None, "미입력"))[1]


def codes_for_situations(situations: Iterable[str]) -> Dict[str, List[str]]:
    """상황 태그 목록 → {묶음: [코드...]}."""
    out: Dict[str, List[str]] = {}
    for key in situations:
        spec = SITUATIONS.get(str(key).strip())
        if not spec:
            continue
        out.setdefault(spec["group"], [])
        for code in spec["codes"]:
            if code not in out[spec["group"]]:
                out[spec["group"]].append(code)
    return out


def situation_keys() -> List[str]:
    return list(SITUATIONS)


def describe_code(code: str) -> str:
    group, label = CODE_CATALOG.get(code, (None, code))
    return f"{label} ({code})" if group else code


def group_label(group: str) -> str:
    return GROUP_LABELS.get(group, group)
