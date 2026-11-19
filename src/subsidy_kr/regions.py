"""시도·시군구 정규화와 '소관기관명 → 지역' 판별.

공공서비스 API에는 지역 코드가 없습니다. 소관기관명(`서울특별시 강남구`,
`인천광역시 서구`, `마포구시설관리공단`)만으로 지역을 판별해야 하는데,
`중구`·`서구`·`고성군`처럼 여러 시도에 있는 이름은 **억지로 찍지 않고**
'지역 미확인'으로 남깁니다. 틀린 지역으로 후보를 걸러내는 것보다
"확인 필요"가 낫기 때문입니다.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

from .regions_data import SIGUNGU_BY_SIDO

# 시도 정식 명칭 → 코드 앞 2자리
SIDO_CODES: Dict[str, str] = {
    "서울특별시": "11",
    "부산광역시": "26",
    "대구광역시": "27",
    "인천광역시": "28",
    "광주광역시": "29",
    "대전광역시": "30",
    "울산광역시": "31",
    "세종특별자치시": "36",
    "경기도": "41",
    "강원특별자치도": "42",
    "충청북도": "43",
    "충청남도": "44",
    "전북특별자치도": "45",
    "전라남도": "46",
    "경상북도": "47",
    "경상남도": "48",
    "제주특별자치도": "50",
}

# 짧은 이름·개편 전 이름·흔한 표기
SIDO_ALIASES: Dict[str, str] = {
    "서울": "서울특별시", "서울시": "서울특별시",
    "부산": "부산광역시", "부산시": "부산광역시",
    "대구": "대구광역시", "대구시": "대구광역시",
    "인천": "인천광역시", "인천시": "인천광역시",
    "광주": "광주광역시", "광주시": "광주광역시",
    "대전": "대전광역시", "대전시": "대전광역시",
    "울산": "울산광역시", "울산시": "울산광역시",
    "세종": "세종특별자치시", "세종시": "세종특별자치시",
    "경기": "경기도", "경기도": "경기도",
    "강원": "강원특별자치도", "강원도": "강원특별자치도",
    "충북": "충청북도", "충청북도": "충청북도",
    "충남": "충청남도", "충청남도": "충청남도",
    "전북": "전북특별자치도", "전라북도": "전북특별자치도",
    "전남": "전라남도", "전라남도": "전라남도",
    "경북": "경상북도", "경상북도": "경상북도",
    "경남": "경상남도", "경상남도": "경상남도",
    "제주": "제주특별자치도", "제주도": "제주특별자치도",
    "제주특별자치도": "제주특별자치도",
}

# 시군구 명부에 남아 있는 개편 전 이름 (2023-07 배포본 기준)
SIGUNGU_ALIASES: Dict[str, str] = {
    "미추홀구": "미추홀구",
    "부천": "부천시",
    "청주": "청주시 흥덕구",
}

_PROVINCE_SUFFIX = ("특별시", "광역시", "특별자치시", "특별자치도", "도")

# 시군구 이름 → 소속 시도들 (동명 시군구 판별용)
_SIGUNGU_INDEX: Dict[str, List[str]] = {}
# 접미사(시·군·구)를 뗀 짧은 이름 → 소속 시도들 (`구리도시공사`, `남동문화재단` 같은 기관명용)
_SHORT_INDEX: Dict[str, List[str]] = {}
for _sido, _rows in SIGUNGU_BY_SIDO.items():
    for _code, _name in _rows:
        short = _name.split()[-1] if " " in _name else _name
        _SIGUNGU_INDEX.setdefault(short, [])
        if _sido not in _SIGUNGU_INDEX[short]:
            _SIGUNGU_INDEX[short].append(_sido)
        if _name not in _SIGUNGU_INDEX:
            _SIGUNGU_INDEX[_name] = [_sido]
        stem = short[:-1] if short.endswith(("시", "군", "구")) else short
        if len(stem) >= 2:
            _SHORT_INDEX.setdefault(stem, [])
            if _sido not in _SHORT_INDEX[stem]:
                _SHORT_INDEX[stem].append(_sido)


def sido_names() -> List[str]:
    return list(SIDO_CODES)


def sigungu_names(sido: str) -> List[Tuple[str, str]]:
    """(코드, 명칭) 목록. 모르는 시도면 빈 목록."""
    canonical = canonical_sido(sido)
    return list(SIGUNGU_BY_SIDO.get(canonical or "", []))


def canonical_sido(value: Optional[str]) -> Optional[str]:
    """'인천', '인천시', '인천서구' → '인천광역시'. 모르면 None."""
    raw = re.sub(r"\s+", "", str(value or ""))
    if not raw:
        return None
    if raw in SIDO_CODES:
        return raw
    if raw in SIDO_ALIASES:
        return SIDO_ALIASES[raw]
    for canonical in SIDO_CODES:
        if raw.startswith(canonical):
            return canonical
    for alias, canonical in sorted(SIDO_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if raw.startswith(alias):
            return canonical
    return None


def canonical_sigungu(sido: Optional[str], value: Optional[str]) -> Optional[str]:
    """시도 안에서 시군구 이름을 정식 표기로 맞춘다.

    '서구' → '서구', '수원 장안구' → '수원시 장안구', '구리' → '구리시'.
    같은 이름이 여러 시도에 있더라도 시도가 정해져 있으면 그 안에서 고른다.
    """
    raw = re.sub(r"\s+", "", str(value or ""))
    if not raw:
        return None
    province = canonical_sido(sido)
    rows = SIGUNGU_BY_SIDO.get(province or "", [])
    if province and raw == province:
        return None
    candidates: List[str] = []
    for _code, name in rows:
        compact = name.replace(" ", "")
        if raw == compact or compact.endswith(raw) or raw.endswith(compact):
            candidates.append(name)
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        exact = [name for name in candidates if name.replace(" ", "") == raw]
        return exact[0] if len(exact) == 1 else None
    # 접미사가 빠진 이름('수원 장안구', '구리')과 띄어쓰기만 다른 이름
    stripped = re.sub(r"[시군구]", "", raw)
    fuzzy = [name for _code, name in rows
             if stripped and re.sub(r"[시군구]", "", name.replace(" ", "")) == stripped]
    if len(fuzzy) == 1:
        return fuzzy[0]
    stems = [name for _code, name in rows if name.replace(" ", "")[:-1] == raw]
    if len(stems) == 1:
        return stems[0]
    if raw in SIGUNGU_ALIASES:
        alias = SIGUNGU_ALIASES[raw]
        return alias if any(alias == name for _c, name in rows) else None
    return None


def find_sido_by_sigungu(value: Optional[str]) -> Tuple[Optional[str], str]:
    """시도 없이 들어온 시군구 이름 → (시도, 상태).

    상태: `unique`(한 곳), `ambiguous`(여러 시도), `unknown`.
    """
    raw = re.sub(r"\s+", "", str(value or ""))
    if not raw:
        return None, "unknown"
    hits = _SIGUNGU_INDEX.get(raw) or _SIGUNGU_INDEX.get(raw.split("구")[0] + "구" if raw.endswith("구") else raw) or []
    if len(hits) == 1:
        return hits[0], "unique"
    if len(hits) > 1:
        return None, "ambiguous"
    return None, "unknown"


def region_block(sido: Optional[str] = None, sigungu: Optional[str] = None) -> Dict[str, str]:
    """{'level': national|sido|sigungu|local_unresolved|unknown, 'sido','sigungu','label'}"""
    province = canonical_sido(sido)
    if not province and sigungu:
        found, state = find_sido_by_sigungu(sigungu)
        if state == "unique":
            province = found
    if not province:
        if sigungu:
            return {"level": "local_unresolved", "sido": "", "sigungu": str(sigungu),
                    "label": str(sigungu)}
        return {"level": "national", "sido": "", "sigungu": "", "label": "전국"}
    district = canonical_sigungu(province, sigungu)
    if sigungu and not district:
        return {"level": "sido", "sido": province, "sigungu": "",
                "label": province, "unresolved_sigungu": str(sigungu)}
    if district:
        return {"level": "sigungu", "sido": province, "sigungu": district,
                "label": f"{province} {district}"}
    return {"level": "sido", "sido": province, "sigungu": "", "label": province}


_LOCAL_PREFIXES = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
                   "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주")


def parse_agency_region(agency_name: Optional[str]) -> Dict[str, str]:
    """소관기관명에서 지역을 읽는다.

    1. 시도 이름으로 시작하면 그 시도를 쓰고, 이어지는 시군구 이름을 찾는다.
    2. 시도가 없으면 시군구 이름으로 역추적한다(유일할 때만).
    3. 지자체처럼 보이는데 특정할 수 없으면 `local_unresolved`로 남긴다.
    """
    raw = re.sub(r"\s+", "", str(agency_name or ""))
    if not raw:
        return {"level": "unknown", "sido": "", "sigungu": "", "label": "소관기관 미기재"}

    # '광주시'는 광주광역시와 경기도 광주시가 겹친다 — 기관명에서는 찍지 않는다.
    if raw.startswith("광주시") and not raw.startswith("광주광역시"):
        return {"level": "local_unresolved", "sido": "", "sigungu": "광주시",
                "label": "광주시(광주광역시/경기도 광주시 미확인)"}

    province = None
    matched_prefix = ""
    for prefix in sorted(list(SIDO_CODES) + list(SIDO_ALIASES), key=len, reverse=True):
        if raw.startswith(prefix):
            province = SIDO_ALIASES.get(prefix, prefix)
            matched_prefix = prefix
            break
    if province:
        rest = raw[len(matched_prefix):]
        if rest.startswith(province.replace(" ", "")):
            rest = rest[len(province.replace(" ", "")):]
        # '세종특별자치시'처럼 시도와 시군구 이름이 같은 경우
        if not rest or rest == province.replace(" ", ""):
            return {"level": "sido", "sido": province, "sigungu": "", "label": province}
        if rest in ("시", "군", "구"):
            # '제주시'·'광주시'처럼 시도 접두 + 접미사만 있는 경우
            only = canonical_sigungu(province, matched_prefix + rest)
            if only:
                return {"level": "sigungu", "sido": province, "sigungu": only,
                        "label": f"{province} {only}"}
            return {"level": "sido", "sido": province, "sigungu": "", "label": province}
        district = canonical_sigungu(province, rest[:8]) if rest else None
        if district is None and rest:
            # '서구시설관리공단'처럼 뒤에 기관명이 붙는 경우 앞부분만 떼어 본다
            for length in range(len(rest), 1, -1):
                district = canonical_sigungu(province, rest[:length])
                if district:
                    break
        if district:
            return {"level": "sigungu", "sido": province, "sigungu": district,
                    "label": f"{province} {district}"}
        return {"level": "sido", "sido": province, "sigungu": "", "label": province}

    for name, sidos in sorted(_SIGUNGU_INDEX.items(), key=lambda kv: -len(kv[0])):
        if len(name) < 2 or name not in raw:
            continue
        if len(sidos) == 1:
            district = canonical_sigungu(sidos[0], name)
            if district:
                return {"level": "sigungu", "sido": sidos[0], "sigungu": district,
                        "label": f"{sidos[0]} {district}"}
        else:
            return {"level": "local_unresolved", "sido": "", "sigungu": name,
                    "label": f"{name}(시도 미확인)"}

    # '구리도시공사', '남동문화재단'처럼 접미사가 생략된 기관명 (앞에 수식어가 붙기도 한다)
    for stem, sidos in sorted(_SHORT_INDEX.items(), key=lambda kv: -len(kv[0])):
        if stem not in raw or len(sidos) != 1:
            continue
        district = canonical_sigungu(sidos[0], stem)
        if district:
            return {"level": "sigungu", "sido": sidos[0], "sigungu": district,
                    "label": f"{sidos[0]} {district}"}

    if any(prefix in raw for prefix in _LOCAL_PREFIXES) or raw.endswith(_PROVINCE_SUFFIX):
        return {"level": "local_unresolved", "sido": "", "sigungu": "", "label": raw[:40]}
    return {"level": "national", "sido": "", "sigungu": "", "label": "전국"}


def match_region(user: Dict[str, str], service: Dict[str, str]) -> Dict[str, str]:
    """사용자 지역과 제도 지역을 비교한다.

    반환 state: `match` · `mismatch` · `unknown`(어느 한쪽을 특정할 수 없음).
    전국 제도는 지역과 무관하게 `match`.
    """
    level = str(service.get("level") or "national")
    if level == "national":
        return {"state": "match", "reason_ko": "전국 단위 제도"}
    if level == "local_unresolved":
        return {"state": "unknown",
                "reason_ko": "지자체 제도로 보이나 소관기관명만으로 지역을 특정할 수 없습니다."}
    user_level = str(user.get("level") or "national")
    if user_level in ("national", "unknown", "local_unresolved"):
        return {"state": "unknown", "reason_ko": "거주 지역이 입력되지 않았거나 시·도를 특정할 수 없습니다."}
    if user.get("sido") != service.get("sido"):
        return {"state": "mismatch",
                "reason_ko": f"{service.get('sido')} 제도로, 거주 지역({user.get('sido')})과 다릅니다."}
    if level == "sido":
        return {"state": "match", "reason_ko": f"{service.get('sido')} 단위 제도"}
    if not user.get("sigungu"):
        return {"state": "unknown",
                "reason_ko": f"{service.get('sido')} 안에서 시·군·구를 입력해야 확인됩니다."}
    if user.get("sigungu") != service.get("sigungu"):
        return {"state": "mismatch",
                "reason_ko": f"{service.get('sigungu')} 제도로, 거주 시·군·구와 다릅니다."}
    return {"state": "match", "reason_ko": f"{service.get('sigungu')} 단위 제도"}


def region_label(sido: Optional[str], sigungu: Optional[str] = None) -> str:
    block = region_block(sido, sigungu)
    return block["label"]


def iter_all_regions() -> Iterable[Tuple[str, str, str]]:
    """(시도, 시군구, 5자리 코드) 전수. pSEO·통계에서 쓴다."""
    for sido, rows in SIGUNGU_BY_SIDO.items():
        for code, name in rows:
            yield sido, name, code
