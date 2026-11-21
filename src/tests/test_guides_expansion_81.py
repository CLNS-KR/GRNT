"""0.4.5 — 질문형 지원금 가이드 20종 추가(61 → 81) 회귀 테스트.

검증 항목
1. 가이드가 81개이고, 새 20종이 조건·착각·관련 링크·질문 형식을 지킨다.
2. 새 가이드가 금액을 고정하지 않고(공고로 확인), FAQPage·BreadcrumbList 를 싣는다.
3. 사이트맵·llms.txt·인덱스·`/v1/meta` 가 새 가이드를 자동 반영한다.
4. 브리프가 지정한 주제(임산부 교통비·초기창업·전세보증·배우자 출산휴가·양육수당·
   청년도전·육아기 단축·국민연금 추납·기한 후 신청·도약계좌 해지·통신비 감면·피부양자·
   장애인 고용·폐업 정리·결제 수수료·환수·중소기업 정책자금·마감 관리)가 모두 들어 있다.

실행: PYTHONPATH=src python3 -m unittest tests.test_guides_expansion_81 -q
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import guides, static_files, web_ui  # noqa: E402
from subsidy_kr.api import call_tool  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402

NEW_SLUGS = (
    "jeonse-bojang-guarantee",
    "cheongnyeon-jeonse-imdae",
    "imsinbu-gyotongbi",
    "baeuja-chulsan-hyuga-geupyeo",
    "yangyuk-suyang-eorinijib",
    "cheongnyeon-dojeon-jiwon",
    "yuga-gigan-danchuk-geupyeo",
    "gukmin-yeon-geum-chunap",
    "geullo-jangnyeogeum-gihanhu",
    "cheongnyeon-doyak-junghae",
    "tongsinbi-gammyeon",
    "geongangboheom-pibuyangja",
    "chogi-changup-package",
    "sabupjang-jangaein-goyong-jiwon",
    "pyeopji-geunroja-jeongri",
    "sosanggongin-gyeolje-sujeung",
    "jangnyeogeum-hwansu",
    "jungso-gieop-jeongchaekjageum",
    "madam-gonggo-calendar",
    "gonggo-munseo-hwagin",
)


def json_ld_blocks(page):
    return [json.loads(block) for block in
            re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)]


class ExpansionShareTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_total_is_eighty_one(self):
        self.assertEqual(guides.GUIDE_COUNT, 81)
        self.assertEqual(guides.GUIDE_COUNT, len(guides.GUIDES))
        self.assertEqual(len(set(NEW_SLUGS)), 20)

    def test_twenty_new_guides_are_complete(self):
        for slug in NEW_SLUGS:
            guide = guides.by_slug(slug)
            with self.subTest(slug=slug):
                self.assertIsNotNone(guide)
                self.assertRegex(slug, r"^[a-z0-9-]+$")
                self.assertIn(guide["category"], guides.CATEGORY_LABEL)
                self.assertIn(guide["track"], ("personal", "business", "agent"))
                self.assertGreaterEqual(len(guide["conditions"]), 4)
                self.assertGreaterEqual(len(guide["pitfalls"]), 2)
                self.assertGreaterEqual(len(guide["keywords"]), 2)
                self.assertTrue(guide["question"].endswith("?"))
                self.assertGreaterEqual(len(guide["one_line"]), 60)
                for other in guide["related"]:
                    self.assertIsNotNone(guides.by_slug(other), f"{slug} → {other}")
                    self.assertNotEqual(other, slug)

    def test_new_questions_are_distinct(self):
        questions = [guide["question"] for guide in guides.GUIDES]
        self.assertEqual(len(questions), len(set(questions)))

    def test_new_guides_do_not_fix_amounts(self):
        for slug in NEW_SLUGS:
            page = guides.render_item(slug, self.catalog)
            with self.subTest(slug=slug):
                self.assertIsNone(re.search(r"\d[\d,]*\s*만?원", page))

    def test_new_guides_render_with_faq_and_breadcrumb(self):
        for slug in NEW_SLUGS:
            page = guides.render_item(slug, self.catalog)
            with self.subTest(slug=slug):
                self.assertIsNotNone(page)
                types = [block.get("@type") for block in json_ld_blocks(page)]
                self.assertIn("FAQPage", types)
                self.assertIn("BreadcrumbList", types)
                self.assertIn("지금 열려 있는 관련 공고", page)
                self.assertIn("흔히 하는 착각", page)
                self.assertIn(guides.DISCLAIMER_KO, page)
                self.assertIn("index,follow", page)

    def test_new_guides_reach_sitemap_llms_and_index(self):
        xml = static_files.sitemap_xml(self.catalog, base="https://example.test")
        text = static_files.llms_txt(self.catalog, base="https://example.test")
        index = guides.render_index(self.catalog)
        for slug in NEW_SLUGS:
            with self.subTest(slug=slug):
                self.assertIn(f"<loc>https://example.test/guides/{slug}</loc>", xml)
                self.assertIn(f"https://example.test/guides/{slug}", text)
                self.assertIn(f"/guides/{slug}", index)
        self.assertIn(f"자주 묻는 지원금 질문 {guides.GUIDE_COUNT}개", index)

    def test_meta_reports_eighty_one(self):
        meta = call_tool("get_service_meta", {}, self.catalog)["result"]
        self.assertEqual(meta["guides"]["count"], 81)
        self.assertEqual(meta["guides"]["count"], guides.GUIDE_COUNT)

    def test_home_lists_total(self):
        home = web_ui.render_page(self.catalog.meta)
        self.assertIn(f"가이드 {guides.GUIDE_COUNT}개 전체 보기", home)

    def test_briefed_topics_are_covered(self):
        text = " ".join(f"{g['slug']} {g['question']} {g['topic']} {g['one_line']}"
                        for g in guides.GUIDES)
        for needle in ("임산부 교통비", "초기창업패키지", "전세보증금 반환보증", "배우자 출산휴가",
                       "양육수당", "청년도전지원", "육아기 근로시간 단축", "국민연금 추납",
                       "기한 후 신청", "중도해지", "통신비 감면", "피부양자",
                       "장애인을 고용", "폐업", "결제 수수료", "환수",
                       "중소기업 정책자금", "마감일"):
            self.assertIn(needle, text, needle)

    def test_new_guides_spread_across_categories(self):
        categories = {guides.by_slug(slug)["category"] for slug in NEW_SLUGS}
        self.assertGreaterEqual(len(categories), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
