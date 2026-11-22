"""담당자 이메일 마스킹 회귀 테스트 (v0.4.9).

무엇을 지키는가
---------------
공고 원문에는 기관 담당자 이메일이 그대로 들어 있다(기업마당 `refrncNm`, K-Startup
`aply_mthd_eml_rcpt_istc`, 보조금24 `전화문의`·`신청방법` 등). 카탈로그 파일은 원문 그대로
두고, **밖으로 나가는 출력**(/s/·/regions/·/guides/ HTML, API·MCP JSON, CSV 리포트,
스냅샷 비교)에서만 로컬파트를 가린다.

이 테스트는 그 약속을 두 방향에서 확인한다.
1. 원문(`Service` 필드)은 손대지 않는다 — 마스킹은 출력 계층에서만.
2. 어떤 출력 경로에도 가려지지 않은 주소가 남지 않는다 — 도메인·출처 링크는 남는다.

테스트 파일에는 이메일 리터럴을 쓰지 않는다(`test_privacy.PersonalDataTest` 가 소스 전체에서
이메일 모양 문자열을 금지한다). 조각을 합쳐 만든다.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from subsidy_kr import api, engine, guides, pseo, redact, regions, snapshots  # noqa: E402
from subsidy_kr.catalog import Catalog, load_catalog, normalize_service  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402

AT = "@"
CATALOG = os.path.join(PROJECT, "data", "gov24", "catalog.json")
HAS_DATA = os.path.exists(CATALOG) or os.path.exists(CATALOG + ".gz")


def addr(local: str, domain: str = "example.com") -> str:
    """테스트용 주소 — 소스에 이메일 리터럴을 남기지 않으려고 조각을 합친다."""
    return local + AT + domain


def raw_row(**over):
    """원문 필드마다 담당자 주소가 섞인 개인 트랙 공고 1건."""
    row = {
        "서비스ID": "T-900001",
        "서비스명": "청년 월세 지원",
        "서비스목적요약": "청년의 주거비 부담을 덜어 주는 월세 지원",
        "소관기관명": "서울특별시 중구청",
        "소관기관유형": "지방자치단체",
        "서비스분야": "주거·자립",
        "사용자구분": "가구",
        "지원대상": "만 19~34세 무주택 청년. 문의 " + addr("targetowner", "example.org"),
        "선정기준": "소득 기준 충족. 담당 " + addr("criteria.owner", "example.net"),
        "지원내용": "월 20만 원 지원. 문의 " + addr("contentowner", "example.com"),
        "신청방법": "이메일 접수 " + addr("applyowner", "example.com") + " 또는 주민센터 방문",
        "신청기한": "2026. 12. 31.",
        "접수기관": "주거복지과",
        "전화문의": addr("contactowner", "example.com"),
        "상세조회URL": "https://example.com/detail/T-900001",
        "온라인신청사이트URL": "",
        "구비서류": "",
        "수정일시": "2026-11-20",
    }
    row.update(over)
    return row


def build_catalog(rows=None):
    rows = rows or [raw_row()]
    meta = {"catalog_state": "synced", "data_state": "gov24", "generated_on": "2026-11-22",
            "source": "테스트"}
    return Catalog([normalize_service(row, source="gov24") for row in rows], meta)


def unmasked(value):
    return list(redact.iter_unmasked(value))


class MaskRuleTest(unittest.TestCase):
    def test_keeps_two_leading_characters_and_domain(self):
        self.assertEqual(redact.mask_emails(addr("honggildong")), "ho" + "***" + AT + "example.com")

    def test_short_local_parts_are_fully_masked(self):
        self.assertEqual(redact.mask_emails(addr("ab")), "*" + AT + "example.com")
        self.assertEqual(redact.mask_emails(addr("a")), "*" + AT + "example.com")

    def test_multi_label_and_korean_domains_keep_shape(self):
        masked = redact.mask_emails(addr("jieun36", "geri.re.kr"))
        self.assertEqual(masked, "ji" + "***" + AT + "geri.re.kr")
        self.assertTrue(masked.endswith(AT + "geri.re.kr"))

    def test_every_address_in_a_sentence_is_masked(self):
        text = "접수 " + addr("firstone") + ", 문의 " + addr("secondone", "example.org") + " 입니다"
        masked = redact.mask_emails(text)
        self.assertEqual(redact.find_emails(masked), [])
        self.assertIn("example.org", masked)
        self.assertIn("example.com", masked)

    def test_masking_is_idempotent(self):
        once = redact.mask_emails("문의 " + addr("repeattest"))
        self.assertEqual(redact.mask_emails(once), once)

    def test_plain_text_is_untouched(self):
        for text in ("문의: 02-0000-0000", "이메일 접수", "https://example.com/a?b=1",
                     "가격 1.5@3 배", ""):
            self.assertEqual(redact.mask_emails(text), text)

    def test_mask_object_does_not_mutate_source(self):
        source = {"contact": addr("keepme"), "rows": [addr("alsokeep", "example.org")]}
        masked = redact.mask_object(source)
        self.assertEqual(unmasked(masked), [])
        self.assertIn(AT + "example.com", source["contact"])


class SummaryAndEngineTest(unittest.TestCase):
    def setUp(self):
        self.catalog = build_catalog()
        self.service = self.catalog.services[0]

    def test_raw_fields_keep_original_addresses(self):
        """원문 데이터는 그대로 — 마스킹은 출력에서만 한다."""
        self.assertEqual(self.service.contact, addr("contactowner"))
        self.assertIn(addr("contentowner"), self.service.content)
        self.assertIn(addr("applyowner"), self.service.how)

    def test_summary_masks_every_field_but_keeps_source_links(self):
        block = self.service.summary(detail=True)
        self.assertEqual(unmasked(block), [])
        self.assertEqual(block["contact"], "co" + "***" + AT + "example.com")
        self.assertEqual(block["detail_url"], "https://example.com/detail/T-900001")
        self.assertEqual(block["agency"], "서울특별시 중구청")

    def test_engine_row_masks_reasons_and_application(self):
        profile = engine.normalize_profile({"age": 30, "region": {"sido": "서울특별시",
                                                                  "sigungu": "중구"}})
        row = engine.evaluate_service(self.service, profile)
        self.assertEqual(unmasked(row), [])
        self.assertIn(AT + "example.com", str(row))

    def test_fingerprint_is_computed_from_original_text(self):
        """마스킹이 지문을 바꾸면 스냅샷 비교가 거짓 변경을 만든다."""
        again = normalize_service(raw_row(), source="gov24")
        self.assertEqual(self.service.fingerprint, again.fingerprint)
        self.assertEqual(unmasked(self.service.fingerprint), [])


class HtmlOutputTest(unittest.TestCase):
    def setUp(self):
        rows = [raw_row(), raw_row(**{"서비스ID": "T-900002", "서비스명": "청년 주거비 지원"})]
        self.catalog = build_catalog(rows)

    def _scan(self, page, label):
        self.assertIsNotNone(page, label)
        self.assertEqual(unmasked(page), [], label)
        return page

    def test_topic_page(self):
        page = self._scan(pseo.render_item("cheongnyeon", self.catalog), "/s/cheongnyeon")
        self.assertIn("청년 월세 지원", page)
        self.assertIn("서울특별시 중구청", page)
        self.assertIn("https://example.com/detail/T-900001", page)
        self.assertIn("co" + "***" + AT + "example.com", page)

    def test_region_page(self):
        page = self._scan(regions.render_item("seoul", self.catalog), "/regions/seoul")
        self.assertIn("중구", page)
        self.assertIn("co" + "***" + AT + "example.com", page)

    def test_guide_pages(self):
        rendered_with_rows = 0
        for slug in [guide["slug"] for guide in guides.GUIDES]:
            page = self._scan(guides.render_item(slug, self.catalog), f"/guides/{slug}")
            if "청년 월세 지원" in page:
                rendered_with_rows += 1
        self.assertGreater(rendered_with_rows, 0, "가이드 페이지에 관련 공고 줄이 그려지지 않았습니다")


class ApiOutputTest(unittest.TestCase):
    def setUp(self):
        self.catalog = build_catalog()
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def _call(self, name, args):
        out = api.call_tool(name, args, self.catalog, store=self.store)
        self.assertTrue(out["ok"], name)
        self.assertEqual(unmasked(out), [], name)
        return out["result"]

    def test_search_and_check_and_detail(self):
        profile = {"age": 30, "region": {"sido": "서울특별시", "sigungu": "중구"}}
        result = self._call("search_subsidies", {"profile": profile, "include_ineligible": True})
        self.assertTrue(result["results"])
        self._call("check_eligibility", {"profile": profile, "service_id": "T-900001"})
        detail = self._call("get_subsidy_detail", {"service_id": "T-900001"})
        self.assertEqual(detail["service"]["contact"], "co" + "***" + AT + "example.com")

    def test_region_list_and_deadline_calendar(self):
        self._call("list_region_subsidies", {"sido": "서울특별시", "sigungu": "중구"})
        self._call("deadline_calendar", {"days": 400})


class SnapshotDiffTest(unittest.TestCase):
    def test_diff_masks_changed_text(self):
        first = build_catalog([raw_row()])
        changed_row = raw_row(**{"지원내용": "월 25만 원 지원. 문의 " + addr("newowner")})
        second = build_catalog([changed_row])
        before = snapshots.build_snapshot(first.services, "2026-11-01")
        after = snapshots.build_snapshot(second.services, "2026-11-02")
        diff = snapshots.diff_snapshots(before, after)
        self.assertEqual(unmasked(diff), [])
        self.assertTrue(diff["changed"], "변경 건이 잡히지 않았습니다")


@unittest.skipUnless(HAS_DATA, "동기화 산출물이 없어 건너뜁니다")
class LiveCatalogMaskingTest(unittest.TestCase):
    """실데이터 — 원문에 담당자 주소가 있는 제도가 전부 가려져 나오는지."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(CATALOG)
        cls.with_email = [svc for svc in cls.catalog.services
                          if redact.find_emails(" ".join(
                              (svc.name, svc.target, svc.criteria, svc.content, svc.how,
                               svc.contact, svc.purpose)))]

    def test_catalog_has_addresses_to_cover(self):
        self.assertGreater(len(self.with_email), 0)

    def test_summary_and_engine_rows_are_clean(self):
        profile = engine.normalize_profile({"age": 34})
        for svc in self.with_email:
            self.assertEqual(unmasked(svc.summary(detail=True)), [], svc.service_id)
            self.assertEqual(unmasked(engine.evaluate_service(svc, profile)), [], svc.service_id)

    def test_masking_keeps_domain_and_shortens_local_part(self):
        sample = self.with_email[0]
        block = sample.summary(detail=True)
        original = redact.find_emails(" ".join((sample.name, sample.target, sample.content,
                                                sample.how, sample.contact)))
        if not original:
            self.skipTest("첫 건의 원문 주소가 요약 필드 밖에 있습니다")
        address = original[0]
        local, _, domain = address.rpartition(AT)
        self.assertIn(domain, str(block))
        if len(local) > 2:
            self.assertNotIn(local, str(block))

    def test_topic_and_region_pages_have_no_addresses(self):
        for page in pseo.items(self.catalog):
            html = pseo.render_item(page["slug"], self.catalog)
            self.assertEqual(unmasked(html), [], page["slug"])
        for slug in [row["slug"] for row in regions.hub_summary(self.catalog)]:
            html = regions.render_item(slug, self.catalog)
            self.assertEqual(unmasked(html), [], slug)


if __name__ == "__main__":
    unittest.main(verbosity=2)
