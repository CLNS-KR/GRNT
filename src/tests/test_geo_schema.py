"""AI 검색(GEO)·검색엔진용 출력 검사 — JSON-LD·robots·sitemap·llms.txt.

검증하는 것
-----------
1. 모든 JSON-LD 블록이 **유효한 JSON** 이고 `@context`/`@type` 을 갖는지
2. 홈의 Organization · WebSite · WebApplication 이 `@id` 로 서로를 가리키는지
3. 목록 페이지의 CollectionPage/ItemList 숫자가 화면의 건수와 맞는지
4. robots.txt 가 주요 AI 크롤러를 빠뜨리지 않았는지, sitemap 이 XML 로 읽히는지
5. llms.txt 의 링크가 전부 절대 주소인지, 구조화 데이터 안내가 있는지
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ElementTree

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from subsidy_kr import guides, pseo, regions, static_files, web_ui  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402

BASE = "https://example.test"
LD_PATTERN = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)

AI_CRAWLERS = ("GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot", "Google-Extended",
               "CCBot", "Applebot-Extended")


def _blocks(page: str):
    return [json.loads(body) for body in LD_PATTERN.findall(page)]


class JsonLdTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()

    def test_home_graph_is_linked(self):
        page = web_ui.render_page(self.catalog.meta)
        blocks = _blocks(page)
        self.assertEqual(len(blocks), 1)
        graph = blocks[0]["@graph"]
        types = [node["@type"] for node in graph]
        self.assertEqual(types, ["Organization", "WebSite", "WebApplication"])
        ids = {node["@id"] for node in graph}
        website = next(node for node in graph if node["@type"] == "WebSite")
        app = next(node for node in graph if node["@type"] == "WebApplication")
        self.assertEqual(website["publisher"]["@id"], website["@id"].replace("#website", "#org"))
        self.assertIn(website["publisher"]["@id"], ids)
        self.assertEqual(app["isPartOf"]["@id"], website["@id"])
        self.assertEqual(website["potentialAction"]["@type"], "SearchAction")
        self.assertIn("{search_term_string}",
                      website["potentialAction"]["target"]["urlTemplate"])
        self.assertEqual(app["offers"]["price"], "0")

    def test_pseo_index_and_item(self):
        index = pseo.render_index(self.catalog)
        blocks = _blocks(index)
        self.assertEqual([block["@type"] for block in blocks],
                         ["CollectionPage", "BreadcrumbList"])
        self.assertEqual(blocks[0]["mainEntity"]["numberOfItems"], len(pseo.items(self.catalog)))
        self.assertTrue(blocks[0]["mainEntity"]["itemListElement"])

        item = pseo.render_item("cheongnyeon", self.catalog)
        blocks = _blocks(item)
        collection = blocks[0]
        self.assertEqual(collection["@type"], "CollectionPage")
        self.assertEqual(collection["mainEntity"]["numberOfItems"],
                         next(page["count"] for page in pseo.items(self.catalog)
                              if page["slug"] == "cheongnyeon"))
        elements = collection["mainEntity"]["itemListElement"]
        self.assertLessEqual(len(elements), 10)
        self.assertEqual([element["position"] for element in elements],
                         list(range(1, len(elements) + 1)))
        for element in elements:
            self.assertTrue(element["url"].startswith("http"))

    def test_thin_page_still_has_valid_structured_data(self):
        thin = next(page for page in pseo.items(self.catalog) if not page["indexable"])
        page = pseo.render_item(thin["slug"], self.catalog)
        self.assertIn("noindex,follow", page)
        blocks = _blocks(page)
        self.assertEqual(blocks[0]["@type"], "CollectionPage")

    def test_region_hub(self):
        page = regions.render_index(self.catalog)
        blocks = _blocks(page)
        types = [block["@type"] for block in blocks]
        self.assertIn("FAQPage", types)
        self.assertIn("BreadcrumbList", types)
        faq = next(block for block in blocks if block["@type"] == "FAQPage")
        self.assertTrue(faq["mainEntity"])
        for question in faq["mainEntity"]:
            self.assertTrue(question["name"])
            self.assertTrue(question["acceptedAnswer"]["text"])

    def test_guide_faq(self):
        page = guides.render_item(guides.GUIDES[0]["slug"], self.catalog)
        blocks = _blocks(page)
        faq = next(block for block in blocks if block["@type"] == "FAQPage")
        self.assertGreaterEqual(len(faq["mainEntity"]), 3)
        for question in faq["mainEntity"]:
            self.assertEqual(question["@type"], "Question")
            self.assertEqual(question["acceptedAnswer"]["@type"], "Answer")

    def test_no_unescaped_closing_tag_inside_blocks(self):
        for page in (web_ui.render_page(self.catalog.meta),
                     pseo.render_index(self.catalog),
                     pseo.render_item("cheongnyeon", self.catalog),
                     regions.render_index(self.catalog)):
            for body in LD_PATTERN.findall(page):
                self.assertNotIn("</", body.replace("<\\/", ""))

    def test_head_meta_is_complete(self):
        pages = {
            "home": web_ui.render_page(self.catalog.meta),
            "index": pseo.render_index(self.catalog),
            "item": pseo.render_item("cheongnyeon", self.catalog),
            "region": regions.render_index(self.catalog),
        }
        for name, page in pages.items():
            head = page.split("</head>", 1)[0]
            for marker in ('<title>', 'name="description"', 'rel="canonical"',
                           'name="robots"', 'property="og:title"', 'property="og:url"',
                           'name="twitter:card"'):
                self.assertIn(marker, head, f"{name}: {marker}")
            self.assertEqual(head.count("<title>"), 1, name)


class StaticFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()

    def test_robots_allows_ai_crawlers(self):
        text = static_files.robots_txt(BASE)
        self.assertIn("Disallow: /v1/", text)
        self.assertIn(f"Sitemap: {BASE}/sitemap.xml", text)
        self.assertIn("llms.txt", text)
        for crawler in AI_CRAWLERS:
            self.assertIn(f"User-agent: {crawler}", text, crawler)
            block = text.split(f"User-agent: {crawler}", 1)[1].split("\n\n", 1)[0]
            self.assertIn("Allow: /", block, crawler)

    def test_sitemap_is_valid_xml(self):
        xml = static_files.sitemap_xml(self.catalog, base=BASE)
        root = ElementTree.fromstring(xml)
        namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        locs = [node.text for node in root.iter(f"{namespace}loc")]
        self.assertTrue(locs)
        self.assertEqual(len(locs), len(set(locs)))
        for loc in locs:
            self.assertTrue(loc.startswith(BASE + "/"), loc)
        for path in ("/", "/s/", "/guides/", "/regions/", "/about", "/privacy", "/terms"):
            self.assertIn(BASE + path, locs, path)
        for node in root.iter(f"{namespace}lastmod"):
            self.assertRegex(node.text, r"^\d{4}-\d{2}-\d{2}$")
        for node in root.iter(f"{namespace}priority"):
            self.assertGreaterEqual(float(node.text), 0.0)
            self.assertLessEqual(float(node.text), 1.0)

    def test_llms_links_are_absolute(self):
        text = static_files.llms_txt(self.catalog, base=BASE)
        links = re.findall(r"\]\(([^)]+)\)", text)
        self.assertTrue(links)
        for link in links:
            self.assertTrue(link.startswith("http"), link)
        self.assertIn("## 구조화 데이터(JSON-LD)", text)
        self.assertIn("CollectionPage", text)
        for marker in ("## 사람용", "## 기계용 (MCP · JSON-RPC 2.0)", "## 기계용 (REST JSON)",
                       "## 읽는 법", "eligible_likely"):
            self.assertIn(marker, text, marker)

    def test_llms_documents_batch_columns(self):
        text = static_files.llms_txt(self.catalog, base=BASE)
        for column in ("industry_keyword", "entity", "employment", "employees_bracket",
                       "founded_year", "탈락 사유"):
            self.assertIn(column, text, column)

    def test_server_card_matches_tools(self):
        card = static_files.server_card()
        self.assertEqual(len(card["tools"]), 9)
        self.assertFalse(card["authentication"]["required"])
        names = {tool["name"] for tool in card["tools"]}
        self.assertIn("batch_match_clients", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
