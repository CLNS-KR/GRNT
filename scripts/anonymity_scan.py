"""익명성ㆍ시크릿 스캔 — 푸시 전에 "이 저장소에 개인 흔적이 섞였는가"를 0건으로 만든다.

무엇을 보는가
-------------
1. **개인 식별 정보** — 휴대전화 번호, 개인 메일 주소, 주민등록번호 모양 문자열,
   운영체제 사용자 경로(`/Users/…`, `/home/…`).
2. **신원을 드러내는 말** — 실명 조각ㆍ직업명ㆍ개인 계정 핸들. 이 목록은 스크립트 자체에
   그대로 남지 않도록 코드포인트로 조립해 두었고, 저장소 밖 `.private-terms` 파일이 있으면
   그 목록을 더합니다(줄 단위, `#` 주석 허용).
3. **비밀값** — GitHub 토큰, OpenAIㆍGoogle API 키, 개인키 블록, `password=` 류 대입.

오탐을 줄이는 규칙
-----------------
이 저장소에는 법령 API 주소(`law.go.kr/...?admRulSeq=2100000269780`)처럼 **13자리 숫자가
들어간 공개 URL**과, 마스킹 동작을 시험하려고 둔 **자리표시자 번호**(국번 뒤가 모두 0 인 번호)가
많습니다. 이걸 개인정보로 세면 진짜 발견이 묻히므로 다음을 구분합니다.

- URL 안의 숫자·주소는 개인정보가 아니다(참조 링크).
- 휴대전화는 국번 뒤가 모두 0 이거나 `0000` 으로 시작하면 자리표시자다.
- 주민등록번호는 생년월일(월 1~12ㆍ일 1~31)ㆍ성별 자리(1~8)ㆍ검증 숫자가 맞아야 한다.
  아무 13자리 숫자나 주민등록번호로 세지 않는다.
- 메일 주소는 예약된 시험용 도메인(`.test`ㆍ`.invalid`ㆍexample.com 등)을 통과시킨다.

쓰는 법
-------
    python scripts/anonymity_scan.py            # 저장소 전체 검사(CI 와 같은 범위)
    python scripts/anonymity_scan.py src tests  # 특정 경로만

종료 코드는 발견 0건이면 0, 하나라도 있으면 1 입니다. 발견 내용은 값을 마스킹해 출력하므로
로그에 원문이 남지 않습니다.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent

# 검사 대상 확장자ㆍ파일명(바이너리ㆍDBㆍ캐시는 건너뛴다).
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".csv", ".toml", ".cfg",
                 ".ini", ".example", ".html", ".css", ".js", ".sh", ".dockerfile", ""}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "data", "out",
             "node_modules", ".mypy_cache"}
SKIP_FILES = {".env", "anonymity_scan.py"}

# 실명 조각ㆍ직업명ㆍ개인 핸들 — 스크립트에 그대로 적지 않으려고 코드포인트로 조립한다.
IDENTITY_TERMS: Tuple[str, ...] = (
    "\ubbfc\uc11d",           # 성명 조각
    "\uc870\uc885\uc0ac",        # 직업명
    "B7" + "37",
    "pil" + "otage",
)

EMAIL_ALLOW_LIST = ("example.com", "example.org", "example.net", "example.test",
                    "users.noreply.github.com", "localhost", "clns-kr", ".test",
                    ".invalid", ".example", ".localhost")

PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("휴대전화 번호", re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}")),
    ("주민등록번호 모양", re.compile(r"\b\d{6}[-.\s]?\d{7}\b")),
    ("개인 메일 주소", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("로컬 사용자 경로", re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/")),
    ("GitHub 토큰", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("OpenAIㆍGoogle 키", re.compile(r"\bsk-[A-Za-z0-9]{20,}|\bAIza[0-9A-Za-z_-]{20,}")),
    ("개인키 블록", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("비밀번호 대입", re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key)\s*=\s*['\"][^'\"\s]{6,}['\"]")),
)

_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")
_RRN_WEIGHTS = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)


def _mask(value: str) -> str:
    text = value.strip()
    if len(text) <= 2:
        return "*" * len(text)
    keep = min(2, len(text) // 4)
    return text[:keep] + "*" * max(1, len(text) - keep * 2) + text[-keep:]


def _url_spans(line: str, offset: int = 0) -> List[Tuple[int, int]]:
    return [(match.start() + offset, match.end() + offset) for match in _URL_RE.finditer(line)]


def _inside(spans: List[Tuple[int, int]], start: int, end: int) -> bool:
    return any(left <= start and end <= right for left, right in spans)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _looks_like_placeholder_phone(value: str) -> bool:
    """국번 뒤가 모두 0 인 자리표시자(마스킹 시험용) 번호인가."""
    digits = _digits(value)
    if not digits:
        return False
    body = digits[3:]
    if not body:
        return True
    if set(body) <= {"0"}:
        return True
    # 국번 뒤 첫 네 자리가 0000 이면 실제 번호로 쓰이지 않는 자리표시자다.
    return body.startswith("0000")


def _looks_like_rrn(value: str) -> bool:
    """생년월일ㆍ성별 자리ㆍ검증 숫자가 맞는 주민등록번호 모양인가.

    법령 API 주소에 들어간 13자리 숫자나 13자리 품목보고번호는 월이 12를 넘거나
    검증 숫자가 맞지 않아 여기서 걸러진다. 진짜 주민등록번호는 그대로 잡힌다.
    """
    digits = _digits(value)
    if len(digits) != 13:
        return False
    month, day = int(digits[2:4]), int(digits[4:6])
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return False
    if digits[6] not in "12345678":
        return False
    total = sum(int(digit) * weight for digit, weight in zip(digits[:12], _RRN_WEIGHTS))
    return (11 - total % 11) % 10 == int(digits[12])


def _isolated(line: str, start: int, end: int) -> bool:
    """앞뒤가 숫자인 더 긴 숫자열의 일부가 아닌가(URL 경로 속 번호 방지)."""
    before = line[start - 1] if start > 0 else ""
    after = line[end] if end < len(line) else ""
    return not (before.isdigit() or after.isdigit())


def _iter_files(paths: Iterable[str]) -> Iterable[Path]:
    for raw in paths:
        target = (ROOT / raw).resolve()
        if target.is_file():
            yield target
            continue
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for filename in filenames:
                candidate = Path(dirpath) / filename
                if candidate.name in SKIP_FILES:
                    continue
                if candidate.suffix.lower() not in TEXT_SUFFIXES and candidate.name != "Dockerfile":
                    continue
                yield candidate


def _extra_terms() -> List[str]:
    terms: List[str] = []
    path = ROOT / ".private-terms"
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                terms.append(text)
    return terms


def _is_allowed(label: str, value: str, line: str, start: int, end: int,
                spans: List[Tuple[int, int]]) -> bool:
    """패턴에 걸렸지만 개인정보가 아닌 경우(URL 속 번호ㆍ자리표시자ㆍ시험용 도메인)."""
    if label == "개인 메일 주소":
        if any(ok in value for ok in EMAIL_ALLOW_LIST):
            return True
        return _inside(spans, start, end)
    if label == "휴대전화 번호":
        if _looks_like_placeholder_phone(value):
            return True
        if _inside(spans, start, end):
            return True
        return not _isolated(line, start, end)
    if label == "주민등록번호 모양":
        if _inside(spans, start, end):
            return True
        if not _isolated(line, start, end):
            return True
        return not _looks_like_rrn(value)
    if label == "비밀번호 대입":
        return any(token in value.lower() for token in ("<", "example", "your_", "xxx", "none"))
    return False


def scan(paths: Iterable[str]) -> List[str]:
    findings: List[str] = []
    identity = list(IDENTITY_TERMS) + _extra_terms()
    for path in sorted(_iter_files(paths)):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:  # 읽을 수 없는 파일은 조용히 넘긴다(권한ㆍ잠금)
            findings.append(f"{_rel(path)}: 읽지 못함({type(exc).__name__})")
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            for term in identity:
                if term and term.lower() in lowered:
                    findings.append(f"{_rel(path)}:{number}: 신원 노출 의심('{_mask(term)}')")
            spans = _url_spans(line)
            for label, pattern in PATTERNS:
                for match in pattern.finditer(line):
                    value = match.group(0)
                    if _is_allowed(label, value, line, match.start(), match.end(), spans):
                        continue
                    findings.append(f"{_rel(path)}:{number}: {label}('{_mask(value)}')")
    return findings


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv: List[str]) -> int:
    targets = argv or ["src", "tests", "samples", "scripts", "README.md", "Dockerfile",
                       ".env.example", ".github", "requirements.txt", "requirements-postgres.txt"]
    findings = scan(targets)
    if findings:
        print(f"익명성ㆍ시크릿 스캔: {len(findings)}건 발견")
        for line in findings:
            print("  -", line)
        print("값은 마스킹했습니다. 원문을 지운 뒤 다시 실행하세요.")
        return 1
    print("익명성ㆍ시크릿 스캔: 0건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
