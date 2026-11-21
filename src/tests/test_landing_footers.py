"""랜딩 페이지 푸터·공유 카드·sitemap 정합성 회귀 테스트 — 0.4.8.

검색·AI 로 `/guides/*`·`/s/*`·`/regions/*` 에 **바로 들어온 사람**이 홈까지 돌아가지
않아도 약관·개인정보·소개와 자매 서비스로 이어져야 한다. 그리고 홈은 12,429건,
`llms.txt` 는 13,416건처럼 서비스마다 다른 건수를 말하지 않아야 한다.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import xml.etree.ElementTree as ElementTree

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from subsidy_kr import guides, legal, pseo, regions, static_files, web_ui  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402
from subsidy_kr.version import RELEASE_DATE  # noqa: E402

BASE = "https://example.test"
LEGAL_PATHS = ("/privacy", "/terms", "/about")


def _foot(page: str) -> str:
    """`<p class="foot">` 한 덩어리(랜딩 페이지 푸터)."""
    at = page.index('<p class="foot">')
    return page[at:page.index("</p>", at)]


class LandingFooterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.pages = {
            "s-index": pseo.render_index(cls.catalog),
            "s-item": pseo.render_item("cheongnyeon", cls.catalog),
            "region-index": regions.render_index(cls.catalog),
            "region-item": regions.render_item("seoul", cls.catalog),
            "guide-index": guides.render_index(cls.catalog),
            "guide-item": guides.render_item(guides.GUIDES[0]["slug"], cls.catalog),
        }

    def test_some_pages_are_rendered(self):
        # 슬러그 이름이 바뀌어 조용히 None 을 비교하는 일을 막는다.
        self.assertEqual(len(self.pages), 6)
        for name, page in self.pages.items():
            self.assertIsInstance(page, str, name)

    def test_every_landing_footer_links_legal_pages(self):
        for name, page in self.pages.items():
            foot = _foot(page)
            for path in LEGAL_PATHS:
                self.assertIn(f'href="{path}"', foot, f"{name}: {path}")

    def test_every_landing_footer_links_sibling_services(self):
        for name, page in self.pages.items():
            foot = _foot(page)
            self.assertIn("같이 쓰는 서비스", foot, name)
            for url, label, _note in legal.SIBLINGS:
                self.assertIn(url, foot, f"{name}: {label}")
                self.assertIn(label, foot, name)

    def test_sibling_links_open_safely(self):
        for name, page in self.pages.items():
            foot = _foot(page)
            for url, _label, _note in legal.SIBLINGS:
                at = foot.index(url)
                start = foot.rindex("<a ", 0, at)
                tag = foot[start:foot.index(">", start) + 1]
                self.assertIn('target="_blank"', tag, name)
                self.assertIn('rel="noopener noreferrer"', tag, name)

    def test_sibling_urls_point_at_live_services(self):
        for url, _label, _note in legal.SIBLINGS:
            self.assertTrue(url.startswith("https://"), url)
            self.assertTrue(url.endswith("/"), url)


class RegionShareCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()

    def test_region_pages_have_og_image(self):
        for page in (regions.render_index(self.catalog), regions.render_item("seoul", self.catalog)):
            head = page.split("</head>", 1)[0]
            self.assertIn('property="og:image"', head)
            self.assertIn("/static/og.png", head)
            self.assertIn('property="og:image:width" content="1200"', head)
            self.assertIn('property="og:image:height" content="630"', head)
            self.assertIn('name="twitter:card" content="summary_large_image"', head)

    def test_every_landing_page_type_has_og_image(self):
        pages = {
            "home": web_ui.render_page(self.catalog.meta),
            "s-index": pseo.render_index(self.catalog),
            "region": regions.render_index(self.catalog),
            "guide": guides.render_item(guides.GUIDES[0]["slug"], self.catalog),
        }
        for name, page in pages.items():
            self.assertIn('property="og:image"', page.split("</head>", 1)[0], name)


class SitemapLastmodTest(unittest.TestCase):
    def test_lastmod_is_not_older_than_release(self):
        catalog = sample_catalog()
        catalog.meta["generated_on"] = "2026-01-02T00:00:00+09:00"
        xml = static_files.sitemap_xml(catalog, base=BASE)
        root = ElementTree.fromstring(xml)
        namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        for node in root.iter(f"{namespace}lastmod"):
            self.assertGreaterEqual(node.text, RELEASE_DATE)
            self.assertGreaterEqual(node.text, "2026-01-02")

    def test_catalog_date_wins_when_newer(self):
        catalog = sample_catalog()
        catalog.meta["generated_on"] = "2099-01-01T00:00:00+09:00"
        xml = static_files.sitemap_xml(catalog, base=BASE)
        self.assertIn("<lastmod>2099-01-01</lastmod>", xml)

    def test_release_date_shape(self):
        self.assertRegex(RELEASE_DATE, r"^\d{4}-\d{2}-\d{2}$")
        self.assertGreaterEqual(RELEASE_DATE, "2026-11-22")


class LlmsSiblingSectionTest(unittest.TestCase):
    def test_llms_lists_sibling_services(self):
        text = static_files.llms_txt(sample_catalog(), base=BASE)
        self.assertIn("## 같이 쓰는 서비스", text)
        for url, label, _note in legal.SIBLINGS:
            self.assertIn(label, text)
            self.assertIn(url, text)

    def test_llms_still_has_core_sections(self):
        text = static_files.llms_txt(sample_catalog(), base=BASE)
        for marker in ("## 사람용", "## 기계용 (MCP · JSON-RPC 2.0)", "## 같이 쓰는 서비스"):
            self.assertIn(marker, text, marker)


class CountConsistencyTest(unittest.TestCase):
    """홈·`/v1/meta`·`llms.txt` 가 같은 건수를 말해야 한다."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        stats = cls.catalog.stats()
        # 산출물 meta 에 옛 통계가 남은 상황을 흉내 낸다(0.4.5 실제 파일).
        cls.catalog.meta = dict(cls.catalog.meta)
        cls.catalog.meta["stats"] = {"services": 1, "personal": 1, "business": 0}
        cls.stats = stats

    def test_api_block_uses_computed_stats(self):
        from subsidy_kr import api

        block = api._catalog_block(self.catalog)
        self.assertEqual(block["stats"]["services"], self.stats["services"])
        self.assertEqual(block["tracks"], self.stats["by_track"])

    def test_llms_uses_computed_stats(self):
        text = static_files.llms_txt(self.catalog, base=BASE)
        self.assertIn(f"제도 {self.stats['services']:,}건", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
