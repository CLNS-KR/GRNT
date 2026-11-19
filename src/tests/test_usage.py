"""경로 카운터 키 계산 회귀 테스트 — 요청마다 25MB 카탈로그를 다시 읽던 502 원인.

`usage.record_request()` 는 모든 요청마다 `path_key()` 를 부르고, 그것이
`_known_paths()` → `pseo.slugs()` → `load_catalog()` 로 이어져 요청마다 카탈로그를
다시 파싱했습니다(Render 무료 0.1 vCPU 에서 15~30초 → 502). 경로 집합은 프로세스
수명 동안 바뀌지 않으므로 1회만 계산해 캐시해야 합니다.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from subsidy_kr import usage  # noqa: E402


class KnownPathsCacheTest(unittest.TestCase):
    def test_known_paths_is_cached_frozenset(self):
        first = usage._known_paths()
        self.assertIsInstance(first, frozenset, "frozenset 이어야 캐시해도 안전하다")
        self.assertIn("/healthz", first)
        before = usage._known_paths.cache_info()
        second = usage._known_paths()
        after = usage._known_paths.cache_info()
        self.assertIs(first, second, "두 번째 호출은 같은 객체를 돌려줘야 한다(재계산 없음)")
        self.assertEqual(after.misses, before.misses, "캐시된 뒤에는 다시 계산하지 않는다")
        self.assertEqual(after.hits, before.hits + 1)
        self.assertEqual(after.maxsize, 1)

    def test_path_key_still_maps_known_and_unknown(self):
        self.assertEqual(usage.path_key("/healthz"), "/healthz")
        self.assertEqual(usage.path_key("/healthz/"), "/healthz")
        self.assertEqual(usage.path_key("/mcp?x=1"), "/mcp")
        self.assertEqual(usage.path_key("/not-a-page"), "/404")
        self.assertEqual(usage.path_key("no-slash"), "/404")

    def test_server_warms_the_cache_at_startup(self):
        """serve() 가 시작 시 1회 계산해 첫 요청이 카탈로그를 다시 읽지 않게 한다."""
        with open(os.path.join(SRC, "subsidy_kr", "server.py"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("usage._known_paths()", text)


if __name__ == "__main__":
    unittest.main()
