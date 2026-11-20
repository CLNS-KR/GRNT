"""질문형 가이드(`/guides/`) 테스트 — 데이터·렌더·JSON-LD·사이트맵·익명 카운터."""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import guides, static_files, usage, web_ui  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402

VOID_TAGS = {"meta", "link", "br", "hr", "img", "input", "source", "area", "base", "col"}


def balanced(html_text):
    """태그 짝이 맞는지 (스택 기반 단순 검사)."""
    stack, errors = [], []

    class Checker(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag not in VOID_TAGS:
                stack.append(tag)

        def handle_endtag(self, tag):
            if tag in VOID_TAGS:
                return
            if stack and stack[-1] == tag:
                stack.pop()
            else:
                errors.append((tag, list(stack[-3:])))

    Checker().feed(html_text)
    return stack, errors


def json_ld_blocks(page):
    return [json.loads(block) for block in
            re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)]


class GuidesDataTest(unittest.TestCase):
    def test_at_least_thirty_guides(self):
        self.assertGreaterEqual(guides.GUIDE_COUNT, 30)
        self.assertEqual(guides.GUIDE_COUNT, len(guides.GUIDES))

    def test_slugs_are_unique_and_url_safe(self):
        slugs = guides.slugs()
        self.assertEqual(len(slugs), len(set(slugs)))
        for slug in slugs:
            self.assertRegex(slug, r"^[a-z0-9-]+$")

    def test_each_guide_is_complete(self):
        required = ("slug", "category", "topic", "question", "one_line", "conditions",
                    "apply", "pitfalls", "keywords", "q", "track", "related")
        for guide in guides.GUIDES:
            for key in required:
                self.assertIn(key, guide, f"{guide.get('slug')}: {key}")
                self.assertTrue(guide[key], f"{guide.get('slug')}: 빈 {key}")
            self.assertIn(guide["category"], guides.CATEGORY_LABEL, guide["slug"])
            self.assertIn(guide["track"], ("personal", "business", "agent"), guide["slug"])
            self.assertGreaterEqual(len(guide["conditions"]), 3, guide["slug"])
            self.assertGreaterEqual(len(guide["pitfalls"]), 2, guide["slug"])
            self.assertTrue(guide["question"].endswith("?"), guide["slug"])

    def test_related_guides_exist(self):
        for guide in guides.GUIDES:
            for other in guide["related"]:
                self.assertIsNotNone(guides.by_slug(other), f"{guide['slug']} → {other}")
                self.assertNotEqual(other, guide["slug"])

    def test_questions_are_distinct(self):
        questions = [guide["question"] for guide in guides.GUIDES]
        self.assertEqual(len(questions), len(set(questions)))

    def test_covers_requested_question_areas(self):
        """브리프가 지정한 주제(청년 월세·정책자금·예비창업·출산·육아·교통·에너지·장려금·
        내일배움·1인가구·대리인 리포트)가 모두 들어 있는지."""
        text = " ".join(f"{g['question']} {g['topic']} {g['one_line']}" for g in guides.GUIDES)
        for needle in ("월세", "정책자금", "예비창업", "첫만남", "부모급여", "육아휴직",
                       "K-패스", "에너지바우처", "근로장려금", "자녀장려금", "내일배움카드",
                       "1인 가구", "리포트"):
            self.assertIn(needle, text, needle)

    def test_paths_and_lookup(self):
        paths = guides.paths()
        self.assertEqual(paths[0], "/guides/")
        self.assertEqual(len(paths), guides.GUIDE_COUNT + 1)
        self.assertIsNone(guides.by_slug("no-such-guide"))
        self.assertEqual(guides.by_slug("/cheongnyeon-wolse/")["slug"], "cheongnyeon-wolse")


class GuidesRenderTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_index_lists_every_guide(self):
        html = guides.render_index(self.catalog)
        self.assertIn(f"자주 묻는 지원금 질문 {guides.GUIDE_COUNT}개", html)
        for guide in guides.GUIDES:
            self.assertIn(f'/guides/{guide["slug"]}', html, guide["slug"])
        self.assertIn(guides.DISCLAIMER_KO, html)
        self.assertIn('href="/mcp"', html)

    def test_every_guide_page_has_required_parts(self):
        for guide in guides.GUIDES:
            page = guides.render_item(guide["slug"], self.catalog)
            self.assertIsNotNone(page, guide["slug"])
            for marker in ("한 줄 기준", "확인해야 할 조건", "지금 열려 있는 관련 공고",
                           "흔히 하는 착각", "/mcp", "/v1/tools/",
                           guides.DISCLAIMER_KO, "index,follow"):
                self.assertIn(marker, page, f"{guide['slug']}: {marker}")
            self.assertIn(guide["question"], page)
            self.assertIn(guide["one_line"], page)

    def test_faq_json_ld_is_valid_and_matches_page(self):
        for guide in guides.GUIDES:
            page = guides.render_item(guide["slug"], self.catalog)
            blocks = json_ld_blocks(page)
            types = [block.get("@type") for block in blocks]
            self.assertIn("FAQPage", types, guide["slug"])
            self.assertIn("BreadcrumbList", types, guide["slug"])
            faq = next(block for block in blocks if block["@type"] == "FAQPage")
            self.assertGreaterEqual(len(faq["mainEntity"]), 3, guide["slug"])
            self.assertEqual(faq["mainEntity"][0]["name"], guide["question"])
            for entry in faq["mainEntity"]:
                self.assertEqual(entry["@type"], "Question")
                self.assertEqual(entry["acceptedAnswer"]["@type"], "Answer")
                self.assertGreater(len(entry["acceptedAnswer"]["text"]), 20, guide["slug"])

    def test_unknown_guide_returns_none(self):
        self.assertIsNone(guides.render_item("no-such-guide", self.catalog))

    def test_pages_are_well_formed_html(self):
        for guide in guides.GUIDES:
            page = guides.render_item(guide["slug"], self.catalog)
            stack, errors = balanced(page)
            self.assertEqual(stack, [], guide["slug"])
            self.assertEqual(errors, [], guide["slug"])
            for leftover in ("{css}", "{body}", "{guides_footer}", "{extra_script}", "{{"):
                self.assertNotIn(leftover, page, f"{guide['slug']}: {leftover}")

    def test_guide_links_prefill_the_search(self):
        """가이드의 '내 조건으로 확인하기'는 /?q=... 로 판정 화면을 미리 채운다."""
        page = guides.render_item("cheongnyeon-wolse", self.catalog)
        self.assertIn("/?q=", page)
        self.assertIn("%EC%B2%AD%EB%85%84", page)  # '청년' URL 인코딩
        business = guides.render_item("yebi-changup-package", self.catalog)
        self.assertIn("track=business", business)

    def test_related_postings_use_catalog(self):
        """샘플 카탈로그에 있는 주제는 실제 제도 이름이 페이지에 나온다."""
        page = guides.render_item("cheongnyeon-wolse", self.catalog)
        self.assertIn("청년월세", page)
        self.assertIn("건을 찾았습니다", page)


class GuidesDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_sitemap_includes_index_and_every_guide(self):
        xml = static_files.sitemap_xml(self.catalog, base="https://example.test")
        self.assertIn("<loc>https://example.test/guides/</loc>", xml)
        for guide in guides.GUIDES:
            self.assertIn(f"<loc>https://example.test/guides/{guide['slug']}</loc>", xml)
        self.assertEqual(xml.count("<url>"), xml.count("</url>"))

    def test_llms_txt_lists_guides_with_answers(self):
        text = static_files.llms_txt(self.catalog, base="https://example.test")
        self.assertIn("질문형 가이드", text)
        for guide in guides.GUIDES[:5]:
            self.assertIn(f"https://example.test/guides/{guide['slug']}", text)
            self.assertIn(guide["question"], text)
        self.assertIn(guides.DISCLAIMER_KO, text)

    def test_home_footer_links_guides(self):
        home = web_ui.render_page(self.catalog.meta)
        self.assertIn('href="/guides/"', home)
        self.assertIn("자주 묻는 지원금 질문", home)
        linked = len(re.findall(r'href="/guides/[a-z0-9-]+"', home))
        self.assertGreaterEqual(linked, 12)
        # 전체 보기(details)에도 나머지 가이드가 들어 있다
        self.assertIn(f"가이드 {guides.GUIDE_COUNT}개 전체 보기", home)

    def test_service_meta_points_to_guides(self):
        from subsidy_kr.api import call_tool

        meta = call_tool("get_service_meta", {}, self.catalog)["result"]
        self.assertEqual(meta["guides"]["count"], guides.GUIDE_COUNT)
        self.assertTrue(meta["guides"]["index_url"].endswith("/guides/"))
        self.assertTrue(meta["guides"]["has_faq_json_ld"])

    def test_home_page_reads_q_and_track(self):
        home = web_ui.render_page(self.catalog.meta)
        self.assertIn("URLSearchParams", home)
        self.assertIn("params.get('q')", home)
        self.assertIn("params.get('track')", home)


class GuidesCounterTest(unittest.TestCase):
    def test_guide_paths_have_their_own_bucket(self):
        usage._known_paths.cache_clear()
        self.assertEqual(usage.path_key("/guides/"), "/guides/")
        self.assertEqual(usage.path_key("/guides"), "/guides")
        for slug in guides.slugs()[:5]:
            self.assertEqual(usage.path_key(f"/guides/{slug}"), f"/guides/{slug}")
        # 모르는 슬러그는 한 칸으로 뭉갠다(임의 문자열이 통계에 남지 않게)
        self.assertEqual(usage.path_key("/guides/자유입력-문자열"), "/404")
        self.assertEqual(usage.path_key("/guides/cheongnyeon-wolse?utm=1"),
                         "/guides/cheongnyeon-wolse")

    def test_fixed_paths_include_guides(self):
        self.assertIn("/guides/", usage.FIXED_PATHS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
