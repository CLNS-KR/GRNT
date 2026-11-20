"""시도·시군구 정규화와 소관기관명 → 지역 판별."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import json  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

from subsidy_kr import regions, static_files, usage  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.server import make_handler  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402


class SidoTest(unittest.TestCase):
    def test_aliases_and_prefixes(self):
        cases = {
            "서울": "서울특별시", "서울시": "서울특별시", "서울특별시": "서울특별시",
            "인천": "인천광역시", "인천시": "인천광역시", "인천서구": "인천광역시",
            "경기": "경기도", "경기도": "경기도", "경기도수원시": "경기도",
            "전북": "전북특별자치도", "전라북도": "전북특별자치도",
            "강원도": "강원특별자치도", "제주": "제주특별자치도",
        }
        for raw, expected in cases.items():
            self.assertEqual(regions.canonical_sido(raw), expected, raw)
        self.assertIsNone(regions.canonical_sido("화성"))
        self.assertIsNone(regions.canonical_sido(""))

    def test_sido_list_is_17(self):
        self.assertEqual(len(regions.sido_names()), 17)
        self.assertEqual(len(list(regions.iter_all_regions())), 250)


class SigunguTest(unittest.TestCase):
    def test_resolution(self):
        self.assertEqual(regions.canonical_sigungu("인천광역시", "서구"), "서해구")
        self.assertEqual(regions.canonical_sigungu("경기도", "수원 장안구"), "수원시 장안구")
        self.assertEqual(regions.canonical_sigungu("경기도", "구리"), "구리시")
        self.assertEqual(regions.canonical_sigungu("경기도", "부천"), "부천시")
        self.assertIsNone(regions.canonical_sigungu("인천광역시", "강남구"))
        self.assertIsNone(regions.canonical_sigungu("세종특별자치시", "세종특별자치시"))

    def test_ambiguous_sigungu_needs_sido(self):
        sido, state = regions.find_sido_by_sigungu("중구")
        self.assertIsNone(sido)
        self.assertEqual(state, "ambiguous")
        sido, state = regions.find_sido_by_sigungu("마포구")
        self.assertEqual((sido, state), ("서울특별시", "unique"))

    def test_region_block_levels(self):
        self.assertEqual(regions.region_block()["level"], "national")
        self.assertEqual(regions.region_block("인천광역시")["level"], "sido")
        block = regions.region_block("인천", "서구")
        self.assertEqual((block["level"], block["sido"], block["sigungu"]),
                         ("sigungu", "인천광역시", "서해구"))
        self.assertEqual(regions.region_block("", "서구")["level"], "local_unresolved")


class AgencyRegionTest(unittest.TestCase):
    def test_central_agency_is_national(self):
        for name in ("해양수산부", "교육부", "국세청", "금융위원회"):
            self.assertEqual(regions.parse_agency_region(name)["level"], "national", name)
        self.assertEqual(regions.parse_agency_region("")["level"], "unknown")

    def test_full_names(self):
        block = regions.parse_agency_region("인천광역시 서구")
        self.assertEqual((block["level"], block["sido"], block["sigungu"]),
                         ("sigungu", "인천광역시", "서해구"))
        self.assertEqual(regions.parse_agency_region("세종특별자치시")["level"], "sido")
        self.assertEqual(regions.parse_agency_region("제주시")["sigungu"], "제주시")

    def test_agency_names_without_sido(self):
        block = regions.parse_agency_region("마포구시설관리공단")
        self.assertEqual((block["sido"], block["sigungu"]), ("서울특별시", "마포구"))
        block = regions.parse_agency_region("구리도시공사")
        self.assertEqual((block["sido"], block["sigungu"]), ("경기도", "구리시"))
        block = regions.parse_agency_region("(재)남동문화재단")
        self.assertEqual((block["sido"], block["sigungu"]), ("인천광역시", "남동구"))

    def test_ambiguous_agency_is_left_unresolved(self):
        self.assertEqual(regions.parse_agency_region("광주시")["level"], "local_unresolved")
        self.assertEqual(regions.parse_agency_region("중구")["level"], "local_unresolved")

    def test_gyeonggi_gwangju_is_resolved(self):
        block = regions.parse_agency_region("경기도 광주시")
        self.assertEqual((block["sido"], block["sigungu"]), ("경기도", "광주시"))


class MatchTest(unittest.TestCase):
    def _service(self, **kwargs):
        return {"level": "national", "sido": "", "sigungu": "", **kwargs}

    def test_national_always_matches(self):
        self.assertEqual(regions.match_region(regions.region_block(), self._service())["state"],
                         "match")

    def test_mismatch_and_match(self):
        user = regions.region_block("인천광역시", "서구")
        self.assertEqual(regions.match_region(
            user, self._service(level="sigungu", sido="인천광역시", sigungu="서해구"))["state"], "match")
        self.assertEqual(regions.match_region(
            user, self._service(level="sigungu", sido="인천광역시", sigungu="남동구"))["state"],
            "mismatch")
        self.assertEqual(regions.match_region(
            user, self._service(level="sido", sido="부산광역시"))["state"], "mismatch")

    def test_unknown_when_user_or_service_unresolved(self):
        self.assertEqual(regions.match_region(
            regions.region_block(), self._service(level="sido", sido="부산광역시"))["state"],
            "unknown")
        self.assertEqual(regions.match_region(
            regions.region_block("", "서구"), self._service(level="sido", sido="부산광역시"))["state"],
            "unknown")
        self.assertEqual(regions.match_region(
            regions.region_block("인천광역시"), self._service(level="local_unresolved"))["state"],
            "unknown")


# ---------------------------------------------------------------------------
# 시·도별 SEO 허브 (`/regions/` · `/regions/{slug}`)
# ---------------------------------------------------------------------------
EXPECTED_SLUGS = [
    "seoul", "busan", "daegu", "incheon", "gwangju", "daejeon", "ulsan", "sejong",
    "gyeonggi", "gangwon", "chungbuk", "chungnam", "jeonbuk", "jeonnam",
    "gyeongbuk", "gyeongnam", "jeju",
]


def _ld_blocks(html_text):
    return [json.loads(raw) for raw in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html_text, re.S)]


class RegionSlugTest(unittest.TestCase):
    def test_seventeen_slugs(self):
        self.assertEqual(len(regions.SIDO_SLUGS), 17)
        self.assertEqual(regions.sido_slugs(), EXPECTED_SLUGS)
        self.assertEqual(len(set(EXPECTED_SLUGS)), 17)
        for slug in regions.sido_slugs():
            self.assertRegex(slug, r"^[a-z]+$")
            self.assertIsNotNone(regions.sido_for_slug(slug))
        self.assertEqual(set(regions.SIDO_SLUGS), set(regions.SIDO_CODES))

    def test_alias_and_unknown_slugs(self):
        self.assertEqual(regions.slug_for_sido("경기"), "gyeonggi")
        self.assertEqual(regions.slug_for_sido("전라북도"), "jeonbuk")
        self.assertIsNone(regions.slug_for_sido("화성"))
        self.assertIsNone(regions.sido_for_slug("no-such-region"))
        self.assertIsNone(regions.sido_for_slug(""))

    def test_hub_paths(self):
        paths = regions.hub_paths()
        self.assertEqual(len(paths), 18)
        self.assertEqual(paths[0], "/regions/")
        self.assertIn("/regions/incheon", paths)

    def test_sigungu_rows_follow_legacy_key(self):
        # 시·군·구 명부는 2023-07 배포본이라 전북이 개편 전 이름으로 들어 있다.
        # 읽을 때 정식 명칭으로 맞춰야 시·군·구 판정이 시·도 단위로 뭉개지지 않는다.
        self.assertTrue(regions._sigungu_rows("전북특별자치도"))
        self.assertEqual(regions.canonical_sigungu("전북특별자치도", "완주군"), "완주군")
        self.assertEqual(regions.parse_agency_region("전북특별자치도 완주군")["sido"],
                         "전북특별자치도")
        self.assertEqual(regions.find_sido_by_sigungu("완주군"), ("전북특별자치도", "unique"))
        self.assertEqual(set(regions.SIGUNGU_BY_SIDO), set(regions.SIDO_CODES))


class RegionHubRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()

    def test_every_region_renders(self):
        for slug in regions.sido_slugs():
            page = regions.render_item(slug, self.catalog)
            self.assertIsNotNone(page, slug)
            self.assertIn("<html lang=\"ko\">", page)
            self.assertIn(" 지원금", page)
            self.assertEqual(page.count("<h2>"), 1, slug)
        self.assertIsNone(regions.render_item("no-such-region", self.catalog))

    def test_index_links_every_region(self):
        page = regions.render_index(self.catalog)
        for slug in regions.sido_slugs():
            self.assertIn(f'href="/regions/{slug}"', page)
        self.assertIn("17개 시·도", page)
        self.assertIn("지역별 지원금", page)

    def test_dark_mode_tokens(self):
        page = regions.render_item("seoul", self.catalog)
        self.assertIn('<meta name="color-scheme" content="light dark">', page)
        self.assertIn("@media (prefers-color-scheme: dark)", page)
        # 허브 전용 CSS 는 BASE_CSS 토큰만 쓰고 색을 직접 박지 않는다.
        self.assertNotRegex(regions.REGION_CSS, r"#[0-9a-fA-F]{3,8}\b")
        self.assertNotRegex(regions.REGION_CSS, r"\b(rgb|rgba|hsl)\(")
        for token in ("var(--ink)", "var(--ink-soft)", "var(--card)", "var(--line)"):
            self.assertIn(token, regions.REGION_CSS)

    def test_structured_data_and_canonical(self):
        page = regions.render_item("incheon", self.catalog)
        blocks = _ld_blocks(page)
        kinds = {block.get("@type") for block in blocks}
        self.assertIn("FAQPage", kinds)
        self.assertIn("BreadcrumbList", kinds)
        self.assertIn("WebPage", kinds)
        faq = next(block for block in blocks if block["@type"] == "FAQPage")
        self.assertGreaterEqual(len(faq["mainEntity"]), 3)
        for item in faq["mainEntity"]:
            self.assertTrue(item["name"])
            self.assertTrue(item["acceptedAnswer"]["text"])
        breadcrumb = next(block for block in blocks if block["@type"] == "BreadcrumbList")
        self.assertEqual([row["position"] for row in breadcrumb["itemListElement"]], [1, 2, 3])
        self.assertIn("인천광역시", breadcrumb["itemListElement"][2]["name"])
        self.assertIn('<link rel="canonical" href="https://grnt-kr.onrender.com/regions/incheon">',
                      page)
        webpage = next(block for block in blocks if block["@type"] == "WebPage")
        self.assertEqual(webpage["url"], "https://grnt-kr.onrender.com/regions/incheon")

    def test_cta_and_sitemap_links(self):
        page = regions.render_item("busan", self.catalog)
        self.assertIn('/?track=personal&amp;sido=%EB%B6%80%EC%82%B0%EA%B4%91%EC%97%AD%EC%8B%9C', page)
        self.assertIn('/?track=business&amp;sido=', page)
        self.assertIn('href="/s/busan"', page)
        self.assertIn('href="/regions/"', page)

    def test_counts_come_from_catalog(self):
        stats = regions.region_stats(self.catalog)["인천광역시"]
        self.assertGreaterEqual(stats["local_total"], stats["local_open"])
        self.assertLessEqual(len(stats["items"]), regions.MAX_HUB_ITEMS)
        for svc in stats["items"]:
            self.assertFalse(svc.is_expired)
        page = regions.render_item("incheon", self.catalog)
        self.assertIn(f"{stats['local_total']:,}건", page)
        self.assertIn(f"{stats['national_open']:,}", page)

    def test_index_structured_data(self):
        page = regions.render_index(self.catalog)
        kinds = {block.get("@type") for block in _ld_blocks(page)}
        self.assertIn("FAQPage", kinds)
        self.assertIn("BreadcrumbList", kinds)
        self.assertIn("WebPage", kinds)
        self.assertIn("<link rel=\"canonical\" href=\"https://grnt-kr.onrender.com/regions/\">", page)


class RegionStaticFilesTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_sitemap_has_eighteen_region_urls(self):
        xml = static_files.sitemap_xml(self.catalog, base="https://example.test")
        self.assertIn("<loc>https://example.test/regions/</loc>", xml)
        for slug in regions.sido_slugs():
            self.assertIn(f"<loc>https://example.test/regions/{slug}</loc>", xml)
        region_locs = [line for line in xml.splitlines() if "/regions/" in line]
        self.assertEqual(len(region_locs), 18)
        self.assertEqual(xml.count("<url>"), xml.count("</url>"))

    def test_llms_txt_links_region_hub(self):
        text = static_files.llms_txt(self.catalog, base="https://example.test")
        self.assertIn("https://example.test/regions/", text)
        self.assertIn("시·도별 지원금", text)

    def test_usage_counts_region_paths(self):
        self.assertIn("/regions/", usage.FIXED_PATHS)
        self.assertEqual(usage.path_key("/regions/seoul"), "/regions/seoul")
        self.assertEqual(usage.path_key("/regions/"), "/regions/")
        self.assertEqual(usage.path_key("/regions/nope"), "/404")

    def test_meta_payload_keeps_existing_keys(self):
        from subsidy_kr.api import call_tool
        result = call_tool("get_service_meta", {}, self.catalog)["result"]
        for key in ("tracks", "verdicts", "sido_list", "guides", "tools", "stats", "privacy"):
            self.assertIn(key, result)
        block = result["regions"]
        self.assertEqual(block["count"], 17)
        self.assertEqual(len(block["regions"]), 17)
        self.assertEqual(block["index_url"], "https://grnt-kr.onrender.com/regions/")
        self.assertEqual({row["slug"] for row in block["regions"]}, set(EXPECTED_SLUGS))

    def test_home_footer_links_region_hub(self):
        from subsidy_kr.web_ui import render_page
        page = render_page(self.catalog.meta)
        self.assertIn('href="/regions/"', page)


class RegionHttpTest(unittest.TestCase):
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

    def _status(self, path, method="GET"):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def test_index_200(self):
        for path in ("/regions/", "/regions"):
            status, body = self._status(path)
            self.assertEqual(status, 200, path)
            self.assertIn("시·도", body)

    def test_all_seventeen_regions_200(self):
        for slug in regions.sido_slugs():
            status, body = self._status(f"/regions/{slug}")
            self.assertEqual(status, 200, slug)
            self.assertIn("FAQPage", body)
            self.assertIn("BreadcrumbList", body)
            self.assertIn("WebPage", body)
            self.assertIn("rel=\"canonical\"", body)

    def test_head_and_trailing_slash(self):
        status, _ = self._status("/regions/gyeonggi/", "GET")
        self.assertEqual(status, 200)
        status, _ = self._status("/regions/", "HEAD")
        self.assertEqual(status, 200)
        status, _ = self._status("/regions/gyeonggi", "HEAD")
        self.assertEqual(status, 200)

    def test_unknown_slug_404(self):
        status, body = self._status("/regions/no-such-region")
        self.assertEqual(status, 404)
        self.assertIn("unknown_region", body)

    def test_sitemap_and_llms_over_http(self):
        status, body = self._status("/sitemap.xml")
        self.assertEqual(status, 200)
        self.assertIn("/regions/", body)
        for slug in regions.sido_slugs():
            self.assertIn(f"/regions/{slug}</loc>", body)
        status, body = self._status("/llms.txt")
        self.assertEqual(status, 200)
        self.assertIn("/regions/", body)

    def test_meta_over_http(self):
        status, body = self._status("/v1/meta")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["result"]["regions"]["count"], 17)


if __name__ == "__main__":
    unittest.main(verbosity=2)
