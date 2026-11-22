"""웹 UI·pSEO·정적 파일 테스트."""
from __future__ import annotations

import os
import re
import sys
import unittest
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

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


class ShareFeatureTest(unittest.TestCase):
    """판정 결과 공유·복사 버튼 — 요약 복사, 비식별 조건 링크 복사."""

    def setUp(self):
        self.catalog = sample_catalog()
        self.html = web_ui.render_page(self.catalog.meta)

    def test_two_copy_buttons_are_at_top_of_results(self):
        self.assertIn('id="copy-summary"', self.html)
        self.assertIn('id="copy-link"', self.html)
        self.assertIn("결과 요약 복사", self.html)
        self.assertIn("조건 링크 복사", self.html)
        card = self.html.index('id="results-card"')
        bar = self.html.index('id="share-bar"')
        sub = self.html.index('id="results-sub"')
        self.assertLess(card, bar)
        self.assertLess(bar, sub)

    def test_share_link_keys_are_non_identifying(self):
        self.assertEqual(web_ui.SHARE_PARAM_KEYS, ("track", "sido", "sigungu", "q"))
        self.assertIn('data-keys="track,sido,sigungu,q"', self.html)
        for key in ("birth_year", "sex", "household_size", "income_band",
                    "children_years", "situation"):
            self.assertNotIn(key, web_ui.SHARE_PARAM_KEYS)
        keys = self.html.split('data-keys="')[1].split('"')[0]
        self.assertNotIn("name=", keys)

    def test_summary_carries_track_counts_rows_and_source(self):
        script = web_ui.SHARE_SCRIPT
        for marker in ("[GRNT 지원금 판정 요약]", "트랙: ", "대조: 제도 ", "출처: ",
                       "받을 가능성 높음", "조건 확인 필요",
                       "받을 가능성 높음이 3건 미만이면", "확정 판정이 아니며"):
            self.assertIn(marker, script, marker)
        self.assertIn("https://grnt-kr.onrender.com", self.html)

    def test_copy_uses_clipboard_with_textarea_fallback(self):
        script = web_ui.SHARE_SCRIPT
        self.assertIn("navigator.clipboard", script)
        self.assertIn("clipboard.writeText", script)
        self.assertIn("execCommand('copy')", script)
        self.assertIn("createElement('textarea')", script)
        self.assertIn("복사됨 ✓", script)
        self.assertIn('id="share-flash"', self.html)

    def test_share_origin_follows_public_base_url(self):
        self.assertIn('data-origin="https://grnt-kr.onrender.com"', self.html)
        os.environ["PUBLIC_BASE_URL"] = "https://example.test"
        try:
            html = web_ui.render_page(self.catalog.meta)
        finally:
            os.environ.pop("PUBLIC_BASE_URL", None)
        self.assertIn('data-origin="https://example.test"', html)

    def test_results_update_the_share_data(self):
        """판정 렌더가 끝나면 공유 스크립트가 최신 결과를 받는다(저장소 없이 메모리만)."""
        self.assertIn("GRNT_SHARE.update(data)", self.html)
        self.assertNotIn("localStorage", self.html)

    def test_entry_script_restores_shared_conditions(self):
        self.assertIn("params.get('sido')", self.html)
        self.assertIn("params.get('sigungu')", self.html)
        self.assertIn("params.get('q')", self.html)
        self.assertIn("params.get('track')", self.html)


class InlineScriptSyntaxTest(unittest.TestCase):
    """인라인 스크립트 문법 검사 — fieldOrder 버그 같은 회귀를 막는다."""

    def setUp(self):
        self.html = web_ui.render_page(sample_catalog().meta)
        self.scripts = re.findall(r"<script>(.*?)</script>", self.html, re.S)

    def test_scripts_are_present(self):
        self.assertGreaterEqual(len(self.scripts), 3)
        self.assertTrue(any("renderResults" in script for script in self.scripts))

    def test_inline_scripts_parse(self):
        try:
            import esprima
        except ImportError:  # 개발 환경에만 있는 검사기
            self.skipTest("esprima 미설치 — 문법 검사 건너뜀")
        for index, script in enumerate(self.scripts):
            try:
                esprima.parseScript(script)
            except Exception as error:  # noqa: BLE001 - 파서 오류를 그대로 보고
                self.fail(f"인라인 스크립트 {index}번 문법 오류: {error}")

    def test_field_order_is_declared_before_use(self):
        main = next(script for script in self.scripts if "fieldOrder" in script)
        declared = main.index("var fieldOrder")
        self.assertIn("'주거·주택'", main)
        self.assertLess(declared, main.index("fieldOrder.forEach"))
        for match in re.finditer(r"fieldOrder\.forEach", main):
            self.assertGreater(match.start(), declared)


class DarkModeContrastTest(unittest.TestCase):
    """다크 모드에서 판정 결과 영역이 흰 배경에 흰 글자로 사라지지 않게 한다."""

    LIGHT_HARD_CODED = ("#f3f4f6", "#f8f9fb", "#e6e8ee", "#dde1ea", "#eef1f6",
                        "background:#fff")

    def setUp(self):
        self.css = web_ui.BASE_CSS
        source = os.path.join(SRC, "subsidy_kr", "web_ui.py")
        with open(source, "r", encoding="utf-8") as handle:
            self.source = handle.read()

    def test_dark_media_query_redefines_surface_tokens(self):
        self.assertIn("@media (prefers-color-scheme: dark)", self.css)
        dark = self.css.split("@media (prefers-color-scheme: dark)", 1)[1].split("}\n", 1)[0]
        for token in ("--bg", "--card", "--ink", "--ink-soft", "--line",
                      "--surface-2", "--surface-3", "--on-brand"):
            self.assertIn(token + ":", dark, token)

    def test_surfaces_are_painted_with_tokens(self):
        # 요약 박스·접힌 세부 조건·선택된 칩은 모두 토큰으로만 칠한다.
        self.assertIn(".summary{padding:20px", self.css)
        self.assertIn("background:var(--surface-2)", self.css)
        self.assertIn("details.more-conditions{", self.css)
        self.assertIn(".counts button.active{background:var(--ink)", self.css)
        self.assertIn("border-top:1px dashed var(--line)", self.css)

    def test_text_on_brand_colour_uses_token(self):
        self.assertIn("--on-brand:#ffffff", self.css)
        self.assertIn("--on-brand:#0b1220", self.css)
        self.assertNotIn("color:#fff", self.css)

    def test_no_light_background_is_hard_coded_in_ui_source(self):
        # 토큰 정의(--surface-2:#f8f9fb 등)만 허용하고, 나머지 곳에 밝은 색이 직접 박혀 있으면
        # 다크 모드에서 그 부분만 흰 배경으로 남는다.
        stripped = re.sub(r"--[a-z0-9-]+:#[0-9a-fA-F]{3,8}", "", self.source)
        for colour in self.LIGHT_HARD_CODED:
            self.assertNotIn(colour, stripped, colour)
        self.assertNotIn("style.background =", stripped)
        self.assertNotIn("cssText", stripped)

    def _tokens(self):
        light_block = self.css.split("@media (prefers-color-scheme: dark)", 1)[0]
        dark_block = self.css.split("@media (prefers-color-scheme: dark)", 1)[1]
        pattern = r"--([a-z0-9-]+):(#[0-9a-fA-F]{6})"
        return (dict(re.findall(pattern, light_block)), dict(re.findall(pattern, dark_block)))

    @staticmethod
    def _contrast(first, second):
        def luminance(colour):
            channels = [int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                      for c in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        high, low = sorted((luminance(first), luminance(second)), reverse=True)
        return (high + 0.05) / (low + 0.05)

    def test_text_pairs_meet_contrast_in_both_themes(self):
        """본문·보조글자·배지·버튼 글자가 배경과 4.5:1 이상 대비된다."""
        pairs = (("ink", "card"), ("ink", "surface-3"), ("ink-soft", "card"),
                 ("ink-soft", "surface-2"), ("on-brand", "brand"),
                 ("ok", "ok-soft"), ("warn", "warn-soft"),
                 ("info", "info-soft"), ("danger", "danger-soft"),
                 ("brand-ink", "brand-soft"))
        for name, tokens in zip(("light", "dark"), self._tokens()):
            for foreground, background in pairs:
                self.assertIn(foreground, tokens, f"{name}:{foreground}")
                self.assertIn(background, tokens, f"{name}:{background}")
                ratio = self._contrast(tokens[foreground], tokens[background])
                self.assertGreaterEqual(
                    ratio, 4.5, f"{name} {foreground}/{background} 대비 {ratio:.2f}:1")


class PseoTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_index_lists_topics(self):
        html = pseo.render_index(self.catalog)
        self.assertIn("주제·지역별 지원금", html)
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
            self.assertEqual(page["count"], len(page["service_ids"]))
            self.assertEqual(page["indexable"], page["count"] >= pseo.MIN_INDEX_ITEMS)

    def test_item_h1_is_the_page_subject(self):
        """pSEO 페이지의 h1 은 브랜드가 아니라 그 페이지의 주제여야 한다(색인 제목)."""
        html = pseo.render_item("cheongnyeon", self.catalog)
        self.assertEqual(html.count("<h1"), 1)
        self.assertIn('<h1 class="page-title">청년 지원금</h1>', html)
        self.assertNotIn("<h1>GRNT", html)
        region_html = pseo.render_item("seoul", self.catalog)
        if region_html is not None:
            self.assertIn('<h1 class="page-title">서울특별시 지원금 목록</h1>', region_html)
            self.assertNotIn("<h1>GRNT", region_html)

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
        self.assertEqual(len(card["tools"]), 9)
        self.assertEqual(card["transport"]["type"], "streamable-http")
        self.assertIn("stdio", card["transports"])

    def test_sitemap_well_formed(self):
        xml = static_files.sitemap_xml(self.catalog, base="https://example.test")
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertEqual(xml.count("<url>"), xml.count("</url>"))
        self.assertNotIn("//s/", xml)


if __name__ == "__main__":
    unittest.main(verbosity=2)
