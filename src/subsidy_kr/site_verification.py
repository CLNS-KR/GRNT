"""검색엔진 소유확인(구글 서치콘솔·네이버 서치어드바이저) 지원.

두 기관 모두 "메타태그를 첫 페이지 head 에 넣기" 또는 "루트에 HTML 확인 파일 올리기"
둘 중 하나로 소유를 확인한다. 이 모듈은 **환경변수만으로** 그 두 가지를 모두 열어 준다.
코드 수정 없이 Render 대시보드에서 값을 넣고 재시작하면 바로 확인이 끝난다.

환경변수
--------
- `GOOGLE_SITE_VERIFICATION`  → `<meta name="google-site-verification" content="...">`
- `NAVER_SITE_VERIFICATION`   → `<meta name="naver-site-verification" content="...">`
- `SITE_VERIFICATION_FILES`   → JSON. 예:
  `{"google1a2b3c.html": "google-site-verification: google1a2b3c.html",
    "naver1a2b3cd.html": "naver-site-verification: naver1a2b3cd.html"}`

원칙
----
1. 익명: 확인 토큰은 검색엔진이 발급한 값 그대로이고, 사람 이름·이메일을 받지 않는다.
2. 값은 화이트리스트 문자만 남겨 새니타이즈한다(HTML 주입·경로 이탈 차단).
3. 환경변수가 없으면 아무 것도 내보내지 않는다(기존 응답과 완전히 동일).
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Optional

ENV_GOOGLE = "GOOGLE_SITE_VERIFICATION"
ENV_NAVER = "NAVER_SITE_VERIFICATION"
ENV_FILES = "SITE_VERIFICATION_FILES"

# (meta name, 환경변수) — 순서대로 출력된다.
META_NAMES = (
    ("google-site-verification", ENV_GOOGLE),
    ("naver-site-verification", ENV_NAVER),
)

# 토큰에 실제로 쓰이는 문자만 허용한다(영숫자·점·하이픈·밑줄·콜론).
_TOKEN_UNSAFE = re.compile(r"[^0-9A-Za-z._:-]")
_FILE_NAME_RE = re.compile(r"^[0-9A-Za-z._-]{1,120}\.html$")
_FILE_BODY_UNSAFE = re.compile(r"[^0-9A-Za-z._:\- \n]")
MAX_TOKEN = 200
MAX_FILE_BODY = 200


def _token(raw: Optional[str]) -> str:
    return _TOKEN_UNSAFE.sub("", (raw or "").strip())[:MAX_TOKEN]


def meta_tags() -> str:
    """`<head>` 에 넣을 소유확인 메타태그 블록. 없으면 빈 문자열."""
    tags = []
    for name, env in META_NAMES:
        value = _token(os.environ.get(env))
        if value:
            tags.append(f'<meta name="{name}" content="{value}">')
    return "\n".join(tags) + "\n" if tags else ""


def files() -> Dict[str, str]:
    """루트에 서빙할 확인 파일들 — `{'/name.html': '본문'}`. 잘못된 항목은 조용히 버린다."""
    raw = (os.environ.get(ENV_FILES) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: Dict[str, str] = {}
    for name, body in parsed.items():
        if not isinstance(name, str) or not isinstance(body, str):
            continue
        clean = name.strip().lstrip("/")
        if not _FILE_NAME_RE.match(clean):
            continue
        safe_body = _FILE_BODY_UNSAFE.sub("", body.strip())[:MAX_FILE_BODY]
        if not safe_body:
            continue
        out["/" + clean] = safe_body
    return out


def file_body(path: str) -> Optional[str]:
    """요청 경로에 대응하는 확인 파일 본문. 없으면 None."""
    return files().get(path)
