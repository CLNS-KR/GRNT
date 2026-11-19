"""창업·기업 공고 정규화 테스트 — 실호출 응답 모양을 그대로 흉내 낸다."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import programs, sample_programs  # noqa: E402

KSTARTUP_ROW = {
    "pbanc_sn": "179839",
    "biz_pbanc_nm": "2027년 상반기 경기도여성창업보육센터 입주기업 모집 공고",
    "pbanc_ntrp_nm": "경기도일자리재단 남부사업본부장",
    "sprv_inst": "공공기관",
    "biz_prch_dprt_nm": "기업지원팀",
    "supt_biz_clsfc": "시설ㆍ공간ㆍ보육",
    "aply_trgt": "일반기업",
    "aply_trgt_ctnt": ("○입주모집 공고일 현재 경기도 내에 주소를 둔 여성 예비창업자\r\n"
                       "○경기도 내에 주된 사무소를 둔 창업 후 3년 이내의 여성기업"),
    "supt_regin": "경기",
    "pbanc_rcpt_bgng_dt": "20261118",
    "pbanc_rcpt_end_dt": "20261204",
    "biz_enyy": "3년미만",
    "biz_trgt_age": "만 20세 이상 ~ 만 39세 이하",
    "rcrt_prgs_yn": "Y",
    "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179839",
    "aply_mthd_onli_rcpt_istc": "https://www.dreammaru.or.kr/apply",
    "support_ctnt": " 지원내용 ○ 사무실, 사무집기 등 제공\r ○ 사업화지원금 지원",
    "pbanc_ctnt": "창업활동 지원공간을 제공합니다.",
    "eval_method": "1차 적격심사, 2차 면접심사",
    "prch_cnpl_no": "0312709779",
    "prfn_matr": "여성창업 우대",
}

BIZINFO_ROW = {
    "pblancId": "PBLN_000000000128009",
    "pblancNm": "[경기] 구리시 2026년 농산물유통사업 물류비 지원 신청 공고",
    "jrsdInsttNm": "경기도",
    "excInsttNm": "기초자치단체",
    "bsnsSumryCn": "<p>구리시 생산 농산물의 <b>물류비</b> 부담 경감</p><p>&nbsp;지원합니다.</p>",
    "pldirSportRealmLclasCodeNm": "경영",
    "reqstBeginEndDe": "2026-12-01 ~ 2026-12-08",
    "trgetNm": "중소기업",
    "hashtags": "경영,경기,소상공인,물류비",
    "reqstMthPapersCn": "온라인 접수",
    "refrncNm": "구리시 농업정책팀 031-000-0000",
    "pblancUrl": "https://www.bizinfo.go.kr/sii/128009",
    "rceptEngnHmpgUrl": "https://www.bizinfo.go.kr/sii/128009",
    "creatPnttm": "2026-11-18 09:00:00",
    "updtPnttm": "2026-11-18 09:00:00",
}


class YearParseTest(unittest.TestCase):
    def test_single_value(self):
        self.assertEqual(programs.parse_years("7년미만")["max_years"], 7)
        self.assertEqual(programs.parse_years("3년미만")["max_years"], 3)
        self.assertIsNone(programs.parse_years("예비창업자")["max_years"])

    def test_multiple_options_take_the_widest(self):
        # 실제 API 는 '허용하는 업력 목록'을 쉼표로 준다. 좁은 쪽을 고르면 오답이 된다.
        text = "예비창업자,1년미만,2년미만,3년미만,5년미만,7년미만,10년미만"
        self.assertEqual(programs.parse_years(text)["max_years"], 10)

    def test_prose_years(self):
        self.assertEqual(programs.parse_years_from_prose("창업 3년 이내 창업기업"), 3)
        self.assertIsNone(programs.parse_years_from_prose("누구나"))


class AgeParseTest(unittest.TestCase):
    def test_range(self):
        self.assertEqual(programs.parse_age_range("만 20세 이상 ~ 만 39세 이하"),
                         {"min_age": 20, "max_age": 39})

    def test_inclusive_and_exclusive_upper_bound(self):
        self.assertEqual(programs.parse_age_range("만 39세 이하")["max_age"], 39)
        self.assertEqual(programs.parse_age_range("만 39세 미만")["max_age"], 38)

    def test_options_union_covers_all_ages(self):
        text = "만 20세 미만,만 20세 이상 ~ 만 39세 이하,만 40세 이상"
        self.assertEqual(programs.parse_age_range(text), {"min_age": None, "max_age": None})

    def test_open_upper(self):
        self.assertEqual(programs.parse_age_range("만 40세 이상"),
                         {"min_age": 40, "max_age": None})


class EntityParseTest(unittest.TestCase):
    def test_pre_startup_only(self):
        self.assertEqual(programs.parse_entities("공고일 기준 사업자등록이 없는 예비창업자"),
                         ["pre_startup"])

    def test_pre_and_operating(self):
        entities = programs.parse_entities("여성 예비창업자 또는 창업 후 3년 이내의 여성기업")
        self.assertIn("pre_startup", entities)
        self.assertIn("startup", entities)

    def test_small_business_and_sme(self):
        entities = programs.parse_entities("소상공인(연 매출 10억 원 이하 개인사업자)")
        self.assertIn("small_business", entities)
        self.assertIn("sole_proprietor", entities)
        self.assertIn("sme", programs.parse_entities("중소기업"))

    def test_gender_and_region(self):
        self.assertEqual(programs.parse_gender("여성 예비창업자"), "female")
        self.assertIsNone(programs.parse_gender("청년 창업자"))
        self.assertEqual(programs.parse_region_text("전국"), None)
        self.assertEqual(programs.parse_region_text("경기")["sido"], "경기도")
        self.assertIsNone(programs.parse_region_text("서울,부산"))

    def test_recruiting(self):
        self.assertEqual(programs.parse_recruiting("Y"), "open")
        self.assertEqual(programs.parse_recruiting("N"), "closed")
        self.assertEqual(programs.parse_recruiting(""), "unknown")


class KStartupNormalizeTest(unittest.TestCase):
    def setUp(self):
        self.record = programs.normalize_kstartup(KSTARTUP_ROW)

    def test_ids_and_source(self):
        self.assertEqual(self.record["서비스ID"], "KSU-179839")
        self.assertEqual(self.record["track"], "business")
        self.assertEqual(self.record["source"], "kstartup")
        self.assertEqual(self.record["region"]["sido"], "경기도")

    def test_deadline_is_readable_by_deadline_parser(self):
        self.assertEqual(self.record["신청기한"], "2026. 11. 18. ~ 2026. 12. 4.")
        from subsidy_kr import deadlines

        parsed = deadlines.parse_deadline(self.record["신청기한"], today=None)
        self.assertEqual(parsed["end_date"], "2026-12-04")

    def test_business_block(self):
        block = self.record["business"]
        self.assertEqual(block["max_years"], 3)
        self.assertEqual((block["min_age"], block["max_age"]), (20, 39))
        self.assertEqual(block["gender"], "female")
        self.assertEqual(block["recruiting"], "open")
        self.assertIn("pre_startup", block["entity"])
        self.assertIn("startup", block["entity"])
        self.assertTrue(block["parsed"])

    def test_text_fields_strip_html_and_whitespace(self):
        self.assertNotIn("\r", self.record["지원대상"])
        self.assertNotIn("\n", self.record["지원내용"])
        self.assertIn("선정방법", self.record["선정기준"])
        self.assertEqual(self.record["전화문의"], "031-270-9779")

    def test_online_url_is_not_detail_url(self):
        self.assertNotEqual(self.record["온라인신청사이트URL"],
                            self.record["상세조회URL"])

    def test_multi_option_age(self):
        row = dict(KSTARTUP_ROW, biz_trgt_age="만 20세 미만,만 20세 이상 ~ 만 39세 이하,만 40세 이상")
        record = programs.normalize_kstartup(row)
        self.assertEqual((record["business"]["min_age"], record["business"]["max_age"]),
                         (None, None))


class BizinfoNormalizeTest(unittest.TestCase):
    def setUp(self):
        self.record = programs.normalize_bizinfo(BIZINFO_ROW)

    def test_html_is_stripped_but_wording_kept(self):
        summary = self.record["지원내용"]
        self.assertNotIn("<p>", summary)
        self.assertIn("물류비", summary)
        self.assertIn("부담 경감", summary)

    def test_source_and_region(self):
        self.assertEqual(self.record["서비스ID"], "BIZ-PBLN_000000000128009")
        self.assertEqual(self.record["source"], "bizinfo")
        self.assertEqual(self.record["region"]["sido"], "경기도")

    def test_executor_fallback(self):
        # '기초자치단체'는 수행기관 이름이 아니라 분류값이다.
        self.assertEqual(self.record["접수기관"], "경기도")

    def test_hashtags_are_kept_for_search(self):
        self.assertIn("물류비", self.record["extra"]["해시태그"])


class CurrencyTest(unittest.TestCase):
    def test_closed_and_expired(self):
        current = {"business": {"recruiting": "open"}, "신청기한": "2026. 11. 1. ~ 2026. 12. 31."}
        self.assertTrue(programs.is_current(current, today=__import__("datetime").date(2026, 11, 19)))
        closed = {"business": {"recruiting": "closed"}, "신청기한": "2026. 11. 1. ~ 2026. 12. 31."}
        self.assertFalse(programs.is_current(closed))
        expired = {"business": {"recruiting": "open"}, "신청기한": "2025. 1. 1. ~ 2025. 2. 1."}
        self.assertFalse(programs.is_current(expired, today=__import__("datetime").date(2026, 11, 19)))
        unknown = {"business": {"recruiting": "unknown"}, "신청기한": "예산 소진시까지"}
        self.assertTrue(programs.is_current(unknown))

    def test_grace_period(self):
        from datetime import date

        recent = {"business": {"recruiting": "open"}, "신청기한": "2026. 11. 1. ~ 2026. 11. 10."}
        self.assertTrue(programs.is_current(recent, today=date(2026, 11, 19), grace_days=30))
        self.assertFalse(programs.is_current(recent, today=date(2026, 11, 19), grace_days=3))


class SampleProgramTest(unittest.TestCase):
    def test_samples_are_flagged_and_parse(self):
        rows = sample_programs.services()
        self.assertEqual(len(rows), 12)
        for row in rows:
            self.assertEqual(row["track"], "business")
            self.assertEqual(row["source"], "sample")
            self.assertTrue(row["서비스ID"].startswith(("KSU-", "BIZ-")))
            self.assertIn("business", row)
            self.assertTrue(row["business"]["parsed"])

    def test_summary_line(self):
        block = {"entity": ["pre_startup"], "max_years": 3, "min_age": 20, "max_age": 39,
                 "recruiting": "open"}
        text = programs.business_summary(block)
        self.assertIn("예비창업자", text)
        self.assertIn("업력 3년 이내", text)
        self.assertIn("만 20~39세", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
