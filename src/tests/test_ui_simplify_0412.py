"""0.4.12 화면 단순화 회귀 — 첫 화면에 남는 것과 결과 카드 구조를 고정한다.

사용자 피드백: "가독성이 떨어지고, 선택해야 될 게 많고, 어디서 어떻게 봐야 될지 모르겠다."
그래서 다음을 테스트로 못 박는다.

1. 첫 화면 폼에는 **대상 2버튼 · 지역 1칸 · 검색어 1칸 · 큰 버튼 · 예시 3개** 만 보인다.
2. 나이·소득·가구원·상황·업력·지난 공고 같은 세부 조건은 **접힌 details** 안에 있다.
3. 머리글은 한 줄(마크+이름), 실데이터 건수는 푸터의 기준일 한 줄로 내려간다.
4. 결과는 **요약 상자 → 공유 → 설명 → 판정 칩 → 카드** 순서이고, 카드는
   제목 · 지원 내용 · 마감일·신청처 · 자세히 보기 · 바로 신청만 갖는다.
5. 보조 기능(거래처 리포트·일괄 매칭·자매 서비스·문의)은 결과 아래에 있고, 일괄 매칭은 접혀 있다.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from subsidy_kr import web_ui  # noqa: E402
from subsidy_kr.catalog import sample_catalog  # noqa: E402

DETAIL_MARKERS = ('id="birth_year"', 'id="household_size"', 'id="income_band"',
                  'name="situation"', 'id="children_years"', 'id="biz_years"',
                  'id="include_closed"')


def search_head(html: str) -> str:
    """`#search-card` 안에서 세부 조건(details) 앞까지 = 첫 화면에 보이는 폼."""
    start = html.index('id="search-card"')
    end = html.index('id="more-conditions"')
    return html[start:end]


class FirstScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = web_ui.render_page(sample_catalog().meta)
        cls.head = search_head(cls.html)

    def test_only_essential_controls_are_above_the_fold(self):
        # 시·군·구 칸은 시·도를 고를 때만 보인다(기본 hidden) — 보이는 컨트롤만 센다.
        start = self.head.index('id="sigungu-field"')
        end = self.head.index("</label>", self.head.index('id="sigungu"')) + len("</label>")
        visible = self.head[:start] + self.head[end:]
        controls = re.findall(r"<(?:input|select|button)\b", visible)
        # 대상 2 · 지역 1 · 검색어 1 · 찾기 1 · 예시 3 = 8개 이하
        self.assertLessEqual(len(controls), 8, f"{len(controls)}개: {controls}")
        self.assertEqual(visible.count('name="track"'), 2)
        for marker in ('id="sido"', 'id="keyword"', 'id="run"'):
            self.assertIn(marker, visible, marker)

    def test_sigungu_appears_only_after_a_sido_is_chosen(self):
        self.assertIn('<label class="field" id="sigungu-field" hidden>', self.head)
        self.assertGreater(self.head.index('id="sigungu-field"'), self.head.index('id="sido"'))
        self.assertIn("sigunguField.hidden = !sido.value;", self.html)

    def test_detail_filters_start_collapsed(self):
        at = self.html.rindex("<details", 0, self.html.index('id="more-conditions"'))
        self.assertNotIn(" open", self.html[at:self.html.index(">", at) + 1])
        base = self.html.index('id="more-conditions"')
        for marker in DETAIL_MARKERS:
            self.assertGreater(self.html.index(marker), base, marker)

    def test_header_is_one_line_without_badges(self):
        header = self.html[self.html.index('<header class="top">'):self.html.index("</header>")]
        self.assertNotIn("<span", header)
        self.assertNotIn("<p", header)
        self.assertIn('<div class="brand-name">GRNT</div>', header)

    def test_hero_is_one_title_and_one_line(self):
        self.assertEqual(self.html.count("<h1"), 1)
        hero = self.html[self.html.index('<section class="hero">'):]
        hero = hero[:hero.index("</section>")]
        self.assertEqual(len(re.findall(r"<p\b", hero)), 1)
        self.assertIn("지원금", hero)

    def test_data_counts_moved_to_the_quiet_footer_line(self):
        synced = web_ui.render_page({"catalog_state": "synced", "generated_on": "2026-11-22",
                                     "stats": {"services": 13532, "personal": 11990,
                                               "business": 1542}})
        self.assertIn('<p class="data-note">', synced)
        self.assertIn("실데이터 기준일", synced)
        # 기준일·건수는 문의 카드 아래(푸터) 한 줄로 내려간다
        self.assertGreater(synced.index('<p class="data-note">'),
                           synced.index('id="inquiry-card"'))
        # 샘플일 때는 반대로 첫 화면 위에 경고를 띄운다
        self.assertIn("샘플 데이터로 동작", self.html)
        self.assertLess(self.html.index("샘플 데이터로 동작"),
                        self.html.index('id="search-card"'))

    def test_examples_are_three_and_run_immediately(self):
        chips = re.findall(r'<button type="button" data-kw="[^"]+" data-track="[^"]+">',
                           self.html)
        self.assertEqual(len(chips), 3, chips)
        self.assertIn("querySelectorAll('.examples button')", self.html)
        block = self.html[self.html.index("querySelectorAll('.examples button')"):]
        self.assertIn("search();", block[:800])


class ResultScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = web_ui.render_page(sample_catalog().meta)
        cls.card_script = cls.html[cls.html.index("function buildCard(row)"):]
        cls.card_script = cls.card_script[:cls.card_script.index("function renderResults")]

    def test_summary_box_is_first_then_filters_then_cards(self):
        order = ['id="results-card"', 'id="summary"', 'id="share-bar"', 'id="results-sub"',
                 'id="counts"', 'id="results"', 'id="more-results"']
        positions = [self.html.index(marker) for marker in order]
        self.assertEqual(positions, sorted(positions), order)

    def test_summary_reads_total_and_applicable_counts(self):
        self.assertIn("건 찾았어요", self.html)
        self.assertIn("'신청 가능 '", self.html)
        self.assertIn("조건 확인 필요", self.html)
        # 숫자는 잘린 목록이 아니라 서버 집계에서 온다
        self.assertIn("result.kind_verdict_counts", self.html)
        self.assertIn("result.kind_counts", self.html)

    def test_card_has_only_the_five_parts(self):
        for marker in ("el('h3'", "el('p', 'amount'", "'마감 '", "'자세히 보기'",
                       "'신청하러 가기'", "'지원 내용: '"):
            self.assertIn(marker, self.card_script, marker)
        # 지원 내용은 두 줄까지만 보이고 전문은 펼친 곳에 있다
        self.assertIn("-webkit-line-clamp:2", web_ui.BASE_CSS)
        # 카드에 붙던 트랙·종류 태그는 없앴다
        self.assertNotIn("el('span', 'tag'", self.card_script)

    def test_filters_are_one_row_not_three_levels(self):
        for gone in ("지원금·바우처", "교육·건강·프로그램", "field-bar", "kindTabs"):
            self.assertNotIn(gone, self.html, gone)
        self.assertIn("verdictTotal(result", self.html)
        self.assertIn("refetchVerdict(code)", self.html)
        self.assertIn("전체 결과로 돌아가기", self.html)

    def test_cards_are_sorted_and_paged(self):
        self.assertIn("function sortRows(rows)", self.html)
        self.assertIn("VERDICT_RANK", self.html)
        self.assertIn("var PAGE_SIZE = 10;", self.html)
        self.assertIn("더 보기 (", self.html)


class SecondaryBlocksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = web_ui.render_page(sample_catalog().meta)

    def test_secondary_blocks_come_after_results(self):
        results = self.html.index('id="results-card"')
        for anchor in ('id="agent-card"', 'id="report-card"', 'id="how"',
                       'id="batch-card"', 'id="siblings"', 'id="inquiry-card"'):
            self.assertGreater(self.html.index(anchor), results, anchor)

    def test_batch_matching_is_folded(self):
        block = self.html[self.html.index('<section class="card" id="batch-card">'):]
        self.assertIn('<details class="block">', block[:200])
        # 접혀 있어도 기능 요소는 그대로다
        for marker in ('id="batch-csv"', 'id="batch-run"', 'id="batch-sample"'):
            self.assertIn(marker, block, marker)

    def test_agent_report_is_a_secondary_track(self):
        self.assertNotIn('value="agent"', search_head(self.html))
        self.assertIn('value="agent"', self.html)
        self.assertIn('id="agent-fields"', self.html)
        self.assertIn('id="agent-run"', self.html)

    def test_no_sibling_link_before_results(self):
        results = self.html.index('id="results-card"')
        self.assertNotIn("clns-kr.onrender.com", self.html[:results])


if __name__ == "__main__":
    unittest.main(verbosity=2)
