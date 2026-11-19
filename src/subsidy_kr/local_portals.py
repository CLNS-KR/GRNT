"""지자체 자체 복지포털 커넥터 (전국 17개 시·도 지역사회서비스포털 · 부평복지ON · 인천 · 서울 · 경기민원24 · 세종).

정부24 보조금24(15113968)에 올라오지 않는 광역·기초 지자체 자체 복지·행사 공고를
수집·보강합니다. 표준 라이브러리(urllib·re·html·concurrent.futures)만 사용합니다.
"""
from __future__ import annotations

import concurrent.futures
import html
import math
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from . import deadlines, programs, regions

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Connection": "close",
}

BOKJION_BASE = "https://www.icbp.go.kr"
BOKJION_LIST_URL = BOKJION_BASE + "/bokjion/program/programInfoList.do?pgno={page}"
INCHEON_BENEFIT_URL = "https://www.incheon.go.kr/icbenefit/ICB040401"
INCHEON_1IN_URL = "https://www.incheon.go.kr/1in/OHH020107"
SEOUL_WIS_URL = "https://wis.seoul.go.kr/main.do"
GG24_BASE = "https://gg24.gg.go.kr"
GG24_LIST_URL = GG24_BASE + "/svcreqst/selectPageListSvcReqst.do?pageIndex={page}"
SEJONG_SUBSIDY_URL = "https://www.sejong.go.kr/prog/bokjiro24/sejong/people/citizen/sub03_1204/extonline/list.do"
BROSO_URL_TMPL = "https://www.broso.or.kr/{slug}/hp/svc/SelectServiceSeach.do"

BROSO_REGIONS: List[Tuple[str, str]] = [
    ("seoul", "서울특별시"),
    ("busan", "부산광역시"),
    ("daegu", "대구광역시"),
    ("incheon", "인천광역시"),
    ("gwangju", "광주광역시"),
    ("daejeon", "대전광역시"),
    ("ulsan", "울산광역시"),
    ("sejong", "세종특별자치시"),
    ("gyeonggi", "경기도"),
    ("gangwon", "강원특별자치도"),
    ("chungbuk", "충청북도"),
    ("chungnam", "충청남도"),
    ("jeonbuk", "전북특별자치도"),
    ("jeonnam", "전라남도"),
    ("gyeongbuk", "경상북도"),
    ("gyeongnam", "경상남도"),
    ("jeju", "제주특별자치도"),
]

_TAG_RE = re.compile(r"<[^>]+>")

# 부평복지ON 패턴
_BOKJION_ITEM_RE = re.compile(
    r'<li>\s*<a\s+href="(/bokjion/program/programInfoDetail\.do\?prgm_seq=(\d+)[^"]*)">(.*?)</a>\s*</li>',
    re.S,
)
_TIT_RE = re.compile(r'<p\s+class="tit">(.*?)</p>', re.S)
_WRITER_RE = re.compile(r'<p\s+class="writer">(.*?)</p>', re.S)
_DATE_RE = re.compile(r'<p\s+class="date">(.*?)</p>', re.S)

# 인천 맞춤형수혜서비스 패턴 (설명 안 따옴표·개행에도 안전하게 item 블록 단위 파싱)
_IC_BLOCK_RE = re.compile(
    r'fn_saveMywish\([^)]*?,\s*\'(\d+)\',\s*\'benefit\'\s*,(.*?)\);\s*\">.*?<strong\s+class="icbenefit-item-title">(.*?)</strong>\s*<p\s+class="icbenefit-item-desc">(.*?)</p>(.*?)</div>\s*</a>',
    re.S,
)

# 인천 1인가구 포털 패턴
_IC1_ROW_RE = re.compile(
    r"<tr>\s*<td[^>]*>\s*(\d+)\s*</td>\s*(?:<!--.*?-->\s*)*"
    r"<td[^>]*>(.*?)</td>\s*"
    r"<td[^>]*id=\"searchFrstRgstDt\d*\"[^>]*>.*?f_searchPopup\('([^']*)'[^>]*>(.*?)</a>.*?</td>\s*"
    r"<td[^>]*>(.*?)</td>",
    re.S,
)

# 서울복지포털 패턴
_SEOUL_ITEM_RE = re.compile(
    r'onclick="detailOpen\(\'(\d+)\'\);"[^>]*>\s*'
    r'<p\s+class="tg">\s*<span>(.*?)</span>\s*</p>\s*'
    r'<dl>\s*<dt>(.*?)</dt>\s*<dd><p>(.*?)</p></dd>\s*</dl>',
    re.S,
)

# 연동 완료된 지자체 포털 커버리지: (시도, 시군구 또는 ""=시도전체)
SUPPORTED_PORTAL_REGIONS: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("서울특별시", ""): {
        "name": "서울복지포털 · 서울 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "서울복지포털 및 서울 자치구 지역사회서비스가 연동되어 있습니다.",
    },
    ("부산광역시", ""): {
        "name": "부산 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "부산광역시 및 구·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("대구광역시", ""): {
        "name": "대구 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "대구광역시 및 구·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("인천광역시", ""): {
        "name": "인천광역시 맞춤형수혜서비스 · 인천 1인가구 · 인천 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "인천광역시 자체 복지·혜택, 1인가구 지원사업 및 지역사회서비스가 연동되어 있습니다.",
    },
    ("인천광역시", "부평구"): {
        "name": "부평복지ON (부평구 자체 복지포털)",
        "scope": "sigungu",
        "note_ko": "부평복지ON 자체 복지·행사 공고까지 연동되어 있습니다.",
    },
    ("광주광역시", ""): {
        "name": "광주 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "광주광역시 지역사회서비스가 연동되어 있습니다.",
    },
    ("대전광역시", ""): {
        "name": "대전 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "대전광역시 및 자치구 지역사회서비스가 연동되어 있습니다.",
    },
    ("울산광역시", ""): {
        "name": "울산 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "울산광역시 및 구·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("세종특별자치시", ""): {
        "name": "세종시 보조금 찾기 · 세종 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "세종시 자체 보조금 및 지역사회서비스가 연동되어 있습니다.",
    },
    ("경기도", ""): {
        "name": "경기민원24 · 경기 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "경기도 직접 지원사업(경기민원24) 및 31개 시·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("강원특별자치도", ""): {
        "name": "강원 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "강원특별자치도 및 시·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("충청북도", ""): {
        "name": "충북 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "충청북도 및 시·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("충청남도", ""): {
        "name": "충남 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "충청남도 및 시·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("전북특별자치도", ""): {
        "name": "전북 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "전북특별자치도 및 시·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("전라남도", ""): {
        "name": "전남 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "전라남도 및 시·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("경상북도", ""): {
        "name": "경북 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "경상북도 및 시·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("경상남도", ""): {
        "name": "경남 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "경상남도 및 시·군 지역사회서비스가 연동되어 있습니다.",
    },
    ("제주특별자치도", ""): {
        "name": "제주 지역사회서비스포털",
        "scope": "sido",
        "note_ko": "제주특별자치도 지역사회서비스가 연동되어 있습니다.",
    },
}


def _clean(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_html(url: str, timeout: float = 8.0,
                data: Optional[bytes] = None, retries: int = 2) -> str:
    last_err: Optional[Exception] = None
    for _ in range(max(1, retries + 1)):
        try:
            req = urllib.request.Request(url, data=data, headers=DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "ignore")
        except (ssl.SSLError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
    if last_err:
        raise last_err
    return ""


# ---------------------------------------------------------------------------
# 1. 인천 부평구: 부평복지ON
# ---------------------------------------------------------------------------
def parse_bokjion_list_html(body: str, *, today: Optional[date] = None,
                            include_expired: bool = False) -> List[Dict[str, Any]]:
    now = today or datetime.now().date()
    records: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for href, seq, block in _BOKJION_ITEM_RE.findall(body):
        if seq in seen:
            continue
        seen.add(seq)
        tit_m = _TIT_RE.search(block)
        if not tit_m:
            continue
        title = _clean(tit_m.group(1))
        if not title:
            continue
        writer_m = _WRITER_RE.search(block)
        writer_text = _clean(writer_m.group(1)) if writer_m else ""
        date_m = _DATE_RE.search(block)
        date_raw = _clean(date_m.group(1)) if date_m else ""
        deadline_text = re.sub(r"^신청기간\s*:\s*", "", date_raw).strip() or "수시"

        parsed_dl = deadlines.parse_deadline(deadline_text, today=now, title=title)
        if not include_expired and parsed_dl.get("expired"):
            continue

        detail_url = BOKJION_BASE + html.unescape(href)
        records.append({
            "서비스ID": f"BOKJION-{seq}",
            "서비스명": title,
            "서비스목적요약": f"인천광역시 부평구 부평복지ON 자체 등록 복지·행사 공고 ({writer_text or '부평구'})",
            "소관기관명": "인천광역시 부평구 (부평복지ON)",
            "소관기관코드": "BOKJION-ICBP",
            "소관기관유형": "지자체 복지포털",
            "서비스분야": "생활지원",
            "사용자구분": "개인",
            "지원대상": writer_text or "부평구 주민",
            "선정기준": "부평복지ON 자체 공고로, 세부 자격과 신청 방법은 원문 페이지에서 확인하세요.",
            "지원내용": title,
            "지원유형": "지자체 자체 공고",
            "신청방법": "부평복지ON 상세 페이지 안내 참조",
            "신청기한": deadline_text,
            "접수기관": "인천광역시 부평구청 / 부평복지ON",
            "전화문의": "032-504-2114",
            "상세조회URL": detail_url,
            "온라인신청사이트URL": detail_url,
            "구비서류": "",
            "수정일시": now.isoformat(),
            "conditions": {},
            "source": "local_portal",
            "track": programs.TRACK_PERSONAL,
        })
    return records


def fetch_bupyeong_bokjion(*, max_pages: int = 5, today: Optional[date] = None,
                           include_expired: bool = False,
                           timeout: float = 6.0) -> List[Dict[str, Any]]:
    all_records: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for page in range(1, max(1, max_pages) + 1):
        try:
            body = _fetch_html(BOKJION_LIST_URL.format(page=page), timeout=timeout)
        except (urllib.error.URLError, TimeoutError, OSError):
            break
        for row in parse_bokjion_list_html(body, today=today, include_expired=include_expired):
            if row["서비스ID"] not in seen_ids:
                seen_ids.add(row["서비스ID"])
                all_records.append(row)
    return all_records


# ---------------------------------------------------------------------------
# 2. 인천광역시: 맞춤형수혜서비스 (ICB040401)
# ---------------------------------------------------------------------------
def parse_incheon_benefit_html(body: str, *, today: Optional[date] = None,
                               include_expired: bool = False) -> List[Dict[str, Any]]:
    now = today or datetime.now().date()
    # 보조금24 섹션 이전("인천광역시 혜택·지원"만) 또는 전체에서 중복 제거
    marker = "보조금24 혜택·지원"
    section = body.split(marker, 1)[0] if marker in body else body

    records: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for srvc_id, _args, title_raw, desc_raw, foot_raw in _IC_BLOCK_RE.findall(section):
        if srvc_id in seen:
            continue
        seen.add(srvc_id)
        name = _clean(title_raw)
        if not name:
            continue
        m_period = re.search(r"사업기간\s*</span>\s*([^<]+)", foot_raw) or re.search(r"사업기간(.*?)(?:</li>|운영기관)", foot_raw, re.S)
        deadline_text = _clean(m_period.group(1)) if m_period else "상시"
        if not deadline_text:
            deadline_text = "상시"
        m_org = re.search(r"운영기관\s*</span>\s*([^<]+)", foot_raw) or re.search(r"운영기관(.*?)</li>", foot_raw, re.S)
        contact = _clean(m_org.group(1)) if m_org else ""
        parsed_dl = deadlines.parse_deadline(deadline_text, today=now, title=name)
        if not include_expired and parsed_dl.get("expired"):
            continue

        # 제목 앞 "(남동구)" / "(연수구)" / "(서구)" 등 군구 힌트 추출
        sigungu_hint = ""
        m_gu = re.match(r"^\(([^)]+)\)", name)
        if m_gu:
            gu_cand = regions.canonical_sigungu("인천광역시", m_gu.group(1))
            if gu_cand:
                sigungu_hint = gu_cand
        agency = f"인천광역시 {sigungu_hint}".strip() if sigungu_hint else "인천광역시"
        detail_url = f"https://www.incheon.go.kr/icbenefit/ICB010201/view?&srvcId={srvc_id}"

        records.append({
            "서비스ID": f"ICBENEFIT-{srvc_id}",
            "서비스명": name,
            "서비스목적요약": _clean(desc_raw) or name,
            "소관기관명": f"{agency} (인천맞춤형수혜)",
            "소관기관코드": "ICBENEFIT",
            "소관기관유형": "지자체 복지포털",
            "서비스분야": "생활지원",
            "사용자구분": "개인",
            "지원대상": "인천광역시 시민",
            "선정기준": "인천광역시 맞춤형수혜서비스 자체 등록 사업으로 세부 기준은 원문에서 확인하세요.",
            "지원내용": _clean(desc_raw) or name,
            "지원유형": "지자체 자체 공고",
            "신청방법": "인천광역시 맞춤형수혜서비스 안내 참조",
            "신청기한": deadline_text,
            "접수기관": contact or agency,
            "전화문의": contact or "032-120",
            "상세조회URL": detail_url,
            "온라인신청사이트URL": detail_url,
            "구비서류": "",
            "수정일시": now.isoformat(),
            "conditions": {},
            "source": "local_portal",
            "track": programs.TRACK_PERSONAL,
        })
    return records


def fetch_incheon_benefit(*, today: Optional[date] = None,
                          include_expired: bool = False,
                          timeout: float = 8.0) -> List[Dict[str, Any]]:
    try:
        body = _fetch_html(INCHEON_BENEFIT_URL, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return []
    return parse_incheon_benefit_html(body, today=today, include_expired=include_expired)


# ---------------------------------------------------------------------------
# 3. 인천광역시: 1인가구 포털 (OHH020107)
# ---------------------------------------------------------------------------
def parse_incheon_1in_html(body: str, *, today: Optional[date] = None,
                           include_expired: bool = False) -> List[Dict[str, Any]]:
    now = today or datetime.now().date()
    records: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for _no, area_raw, q_param, title_raw, period_raw in _IC1_ROW_RE.findall(body):
        m_id = re.search(r"oneHouseHoldId=([A-Za-z0-9]+)", q_param)
        sid = m_id.group(1) if m_id else ""
        if not sid or sid in seen:
            continue
        seen.add(sid)
        name = _clean(title_raw)
        if not name:
            continue
        area = _clean(area_raw)
        deadline_text = _clean(period_raw) or "연중"
        parsed_dl = deadlines.parse_deadline(deadline_text, today=now, title=name)
        if not include_expired and parsed_dl.get("expired"):
            continue

        gu = regions.canonical_sigungu("인천광역시", area) if area and area != "인천" else None
        agency = f"인천광역시 {gu}" if gu else "인천광역시"
        records.append({
            "서비스ID": f"IC1IN-{sid}",
            "서비스명": name,
            "서비스목적요약": f"{agency} 1인가구 포털 지원사업",
            "소관기관명": f"{agency} (인천1인가구포털)",
            "소관기관코드": "IC1IN",
            "소관기관유형": "지자체 복지포털",
            "서비스분야": "생활지원",
            "사용자구분": "개인",
            "지원대상": f"{agency} 1인가구",
            "선정기준": "인천 1인가구 포털 등록 사업으로 세부 신청 방법은 포털에서 확인하세요.",
            "지원내용": name,
            "지원유형": "지자체 자체 공고",
            "신청방법": "인천 1인가구 포털 참조",
            "신청기한": deadline_text,
            "접수기관": agency,
            "전화문의": "032-120",
            "상세조회URL": INCHEON_1IN_URL,
            "온라인신청사이트URL": INCHEON_1IN_URL,
            "구비서류": "",
            "수정일시": now.isoformat(),
            "conditions": {},
            "source": "local_portal",
            "track": programs.TRACK_PERSONAL,
        })
    return records


def fetch_incheon_1in(*, today: Optional[date] = None,
                      include_expired: bool = False,
                      timeout: float = 8.0) -> List[Dict[str, Any]]:
    try:
        body = _fetch_html(INCHEON_1IN_URL, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return []
    return parse_incheon_1in_html(body, today=today, include_expired=include_expired)


# ---------------------------------------------------------------------------
# 4. 서울특별시: 서울복지포털 (wis.seoul.go.kr)
# ---------------------------------------------------------------------------
def parse_seoul_wis_html(body: str, *, today: Optional[date] = None) -> List[Dict[str, Any]]:
    now = today or datetime.now().date()
    records: List[Dict[str, Any]] = []
    seen_titles: Set[str] = set()
    for seq, cat_raw, title_raw, desc_raw in _SEOUL_ITEM_RE.findall(body):
        name = _clean(title_raw)
        if not name or name in seen_titles:
            continue
        seen_titles.add(name)
        cat = _clean(cat_raw).strip("[]")
        desc = _clean(desc_raw) or name
        records.append({
            "서비스ID": f"SEOULWIS-{seq}",
            "서비스명": name,
            "서비스목적요약": desc,
            "소관기관명": "서울특별시 (서울복지포털)",
            "소관기관코드": "SEOULWIS",
            "소관기관유형": "지자체 복지포털",
            "서비스분야": cat or "생활지원",
            "사용자구분": "개인",
            "지원대상": f"서울특별시 시민 ({cat})" if cat else "서울특별시 시민",
            "선정기준": "서울복지포털 등록 사업으로 세부 자격은 서울복지포털에서 확인하세요.",
            "지원내용": desc,
            "지원유형": "지자체 자체 공고",
            "신청방법": "서울복지포털(wis.seoul.go.kr) 참조",
            "신청기한": "상시 (세부 일정 포털 확인)",
            "접수기관": "서울특별시 / 관할 자치구",
            "전화문의": "02-120",
            "상세조회URL": SEOUL_WIS_URL,
            "온라인신청사이트URL": SEOUL_WIS_URL,
            "구비서류": "",
            "수정일시": now.isoformat(),
            "conditions": {},
            "source": "local_portal",
            "track": programs.TRACK_PERSONAL,
        })
    return records


def fetch_seoul_wis(*, today: Optional[date] = None,
                    timeout: float = 10.0) -> List[Dict[str, Any]]:
    try:
        body = _fetch_html(SEOUL_WIS_URL, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return []
    return parse_seoul_wis_html(body, today=today)


# ---------------------------------------------------------------------------
# 5. 경기도: 경기민원24 (gg24.gg.go.kr)
# ---------------------------------------------------------------------------
_GG24_ITEM_RE = re.compile(r'<li\s+class="board-boxlist__item">(.*?)</li>', re.S)


def parse_gg24_list_html(body: str, *, today: Optional[date] = None,
                         include_expired: bool = False) -> List[Dict[str, Any]]:
    now = today or datetime.now().date()
    records: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for block in _GG24_ITEM_RE.findall(body):
        m_href = re.search(r'href="(/svcreqst/selectSvcReqst\.do\?svc_seq=(\d+)[^"]*)"', block)
        if not m_href:
            continue
        href, seq = m_href.group(1), m_href.group(2)
        if seq in seen:
            continue
        seen.add(seq)

        badge_m = re.search(r'class="board-boxlist--top__badge"[^>]*>(.*?)</div>', block, re.S)
        badge = _clean(badge_m.group(1)) if badge_m else ""
        if badge and "마감" in badge and not include_expired:
            continue

        tit_m = re.search(r'class="board-boxlist--bottom__tit"[^>]*>(.*?)</h4>', block, re.S)
        if not tit_m:
            continue
        title = _clean(tit_m.group(1))
        if not title:
            continue

        sub_m = re.search(r'class="board-boxlist--bottom__sub"[^>]*>(.*?)</p>', block, re.S)
        deadline_text = _clean(sub_m.group(1)) if sub_m else "상시 접수"
        if not deadline_text:
            deadline_text = "상시 접수"
        parsed_dl = deadlines.parse_deadline(deadline_text, today=now, title=title)
        if not include_expired and parsed_dl.get("expired"):
            continue

        methods = [_clean(x) for x in re.findall(r'class="badge__text[^"]*"[^>]*>(.*?)</span>', block, re.S)]
        method_str = " · ".join(m for m in methods if m) or "경기민원24 온라인/오프라인 접수"
        detail_url = GG24_BASE + html.unescape(href)
        records.append({
            "서비스ID": f"GG24-{seq}",
            "서비스명": title,
            "서비스목적요약": f"경기도 경기민원24 등록 지원사업 ({deadline_text})",
            "소관기관명": "경기도 (경기민원24)",
            "소관기관코드": "GG24",
            "소관기관유형": "지자체 복지포털",
            "서비스분야": "생활지원",
            "사용자구분": "개인",
            "지원대상": "경기도민 (세부 조건 원문 확인)",
            "선정기준": "경기민원24 등록 공고로, 세부 자격 요건은 원문 페이지에서 확인하세요.",
            "지원내용": title,
            "지원유형": "지자체 자체 공고",
            "신청방법": method_str,
            "신청기한": deadline_text,
            "접수기관": "경기도 / 경기민원24",
            "전화문의": "031-120",
            "상세조회URL": detail_url,
            "온라인신청사이트URL": detail_url,
            "구비서류": "",
            "수정일시": now.isoformat(),
            "conditions": {},
            "source": "local_portal",
            "track": programs.TRACK_PERSONAL,
        })
    return records


def fetch_gg24(*, max_pages: int = 3, today: Optional[date] = None,
               include_expired: bool = False,
               timeout: float = 8.0) -> List[Dict[str, Any]]:
    all_records: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for page in range(1, max(1, max_pages) + 1):
        try:
            body = _fetch_html(GG24_LIST_URL.format(page=page), timeout=timeout)
        except (ssl.SSLError, urllib.error.URLError, TimeoutError, OSError):
            break
        rows = parse_gg24_list_html(body, today=today, include_expired=include_expired)
        if not rows:
            break
        for row in rows:
            if row["서비스ID"] not in seen_ids:
                seen_ids.add(row["서비스ID"])
                all_records.append(row)
    return all_records


# ---------------------------------------------------------------------------
# 6. 세종특별자치시: 세종시민 보조금 찾기
# ---------------------------------------------------------------------------
_SEJONG_CARD_RE = re.compile(
    r"fn_search_detail\('(\d+)'\)[^>]*class=\"card-title\"[^>]*>(.*?)</a>\s*"
    r'<p\s+class="card-desc"[^>]*>(.*?)</p>',
    re.S,
)


def parse_sejong_subsidy_html(body: str, *, today: Optional[date] = None) -> List[Dict[str, Any]]:
    now = today or datetime.now().date()
    records: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for seq, title_raw, desc_raw in _SEJONG_CARD_RE.findall(body):
        if seq in seen:
            continue
        seen.add(seq)
        name = _clean(title_raw)
        if not name:
            continue
        desc = _clean(desc_raw) or name
        records.append({
            "서비스ID": f"SEJONG-{seq}",
            "서비스명": name,
            "서비스목적요약": desc,
            "소관기관명": "세종특별자치시",
            "소관기관코드": "SEJONG-SUB",
            "소관기관유형": "지자체 복지포털",
            "서비스분야": "생활지원",
            "사용자구분": "개인",
            "지원대상": "세종특별자치시 시민",
            "선정기준": "세종특별자치시 보조금 안내 사업으로 세부 기준은 원문 페이지에서 확인하세요.",
            "지원내용": desc,
            "지원유형": "지자체 자체 공고",
            "신청방법": "세종시 보조금 찾기 온라인/방문 신청",
            "신청기한": "상시 (세부 일정 포털 확인)",
            "접수기관": "세종특별자치시",
            "전화문의": "044-120",
            "상세조회URL": SEJONG_SUBSIDY_URL,
            "온라인신청사이트URL": SEJONG_SUBSIDY_URL,
            "구비서류": "",
            "수정일시": now.isoformat(),
            "conditions": {},
            "source": "local_portal",
            "track": programs.TRACK_PERSONAL,
        })
    return records


def fetch_sejong_subsidy(*, today: Optional[date] = None,
                         timeout: float = 10.0) -> List[Dict[str, Any]]:
    try:
        body = _fetch_html(SEJONG_SUBSIDY_URL, timeout=timeout)
    except (ssl.SSLError, urllib.error.URLError, TimeoutError, OSError):
        return []
    return parse_sejong_subsidy_html(body, today=today)


# ---------------------------------------------------------------------------
# 7. 전국 17개 시·도: 지역사회서비스포털 (broso.or.kr)
# ---------------------------------------------------------------------------
_BROSO_ITEM_RE = re.compile(
    r"fn_selectServiceSeachDet\('([^']*)',\s*'([^']*)'\);\"[^>]*>\s*"
    r"<dl>\s*<dt>(.*?)</dt>\s*<dd>(.*?)</dd>\s*</dl>",
    re.S,
)
_BROSO_ORG_RE = re.compile(r"<span>\s*\[([^\]]+)\]\s*</span>", re.S)


def _infer_sigungu_from_org(sido: str, org_name: str) -> str:
    """기관명([부평구보건소], [수원시청], [해운대구] 등)에서 시군구명을 추출한다."""
    if not org_name or sido == "세종특별자치시":
        return ""
    for suffix in ("청", "보건소", "복지관", "가족센터", "지원센터", "시니어클럽", "종합사회복지관", "건강생활지원센터"):
        idx = org_name.find(suffix)
        if idx > 0:
            cand = org_name[:idx].strip()
            gu = regions.canonical_sigungu(sido, cand)
            if gu:
                return gu
    m_sgg = re.search(r"([가-힣]{1,5}[시군구])", org_name)
    if m_sgg:
        gu = regions.canonical_sigungu(sido, m_sgg.group(1))
        if gu:
            return gu
    return ""


def parse_broso_list_html(body: str, *, slug: str, sido: str,
                          today: Optional[date] = None) -> List[Dict[str, Any]]:
    now = today or datetime.now().date()
    records: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    base_url = BROSO_URL_TMPL.format(slug=slug)

    for engn_id, svc_id, dt_raw, dd_raw in _BROSO_ITEM_RE.findall(body):
        uid = f"{slug}-{engn_id}-{svc_id}"
        if uid in seen:
            continue
        seen.add(uid)

        org_m = _BROSO_ORG_RE.search(dt_raw)
        org_name = _clean(org_m.group(1)) if org_m else sido
        title_only = _BROSO_ORG_RE.sub("", dt_raw)
        name = _clean(title_only)
        if not name:
            continue
        desc = _clean(dd_raw) or name

        sigungu = _infer_sigungu_from_org(sido, org_name)
        agency = f"{sido} {sigungu} ({org_name})".strip() if sigungu else f"{sido} ({org_name})"

        records.append({
            "서비스ID": f"BROSO-{slug.upper()}-{engn_id}-{svc_id}",
            "서비스명": name,
            "서비스목적요약": desc,
            "소관기관명": agency,
            "소관기관코드": f"BROSO-{slug.upper()}",
            "소관기관유형": "지자체 지역사회서비스",
            "서비스분야": "돌봄·복지서비스",
            "사용자구분": "개인",
            "지원대상": f"{sido} {sigungu} 주민 ({org_name})".replace("  ", " ").strip(),
            "선정기준": "지역사회서비스포털 등록 사업으로 세부 자격은 해당 포털·기관에서 확인하세요.",
            "지원내용": desc,
            "지원유형": "지자체 지역사회서비스",
            "신청방법": f"관할 읍·면·동 행정복지센터 또는 {org_name} 문의",
            "신청기한": "상시 (기관별 모집시기 확인)",
            "접수기관": org_name,
            "전화문의": "",
            "상세조회URL": base_url,
            "온라인신청사이트URL": base_url,
            "구비서류": "",
            "수정일시": now.isoformat(),
            "conditions": {},
            "source": "local_portal",
            "track": programs.TRACK_PERSONAL,
        })
    return records


def fetch_broso_region(slug: str, sido: str, *, max_pages: int = 8,
                       today: Optional[date] = None,
                       timeout: float = 8.0) -> List[Dict[str, Any]]:
    url = BROSO_URL_TMPL.format(slug=slug)
    try:
        first_body = _fetch_html(url, timeout=timeout, retries=2)
    except (ssl.SSLError, urllib.error.URLError, TimeoutError, OSError):
        return []

    m_cnt = re.search(r"총\s*\(?\s*(\d+)\s*건", first_body)
    total_cnt = int(m_cnt.group(1)) if m_cnt else 10
    total_pages = min(max(1, max_pages), max(1, math.ceil(total_cnt / 10)))

    all_rows = parse_broso_list_html(first_body, slug=slug, sido=sido, today=today)
    seen_ids = {r["서비스ID"] for r in all_rows}

    for page in range(2, total_pages + 1):
        try:
            body = _fetch_html(
                url,
                timeout=timeout,
                data=urllib.parse.urlencode({"pageIndex": str(page)}).encode("utf-8"),
                retries=2,
            )
        except (ssl.SSLError, urllib.error.URLError, TimeoutError, OSError):
            continue
        rows = parse_broso_list_html(body, slug=slug, sido=sido, today=today)
        if not rows:
            break
        for row in rows:
            if row["서비스ID"] not in seen_ids:
                seen_ids.add(row["서비스ID"])
                all_rows.append(row)
    return all_rows


def fetch_broso_all(*, max_pages_per_sido: int = 8,
                    today: Optional[date] = None,
                    timeout: float = 8.0) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    results: List[Dict[str, Any]] = []
    per_sido: Dict[str, int] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        future_map = {
            pool.submit(fetch_broso_region, slug, sido, max_pages=max_pages_per_sido, today=today, timeout=timeout): (slug, sido)
            for slug, sido in BROSO_REGIONS
        }
        for fut in concurrent.futures.as_completed(future_map):
            slug, _sido = future_map[fut]
            try:
                rows = fut.result()
            except Exception:
                rows = []
            per_sido[slug] = len(rows)
            results.extend(rows)
    return results, per_sido


# ---------------------------------------------------------------------------
# 통합 수집 및 미연동 지역 안내
# ---------------------------------------------------------------------------
def collect_all_local_portals(*, today: Optional[date] = None,
                              include_expired: bool = False,
                              broso_max_pages: int = 8) -> Dict[str, Any]:
    """연동된 모든 지자체 자체 복지포털 데이터를 수집·중복제거한다."""
    bupyeong = fetch_bupyeong_bokjion(max_pages=5, today=today, include_expired=include_expired)
    incheon_b = fetch_incheon_benefit(today=today, include_expired=include_expired)
    incheon_1 = fetch_incheon_1in(today=today, include_expired=include_expired)
    seoul = fetch_seoul_wis(today=today)
    gg24 = fetch_gg24(max_pages=3, today=today, include_expired=include_expired)
    sejong = fetch_sejong_subsidy(today=today)
    broso_rows, broso_counts = fetch_broso_all(max_pages_per_sido=broso_max_pages, today=today)

    combined: List[Dict[str, Any]] = []
    seen_names: Set[Tuple[str, str]] = set()
    for row in bupyeong + incheon_b + incheon_1 + seoul + gg24 + sejong + broso_rows:
        key = (row.get("소관기관명", "").split("(")[0].strip(), row.get("서비스명", "").strip())
        if key in seen_names:
            continue
        seen_names.add(key)
        combined.append(row)

    return {
        "records": combined,
        "counts": {
            "bupyeong_bokjion": len(bupyeong),
            "incheon_benefit": len(incheon_b),
            "incheon_1in": len(incheon_1),
            "seoul_wis": len(seoul),
            "gg24": len(gg24),
            "sejong_subsidy": len(sejong),
            "broso_total": len(broso_rows),
            "broso_by_sido": broso_counts,
            "total_deduped": len(combined),
        },
    }


def coverage_status(sido: Optional[str], sigungu: Optional[str] = None) -> Dict[str, Any]:
    """선택한 지역의 지자체 자체 복지포털 연동 여부를 반환한다.

    - 연동된 지역(`supported=True`): 별도 경고가 필요 없음.
    - 미연동 지역(`supported=False`): UI·API에서 "이 지역 구청 자체 공지는 미연동" 안내를 띄운다.
    """
    if not sido:
        return {
            "supported": True,
            "scope": "national",
            "portal_names": [v["name"] for v in SUPPORTED_PORTAL_REGIONS.values()],
            "notice_ko": None,
        }

    sido_entry = SUPPORTED_PORTAL_REGIONS.get((sido, ""))
    sigungu_entry = SUPPORTED_PORTAL_REGIONS.get((sido, sigungu)) if sigungu else None

    if sigungu:
        if sigungu_entry:
            return {
                "supported": True,
                "scope": "sigungu",
                "portal_names": [sigungu_entry["name"]] + ([sido_entry["name"]] if sido_entry else []),
                "notice_ko": None,
            }
        if sido_entry:
            return {
                "supported": False,
                "scope": "sigungu_missing",
                "portal_names": [sido_entry["name"]],
                "notice_ko": (
                    f"{sido} 광역 포털({sido_entry['name']})과 지역사회서비스는 연동되어 있으나, "
                    f"{sigungu} 구·군청 자체 홈페이지 행사 공지는 아직 별도 연동되지 않아 "
                    "정부24·시도 포털 등록 제도 위주로 표시됩니다."
                ),
            }
        return {
            "supported": False,
            "scope": "region_missing",
            "portal_names": [],
            "notice_ko": (
                f"{sido} {sigungu}는 아직 지자체 자체 복지포털이 연동되지 않아 "
                "정부24(보조금24)·K-Startup·기업마당 정식 등록 제도만 표시됩니다."
            ),
        }

    if sido_entry:
        return {
            "supported": True,
            "scope": "sido",
            "portal_names": [sido_entry["name"]],
            "notice_ko": None,
        }

    return {
        "supported": False,
        "scope": "region_missing",
        "portal_names": [],
        "notice_ko": (
            f"{sido}는 아직 지자체 자체 복지포털이 연동되지 않아 "
            "정부24(보조금24)·K-Startup·기업마당 정식 등록 제도만 표시됩니다."
        ),
    }
