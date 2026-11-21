"""세무·노무 사무소용 **거래처 일괄(50~300곳) 익명 매칭**.

무엇을 하는가
-------------
거래처 목록 CSV(익명 코드·업종·상시근로자·연매출·업력·지역)를 한 번 올리면, 거래처마다
지금 신청할 만한 공고 3~5건을 골라 **1페이지 요약(인쇄·PDF)** 과 **CSV 요약**으로 돌려줍니다.
한 거래처씩 `business_report` 를 돌리는 것과 같은 판정 규격(같은 엔진·같은 묶음·같은
우선순위)을 쓰되, 수백 곳을 2초 안에 끝내도록 두 단으로 나눠 계산합니다.

익명 경계 — 이 모듈의 핵심
--------------------------
1. **상호·사업자번호·대표자·연락처·이메일·주민등록번호·상세주소** 열은 헤더만 확인하고
   **값을 꺼내지 않습니다**. 꺼내지 않으므로 매칭 함수로 넘어갈 값 자체가 만들어지지 않습니다.
   응답에는 어떤 열이 버려졌는지 **열 이름만** 남깁니다(값은 절대 남기지 않습니다).
2. 매칭에 들어가는 것은 `client_ref`(익명 코드)와 **조건 코드**뿐입니다 — 업종 슬러그,
   상시근로자 수, 연매출(원 또는 구간), 업력, 시도·시군구.
3. 자유 서술 열(`note`·`메모`·`비고`)은 기본으로 버립니다. `allow_labels=true` 로 명시했을
   때만 **매칭에 쓰지 않는 표시용 라벨**로 결과에 붙입니다(저장하지 않음). 붙이지 않으려면
   응답의 `client_ref` 로 사무소 파일에서 다시 이어 붙이면 됩니다(VLOOKUP 방식).
4. 서버에는 아무것도 저장하지 않습니다. 카운터에도 거래처 수·조회 횟수만 남습니다.

성능 설계
---------
300곳 × 전국 사업 공고 1.5천 건을 2초 안에 끝내기 위해 두 단으로 나눕니다.

1. **1차 필터** — `engine.structural_fail`. 지역·대상·업력·연령·성별·업종에서 **명확히
   어긋난** 공고만 걷어냅니다. `evaluate_service` 와 같은 검사 함수를 쓰므로, 여기서 걸러진
   공고는 정밀 판정에서도 `ineligible` 이 되어 리포트에 들어오지 않습니다. 즉 결과가 달라지지
   않습니다.
2. **2차 정밀 판정** — 남은 후보를 우선순위 근사 점수(묶음 적합·마감 임박·업종·지역 일치)로
   상위 `SHORTLIST`(24)건까지 줄인 뒤 `engine.evaluate_service` 로 정밀 판정합니다.
   상위 40건 밖에서 5건 안에 들 후보는 사실상 없지만, 0은 아니므로 응답에 그 사실을 적습니다.

읽는 값의 근거는 `agent_report` 와 같습니다(「소상공인기본법」 제2조·시행령 제3조,
「중소기업기본법 시행령」 별표 3). 규모 판정은 **추정**이고, 확정은 확인서로 합니다.

1.1 — 세무·노무 담당의 실제 파일에 맞춘 정교화
--------------------------------------------
사무소 파일에는 상시근로자 '수'보다 **구간**(5인 미만·10인 이상), 업종 '대분류'보다
**세부 업종**(한식·가구·소프트웨어), 그리고 **고용 이슈**(청년 채용·육아휴직 대체인력·
고령자·장애인·사회보험료)가 적혀 있는 경우가 많습니다. 1.1 은 그 세 가지와
**기업 형태**(소상공인·중소기업·법인 등)를 조건으로 받아

- 매칭 점수에 고용 이슈·세부 업종 가점을 넣고,
- 거래처마다 **탈락 사유**(지역·업력·연령·업종·기업 형태·상위 후보 밖)를 사유별로 세어
  왜 그 공고가 빠졌는지 보여 주고,
- 결과 1건마다 **판정 근거 문구**(지역 일치/업력 충족/업종 충족, 확인이 필요한 항목)를 붙입니다.

고용 이슈 문구는 '고령'(→ 고령군 같은 지역명)·'청년'(→ 청년창업센터 같은 창업 지원)처럼
혼동되는 낱말을 피하고, **고용 지원을 뜻하는 결합 표현**(청년일자리·시니어인턴십·육아휴직
대체인력 등)만 골라 잡습니다.
"""
from __future__ import annotations

import csv
import html
import io
import re
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import agent_report, engine, programs, regions
from .catalog import Catalog

SCHEMA_VERSION = "1.1"

MAX_CLIENTS = 300
MIN_CLIENTS_HINT = 50
MIN_TOP_N = 3
MAX_TOP_N = 5
DEFAULT_TOP_N = 5
SHORTLIST = 24
MAX_SCAN = 20000
MAX_LABEL_LEN = 40
MAX_NOTE_LEN = 120

DISCLAIMER_KO = (
    "본 리포트는 공개 데이터(정부24 보조금24·K-Startup·기업마당)를 이용한 참고용 사전 점검이며, "
    "수급·선정 자격을 확정하지 않습니다. 신청 전 소관기관 원문과 담당 부서에 확인하세요."
)

SCOPE_LIMITS_KO = [
    "판정은 공고의 구조화된 신청자격(업력·연령·지역·대상·성별·업종)만 근거로 합니다. "
    "공고문의 서술형 요건은 원문 확인 대상입니다.",
    "규모(소상공인·소기업) 판정은 입력값 기준 추정입니다. 확정은 소상공인시장진흥공단 "
    "소상공인 확인서·중소기업 확인서로 합니다.",
    "거래처당 상위 24건까지 정밀 판정해 3~5건을 고릅니다. 그 밖의 후보는 표시하지 않습니다.",
    "선정은 평가·경쟁·예산으로 결정됩니다. 이 서비스는 신청을 대행하지 않습니다.",
]

ANONYMITY_BADGE_KO = "상호명·사업자번호는 서버 매칭에 쓰지 않고 조건 코드만 처리합니다"

# 열 이름과 허용 값을 사람에게 그대로 보여 준다 — 사무소 파일의 열 이름이 제각각이기 때문이다.
CONDITION_GUIDE_KO: List[str] = [
    "업종: 대분류 코드(manufacturing·retail·food·ict·service·construction·logistics·agri·"
    "education·health·culture·energy·finance) 또는 한글 별칭(음식숙박·제조·도소매 등).",
    "업종키워드: 취급 품목·업태(한식, 가구, 소프트웨어, 미용 등). 알아본 낱말만 점수에 쓰고, "
    "업종이 비어 있으면 대분류를 채웁니다.",
    "직원수구간: '5인 미만'·'5~9명'·'10명 이상' 같은 구간. 상시근로자 수 열이 없을 때 씁니다.",
    "기업형태: 소상공인·중소기업·법인·개인사업자·벤처기업·사회적기업·창업기업 또는 "
    "Y/N(소상공인여부 — Y=소상공인, N=중소기업).",
    "고용이슈: 청년·고령(중장년)·육아휴직·장애인·사회보험료를 쉼표로 구분(청년, 육아휴직).",
    "설립연도: 업력 열이 없을 때 설립연도로 연차를 계산합니다(개월 단위 미반영).",
]

# --- 열 이름 ---------------------------------------------------------------
# 헤더는 공백·밑줄·하이픈을 지우고 소문자로 맞춰 비교한다(엑셀에서 그대로 저장한 머리글도 읽는다).
_KIND = {
    "client_ref": ("clientref", "ref", "id", "code", "거래처코드", "고객코드", "코드", "번호",
                   "거래처번호", "관리번호"),
    "industry": ("industry", "업종", "업태", "업종코드", "산업"),
    "employees": ("employees", "employee", "staff", "상시근로자", "상시근로자수", "근로자수",
                  "직원수", "인원", "상시직원수"),
    "revenue_krw": ("revenuekrw", "revenue", "annualrevenuekrw", "annualrevenue", "연매출",
                    "매출액", "연매출액", "매출"),
    "revenue_bracket": ("revenuebracket", "매출구간", "연매출구간", "매출액구간"),
    "business_age_years": ("businessageyears", "bizyears", "years", "업력",
                           "업력년", "업력년수", "창업후년수", "사업기간", "창업연차",
                           "업력년차", "창업년차"),
    "region": ("region", "지역", "소재지", "시도시군구", "사업장지역", "사업장소재지"),
    "sido": ("sido", "시도", "광역"),
    "sigungu": ("sigungu", "시군구", "구군"),
    "age": ("age", "대표나이", "대표자나이", "만나이"),
    "employees_bracket": ("employeesbracket", "직원수구간", "상시근로자구간", "근로자구간",
                          "인원구간", "직원수범위"),
    "entity": ("entity", "bizentity", "기업형태", "사업자형태", "기업구분", "법인구분",
               "기업유형", "규모구분", "소상공인여부", "중소기업여부", "법인여부"),
    "industry_keyword": ("industrykeyword", "업종키워드", "세부업종", "업종상세", "업종상세명",
                         "취급품목", "주요품목"),
    "employment": ("employment", "고용이슈", "인력이슈", "채용이슈", "고용상황", "노무이슈"),
    "founded_year": ("foundedyear", "설립연도", "창업연도", "개업연도"),
    "note": ("note", "notes", "비고", "메모", "라벨", "label", "참고"),
}

# 값이 아니라 **존재 여부만** 확인하고 버리는 열. 여기에 값이 들어 있어도 읽지 않는다.
SENSITIVE_KINDS = {
    "company_name": ("companyname", "상호", "상호명", "기업명", "법인명", "사업장명", "가맹점명",
                     "거래처명", "고객명", "name"),
    "biz_no": ("bizno", "businessnumber", "biznumber", "사업자번호", "사업자등록번호",
               "사업자등록증번호"),
    "representative": ("representative", "ceo", "owner", "대표", "대표자", "대표자명", "성명",
                       "이름"),
    "contact": ("contact", "phone", "tel", "mobile", "연락처", "전화", "전화번호", "휴대폰",
                "핸드폰", "담당자", "담당자명"),
    "email": ("email", "이메일", "메일"),
    "resident_no": ("residentno", "rrn", "주민등록번호", "주민번호"),
    "address": ("address", "주소", "상세주소", "도로명주소", "지번주소"),
}


def _norm_header(value: Any) -> str:
    return re.sub(r"[\s_\-\.\(\)\[\]]+", "", str(value or "")).lower()


def _kind_index(header_row: Iterable[Any]) -> Tuple[Dict[str, int], List[str], List[str]]:
    """머리글 → (쓸 열 위치, 버린 민감 열 이름, 모르는 열 이름).

    민감 열은 위치만 기억하고 **값은 이후 단계에서도 꺼내지 않는다**(`_row_values` 가
    허용된 종류의 위치만 읽는다).
    """
    allowed: Dict[str, int] = {}
    sensitive: List[str] = []
    unknown: List[str] = []
    for position, raw in enumerate(header_row):
        key = _norm_header(raw)
        if not key:
            continue
        hit = None
        for kind, names in _KIND.items():
            if key in names:
                hit = kind
                break
        if hit and hit not in allowed:
            allowed[hit] = position
            continue
        dropped = None
        for kind, names in SENSITIVE_KINDS.items():
            if key in names:
                dropped = kind
                break
        if dropped:
            sensitive.append(str(raw).strip())
        else:
            unknown.append(str(raw).strip())
    return allowed, sensitive, unknown


def _row_values(row: List[str], allowed: Dict[str, int]) -> Dict[str, str]:
    """허용된 열만 꺼낸다 — 민감 열 값은 이 함수를 통과하지 않는다."""
    out: Dict[str, str] = {}
    for kind, position in allowed.items():
        if position < len(row):
            out[kind] = str(row[position] if row[position] is not None else "").strip()
    return out


# --- 값 해석 ---------------------------------------------------------------
_KO_UNITS = {"천": 1_000, "백": 100, "십": 10, "만": 10_000, "억": 100_000_000}


def parse_money_krw(value: Any) -> Optional[int]:
    """'2억', '5천만원', '200,000,000', '1억2천만' → 원 단위 정수."""
    text = str(value or "").strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return int(float(text))
    total = 0.0
    matched = False
    for number, units in re.findall(r"(\d+(?:\.\d+)?)([천백십만억]*)", text):
        amount = float(number)
        for char in units:
            amount *= _KO_UNITS[char]
        total += amount
        matched = True
    if not matched or total <= 0:
        return None
    return int(round(total))


def parse_bracket_krw(value: Any) -> Tuple[Optional[int], str]:
    """매출 **구간**을 보수적인 상한(또는 하한) 금액으로 바꾼다.

    소상공인 기준은 '이 금액 이하'로 보므로 구간의 **상한**을 씁니다. '3억 이상'처럼 위가
    열린 구간은 하한을 쓰고 그 사실을 note 로 돌려줍니다(과대 추정을 피하려는 선택).
    """
    text = str(value or "").strip()
    if not text:
        return None, ""
    compact = text.replace("~", "-").replace("–", "-").replace("—", "-")
    compact = compact.replace("부터", "-").replace("까지", "")
    parts = [part for part in re.split(r"-", compact) if part.strip()]
    if len(parts) >= 2:
        upper = parse_money_krw(parts[-1])
        if upper:
            return upper, "구간 상한으로 판정"
    if any(word in text for word in ("이상", "초과", "over")):
        lower = parse_money_krw(re.sub(r"(이상|초과|over)", "", text))
        if lower:
            return lower, "위가 열린 구간이라 하한으로 판정"
    amount = parse_money_krw(re.sub(r"(미만|이하|under|below)", "", text))
    if amount:
        return amount, "구간 상한으로 판정"
    return None, ""


def parse_region_text(value: Any) -> Dict[str, str]:
    """'인천광역시 서구', '서울 강남구', '경기 성남시 분당구' → 표준 시도·시군구."""
    text = str(value or "").strip()
    if not text:
        return {"level": "national", "sido": "", "sigungu": "", "label": "전국"}
    parsed = regions.parse_agency_region(text)
    if parsed.get("level") in ("sido", "sigungu"):
        return {"level": parsed["level"], "sido": parsed.get("sido", ""),
                "sigungu": parsed.get("sigungu", ""), "label": parsed.get("label", "")}
    parts = text.split()
    block = regions.region_block(parts[0] if parts else "", " ".join(parts[1:]) if len(parts) > 1 else "")
    if block.get("level") in ("sido", "sigungu"):
        return {"level": block["level"], "sido": block.get("sido", ""),
                "sigungu": block.get("sigungu", ""), "label": block.get("label", "")}
    return {"level": "national", "sido": "", "sigungu": "",
            "label": f"지역 미확인({text[:20]})"}


# 업종 이름에 흔히 붙는 말 — `agent_report` 의 별칭으로 못 읽는 표기만 보완한다.
_INDUSTRY_HINTS: List[Tuple[str, str]] = [
    ("정보통신", "ict"), ("아이티", "ict"), ("소프트웨어", "ict"), ("프로그램", "ict"),
    ("음식", "food"), ("숙박", "food"), ("요식", "food"), ("제과", "food"),
    ("소매", "retail"), ("도매", "retail"), ("유통", "retail"), ("판매", "retail"),
    ("제조", "manufacturing"), ("공장", "manufacturing"), ("가공", "manufacturing"),
    ("건설", "construction"), ("시공", "construction"),
    ("운수", "logistics"), ("물류", "logistics"), ("택배", "logistics"), ("운송", "logistics"),
    ("농업", "agri"), ("어업", "agri"), ("임업", "agri"),
    ("금융", "finance"), ("보험", "finance"),
    ("교육", "education"), ("학원", "education"),
    ("의료", "health"), ("병원", "health"), ("약국", "health"), ("보건", "health"),
    ("문화", "culture"), ("예술", "culture"), ("관광", "culture"),
    ("에너지", "energy"), ("환경", "energy"),
]


def resolve_industry(value: Any) -> Optional[str]:
    """업종 입력을 표준 슬러그로 바꾼다 — `agent_report` 별칭 + 흔한 복합 표기 보완."""
    slug = agent_report.resolve_industry(value)
    if slug:
        return slug
    text = re.sub(r"[\s·ㆍ/\-_,]+", "", str(value or "")).lower()
    if not text:
        return None
    if text in ("it", "ict", "아이티"):
        return "ict"
    for word, hint in _INDUSTRY_HINTS:
        if word in text:
            return hint
    return None


def _as_int(value: Any) -> Optional[int]:
    text = str(value or "").strip().replace(",", "").replace("명", "").replace("인", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _as_float(value: Any) -> Optional[float]:
    text = str(value or "").strip().replace(",", "").replace("년", "").replace("년차", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# --- 직원 수 구간 ----------------------------------------------------------
# 사무소 파일은 정확한 인원 대신 '5인 미만'·'10~49명'처럼 구간을 적는다.
# 소상공인 요건은 '미만'이 핵심이므로, 구간의 **위쪽 값**을 써서 넘지 않게 판정하고
# '10인 이상'처럼 위가 열린 구간만 아래쪽 값을 쓰고 그 사실을 note 로 남깁니다.
def parse_employees_bracket(value: Any) -> Tuple[Optional[int], str]:
    """'5인 미만'·'5~9명'·'10명 이상' → (상시근로자 수, 판정 근거 문구)."""
    text = str(value or "").strip().replace("명", "").replace("인", "")
    if not text:
        return None, ""
    compact = re.sub(r"[\s,]", "", text)
    numbers = [int(match) for match in re.findall(r"\d+", compact)]
    if not numbers:
        return None, ""
    if any(word in compact for word in ("미만", "이하", "under", "below")):
        upper = numbers[-1]
        if "이하" in compact:
            return upper, "구간 상한(이하)으로 판정"
        return max(0, upper - 1), "구간 상한(미만)으로 판정"
    if len(numbers) >= 2:
        return numbers[-1], "구간 상한으로 판정"
    if any(word in compact for word in ("이상", "초과", "over")):
        return numbers[0], "위가 열린 구간이라 하한으로 판정"
    return numbers[0], ""


# --- 기업 형태 -------------------------------------------------------------
_ENTITY_INPUT_ALIASES: Dict[str, str] = {
    "소상공인": "small_business", "소상공인임": "small_business", "자영업": "small_business",
    "개인사업자": "sole_proprietor", "개인": "sole_proprietor",
    "중소기업": "sme", "중견기업": "sme", "일반기업": "sme",
    "법인": "corporate", "주식회사": "corporate", "법인사업자": "corporate",
    "벤처기업": "venture", "벤처": "venture", "이노비즈": "venture",
    "사회적기업": "social_enterprise", "사회적협동조합": "social_enterprise",
    "예비창업자": "pre_startup", "예비창업": "pre_startup",
    "창업기업": "startup", "스타트업": "startup", "초기창업기업": "startup",
    "y": "small_business", "yes": "small_business", "o": "small_business",
    "예": "small_business", "true": "small_business", "1": "small_business",
    "n": "sme", "no": "sme", "아니오": "sme", "false": "sme", "0": "sme",
}


def resolve_entity(value: Any) -> Optional[str]:
    """기업 형태 입력(한국어·코드·Y/N)을 엔진 코드로 바꿉니다.

    '소상공인여부' 열이 Y/N 으로만 적혀 있어도 읽습니다(Y=소상공인, N=중소기업).
    """
    text = str(value or "").strip()
    if not text:
        return None
    if text in programs.BUSINESS_ENTITIES:
        return text
    compact = re.sub(r"[\s·ㆍ\-_\(\)]+", "", text).lower()
    if not compact:
        return None
    if compact in programs.BUSINESS_ENTITIES:
        return compact
    return _ENTITY_INPUT_ALIASES.get(compact)


def _entity_for_engine(entity: Optional[str]) -> Optional[str]:
    """기업 형태를 엔진이 읽는 코드로 옮긴다 — '창업기업'은 중소기업 범주로 본다.

    엔진은 "기업 형태가 중소기업이면 창업기업 요건을 통과"로 판정하지만, 반대 방향
    (창업기업으로 입력 → 중소기업 요건)은 통과시키지 않습니다. 창업기업은 법상 중소기업의
    부분집합이므로, '창업기업'을 그대로 넘기면 중소기업 대상 공고가 통째로 빠집니다.
    표시는 '창업기업'으로 두고 판정만 중소기업으로 합니다(업력 요건은 따로 판정됩니다).
    """
    if entity == "startup":
        return "sme"
    return entity


# --- 고용 이슈 -------------------------------------------------------------
# 노무 담당이 거래처별로 아는 고용 상황. 공고 문구에서 **고용 지원을 뜻하는 결합 표현만**
# 골라 잡습니다 — '고령'만 보면 '고령군'(지역명), '청년'만 보면 '청년창업지원센터'까지 걸립니다.
EMPLOYMENT_ISSUES: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("youth", "청년 채용",
     ("청년일자리", "청년 일자리", "청년고용", "청년 고용", "청년채용", "청년 채용",
      "청년장려금", "청년 장려금", "일자리도약", "청년취업", "청년 취업")),
    ("senior", "고령·중장년", ("고령자", "시니어", "중장년", "신중년")),
    ("parental_leave", "육아휴직·대체인력", ("육아휴직", "출산휴가", "대체인력")),
    ("disabled", "장애인 고용", ("장애인 고용", "장애인고용", "장애인 의무고용", "중증장애인",
                              "장애인 근로자")),
    ("social_insurance", "사회보험료", ("두루누리", "사회보험료", "4대보험료", "고용보험료")),
]

EMPLOYMENT_LABELS_KO: Dict[str, str] = {code: label for code, label, _ in EMPLOYMENT_ISSUES}

_EMPLOYMENT_INPUT_ALIASES: Dict[str, str] = {
    "청년": "youth", "청년채용": "youth", "청년고용": "youth", "청년일자리": "youth",
    "youth": "youth",
    "고령": "senior", "고령자": "senior", "시니어": "senior", "중장년": "senior",
    "신중년": "senior", "senior": "senior", "middle_aged": "senior",
    "육아휴직": "parental_leave", "출산휴가": "parental_leave", "대체인력": "parental_leave",
    "parental_leave": "parental_leave", "leave": "parental_leave",
    "장애인": "disabled", "장애인고용": "disabled", "장애": "disabled", "disabled": "disabled",
    "사회보험": "social_insurance", "사회보험료": "social_insurance", "두루누리": "social_insurance",
    "4대보험": "social_insurance", "social_insurance": "social_insurance",
}


def _compact_text(value: Any) -> str:
    return re.sub(r"[\s·ㆍ\-_/]+", "", str(value or ""))


def employment_codes(text: Any) -> frozenset:
    """공고 문구에서 고용 이슈를 뽑는다 — 결합 표현만 인정한다.

    '고령군 2026년 고령친화산업'이나 '송파ICT청년창업지원센터'는 고용 지원 공고가 아니므로
    '고령자'·'청년일자리' 같은 결합 표현이 있어야 잡습니다.
    """
    compact = _compact_text(text)
    if not compact:
        return frozenset()
    found = set()
    for code, _label, terms in EMPLOYMENT_ISSUES:
        for term in terms:
            if _compact_text(term) in compact:
                found.add(code)
                break
    return frozenset(found)


def _norm_employment_key(value: str) -> str:
    return re.sub(r"[\s·ㆍ\-_]+", "", str(value or "")).lower()


# 별칭 키를 넣는 방식과 같은 방식으로 정규화해 둔다(코드형 'social_insurance' 도 읽게).
_EMPLOYMENT_ALIASES_NORM: Dict[str, str] = {
    _norm_employment_key(key): value for key, value in _EMPLOYMENT_INPUT_ALIASES.items()
}


def parse_employment(value: Any) -> List[str]:
    """입력 열의 고용 이슈(쉼표·슬래시 구분, 한국어/코드) → 코드 목록(중복 제거)."""
    raw = str(value or "")
    if not raw.strip():
        return []
    codes: List[str] = []
    for token in re.split(r"[,，/;|]+", raw):
        compact = _norm_employment_key(token)
        if not compact:
            continue
        code = _EMPLOYMENT_ALIASES_NORM.get(compact)
        if code and code not in codes:
            codes.append(code)
    return [code for code in EMPLOYMENT_LABELS_KO if code in codes]


# --- 업종 세부 키워드 -------------------------------------------------------
# '업종' 열이 대분류만 담을 때가 많아, 취급 품목·업태를 대분류와 함께 읽습니다.
# 알아본 낱말만 쓰고(응답에 되풀이하지 않음) 매칭 점수에 반영합니다.
INDUSTRY_KEYWORD_HINTS: List[Tuple[str, Tuple[str, ...]]] = [
    ("food", ("한식", "중식", "일식", "양식", "분식", "카페", "커피", "제과", "베이커리",
              "치킨", "호프", "주점", "급식", "도시락", "반찬", "식당", "음식점",
              "푸드트럭", "케이터링", "정육", "수산", "떡", "김치")),
    ("manufacturing", ("가구", "의류", "봉제", "섬유", "금속", "기계", "전자부품", "플라스틱",
                       "포장재", "화학", "인쇄", "정밀가공", "식품제조", "목공", "주얼리",
                       "한복", "3d프린팅", "반도체", "배터리", "철강")),
    ("ict", ("소프트웨어", "sw", "앱", "웹", "인공지능", "ai", "플랫폼", "정보보안",
             "게임", "saas", "클라우드", "데이터")),
    ("retail", ("편의점", "마트", "슈퍼", "온라인몰", "쇼핑몰", "전자상거래", "무인매장",
                "의류판매", "화장품판매", "농수산물판매", "중고거래")),
    ("service", ("미용", "헤어", "네일", "세탁", "수리", "청소", "시설관리", "부동산중개",
                 "여행사", "렌터카", "사진관", "번역", "컨설팅", "광고대행")),
    ("education", ("학원", "교습소", "에듀", "과외", "직업훈련", "온라인강의")),
    ("health", ("병원", "의원", "약국", "요양", "보건", "의료기기", "헬스장", "필라테스")),
    ("construction", ("건설", "시공", "인테리어", "전기공사", "설비", "조경", "철거", "도장")),
    ("logistics", ("물류", "택배", "운송", "화물", "창고", "배송", "퀵", "이사")),
    ("culture", ("공연", "전시", "영상", "사진", "디자인", "예술", "관광", "공예")),
    ("agri", ("농업", "축산", "원예", "과수", "스마트팜", "어업", "임업", "양봉")),
    ("energy", ("태양광", "에너지", "재활용", "환경", "탄소", "폐기물", "정수기")),
]


def resolve_industry_keywords(value: Any) -> Tuple[List[str], List[str]]:
    """취급 품목·업태 문구 → (업종 대분류 후보, 알아본 키워드).

    알아본 키워드만 돌려줍니다. 알아보지 못한 문구는 응답에 되풀이하지 않습니다
    (거래처 이름·상호가 섮여 들어오는 것을 피하려는 것).
    """
    compact = _compact_text(value).lower()
    if not compact:
        return [], []
    slugs: List[str] = []
    tokens: List[str] = []
    for slug, words in INDUSTRY_KEYWORD_HINTS:
        for word in words:
            if _compact_text(word).lower() in compact:
                if slug not in slugs:
                    slugs.append(slug)
                if word not in tokens and len(tokens) < 4:
                    tokens.append(word)
                break
    return slugs, tokens


# --- 클라이언트(거래처) 만들기 ---------------------------------------------
def _client_from_codes(client_ref: str, codes: Dict[str, str], *,
                       allow_labels: bool) -> Dict[str, Any]:
    """조건 코드만으로 거래처 1곳을 만든다. 민감 정보는 애초에 전달되지 않는다."""
    errors: List[str] = []
    notes: List[str] = []
    industry_raw = codes.get("industry", "")
    industry = resolve_industry(industry_raw) if industry_raw else None
    startup = any(word in industry_raw for word in agent_report.STARTUP_WORDS)

    keyword_slugs, industry_terms = resolve_industry_keywords(codes.get("industry_keyword"))
    if industry is None and keyword_slugs:
        # 업종 열이 비었거나 못 읽었을 때만 세부 키워드로 대분류를 채운다.
        industry = keyword_slugs[0]
        notes.append(f"업종을 세부 키워드({industry_terms[0]})로 읽어 "
                     f"{programs.INDUSTRY_LABELS.get(industry, industry)}으로 보았습니다.")
    if industry_raw and industry is None and not startup:
        errors.append(f"업종을 읽지 못했습니다({industry_raw[:12]}). 업종 코드를 확인하세요.")

    employees = _as_int(codes.get("employees"))
    employees_source = "정확값" if employees is not None else ""
    bracket_text = ""
    if employees is None and codes.get("employees_bracket"):
        employees, bracket_text = parse_employees_bracket(codes.get("employees_bracket"))
        if employees is not None:
            employees_source = "구간"
        else:
            errors.append("직원 수 구간을 읽지 못했습니다(예: 5인 미만, 10~49명).")
    if employees is not None and not (0 <= employees <= 100_000):
        employees = None
        employees_source = ""
        errors.append("상시근로자 수가 범위를 벗어나 비웠습니다.")

    revenue = parse_money_krw(codes.get("revenue_krw"))
    revenue_source = "정확값" if revenue is not None else ""
    bracket_note = ""
    if revenue is None and codes.get("revenue_bracket"):
        revenue, bracket_note = parse_bracket_krw(codes.get("revenue_bracket"))
        revenue_source = "구간" if revenue is not None else ""
        if revenue is None:
            errors.append("매출 구간을 읽지 못했습니다.")

    years = _as_float(codes.get("business_age_years"))
    years_source = "업력" if years is not None else ""
    if years is None and codes.get("founded_year"):
        founded = _as_int(codes.get("founded_year"))
        current = datetime.now().year
        if founded is not None and 1900 <= founded <= current:
            years = float(max(0, current - founded))
            years_source = "설립연도"
            notes.append(f"업력을 설립연도({founded}) 기준 연차로 계산했습니다"
                         "(개월 단위는 반영하지 않음).")
        elif founded is not None:
            errors.append("설립연도를 읽지 못해 업력을 비웠습니다.")
    if years is not None and not (0 <= years <= 60):
        years = None
        years_source = ""
        errors.append("업력이 범위를 벗어나 비웠습니다.")

    region_text = codes.get("region") or " ".join(
        part for part in (codes.get("sido"), codes.get("sigungu")) if part)
    region = parse_region_text(region_text)
    if region["level"] == "national" and region_text:
        errors.append("지역을 읽지 못해 전국 기준으로 판정했습니다(시·도 이름을 확인하세요).")

    age = _as_int(codes.get("age"))
    if age is not None and not (0 <= age <= 120):
        age = None

    entity = resolve_entity(codes.get("entity"))
    if entity and str(codes.get("entity") or "").strip().lower() in ("y", "n", "yes", "no"):
        notes.append("기업 형태 Y/N 열을 읽었습니다"
                     f"(Y=소상공인, N=중소기업 → {'소상공인' if entity == 'small_business' else '중소기업'}).")
    employment = parse_employment(codes.get("employment"))

    label = ""
    if allow_labels:
        label = str(codes.get("note") or "").strip()[:MAX_LABEL_LEN]

    return {
        "client_ref": client_ref,
        "label": label,
        "industry": industry,
        "industry_input": industry_raw if industry is None else None,
        "industry_terms": industry_terms,
        "industry_keyword_slugs": keyword_slugs,
        "startup": startup,
        "employees": employees,
        "employees_source": employees_source,
        "employees_note_ko": bracket_text,
        "revenue_krw": revenue,
        "revenue_source": revenue_source,
        "revenue_note_ko": bracket_note,
        "business_age_years": years,
        "years_source": years_source,
        "region": region,
        "age": age,
        "entity": entity,
        "employment": employment,
        "parse_errors": errors,
        "parse_notes": notes,
    }


def _report_args(client: Dict[str, Any], *, include_closed: bool, keyword: Optional[str]) -> Dict[str, Any]:
    """`agent_report` 가 읽는 인자 모양으로 바꾼다 — 단건 리포트와 같은 규격을 쓰기 위해서다."""
    declared_entity = _entity_for_engine(client.get("entity"))
    args: Dict[str, Any] = {
        "include_closed": bool(include_closed),
        "biz_status": "pre" if (client["startup"] or declared_entity == "pre_startup") else "operating",
    }
    if declared_entity:
        # 사무소가 확인서로 아는 기업 형태를 그대로 넘긴다(규모 추정보다 정확하다).
        args["biz_entity"] = declared_entity
    if client["industry"]:
        args["industry"] = client["industry"]
    elif client["startup"]:
        args["industry"] = "창업"
    if client["employees"] is not None:
        args["employees"] = client["employees"]
    if client["revenue_krw"] is not None:
        args["annual_revenue_krw"] = client["revenue_krw"]
    if client["business_age_years"] is not None:
        args["biz_years"] = client["business_age_years"]
    if client["age"] is not None:
        args["age"] = client["age"]
    if client["region"]["level"] in ("sido", "sigungu"):
        args["sido"] = client["region"]["sido"]
        if client["region"].get("sigungu"):
            args["sigungu"] = client["region"]["sigungu"]
    if keyword:
        args["keyword"] = keyword
    return args


# --- CSV / JSON 입력 -------------------------------------------------------
def parse_clients_csv(text: str, *, allow_labels: bool = False,
                      max_clients: int = MAX_CLIENTS) -> Dict[str, Any]:
    """CSV 텍스트 → 거래처 목록 + 입력 점검.

    구분자는 쉼표·탭·세미콜론을 스스로 판별합니다. 엑셀 CSV(UTF-8 BOM)도 읽습니다.
    민감 열은 **이름만** 기록하고 값은 꺼내지 않습니다.
    """
    raw = str(text or "").lstrip("\ufeff")
    if not raw.strip():
        raise ValueError("csv_required")
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(raw), dialect)
    rows = [row for row in reader if any(str(cell).strip() for cell in row)]
    if len(rows) < 2:
        raise ValueError("csv_needs_header_and_row")
    allowed, sensitive, unknown = _kind_index(rows[0])
    if "client_ref" not in allowed and not allowed:
        raise ValueError("csv_columns_unrecognized")

    clients: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for position, row in enumerate(rows[1:], start=1):
        codes = _row_values(row, allowed)
        ref = str(codes.get("client_ref") or "").strip() or f"C-{position:03d}"
        ref = re.sub(r"[^0-9A-Za-z가-힣_.\-]", "", ref)[:32] or f"C-{position:03d}"
        if ref in seen:
            seen[ref] += 1
            ref = f"{ref}-{seen[ref]}"
        else:
            seen[ref] = 1
        client = _client_from_codes(ref, codes, allow_labels=allow_labels)
        if not any(client[key] not in (None, "", False)
                   for key in ("industry", "employees", "revenue_krw", "business_age_years",
                               "entity")):
            client["parse_errors"].append(
                "조건 값이 없습니다(업종·근로자·매출·업력·기업 형태 중 하나 필요).")
        clients.append(client)
        if len(clients) > max_clients:
            raise ValueError("too_many_clients")
    return {
        "clients": clients,
        "columns_used": sorted(allowed),
        "columns_dropped_sensitive": sensitive,
        "columns_ignored": unknown,
        "rows_received": len(rows) - 1,
    }


def clients_from_mappings(items: Iterable[Dict[str, Any]], *,
                          allow_labels: bool = False,
                          max_clients: int = MAX_CLIENTS) -> Dict[str, Any]:
    """JSON 배열 입력도 같은 경계를 통과시킨다(민감 키는 값 없이 무시)."""
    clients: List[Dict[str, Any]] = []
    dropped: List[str] = []
    ignored: List[str] = []
    used: set = set()
    for position, item in enumerate(list(items), start=1):
        if not isinstance(item, dict):
            raise ValueError("clients_must_be_objects")
        codes: Dict[str, str] = {}
        for key, value in item.items():
            norm = _norm_header(key)
            hit = None
            for kind, names in _KIND.items():
                if norm in names:
                    hit = kind
                    break
            if hit:
                used.add(hit)
                if hit not in codes:
                    codes[hit] = "" if value is None else str(value)
                continue
            if any(norm in names for names in SENSITIVE_KINDS.values()):
                if str(key) not in dropped:
                    dropped.append(str(key))
            elif str(key) not in ignored:
                ignored.append(str(key))
        ref = str(codes.get("client_ref") or "").strip() or f"C-{position:03d}"
        ref = re.sub(r"[^0-9A-Za-z가-힣_.\-]", "", ref)[:32] or f"C-{position:03d}"
        client = _client_from_codes(ref, codes, allow_labels=allow_labels)
        clients.append(client)
        if len(clients) > max_clients:
            raise ValueError("too_many_clients")
    return {
        "clients": clients,
        "columns_used": sorted(used),
        "columns_dropped_sensitive": dropped,
        "columns_ignored": ignored,
        "rows_received": len(clients),
    }


# --- 매칭 ------------------------------------------------------------------
def _program_index(catalog: Catalog, *, include_closed: bool = False) -> List[Dict[str, Any]]:
    """사업 공고 색인 — 카탈로그당 한 번만 만든다(요청마다 1.5천 건을 다시 훑지 않는다).

    `include_closed` 별로 따로 캐시한다(마감 공고 포함 여부는 후보 목록 자체를 바꾼다).
    """
    key = "batch_programs_all" if include_closed else "batch_programs"
    cached = catalog.memo.get(key)
    if cached is not None:
        return cached
    if hasattr(catalog, "query_pool"):
        pool = catalog.query_pool(track=programs.TRACK_BUSINESS, business_declared=True,
                                  include_closed=include_closed, max_scan=MAX_SCAN)
    else:
        pool = catalog.by_track(programs.TRACK_BUSINESS)
    cards: List[Dict[str, Any]] = []
    for svc in pool:
        if svc.is_expired and not include_closed:
            continue
        like = {"name": svc.name, "field_label": svc.field_label, "field": svc.field,
                "support_type": svc.support_type, "track": svc.track,
                "business_summary_ko": svc.business_summary_text, "business": svc.business}
        categories = agent_report.classify_row(like)
        deadline = svc.deadline
        business = svc.business or {}
        entities = tuple(business.get("entity") or ())
        search_text = " ".join((svc.name, svc.purpose[:400], svc.target[:400],
                                str(svc.support_type or "")))
        cards.append({
            "svc": svc,
            "categories": categories,
            "primary": categories[0],
            "days_left": deadline.get("days_left"),
            "industry_required": bool(business.get("industry_required")),
            "industries": frozenset(business.get("industries") or ()),
            "level": svc.region.get("level"),
            "sido": svc.region.get("sido") or "",
            "sigungu": svc.region.get("sigungu") or "",
            "entities": entities,
            "max_years": business.get("max_years"),
            "min_age": business.get("min_age"),
            "max_age": business.get("max_age"),
            "gender": business.get("gender"),
            # 고용 이슈(청년일자리·시니어인턴십·육아휴직 대체인력…)를 색인 때 한 번만 뽑는다.
            "employment": employment_codes(search_text),
            "search_text": search_text,
        })
    catalog.memo[key] = cards
    return cards


def _entity_allows(status: Optional[str], entity: Optional[str],
                   allowed: Tuple[str, ...]) -> Optional[bool]:
    """`engine._check_business_entity` 의 합격/불합격 판단만 그대로 옴긴 것.

    None 은 '모름(불합격 아님)'입니다. 문구를 만들지 않아 수백 배 빠릅니다.
    `test_batch_client.FastScreenParityTest` 가 실제 엔진과 같은 답을 내는지 확인합니다.
    """
    if not allowed:
        return None
    if status is None:
        return None
    if status == "pre":
        return "pre_startup" in allowed
    operating = tuple(slug for slug in allowed if slug != "pre_startup")
    if not operating:
        return False
    if entity is None:
        return None
    if entity in operating:
        return True
    if "startup" in operating and entity in ("small_business", "sole_proprietor", "sme",
                                              "corporate", "venture", "social_enterprise",
                                              "startup"):
        return True
    if "sme" in operating and entity in ("small_business", "sole_proprietor"):
        return True
    if entity == "corporate" and "venture" in operating:
        return True
    return False


EXCLUSION_REGION = "region"
EXCLUSION_ENTITY = "entity"
EXCLUSION_YEARS = "years"
EXCLUSION_AGE = "age"
EXCLUSION_GENDER = "gender"
EXCLUSION_INDUSTRY = "industry"
EXCLUSION_KEYWORD = "keyword"
EXCLUSION_SHORTLIST = "shortlist"
EXCLUSION_ENGINE = "engine"
EXCLUSION_CATEGORY = "category"

EXCLUSION_LABELS_KO: Dict[str, str] = {
    EXCLUSION_REGION: "지역 불일치",
    EXCLUSION_ENTITY: "기업 형태 불일치",
    EXCLUSION_YEARS: "업력 초과",
    EXCLUSION_AGE: "연령 요건 불일치",
    EXCLUSION_GENDER: "성별 요건 불일치",
    EXCLUSION_INDUSTRY: "업종 요건 불일치",
    EXCLUSION_KEYWORD: "검색어 불일치",
    EXCLUSION_SHORTLIST: "상위 후보 밖(정밀 판정 생략)",
    EXCLUSION_ENGINE: "정밀 판정 불합격",
    EXCLUSION_CATEGORY: "관심 분야 밖",
}

EXCLUSION_ORDER: List[str] = [EXCLUSION_REGION, EXCLUSION_YEARS, EXCLUSION_AGE,
                             EXCLUSION_ENTITY, EXCLUSION_INDUSTRY, EXCLUSION_GENDER,
                             EXCLUSION_SHORTLIST, EXCLUSION_ENGINE, EXCLUSION_KEYWORD,
                             EXCLUSION_CATEGORY]


def _age_text(low: Optional[int], high: Optional[int]) -> str:
    if low is not None and high is not None:
        return f"만 {low}~{high}세"
    if low is not None:
        return f"만 {low}세 이상"
    if high is not None:
        return f"만 {high}세 이하"
    return "연령 요건"


def _requirement_text(code: str, card: Dict[str, Any]) -> str:
    """탈락 사유의 '요건'을 짧게 — 왜 빠졌는지 한 줄로 보여 주기 위해서다."""
    if code == EXCLUSION_REGION:
        return " ".join(part for part in (card.get("sido"), card.get("sigungu")) if part)
    if code == EXCLUSION_ENTITY:
        return " · ".join(dict.fromkeys(programs.ENTITY_LABELS.get(slug, slug)
                                       for slug in card.get("entities") or ()))
    if code == EXCLUSION_YEARS:
        return f"창업 {card.get('max_years')}년 이내"
    if code == EXCLUSION_AGE:
        return _age_text(card.get("min_age"), card.get("max_age"))
    if code == EXCLUSION_GENDER:
        return "여성" if card.get("gender") == "female" else "남성"
    if code == EXCLUSION_INDUSTRY:
        return " · ".join(dict.fromkeys(programs.INDUSTRY_LABELS.get(slug, slug)
                                       for slug in card.get("industries") or ()))
    return ""


def _fast_fail_reason(card: Dict[str, Any], context: Dict[str, Any]) -> Optional[str]:
    """정밀 판정 전 1차 필터 — 명확히 어긋난 공고의 **사유 코드**를 돌려준다(아니면 None).

    `engine.structural_fail` 과 같은 순서·같은 판단을 문자열 생성 없이 한다(같은 결과를
    테스트로 고정). 사유 코드를 돌려주므로 거래처마다 "무엇 때문에 빠졌는지"를 셀 수 있다.
    """
    level = card["level"]
    if level in ("sido", "sigungu") and context["region_level"] in ("sido", "sigungu"):
        if card["sido"] != context["sido"]:
            return EXCLUSION_REGION
        if level == "sigungu" and context["sigungu"] and card["sigungu"] != context["sigungu"]:
            return EXCLUSION_REGION
    entities = card["entities"]
    if entities:
        allowed = context["entity_cache"].get(entities)
        if allowed is None:
            allowed = _entity_allows(context["status"], context["entity"], entities)
            context["entity_cache"][entities] = allowed
        if allowed is False:
            return EXCLUSION_ENTITY
    max_years = card["max_years"]
    if (max_years is not None and context["status"] != "pre"
            and context["years"] is not None and context["years"] > max_years):
        return EXCLUSION_YEARS
    age = context["age"]
    if age is not None:
        if card["min_age"] is not None and age < card["min_age"]:
            return EXCLUSION_AGE
        if card["max_age"] is not None and age > card["max_age"]:
            return EXCLUSION_AGE
    gender = card["gender"]
    if gender in ("female", "male") and context["sex"] in ("female", "male"):
        if context["sex"] != gender:
            return EXCLUSION_GENDER
    if card["industry_required"] and card["industries"]:
        industry = context["industry"]
        if industry is not None and industry not in card["industries"]:
            return EXCLUSION_INDUSTRY
    return None


def _fast_fail(card: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """정밀 판정 전 1차 필터 — 명확히 어긋난 공고만 True."""
    return _fast_fail_reason(card, context) is not None


def _pre_score(card: Dict[str, Any], *, size: Dict[str, Any], industry: Optional[str],
               region: Dict[str, str], employment: frozenset = frozenset(),
               industry_terms: Tuple[str, ...] = ()) -> int:
    """`agent_report._priority` 에서 **판정 등급 항목만 뺀** 점수(정밀 판정 전 순위 근사).

    고용 이슈와 세부 업종은 판정 조건이 아니라 **순위 신호**다(공고 신청자격은 그대로 판정).
    노무사가 "청년 채용 지원"을 찾을 때 청년일자리 공고가 상위 후보로 올라오게 한다.
    """
    score = 0
    likely = size.get("small_business_likely")
    primary = card["primary"]
    if primary == agent_report.CATEGORY_SMALL_BUSINESS and likely is True:
        score += 4
    elif primary == agent_report.CATEGORY_SME and likely is False:
        score += 3
    elif primary == agent_report.CATEGORY_SME and likely is True:
        score += 1
    elif primary in (agent_report.CATEGORY_LABOR, agent_report.CATEGORY_FINANCE_TAX):
        score += 2
    days = card["days_left"]
    if days is not None:
        if 0 <= int(days) <= agent_report.D7_DAYS:
            score += 3
        elif int(days) <= 30:
            score += 1
    if industry and card["industry_required"] and industry in card["industries"]:
        score += 2
    if employment:
        hits = card.get("employment") or frozenset()
        matched = len(hits & employment)
        if matched:
            # 거래처가 "우리 고용 이슈는 이것"이라고 밝혔을 때, 그 이슈를 직접 다루는 공고를
            # 상위로 올린다. 판정(자격)은 바꾸지 않고 순위만 올린다.
            score += min(12, 8 * matched)
        if primary == agent_report.CATEGORY_LABOR:
            score += 2
    if industry_terms:
        text = card.get("search_text") or ""
        found = sum(1 for term in industry_terms if term and term in text)
        if found:
            score += min(4, 2 + (found - 1))
            if any(term and term in str(card["svc"].name) for term in industry_terms):
                score += 1
    if region.get("level") == "sigungu" and card["level"] in ("sido", "sigungu"):
        score += 1
    return score


def _shortlist(candidates: List[Tuple[int, Dict[str, Any]]], limit: int) -> List[Dict[str, Any]]:
    """점수 상위 + **묶음별 대표**를 섞어 담는다 — 한 묶음이 상위를 독차지하지 않게."""
    candidates.sort(key=lambda pair: (-pair[0], str(pair[1]["svc"].name)))
    picked: List[Dict[str, Any]] = []
    seen = set()
    for slug in agent_report.CATEGORY_ORDER:
        for score, card in candidates:
            if card["primary"] == slug and id(card) not in seen:
                picked.append(card)
                seen.add(id(card))
                break
        if len(picked) >= limit:
            return picked[:limit]
    for _score, card in candidates:
        if len(picked) >= limit:
            break
        if id(card) not in seen:
            picked.append(card)
            seen.add(id(card))
    return picked


def _select_top(rows: List[Dict[str, Any]], top_n: int, *,
               emphasis: int = 0) -> List[Dict[str, Any]]:
    """거래처에 보낼 3~5건 — 묶음별 대표를 먼저 넣고 남은 자리는 우선순위 순으로 채운다.

    `emphasis` 는 거래처가 밝힌 고용 이슈와 맞는 공고를 앞자리에 넣는 수입니다(최대 2).
    """
    picked: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        if len(picked) >= min(2, emphasis):
            break
        if id(row) in seen:
            continue
        picked.append(row)
        seen.add(id(row))
    for slug in agent_report.CATEGORY_ORDER:
        if len(picked) >= top_n:
            break
        for row in rows:
            if row["category"] == slug and id(row) not in seen:
                picked.append(row)
                seen.add(id(row))
                break
    for row in rows:
        if len(picked) >= top_n:
            break
        if id(row) not in seen:
            picked.append(row)
            seen.add(id(row))
    picked.sort(key=agent_report._sort_key)
    return picked[:top_n]


_BENEFIT_WORDS = ("지원", "지급", "보조", "이자", "최대", "한도", "감면", "보증", "바우처",
                  "훈련비", "수수료", "원)", "만원", "억원")


def _benefit_snippet(text: Any, limit: int = 110) -> str:
    """공고 본문에서 '무엇을 얼마나 주는지'에 가까운 문장 하나만 뽑는다."""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return ""
    parts = [part.strip(" -·ㆍ()") for part in re.split(r"☞|(?<=[.。!?])\s+|•", raw)]
    parts = [part for part in parts if len(part) >= 10]
    if not parts:
        return ""
    not_benefit = ("지원대상", "신청대상", "공고문 참조", "인 자", "자격", "제외대상", "신청자격")
    best, best_score = "", -99
    for part in parts:
        score = 0
        if any(word in part for word in _BENEFIT_WORDS):
            score += 2
        if any(unit in part for unit in ("원", "%", "점")):
            score += 2
        if len(part) <= 90:
            score += 1
        if part.startswith("기준") or any(word in part for word in not_benefit):
            score -= 3
        # 같은 점수면 앞 문장을 쓴다(원문 순서 유지).
        if score > best_score:
            best, best_score = part, score
    if best_score < 1:
        # 혜택 문장을 찾지 못했다 — 자격 요건 문장을 '혜택'으로 내보내지 않는다(빈칸이 정직하다).
        return ""
    if len(best) > limit:
        best = best[:limit - 1] + "…"
    return best


def _compact_match(row: Dict[str, Any], rank: int) -> Dict[str, Any]:
    amount = _benefit_snippet(row.get("amount"))
    verdict = row.get("verdict") or {}
    priority = row.get("priority") or {}
    return {
        "rank": rank,
        "service_id": row.get("service_id"),
        "name": row.get("name"),
        "agency": row.get("agency"),
        "category": row.get("category"),
        "category_label": row.get("category_label"),
        "verdict": {"code": verdict.get("code"), "label_ko": verdict.get("label_ko")},
        "support_type": row.get("support_type") or "",
        "benefit_kind": row.get("benefit_kind"),
        "benefit_summary_ko": amount,
        "deadline_date": row.get("deadline_date"),
        "deadline_text": row.get("deadline_text") or "",
        "d_day": row.get("d_day") or "",
        "days_left": row.get("days_left"),
        "closing_soon": bool(row.get("closing_soon")),
        "link": row.get("link") or "",
        "priority": {"tier": priority.get("tier"), "tier_label_ko": priority.get("tier_label_ko"),
                     "score": priority.get("score")},
        "requirements_ko": row.get("business_summary_ko") or "",
        "employment_hits_ko": [EMPLOYMENT_LABELS_KO[code]
                               for code in (row.get("employment_hits") or ())
                               if code in EMPLOYMENT_LABELS_KO],
    }


def _fit_block(row: Dict[str, Any], employment_hits: Iterable[str]) -> Dict[str, Any]:
    """거래처 조건과 공고 요건이 맞물린 **근거 문구**(엔진 판정의 why 를 그대로 옮긴다).

    판정을 새로 만들지 않습니다. 엔진이 남긴 규칙 중 지역·기업 형태·업력·업종·연령·성별처럼
    거래처 조건과 직접 맞물린 것만 추리고, 정보가 없어 판정하지 못한 항목은 '확인 필요'로
    따로 세웁니다. 300곳×5건 응답이 커지지 않도록 항목 수와 필드를 줄입니다(문장은 reasons_ko).
    """
    checks: List[Dict[str, str]] = []
    reasons: List[str] = []
    seen = set()
    missing: List[str] = []
    for rule in row.get("why") or []:
        state = rule.get("state")
        group = rule.get("group")
        if state == "pass" and group in ("region", "business", "gender"):
            required = str(rule.get("required") or "")
            if not required or required == "전국":
                continue
            key = ("pass", group, required)
            if key in seen:
                continue
            seen.add(key)
            checks.append({"state": "pass", "key": group, "required_ko": required})
            if len(reasons) < 4:
                reasons.append(str(rule.get("reason_ko") or ""))
        elif state == "unknown" and rule.get("missing_key"):
            required = str(rule.get("required") or "")
            if not required:
                continue
            key = ("unknown", rule.get("missing_key"), required)
            if key in seen:
                continue
            seen.add(key)
            checks.append({"state": "unknown", "key": str(rule.get("missing_key")),
                           "required_ko": required})
            if len(missing) < 2:
                missing.append(f"확인 필요: {required}")
    hits = [EMPLOYMENT_LABELS_KO[code] for code in employment_hits
            if code in EMPLOYMENT_LABELS_KO]
    for label in hits:
        reasons.append(f"고용 이슈 일치({label})")
    return {
        "reasons_ko": [reason for reason in reasons if reason][:5],
        "checks": checks[:3],
        "open_questions_ko": missing,
    }


def _match_one(cards: List[Dict[str, Any]], client: Dict[str, Any], *,
               top_n: int, include_closed: bool, keyword: Optional[str]) -> Dict[str, Any]:
    """거래처 1곳 매칭 — 단건 `business_report` 와 같은 판정·묶음·우선순위를 쓴다."""
    args = _report_args(client, include_closed=include_closed, keyword=keyword)
    spec = agent_report._parse_inputs(args)
    size = agent_report.size_estimate(spec["industry"], spec["employees"], spec["revenue_krw"],
                                      spec["status"] or ("pre" if spec["startup_only"] else "operating"))
    profile = agent_report._engine_profile(spec, size)
    region = profile.get("region") or {}

    business = profile.get("business") or {}
    employment = frozenset(client.get("employment") or ())
    industry_terms = tuple(client.get("industry_terms") or ())
    context = {
        "region_level": region.get("level") or "national",
        "sido": region.get("sido") or "",
        "sigungu": region.get("sigungu") or "",
        "status": business.get("status"),
        "entity": business.get("entity"),
        "years": business.get("years"),
        "industry": business.get("industry"),
        "age": profile.get("age"),
        "sex": profile.get("sex"),
        "entity_cache": {},
    }
    words = [word for word in str(keyword or "").split() if word]
    candidates: List[Tuple[int, Dict[str, Any]]] = []
    exclusions: Dict[str, int] = {}
    examples: List[Dict[str, str]] = []
    example_codes = set()
    keyword_skipped = 0
    for card in cards:
        if words and not all(word in card["search_text"] for word in words):
            keyword_skipped += 1
            continue
        reason = _fast_fail_reason(card, context)
        if reason:
            exclusions[reason] = exclusions.get(reason, 0) + 1
            if reason not in example_codes and len(examples) < 2:
                example_codes.add(reason)
                examples.append({"reason_code": reason,
                                 "reason_label_ko": EXCLUSION_LABELS_KO.get(reason, reason),
                                 "name": card["svc"].name,
                                 "requirement_ko": _requirement_text(reason, card)})
            continue
        candidates.append((_pre_score(card, size=size, industry=spec["industry"], region=region,
                                      employment=employment, industry_terms=industry_terms),
                           card))
    if keyword_skipped:
        exclusions[EXCLUSION_KEYWORD] = keyword_skipped
    shortlist = _shortlist(candidates, 1 if len(candidates) <= 1 else SHORTLIST)
    if len(candidates) > len(shortlist):
        exclusions[EXCLUSION_SHORTLIST] = len(candidates) - len(shortlist)

    rows: List[Dict[str, Any]] = []
    engine_rejected = 0
    for card in shortlist:
        row = engine.evaluate_service(card["svc"], profile)
        if (row.get("verdict") or {}).get("code") == "ineligible":
            engine_rejected += 1
            continue
        report_row = agent_report._report_row(row, size=size, industry=spec["industry"],
                                              region=region)
        # `_report_row` 는 금액을 싣지 않는다 — 일괄 리포트는 '예상 지원금·혜택' 칸이 필요하다.
        report_row["amount"] = row.get("amount") or ""
        # 판정에 쓰인 why(규칙)와 고용 이슈 일치를 근거 문구로 옮긴다.
        report_row["why"] = row.get("why") or []
        report_row["employment_hits"] = tuple(sorted(card.get("employment") & employment))
        if report_row["employment_hits"]:
            # 거래처가 밝힌 고용 이슈를 다루는 공고는 리포트 안에서도 앞에 놓는다.
            priority = report_row.get("priority") or {}
            priority["score"] = int(priority.get("score") or 0) + 6
            labels = [EMPLOYMENT_LABELS_KO[code] for code in report_row["employment_hits"]]
            reasons = priority.get("reasons_ko")
            if isinstance(reasons, list):
                reasons.append("고용 이슈 일치(" + ", ".join(labels) + ")")
        rows.append(report_row)
    if engine_rejected:
        exclusions[EXCLUSION_ENGINE] = engine_rejected
    if spec["interest"]:
        before_interest = len(rows)
        rows = [row for row in rows if row["category"] in spec["interest"]]
        if len(rows) < before_interest:
            exclusions[EXCLUSION_CATEGORY] = before_interest - len(rows)
    rows.sort(key=agent_report._sort_key)
    emphasis = sum(1 for row in rows if row.get("employment_hits"))
    picked = _select_top(rows, top_n, emphasis=emphasis)

    matches: List[Dict[str, Any]] = []
    for index, row in enumerate(picked, start=1):
        item = _compact_match(row, index)
        item["fit"] = _fit_block(row, row.get("employment_hits") or ())
        matches.append(item)

    ordered = [code for code in EXCLUSION_ORDER if exclusions.get(code)]
    exclusion_block = {
        "total": sum(exclusions.values()),
        "by_reason": [{"code": code, "label_ko": EXCLUSION_LABELS_KO[code], "count": exclusions[code]}
                      for code in ordered],
        "top_label_ko": (f"{EXCLUSION_LABELS_KO[ordered[0]]} {exclusions[ordered[0]]}건"
                         if ordered else ""),
        "examples": examples,
        "note_ko": (
            "탈락 사유는 공고의 구조화된 신청자격(지역·기업 형태·업력·연령·성별·업종)만 근거로 "
            "셉니다. 원문 서술 요건은 판정 전 단계에서 걸러지지 않습니다."
        ),
    }

    codes = {
        "industry": client["industry"] or ("pre_startup" if client["startup"] else None),
        "industry_label": (programs.INDUSTRY_LABELS.get(client["industry"] or "", "미지정")
                           if not client["startup"] else "예비창업자"),
        "industry_terms": list(industry_terms),
        "employees": client["employees"],
        "employees_source": client.get("employees_source") or "",
        "revenue_krw": client["revenue_krw"],
        "revenue_label": agent_report._krw_label(client["revenue_krw"]),
        "revenue_source": client["revenue_source"],
        "business_age_years": client["business_age_years"],
        "years_source": client.get("years_source") or "",
        "entity": client.get("entity"),
        "entity_label": programs.ENTITY_LABELS.get(client.get("entity") or "", ""),
        "employment": list(employment),
        "employment_labels_ko": [EMPLOYMENT_LABELS_KO[code] for code in EMPLOYMENT_LABELS_KO
                                 if code in employment],
        "region": {"sido": client["region"].get("sido", ""),
                   "sigungu": client["region"].get("sigungu", ""),
                   "label": client["region"].get("label", "")},
    }
    counts = {
        "candidates": len(candidates),
        "evaluated": len(shortlist),
        "shown": len(matches),
        "excluded": sum(exclusions.values()),
        "eligible_likely": sum(1 for row in matches
                               if (row["verdict"] or {}).get("code") == "eligible_likely"),
        "check_needed": sum(1 for row in matches
                            if (row["verdict"] or {}).get("code") == "check_needed"),
        "closing_soon": sum(1 for row in matches if row["closing_soon"]),
    }
    status = "matched" if matches else "no_match"
    if not candidates:
        status = "no_candidate"

    notes: List[str] = []
    if client["parse_errors"]:
        notes.extend(client["parse_errors"])
    if client.get("parse_notes"):
        notes.extend(client["parse_notes"])
    if client["employees_note_ko"]:
        notes.append(f"상시근로자는 {client['employees_note_ko']}.")
    if client["revenue_note_ko"]:
        notes.append(f"연매출 {client['revenue_note_ko']}.")
    if client.get("entity"):
        label = programs.ENTITY_LABELS.get(client["entity"], client["entity"])
        notes.append(f"기업 형태는 입력값({label})으로 판정했습니다. 확정은 확인서로 합니다.")
        if client["entity"] == "small_business" and size.get("small_business_likely") is False:
            notes.append("입력한 근로자·매출은 소상공인 기준을 넘습니다. 기업 형태를 잘못 적었는지 "
                         "확인하세요(소상공인 전용 공고는 자격 확인 필요).")
        if client["entity"] in ("sme", "corporate", "venture", "social_enterprise") \
                and size.get("small_business_likely") is True:
            notes.append("근로자·매출만 보면 소상공인 기준을 충족합니다. 소상공인 전용 공고도 "
                         "살펴보시려면 기업 형태를 비우거나 소상공인으로 다시 돌려 보세요.")
    if status == "no_match":
        notes.append("조건과 명확히 어긋나지 않는 공고가 후보에 없었습니다. 업종·지역·업력을 "
                     "확인하거나 조건 없이 단건 리포트로 다시 뽑아 보세요.")
    if status == "no_candidate":
        notes.append("업종·규모·지역 조건에서 남는 후보가 없었습니다. 입력값을 확인하세요.")
    if exclusion_block["top_label_ko"] and status != "matched":
        notes.append(f"가장 많이 빠진 사유: {exclusion_block['top_label_ko']}.")
    if employment and not any(match["employment_hits_ko"] for match in matches):
        labels = ", ".join(EMPLOYMENT_LABELS_KO[code] for code in EMPLOYMENT_LABELS_KO
                           if code in employment)
        notes.append(f"고용 이슈({labels})가 공고 문구에 드러난 후보는 추천에 들지 못했습니다. "
                     "노무 지원사업을 따로 찾으려면 keyword 에 '일자리'·'고용'을 넣어 보세요.")
    if industry_terms and any(term in (match.get("name") or "") for match in matches
                              for term in industry_terms):
        notes.append("세부 업종 키워드가 공고명에 있는 공고를 우선했습니다(판정 조건은 업종 대분류).")
    if size.get("small_business_likely") is False:
        notes.append("소상공인 기준을 넘습니다. 중소기업·소기업 지원사업 위주로 검토하세요.")
    # 규모 판정이 '일부 요건만 확인'이어도, 넘은 요건은 그대로 알린다(판정을 바꾸지는 않는다).
    for note in size.get("notes_ko") or []:
        if "넘습니다" in note and note not in notes:
            notes.append(note + " 소상공인 전용 공고는 원문에서 자격을 확인하세요.")

    return {
        "client_ref": client["client_ref"],
        "label": client["label"],
        "status": status,
        "conditions": codes,
        "size_estimate": {"status": size.get("status"),
                          "small_business_likely": size.get("small_business_likely"),
                          "summary_ko": size.get("summary_ko") or ""},
        "counts": counts,
        "exclusions": exclusion_block,
        "matches": matches,
        "notes_ko": notes,
    }


def match_clients(catalog: Catalog, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """거래처 일괄 매칭의 진입점 — CSV 텍스트 또는 JSON 배열을 받는다."""
    args = args or {}
    top_n = _as_int(args.get("top_n")) or DEFAULT_TOP_N
    top_n = max(MIN_TOP_N, min(int(top_n), MAX_TOP_N))
    allow_labels = bool(args.get("allow_labels"))
    include_closed = bool(args.get("include_closed"))
    keyword = str(args.get("keyword") or "").strip() or None

    started = time.perf_counter()
    source = "csv"
    if isinstance(args.get("clients"), list):
        parsed = clients_from_mappings(args["clients"], allow_labels=allow_labels,
                                       max_clients=MAX_CLIENTS)
        source = "json"
    elif args.get("csv"):
        parsed = parse_clients_csv(str(args["csv"]), allow_labels=allow_labels,
                                   max_clients=MAX_CLIENTS)
    else:
        raise ValueError("csv_or_clients_required")

    cards = _program_index(catalog, include_closed=include_closed)
    results = [_match_one(cards, client, top_n=top_n, include_closed=include_closed,
                          keyword=keyword)
               for client in parsed["clients"]]
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    by_verdict = {"eligible_likely": 0, "check_needed": 0}
    by_category: Dict[str, int] = {slug: 0 for slug in agent_report.CATEGORY_ORDER}
    by_exclusion: Dict[str, int] = {}
    for result in results:
        for match in result["matches"]:
            code = (match["verdict"] or {}).get("code")
            if code in by_verdict:
                by_verdict[code] += 1
            category = match.get("category")
            if category in by_category:
                by_category[category] += 1
        for row in (result.get("exclusions") or {}).get("by_reason") or []:
            by_exclusion[row["code"]] = by_exclusion.get(row["code"], 0) + int(row["count"])
    exclusion_rank = sorted(by_exclusion.items(), key=lambda pair: (-pair[1],
                                                                   EXCLUSION_ORDER.index(pair[0])
                                                                   if pair[0] in EXCLUSION_ORDER else 99))
    summary = {
        "clients": len(results),
        "matched": sum(1 for result in results if result["status"] == "matched"),
        "no_match": sum(1 for result in results if result["status"] != "matched"),
        "with_notes": sum(1 for result in results if result["notes_ko"]),
        "with_parse_errors": sum(1 for result in results
                                 if any("비웠" in note or "읽지 못" in note
                                        for note in result["notes_ko"])),
        "with_employment": sum(1 for result in results
                               if (result["conditions"] or {}).get("employment")),
        "matches": sum(len(result["matches"]) for result in results),
        "clients_with_urgent": sum(1 for result in results
                                   if any(match["closing_soon"] for match in result["matches"])),
        "by_verdict": by_verdict,
        "by_category": by_category,
        "by_exclusion": {code: count for code, count in exclusion_rank},
        "exclusion_top_ko": [f"{EXCLUSION_LABELS_KO.get(code, code)} {count:,}건"
                             for code, count in exclusion_rank[:4]],
        "elapsed_ms": elapsed_ms,
        "business_programs_scanned": len(cards),
        "top_n": top_n,
    }

    dropped = parsed["columns_dropped_sensitive"]
    anonymity = {
        "matching_inputs": ["client_ref(익명 코드)", "업종 코드", "업종 세부 키워드",
                            "상시근로자 수/구간", "연매출/구간", "업력/설립연도",
                            "시도·시군구", "기업 형태", "고용 이슈"],
        "identity_columns_dropped": dropped,
        "identity_used_in_matching": False,
        "labels_included": allow_labels,
        "stored": False,
        "note_ko": (
            ("note 열을 표시용 라벨로만 붙였습니다(매칭·저장에 쓰지 않음). "
             "상호·사업자번호 값은 읽지도 않았습니다.")
            if allow_labels else
            ("상호·사업자번호 같은 열은 헤더만 확인하고 값을 읽지 않았습니다. "
             "결과의 client_ref 로 사무소 원본 파일에서 다시 이어 붙이세요(VLOOKUP). "
             "note·메모 열은 버렸습니다.")
        ),
    }

    payload: Dict[str, Any] = {
        "summary": summary,
        "anonymity": anonymity,
        "inputs": {
            "source": source,
            "rows_received": parsed["rows_received"],
            "columns_used": parsed["columns_used"],
            "columns_dropped_sensitive": dropped,
            "columns_ignored": parsed["columns_ignored"],
            "allow_labels": allow_labels,
            "include_closed": include_closed,
            "keyword": keyword,
        },
        "condition_guide_ko": CONDITION_GUIDE_KO,
        "exclusion_legend_ko": [{"code": code, "label_ko": EXCLUSION_LABELS_KO[code]}
                                for code in EXCLUSION_ORDER],
        "clients": results,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "schema_version": SCHEMA_VERSION,
        "disclaimer_ko": DISCLAIMER_KO,
        "scope_limits_ko": SCOPE_LIMITS_KO,
        "anonymity_badge_ko": ANONYMITY_BADGE_KO,
    }
    return payload


def to_markdown(payload: Dict[str, Any], *, clients_shown: int = 8, limit: int = 3) -> str:
    """MCP·텍스트 응답용 사람이 읽는 요약(전체 JSON 앞에 붙인다)."""
    summary = payload.get("summary") or {}
    lines = [
        f"거래처 {summary.get('clients', 0)}곳 · 추천 {summary.get('matches', 0)}건 · "
        f"7일 내 마감이 있는 거래처 {summary.get('clients_with_urgent', 0)}곳 · "
        f"후보 없음 {summary.get('no_match', 0)}곳 · 처리 {summary.get('elapsed_ms', 0)}ms",
    ]
    anonymity = payload.get("anonymity") or {}
    dropped = anonymity.get("identity_columns_dropped") or []
    lines.append("매칭 입력: 익명 코드 + 업종·근로자·매출·업력·지역"
                 + (f" · 값을 읽지 않은 열: {', '.join(dropped)}" if dropped else ""))
    by_category = summary.get("by_category") or {}
    if any(by_category.values()):
        lines.append("묶음: " + " · ".join(
            f"{agent_report.CATEGORY_LABELS_KO[slug]} {count}"
            for slug, count in by_category.items()
            if count and slug in agent_report.CATEGORY_LABELS_KO))
    if summary.get("exclusion_top_ko"):
        lines.append("탈락 사유(전체): " + " · ".join(summary["exclusion_top_ko"]))
    for client in (payload.get("clients") or [])[:clients_shown]:
        conditions = client.get("conditions") or {}
        region = (conditions.get("region") or {}).get("label") or "전국"
        head = (f"[{client.get('client_ref')}] {conditions.get('industry_label') or '업종 미지정'}"
                f" · 상시 {conditions.get('employees') if conditions.get('employees') is not None else '미입력'}"
                f" · {region}")
        extras = [label for label in (conditions.get("employment_labels_ko") or [])]
        if conditions.get("entity_label"):
            extras.append(conditions["entity_label"])
        if conditions.get("industry_terms"):
            extras.append("/".join(conditions["industry_terms"][:2]))
        if extras:
            head += " · " + " · ".join(extras)
        lines.append(head)
        for match in (client.get("matches") or [])[:limit]:
            verdict = (match.get("verdict") or {}).get("label_ko") or ""
            lines.append(f"  · {match.get('d_day')} [{match.get('category_label')}] "
                         f"{match.get('name')} — {verdict}")
        if not client.get("matches"):
            reason = (client.get("exclusions") or {}).get("top_label_ko") or ""
            lines.append("  · 조건에 맞는 공고 없음" + (f" (가장 많이 빠진 사유: {reason})" if reason else ""))
    if len(payload.get("clients") or []) > clients_shown:
        lines.append(f"… 외 {len(payload['clients']) - clients_shown}곳")
    return "\n".join(lines)


# --- 내보내기 ---------------------------------------------------------------
CSV_COLUMNS: List[Tuple[str, str]] = [
    ("거래처코드", "client_ref"),
    ("업종", "industry"),
    ("업종 키워드", "industry_terms"),
    ("기업 형태", "entity"),
    ("고용 이슈", "employment"),
    ("상시근로자", "employees"),
    ("연매출", "revenue"),
    ("업력(년)", "years"),
    ("지역", "region"),
    ("순위", "rank"),
    ("공고명", "name"),
    ("소관기관", "agency"),
    ("구분", "category"),
    ("판정", "verdict"),
    ("지원유형", "support_type"),
    ("예상 지원금·혜택", "benefit"),
    ("마감일", "deadline"),
    ("D-day", "d_day"),
    ("신청 링크", "link"),
    ("판정 근거", "fit"),
    ("탈락 사유(요약)", "exclusion"),
    ("메모", "note"),
]


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def to_csv(payload: Dict[str, Any]) -> str:
    """거래처·공고 1건을 한 줄로 편 CSV(엑셀 UTF-8 BOM). 상호·사업자번호 열은 없다."""
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([
        "GRNT 거래처 일괄 매칭 · 참고용 사전 점검(선정·수급 확정 아님) · "
        + ANONYMITY_BADGE_KO
    ])
    summary = payload.get("summary") or {}
    writer.writerow([
        f"거래처 {summary.get('clients', 0)}곳 · 추천 {summary.get('matches', 0)}건 · "
        f"7일 내 마감이 있는 거래처 {summary.get('clients_with_urgent', 0)}곳 · "
        f"기준일 {(payload.get('checked_at') or '')[:10]}"
    ])
    writer.writerow([label for label, _ in CSV_COLUMNS])
    for client in payload.get("clients") or []:
        conditions = client.get("conditions") or {}
        region = (conditions.get("region") or {}).get("label") or "전국"
        exclusions = client.get("exclusions") or {}
        base = {
            "client_ref": client.get("client_ref"),
            "industry": conditions.get("industry_label") or "",
            "industry_terms": "/".join(conditions.get("industry_terms") or []),
            "entity": conditions.get("entity_label") or "",
            "employment": "/".join(conditions.get("employment_labels_ko") or []),
            "employees": ("" if conditions.get("employees") is None
                          else conditions.get("employees")),
            "revenue": conditions.get("revenue_label") or "",
            "years": ("" if conditions.get("business_age_years") is None
                      else conditions.get("business_age_years")),
            "region": region,
            "exclusion": " · ".join(f"{row['label_ko']} {row['count']}"
                                    for row in (exclusions.get("by_reason") or [])[:3]),
        }
        matches = client.get("matches") or []
        if not matches:
            row = dict(base)
            row.update({"note": (client.get("notes_ko") or ["후보 없음"])[0]})
            writer.writerow([_csv_cell(row.get(key)) for _, key in CSV_COLUMNS])
            continue
        for match in matches:
            row = dict(base)
            row.update({
                "rank": match.get("rank"),
                "name": match.get("name"),
                "agency": match.get("agency"),
                "category": match.get("category_label"),
                "verdict": (match.get("verdict") or {}).get("label_ko"),
                "support_type": match.get("support_type"),
                "benefit": match.get("benefit_summary_ko"),
                "deadline": match.get("deadline_date") or match.get("deadline_text"),
                "d_day": match.get("d_day"),
                "link": match.get("link"),
                "fit": " / ".join(((match.get("fit") or {}).get("reasons_ko") or [])[:3]),
                "note": client.get("label") or "",
            })
            writer.writerow([_csv_cell(row.get(key)) for _, key in CSV_COLUMNS])
    writer.writerow([])
    writer.writerow([payload.get("disclaimer_ko", "")])
    return buffer.getvalue()


REPORT_CSS = """
:root{--ink:#14181f;--soft:#5a6472;--line:#d7dce4;--brand:#123a8c;--warn:#8a3b00;--warn-bg:#fdf1e2}
*{box-sizing:border-box}
body{margin:0;padding:0;color:var(--ink);background:#e9ecf2;
  font-family:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;font-size:12.5px;line-height:1.5}
.client-page{background:#fff;max-width:210mm;margin:12px auto;padding:14mm 14mm 12mm;min-height:280mm;
  page-break-after:always;position:relative}
.client-page:last-child{page-break-after:auto}
h1{font-size:19px;margin:0 0 3px}
h2{font-size:13px;margin:16px 0 6px;padding-bottom:4px;border-bottom:2px solid var(--ink)}
.sub{margin:0;color:var(--soft);font-size:12px}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0 0}
.tags span{font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;
  background:#eef1f6;color:#3b4557}
.head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.tools{display:flex;gap:6px;flex-wrap:wrap}
.tools button{font:inherit;font-size:11.5px;font-weight:700;padding:6px 10px;border-radius:8px;
  border:1px solid var(--line);background:#fff;color:#3b4557;cursor:pointer}
table{width:100%;border-collapse:collapse;font-size:11.5px;margin:6px 0 0}
th,td{border:1px solid var(--line);padding:5px 6px;text-align:left;vertical-align:top}
th{background:#eef1f6;font-weight:700;white-space:nowrap;font-size:11px}
td.num{white-space:nowrap}
td.benefit{color:#3b4557;font-size:11px}
td.soon{color:var(--warn);font-weight:800;background:var(--warn-bg)}
a{color:var(--brand);text-decoration:none;word-break:break-all}
.notes{margin:12px 0 0;padding:9px 12px;border-radius:8px;background:#f6f8fc;color:#3b4557;font-size:11.5px}
.notes ul{margin:4px 0 0;padding-left:16px}
.foot{margin-top:16px;padding-top:8px;border-top:1px solid var(--line);color:var(--soft);font-size:10.5px}
.foot p{margin:3px 0}
.cover{background:#fff;max-width:210mm;margin:12px auto;padding:18mm 14mm;page-break-after:always}
.cover h1{font-size:24px}
.cover .big{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0 0}
.cover .big span{font-size:13px;font-weight:800;padding:8px 14px;border-radius:10px;
  background:#eef1f6;color:#243044}
.cover ul{margin:12px 0 0;padding-left:18px;color:#3b4557;font-size:12px;line-height:1.7}
@media print{
  body{background:#fff}
  .client-page,.cover{box-shadow:none;margin:0;max-width:none;padding:10mm 12mm;min-height:0}
  .noprint{display:none}
  tr{page-break-inside:avoid}
  body.printing-one .client-page{display:none}
  body.printing-one .client-page.one{display:block}
  body.printing-one .cover{display:none}
}
@page{size:A4;margin:10mm}
"""

REPORT_JS = """
(function(){
  function only(id){
    Array.prototype.slice.call(document.querySelectorAll('.client-page')).forEach(function(page){
      page.classList.toggle('one', page.id === id);
    });
  }
  document.addEventListener('click', function(event){
    var target = event.target;
    var saveBtn = target.closest ? target.closest('[data-save]') : null;
    if (saveBtn) {
      var section = document.getElementById(saveBtn.getAttribute('data-save'));
      if (!section) { return; }
      var style = document.querySelector('style');
      var css = style ? style.textContent : '';
      var html = '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        + '<meta name="viewport" content="width=device-width,initial-scale=1">'
        + '<title>' + (section.querySelector('h1') ? section.querySelector('h1').textContent : '리포트')
        + '</title><style>' + css + '</style></head><body>' + section.outerHTML + '</body></html>';
      var url = URL.createObjectURL(new Blob([html], {type: 'text/html'}));
      var anchor = document.createElement('a');
      anchor.href = url; anchor.download = saveBtn.getAttribute('data-save') + '.html';
      document.body.appendChild(anchor); anchor.click(); document.body.removeChild(anchor);
      setTimeout(function(){ URL.revokeObjectURL(url); }, 10000);
      return;
    }
    var printBtn = target.closest ? target.closest('[data-print]') : null;
    if (printBtn) {
      only(printBtn.getAttribute('data-print'));
      document.body.classList.add('printing-one');
      window.print();
      return;
    }
    var copyBtn = target.closest ? target.closest('[data-copy]') : null;
    if (copyBtn) {
      var page = document.getElementById(copyBtn.getAttribute('data-copy'));
      var text = page ? page.innerText : '';
      if (navigator.clipboard) { navigator.clipboard.writeText(text); copyBtn.textContent = '복사됨'; }
    }
  });
  window.addEventListener('afterprint', function(){
    document.body.classList.remove('printing-one');
    Array.prototype.slice.call(document.querySelectorAll('.client-page')).forEach(function(page){
      page.classList.remove('one');
    });
  });
  if (window.location.hash === '#print') { window.print(); }
})();
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _page_id(client_ref: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z가-힣_.\-]", "-", str(client_ref or "client"))
    return f"client-{safe}"


def _client_page(client: Dict[str, Any], index: int) -> str:
    conditions = client.get("conditions") or {}
    region = (conditions.get("region") or {}).get("label") or "전국"
    employees = conditions.get("employees")
    years = conditions.get("business_age_years")
    tags = [
        conditions.get("industry_label") or "업종 미지정",
        f"상시 {employees}명" if employees is not None else "상시 미입력",
        f"연매출 {conditions.get('revenue_label') or '미입력'}",
        f"업력 {f'{years:g}년' if isinstance(years, (int, float)) else '미입력'}",
        region,
    ]
    if conditions.get("entity_label"):
        tags.append(conditions["entity_label"])
    for label in conditions.get("employment_labels_ko") or []:
        tags.append(f"고용: {label}")
    if conditions.get("industry_terms"):
        tags.append("업종 키워드: " + "/".join(conditions["industry_terms"][:2]))
    title = client.get("client_ref") or f"C-{index:03d}"
    label = client.get("label") or ""
    head = [
        '<section class="client-page" id="', _esc(_page_id(title)), '">',
        '<div class="head"><div>',
        f'<h1>{_esc(title)}',
    ]
    if label:
        head.append(f' <span class="sub">· {_esc(label)}</span>')
    head.append("</h1>")
    size = client.get("size_estimate") or {}
    head.append(f'<p class="sub">{_esc(size.get("summary_ko") or "")}</p>')
    head.append('<div class="tags">' + "".join(f"<span>{_esc(tag)}</span>" for tag in tags) + "</div>")
    head.append("</div><div class=\"tools noprint\">")
    head.append(f'<button type="button" data-copy="{_esc(_page_id(title))}">요약 복사</button>')
    head.append(f'<button type="button" data-print="{_esc(_page_id(title))}">이 장만 인쇄</button>')
    head.append(f'<button type="button" data-save="{_esc(_page_id(title))}">이 장 HTML 저장</button>')
    head.append("</div></div>")

    matches = client.get("matches") or []
    if matches:
        head.append("<h2>지금 신청할 만한 공고</h2>")
        head.append('<table><thead><tr><th>순위</th><th>공고명 · 혜택</th><th>구분</th>'
                    "<th>판정</th><th>마감</th><th>신청</th></tr></thead><tbody>")
        for match in matches:
            verdict = (match.get("verdict") or {}).get("label_ko") or ""
            deadline = match.get("deadline_date") or match.get("deadline_text") or "미기재"
            dday = match.get("d_day") or ""
            soon = " soon" if match.get("closing_soon") else ""
            link = match.get("link") or ""
            link_cell = (f'<a href="{_esc(link)}" target="_blank" rel="noopener noreferrer">신청</a>'
                         if link else "—")
            benefit = match.get("benefit_summary_ko") or match.get("requirements_ko") or ""
            fit = match.get("fit") or {}
            fit_lines = [reason for reason in (fit.get("reasons_ko") or [])[:3]
                         if reason and reason not in (benefit or "")]
            fit_lines += (fit.get("open_questions_ko") or [])[:1]
            fits = (f'<div class="benefit">근거: {", ".join(_esc(line) for line in fit_lines)}</div>'
                    if fit_lines else "")
            head.append(
                "<tr>"
                f'<td class="num">{_esc(match.get("rank"))}</td>'
                f'<td><strong>{_esc(match.get("name"))}</strong><br>'
                f'<span class="sub">{_esc(match.get("agency"))}</span>'
                + (f'<div class="benefit">{_esc(benefit)}</div>' if benefit else "")
                + fits
                + "</td>"
                f'<td class="num">{_esc(match.get("category_label"))}</td>'
                f'<td class="num">{_esc(verdict)}</td>'
                f'<td class="num{soon}">{_esc(deadline)}<br><strong>{_esc(dday)}</strong></td>'
                f"<td>{link_cell}</td>"
                "</tr>"
            )
        head.append("</tbody></table>")
    else:
        head.append('<p class="sub">조건에 맞는 공고가 나오지 않았습니다. 업종·지역·업력을 확인해 '
                    "다시 뽑아 보세요.</p>")

    notes = client.get("notes_ko") or []
    if notes:
        head.append('<div class="notes"><strong>확인할 점</strong><ul>'
                    + "".join(f"<li>{_esc(note)}</li>" for note in notes) + "</ul></div>")

    exclusions = client.get("exclusions") or {}
    reasons = exclusions.get("by_reason") or []
    if reasons:
        head.append('<div class="notes"><strong>탈락 사유(왜 다른 공고는 빠졌나)</strong><ul>'
                    + "".join(f"<li>{_esc(row['label_ko'])} {_esc(row['count'])}건</li>"
                              for row in reasons[:5])
                    + "</ul></div>")
    examples = exclusions.get("examples") or []
    if examples:
        head.append('<p class="sub">빠진 예: '
                    + " · ".join(f"{_esc(row.get('name'))}({_esc(row.get('requirement_ko'))})"
                                for row in examples[:3]) + "</p>")

    head.append('<div class="foot">')
    head.append(f"<p>{_esc(DISCLAIMER_KO)}</p>")
    head.append(f"<p>{_esc(ANONYMITY_BADGE_KO)} · 개인 식별 정보는 매칭에 쓰지 않았습니다.</p>")
    head.append("</div></section>")
    return "".join(head)


def to_report_html(payload: Dict[str, Any], *, title: str = "거래처별 지원금 요약") -> str:
    """거래처별 1페이지 요약 — 브라우저 인쇄/PDF 저장용(외부 자원 없음, 값은 전부 escape)."""
    summary = payload.get("summary") or {}
    anonymity = payload.get("anonymity") or {}
    clients = payload.get("clients") or []
    parts: List[str] = [
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{_esc(title)}</title><style>{REPORT_CSS}</style></head><body>",
        '<section class="cover"><h1>거래처 지원금 일괄 점검</h1>',
        f'<p class="sub">기준일 {_esc((payload.get("checked_at") or "")[:10])} · '
        f'거래처 {_esc(summary.get("clients", 0))}곳 · 추천 공고 '
        f'{_esc(summary.get("matches", 0))}건</p>',
        '<div class="big">',
        f'<span>7일 내 마감 포함 {_esc(summary.get("clients_with_urgent", 0))}곳</span>',
        f'<span>받을 가능성 높음 {_esc((summary.get("by_verdict") or {}).get("eligible_likely", 0))}건</span>',
        f'<span>조건 확인 필요 {_esc((summary.get("by_verdict") or {}).get("check_needed", 0))}건</span>',
        f'<span>처리 {_esc(summary.get("elapsed_ms", 0))}ms</span>',
        "</div>",
        "<ul>",
        f"<li>{_esc(ANONYMITY_BADGE_KO)}. 응답은 익명 코드 <code>client_ref</code> 기준입니다.</li>",
    ]
    dropped = anonymity.get("identity_columns_dropped") or []
    if dropped:
        parts.append("<li>값을 읽지 않고 버린 열: "
                     + _esc(", ".join(dropped)) + " (열 이름만 기록)</li>")
    for limit in payload.get("scope_limits_ko") or []:
        parts.append(f"<li>{_esc(limit)}</li>")
    parts.append("</ul>")
    by_category = summary.get("by_category") or {}
    if any(by_category.values()):
        parts.append('<div class="big">'
                     + "".join(f'<span>{_esc(agent_report.CATEGORY_LABELS_KO.get(slug, slug))} '
                               f'{_esc(count)}건</span>'
                               for slug, count in by_category.items() if count)
                     + "</div>")
    if summary.get("exclusion_top_ko"):
        parts.append("<h2>탈락 사유 상위</h2><ul>"
                     + "".join(f"<li>{_esc(item)}</li>" for item in summary["exclusion_top_ko"][:4])
                     + "</ul>")
    parts.append("<h2>조건 열 읽는 법</h2><ul>"
                 + "".join(f"<li>{_esc(item)}</li>" for item in CONDITION_GUIDE_KO)
                 + "</ul>")
    parts.append(f'<div class="foot"><p>{_esc(payload.get("disclaimer_ko") or DISCLAIMER_KO)}</p></div>')
    parts.append("</section>")
    for index, client in enumerate(clients, start=1):
        parts.append(_client_page(client, index))
    parts.append(f"<script>{REPORT_JS}</script></body></html>")
    return "".join(parts)


def filename_for(payload: Dict[str, Any], suffix: str) -> str:
    """파일명에 상호·대표자를 넣지 않는다(날짜·건수만).

    1페이지 요약은 정해진 이름(`batch-client-reports.html`)을 쓴다 — 사무소에서 같은 이름으로
    다시 받아 덮어쓰기 쉽고, 인쇄·PDF 저장 결과물 이름도 예측 가능하다.
    """
    if suffix == "html":
        return "batch-client-reports.html"
    stamp = (payload.get("checked_at") or "")[:10].replace("-", "") or "batch"
    count = len(payload.get("clients") or [])
    return f"grnt-batch-{count}-{stamp}.{suffix}"


SAMPLE_CSV_ROWS: List[Dict[str, str]] = [
    {"client_ref": "C-001", "company_name": "예시상호A", "biz_no": "000-00-00000",
     "industry": "음식숙박", "industry_keyword": "한식", "employment": "",
     "entity": "소상공인", "employees": "3", "revenue_bracket": "1억~2억",
     "business_age_years": "4", "region": "인천광역시 서구", "note": "음식점"},
    {"client_ref": "C-002", "company_name": "예시상호B", "biz_no": "000-00-00001",
     "industry": "제조", "industry_keyword": "전자부품", "employment": "청년",
     "entity": "", "employees": "8", "revenue_bracket": "30억~50억",
     "business_age_years": "9", "region": "경기도 화성시", "note": "부품 제조"},
    {"client_ref": "C-003", "company_name": "예시상호C", "biz_no": "000-00-00002",
     "industry": "IT·정보통신", "industry_keyword": "소프트웨어", "employment": "청년, 육아휴직",
     "entity": "", "employees": "5", "revenue_krw": "350000000",
     "revenue_bracket": "", "business_age_years": "3", "region": "서울특별시 마포구",
     "note": "소프트웨어"},
    {"client_ref": "C-004", "company_name": "예시상호D", "biz_no": "000-00-00003",
     "industry": "도소매", "industry_keyword": "온라인몰", "employment": "",
     "entity": "소상공인", "employees": "2", "revenue_bracket": "5천만원 미만",
     "business_age_years": "1", "region": "부산광역시 해운대구", "note": "온라인 판매"},
    {"client_ref": "C-005", "company_name": "예시상호E", "biz_no": "000-00-00004",
     "industry": "서비스", "industry_keyword": "시설관리", "employment": "고령",
     "entity": "", "employees": "12", "revenue_bracket": "3억 이상",
     "business_age_years": "12", "region": "대구광역시 수성구", "note": "시설관리"},
]

SAMPLE_CSV_COLUMNS = ["client_ref", "company_name", "biz_no", "industry", "industry_keyword",
                      "employment", "entity", "employees", "revenue_krw", "revenue_bracket",
                      "business_age_years", "region", "note"]


def sample_csv(rows: Optional[List[Dict[str, str]]] = None) -> str:
    """샘플 CSV — 상호·사업자번호 열이 **있어도 버려진다**는 점을 그대로 보여 준다.

    값은 전부 '예시상호A'·'000-00-00000' 같은 자리표시자입니다.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(SAMPLE_CSV_COLUMNS)
    for row in rows or SAMPLE_CSV_ROWS:
        writer.writerow([row.get(column, "") for column in SAMPLE_CSV_COLUMNS])
    return buffer.getvalue()


def sample_batch(n: int = MAX_CLIENTS) -> str:
    """성능·부하 시험용 합성 목록(무작위 없이 규칙적으로 만든다 — 결과가 매번 같다)."""
    industries = ["food", "retail", "service", "manufacturing", "ict", "construction",
                  "logistics", "education", "health", "culture"]
    regions_pool = ["인천광역시 서구", "서울특별시 마포구", "경기도 수원시", "부산광역시 해운대구",
                    "대구광역시 수성구", "광주광역시 북구", "대전광역시 유성구"]
    rows: List[Dict[str, str]] = []
    for index in range(1, n + 1):
        industry = industries[index % len(industries)]
        rows.append({
            "client_ref": f"C-{index:03d}",
            "industry": industry,
            "employees": str(index % 14),
            "revenue_bracket": ["5천만원 미만", "1억~3억", "3억~10억", "10억 이상"][index % 4],
            "business_age_years": str(index % 15),
            "region": regions_pool[index % len(regions_pool)],
            "note": "",
        })
    return sample_csv(rows)
