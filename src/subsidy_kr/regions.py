"""시도·시군구 정규화와 '소관기관명 → 지역' 판별.

공공서비스 API에는 지역 코드가 없습니다. 소관기관명(`서울특별시 강남구`,
`인천광역시 서구`, `마포구시설관리공단`)만으로 지역을 판별해야 하는데,
`중구`·`서구`·`고성군`처럼 여러 시도에 있는 이름은 **억지로 찍지 않고**
'지역 미확인'으로 남깁니다. 틀린 지역으로 후보를 걸러내는 것보다
"확인 필요"가 낫기 때문입니다.
"""
from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from .regions_data import SIGUNGU_BY_SIDO as _RAW_SIGUNGU_BY_SIDO

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
    "서구": "서해구",
    "인천서구": "서해구",
}

_PROVINCE_SUFFIX = ("특별시", "광역시", "특별자치시", "특별자치도", "도")

# 시·군·구 명부는 2023-07 배포본이라 개편 전 시도 이름(전라북도·강원도)을 씁니다.
# 명부를 그대로 두면 `canonical_sigungu('전북특별자치도', '완주군')` 이 빈 값을 돌려주고,
# 전북 공고가 전부 시·도 단위로 뭉개집니다. 그래서 읽을 때 정식 명칭으로 맞춥니다.
_SIGUNGU_SIDO_ALIASES: Dict[str, str] = {
    "전라북도": "전북특별자치도",
    "강원도": "강원특별자치도",
}

SIGUNGU_BY_SIDO: Dict[str, List[Tuple[str, str]]] = {}
for _raw_sido, _raw_rows in _RAW_SIGUNGU_BY_SIDO.items():
    SIGUNGU_BY_SIDO.setdefault(_SIGUNGU_SIDO_ALIASES.get(_raw_sido, _raw_sido), []).extend(
        list(_raw_rows))

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


# ---------------------------------------------------------------------------
# 시·도별 SEO 허브 — `GET /regions/` · `GET /regions/{slug}`
#
# 왜 별도 페이지인가
# -----------------
# `/s/{slug}`(pseo)는 카탈로그 전체를 주제·지역으로 훑어 '목록'을 붙이는 페이지입니다.
# 여기서는 검색어가 실제로 들어오는 **시·도 이름**마다 한 장씩 두고, 그 지역의 공고 수·
# 분야 분포·마감 임박 목록·시·군·구 분포를 카탈로그에서 계산해 넣습니다. 숫자는 전부
# 카탈로그 집계값이고, 집계할 수 없는 것(선정 확률·예상 수령액)은 쓰지 않습니다.
# ---------------------------------------------------------------------------
MAX_HUB_ITEMS = 10          # 대표 공고 최대 건수
SOON_DAYS = 14              # '마감 임박' 기준(일)
REGION_HUB_PATH = "/regions/"

SIDO_SLUGS: Dict[str, str] = {
    "서울특별시": "seoul",
    "부산광역시": "busan",
    "대구광역시": "daegu",
    "인천광역시": "incheon",
    "광주광역시": "gwangju",
    "대전광역시": "daejeon",
    "울산광역시": "ulsan",
    "세종특별자치시": "sejong",
    "경기도": "gyeonggi",
    "강원특별자치도": "gangwon",
    "충청북도": "chungbuk",
    "충청남도": "chungnam",
    "전북특별자치도": "jeonbuk",
    "전라남도": "jeonnam",
    "경상북도": "gyeongbuk",
    "경상남도": "gyeongnam",
    "제주특별자치도": "jeju",
}
SLUG_TO_SIDO: Dict[str, str] = {slug: sido for sido, slug in SIDO_SLUGS.items()}

# 시·군·구 명부가 개편 전 이름으로 남아 있는 시도(명부는 2023-07 배포본 기준)
_SIGUNGU_KEY_FALLBACK: Dict[str, str] = {"전북특별자치도": "전라북도"}

# 시도별 한 줄 설명 — 행정 구조만 씁니다(금액·수급 조건은 공고마다 달라 단정하지 않습니다).
SIDO_STRUCTURE: Dict[str, str] = {
    "서울특별시": "서울은 25개 자치구가 각각 사업을 운영해, 같은 서울 안에서도 사는 구에 따라 "
                 "받을 수 있는 제도가 달라집니다.",
    "부산광역시": "부산은 16개 구·군이 각각 사업을 운영하고, 시 단위 사업도 함께 공고됩니다.",
    "대구광역시": "대구는 9개 구·군 단위 사업과 시 단위 사업이 함께 올라옵니다.",
    "인천광역시": "인천은 구와 군이 함께 있어, 군 지역 사업은 시 단위 사업과 따로 확인해야 합니다.",
    "광주광역시": "광주는 5개 자치구가 사업을 운영합니다.",
    "대전광역시": "대전은 5개 자치구가 사업을 운영합니다.",
    "울산광역시": "울산은 5개 구·군이 사업을 운영합니다.",
    "세종특별자치시": "세종은 기초자치단체가 없어 시 단위 사업이 중심입니다.",
    "경기도": "경기도는 31개 시·군이 각각 사업을 운영해, 사는 곳에 따라 받을 수 있는 제도가 "
                "크게 달라집니다.",
    "강원특별자치도": "강원은 18개 시·군이 사업을 운영합니다.",
    "충청북도": "충북은 청주시가 구 단위로 나뉘어 있어, 청주 안에서도 주소에 따라 사업이 갈립니다.",
    "충청남도": "충남은 시·군 단위 사업과 도 단위 사업이 함께 공고됩니다.",
    "전북특별자치도": "전북은 시·군 단위 사업과 도 단위 사업이 함께 공고됩니다.",
    "전라남도": "전남은 시·군 단위 사업이 많고, 도 단위 사업도 함께 올라옵니다.",
    "경상북도": "경북은 시·군 단위 사업이 많아 소관기관을 확인하는 것이 중요합니다.",
    "경상남도": "경남은 시·군 단위 사업과 도 단위 사업이 함께 공고됩니다.",
    "제주특별자치도": "제주는 제주시·서귀포시 두 곳으로 나뉘어 있습니다.",
}

SIDO_PURPOSE = (
    "이 페이지는 소관기관명이 &lsquo;{sido}&rsquo;로 확인된 지자체 공고와, 거주지와 상관없이 "
    "신청할 수 있는 전국 공통 제도를 함께 정리합니다."
)

REGION_CSS = """
.region-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}
@media (max-width:680px){.region-grid{grid-template-columns:1fr}}
.region-card{display:block;text-decoration:none;color:var(--ink);border:1px solid var(--line);
  border-radius:12px;padding:13px 15px;background:var(--surface-2)}
.region-card:hover{border-color:var(--brand);background:var(--card)}
.region-card strong{display:block;font-size:15px;letter-spacing:-.2px;color:var(--ink)}
.region-card .n{display:block;margin-top:5px;font-size:12.5px;color:var(--ink-soft)}
.region-card .n b{color:var(--ink);font-weight:700}
.stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:14px}
@media (max-width:680px){.stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.stat{background:var(--surface-2);border:1px solid var(--line);border-radius:12px;padding:11px 13px}
.stat span{display:block;font-size:11.5px;color:var(--ink-soft);font-weight:700}
.stat b{display:block;margin-top:3px;font-size:19px;letter-spacing:-.4px;color:var(--ink)}
.bars{margin:12px 0 0;display:grid;gap:8px}
.bar{display:grid;grid-template-columns:110px 1fr 60px;gap:10px;align-items:center;
  font-size:12.5px;color:var(--ink-soft)}
.bar .track2{display:block;height:9px;border-radius:999px;background:var(--surface-3);overflow:hidden}
.bar .fill{display:block;height:100%;border-radius:999px;background:var(--brand)}
.bar b{text-align:right;color:var(--ink);font-size:12.5px}
.chip-nav{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.chip-nav a{display:inline-block;font-size:12px;font-weight:700;padding:5px 10px;border-radius:999px;
  border:1px solid var(--line);color:var(--ink-soft);text-decoration:none}
.chip-nav a:hover{border-color:var(--brand);color:var(--brand-ink)}
.chip-nav a.on{background:var(--brand-soft);border-color:var(--brand);color:var(--brand-ink)}
.tbl{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
.tbl th,.tbl td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);
  color:var(--ink-soft)}
.tbl th{font-size:11.5px}
.tbl td b{color:var(--ink)}
.cta{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.cta a{display:inline-block;font-size:14px;font-weight:800;padding:12px 18px;border-radius:11px;
  background:var(--brand);color:var(--on-brand);text-decoration:none}
.cta a.ghost{background:transparent;color:var(--brand-ink);border:1px solid var(--line);font-weight:700}
.qa{margin-top:10px}
.qa h4{margin:0;font-size:14px}
.qa p{margin:4px 0 0;font-size:13px;color:var(--ink-soft)}
.qa+.qa{margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
"""


def sido_slugs() -> List[str]:
    return list(SIDO_SLUGS.values())


def slug_for_sido(sido: Optional[str]) -> Optional[str]:
    canonical = canonical_sido(sido)
    return SIDO_SLUGS.get(canonical) if canonical else None


def sido_for_slug(slug: Optional[str]) -> Optional[str]:
    return SLUG_TO_SIDO.get(str(slug or "").strip().strip("/"))


def hub_paths() -> List[str]:
    """사이트맵·llms.txt·카운터가 함께 쓰는 지역 허브 경로(18개)."""
    return [REGION_HUB_PATH] + [f"/regions/{slug}" for slug in sido_slugs()]


def _sigungu_rows(sido: str) -> List[Tuple[str, str]]:
    rows = SIGUNGU_BY_SIDO.get(sido)
    if rows is None:
        rows = SIGUNGU_BY_SIDO.get(_SIGUNGU_KEY_FALLBACK.get(sido, ""), [])
    return list(rows or [])


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _clip(value: Any, limit: int = 140) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _items_link(sido: str, track: str = "personal") -> str:
    return f"/?track={track}&sido={quote(sido, safe='')}"


def _deadline_rank(svc: Any) -> Tuple[int, int, str]:
    """마감이 가까운 순 → 기한이 없는(상시·미기재) 순."""
    deadline = getattr(svc, "deadline", {}) or {}
    days = deadline.get("days_left")
    if isinstance(days, int):
        return (0, days, svc.name)
    return (1, 0, svc.name)


def _is_soon(svc: Any) -> bool:
    days = (getattr(svc, "deadline", {}) or {}).get("days_left")
    return isinstance(days, int) and 0 <= days <= SOON_DAYS


def region_stats(catalog: Any) -> Dict[str, Dict[str, Any]]:
    """시도별 집계 — 카탈로그를 한 번만 훑어 17개 모두 계산하고 메모에 둔다.

    `SQLiteCatalog`·`Catalog` 둘 다 `services`·`memo`·`meta` 를 제공하므로 같은 코드로
    동작합니다. 계산 결과는 작은 요약(건수·분야·상위 목록)이라 프로세스 수명 동안 재사용합니다.
    """
    cached = catalog.memo.get("region_hub_stats") if hasattr(catalog, "memo") else None
    if cached is not None:
        return cached
    services = catalog.services
    national_open: List[Any] = []
    local_by_sido: Dict[str, List[Any]] = {}
    for svc in services:
        level = svc.region.get("level")
        if level == "national":
            if not svc.is_expired:
                national_open.append(svc)
            continue
        sido = svc.region.get("sido")
        if sido in SIDO_SLUGS:
            local_by_sido.setdefault(sido, []).append(svc)
    national_top = sorted(national_open, key=lambda svc: (svc.is_business, _deadline_rank(svc)))[
        :MAX_HUB_ITEMS]
    result: Dict[str, Dict[str, Any]] = {}
    for sido, slug in SIDO_SLUGS.items():
        local = local_by_sido.get(sido, [])
        open_rows = [svc for svc in local if not svc.is_expired]
        fields = Counter(svc.field_label for svc in open_rows)
        sigungu = Counter(svc.region.get("sigungu") for svc in open_rows
                          if svc.region.get("sigungu"))
        result[sido] = {
            "sido": sido,
            "slug": slug,
            "local_total": len(local),
            "local_open": len(open_rows),
            "local_closed": len(local) - len(open_rows),
            "soon": sum(1 for svc in open_rows if _is_soon(svc)),
            "fields": fields.most_common(6),
            "sigungu": sigungu.most_common(10),
            "sigungu_total": len(_sigungu_rows(sido)),
            "items": sorted(open_rows, key=lambda svc: (svc.is_business, _deadline_rank(svc)))[
                :MAX_HUB_ITEMS],
            "national_open": len(national_open),
            "national_items": national_top,
        }
    if hasattr(catalog, "memo"):
        catalog.memo["region_hub_stats"] = result
    return result


def hub_summary(catalog: Any) -> List[Dict[str, Any]]:
    """목록 페이지용 요약(건수 많은 순)."""
    stats = region_stats(catalog)
    return sorted(stats.values(), key=lambda row: (-row["local_open"], row["sido"]))


def _generated(catalog: Any) -> str:
    return str(catalog.meta.get("generated_on") or catalog.meta.get("fetched_at") or "")[:10]


def _year(catalog: Any) -> str:
    """제목 연도 — 카탈로그 기준일에서 가져오고, 없으면 오늘 연도."""
    generated = _generated(catalog)
    return generated[:4] if len(generated) >= 4 else str(date.today().year)


def _faq_pairs(sido: str, stats: Dict[str, Any], generated: str) -> List[Tuple[str, str]]:
    basis = f"{generated} 기준" if generated else "카탈로그 기준"
    return [
        (f"{sido}에서 신청할 수 있는 지원금은 몇 건인가요?",
         f"{basis}으로 {sido} 소관 공고 {stats['local_total']:,}건 중 신청기한이 지나지 않은 "
         f"{stats['local_open']:,}건이 확인되고, 여기에 전국 공통 공고 {stats['national_open']:,}건이 "
         "더해집니다. 이 가운데 내가 받을 수 있는 것은 나이·소득·가구·주소에 따라 달라집니다."),
        (f"{sido} 지자체 지원금은 어디에 신청하나요?",
         "공고마다 접수기관이 다릅니다. 아래 목록의 접수·문의와 공고 원문 링크에서 확인하고, "
         "온라인 접수는 대부분 지자체 홈페이지나 복지로·정부24에서 이뤄집니다. 이 사이트는 "
         "신청을 대행하지 않습니다."),
        (f"{sido}에 살면 전국 지원금도 받을 수 있나요?",
         "전국 단위 제도는 거주지와 상관없이 후보에 들어갑니다. 판정 화면에서 주소를 넣으면 "
         "지역 요건이 있는 제도와 없는 제도를 나눠 보여 줍니다."),
        (f"{sido} 안에서 시·군·구별로 사업이 다른가요?",
         "네. 소관기관명에 적힌 시·군·구로 구분하며, 같은 시도 안에서도 시·군·구 사업은 서로 "
         "다릅니다. 중구·서구처럼 여러 시도에 있는 이름은 임의로 찍지 않고 확인 필요로 남깁니다."),
    ]


def _index_faq(stats: Dict[str, Dict[str, Any]], generated: str) -> List[Tuple[str, str]]:
    total = sum(row["local_total"] for row in stats.values())
    basis = f"{generated} 기준" if generated else "카탈로그 기준"
    return [
        ("지역별 지원금 페이지는 무엇을 보여 주나요?",
         f"{basis}으로 시·도별 지자체 공고 수와 분야 분포, 마감이 가까운 공고, 시·군·구별 "
         "공고 수를 정리합니다. 전국 공통 제도도 함께 보여 줍니다."),
        ("우리 동네 지원금은 어디서 확인하나요?",
         "아래에서 시·도를 고르면 그 지역 공고 목록이 나옵니다. 시·군·구 단위로 좁히려면 "
         "판정 화면에서 시·도와 시·군·구를 함께 골라 주세요."),
        ("지역 공고 수는 무엇을 기준으로 세나요?",
         f"소관기관명으로 지역을 판별한 카탈로그 집계이며 {basis}입니다. 지자체 원본에 "
         "선정기준이 비어 있는 공고도 건수에는 포함하고, 화면에서는 확인 필요로 표시합니다. "
         f"현재 시·도 소관 공고는 모두 {total:,}건입니다."),
        ("지역을 잘못 판별한 공고는 어떻게 처리하나요?",
         "중구·서구·고성군처럼 여러 시도에 있는 이름은 임의로 지역을 정하지 않고 확인 필요로 "
         "남깁니다. 틀린 지역으로 걸러내는 것보다 확인이 낫기 때문입니다."),
    ]


def json_ld_blocks(title: str, description: str, canonical: str,
                   faq: List[Tuple[str, str]], crumbs: List[Tuple[str, str]],
                   generated: str) -> List[Dict[str, Any]]:
    """FAQPage + BreadcrumbList + WebPage — 검색·AI 인용용 구조화 데이터."""
    from . import static_files

    root = static_files.base_url()
    faq_block = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "url": canonical,
        "inLanguage": "ko-KR",
        "mainEntity": [
            {"@type": "Question", "name": question,
             "acceptedAnswer": {"@type": "Answer", "text": answer}}
            for question, answer in faq
        ],
    }
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": index + 1, "name": name, "item": url}
            for index, (name, url) in enumerate(crumbs)
        ],
    }
    webpage: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "url": canonical,
        "description": description,
        "inLanguage": "ko-KR",
        "isPartOf": {"@type": "WebSite", "name": "GRNT", "url": root + "/"},
        "publisher": {"@type": "Organization", "name": "GRNT", "url": root + "/"},
    }
    if generated:
        webpage["dateModified"] = generated
    blocks: List[Dict[str, Any]] = [webpage, faq_block, breadcrumb]
    return blocks


def _page(title: str, description: str, body: str, canonical_path: str,
          blocks: List[Dict[str, Any]]) -> str:
    from . import site_verification, static_files
    from .web_ui import BASE_CSS

    root = static_files.base_url()
    canonical = root + canonical_path
    scripts = "".join(
        '<script type="application/ld+json">'
        + json.dumps(block, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        + "</script>\n"
        for block in blocks
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<meta name="robots" content="index,follow">
{site_verification.meta_tags()}<meta property="og:type" content="website">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:locale" content="ko_KR">
<meta property="og:url" content="{canonical}">
<meta name="twitter:card" content="summary">
<link rel="canonical" href="{canonical}">
{scripts}
<style>{BASE_CSS}{REGION_CSS}</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <div class="brand">
    <div class="mark" aria-hidden="true">G</div>
    <div><h1>GRNT · 시·도별 지원금</h1>
    <p class="en">KOREA GRANT &amp; SUBSIDY INTELLIGENCE</p></div>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap">
    <a class="pill" href="/">내 조건으로 판정하기</a>
    <a class="pill ghost" href="/regions/">지역 전체</a>
  </div>
</header>
{body}
<p class="foot"><strong>확인 안내</strong> — 공개 데이터 기반 사전 정리이며 수급 자격을 확정하지
않습니다. 금액·기한·요건은 공고 원문으로 확인하세요. 최종 수급·선정 여부는 소관기관 심사로
결정됩니다. 입력값은 저장하지 않습니다.<br>
출처: 행정안전부 보조금24(15113968) · 창업진흥원 K-Startup(15125364) ·
중소벤처기업부 기업마당(15157820, 출처표시·변경금지)</p>
</div>
</body>
</html>
"""


def _service_row(svc: Any) -> str:
    deadline = getattr(svc, "deadline", {}) or {}
    label = deadline.get("label_ko") or svc.deadline_text or "신청기한 미기재"
    label = _clip(label, 44)
    days = deadline.get("days_left")
    soon = ("" if not isinstance(days, int) or days > SOON_DAYS
            else f' <span class="badge check_needed">D-{days}</span>' if days > 0
            else ' <span class="badge check_needed">오늘 마감</span>')
    region_label = svc.region.get("label") or ""
    if svc.region.get("level") == "national" or region_label == svc.agency:
        region_label = ""
    meta = " · ".join(part for part in (
        "창업·기업" if svc.is_business else "개인·가구",
        svc.agency or "소관기관 미기재",
        svc.field_label,
        region_label,
    ) if part)
    link = ("")
    if svc.detail_url:
        link = (f'<div class="links"><a href="{_esc(svc.detail_url)}" rel="noopener noreferrer" '
                f'target="_blank">{"공고 상세" if svc.is_business else "정부24 상세"}</a></div>')
    criteria = ("" if svc.has_criteria or svc.is_business
                else ' <span class="pill ghost">선정기준 원문 미기재 · 확인 필요</span>')
    amount = f'<p class="amount">{_esc(_clip(svc.content))}</p>' if svc.content else ""
    return (
        '<div class="result">'
        f'<div class="result-head"><div><h4>{_esc(svc.name)}</h4>'
        f'<p class="meta">{_esc(meta)}</p></div>'
        f'<span class="deadline-pill{" soon" if soon else ""}">{_esc(label)}{soon}</span></div>'
        + amount
        + f'<p class="meta">접수·문의: {_esc(_clip(svc.contact, 60)) or "미기재"}{criteria}</p>'
        + link
        + "</div>"
    )


def _faq_html(faq: List[Tuple[str, str]]) -> str:
    return "".join(
        f'<div class="qa"><h4>{_esc(question)}</h4><p>{_esc(answer)}</p></div>'
        for question, answer in faq
    )


def render_index(catalog: Any) -> str:
    stats = region_stats(catalog)
    rows = hub_summary(catalog)
    generated = _generated(catalog)
    total_local = sum(row["local_total"] for row in rows)
    total_open = sum(row["local_open"] for row in rows)
    national_open = rows[0]["national_open"] if rows else 0
    unresolved = 0
    try:
        unresolved = max(0, int(catalog.stats().get("local_services", total_local)) - total_local)
    except Exception:  # noqa: BLE001 - 통계가 없어도 페이지는 나가야 한다
        unresolved = 0
    cards = "".join(
        f'<a class="region-card" href="/regions/{row["slug"]}">'
        f'<strong>{_esc(row["sido"])} 지원금</strong>'
        f'<span class="n">지자체 공고 <b>{row["local_open"]:,}</b>건'
        f'{" · 마감 임박 " + str(row["soon"]) + "건" if row["soon"] else ""}</span></a>'
        for row in rows
    )
    faq = _index_faq(stats, generated)
    title = f"17개 시·도별 지원금 총정리 ({_year(catalog)}) | GRNT"
    description = (
        "서울·경기·인천·부산 등 17개 시·도별로 지금 신청할 수 있는 지자체 지원금과 "
        "전국 공통 지원금을 공고 수·분야·마감일 기준으로 정리했습니다."
    )
    body = f"""
<main>
  <p class="crumb"><a href="/">GRNT</a> · <span>지역별 지원금</span></p>
  <section class="card" style="margin-top:12px">
    <h2>전국 17개 시·도 지원금 모아보기</h2>
    <p class="sub">사는 지역을 고르면 그 시·도 소관 공고와 전국 공통 제도를 한 화면에서 볼 수
    있습니다. 건수·분야·마감일은 아래 카탈로그 집계를 그대로 씁니다.</p>
    <div class="stat-grid">
      <div class="stat"><span>시·도</span><b>17</b></div>
      <div class="stat"><span>지자체 공고</span><b>{total_local:,}</b></div>
      <div class="stat"><span>신청 가능</span><b>{total_open:,}</b></div>
      <div class="stat"><span>전국 공통</span><b>{national_open:,}</b></div>
    </div>
    <div class="notice" role="status">집계 기준일 {_esc(generated) or "내장 샘플"} · 마감이 지난 공고는
    빼고 셉니다. 지자체 원본에 선정기준이 비어 있는 공고는 &lsquo;확인 필요&rsquo;로 표시합니다.
    {"소관기관명만으로 시·도를 특정하지 못한 지자체 공고 " + format(unresolved, ",") + "건은 어느 시·도에도 넣지 않았습니다." if unresolved else ""}</div>
    <div class="cta">
      <a href="/">내 조건으로 바로 조회하기</a>
      <a class="ghost" href="/s/">주제별 지원금</a>
    </div>
  </section>
  <section class="card">
    <h3>시·도 선택</h3>
    <p class="sub">카드의 숫자는 신청기한이 지나지 않은 지자체 공고 수입니다.</p>
    <div class="region-grid">{cards}</div>
  </section>
  <section class="card">
    <h3>자주 묻는 질문</h3>
    {_faq_html(faq)}
  </section>
</main>
"""
    canonical = static_files_root() + REGION_HUB_PATH
    blocks = json_ld_blocks(
        title, description, canonical, faq,
        [("GRNT", static_files_root() + "/"), ("지역별 지원금", canonical)],
        generated,
    )
    return _page(title, description, body, REGION_HUB_PATH, blocks)


def static_files_root() -> str:
    from . import static_files

    return static_files.base_url()


def render_item(slug: str, catalog: Any) -> Optional[str]:
    sido = sido_for_slug(slug)
    if not sido:
        return None
    stats = region_stats(catalog).get(sido)
    if stats is None:
        return None
    generated = _generated(catalog)
    structure = SIDO_STRUCTURE.get(sido, "")
    purpose = SIDO_PURPOSE.format(sido=sido)
    fields = stats["fields"]
    top_field = fields[0][0] if fields else ""
    title = f"{sido} 지원금·보조금 총정리 ({_year(catalog)}) | GRNT"
    description = (f"{sido}에서 신청할 수 있는 지자체 지원금 {stats['local_total']:,}건과 전국 공통 "
                   f"지원금을 분야·마감일 기준으로 정리했습니다. 시·군·구별 공고 수와 마감 임박 "
                   f"공고 {stats['soon']:,}건을 함께 봅니다.")
    canonical = static_files_root() + f"/regions/{slug}"

    field_max = max((count for _label, count in fields), default=1) or 1
    bars = "".join(
        f'<div class="bar"><span>{_esc(label)}</span>'
        f'<span class="track2"><span class="fill" style="width:{max(3, round(count * 100 / field_max))}%"></span></span>'
        f'<b>{count:,}건</b></div>'
        for label, count in fields
    ) or '<p class="sub">분야를 나눌 만큼 공고가 많지 않습니다.</p>'

    rows_html = "".join(_service_row(svc) for svc in stats["items"]) or (
        '<div class="empty">이 시·도 소관으로 확인된 공고가 아직 없습니다. ' 
        '<a href="/">내 조건으로 조회</a>하면 전국 제도를 볼 수 있습니다.</div>')
    national_html = "".join(_service_row(svc) for svc in stats["national_items"][:5])

    sigungu_rows = stats["sigungu"]
    sigungu_html = "".join(
        f'<tr><td><b>{_esc(name)}</b></td><td>{count:,}건</td></tr>'
        for name, count in sigungu_rows
    )
    sigungu_block = (
        f'<table class="tbl"><thead><tr><th>시·군·구</th><th>공고</th></tr></thead>'
        f'<tbody>{sigungu_html}</tbody></table>' if sigungu_rows else
        '<p class="sub">시·군·구까지 판별된 공고가 아직 없습니다.</p>'
    )
    if sigungu_rows and stats["sigungu_total"] > len(sigungu_rows):
        sigungu_block += (
            f'<p class="meta">공고가 많은 {len(sigungu_rows)}곳만 표시합니다. 판별 단위 '
            f'{stats["sigungu_total"]}곳 중 나머지는 공고가 없거나 시·도 단위로만 올라왔습니다.</p>')

    faq = _faq_pairs(sido, stats, generated)
    others = []
    for other in sorted(region_stats(catalog).values(), key=lambda row: row["sido"]):
        active = ' class="on"' if other["sido"] == sido else ""
        others.append(
            f'<a href="/regions/{other["slug"]}"{active}>{_esc(other["sido"])}</a>'
        )
    others_html = "".join(others)

    body = f"""
<main>
  <p class="crumb"><a href="/">GRNT</a> · <a href="/regions/">지역별 지원금</a> ·
  <span>{_esc(sido)}</span></p>
  <section class="card" style="margin-top:12px">
    <h2>{_esc(sido)} 지원금·보조금</h2>
    <p class="sub">{_esc(structure)} {purpose}</p>
    <div class="stat-grid">
      <div class="stat"><span>지자체 공고</span><b>{stats['local_total']:,}</b></div>
      <div class="stat"><span>신청 가능</span><b>{stats['local_open']:,}</b></div>
      <div class="stat"><span>마감 임박({SOON_DAYS}일)</span><b>{stats['soon']:,}</b></div>
      <div class="stat"><span>전국 공통</span><b>{stats['national_open']:,}</b></div>
    </div>
    <div class="cta">
      <a href="{_esc(_items_link(sido))}">내 조건으로 {_esc(sido)} 지원금 바로 조회하기</a>
      <a class="ghost" href="{_esc(_items_link(sido, 'business'))}">창업·기업 공고로 보기</a>
    </div>
    <div class="notice" role="status">집계 기준일 {_esc(generated) or "내장 샘플"} · 마감이 지난 공고
    {stats['local_closed']:,}건은 목록에서 뺐습니다. 화면의 금액·기한은 공고 원문 값이며,
    이 페이지는 금액을 추정하거나 합산해 단정하지 않습니다.</div>
  </section>
  <section class="card">
    <h3>분야 분포</h3>
    <p class="sub">신청기한이 지나지 않은 {_esc(sido)} 소관 공고 {stats['local_open']:,}건을 분야별로
    센 값입니다{f' (가장 많은 분야: {_esc(top_field)})' if top_field else ''}.</p>
    <div class="bars">{bars}</div>
  </section>
  <section class="card">
    <h3>지금 신청할 수 있는 {_esc(sido)} 공고</h3>
    <p class="sub">개인·가구 공고를 먼저, 그 안에서 마감이 가까운 순으로 최대 {MAX_HUB_ITEMS}건 보여
    줍니다. 조건을 넣으면 내가 받을 수 있는 것만 추려 볼 수 있습니다.</p>
    {rows_html}
  </section>
  <section class="card">
    <h3>거주지와 상관없는 전국 공통 공고</h3>
    <p class="sub">전국 단위 제도 {stats['national_open']:,}건 중 개인·가구 공고를 먼저, 마감이
    가까운 순으로 5건 골랐습니다.</p>
    {national_html}
  </section>
  <section class="card">
    <h3>{_esc(sido)} 시·군·구별 공고</h3>
    <p class="sub">소관기관명으로 시·군·구까지 판별된 공고를 센 값입니다(시·도 단위 공고는 제외).</p>
    {sigungu_block}
    <div class="links"><a href="/s/{_esc(stats['slug'])}">{_esc(sido)} 주제별 모아보기</a>
    <a href="/guides/">자주 묻는 지원금 질문</a></div>
  </section>
  <section class="card">
    <h3>자주 묻는 질문</h3>
    {_faq_html(faq)}
  </section>
  <section class="card">
    <h3>다른 시·도 지원금</h3>
    <div class="chip-nav">{others_html}</div>
  </section>
</main>
"""
    blocks = json_ld_blocks(
        title, description, canonical, faq,
        [("GRNT", static_files_root() + "/"),
         ("지역별 지원금", static_files_root() + REGION_HUB_PATH),
         (f"{sido} 지원금", canonical)],
        generated,
    )
    return _page(title, description, body, f"/regions/{slug}", blocks)
