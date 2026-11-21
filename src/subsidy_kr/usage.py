"""익명 일별 사용 카운터.

남기는 것: `날짜(KST) · 경로 · 툴 이름 · 판정 등급 · 0건/오류 여부`의 **횟수**만.
그리고 **0건으로 끝난 검색어만** 예외적으로 비식별 처리해 남깁니다(아래 `sanitize_query`).
남기지 않는 것: IP, X-Forwarded-For, User-Agent, 쿠키, Referer, 세션, 프로필,
서비스ID 목록, 결과가 있던 검색어. 집계 키는 서버가 아는 값으로만 제한하고, 모르는
경로는 `/404` 한 칸으로 뭉갭니다(임의 문자열이 통계에 남지 않게).

0건 검색어를 남기는 이유
------------------------
"찾는 제도가 없다"는 사실은 다음 데이터 확충의 유일한 신호입니다. 다만 검색어에는
지역·나이·연락처가 섞여 들어오므로 **결과가 0건일 때만**, 다음을 지운 뒤 최대 30자로
남깁니다: 전화번호·주민등록번호·이메일·URL·@핸들, 2자리 이상 숫자, 시·도/시·군·구 이름.
프로필 입력값(나이·소득구간·임신 여부 등)은 검색어와 무관하게 저장하지 않습니다.

문의 폼(다른 경로)
--------------------
이 모듈은 사전 신청·문의 폼(`POST /v1/inquiry`)의 검증·저장도 맡습니다. 이때만 사용자가
직접 적어 보낸 연락처를 `inquiries` 표에 남기며, 회신 목적 외에는 쓰지 않고 이 통계·익명
카운터에는 넣지 않습니다(`inquiry_summary` 는 주제별 건수만 읽습니다).

한계: 무료 플랜은 영구 디스크가 없어 재배포 시 0으로 돌아갑니다(일별 집계라 감수).
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, Optional

from . import models

KST = timezone(timedelta(hours=9))
MAX_DAYS = 30
DEFAULT_DAYS = 7

KIND_PATH = "path"
KIND_TOOL = "tool"
KIND_VERDICT = "verdict"
KIND_FLAG = "flag"
KIND_ZERO_QUERY = "zero_query"

FLAG_ZERO = "zero_results"
FLAG_ERROR = "errors"
FLAG_SAMPLE = "sample_catalog"

FIXED_PATHS = (
    "/", "/s/", "/guides/", "/guides", "/regions/", "/regions",
    "/healthz", "/robots.txt", "/llms.txt", "/sitemap.xml",
    "/.well-known/mcp/server-card.json", "/v1/meta", "/v1/mcp", "/v1/stats",
    "/v1/tools", "/v1/report/export.csv", "/v1/report/print.html",
    "/v1/batch-match", "/v1/batch-match/export.csv", "/v1/batch-match/reports.html",
    "/v1/batch-match/sample.csv", "/v1/inquiry", "/mcp", "/favicon.ico", "/404",
)

KEY_RE = re.compile(r"[^0-9A-Za-z._:/{}-]")
MAX_KEY = 64

# 0건 검색어 — 남기는 형태를 여기서만 정한다.
MAX_QUERY_CHARS = 30      # 저장하는 검색어 최대 길이
TOP_ZERO_QUERIES = 20     # 날짜별로 노출하는 상위 개수(전체 개수는 total/distinct 로 따로)
TRACKS = ("personal", "business", "all")

# --- 사전 신청·문의 폼 ---------------------------------------------------------
# 사용자가 문의 카드에 **직접 적어 보낸 연락처**만 저장한다(판정 입력과 다른 경로).
# 연락처는 회신 목적으로만 쓰고, 통계(`stats_payload`)·익명 카운터에는 절대 넣지 않는다.
INQUIRY_TOPICS = ("batch_report", "api_mcp", "other")
INQUIRY_TOPIC_LABELS = {
    "batch_report": "세무·노무사 거래처 리포트·대량 매칭",
    "api_mcp": "API·MCP 연동",
    "other": "그 밖의 문의",
}
INQUIRY_CONTACT_MIN = 3
INQUIRY_CONTACT_MAX = 120
INQUIRY_MESSAGE_MAX = 500
INQUIRY_DAILY_CAP = 200      # 같은 날 접수 상한(스팸으로 무료 인스턴스 디스크를 채우지 않게)
INQUIRY_KEEP_DAYS = 180      # 회신 목적이 끝난 연락처 보관 기간
# 문의 유실 대비 — 무료 플랜은 영구 디스크가 없어 재배포 때 SQLite 가 초기화된다.
# 아래 두 환경변수는 **운영자(서비스 주인)가 직접 켜는 선택 기능**이며 기본은 꺼져 있다.
INQUIRY_SINK_ENV = "GRNT_INQUIRY_SINK"        # 접수 1건당 JSON 한 줄을 덧붙일 파일(영속 디스크)
INQUIRY_WEBHOOK_ENV = "GRNT_INQUIRY_WEBHOOK"  # 접수 즉시 알림을 받을 운영자 엔드포인트(HTTPS)
INQUIRY_WEBHOOK_TIMEOUT = 3.0

_EMAIL_RE = re.compile(r"[0-9A-Za-z._%+\-]+@[0-9A-Za-z.\-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"(?i)(?:https?://|www\.)\S+")
_HANDLE_RE = re.compile(r"@[0-9A-Za-z._\-]+")
_RRN_RE = re.compile(r"\d{6}\s?-?\s?\d{7}")
_PHONE_RE = re.compile(r"0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}")
_DIGITS_RE = re.compile(r"\d{2,}")          # 2자리 이상 숫자는 나이·연도일 수 있다
_ALLOWED_RE = re.compile(r"[^0-9A-Za-z가-힣\s·+&]")
_SPACE_RE = re.compile(r"\s+")
_HAS_LETTER_RE = re.compile(r"[가-힣]")
_HAS_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_HAS_ANY_RE = re.compile(r"[0-9A-Za-z가-힣]")
_CONTACT_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MESSAGE_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _shift(day: str, days: int) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def safe_key(value: Any) -> str:
    return KEY_RE.sub("", str(value or ""))[:MAX_KEY]


@lru_cache(maxsize=1)
def _region_terms() -> tuple:
    """검색어에서 지울 시·도·시·군·구 이름(긴 것부터).

    지역은 프로필 입력값이면서 동시에 사람을 좁히는 단서입니다. 검색어에 섞여 들어와도
    통계에는 남기지 않습니다(예: '인천 서구 청년 월세' → '청년 월세').
    """
    terms = set()
    try:
        from . import regions
        from .regions_data import SIGUNGU_BY_SIDO

        for name in regions.sido_names():
            terms.add(name)
            for suffix in ("특별시", "광역시", "특별자치시", "특별자치도", "도"):
                if name.endswith(suffix) and len(name) > len(suffix) + 1:
                    terms.add(name[: -len(suffix)])
        terms.update(regions.SIDO_ALIASES.keys())
        for name in regions.SIGUNGU_ALIASES:
            terms.add(name)
        for rows in SIGUNGU_BY_SIDO.values():
            for _code, label in rows:
                terms.add(label)
                if len(label) >= 3:      # '수원시' → '수원', '강남구' → '강남'
                    terms.add(label[:-1])
                head = label.split()[0]  # '수원시 장안구' → '수원시'
                if head != label:
                    terms.add(head)
                    if len(head) >= 3:
                        terms.add(head[:-1])
    except Exception:  # noqa: BLE001 - 지역 명부가 없어도 카운터는 돌아야 한다
        pass
    return tuple(sorted((term for term in terms if len(term) >= 2),
                        key=len, reverse=True))


@lru_cache(maxsize=1)
def _tag_words() -> tuple:
    """분야 추론용 규칙((슬러그, 낱말들)) — 카탈로그의 TAG_RULES 와 같은 표를 쓴다."""
    try:
        from .catalog import TAG_RULES

        return tuple((slug, tuple(str(word).lower() for word in words if word))
                     for slug, _label, words in TAG_RULES)
    except Exception:  # noqa: BLE001
        return ()


def infer_tag(query: str) -> str:
    """검색어에서 분야 태그를 추론한다(사용자가 분야을 고르지 않아도 통계에 남기기 위해).

    검색어 자체에서만 뽑으므로 추가 개인정보가 생기지 않는다.
    """
    text = str(query or "").lower()
    if not text:
        return ""
    for slug, words in _tag_words():
        if any(word in text for word in words):
            return slug
    return ""


@lru_cache(maxsize=1)
def _tag_labels() -> dict:
    try:
        from .catalog import TAG_RULES

        return {slug: label for slug, label, _words in TAG_RULES}
    except Exception:  # noqa: BLE001
        return {}


def _is_region_token(token: str, terms: tuple) -> bool:
    """토큰이 지역명만으로 이루어졌는지(‘인천서구’, ‘수원시’, ‘서해구청’)."""
    rest = token
    for _ in range(6):        # 지역명이 최대 여러 개 붙는 경우만 본다
        if not rest:
            return True
        if rest in ("청", "시청", "구청", "군청"):
            return True
        for term in terms:    # 긴 이름부터
            if rest.startswith(term):
                rest = rest[len(term):]
                break
        else:
            return False
    return not rest


def _strip_regions(text: str) -> str:
    """지역명만 남은 토큰을 통째로 지운다.

    낱말 가운데 들어 있는 지역명은 지우지 않습니다 — ‘무주택’의 ‘무주(茂朱)’처럼
    다른 뜻으로 쓰인 말까지 없애면 통계가 쓸모없어집니다.
    """
    terms = _region_terms()
    kept = [token for token in text.split() if not _is_region_token(token, terms)]
    return " ".join(kept)


def sanitize_query(text: Any, limit: int = MAX_QUERY_CHARS) -> str:
    """검색어 → 통계에 남겨도 되는 비식별 형태(최대 `limit`자).

    남는 것이 없으면 빈 문자열을 돌려주고, 호출자는 그때 기록하지 않습니다.
    """
    raw = str(text or "")[:400]
    raw = _URL_RE.sub(" ", raw)
    raw = _EMAIL_RE.sub(" ", raw)
    raw = _HANDLE_RE.sub(" ", raw)
    raw = _RRN_RE.sub(" ", raw)
    raw = _PHONE_RE.sub(" ", raw)
    raw = _ALLOWED_RE.sub(" ", raw)
    raw = _strip_regions(raw)
    raw = _DIGITS_RE.sub("N", raw)
    raw = _SPACE_RE.sub(" ", raw).strip()
    # 숫자만 있던 토큰은 'N' 한 글자로 남는다 — 뜻이 없으니 버린다.
    raw = " ".join(token for token in raw.split() if token.strip("N"))
    if len(raw) > limit:
        raw = raw[:limit].strip()
    # 숫자 자리표시자만 남았거나(='N'만) 아무 글자도 없으면 기록하지 않는다.
    if not raw or not _HAS_ANY_RE.search(raw):
        return ""
    if not _HAS_LETTER_RE.search(raw) and not _HAS_WORD_RE.search(raw):
        return ""
    return raw


def safe_tag(value: Any) -> str:
    """분야(tag)는 카탈로그가 아는 슬러그만 남긴다(임의 문자열 유입 차단)."""
    tag = str(value or "").strip()
    return tag if tag in _tag_labels() else ""


# --- 사전 신청·문의 폼 ---------------------------------------------------------
# 판정 입력과 다른 경로다. 사용자가 문의 카드에 직접 적어 보낸 연락처만 다루고,
# 아래 함수들은 판정 프로필(나이·지역·소득·임신 등)을 읽지 않는다.
INQUIRY_ERRORS_KO = {
    "contact_too_short": f"연락처를 {INQUIRY_CONTACT_MIN}자 이상 적어 주세요.",
    "contact_too_long": f"연락처는 {INQUIRY_CONTACT_MAX}자까지 쓸 수 있습니다.",
    "invalid_topic": "문의 유형을 다시 선택해 주세요.",
    "message_too_long": f"문의 내용은 {INQUIRY_MESSAGE_MAX}자까지 쓸 수 있습니다.",
    "daily_cap_reached": "오늘 접수 한도에 닿았습니다. 내일 다시 보내 주시거나 API·MCP 주소로 남겨 주세요.",
    "store_unavailable": "지금은 문의를 저장할 수 없습니다. 잠시 뒤 다시 시도해 주세요.",
}


def clean_contact(value: Any) -> str:
    """연락처 1줄 — 제어문자·줄바꿈을 공백으로 바꾸고 앞뒤 공백을 뗀다."""
    text = _CONTACT_CTRL_RE.sub(" ", str(value or "")[:400])
    return _SPACE_RE.sub(" ", text).strip()


def clean_message(value: Any) -> str:
    """문의 내용 — 줄바꿈·탭은 남기고 나머지 제어문자만 지운다."""
    text = _MESSAGE_CTRL_RE.sub(" ", str(value or "")[:2000])
    return text.strip()


def normalize_inquiry(payload: Any) -> tuple:
    """요청 본문 → `(정리된 값, 오류 코드)`. 오류가 없으면 두 번째 값이 None.

    `contact` 3~120자 · `topic` 은 `INQUIRY_TOPICS` 중 하나 · `message` 는 선택 0~500자.
    """
    data = payload if isinstance(payload, dict) else {}
    contact = clean_contact(data.get("contact"))
    if len(contact) < INQUIRY_CONTACT_MIN:
        return {}, "contact_too_short"
    if len(contact) > INQUIRY_CONTACT_MAX:
        return {}, "contact_too_long"
    topic = str(data.get("topic") or "").strip()
    if topic not in INQUIRY_TOPICS:
        return {}, "invalid_topic"
    message = clean_message(data.get("message"))
    if len(message) > INQUIRY_MESSAGE_MAX:
        return {}, "message_too_long"
    return {"contact": contact, "topic": topic, "message": message}, None


def save_inquiry(store: Any, data: Dict[str, Any], day: Optional[str] = None) -> Dict[str, Any]:
    """정리된 문의를 저장한다 — 같은 날 같은 내용은 한 번만 남긴다.

    저장에 실패해도 예외를 밖으로 던지지 않고 `stored: False`를 돌려준다(응답이 깨지지 않게).
    저장 뒤에는 **선택 기능**인 파일 미러·알림 훅을 시도한다(둘 다 기본 꺼짐).
    """
    stamp = day or today_kst()
    if store is None:
        return {"stored": False, "duplicate": False, "error": "store_unavailable"}
    contact = str(data.get("contact") or "")
    topic = str(data.get("topic") or "")
    message = str(data.get("message") or "")
    try:
        if store.inquiry_exists(stamp, topic, contact, message):
            return {"stored": False, "duplicate": True}
        if store.inquiry_count(stamp) >= INQUIRY_DAILY_CAP:
            return {"stored": False, "duplicate": False, "error": "daily_cap_reached"}
        row_id = store.add_inquiry(stamp, topic, contact, message)
    except Exception:  # noqa: BLE001 - 저장 실패가 응답 형식을 바꾸지 않게
        return {"stored": False, "duplicate": False, "error": "store_unavailable"}
    receipt = f"I{int(row_id):05d}"
    return {"stored": True, "duplicate": False, "receipt": receipt,
            "persistence": mirror_inquiry(data, stamp=stamp, receipt=receipt)}


def mirror_inquiry(data: Dict[str, Any], *, stamp: str, receipt: str) -> Dict[str, Any]:
    """문의 유실 대비 — 파일 미러(`GRNT_INQUIRY_SINK`)와 알림 훅(`GRNT_INQUIRY_WEBHOOK`).

    둘 다 운영자가 환경변수로 켜야 동작하고, 실패해도 접수 응답을 막지 않는다.
    내보내는 값은 사용자가 문의 카드에 직접 적은 연락처·주제·내용뿐이며(회신 목적),
    나이·지역·소득 같은 판정 입력은 여기까지 오지 않는다.
    """
    result: Dict[str, Any] = {"stored_in_database": True, "mirrored_to_file": False,
                              "notified_hook": False}
    sink = str(os.environ.get(INQUIRY_SINK_ENV) or "").strip()
    if sink:
        result["mirrored_to_file"] = _append_inquiry_sink(sink, data, stamp, receipt)
    hook = str(os.environ.get(INQUIRY_WEBHOOK_ENV) or "").strip()
    if hook:
        result["notified_hook"] = _notify_inquiry_hook(hook, data, stamp, receipt)
    return result


def _append_inquiry_sink(path: str, data: Dict[str, Any], stamp: str, receipt: str) -> bool:
    """접수 1건을 JSON 한 줄로 덧붙인다(영속 디스크에 두면 재배포에도 남는다)."""
    line = json.dumps({"receipt": receipt, "day": stamp, "topic": data.get("topic"),
                       "contact": data.get("contact"), "message": data.get("message"),
                       "received_at": datetime.now(KST).isoformat(timespec="seconds")},
                      ensure_ascii=False, separators=(",", ":"))
    try:
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except OSError:
        return False


def _notify_inquiry_hook(url: str, data: Dict[str, Any], stamp: str, receipt: str) -> bool:
    """접수 사실을 운영자 엔드포인트로 보낸다 — 응답을 기다리지 않고 스레드에서.

    실패해도 조용히 넘긴다(접수 자체는 이미 끝났다). http(s) 만 허용한다.
    """
    if not url.lower().startswith(("http://", "https://")):
        return False
    payload = json.dumps({"receipt": receipt, "day": stamp, "topic": data.get("topic"),
                          "contact": data.get("contact"), "message": data.get("message"),
                          "source": "grnt"},
                         ensure_ascii=False).encode("utf-8")

    def _post() -> None:
        import urllib.request

        request = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            urllib.request.urlopen(request, timeout=INQUIRY_WEBHOOK_TIMEOUT).close()
        except Exception:  # noqa: BLE001 - 알림 실패가 접수를 되돌리지 않는다
            pass

    try:
        threading.Thread(target=_post, name="inquiry-hook", daemon=True).start()
    except RuntimeError:
        return False
    return True


def inquiry_summary(store: Any) -> Dict[str, Any]:
    """주제별 접수 건수만 — 연락처·내용은 읽지 않는다(운영 확인용)."""
    counts: Dict[str, int] = {}
    try:
        counts = store.inquiry_topic_counts() if store is not None else {}
    except Exception:  # noqa: BLE001
        counts = {}
    total = sum(counts.values())
    return {
        "total": total,
        "by_topic": [{"topic": topic, "label_ko": INQUIRY_TOPIC_LABELS[topic],
                      "count": int(counts.get(topic, 0))}
                     for topic in INQUIRY_TOPICS],
        "stores_contact": True,
        "in_usage_stats": False,
        "keep_days": INQUIRY_KEEP_DAYS,
    }


def purge_inquiries(store: Any, keep_days: int = INQUIRY_KEEP_DAYS,
                    day: Optional[str] = None) -> int:
    """보관 기간이 지난 문의를 지운다(서버 기동 시 1회). 실패해도 기동을 막지 않는다."""
    if store is None:
        return 0
    try:
        return store.purge_inquiries(keep_days, day)
    except Exception:  # noqa: BLE001
        return 0


def zero_query_key(query: str, track: str = "all", tag: str = "") -> str:
    """0건 검색어 1건의 저장 키 — 검색어·트랙·분야를 JSON 한 줄로 묶는다."""
    payload = {"q": str(query or "")[:MAX_QUERY_CHARS],
               "t": track if track in TRACKS else "all",
               "g": safe_tag(tag)}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def zero_entry(key: Any) -> Optional[tuple]:
    """저장 키 → `(검색어, 트랙, 분야)`. 읽을 수 없으면 None."""
    try:
        parsed = json.loads(str(key or ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    query = str(parsed.get("q") or "")
    if not query:
        return None
    track = parsed.get("t") if parsed.get("t") in TRACKS else "all"
    return query[:MAX_QUERY_CHARS], str(track), safe_tag(parsed.get("g"))


@lru_cache(maxsize=1)
def _known_paths() -> frozenset:
    paths = set(FIXED_PATHS)
    try:
        from . import guides, pseo, regions

        for spec in pseo.TOPICS:
            paths.add(f"/s/{spec['slug']}")
        for slug in pseo.SIDO_SLUGS.values():
            paths.add(f"/s/{slug}")
        # 시·도별 허브도 슬러그별로 남겨 어떤 지역이 유입을 만드는지 센다.
        for slug in regions.sido_slugs():
            paths.add(f"/regions/{slug}")
        # 질문형 가이드도 슬러그별 버킷으로 남겨 어떤 질문이 유입을 만드는지 센다.
        for slug in guides.slugs():
            paths.add(f"/guides/{slug}")
    except Exception:  # noqa: BLE001 - 카탈로그가 없어도 카운터는 돌아야 한다
        pass
    # 카탈로그를 열지 않고도 정적 주제·지역 슬러그를 즉시 구성한다.
    return frozenset(paths)


def path_key(path: str) -> str:
    raw = str(path or "").split("?", 1)[0]
    if not raw.startswith("/"):
        return "/404"
    trimmed = raw.rstrip("/") or "/"
    if trimmed.startswith("/v1/tools/"):
        return "/v1/tools"
    for candidate in (raw, trimmed):
        if candidate in _known_paths():
            return candidate
    return "/404"


def record_request(store: Any, method: str, path: str, day: Optional[str] = None) -> None:
    if store is None or str(method or "").upper() not in ("GET", "POST"):
        return
    try:
        store.bump_usage(day or today_kst(), KIND_PATH, path_key(path))
    except Exception:  # noqa: BLE001 - 계측 실패가 응답을 막지 않는다
        pass


def _is_zero_result(name: str, result: Any) -> bool:
    data = result if isinstance(result, dict) else {}
    payload = data.get("result") if isinstance(data.get("result"), dict) else data
    if name == "search_subsidies" and isinstance(payload, dict):
        counts = payload.get("counts")
        if isinstance(counts, dict):
            return int(counts.get(models.VERDICT_ELIGIBLE, 0)) == 0 and \
                   int(counts.get(models.VERDICT_CHECK, 0)) == 0
    if name == "list_region_subsidies" and isinstance(payload, dict):
        return int(payload.get("count") or 0) == 0
    return False


def record_zero_query(store: Any, args: Any, result: Any, day: Optional[str] = None) -> None:
    """결과가 0건인 검색만 비식별 검색어로 남긴다(프로필 값은 보지도 않는다)."""
    if store is None or not isinstance(args, dict):
        return
    keyword = str(args.get("keyword") or args.get("q") or "").strip()
    if not keyword:
        return
    query = sanitize_query(keyword)
    if not query:
        return
    data = result if isinstance(result, dict) else {}
    payload = data.get("result") if isinstance(data.get("result"), dict) else {}
    track = str(payload.get("track") or args.get("track") or "all")
    tag = safe_tag(args.get("tag")) or infer_tag(query)
    try:
        store.bump_usage(day or today_kst(), KIND_ZERO_QUERY,
                         zero_query_key(query, track, tag))
    except Exception:  # noqa: BLE001 - 계측 실패가 응답을 막지 않는다
        pass


def record_tool(store: Any, name: str, result: Any, args: Any = None,
                day: Optional[str] = None) -> None:
    if store is None:
        return
    stamp = day or today_kst()
    key = safe_key(name) or "unknown"
    try:
        store.bump_usage(stamp, KIND_TOOL, key)
        data = result if isinstance(result, dict) else {}
        payload = data.get("result") if isinstance(data.get("result"), dict) else {}
        verdict = payload.get("verdict") if isinstance(payload.get("verdict"), dict) else {}
        # 단건 판정 툴
        code = str(verdict.get("code") or "")
        if code in models.VERDICT_ORDER:
            store.bump_usage(stamp, KIND_VERDICT, code)
        # 후보 목록 툴: 등급별 건수를 그대로 더한다
        counts = payload.get("counts") if isinstance(payload, dict) else None
        if isinstance(counts, dict):
            for verdict_code, value in counts.items():
                if verdict_code in models.VERDICT_ORDER and int(value or 0) > 0:
                    store.bump_usage(stamp, KIND_VERDICT, verdict_code, int(value))
        if data.get("ok") is False:
            store.bump_usage(stamp, KIND_FLAG, FLAG_ERROR)
        elif _is_zero_result(key, data):
            store.bump_usage(stamp, KIND_FLAG, FLAG_ZERO)
            record_zero_query(store, args, data, stamp)
        meta = payload.get("catalog") if isinstance(payload, dict) else None
        if isinstance(meta, dict) and meta.get("catalog_state") == "sample":
            store.bump_usage(stamp, KIND_FLAG, FLAG_SAMPLE)
    except Exception:  # noqa: BLE001
        pass


def _empty_day(day: str) -> Dict[str, Any]:
    return {"date": day, "requests": 0, "paths": {}, "tools": {}, "verdicts": {}, "flags": {},
            "zero_result_queries": _empty_zero_queries()}


def _empty_zero_queries() -> Dict[str, Any]:
    return {"total": 0, "distinct": 0, "top": []}


def _top_zero_queries(buckets: Dict[tuple, int],
                       limit: int = TOP_ZERO_QUERIES) -> Dict[str, Any]:
    """`{(검색어, 트랙, 분야): 횟수}` → 빈도순 상위 `limit`건."""
    labels = _tag_labels()
    ordered = sorted(buckets.items(), key=lambda item: (-item[1], item[0][0]))[: max(1, limit)]
    rows = [{"query": query,
             "track": track,
             "field": tag or None,
             "field_label": labels.get(tag) if tag else None,
             "count": count}
            for (query, track, tag), count in ordered]
    return {"total": sum(buckets.values()), "distinct": len(buckets), "top": rows}


def stats_payload(store: Any, days: int = DEFAULT_DAYS,
                  today: Optional[str] = None) -> Dict[str, Any]:
    try:
        window = max(1, min(MAX_DAYS, int(days)))
    except (TypeError, ValueError):
        window = DEFAULT_DAYS
    end = today or today_kst()
    start = _shift(end, -(window - 1))
    empty = [_empty_day(_shift(start, offset)) for offset in range(window)]
    by_day = {row["date"]: row for row in empty}
    zero_by_day: Dict[str, Dict[tuple, int]] = {}
    zero_all: Dict[tuple, int] = {}

    if store is not None:
        try:
            rows = store.usage_rows(start, end)
        except Exception:  # noqa: BLE001
            rows = []
        for row in rows:
            target = by_day.get(str(row.get("day") or ""))
            if target is None:
                continue
            kind = str(row.get("kind") or "")
            count = int(row.get("count") or 0)
            if kind == KIND_ZERO_QUERY:
                entry = zero_entry(row.get("key"))
                if entry is None:
                    continue
                bucket = zero_by_day.setdefault(str(row.get("day") or ""), {})
                bucket[entry] = bucket.get(entry, 0) + count
                zero_all[entry] = zero_all.get(entry, 0) + count
                continue
            key = safe_key(row.get("key"))
            if kind == KIND_PATH:
                target["paths"][key] = count
                target["requests"] += count
            elif kind == KIND_TOOL:
                target["tools"][key] = count
            elif kind == KIND_VERDICT:
                target["verdicts"][key] = count
            elif kind == KIND_FLAG:
                target["flags"][key] = count

    for day, bucket in zero_by_day.items():
        by_day[day]["zero_result_queries"] = _top_zero_queries(bucket)

    totals: Dict[str, Any] = {"requests": 0, "paths": {}, "tools": {}, "verdicts": {}, "flags": {}}
    for row in empty:
        totals["requests"] += row["requests"]
        for kind in ("paths", "tools", "verdicts", "flags"):
            for key, value in row[kind].items():
                totals[kind][key] = totals[kind].get(key, 0) + value

    return {
        "ok": True,
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "timezone": "Asia/Seoul",
        "window_days": window,
        "from": start,
        "to": end,
        "privacy": {
            "stores_ip": False,
            "stores_user_agent": False,
            "stores_cookies": False,
            "stores_profile": False,
            "stores_identifiers": False,
            "stores_search_terms": "zero_result_only",
            "zero_result_queries": {
                "what_ko": "결과가 0건이었던 검색어만, 개인식별 요소를 지운 뒤 최대 30자로 남깁니다.",
                "removed_ko": ["전화번호", "주민등록번호", "이메일", "URL", "@핸들",
                               "2자리 이상 숫자(나이·연도)", "시·도·시·군·구 이름"],
                "kept_ko": ["검색어(지운 뒤 남은 말)", "트랙(개인/창업)", "분야 태그"],
                "results_are_not_stored": True,
                "max_chars": MAX_QUERY_CHARS,
                "top_per_day": TOP_ZERO_QUERIES,
                "limit_ko": ("사람 이름·상호는 낱말만으로 판별할 수 없어 지우지 못합니다. "
                             "입력란에는 제도·분야 낱말 예시를 안내합니다."),
            },
            "granularity": ("date (YYYY-MM-DD, Asia/Seoul) · 경로 · 툴 · 판정 등급 · 0건/오류 · "
                            "0건 검색어(비식별, 최대 30자)"),
            "inquiries": {
                "separate_from_usage": True,
                "in_this_payload": False,
                "what_ko": ("문의 카드에 직접 적어 보낸 연락처는 회신 목적으로만 별도 표에 두며 "
                            "이 통계에는 건수도 연락처도 넣지 않습니다."),
                "keep_days": INQUIRY_KEEP_DAYS,
            },
            "note_ko": (
                "거주지·나이·소득구간·임신 여부 같은 입력값은 저장하지 않습니다. 알 수 없는 경로는 "
                "/404 한 칸으로 합산하며, 재배포 시 카운터가 초기화될 수 있습니다. 검색어는 결과가 "
                "0건이었을 때만 지역명·연락처·숫자를 지운 형태로 남겨 다음 데이터 확충에 씁니다."
            ),
        },
        "days": empty,
        "zero_result_queries": _top_zero_queries(zero_all),
        "totals": totals,
    }
