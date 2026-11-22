"""공고 원문에 들어 있는 담당자 이메일을 **내보내는 자리에서만** 가린다.

왜 원문을 고치지 않는가
------------------------
`catalog.json.gz`·SQLite 색인·일자별 스냅샷은 공공데이터 원문 그대로다.
여기서 글자를 지우면

- 판정 지문(`Service.fingerprint`)이 바뀌어 스냅샷 비교가 하루치 거짓 변경을 만들고,
- 다시 동기화할 때마다 원문과 산출물이 어긋나고,
- 검색·매칭에 쓰는 본문이 사용자마다 달라진다.

그래서 화면(HTML)·JSON·MCP 응답·CSV 리포트처럼 **사람과 크롤러가 읽는 출력**을 만드는
경계에서 `mask_emails` 를 부른다. 기관·도메인·출처 링크는 그대로 두고 로컬파트만 줄인다.

마스킹 규칙
-----------
- 로컬파트 3글자 이상 → 앞 2글자만 남기고 `***`
  (`honggildong` → `ho***`, 도메인은 손대지 않는다)
- 로컬파트 1~2글자 → 남기지 않고 `*` 만
  (`ab` → `*`, `a` → `*`)
- 도메인은 그대로 둔다 — 어느 기관인지·원문 링크가 어디인지 확인할 수 있어야 한다.
- 이미 마스킹된 주소(`ho***@…`)는 다시 걸리지 않는다(멱등).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Iterator, List, Tuple

MASK = "***"
SHORT_MASK = "*"
KEEP_LOCAL_CHARS = 2

# 로컬파트: 영문·숫자·._%+- / 도메인: 점으로 이어진 라벨(마지막 라벨 2글자 이상).
# 앞뒤가 같은 문자류면 잡지 않는다(문장 속 단어 일부를 이메일로 오인하지 않게).
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+\-])"
    r"([A-Za-z0-9._%+\-]{1,64})"
    r"@"
    r"([A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*"
    r"\.[A-Za-z]{2,24})"
    r"(?![A-Za-z0-9\-])"
)


def mask_email(address: str) -> str:
    """`local@domain` 한 개 → 로컬파트만 가린 주소."""
    local, _, domain = str(address).rpartition("@")
    if not local or not domain:
        return str(address)
    if len(local) <= KEEP_LOCAL_CHARS:
        hidden = SHORT_MASK
    else:
        hidden = local[:KEEP_LOCAL_CHARS] + MASK
    return f"{hidden}@{domain}"


def _replace(match: "re.Match[str]") -> str:
    return mask_email(match.group(0))


def mask_emails(text: Any) -> Any:
    """문자열 안의 이메일을 전부 가린다. 문자열이 아니면 그대로 돌려준다."""
    if not isinstance(text, str) or "@" not in text:
        return text
    return EMAIL_RE.sub(_replace, text)


def mask_object(value: Any) -> Any:
    """dict·list·tuple 안의 문자열까지 재귀적으로 가린 값(원본은 건드리지 않는다)."""
    if isinstance(value, str):
        return mask_emails(value)
    if isinstance(value, dict):
        return {key: mask_object(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_object(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_object(item) for item in value)
    return value


def mask_fields(record: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    """레코드에서 지정한 문자열 필드만 제자리에서 가린다(레코드를 그대로 돌려준다)."""
    for key in keys:
        if isinstance(record.get(key), str):
            record[key] = mask_emails(record[key])
    return record


def find_emails(text: Any) -> List[str]:
    """테스트·점검용 — 문자열에서 (아직 가려지지 않은) 이메일을 찾는다."""
    if not isinstance(text, str) or "@" not in text:
        return []
    return [match.group(0) for match in EMAIL_RE.finditer(text)]


def iter_unmasked(value: Any, path: str = "") -> Iterator[Tuple[str, str]]:
    """구조 전체를 훑어 아직 안 가려진 이메일을 `(경로, 주소)` 로 낸다(검증용)."""
    if isinstance(value, str):
        for address in find_emails(value):
            yield path, address
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from iter_unmasked(item, f"{path}.{key}" if path else str(key))
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from iter_unmasked(item, f"{path}[{index}]")
