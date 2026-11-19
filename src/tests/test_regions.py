"""시도·시군구 정규화와 소관기관명 → 지역 판별."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import regions  # noqa: E402


class SidoTest(unittest.TestCase):
    def test_aliases_and_prefixes(self):
        cases = {
            "서울": "서울특별시", "서울시": "서울특별시", "서울특별시": "서울특별시",
            "인천": "인천광역시", "인천시": "인천광역시", "인천서구": "인천광역시",
            "경기": "경기도", "경기도": "경기도", "경기도수원시": "경기도",
            "전북": "전북특별자치도", "전라북도": "전북특별자치도",
            "강원도": "강원특별자치도", "제주": "제주특별자치도",
        }
        for raw, expected in cases.items():
            self.assertEqual(regions.canonical_sido(raw), expected, raw)
        self.assertIsNone(regions.canonical_sido("화성"))
        self.assertIsNone(regions.canonical_sido(""))

    def test_sido_list_is_17(self):
        self.assertEqual(len(regions.sido_names()), 17)
        self.assertEqual(len(list(regions.iter_all_regions())), 250)


class SigunguTest(unittest.TestCase):
    def test_resolution(self):
        self.assertEqual(regions.canonical_sigungu("인천광역시", "서구"), "서해구")
        self.assertEqual(regions.canonical_sigungu("경기도", "수원 장안구"), "수원시 장안구")
        self.assertEqual(regions.canonical_sigungu("경기도", "구리"), "구리시")
        self.assertEqual(regions.canonical_sigungu("경기도", "부천"), "부천시")
        self.assertIsNone(regions.canonical_sigungu("인천광역시", "강남구"))
        self.assertIsNone(regions.canonical_sigungu("세종특별자치시", "세종특별자치시"))

    def test_ambiguous_sigungu_needs_sido(self):
        sido, state = regions.find_sido_by_sigungu("중구")
        self.assertIsNone(sido)
        self.assertEqual(state, "ambiguous")
        sido, state = regions.find_sido_by_sigungu("마포구")
        self.assertEqual((sido, state), ("서울특별시", "unique"))

    def test_region_block_levels(self):
        self.assertEqual(regions.region_block()["level"], "national")
        self.assertEqual(regions.region_block("인천광역시")["level"], "sido")
        block = regions.region_block("인천", "서구")
        self.assertEqual((block["level"], block["sido"], block["sigungu"]),
                         ("sigungu", "인천광역시", "서해구"))
        self.assertEqual(regions.region_block("", "서구")["level"], "local_unresolved")


class AgencyRegionTest(unittest.TestCase):
    def test_central_agency_is_national(self):
        for name in ("해양수산부", "교육부", "국세청", "금융위원회"):
            self.assertEqual(regions.parse_agency_region(name)["level"], "national", name)
        self.assertEqual(regions.parse_agency_region("")["level"], "unknown")

    def test_full_names(self):
        block = regions.parse_agency_region("인천광역시 서구")
        self.assertEqual((block["level"], block["sido"], block["sigungu"]),
                         ("sigungu", "인천광역시", "서해구"))
        self.assertEqual(regions.parse_agency_region("세종특별자치시")["level"], "sido")
        self.assertEqual(regions.parse_agency_region("제주시")["sigungu"], "제주시")

    def test_agency_names_without_sido(self):
        block = regions.parse_agency_region("마포구시설관리공단")
        self.assertEqual((block["sido"], block["sigungu"]), ("서울특별시", "마포구"))
        block = regions.parse_agency_region("구리도시공사")
        self.assertEqual((block["sido"], block["sigungu"]), ("경기도", "구리시"))
        block = regions.parse_agency_region("(재)남동문화재단")
        self.assertEqual((block["sido"], block["sigungu"]), ("인천광역시", "남동구"))

    def test_ambiguous_agency_is_left_unresolved(self):
        self.assertEqual(regions.parse_agency_region("광주시")["level"], "local_unresolved")
        self.assertEqual(regions.parse_agency_region("중구")["level"], "local_unresolved")

    def test_gyeonggi_gwangju_is_resolved(self):
        block = regions.parse_agency_region("경기도 광주시")
        self.assertEqual((block["sido"], block["sigungu"]), ("경기도", "광주시"))


class MatchTest(unittest.TestCase):
    def _service(self, **kwargs):
        return {"level": "national", "sido": "", "sigungu": "", **kwargs}

    def test_national_always_matches(self):
        self.assertEqual(regions.match_region(regions.region_block(), self._service())["state"],
                         "match")

    def test_mismatch_and_match(self):
        user = regions.region_block("인천광역시", "서구")
        self.assertEqual(regions.match_region(
            user, self._service(level="sigungu", sido="인천광역시", sigungu="서해구"))["state"], "match")
        self.assertEqual(regions.match_region(
            user, self._service(level="sigungu", sido="인천광역시", sigungu="남동구"))["state"],
            "mismatch")
        self.assertEqual(regions.match_region(
            user, self._service(level="sido", sido="부산광역시"))["state"], "mismatch")

    def test_unknown_when_user_or_service_unresolved(self):
        self.assertEqual(regions.match_region(
            regions.region_block(), self._service(level="sido", sido="부산광역시"))["state"],
            "unknown")
        self.assertEqual(regions.match_region(
            regions.region_block("", "서구"), self._service(level="sido", sido="부산광역시"))["state"],
            "unknown")
        self.assertEqual(regions.match_region(
            regions.region_block("인천광역시"), self._service(level="local_unresolved"))["state"],
            "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
