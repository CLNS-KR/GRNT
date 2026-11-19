"""판정 등급 정의. 서비스 전체가 이 네 단어만 씁니다."""
from __future__ import annotations

from typing import Any, Dict, List

VERDICT_ELIGIBLE = "eligible_likely"
VERDICT_CHECK = "check_needed"
VERDICT_INSUFFICIENT = "insufficient_info"
VERDICT_INELIGIBLE = "ineligible"

# 화면·정렬 순서(위에서부터 먼저 보여 준다)
VERDICT_ORDER: List[str] = [
    VERDICT_ELIGIBLE,
    VERDICT_CHECK,
    VERDICT_INSUFFICIENT,
    VERDICT_INELIGIBLE,
]

VERDICT_LABELS_KO: Dict[str, str] = {
    VERDICT_ELIGIBLE: "받을 가능성 높음",
    VERDICT_CHECK: "조건 확인 필요",
    VERDICT_INSUFFICIENT: "정보 부족",
    VERDICT_INELIGIBLE: "해당 없음",
}

VERDICT_LABELS_EN: Dict[str, str] = {
    VERDICT_ELIGIBLE: "Likely eligible",
    VERDICT_CHECK: "Needs confirmation",
    VERDICT_INSUFFICIENT: "More information needed",
    VERDICT_INELIGIBLE: "Not eligible",
}

VERDICT_DEFINITIONS_KO: Dict[str, str] = {
    VERDICT_ELIGIBLE: (
        "공개된 자격 코드(연령·성별·소득구간·생애·가구)를 입력 조건이 모두 충족했습니다. "
        "코드로 표현되지 않은 재산·거주기간 등은 원문에서 확인해야 합니다."
    ),
    VERDICT_CHECK: (
        "코드 조건은 맞지만, 지자체 원본의 선정기준이 비어 있거나 추첨·선착순처럼 "
        "결과를 미리 알 수 없는 요건이 있어 소관기관 확인이 필요합니다."
    ),
    VERDICT_INSUFFICIENT: (
        "판정에 필요한 입력(소득구간·가구형태·거주지 등)이 없어 가능/불가를 말하지 않습니다. "
        "무엇을 더 알려 주면 판정되는지 함께 반환합니다."
    ),
    VERDICT_INELIGIBLE: (
        "입력 조건과 공개된 자격 코드가 명확히 어긋납니다. 어긋난 항목과 원문 기준을 함께 반환합니다."
    ),
}

# 집계·정렬에서 '얼마나 확실한가'를 비교할 때 쓴다(높을수록 확정에 가깝다).
VERDICT_CONFIDENCE: Dict[str, int] = {
    VERDICT_ELIGIBLE: 3,
    VERDICT_CHECK: 2,
    VERDICT_INELIGIBLE: 2,
    VERDICT_INSUFFICIENT: 1,
}


def verdict_block(code: str) -> Dict[str, Any]:
    return {
        "code": code,
        "label_ko": VERDICT_LABELS_KO.get(code, code),
        "label_en": VERDICT_LABELS_EN.get(code, code),
        "definition_ko": VERDICT_DEFINITIONS_KO.get(code, ""),
        "determinative": False,
    }


def worst(codes: List[str]) -> str:
    """여러 판정을 하나로 합칠 때(불가 > 정보부족 > 확인필요 > 가능)."""
    if VERDICT_INELIGIBLE in codes:
        return VERDICT_INELIGIBLE
    if VERDICT_INSUFFICIENT in codes:
        return VERDICT_INSUFFICIENT
    if VERDICT_CHECK in codes:
        return VERDICT_CHECK
    return VERDICT_ELIGIBLE


SORT_INDEX: Dict[str, int] = {code: index for index, code in enumerate(VERDICT_ORDER)}
