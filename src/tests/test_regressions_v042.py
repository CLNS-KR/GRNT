"""(0.4.2) 회귀 테스트 — 라이브 전수검수에서 나온 P0/P1 결함.

1. 2026-07-01 인천 행정체제 개편(제물포구·영종구·검단구)
2. 전남광주통합특별시 출범(16개 시·도)과 통합 전 슬러그 301
3. 결과 상한에 가려지던 판정 — 탭 숫자는 실집계, 판정별 재조회
4. 지자체·지역 재단 사업의 '전국' 오분류
5. `/s/` 제목의 옛 브랜드(SUBSIDY-KR) 제거
6. non-`/v1/` 404 의 사람용 HTML 안내
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from subsidy_kr import (engine, models, pseo, regions, sample_data,  # noqa: E402
                        static_files)
from subsidy_kr.api import call_tool  # noqa: E402
from subsidy_kr.catalog import load_catalog, sample_catalog  # noqa: E402
from subsidy_kr.server import make_handler  # noqa: E402
from subsidy_kr.sqlite_store import SQLiteCatalog, build_sqlite_from_rows  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 인천 2026-07-01 개편
# ---------------------------------------------------------------------------
class IncheonReorgTest(unittest.TestCase):
    NAMES = [name for _code, name in regions.SIGUNGU_BY_SIDO["인천광역시"]]

    def test_new_districts_are_offered(self):
        for name in ("제물포구", "영종구", "서해구", "검단구", "미추홀구", "연수구",
                     "남동구", "부평구", "계양구", "강화군", "옹진군"):
            self.assertIn(name, self.NAMES, name)
        self.assertEqual(len(self.NAMES), 11)

    def test_abolished_districts_are_gone(self):
        self.assertNotIn("중구", self.NAMES)
        self.assertNotIn("동구", self.NAMES)

    def test_old_names_still_resolve_for_old_data(self):
        # 개편 전 공고·묶은 데이터에는 중구·동구가 남아 있다 — 확인 필요로 흘리지 않는다.
        for old in ("중구", "동구"):
            self.assertEqual(regions.canonical_sigungu("인천광역시", old), "제물포구", old)
        self.assertEqual(regions.region_block("인천광역시", "중구")["sigungu"], "제물포구")
        self.assertEqual(regions.parse_agency_region("인천광역시 동구")["sigungu"], "제물포구")

    def test_geomdan_is_its_own_district(self):
        block = regions.region_block("인천광역시", "검단구")
        self.assertEqual((block["level"], block["sigungu"]), ("sigungu", "검단구"))
        user = regions.region_block("인천광역시", "검단구")
        seohae = {"level": "sigungu", "sido": "인천광역시", "sigungu": "서해구"}
        self.assertEqual(regions.match_region(user, seohae)["state"], "mismatch")
        self.assertEqual(regions.match_region(
            user, {"level": "sido", "sido": "인천광역시", "sigungu": ""})["state"], "match")

    def test_form_payload_has_new_districts(self):
        from subsidy_kr import web_ui
        payload = web_ui.region_payload()["인천광역시"]
        for name in ("제물포구", "영종구", "검단구"):
            self.assertIn(name, payload)


# ---------------------------------------------------------------------------
# 2. 전남광주통합특별시
# ---------------------------------------------------------------------------
class JeonnamGwangjuTest(unittest.TestCase):
    def test_sixteen_metro_governments(self):
        names = regions.sido_names()
        self.assertEqual(len(names), 16)
        self.assertIn("전남광주통합특별시", names)
        for gone in ("광주광역시", "전라남도"):
            self.assertNotIn(gone, names)

    def test_old_names_alias_to_merged_city(self):
        for raw in ("광주", "광주시", "광주광역시", "전남", "전라남도", "전남광주"):
            self.assertEqual(regions.canonical_sido(raw), "전남광주통합특별시", raw)

    def test_districts_cover_gwangju_and_jeonnam(self):
        rows = [name for _code, name in regions.SIGUNGU_BY_SIDO["전남광주통합특별시"]]
        self.assertEqual(len(rows), 27)          # 광주 5 + 전남 22
        self.assertEqual(regions.canonical_sigungu("전남광주통합특별시", "영암군"), "영암군")
        self.assertEqual(regions.canonical_sigungu("전남광주통합특별시", "동구"), "동구")
        self.assertEqual(regions.parse_agency_region("전남광주통합특별시 영암군")["sigungu"], "영암군")
        block = regions.parse_agency_region("전라남도 영암군")
        self.assertEqual((block["sido"], block["sigungu"]),
                         ("전남광주통합특별시", "영암군"))
        block = regions.parse_agency_region("광주광역시 북구")
        self.assertEqual((block["sido"], block["sigungu"]),
                         ("전남광주통합특별시", "북구"))

    def test_cross_district_still_mismatches(self):
        user = regions.region_block("전남광주통합특별시", "동구")
        service = {"level": "sigungu", "sido": "전남광주통합특별시", "sigungu": "영암군"}
        self.assertEqual(regions.match_region(user, service)["state"], "mismatch")
        self.assertEqual(regions.match_region(
            user, {"level": "sido", "sido": "전남광주통합특별시", "sigungu": ""})["state"], "match")

    def test_slug_and_legacy_redirects(self):
        self.assertEqual(regions.slug_for_sido("전남광주통합특별시"), "jeonnamgwangju")
        self.assertEqual(regions.LEGACY_SIDO_SLUGS,
                         {"gwangju": "jeonnamgwangju", "jeonnam": "jeonnamgwangju"})
        self.assertEqual(len(regions.hub_paths()), 17)     # 허브 1 + 시·도 16

    def test_region_hub_wording(self):
        page = regions.render_index(sample_catalog())
        self.assertIn("16개 시·도", page)
        self.assertNotIn("17개 시·도", page)


# ---------------------------------------------------------------------------
# 3. 결과 상한·집계
# ---------------------------------------------------------------------------
def _profile(**kwargs):
    base = {"track": "personal", "birth_year": 1992, "sex": "male", "household_size": 2,
            "income_band": "JA0203", "situations": ["no_home", "worker", "birth"],
            "region": {"sido": "인천광역시", "sigungu": "서해구"}}
    base.update(kwargs)
    return engine.normalize_profile(base)


class ResultCountTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.profile = _profile()

    def _search(self, **options):
        return engine.search(self.catalog, self.profile, **options)

    def test_kind_counts_are_totals_not_quota(self):
        small = self._search(limit=2, balance_kinds=True, balance_verdicts=True)
        big = self._search(limit=500)
        # 상한을 바꿔도 탭 숫자는 같다 — 반환 목록이 아니라 전체 집계이기 때문
        self.assertEqual(small["kind_counts"], big["kind_counts"])
        self.assertEqual(small["kind_verdict_counts"], big["kind_verdict_counts"])
        shown_total = big["scanned"] - big["counts"][models.VERDICT_INELIGIBLE]
        self.assertEqual(sum(big["kind_counts"].values()), shown_total)
        for kind, codes in big["kind_verdict_counts"].items():
            self.assertEqual(sum(codes.values()), big["kind_counts"][kind], kind)
        self.assertLessEqual(len(small["results"]), 2)
        self.assertGreater(sum(small["kind_counts"].values()), len(small["results"]))

    def test_truncation_is_reported_with_real_numbers(self):
        result = self._search(limit=3, balance_kinds=True, balance_verdicts=True)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["returned"], 3)
        self.assertGreater(result["matched_total"], 3)

    def test_verdict_filter_returns_whole_group(self):
        full = self._search(limit=500)
        target = models.VERDICT_CHECK
        if not full["shown_counts"][target]:
            self.skipTest("샘플에 '조건 확인 필요'가 없습니다")
        filtered = self._search(limit=500, verdict=target)
        self.assertEqual(filtered["verdict_filter"], target)
        self.assertEqual(filtered["matched_total"], full["shown_counts"][target])
        self.assertTrue(all(row["verdict"]["code"] == target for row in filtered["results"]))
        # 필터를 걸어도 탭 숫자는 전체 기준 그대로
        self.assertEqual(filtered["counts"], full["counts"])
        self.assertEqual(filtered["kind_counts"], full["kind_counts"])

    def test_balanced_slice_keeps_every_verdict_reachable(self):
        full = self._search(limit=500)
        present = [code for code in models.VERDICT_ORDER
                   if full["shown_counts"].get(code)]
        balanced = self._search(limit=max(4, len(present)), balance_verdicts=True)
        returned = {row["verdict"]["code"] for row in balanced["results"]}
        self.assertEqual(returned, set(present))

    def test_api_cap_is_two_hundred(self):
        result = call_tool("search_subsidies",
                           {"profile": {"age": 34, "income_band": "JA0203"},
                            "limit": 5000}, self.catalog)["result"]
        self.assertEqual(result["limit"], 200)
        self.assertIn("kind_counts", result)
        self.assertIn("kind_verdict_counts", result)
        for code in result["kind_verdict_counts"].values():
            self.assertEqual(set(code), set(models.VERDICT_ORDER))

    def test_unknown_verdict_is_rejected(self):
        result = call_tool("search_subsidies", {"profile": {}, "verdict": "maybe"},
                           self.catalog)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_argument")
        self.assertEqual(result["message"], "unknown_verdict")


# ---------------------------------------------------------------------------
# 4. 지자체 사업의 '전국' 오분류
# ---------------------------------------------------------------------------
class LocalAgencyNotNationalTest(unittest.TestCase):
    CASES = {
        "천안복지재단": "충청남도",
        "천안도시공사": "충청남도",
        "전주시복지재단전주사람": "전북특별자치도",
        "재단법인전주문화재단": "전북특별자치도",
        "재단법인안산인재육성재단": "경기도",
        "안산도시공사": "경기도",
        "고양문화재단": "경기도",
        "고양도시관리공사": "경기도",
        "재단법인수원문화재단": "경기도",
        "재단법인성남시장학회": "경기도",
        "청주도시공사": "충청북도",
        "재단법인경상북도인재평생교육재단": "경상북도",
        "(재)충청북도문화재연구원": "충청북도",
        "재단법인광주문화재단": "전남광주통합특별시",
        "포항연합기술지주": "경상북도",
    }

    def test_regional_agencies_are_not_national(self):
        for agency, sido in self.CASES.items():
            block = regions.parse_agency_region(agency)
            self.assertNotEqual(block["level"], "national", agency)
            self.assertEqual(block["sido"], sido, agency)

    def test_unresolvable_local_agency_is_not_national(self):
        # 고성군은 강원·경남에 같은 이름이 있다 — 찍지 않고 확인 필요로 남긴다.
        block = regions.parse_agency_region("재단법인고성교육재단")
        self.assertEqual(block["level"], "local_unresolved")

    def test_true_national_agencies_stay_national(self):
        for agency in ("중소벤처기업부", "국세청", "한국장학재단", "대한법률구조공단",
                       "한국전력공사", "신용보증기금", "근로복지공단", "국민건강보험공단",
                       "한국농어촌공사", "한국도로공사", "한국언론진흥재단", "창업진흥원"):
            self.assertEqual(regions.parse_agency_region(agency)["level"], "national", agency)

    def test_city_level_foundation_does_not_leak_to_other_regions(self):
        region = regions.parse_agency_region("천안복지재단")
        incheon_user = regions.region_block("인천광역시", "서해구")
        chungnam_user = regions.region_block("충청남도", "천안시 동남구")
        self.assertEqual(regions.match_region(incheon_user, region)["state"], "mismatch")
        self.assertEqual(regions.match_region(chungnam_user, region)["state"], "match")


class LiveCatalogPollutionTest(unittest.TestCase):
    """실데이터에서 인천 사용자의 검색에 타지역 재단 사업이 섞이지 않는지."""

    CATALOG = os.path.join(os.path.dirname(SRC), "data", "gov24", "catalog.json")
    HAS_DATA = os.path.exists(CATALOG) or os.path.exists(CATALOG + ".gz")

    @classmethod
    def setUpClass(cls):
        if not cls.HAS_DATA:
            raise unittest.SkipTest("동기화 카탈로그가 없습니다")
        cls.catalog = load_catalog()
        cls.profile = _profile()

    def test_no_other_region_foundation_in_results(self):
        if len(self.catalog.services) < 500:
            self.skipTest("샘플 카탈로그")
        result = engine.search(self.catalog, self.profile, limit=200,
                               balance_kinds=True, balance_verdicts=True)
        agencies = " ".join((row.get("agency") or "") for row in result["results"])
        for foreign in ("천안복지재단", "전주시복지재단", "안산인재육성재단", "고양문화재단"):
            self.assertNotIn(foreign, agencies, foreign)

    def test_national_count_shrank_from_local_agencies(self):
        if len(self.catalog.services) < 500:
            self.skipTest("샘플 카탈로그")
        national_local = [svc for svc in self.catalog.services
                          if svc.region.get("level") == "national"
                          and svc.agency in {"천안복지재단", "전주시복지재단전주사람",
                                             "재단법인안산인재육성재단", "고양문화재단",
                                             "청주도시공사"}]
        self.assertEqual(national_local, [])


# ---------------------------------------------------------------------------
# 5. 브랜드·404
# ---------------------------------------------------------------------------
class BrandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()

    def test_pseo_titles_use_current_brand(self):
        for page in pseo.items(self.catalog):
            html = pseo.render_item(page["slug"], self.catalog)
            self.assertNotIn("SUBSIDY-KR", html, page["slug"])
            self.assertIn("| GRNT", re.search(r"<title>([^<]*)</title>", html).group(1))
        index = pseo.render_index(self.catalog)
        self.assertNotIn("SUBSIDY-KR", index)
        self.assertEqual(len(re.findall(r'<meta property="og:title" content="[^"]*SUBSIDY-KR',
                                        index)), 0)

    def test_other_pages_have_no_legacy_brand(self):
        self.assertNotIn("SUBSIDY-KR", regions.render_index(self.catalog))
        self.assertNotIn("SUBSIDY-KR", regions.render_item("incheon", self.catalog))
        self.assertNotIn("SUBSIDY-KR", static_files.llms_txt(self.catalog))
        self.assertNotIn("SUBSIDY-KR", static_files.sitemap_xml(self.catalog))


class NotFoundHtmlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.store = Store(":memory:")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.catalog, cls.store))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()

    def _get(self, path, opener=None):
        op = opener or urllib.request.build_opener()
        try:
            with op.open(f"http://127.0.0.1:{self.port}{path}", timeout=10) as response:
                return response.status, response.read().decode(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode(), dict(exc.headers)

    def test_human_404_is_html_with_ways_back(self):
        for path in ("/nope", "/s/does-not-exist", "/guides/does-not-exist",
                     "/regions/does-not-exist"):
            status, body, _ = self._get(path)
            self.assertEqual(status, 404, path)
            self.assertIn("<!doctype html>", body, path)
            self.assertIn("찾으시는 페이지가 없습니다", body, path)
            self.assertIn('href="/"', body, path)
            self.assertIn('href="/guides/"', body, path)
            self.assertIn('name="robots" content="noindex', body, path)

    def test_api_paths_keep_json_404(self):
        status, body, headers = self._get("/v1/nope")
        self.assertEqual(status, 404)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        self.assertEqual(json.loads(body)["error"], "not_found")

    def test_legacy_region_slugs_are_permanent_redirects(self):
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        for old, new in (("/regions/gwangju", "/regions/jeonnamgwangju"),
                         ("/regions/jeonnam", "/regions/jeonnamgwangju"),
                         ("/s/gwangju", "/s/jeonnamgwangju"),
                         ("/s/jeonnam", "/s/jeonnamgwangju")):
            status, _body, headers = self._get(old, opener)
            self.assertEqual(status, 301, old)
            self.assertTrue(headers.get("Location", "").endswith(new), old)


# ---------------------------------------------------------------------------
# 6. SQLite 인덱스의 지역 택소노미 버전
# ---------------------------------------------------------------------------
class RegionSchemaRebuildTest(unittest.TestCase):
    def test_build_records_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "catalog.sqlite")
            build_sqlite_from_rows(sample_data.services(), {"catalog_state": "synced"}, path)
            db = SQLiteCatalog(path)
            self.assertEqual(db.meta.get("region_schema"), regions.SCHEMA_VERSION)

    def test_stale_sqlite_is_rebuilt(self):
        rows = sample_data.services()
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = os.path.join(tmp, "catalog.json")
            with open(catalog_path, "w", encoding="utf-8") as handle:
                json.dump({"meta": {"catalog_state": "synced"}, "services": rows}, handle,
                          ensure_ascii=False)
            db_path = os.path.join(tmp, "catalog.sqlite")
            build_sqlite_from_rows(rows, {"catalog_state": "synced"}, db_path)
            # 개편 전에 만든 DB 처럼 버전 표시를 지우고, mtime 은 JSON 보다 새로 만든다.
            conn = sqlite3.connect(db_path)
            conn.execute("DELETE FROM meta WHERE key = 'region_schema'")
            conn.commit()
            conn.close()
            future = time.time() + 10
            os.utime(db_path, (future, future))
            catalog = load_catalog(catalog_path)
            self.assertEqual(catalog.meta.get("region_schema"), regions.SCHEMA_VERSION)


class WebUiCountWiringTest(unittest.TestCase):
    """화면이 반환 목록이 아니라 서버 집계(kind_counts)로 탭 숫자를 그리는지."""

    def setUp(self):
        from subsidy_kr import web_ui
        self.html = web_ui.render_page({})

    def test_tabs_use_server_facets(self):
        for marker in ("result.kind_counts", "result.kind_verdict_counts",
                       "verdictTotal(result", "refetchVerdict(code)",
                       "body.verdict = code", "전체 결과로 돌아가기"):
            self.assertIn(marker, self.html, marker)

    def test_truncation_is_explained_to_the_user(self):
        self.assertIn("조건에 맞는 '", self.html)
        self.assertIn("' 중 상위 '", self.html)


class ResponseCompressionTest(unittest.TestCase):
    """200건 판정 JSON(~900KB)을 그대로 보내지 않는다 — gzip 협상."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.store = Store(":memory:")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.catalog, cls.store))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()

    def _get(self, path, headers=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                         headers=headers or {})
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(), dict(response.headers)

    def test_gzip_when_accepted(self):
        status, body, headers = self._get("/", {"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", headers.get("Vary", ""))
        self.assertIn("<!doctype html>", gzip.decompress(body).decode("utf-8"))

    def test_identity_when_not_accepted(self):
        status, body, headers = self._get("/")
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Content-Encoding"))
        self.assertIn("<!doctype html>", body.decode("utf-8"))

    def test_small_bodies_are_not_compressed(self):
        status, body, headers = self._get("/healthz", {"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Content-Encoding"))
        self.assertTrue(json.loads(body)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
