"""CLNS·GRNT·FRNC 3종 크로스 링크 회귀 테스트.

GRNT 홈에 형제 서비스 링크가 (1) 창업·소상공인 안내, (2) '같이 쓰는 서비스' 카드,
(3) 푸터에 실제로 렌더되는지 확인한다. 외부 링크는 새 탭+noopener 여야 한다.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from subsidy_kr import web_ui  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402

CLNS_URL = "https://clns-kr.onrender.com/"
FRNC_URL = "https://frnc.onrender.com/"


class CrossLinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = web_ui.render_page(sample_catalog().meta)

    def test_both_sibling_links_are_rendered(self):
        self.assertEqual(self.html.count(CLNS_URL), 3)
        self.assertEqual(self.html.count(FRNC_URL), 3)

    def test_startup_guide_area_links_both_services(self):
        card = self.html[self.html.index("<h2>이 판정은 어떻게 하나요</h2>"):]
        card = card[:card.index("</section>")]
        self.assertIn(CLNS_URL, card)
        self.assertIn(FRNC_URL, card)
        self.assertIn("프랜차이즈", card)
        self.assertIn("수입·유통", card)

    def test_sibling_card_exists(self):
        self.assertIn('id="siblings"', self.html)
        card = self.html[self.html.index('id="siblings"'):]
        card = card[:card.index("</section>")]
        self.assertIn("같이 쓰는 서비스", card)
        self.assertIn(CLNS_URL, card)
        self.assertIn(FRNC_URL, card)

    def test_footer_has_sibling_line(self):
        foot = self.html[self.html.index('<p class="foot">'):]
        foot = foot[:foot.index("</p>")]
        self.assertIn("같이 쓰는 서비스", foot)
        self.assertIn(CLNS_URL, foot)
        self.assertIn(FRNC_URL, foot)

    def test_external_links_are_safe(self):
        for url in (CLNS_URL, FRNC_URL):
            out = self.html
            while True:
                at = out.find(url)
                if at == -1:
                    break
                start = out.rindex("<a ", 0, at)
                tag = out[start:out.index(">", start) + 1]
                self.assertIn('target="_blank"', tag, url)
                self.assertIn('rel="noopener noreferrer"', tag, url)
                out = out[at + len(url):]

    def test_privacy_statement_still_present(self):
        self.assertIn("서버에 저장하지 않습니다", self.html)


if __name__ == "__main__":
    unittest.main()
