"""지자체 자체 복지포털 파서·커버리지 안내·지난 공고 필터 테스트."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import deadlines, engine, local_portals  # noqa: E402

TODAY = date(2026, 11, 19)


class LocalPortalsTest(unittest.TestCase):
    def test_parse_bokjion_filters_expired(self):
        html_doc = """
        <ul>
          <li><a href="/bokjion/program/programInfoDetail.do?prgm_seq=1791&amp;pgno=1">
            <div class="list-con">
              <p class="tit">건강검진 수검 이벤트</p>
              <p class="writer"><span>부평구 전체</span><span>전 주민</span></p>
              <p class="date">신청기간 : 2026-11-17 ~ 2026-11-30</p>
            </div>
          </a></li>
          <li><a href="/bokjion/program/programInfoDetail.do?prgm_seq=1001&amp;pgno=9">
            <div class="list-con">
              <p class="tit">지난 이벤트</p>
              <p class="writer"><span>부평구 전체</span></p>
              <p class="date">신청기간 : 2025-01-01 ~ 2025-12-31</p>
            </div>
          </a></li>
        </ul>
        """
        rows = local_portals.parse_bokjion_list_html(html_doc, today=TODAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["서비스ID"], "BOKJION-1791")
        self.assertEqual(rows[0]["source"], "local_portal")

    def test_coverage_status_distinguishes_supported_and_unsupported(self):
        bp = local_portals.coverage_status("인천광역시", "부평구")
        self.assertTrue(bp["supported"])
        self.assertIsNone(bp["notice_ko"])

        seoul = local_portals.coverage_status("서울특별시", "강남구")
        self.assertFalse(seoul["supported"])
        self.assertIn("강남구", seoul["notice_ko"])

        busan = local_portals.coverage_status("부산광역시", "해운대구")
        self.assertFalse(busan["supported"])
        self.assertIn("해운대구", busan["notice_ko"])

        busan_sido = local_portals.coverage_status("부산광역시")
        self.assertTrue(busan_sido["supported"])

    def test_parse_gg24_and_sejong_and_broso(self):
        gg_html = """
        <ul>
          <li class="board-boxlist__item">
            <a href="/svcreqst/selectSvcReqst.do?svc_seq=945" class="board-boxlist__con">
              <div class="board-boxlist--top__badge">접수중</div>
              <h4 class="board-boxlist--bottom__tit">2026년 경기 청년 지원사업</h4>
              <p class="board-boxlist--bottom__sub">2026.04.20(월) ~ 2026.12.31(목)</p>
              <span class="badge__text">온라인 접수</span>
            </a>
          </li>
          <li class="board-boxlist__item">
            <a href="/svcreqst/selectSvcReqst.do?svc_seq=100" class="board-boxlist__con">
              <div class="board-boxlist--top__badge">접수마감</div>
              <h4 class="board-boxlist--bottom__tit">마감된 사업</h4>
              <p class="board-boxlist--bottom__sub">2025.01.01 ~ 2025.12.31</p>
            </a>
          </li>
        </ul>
        """
        gg_rows = local_portals.parse_gg24_list_html(gg_html, today=TODAY)
        self.assertEqual(len(gg_rows), 1)
        self.assertEqual(gg_rows[0]["서비스ID"], "GG24-945")

        sj_html = """
        <a href="javascript:fn_search_detail('2188016');" class="card-title">아빠장려금 지원</a>
        <p class="card-desc">세종시 육아휴직 남성 장려금</p>
        """
        sj_rows = local_portals.parse_sejong_subsidy_html(sj_html, today=TODAY)
        self.assertEqual(len(sj_rows), 1)
        self.assertEqual(sj_rows[0]["서비스ID"], "SEJONG-2188016")

        broso_html = """
        <a href="javascript:fn_selectServiceSeachDet('P01', '12');">
          <dl>
            <dt>아동심리지원 <span>[해운대구청]</span></dt>
            <dd>아동 정서 발달 지원</dd>
          </dl>
        </a>
        """
        br_rows = local_portals.parse_broso_list_html(broso_html, slug="busan", sido="부산광역시", today=TODAY)
        self.assertEqual(len(br_rows), 1)
        self.assertIn("해운대구", br_rows[0]["소관기관명"])

    def test_deadlines_short_end_and_past_year_and_since(self):
        d1 = deadlines.parse_deadline("2026. 2. 2.~11. 30.", TODAY)
        self.assertEqual(d1["end_date"], "2026-11-30")
        self.assertFalse(d1.get("expired", False))

        d2 = deadlines.parse_deadline("2025.10.~12월 중 신청", TODAY)
        self.assertTrue(d2.get("expired"))

        d3 = deadlines.parse_deadline("2012. 7. 1. 이후", TODAY)
        self.assertFalse(d3.get("expired", False))
        self.assertIsNone(d3["end_date"])

    def test_normalize_profile_string_region(self):
        prof = engine.normalize_profile({"region": "인천 서구", "age": 34}, today=TODAY)
        self.assertEqual(prof["region"]["sido"], "인천광역시")
        self.assertEqual(prof["region"]["sigungu"], "서구")


if __name__ == "__main__":
    unittest.main(verbosity=2)
