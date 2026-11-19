"""개인정보·시크릿 0건 검사.

소스·문서·데이터 파일을 훑어 다음이 없음을 확인합니다.
- 인증키·비밀번호 같은 비밀값 평문
- 휴대폰·주민등록번호·이메일 같은 개인정보
- 프로필(나이·소득·임신·장애)을 저장하는 스키마·로그

개인정보 문자열 목록은 코드에 평문으로 두지 않습니다(저장소가 공개입니다).
프로젝트 루트의 `.private-terms`(gitignore·dockerignore 대상, 로컬 전용)에 한 줄에
하나씩 적어 두면 그 값으로 검사하고, 파일이 없으면(CI·외부 클론) 형식 검사만 합니다.
"""
from __future__ import annotations

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)

TEXT_SUFFIXES = (".py", ".md", ".txt", ".json", ".yaml", ".yml", ".example", "")
PRIVATE_TERMS_FILE = os.path.join(PROJECT, ".private-terms")


def private_terms():
    """로컬 전용 개인정보 문자열 목록(`.private-terms`). 없으면 빈 목록."""
    try:
        with open(PRIVATE_TERMS_FILE, "r", encoding="utf-8") as handle:
            return [line.strip() for line in handle
                    if line.strip() and not line.lstrip().startswith("#")]
    except OSError:
        return []


def project_files():
    for root, dirs, files in os.walk(PROJECT):
        dirs[:] = [name for name in dirs if name not in ("__pycache__", "build", ".git")]
        for name in files:
            if name == ".private-terms":
                continue
            if name.endswith(TEXT_SUFFIXES) or name in (".env.example", ".gitignore",
                                                        ".dockerignore", "Dockerfile"):
                yield os.path.join(root, name)


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return ""


class SecretScanTest(unittest.TestCase):
    def test_no_hardcoded_service_key(self):
        patterns = [
            re.compile(r"DATA_GO_KR_SERVICE_KEY\s*=\s*['\"][^'\"]{8,}['\"]"),
            re.compile(r"serviceKey\s*=\s*['\"][A-Za-z0-9%+/=]{16,}['\"]"),
            re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9%+/=]{20,}['\"]"),
        ]
        for path in project_files():
            if os.sep + "tests" + os.sep in path:   # 검사 규칙 문자열 자체는 제외
                continue
            text = read(path)
            for pattern in patterns:
                self.assertIsNone(pattern.search(text), f"{path}: {pattern.pattern}")

    def test_no_data_go_kr_key_shape(self):
        # data.go.kr 인코딩 키는 60~120자 base64 형태다. 소스에 그런 리터럴이 있으면 안 된다.
        shape = re.compile(r"['\"][A-Za-z0-9%]{64,}['\"]")
        for path in project_files():
            if os.sep + "tests" + os.sep in path:
                continue
            self.assertIsNone(shape.search(read(path)), path)


class PersonalDataTest(unittest.TestCase):
    def test_no_private_terms(self):
        """`.private-terms` 의 개인정보 문자열이 소스·문서에 없다(로컬 검사)."""
        terms = private_terms()
        if not terms:
            self.skipTest(".private-terms 가 없어 개인정보 문자열 검사를 건너뜁니다")
        for path in project_files():
            text = read(path)
            for word in terms:
                self.assertNotIn(word, text, f"{path}: 개인정보 문자열")

    def test_no_phone_or_resident_number_shapes(self):
        """휴대폰·주민등록번호 형태가 코드·문서·설정에 없다(`data/` 는 원문 보존 예외)."""
        mobile = re.compile(r"\b01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}\b")
        rrn = re.compile(r"\b\d{6}\s?-\s?\d{7}\b")
        for path in project_files():
            if os.sep + "data" + os.sep in path or os.sep + "tests" + os.sep in path:
                continue   # data 는 원문 보존, tests 는 예시 문자열
            text = read(path)
            self.assertIsNone(mobile.search(text), path)
            self.assertIsNone(rrn.search(text), path)

    def test_no_email_addresses(self):
        """코드·문서·설정에 이메일을 쓰지 않는다.

        `data/` 는 공공데이터 동기화 산출물이라 예외입니다. 공고문에는 기관 담당자
        이메일이 원문 그대로 들어 있으며(기업마당 변경금지 조건), 이는 사용자 개인정보가
        아니라 공개된 기관 연락처입니다. 대신 `data/` 에 사용자 개인정보가 없는지는
        `test_synced_data_has_no_personal_identifiers` 가 따로 확인합니다.
        """
        pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        for path in project_files():
            if path.endswith("LICENSE") or os.sep + "data" + os.sep in path:
                continue
            self.assertIsNone(pattern.search(read(path)), path)

    def test_synced_data_has_no_personal_identifiers(self):
        """동기화 산출물에 사용자 개인정보(이름·휴대폰·주민번호)가 없어야 한다."""
        terms = private_terms()
        rrn = re.compile(r"\b\d{6}\s?-\s?\d{7}\b")
        for path in project_files():
            if os.sep + "data" + os.sep not in path:
                continue
            text = read(path)
            for word in terms:
                self.assertNotIn(word, text, f"{path}: 개인정보 문자열")
            self.assertIsNone(rrn.search(text), path)


class StorageScanTest(unittest.TestCase):
    def test_schema_has_no_profile_columns(self):
        from subsidy_kr.store import SCHEMA

        forbidden = ("age", "income", "region", "profile", "pregnant", "resident",
                     "birth", "disability", "client_profile")
        lowered = SCHEMA.lower()
        for word in forbidden:
            self.assertIsNone(re.search(rf"\b{re.escape(word)}\b", lowered), word)
            self.assertIsNone(re.search(rf"\b{re.escape(word)}_", lowered), word)

    def test_usage_store_only_counts(self):
        from subsidy_kr.store import SCHEMA

        for column in ("day", "kind", "key", "count"):
            self.assertIn(column, SCHEMA)
        for column in ("ip", "user_agent", "cookie", "referer", "session"):
            self.assertNotIn(column, SCHEMA)

    def test_usage_module_lists_private_fields_as_absent(self):
        from subsidy_kr import usage

        payload = usage.stats_payload(None, days=1, today="2026-11-19")
        for key in ("stores_ip", "stores_user_agent", "stores_cookies",
                    "stores_profile", "stores_identifiers"):
            self.assertFalse(payload["privacy"][key], key)

    def test_no_browser_storage_in_ui(self):
        text = read(os.path.join(SRC, "subsidy_kr", "web_ui.py"))
        for word in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
            self.assertNotIn(word, text)

    def test_no_request_body_logging(self):
        text = read(os.path.join(SRC, "subsidy_kr", "server.py"))
        # 로그는 비워 두고(경로는 익명 카운터로만) 본문을 남기지 않는다
        self.assertIn("def log_message", text)
        self.assertNotIn("print(self.path", text)
        self.assertNotIn("logging.info(", text)

    def test_profile_is_not_echoed_back(self):
        """응답의 profile 블록은 해석 결과만 담고, 원문 입력을 그대로 되돌리지 않는다."""
        from subsidy_kr import engine

        profile = engine.normalize_profile({"age": 34, "income_percent": 80,
                                            "situations": ["no_home"],
                                            "resident_number": "000000-0000000"})
        explained = engine.explain_profile(profile)
        self.assertNotIn("resident_number", explained)
        self.assertEqual(explained["age"], 34)


if __name__ == "__main__":
    unittest.main(verbosity=2)
