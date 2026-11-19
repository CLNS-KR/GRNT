"""웹 UI·pSEO·정적 파일 테스트."""
from __future__ import annotations

import os
import re
import sys
import unittest
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import pseo, static_files, web_ui  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402


class WebUiTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()
        self.html = web_ui.render_page(self.catalog.meta)

    def test_form_fields_present(self):
        for marker in ('id="sido"', 'id="sigungu"', 'id="birth_year"', 'name="sex"',
                       'id="household_size"', 'id="income_band"', 'name="situation"',
                       'id="children_years"', 'id="run"'):
            self.assertIn(marker, self.html, marker)

    def test_no_identity_inputs(self):
        lowered = self.html.lower()
        for forbidden in ('주민등록번호를 입력', 'name="rrn"', 'name="resident"',
                          'name="phone"', 'type="password"', 'name="email"'):
            self.assertNotIn(forbidden, lowered, forbidden)

    def test_privacy_and_limits_are_stated(self):
        self.assertIn("서버에 저장하지 않습니다", self.html)
        self.assertIn("확정하지 않습니다", self.html)
        self.assertIn("익명", self.html)

    def test_no_browser_storage_or_external_assets(self):
        self.assertNotIn("localStorage", self.html)
        self.assertNotIn("sessionStorage", self.html)
        self.assertNotIn("document.cookie", self.html)
        # 외부 스크립트/폰트/CDN 없음
        self.assertNotIn("<script src=", self.html)
        self.assertNotIn("@import", self.html)
        self.assertNotIn("cdn.", self.html)

    def test_situations_are_all_offered(self):
        for key in ("pregnant", "birth", "multi_child", "no_home", "jobseeker",
                    "disabled", "small_business", "farmer"):
            self.assertIn(f'value="{key}"', self.html)

    def test_region_data_is_embedded_for_all_sido(self):
        for sido in ("서울특별시", "인천광역시", "경기도", "제주특별자치도"):
            self.assertIn(sido, self.html)
        self.assertIn("남동구", self.html)

    def test_sample_notice_and_synced_notice(self):
        self.assertIn("샘플 데이터로 동작", self.html)
        synced = web_ui.render_page({"catalog_state": "synced", "generated_on": "2026-11-19",
                                     "stats": {"services": 10925}})
        self.assertNotIn("샘플 데이터로 동작", synced)
        self.assertIn("실데이터 기준일", synced)
        self.assertIn("10,925", synced)

    def test_javascript_references_existing_ids(self):
        ids = set(re.findall(r'id="([^"]+)"', self.html))
        refs = set(re.findall(r"getElementById\('([^']+)'\)", self.html))
        self.assertTrue(refs)
        self.assertEqual(refs - ids, set())

    def test_html_tags_are_balanced(self):
        void = {"meta", "link", "br", "hr", "img", "input", "source", "area", "base", "col"}
        stack = []
        errors = []

        class Checker(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag not in void:
                    stack.append(tag)

            def handle_endtag(self, tag):
                if tag in void:
                    return
                if stack and stack[-1] == tag:
                    stack.pop()
                else:
                    errors.append((tag, list(stack[-3:])))

        Checker().feed(self.html)
        self.assertEqual(stack, [])
        self.assertEqual(errors, [])

    def test_no_template_leftovers(self):
        self.assertNotIn("{css}", self.html)
        self.assertNotIn("{chips}", self.html)
        self.assertNotIn("{{", self.html)


class PseoTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_index_lists_topics(self):
        html = pseo.render_index(self.catalog)
        self.assertIn("주제별 지원금", html)
        self.assertIn('href="/s/cheongnyeon"', html)
        self.assertIn('href="/s/incheon"', html)

    def test_item_page(self):
        html = pseo.render_item("cheongnyeon", self.catalog)
        self.assertIsNotNone(html)
        self.assertIn("청년 지원금", html)
        self.assertIn("청년월세", html)
        self.assertIsNone(pseo.render_item("no-such-topic", self.catalog))

    def test_thin_pages_are_noindex_and_not_in_sitemap(self):
        pages = {page["slug"]: page for page in pseo.items(self.catalog)}
        thin = [slug for slug, page in pages.items() if not page["indexable"]]
        self.assertTrue(thin, "샘플에는 5건 미만 주제가 있어야 규칙을 검증할 수 있다")
        html = pseo.render_item(thin[0], self.catalog)
        self.assertIn("noindex,follow", html)
        sitemap = static_files.sitemap_xml(self.catalog, base="https://example.test")
        self.assertNotIn(f"/s/{thin[0]}", sitemap)
        for page in pages.values():
            if page["indexable"]:
                self.assertIn(f"/s/{page['slug']}", sitemap)

    def test_min_items_rule(self):
        self.assertGreaterEqual(pseo.MIN_INDEX_ITEMS, 5)
        for page in pseo.items(self.catalog):
            self.assertEqual(page["indexable"], len(page["services"]) >= pseo.MIN_INDEX_ITEMS)

    def test_slugs_are_url_safe(self):
        for slug in pseo.slugs(self.catalog):
            self.assertRegex(slug, r"^[a-z0-9-]+$")


class StaticFilesTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_robots(self):
        text = static_files.robots_txt("https://example.test")
        self.assertIn("Disallow: /v1/", text)
        self.assertIn("Sitemap: https://example.test/sitemap.xml", text)

    def test_llms_txt_documents_rules(self):
        text = static_files.llms_txt(self.catalog, base="https://example.test")
        self.assertIn("eligible_likely", text)
        self.assertIn("정보 부족", text)
        self.assertIn("15113968", text)
        self.assertIn("search_subsidies", text)
        self.assertIn("샘플", text)

    def test_server_card(self):
        card = static_files.server_card()
        self.assertEqual(card["serverInfo"]["name"], "grnt")
        self.assertFalse(card["authentication"]["required"])
        self.assertEqual(len(card["tools"]), 7)
        self.assertEqual(card["transport"]["type"], "streamable-http")
        self.assertIn("stdio", card["transports"])

    def test_sitemap_well_formed(self):
        xml = static_files.sitemap_xml(self.catalog, base="https://example.test")
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertEqual(xml.count("<url>"), xml.count("</url>"))
        self.assertNotIn("//s/", xml)


if __name__ == "__main__":
    unittest.main(verbosity=2)
