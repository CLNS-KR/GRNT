"""신청기한 자유 텍스트 → 구조화된 기한.

원본 `신청기한`은 "상시신청", "2026. 3. 2. ~ 2026. 12. 31.", "예산 소진 시까지",
"접수기관 별 상이"처럼 제각각입니다. **확실히 읽히는 날짜만** 쓰고, 애매하면
`unknown`으로 남깁니다(추측한 마감일을 알려 주는 것이 가장 나쁜 오답입니다).
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

_DATE_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_YEAR_MONTH_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*(?:월|\.)(?:\s*중|\s*말|\s*까지)?(?!\s*\d)")
_SHORT_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?")
_YEAR_ONLY_RE = re.compile(r"(?<!\d)(20\d{2})\s*년")
_SINCE_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}[^\n~-]{0,6}(?:이후|부터)")

STATE_ALWAYS = "always"
STATE_NOT_REQUIRED = "not_required"
STATE_BUDGET = "budget_exhausted"
STATE_RANGE = "date_range"
STATE_DEADLINE_ONLY = "deadline_only"
STATE_VARIES = "varies"
STATE_UNKNOWN = "unknown"

_ALWAYS = ("상시", "연중", "수시", "계속")
_NOT_REQUIRED = ("신청불필요", "신청 불필요", "별도신청없음", "별도 신청 없음")
_BUDGET = ("예산소진", "예산 소진", "예산범위", "예산 범위", "소진시")
_VARIES = ("접수기관", "별도 공고", "공고기한", "사업별", "기관별", "지자체별")


def _parse_pairs(text: str) -> List[Tuple[str, str, str]]:
    """(연, 월, 일) 세 쌍. 연도가 없는 짧은 표기는 앞 날짜의 연도를 물려받는다."""
    tokens: List[Tuple[int, int, str, str, str]] = []
    occupied: List[Tuple[int, int]] = []

    for match in _DATE_RE.finditer(text):
        tokens.append((match.start(), match.end(), match.group(1), match.group(2), match.group(3)))
        occupied.append((match.start(), match.end()))

    def _overlaps(s: int, e: int) -> bool:
        return any(not (e <= os_ or s >= oe_) for os_, oe_ in occupied)

    for match in _YEAR_MONTH_RE.finditer(text):
        if _overlaps(match.start(), match.end()):
            continue
        y, m = int(match.group(1)), int(match.group(2))
        if 1 <= m <= 12:
            last_day = calendar.monthrange(y, m)[1]
            # 첫 번째 토큰이면 1일, 마지막/종료 쪽이면 말일
            day_str = str(last_day) if tokens else "1"
            tokens.append((match.start(), match.end(), str(y), str(m), day_str))
            occupied.append((match.start(), match.end()))

    for match in _SHORT_RE.finditer(text):
        if _overlaps(match.start(), match.end()):
            continue
        tokens.append((match.start(), match.end(), "", match.group(1), match.group(2)))
        occupied.append((match.start(), match.end()))

    # 단, 연도가 있는 _YEAR_MONTH_RE가 하나 이상 있고 뒤에 "12월"만 있는 경우 보정
    if any(t[2] for t in tokens):
        for match in re.finditer(r"(?<!\d)(1[0-2]|[1-9])\s*월(?!\s*\d)", text):
            if _overlaps(match.start(), match.end()):
                continue
            m = int(match.group(1))
            tokens.append((match.start(), match.end(), "", str(m), "__END_OF_MONTH__"))
            occupied.append((match.start(), match.end()))

    tokens.sort(key=lambda t: t[0])
    out: List[Tuple[str, str, str]] = []
    last_year = ""
    for _, _, y, m, d in tokens:
        if y:
            last_year = y
        elif last_year:
            y = last_year
        if d == "__END_OF_MONTH__":
            if y and 1 <= int(m) <= 12:
                d = str(calendar.monthrange(int(y), int(m))[1])
            else:
                continue
        out.append((y, m, d))
    return out


def _iso(year: str, month: str, day: str) -> Optional[str]:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except (TypeError, ValueError):
        return None


def parse_deadline(text: Optional[str], today: Optional[date] = None,
                   title: Optional[str] = None) -> Dict[str, Any]:
    raw = str(text or "").strip()
    now = today or datetime.now().date()
    base = {"raw": raw, "start_date": None, "end_date": None, "days_left": None,
            "closing_soon": False}
    if not raw:
        res = {**base, "state": STATE_UNKNOWN,
               "label_ko": "신청기한 미기재", "note_ko": "원문에서 신청기한을 확인해야 합니다."}
        _check_past_year_title(res, title, now)
        return res
    compact = raw.replace(" ", "")

    if any(word.replace(" ", "") in compact for word in _NOT_REQUIRED):
        return {**base, "state": STATE_NOT_REQUIRED, "label_ko": "신청 절차 없음"}
    if any(word.replace(" ", "") in compact for word in _ALWAYS):
        return {**base, "state": STATE_ALWAYS, "label_ko": "상시 신청"}
    if any(word.replace(" ", "") in compact for word in _BUDGET):
        return {**base, "state": STATE_BUDGET, "label_ko": "예산 소진 시까지",
                "note_ko": "예산이 소진되면 조기에 마감될 수 있습니다."}

    # "2012. 7. 1. 이후" 처럼 시작 기준일만 있고 종료 범위가 없는 경우는 마감일이 아니다.
    if _SINCE_RE.search(raw) and "~" not in raw and "-" not in raw:
        return {**base, "state": STATE_UNKNOWN, "label_ko": raw,
                "note_ko": "기준일 이후 신청 대상이며, 별도 마감일은 표기되지 않았습니다."}

    pairs = _parse_pairs(raw)
    parsed: List[Tuple[int, int, int]] = []
    for year, month, day in pairs:
        if not year:
            continue
        try:
            parsed.append((int(year), int(month), int(day)))
        except ValueError:
            continue
    if parsed:
        start = parsed[0]
        end = parsed[-1]
        start_iso = _iso(str(start[0]), str(start[1]), str(start[2]))
        end_iso = _iso(str(end[0]), str(end[1]), str(end[2]))
        state = STATE_RANGE if len(parsed) > 1 else STATE_DEADLINE_ONLY
        result = {**base, "state": state, "start_date": start_iso, "end_date": end_iso,
                  "label_ko": raw}
        _attach_days_left(result, end_iso, now)
        return result

    if any(word.replace(" ", "") in compact for word in _VARIES):
        res = {**base, "state": STATE_VARIES, "label_ko": raw,
               "note_ko": "접수기관·공고에 따라 기한이 달라 원문 확인이 필요합니다."}
        _check_past_year_title(res, title, now)
        return res

    # 날짜 쌍이 없어도 신청기한이나 제목에 과거 연도(예: 2023년)만 명시된 경우
    res = {**base, "state": STATE_UNKNOWN, "label_ko": raw,
           "note_ko": "신청기한 표기를 날짜로 확정할 수 없어 원문 확인이 필요합니다."}
    _check_past_year_only(res, raw, title, now)
    return res


def _check_past_year_only(result: Dict[str, Any], raw: str,
                          title: Optional[str], now: date) -> None:
    if any(k in raw for k in ("이후", "부터", "매년", "상시", "계속", "연중")):
        return
    years = [int(y) for y in _YEAR_ONLY_RE.findall(raw)]
    if years and max(years) < now.year:
        result["expired"] = True
        result["end_date"] = f"{max(years)}-12-31"
        result["note_ko"] = f"{max(years)}년 사업으로 신청기한이 지났습니다."
        return
    _check_past_year_title(result, title, now)


def _check_past_year_title(result: Dict[str, Any], title: Optional[str], now: date) -> None:
    if not title:
        return
    if any(k in title for k in ("이후", "매년", "계속")):
        return
    years = [int(y) for y in _YEAR_ONLY_RE.findall(title)]
    if years and max(years) < now.year:
        result["expired"] = True
        result["end_date"] = result.get("end_date") or f"{max(years)}-12-31"
        result["note_ko"] = f"제목 기준 {max(years)}년 사업으로 신청기한이 지난 것으로 보입니다."


def _attach_days_left(result: Dict[str, Any], end_iso: Optional[str],
                      today: Optional[date]) -> None:
    if not end_iso:
        return
    try:
        end = date.fromisoformat(end_iso)
    except ValueError:
        return
    now = today or datetime.now().date()
    days = (end - now).days
    result["days_left"] = days
    result["closing_soon"] = 0 <= days <= 30
    if days < 0:
        result["expired"] = True
        result["note_ko"] = "표기된 신청기한이 지났습니다. 추가 접수 여부를 문의해야 합니다."


def sort_key(deadline: Dict[str, Any]) -> Tuple[int, str]:
    """마감 임박순 정렬용. 마감일이 있는 것만 앞으로."""
    end = deadline.get("end_date")
    return (0, end) if end else (1, "9999-12-31")
