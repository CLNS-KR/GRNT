"""(0.4.3) 경량 조회 회귀 테스트 — 메모리·속도 수정이 판정을 바꾸지 않았는지 확인한다.

배경(Pilotage 검수 리포트 재검증)
---------------------------------
- `POOL_CACHE_MAX` 가 목록 **개수**만 제한해, 지역·키워드를 바꿔 13~20회 검색하면 Service
  객체가 3.6만 개 넘게 쌓여 Render 512MB 를 넘겼습니다(OOM).
- `/healthz` 가 `len(catalog.services)` 로 매번 SQLite 13,130행을 메모리에 올렸습니다(10~14초).
- `pseo_items` 가 Service 객체 목록 전체를 붙들어 118~171MB 가 상주했습니다.
- 프로필 없는 검색이 후보 1.2만 건을 전부 판정해 28초가 걸렸습니다.

이 파일은 그 수정들이 **같은 결과**를 내는지(정렬·건수·줄 내용) 확인합니다.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from subsidy_kr import engine, models, pseo  # noqa: E402
from subsidy_kr.catalog import Catalog, load_catalog, normalize_service, sample_catalog  # noqa: E402
from subsidy_kr.catalog import browse_sort_key  # noqa: E402
from subsidy_kr.sample_data import services as sample_services  # noqa: E402
from subsidy_kr.sqlite_store import SQLiteCatalog, build_sqlite_from_rows  # noqa: E402

CATALOG = os.path.join(PROJECT, "data", "gov24", "catalog.json")
HAS_DATA = os.path.exists(CATALOG) or os.path.exists(CATALOG + ".gz")
EMPTY = engine.normalize_profile({})


def reference_search(catalog, profile, *, limit=20, include_ineligible=False,
                     include_closed=False, max_scan=20000, verdict=None):
    """경량 경로를 쓰지 않았을 때의 계산 — 후보를 전부 판정해 줄을 세운다."""
    region = profile["region"]
    pool = catalog.services[:max_scan]
    if region.get("level") in ("sido", "sigungu"):
        pool = catalog.by_region(region.get("sido"), region.get("sigungu"))[:max_scan]
    if not (profile.get("business") or {}).get("declared"):
        pool = [svc for svc in pool if not svc.is_business]
    if not include_closed:
        pool = [svc for svc in pool if not svc.is_expired]
    rows = [engine.evaluate_service(svc, profile) for svc in pool]
    if not include_ineligible:
        rows = [row for row in rows if row["verdict"]["code"] != models.VERDICT_INELIGIBLE]
    rows.sort(key=engine._sort_key)
    counts = {code: 0 for code in models.VERDICT_ORDER}
    for row in [engine.evaluate_service(svc, profile) for svc in pool]:
        counts[row["verdict"]["code"]] += 1
    shown_counts = {code: 0 for code in models.VERDICT_ORDER}
    kind_counts = {"grant": 0, "program": 0}
    kind_verdict_counts = {kind: {code: 0 for code in models.VERDICT_ORDER}
                           for kind in ("grant", "program")}
    for row in rows:
        code = row["verdict"]["code"]
        kind = "program" if row.get("benefit_kind") == "program" else "grant"
        shown_counts[code] += 1
        kind_counts[kind] += 1
        kind_verdict_counts[kind][code] += 1
    filtered = rows if not verdict else [row for row in rows
                                         if row["verdict"]["code"] == verdict]
    return {
        "counts": counts,
        "shown_counts": shown_counts,
        "kind_counts": kind_counts,
        "kind_verdict_counts": kind_verdict_counts,
        "scanned": len(pool),
        "matched_total": len(filtered),
        "truncated": len(filtered) > max(1, limit),
    }


class SampleCatalogFastPathTest(unittest.TestCase):
    """샘플 카탈로그에서 경량 경로가 기준 계산과 완전히 같은지."""

    def setUp(self):
        self.catalog = sample_catalog()

    def test_empty_profile_browse_matches_full_evaluation(self):
        expected = reference_search(self.catalog, EMPTY)
        result = engine.search(self.catalog, EMPTY)
        for key, value in expected.items():
            self.assertEqual(result[key], value, key)

    def test_browse_is_used_only_when_the_conditions_are_empty(self):
        self.assertTrue(engine._browse_ready(self.catalog, EMPTY, tag=None, keyword=None))
        self.assertFalse(engine._browse_ready(self.catalog, EMPTY, tag="housing", keyword=None))
        self.assertFalse(engine._browse_ready(self.catalog, EMPTY, tag=None, keyword="월세"))
        # 상한을 크게 부르면(대량 export) 전부 판정하는 길로 간다.
        self.assertFalse(engine._browse_ready(self.catalog, EMPTY, tag=None, keyword=None,
                                             limit=engine.BROWSE_MAX_LIMIT + 1))
        business = engine.normalize_profile({"track": "business"})
        self.assertFalse(engine._browse_ready(self.catalog, business, tag=None, keyword=None))
        aged = engine.normalize_profile({"age": 34})
        self.assertFalse(engine._browse_ready(self.catalog, aged, tag=None, keyword=None))

    def test_browse_key_matches_engine_sort_key(self):
        """`browse_sort_key` 는 `engine._sort_key` 의 뒤쪽 다섯 값과 같아야 한다."""
        for svc in self.catalog.iter_services():
            row = engine.evaluate_service(svc, EMPTY)
            self.assertEqual(browse_sort_key(svc), engine._sort_key(row)[1:], svc.name)


class BrowsePoolContractTest(unittest.TestCase):
    """메모리 카탈로그와 SQLite 카탈로그가 같은 집계·순서를 내는지."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        rows = sample_services()
        meta = {"generated_on": "2026-11-21T00:00:00+09:00", "data_state": "live_sync"}
        path = os.path.join(self.tmp, "catalog.sqlite")
        build_sqlite_from_rows(rows, meta, path)
        self.sqlite = SQLiteCatalog(path)
        self.memory = Catalog([normalize_service(row) for row in rows], meta)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_same_counts_and_order(self):
        for kwargs in ({}, {"per_kind": 3}, {"include_closed": True}):
            with self.subTest(**kwargs):
                fast = self.sqlite.browse_pool(track="personal", per_kind=kwargs.get("per_kind", 20),
                                               include_closed=kwargs.get("include_closed", False))
                slow = self.memory.browse_pool(track="personal",
                                               per_kind=kwargs.get("per_kind", 20),
                                               include_closed=kwargs.get("include_closed", False))
                self.assertEqual(fast["total"], slow["total"])
                self.assertEqual(fast["by_kind"], slow["by_kind"])
                for kind in ("grant", "program"):
                    self.assertEqual([svc.service_id for svc in fast["services"][kind]],
                                     [svc.service_id for svc in slow["services"][kind]], kind)

    def test_deadline_between_matches_manual_scan(self):
        today = date.today()
        until = today + timedelta(days=30)
        for kwargs in ({}, {"track": "personal"}, {"sido": "인천광역시"}):
            with self.subTest(**kwargs):
                light = self.sqlite.deadline_between(
                    start=today, until=until, track=kwargs.get("track", "all"),
                    sido=kwargs.get("sido"))
                rows = self.memory.deadline_between(
                    start=today, until=until, track=kwargs.get("track", "all"),
                    sido=kwargs.get("sido"))
                self.assertEqual(light["total"], rows["total"])
                self.assertEqual(light["unscheduled"], rows["unscheduled"])
                self.assertEqual(light["expired"], rows["expired"])
                self.assertEqual({svc.service_id for svc in light["services"]},
                                 {svc.service_id for svc in rows["services"]})

    def test_get_many_keeps_request_order(self):
        ids = [svc.service_id for svc in self.sqlite.browse_pool(per_kind=3)["services"]["grant"]]
        ids = list(reversed(ids))
        self.assertEqual([svc.service_id for svc in self.sqlite.get_many(ids)], ids)
        self.assertEqual(self.sqlite.get_many(["없는-id"]), [])

    def test_len_does_not_materialise_services(self):
        self.assertEqual(len(self.sqlite), len(sample_services()))
        self.assertEqual(self.sqlite.stats()["services"], len(self.sqlite))


class PoolCacheBudgetTest(unittest.TestCase):
    """후보 목록 캐시는 **객체 수**로 메모리를 묶는다(예전 OOM 원인)."""

    def _pool(self, size):
        return [object() for _ in range(size)]

    def test_item_budget_evicts_oldest(self):
        cache = engine._PoolCache(max_entries=8, max_items=100)
        cache.put(("a",), self._pool(60))
        cache.put(("b",), self._pool(30))
        self.assertEqual(cache.items, 90)
        cache.put(("c",), self._pool(30))   # 120 → 가장 오래된 a 부터 축출
        self.assertLessEqual(cache.items, 100)
        self.assertIsNone(cache.get(("a",)))
        self.assertIsNotNone(cache.get(("c",)))

    def test_pool_larger_than_budget_is_not_kept(self):
        cache = engine._PoolCache(max_entries=8, max_items=50)
        cache.put(("big",), self._pool(51))
        self.assertIsNone(cache.get(("big",)))
        self.assertEqual(cache.items, 0)

    def test_entry_limit_still_applies(self):
        cache = engine._PoolCache(max_entries=2, max_items=1000)
        for key in ("a", "b", "c"):
            cache.put((key,), self._pool(1))
        self.assertEqual(len(cache._entries), 2)

    def test_catalog_uses_the_bounded_cache(self):
        catalog = sample_catalog()
        engine._candidate_pool(catalog, EMPTY, max_scan=20000, tag=None, keyword=None,
                              include_closed=False)
        self.assertIsInstance(catalog.memo.get("pools"), engine._PoolCache)


class HealthzAndPseoMemoryTest(unittest.TestCase):
    def test_healthz_services_comes_from_stats(self):
        """`/healthz` 는 전체 목록을 만들지 않는다 — 실제 서버로 확인한다."""
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        from subsidy_kr.server import make_handler
        from subsidy_kr.store import Store

        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "catalog.sqlite")
            build_sqlite_from_rows(sample_services(), {"catalog_state": "synced"}, path)

            class Strict(SQLiteCatalog):
                @property
                def services(self):   # pragma: no cover - 불리면 실패
                    raise AssertionError("전체 목록(catalog.services)을 읽었습니다")

            catalog = Strict(path)
            store = Store(":memory:")
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(catalog, store))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                url = f"http://127.0.0.1:{httpd.server_address[1]}/healthz"
                with urllib.request.urlopen(url, timeout=5) as response:
                    payload = json.loads(response.read())
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.close()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["services"], len(sample_services()))
            self.assertEqual(payload["catalog_state"], "synced")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pseo_items_hold_ids_not_services(self):
        catalog = sample_catalog()
        stored = tuple(pseo._build_items(catalog))
        for page in stored:
            self.assertNotIn("services", page)
            self.assertEqual(page["count"], len(page["service_ids"]))
        catalog.memo["pseo_items"] = stored
        html = pseo.render_item(stored[0]["slug"], catalog)
        self.assertIn(stored[0]["title"], html)


class RateLimiterTest(unittest.TestCase):
    def test_blocks_after_limit_and_recovers(self):
        from subsidy_kr.server import _RateLimiter

        limiter = _RateLimiter(3)
        self.assertEqual([limiter.check("ip") for _ in range(3)], [0.0, 0.0, 0.0])
        wait = limiter.check("ip")
        self.assertGreater(wait, 0)
        self.assertGreater(wait, 0)
        # 61초 뒤에는 다시 통과한다(슬라이딩 윈도)
        now = 1e9 + 61
        self.assertEqual(limiter.check("ip", now=now), 0.0)

    def test_zero_limit_disables_the_limiter(self):
        from subsidy_kr.server import _RateLimiter

        limiter = _RateLimiter(0)
        for _ in range(50):
            self.assertEqual(limiter.check("ip"), 0.0)

    def test_keys_are_bounded(self):
        from subsidy_kr.server import RATE_LIMIT_KEYS_MAX, _RateLimiter

        limiter = _RateLimiter(5)
        for index in range(RATE_LIMIT_KEYS_MAX + 10):
            limiter.check(f"ip-{index}")
        self.assertLessEqual(len(limiter._hits), RATE_LIMIT_KEYS_MAX)


class HttpGuardTest(unittest.TestCase):
    """동시 처리·요청 빈도 상한 — 넘치면 429/503, 헬스체크는 통과."""

    def setUp(self):
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer

        from subsidy_kr.server import make_handler
        from subsidy_kr.store import Store

        self.urllib_error = urllib.error
        self.urllib_request = urllib.request
        self.store = Store(":memory:")
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(sample_catalog(), self.store, max_concurrency=2,
                         rate_limit=3, rate_limit_heavy=2))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.close()

    def _get(self, path, headers=None):
        request = self.urllib_request.Request(
            f"http://127.0.0.1:{self.port}{path}", headers=headers or {})
        try:
            with self.urllib_request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except self.urllib_error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def test_page_limit_returns_429_with_retry_after(self):
        for _ in range(3):
            self.assertEqual(self._get("/s/")[0], 200)
        status, headers, body = self._get("/s/")
        self.assertEqual(status, 429)
        self.assertTrue(headers.get("Retry-After"))
        self.assertEqual(json.loads(body)["error"], "rate_limited")

    def test_healthz_is_not_rate_limited(self):
        for _ in range(10):
            self.assertEqual(self._get("/healthz")[0], 200)

    def test_limits_are_per_client_ip(self):
        for _ in range(4):
            self._get("/s/")
        status, _headers, _body = self._get("/s/", {"X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(status, 200)


class InquiryMirrorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sink = os.path.join(self.tmp, "inquiries.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sink_file_keeps_one_json_line(self):
        from subsidy_kr import api
        from subsidy_kr.store import Store

        store = Store(":memory:")
        try:
            os.environ["GRNT_INQUIRY_SINK"] = self.sink
            result = api.submit_inquiry({"contact": "테스트연락처", "topic": "batch_report",
                                         "message": "문의"}, store, day="2026-11-21")
        finally:
            os.environ.pop("GRNT_INQUIRY_SINK", None)
        self.assertTrue(result["stored"])
        self.assertTrue(result["persistence"]["mirrored_to_file"])
        with open(self.sink, "r", encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["receipt"], result["receipt"])
        self.assertEqual(lines[0]["topic"], "batch_report")
        # 응답에는 연락처를 되돌려 쓰지 않는다(개인정보 재노출 금지)
        self.assertNotIn("테스트연락처", json.dumps(result, ensure_ascii=False))
        store.close()

    def test_bad_sink_path_does_not_break_the_response(self):
        from subsidy_kr import api
        from subsidy_kr.store import Store

        store = Store(":memory:")
        try:
            os.environ["GRNT_INQUIRY_SINK"] = "/proc/nope/inquiries.jsonl"
            result = api.submit_inquiry({"contact": "테스트연락처", "topic": "other"}, store)
        finally:
            os.environ.pop("GRNT_INQUIRY_SINK", None)
        self.assertTrue(result["ok"])
        self.assertFalse(result["persistence"]["mirrored_to_file"])
        store.close()


@unittest.skipUnless(HAS_DATA, "동기화 산출물이 없어 건너뜁니다")
class LiveCatalogLightweightTest(unittest.TestCase):
    """실데이터(1.3만 건)에서 경량 조회가 기준 계산과 같은지."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(CATALOG)

    def test_empty_profile_browse_matches_full_evaluation(self):
        engine.search(self.catalog, EMPTY, limit=200)      # 경량 경로로 캐시를 채운다
        expected = reference_search(self.catalog, EMPTY, limit=200)
        engine.search(self.catalog, EMPTY, limit=201)      # 다른 키 → 계산
        fast = engine.search(self.catalog, EMPTY, limit=200)
        for key, value in expected.items():
            self.assertEqual(fast[key], value, key)
        self.assertTrue(all(row["verdict"]["code"] == models.VERDICT_INSUFFICIENT
                            for row in fast["results"]))

    def test_deadline_between_matches_full_scan(self):
        today = date.today()
        until = today + timedelta(days=30)
        light = self.catalog.deadline_between(start=today, until=until)
        services = self.catalog.services
        unscheduled = expired = 0
        found = set()
        for svc in services:
            end = (svc.deadline or {}).get("end_date")
            if not end:
                unscheduled += 1
                continue
            try:
                end_date = date.fromisoformat(str(end))
            except ValueError:
                unscheduled += 1
                continue
            if end_date < today:
                expired += 1
                continue
            if end_date > until:
                continue
            found.add(svc.service_id)
        self.assertEqual(light["unscheduled"], unscheduled)
        self.assertEqual(light["expired"], expired)
        self.assertEqual(light["total"], len(services))
        self.assertEqual({svc.service_id for svc in light["services"]}, found)

    def test_pseo_items_do_not_keep_the_catalog(self):
        pages = pseo.items(self.catalog)
        self.assertGreater(len(pages), 30)
        for page in pages:
            self.assertNotIn("services", page)
        html = pseo.render_item(pages[0]["slug"], self.catalog)
        self.assertIsNotNone(html)
        self.assertEqual(html.count("<h1"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
