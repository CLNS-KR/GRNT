"""거래처 일괄 매칭 1.1 — 세무·노무 사무소 파일에 맞춘 정교화 테스트.

검증하는 것
-----------
1. 입력 정교화 — 직원 수 구간·기업 형태(Y/N 포함)·세부 업종 키워드·고용 이슈·설립연도
2. 고용 이슈 문구 판별 — '고령군'·'청년창업센터' 같은 오탐을 잡지 않는지
3. 탈락 사유 — 사유별 건수가 후보 수와 맞아떨어지고, 예시에 요건이 붙는지
4. 판정 근거 — 결과 1건마다 엔진 판정(why)에서 온 근거·확인 항목이 붙는지
5. 순위 — 고용 이슈·세부 업종이 판정을 바꾸지 않고 순위만 올리는지
6. 내보내기 — CSV·HTML·마크다운에 새 칸이 생기고 상호·사업자번호 값은 여전히 없는지
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from subsidy_kr import batch_client, engine, programs  # noqa: E402
from subsidy_kr.catalog import load_catalog, sample_catalog  # noqa: E402

REAL_CATALOG = os.path.join(PROJECT, "data", "gov24", "catalog.json")
HAS_DATA = os.path.exists(REAL_CATALOG) or os.path.exists(REAL_CATALOG + ".gz")

HEADER = ["client_ref", "상호명", "사업자번호", "업종", "업종키워드", "기업형태",
          "고용이슈", "직원수구간", "연매출", "업력", "설립연도", "지역", "비고"]


def _csv(rows, header=None):
    header = header or HEADER
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([str(row.get(column, "")) for column in header])
    return buffer.getvalue()


def _card(**overrides):
    """`_pre_score`·`_select_top` 시험용 카드(색인 구조와 같은 모양)."""
    card = {
        "svc": type("Svc", (), {"name": overrides.get("name", "공고")})(),
        "categories": ["labor"], "primary": "labor", "days_left": 20,
        "industry_required": False, "industries": frozenset(), "level": "national",
        "sido": "", "sigungu": "", "entities": (), "max_years": None, "min_age": None,
        "max_age": None, "gender": None, "employment": frozenset(),
        "search_text": "",
    }
    card.update({key: value for key, value in overrides.items() if key in card})
    return card


class InputParseTest(unittest.TestCase):
    def test_employees_bracket(self):
        self.assertEqual(batch_client.parse_employees_bracket("5인 미만")[0], 4)
        self.assertIn("미만", batch_client.parse_employees_bracket("5인 미만")[1])
        self.assertEqual(batch_client.parse_employees_bracket("10~49명")[0], 49)
        self.assertEqual(batch_client.parse_employees_bracket("3명")[0], 3)
        amount, note = batch_client.parse_employees_bracket("50인 이상")
        self.assertEqual(amount, 50)
        self.assertIn("하한", note)
        self.assertEqual(batch_client.parse_employees_bracket("제조")[0], None)

    def test_entity_aliases(self):
        self.assertEqual(batch_client.resolve_entity("소상공인"), "small_business")
        self.assertEqual(batch_client.resolve_entity("중소기업"), "sme")
        self.assertEqual(batch_client.resolve_entity("법인"), "corporate")
        self.assertEqual(batch_client.resolve_entity("벤처기업"), "venture")
        self.assertEqual(batch_client.resolve_entity("창업기업"), "startup")
        self.assertEqual(batch_client.resolve_entity("Y"), "small_business")
        self.assertEqual(batch_client.resolve_entity("N"), "sme")
        self.assertIsNone(batch_client.resolve_entity("모름"))

    def test_startup_entity_is_judged_as_sme(self):
        """'창업기업'을 그대로 넘기면 중소기업 공고가 통째로 빠진다 — 판정은 중소기업으로."""
        self.assertEqual(batch_client._entity_for_engine("startup"), "sme")
        self.assertEqual(batch_client._entity_for_engine("small_business"), "small_business")

    def test_industry_keywords(self):
        slugs, tokens = batch_client.resolve_industry_keywords("한식 음식점")
        self.assertEqual(slugs, ["food"])
        self.assertIn("한식", tokens)
        slugs, tokens = batch_client.resolve_industry_keywords("전자부품 가공")
        self.assertEqual(slugs[0], "manufacturing")
        self.assertIn("전자부품", tokens)
        self.assertEqual(batch_client.resolve_industry_keywords("알수없는품목"), ([], []))

    def test_employment_input(self):
        self.assertEqual(batch_client.parse_employment("청년, 육아휴직"),
                         ["youth", "parental_leave"])
        self.assertEqual(batch_client.parse_employment("고령/장애인"),
                         ["senior", "disabled"])
        self.assertEqual(batch_client.parse_employment(""), [])
        # 코드로 넣어도 읽는다
        self.assertEqual(batch_client.parse_employment("social_insurance"), ["social_insurance"])

    def test_csv_reads_new_columns(self):
        text = _csv([{"client_ref": "N-1", "업종": "도소매", "업종키워드": "온라인몰",
                      "기업형태": "소상공인", "고용이슈": "청년, 육아휴직",
                      "직원수구간": "5인 미만", "연매출": "1억~2억", "지역": "서울특별시 마포구"}])
        client = batch_client.parse_clients_csv(text)["clients"][0]
        self.assertEqual(client["industry"], "retail")
        self.assertEqual(client["industry_terms"], ["온라인몰"])
        self.assertEqual(client["entity"], "small_business")
        self.assertEqual(client["employment"], ["youth", "parental_leave"])
        self.assertEqual(client["employees"], 4)
        self.assertEqual(client["employees_source"], "구간")

    def test_founded_year_becomes_business_age(self):
        text = _csv([{"client_ref": "F-1", "업종": "음식숙박", "설립연도": "2022",
                      "지역": "부산광역시 해운대구"}])
        client = batch_client.parse_clients_csv(text)["clients"][0]
        expected = datetime.now().year - 2022
        self.assertEqual(client["business_age_years"], float(expected))
        self.assertEqual(client["years_source"], "설립연도")
        self.assertTrue(any("설립연도" in note for note in client["parse_notes"]))

    def test_unknown_industry_keyword_is_not_echoed(self):
        text = _csv([{"client_ref": "K-1", "업종": "음식숙박",
                      "업종키워드": "가상상호ABC", "지역": "서울특별시 마포구"}])
        parsed = batch_client.parse_clients_csv(text)
        self.assertEqual(parsed["clients"][0]["industry_terms"], [])
        self.assertNotIn("가상상호ABC", json.dumps(parsed, ensure_ascii=False))

    def test_sensitive_columns_still_dropped_with_new_columns(self):
        text = _csv([{"client_ref": "S-1", "상호명": "가상상사", "사업자번호": "111-22-33333",
                      "업종": "음식숙박", "고용이슈": "청년", "기업형태": "소상공인",
                      "지역": "서울특별시 마포구"}])
        parsed = batch_client.parse_clients_csv(text)
        self.assertIn("상호명", parsed["columns_dropped_sensitive"])
        self.assertIn("사업자번호", parsed["columns_dropped_sensitive"])
        serialized = json.dumps(parsed, ensure_ascii=False)
        for value in ("가상상사", "111-22-33333"):
            self.assertNotIn(value, serialized)

    def test_entity_only_row_is_not_called_empty(self):
        text = _csv([{"client_ref": "E-1", "기업형태": "중소기업", "지역": "서울특별시"}])
        client = batch_client.parse_clients_csv(text)["clients"][0]
        self.assertFalse(any("조건 값이 없습니다" in note for note in client["parse_errors"]))


class EmploymentTextTest(unittest.TestCase):
    """고용 이슈 문구 — 고용 지원을 뜻하는 결합 표현만 인정한다."""

    def test_youth(self):
        self.assertIn("youth", batch_client.employment_codes("2026년 청년일자리도약장려금 참여기업"))
        self.assertIn("youth", batch_client.employment_codes("청년 일자리 도약장려금 공고"))

    def test_youth_startup_centre_is_not_youth_employment(self):
        self.assertEqual(batch_client.employment_codes("송파ICT청년창업지원센터 입주 모집"), frozenset())
        self.assertEqual(batch_client.employment_codes("마포 청년 창업 재도전"), frozenset())

    def test_senior_and_place_name_고령군(self):
        self.assertIn("senior", batch_client.employment_codes("시니어인턴십 참여기업 모집"))
        self.assertIn("senior", batch_client.employment_codes("중장년 기술창업센터 입주"))
        # '고령군'(지역명)·'고령친화산업'은 고용 지원 공고가 아니다
        self.assertEqual(batch_client.employment_codes("경북 고령군 지역발전 우수기업 환경개선"), frozenset())

    def test_parental_leave_and_social_insurance(self):
        self.assertIn("parental_leave",
                      batch_client.employment_codes("소상공인 육아휴직자 대체인력 인건비 지원"))
        self.assertIn("parental_leave", batch_client.employment_codes("대체인력 채용지원 참여 기업"))
        self.assertIn("social_insurance", batch_client.employment_codes("두루누리 사회보험료 지원"))

    def test_live_catalog_employment_index_is_sparse_and_real(self):
        if not HAS_DATA:
            self.skipTest("동기화 산출물 없음")
        catalog = load_catalog(REAL_CATALOG)
        cards = batch_client._program_index(catalog)
        tagged = [card for card in cards if card["employment"]]
        self.assertGreater(len(tagged), 20)
        # 전체 공고의 10% 미만만 고용 이슈로 잡혀야 한다(오탐이 많으면 노무 공고가 아니게 된다).
        self.assertLess(len(tagged), len(cards) * 0.1)
        for card in tagged:
            self.assertTrue(set(card["employment"]) <= set(batch_client.EMPLOYMENT_LABELS_KO))


class ScoreAndRankTest(unittest.TestCase):
    def _size(self):
        return {"small_business_likely": True}

    def test_employment_raises_score_only(self):
        base = _card()
        hit = _card(employment=frozenset({"youth"}))
        region = {"level": "national"}
        self.assertEqual(
            batch_client._pre_score(hit, size=self._size(), industry=None, region=region,
                                    employment=frozenset({"youth"}))
            - batch_client._pre_score(base, size=self._size(), industry=None, region=region,
                                      employment=frozenset({"youth"})),
            8 + 0)
        # 고용 이슈를 입력하지 않으면 차이가 없다(판정·순위가 저절로 흔들리지 않는다).
        self.assertEqual(
            batch_client._pre_score(hit, size=self._size(), industry=None, region=region),
            batch_client._pre_score(base, size=self._size(), industry=None, region=region))

    def test_mismatched_employment_does_not_score(self):
        other = _card(employment=frozenset({"senior"}))
        region = {"level": "national"}
        self.assertEqual(
            batch_client._pre_score(other, size=self._size(), industry=None, region=region,
                                    employment=frozenset({"youth"})),
            batch_client._pre_score(_card(), size=self._size(), industry=None, region=region,
                                    employment=frozenset({"youth"})))

    def test_industry_keyword_scores(self):
        card = _card(search_text="2026년 한식 메뉴 개발 지원", name="한식 메뉴 개발 지원")
        region = {"level": "national"}
        with_term = batch_client._pre_score(card, size=self._size(), industry=None, region=region,
                                            industry_terms=("한식",))
        without = batch_client._pre_score(card, size=self._size(), industry=None, region=region)
        self.assertGreater(with_term, without)

    def test_select_top_puts_emphasis_first(self):
        rows = []
        for index in range(4):
            rows.append({"category": ["small_business", "sme", "labor", "finance_tax"][index],
                         "priority": {"tier": "medium", "score": 4},
                         "days_left": 20, "name": f"row-{index}", "service_id": f"r{index}"})
        rows[2]["employment_hits"] = ("youth",)
        rows.sort(key=batch_client.agent_report._sort_key)
        picked = batch_client._select_top(rows, 3, emphasis=1)
        self.assertIn("r2", [row["service_id"] for row in picked])


class ExclusionAndFitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.cards = batch_client._program_index(cls.catalog)

    def test_exclusion_counts_add_up(self):
        text = _csv([{"client_ref": "X-1", "업종": "음식숙박", "직원수구간": "2명",
                      "연매출": "1억", "업력": "20", "지역": "인천광역시 서구"}])
        payload = batch_client.match_clients(self.catalog, {"csv": text})
        client = payload["clients"][0]
        counts = client["counts"]
        reasons = client["exclusions"]["by_reason"]
        self.assertTrue(reasons)
        self.assertEqual(sum(row["count"] for row in reasons), counts["excluded"])
        # 1차 필터에서 걸러진 수 + 후보 수 = 전체 공고 수
        fast = sum(row["count"] for row in reasons
                   if row["code"] in (batch_client.EXCLUSION_REGION, batch_client.EXCLUSION_ENTITY,
                                      batch_client.EXCLUSION_YEARS, batch_client.EXCLUSION_AGE,
                                      batch_client.EXCLUSION_GENDER,
                                      batch_client.EXCLUSION_INDUSTRY))
        self.assertEqual(fast + counts["candidates"], len(self.cards))
        self.assertIn("years", {row["code"] for row in reasons})

    def test_exclusion_examples_carry_requirement(self):
        text = _csv([{"client_ref": "X-2", "업종": "음식숙박", "직원수구간": "2명",
                      "연매출": "1억", "업력": "20", "지역": "인천광역시 서구"}])
        payload = batch_client.match_clients(self.catalog, {"csv": text})
        examples = payload["clients"][0]["exclusions"]["examples"]
        self.assertTrue(examples)
        for row in examples:
            self.assertTrue(row["name"])
            self.assertTrue(row["reason_label_ko"])
            self.assertTrue(row["requirement_ko"], row)

    def test_fit_reasons_come_from_engine(self):
        text = _csv([{"client_ref": "X-3", "업종": "음식숙박", "직원수구간": "3명",
                      "연매출": "1억", "업력": "4", "지역": "인천광역시 서구"}])
        payload = batch_client.match_clients(self.catalog, {"csv": text})
        for match in payload["clients"][0]["matches"]:
            fit = match["fit"]
            self.assertIn("reasons_ko", fit)
            self.assertTrue(fit["reasons_ko"])
            for check in fit["checks"]:
                self.assertIn(check["state"], ("pass", "unknown"))
                self.assertTrue(check["required_ko"])
            # 확인이 필요한 항목은 따로 모여 있다
            for question in fit["open_questions_ko"]:
                self.assertTrue(question.startswith("확인 필요:"))

    def test_no_match_client_reports_top_reason(self):
        text = _csv([{"client_ref": "X-4", "업종": "음식숙박", "직원수구간": "2명",
                      "연매출": "1억", "업력": "40", "지역": "제주특별자치도 서귀포시"}])
        payload = batch_client.match_clients(self.catalog, {"csv": text})
        client = payload["clients"][0]
        if client["status"] != "matched":
            self.assertTrue(client["exclusions"]["top_label_ko"])
            self.assertTrue(any("가장 많이 빠진 사유" in note for note in client["notes_ko"]))


class EntityDeclarationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()

    def _ids(self, row):
        payload = batch_client.match_clients(self.catalog, {"csv": _csv([row])})
        client = payload["clients"][0]
        return [match["service_id"] for match in client["matches"]], client

    def test_sme_declaration_drops_small_business_only_programs(self):
        ids, _client = self._ids({"client_ref": "E-1", "업종": "도소매", "기업형태": "중소기업",
                                  "직원수구간": "30명", "연매출": "20억", "업력": "5",
                                  "지역": "경기도 성남시"})
        self.assertTrue(ids)
        self.assertNotIn("KSU-900004", ids)   # 소상공인·개인사업자 전용
        self.assertNotIn("KSU-900005", ids)   # 소상공인 전용

    def test_startup_declaration_keeps_sme_programs(self):
        ids, client = self._ids({"client_ref": "E-2", "업종": "도소매", "기업형태": "창업기업",
                                 "직원수구간": "5명", "연매출": "5억", "업력": "5",
                                 "지역": "경기도 성남시"})
        self.assertTrue(ids)
        self.assertIn("BIZ-PBLN_900000000000010", ids)  # 중소기업 수출바우처
        self.assertTrue(any("기업 형태는 입력값" in note for note in client["notes_ko"]))

    def test_declared_small_business_over_limit_is_flagged(self):
        _ids, client = self._ids({"client_ref": "E-3", "업종": "음식숙박", "기업형태": "소상공인",
                                  "직원수구간": "12명", "연매출": "2억", "업력": "3",
                                  "지역": "인천광역시 서구"})
        # 12명은 소상공인 공통 요건(10명 미만)을 넘는다 — 규모 판정이 '일부 요건만'이어도 알린다.
        self.assertTrue(any("넘습니다" in note for note in client["notes_ko"]), client["notes_ko"])
        self.assertIsNone(client["size_estimate"]["small_business_likely"])


class ExportV11Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.payload = batch_client.match_clients(cls.catalog, {"csv": batch_client.sample_csv()})

    def test_schema_and_legend(self):
        self.assertEqual(batch_client.SCHEMA_VERSION, "1.1")
        self.assertEqual(self.payload["schema_version"], "1.1")
        self.assertTrue(self.payload["condition_guide_ko"])
        codes = {row["code"] for row in self.payload["exclusion_legend_ko"]}
        self.assertEqual(codes, set(batch_client.EXCLUSION_ORDER))

    def test_summary_has_category_and_exclusion_totals(self):
        summary = self.payload["summary"]
        self.assertEqual(sum(summary["by_category"].values()), summary["matches"])
        self.assertTrue(summary["by_exclusion"])
        self.assertTrue(summary["exclusion_top_ko"])
        self.assertIn("with_employment", summary)

    def test_csv_has_new_columns_and_no_identity(self):
        text = batch_client.to_csv(self.payload)
        header = text.splitlines()[2]
        for column in ("업종 키워드", "기업 형태", "고용 이슈", "판정 근거", "탈락 사유(요약)"):
            self.assertIn(column, header, column)
        for value in ("예시상호", "000-00-00000"):
            self.assertNotIn(value, text)

    def test_html_cover_and_client_pages(self):
        html = batch_client.to_report_html(self.payload)
        self.assertIn("탈락 사유 상위", html)
        self.assertIn("조건 열 읽는 법", html)
        self.assertIn("탈락 사유(왜 다른 공고는 빠졌나)", html)
        self.assertEqual(html.count('class="client-page"'), len(self.payload["clients"]))
        self.assertIn("근거: ", html)

    def test_markdown_lists_exclusion_reasons(self):
        text = batch_client.to_markdown(self.payload)
        self.assertIn("탈락 사유(전체)", text)
        self.assertIn("묶음: ", text)

    def test_employment_label_shows_in_client_line(self):
        text = _csv([{"client_ref": "M-1", "업종": "IT·정보통신", "고용이슈": "청년",
                      "직원수구간": "5명", "업력": "3", "지역": "서울특별시 마포구"}])
        payload = batch_client.match_clients(self.catalog, {"csv": text})
        markdown = batch_client.to_markdown(payload)
        self.assertIn("청년 채용", markdown)


class EngineConsistencyTest(unittest.TestCase):
    """새 입력이 엔진 판정을 새로 만들지 않는지 — 같은 조건이면 단건 리포트와 같은 답."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.cards = batch_client._program_index(cls.catalog)

    def test_fast_filter_reason_matches_structural_fail(self):
        from subsidy_kr import agent_report

        args = {"industry": "food", "employees": 3, "annual_revenue_krw": 100_000_000,
                "biz_years": 4, "biz_status": "operating", "biz_entity": "small_business",
                "sido": "인천광역시", "sigungu": "서구"}
        spec = agent_report._parse_inputs(args)
        size = agent_report.size_estimate(spec["industry"], spec["employees"],
                                          spec["revenue_krw"], "operating")
        profile = agent_report._engine_profile(spec, size)
        business = profile.get("business") or {}
        region = profile.get("region") or {}
        context = {
            "region_level": region.get("level") or "national",
            "sido": region.get("sido") or "", "sigungu": region.get("sigungu") or "",
            "status": business.get("status"), "entity": business.get("entity"),
            "years": business.get("years"), "industry": business.get("industry"),
            "age": profile.get("age"), "sex": profile.get("sex"), "entity_cache": {},
        }
        for card in self.cards:
            reason = batch_client._fast_fail_reason(card, context)
            expected = engine.structural_fail(card["svc"], profile) is not None
            self.assertEqual(reason is not None, expected, card["svc"].name)

    def test_employment_signal_does_not_change_verdicts(self):
        base = batch_client.match_clients(self.catalog, {"csv": _csv([
            {"client_ref": "D-1", "업종": "음식숙박", "직원수구간": "3명", "연매출": "1억",
             "업력": "4", "지역": "인천광역시 서구"}])})
        tagged = batch_client.match_clients(self.catalog, {"csv": _csv([
            {"client_ref": "D-1", "업종": "음식숙박", "직원수구간": "3명", "연매출": "1억",
             "업력": "4", "지역": "인천광역시 서구", "고용이슈": "청년"}])})
        self.assertEqual(base["clients"][0]["counts"]["candidates"],
                         tagged["clients"][0]["counts"]["candidates"])
        base_verdicts = {match["service_id"]: match["verdict"]["code"]
                         for match in base["clients"][0]["matches"]}
        tagged_verdicts = {match["service_id"]: match["verdict"]["code"]
                           for match in tagged["clients"][0]["matches"]}
        for service_id, code in tagged_verdicts.items():
            if service_id in base_verdicts:
                self.assertEqual(base_verdicts[service_id], code)


@unittest.skipUnless(HAS_DATA, "동기화 산출물이 없어 건너뜁니다")
class LiveRefinementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(REAL_CATALOG)

    def test_employment_issue_surfaces_in_top_matches(self):
        payload = batch_client.match_clients(self.catalog, {"csv": _csv([
            {"client_ref": "L-1", "업종": "서비스", "고용이슈": "육아휴직",
             "직원수구간": "10~49명", "연매출": "3억", "업력": "9",
             "지역": "서울특별시 마포구"}])})
        matches = payload["clients"][0]["matches"]
        self.assertTrue(matches)
        self.assertTrue(any(match["employment_hits_ko"] for match in matches),
                        [match["name"] for match in matches])

    def test_no_identity_in_large_refined_batch(self):
        rows = [{"client_ref": f"P-{index:03d}", "상호명": f"가상상사{index}",
                 "사업자번호": "111-22-33333", "업종": "제조", "업종키워드": "가공",
                 "기업형태": "중소기업", "고용이슈": "청년", "직원수구간": "10~49명",
                 "연매출": "5억", "업력": "5", "지역": "경기도 성남시"}
                for index in range(30)]
        payload = batch_client.match_clients(self.catalog, {"csv": _csv(rows)})
        text = json.dumps(payload, ensure_ascii=False)
        for value in ("가상상사", "111-22-33333"):
            self.assertNotIn(value, text)
        self.assertEqual(payload["summary"]["clients"], 30)
        self.assertGreater(payload["summary"]["matches"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
