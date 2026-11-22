"""지자체 포털 페이지 상한·감소 보호 회귀 테스트 (v0.4.11).

2026-11-22 자동 갱신이 브라보(지역사회서비스포털) 시·도별 페이지 상한(8페이지=80건)에
잘려 지자체 공고가 987 → 741건으로 조용히 줄었습니다. 여기서는

1. 총 건수만큼 끝까지 읽는지(경기 394건 = 40페이지),
2. 상한에 걸리면 `truncated` 로 드러나는지,
3. 페이지 하나가 TLS 오류로 실패해도 그 페이지만 건너뛰고 나머지를 읽는지,
4. 수집이 비정상적으로 줄었을 때 기존 행을 보존하는지(`_merge_local_rows`)

를 네트워크 없이 확인합니다.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import local_portals, sync_gov24  # noqa: E402


def _item(engn: str, svc: str, title: str, org: str = "해운대구청") -> str:
    return (
        "<a href=\"javascript:fn_selectServiceSeachDet('{e}', '{s}');\">\n"
        "  <dl>\n"
        "    <dt>{t} <span>[{o}]</span></dt>\n"
        "    <dd>{t} 안내</dd>\n"
        "  </dl>\n"
        "</a>\n"
    ).format(e=engn, s=svc, t=title, o=org)


def _page(total: int, page: int, per_page: int = 10, *, prefix: str = "P",
          empty: bool = False) -> str:
    head = f"<div>총({total}건</div>"
    if empty:
        return head
    start = (page - 1) * per_page + 1
    end = min(total, start + per_page - 1)
    body = "".join(
        _item(f"{prefix}{index:04d}", "1", f"지역사회서비스 {index}") for index in range(start, end + 1)
    )
    return head + "<ul>" + body + "</ul>"


class BrosoPagingTest(unittest.TestCase):
    def _patch_fetch(self, pages, *, fail_once=None):
        """`_fetch_html` 대신 페이지 HTML 을 돌려주는 가짜 fetcher. 호출 로그를 남긴다."""
        calls = []

        def fake(url, timeout=8.0, data=None, retries=2):
            page = 1
            if data:
                raw = data.decode("utf-8") if isinstance(data, bytes) else str(data)
                page = int(raw.split("pageIndex=")[1].split("&")[0])
            calls.append(page)
            if fail_once and page in fail_once and fail_once[page] > 0:
                fail_once[page] -= 1
                raise ssl.SSLError("record layer failure")
            return pages.get(page, "<div>총(0건</div>")

        original = local_portals._fetch_html
        local_portals._fetch_html = fake
        self.addCleanup(setattr, local_portals, "_fetch_html", original)
        return calls

    def test_reads_every_page_up_to_the_reported_total(self):
        pages = {page: _page(394, page) for page in range(1, 41)}
        calls = self._patch_fetch(pages)
        report = {}
        rows = local_portals.fetch_broso_region("gyeonggi", "경기도", report=report)
        self.assertEqual(len(rows), 394)          # 8페이지(80건)에서 잘리지 않는다
        self.assertEqual(sorted(calls), list(range(1, 41)))
        self.assertEqual(report["total"], 394)
        self.assertEqual(report["pages"], 40)
        self.assertFalse(report["truncated"])
        self.assertTrue(report["complete"])

    def test_page_cap_is_reported_as_truncated(self):
        pages = {page: _page(394, page) for page in range(1, 41)}
        self._patch_fetch(pages)
        report = {}
        rows = local_portals.fetch_broso_region("gyeonggi", "경기도", max_pages=2, report=report)
        self.assertEqual(len(rows), 20)
        self.assertTrue(report["truncated"])       # 상한에 걸렸다는 사실이 남는다
        self.assertEqual(report["max_pages"], 2)

    def test_tls_error_on_one_page_does_not_drop_the_rest(self):
        pages = {page: _page(50, page) for page in range(1, 6)}
        self._patch_fetch(pages, fail_once={3: 1})   # 3페이지는 첫 시도만 실패
        report = {}
        rows = local_portals.fetch_broso_region("busan", "부산광역시", report=report)
        # 3페이지는 재시도로 받고, 5페이지까지 모두 읽는다.
        self.assertEqual(len(rows), 50)
        self.assertTrue(report["complete"])

    def test_repeated_page_stops_the_loop(self):
        # 페이지 파라미터를 무시하는 포털: 같은 10건이 계속 와도 무한 반복하지 않는다.
        pages = {1: _page(100, 1)}
        calls = self._patch_fetch({page: pages[1] for page in range(1, 11)})
        report = {}
        rows = local_portals.fetch_broso_region("seoul", "서울특별시", report=report)
        self.assertEqual(len(rows), 10)
        self.assertEqual(len(calls), 2)            # 1페이지 + 중복 확인용 1회
        self.assertFalse(report["complete"])

    def test_partial_region_is_collected_again(self):
        # 1바퀴에서 2페이지가 계속 실패하면 partial — 한 바퀴 뒤 그 지역만 다시 돌려 채운다.
        attempts = {"page2": 0}

        def fake(url, timeout=8.0, data=None, retries=2):
            page = 1
            if data:
                raw = data.decode("utf-8") if isinstance(data, bytes) else str(data)
                page = int(raw.split("pageIndex=")[1].split("&")[0])
            if page == 2:
                attempts["page2"] += 1
                if attempts["page2"] <= 3:      # 한 바퀴분 재시도(3회)를 모두 실패시킨다
                    raise ssl.SSLError("record layer failure")
            return _page(30, page)

        original_fetch = local_portals._fetch_html
        original_regions = local_portals.BROSO_REGIONS
        local_portals._fetch_html = fake
        local_portals.BROSO_REGIONS = [("seoul", "서울특별시")]
        self.addCleanup(setattr, local_portals, "BROSO_REGIONS", original_regions)
        self.addCleanup(setattr, local_portals, "_fetch_html", original_fetch)

        reports = {}
        rows, per_sido = local_portals.fetch_broso_all(reports=reports)
        self.assertEqual(per_sido, {"seoul": 30})   # 두 번째 바퀴에서 빠진 페이지를 채운다
        self.assertEqual(len(rows), 30)
        self.assertTrue(reports["seoul"]["complete"])

    def test_fetch_all_reports_per_region_pages(self):
        original_regions = local_portals.BROSO_REGIONS
        local_portals.BROSO_REGIONS = [("seoul", "서울특별시"), ("jeju", "제주특별자치도")]
        self.addCleanup(setattr, local_portals, "BROSO_REGIONS", original_regions)

        def fake(url, timeout=8.0, data=None, retries=2):
            page = 1
            if data:
                raw = data.decode("utf-8") if isinstance(data, bytes) else str(data)
                page = int(raw.split("pageIndex=")[1].split("&")[0])
            if "seoul" in url:
                return _page(21, page)
            return _page(10, page, prefix="J")

        original = local_portals._fetch_html
        local_portals._fetch_html = fake
        self.addCleanup(setattr, local_portals, "_fetch_html", original)

        reports = {}
        rows, per_sido = local_portals.fetch_broso_all(reports=reports)
        self.assertEqual(len(rows), 31)
        self.assertEqual(per_sido, {"seoul": 21, "jeju": 10})
        self.assertEqual(reports["seoul"]["pages"], 3)
        self.assertTrue(reports["seoul"]["complete"])


class MergeLocalRowsTest(unittest.TestCase):
    @staticmethod
    def _row(service_id, title, deadline="상시", source="local_portal"):
        return {"서비스ID": service_id, "서비스명": title, "소관기관명": "부산광역시 (해운대구청)",
                "신청기한": deadline, "source": source}

    def test_empty_portal_keeps_existing_rows(self):
        existing = [self._row("BROSO-BUSAN-P1-1", "기존")]
        rows, kept, guarded = sync_gov24._merge_local_rows([], existing)
        self.assertEqual([row["서비스ID"] for row in rows], ["BROSO-BUSAN-P1-1"])
        self.assertEqual(kept, {"BROSO-BUSAN"})   # 브라보는 시·도 단위로 지킨다
        self.assertEqual(guarded, {})

    def test_vanished_region_is_kept_even_when_other_regions_grew(self):
        # 브라보 한 시·도가 통째로 실패해도 전체 브라보 건수는 조금밖에 안 줄어든다.
        # 시·도 단위로 세지 않으면 세종 16건이 통째로 사라진다.
        existing = [self._row(f"BROSO-SEJONG-P1-{n}", f"세종 {n}") for n in range(16)]
        existing += [self._row(f"BROSO-SEOUL-P1-{n}", f"서울 {n}") for n in range(10)]
        new = [self._row(f"BROSO-SEOUL-P1-{n}", f"서울 새 {n}") for n in range(10)]
        rows, kept, guarded = sync_gov24._merge_local_rows(new, existing)
        self.assertEqual(len(rows), 26)
        self.assertEqual(kept, {"BROSO-SEJONG"})
        self.assertEqual(guarded, {})

    def test_small_drop_is_trusted(self):
        # 4건 감소는 정상 범위(마감·개편) — 새 수집 결과를 그대로 쓴다.
        existing = [self._row(f"BROSO-BUSAN-P1-{n}", f"기존 {n}") for n in range(10)]
        new = [self._row(f"BROSO-BUSAN-P1-{n}", f"새 {n}") for n in range(6)]
        rows, kept, guarded = sync_gov24._merge_local_rows(new, existing)
        self.assertEqual(len(rows), 6)
        self.assertEqual(guarded, {})

    def test_large_drop_preserves_missing_rows(self):
        # 10건 → 2건은 페이지 상한에 잘린 모양이다. 새 행은 반영하고, 보이지 않은 8건은 지킨다.
        existing = [self._row(f"BROSO-GYEONGGI-P1-{n}", f"기존 {n}") for n in range(10)]
        new = [self._row("BROSO-GYEONGGI-P1-0", "새 0"), self._row("BROSO-GYEONGGI-P1-9", "새 9")]
        rows, kept, guarded = sync_gov24._merge_local_rows(new, existing)
        ids = {row["서비스ID"] for row in rows}
        self.assertEqual(len(rows), 10)            # 2 + 보존한 기존 8건
        self.assertIn("BROSO-GYEONGGI-P1-5", ids)
        self.assertEqual(guarded, {"BROSO-GYEONGGI": 8})
        self.assertEqual(kept, set())
        # 새 행이 먼저 온다 — 뒤에 붙은 보존 행이 새 값을 덮어쓰지 않는다.
        self.assertEqual(rows[0]["서비스명"], "새 0")

    def test_preserved_rows_respect_expiry(self):
        existing = [self._row(f"GG24-{n}", f"기존 {n}") for n in range(6)]
        existing.append(self._row("GG24-99", "지난 사업", deadline="2020-01-01 ~ 2020-12-31"))
        new = [self._row("GG24-0", "새 0")]
        rows, _kept, guarded = sync_gov24._merge_local_rows(new, existing)
        ids = {row["서비스ID"] for row in rows}
        self.assertIn("GG24-3", ids)               # 마감 안 지난 행은 보존
        self.assertNotIn("GG24-99", ids)           # 이미 마감한 행은 되살리지 않는다
        self.assertEqual(guarded, {"GG24": 5})

    def test_shrink_is_reported_and_kept_in_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "catalog.json"), "w", encoding="utf-8") as handle:
                json.dump({"meta": {"catalog_state": "synced"},
                           "services": [self._row(f"SEOULWIS-{n}", f"서울 기존 {n}")
                                        for n in range(10)]}, handle, ensure_ascii=False)

            original = local_portals.collect_all_local_portals
            local_portals.collect_all_local_portals = lambda **_kwargs: {
                "records": [self._row("SEOULWIS-0", "서울 새 0")],
                "counts": {"seoul_wis": 1, "total_deduped": 1},
            }
            try:
                report = sync_gov24.sync_all("TESTKEY", data_dir=tmp, force=True,
                                             sources=(), include_local_portals=True)
            finally:
                local_portals.collect_all_local_portals = original

            with open(os.path.join(tmp, "catalog.json"), encoding="utf-8") as handle:
                ids = {row["서비스ID"] for row in json.load(handle)["services"]}
            self.assertEqual(len(ids), 10)
            self.assertIn("SEOULWIS-4", ids)
            self.assertIn("기존유지", report["sources"]["local_portal"]["state"])
            self.assertEqual(report["sources"]["local_portal"]["counts"]["preserved_on_shrink"],
                             {"SEOULWIS": 9})
            self.assertTrue(any("기존 행 9건을 유지" in warning for warning in report["warnings"]))

    def test_truncated_portal_produces_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = local_portals.collect_all_local_portals
            local_portals.collect_all_local_portals = lambda **_kwargs: {
                "records": [self._row("BROSO-SEOUL-P1-1", "서울 1")],
                "counts": {"broso_total": 1, "broso_truncated": ["gyeonggi"],
                           "total_deduped": 1},
            }
            try:
                report = sync_gov24.sync_all("TESTKEY", data_dir=tmp, force=True,
                                             sources=(), include_local_portals=True)
            finally:
                local_portals.collect_all_local_portals = original
            self.assertTrue(any("페이지 상한" in warning and "gyeonggi" in warning
                                for warning in report["warnings"]), report["warnings"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
