"""검색 캐시 회귀 테스트 — 판정 결과가 캐시 전후로 100% 같은지 확인한다.

배경
----
`search_subsidies` 는 호출마다 카탈로그를 다시 훑어 후보 목록을 만들고(1.2만 건),
후보 전부를 판정했습니다(Render 무료 0.1 vCPU 에서 5.9초). 캐시는 세 가지입니다.
- 필터 조합별 후보 목록(`_candidate_pool`)
- (프로필, 옵션)별 판정 결과(`_ResultCache`)
- 제도별 선정기준 규칙(프로필과 무관, `_criteria_rules`)

이 파일은 캐시를 **끈 것과 같은 계산**(아래 `reference_search`)을 그대로 다시 구현해
결과가 완전히 같은지 비교합니다. 캐시는 속도만 바꾸고 판정은 바꾸지 않아야 합니다.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from subsidy_kr import engine, models, pseo, programs  # noqa: E402
from subsidy_kr.catalog import Catalog, load_catalog, sample_catalog  # noqa: E402

CATALOG = os.path.join(PROJECT, "data", "gov24", "catalog.json")
HAS_DATA = os.path.exists(CATALOG) or os.path.exists(CATALOG + ".gz")


def reference_search(catalog, profile, *, limit=20, include_ineligible=False, tag=None,
                     keyword=None, max_scan=20000, include_closed=False):
    """캐시 도입 전 `search()` 와 같은 계산(비교 기준). 캐시를 전혀 쓰지 않는다."""
    region = profile["region"]
    pool = catalog.services[:max_scan]
    if region.get("level") in ("sido", "sigungu"):
        pool = catalog.by_region(region.get("sido"), region.get("sigungu"))[:max_scan]
    track = profile.get("track", "all")
    if track == programs.TRACK_BUSINESS:
        pool = [svc for svc in pool if svc.is_business]
    elif track == programs.TRACK_PERSONAL:
        pool = [svc for svc in pool if not svc.is_business]
    elif not (profile.get("business") or {}).get("declared"):
        pool = [svc for svc in pool if not svc.is_business]
    if not include_closed:
        pool = [svc for svc in pool if not svc.is_expired]
    if tag:
        pool = [svc for svc in pool if tag in svc.tags]
    if keyword:
        words = [word for word in str(keyword).split() if word]
        pool = [svc for svc in pool
                if all(word in f"{svc.name} {svc.purpose} {svc.target} "
                                f"{' '.join(svc.business.get('hashtags') or [])}"
                       for word in words)]

    results = [engine.evaluate_service(svc, profile) for svc in pool]
    if not include_ineligible:
        shown = [row for row in results if row["verdict"]["code"] != models.VERDICT_INELIGIBLE]
    else:
        shown = results
    shown.sort(key=engine._sort_key)
    counts = {code: 0 for code in models.VERDICT_ORDER}
    for row in results:
        counts[row["verdict"]["code"]] += 1
    track_counts = {programs.TRACK_PERSONAL: 0, programs.TRACK_BUSINESS: 0}
    for row in results:
        track_counts[row["track"]] = track_counts.get(row["track"], 0) + 1
    return {
        "counts": counts,
        "scanned": len(results),
        "results": shown[:max(1, limit)],
        "truncated": len(shown) > limit,
        "ineligible_hidden": counts[models.VERDICT_INELIGIBLE] if not include_ineligible else 0,
        "track": track,
        "track_counts": track_counts,
        "closed_hidden": sum(1 for svc in catalog.services if svc.is_expired)
        if not include_closed else 0,
    }


def profile(**kwargs):
    return engine.normalize_profile(kwargs)


PERSONAL = profile(birth_year=1992, sex="male", household_size=2, income_band="JA0203",
                   situations=["no_home", "worker", "birth"],
                   region={"sido": "인천광역시", "sigungu": "서구"})
PERSONAL_FEMALE = profile(birth_year=1997, sex="female", income_band="JA0202",
                          situations=["pregnant", "no_home"],
                          region={"sido": "인천광역시", "sigungu": "서구"})
PERSONAL_NO_REGION = profile(age=34, income_band="JA0201", situations=["jobseeker"])
PERSONAL_CHILD = profile(age=38, income_band="JA0203", children_years=[2016, 2022],
                         situations=["parenting", "multi_child"],
                         region={"sido": "서울특별시", "sigungu": "강서구"})
BUSINESS = profile(track="business", age=33, region={"sido": "서울특별시"},
                   business={"status": "pre", "entity": "pre_startup"})
BUSINESS_OPERATING = profile(track="business", age=44, region={"sido": "경기도", "sigungu": "성남시"},
                             business={"status": "operating", "entity": "small_business",
                                       "years": 4, "industry": "manufacturing"})
EMPTY = profile()


class SampleEquivalenceTest(unittest.TestCase):
    """샘플 카탈로그 — 모든 옵션 조합에서 캐시 결과가 기준 계산과 같아야 한다."""

    @classmethod
    def setUpClass(cls):
        cls.services = sample_catalog().services
        cls.meta = dict(sample_catalog().meta)

    def fresh(self):
        """캐시가 빈 새 카탈로그(서비스 객체는 공유 — 프로필 무관 파생값만 공유한다)."""
        return Catalog(list(self.services), dict(self.meta))

    def check(self, prof, **options):
        catalog = self.fresh()
        expected = reference_search(catalog, prof, **options)
        first = engine.search(catalog, prof, **options)          # 계산 후 캐시 저장
        second = engine.search(catalog, prof, **options)         # 캐시 적중
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        return catalog, expected

    def test_default_options(self):
        for prof in (PERSONAL, PERSONAL_FEMALE, PERSONAL_NO_REGION, PERSONAL_CHILD,
                     BUSINESS, BUSINESS_OPERATING, EMPTY):
            with self.subTest(profile=prof.get("track")):
                self.check(prof)

    def test_limit_and_ineligible(self):
        self.check(PERSONAL, limit=3)
        self.check(PERSONAL, include_ineligible=True, limit=500)
        self.check(BUSINESS, include_ineligible=True, limit=200)

    def test_tag_keyword_and_closed(self):
        self.check(PERSONAL, tag="housing")
        self.check(PERSONAL, keyword="월세")
        self.check(BUSINESS, include_closed=True, include_ineligible=True, limit=200)

    def test_each_option_has_its_own_entry(self):
        catalog, _ = self.check(PERSONAL, limit=5)
        cache = catalog.memo["search_results"]
        before = len(cache._entries)
        engine.search(catalog, PERSONAL, limit=6)
        engine.search(catalog, PERSONAL, limit=5, include_ineligible=True)
        self.assertEqual(len(cache._entries), before + 2)

    def test_cache_hit_does_not_recompute(self):
        catalog = self.fresh()
        expected = reference_search(catalog, PERSONAL)
        engine.search(catalog, PERSONAL)
        original = engine.evaluate_service

        def boom(*_args, **_kwargs):
            raise AssertionError("캐시 적중인데 다시 판정했습니다")

        engine.evaluate_service = boom
        try:
            self.assertEqual(engine.search(catalog, PERSONAL), expected)
        finally:
            engine.evaluate_service = original

    def test_caller_mutation_does_not_poison_cache(self):
        catalog = self.fresh()
        expected = reference_search(catalog, PERSONAL, limit=5)
        result = engine.search(catalog, PERSONAL, limit=5)
        result["counts"]["eligible_likely"] = -1
        result["results"].clear()
        self.assertEqual(engine.search(catalog, PERSONAL, limit=5), expected)

    def test_different_profiles_do_not_share_entries(self):
        catalog = self.fresh()
        young = profile(age=30, income_band="JA0203", situations=["no_home"])
        old = profile(age=70, income_band="JA0203", situations=["no_home"])
        expected_young = reference_search(catalog, young)
        expected_old = reference_search(catalog, old)
        self.assertNotEqual(expected_young["counts"], expected_old["counts"])
        self.assertEqual(engine.search(catalog, young), expected_young)
        self.assertEqual(engine.search(catalog, old), expected_old)

    def test_catalogs_do_not_share_entries(self):
        first, second = self.fresh(), self.fresh()
        engine.search(first, PERSONAL)
        self.assertNotIn("search_results", second.memo)
        self.assertEqual(engine.search(second, PERSONAL), reference_search(second, PERSONAL))


class ResultCacheBudgetTest(unittest.TestCase):
    def test_rows_budget_evicts_oldest(self):
        cache = engine._ResultCache(max_rows=10)
        cache.put(("a",), {"results": []}, 4)
        cache.put(("b",), {"results": []}, 4)
        self.assertIsNotNone(cache.get(("a",)))
        cache.put(("c",), {"results": []}, 4)   # 12행 → 가장 오래된 a(방금 읽었으므로 b)부터 축출
        self.assertEqual(cache._rows, 8)
        cache.put(("d",), {"results": []}, 11)  # 한 건이 상한을 넘으면 담지 않는다
        self.assertIsNone(cache.get(("d",)))

    def test_big_result_is_not_cached(self):
        catalog = sample_catalog()
        cache = engine._ResultCache(max_rows=5)
        catalog.memo["search_results"] = cache
        engine.search(catalog, EMPTY)
        self.assertEqual(len(cache._entries), 0)


class TailRulesCacheTest(unittest.TestCase):
    """선정기준 규칙은 프로필과 무관하다 — 캐시해도 판정이 같아야 한다."""

    def test_cached_rules_match_fresh_rules(self):
        catalog = sample_catalog()
        for svc in catalog.services[:20]:
            fresh = (engine._check_business_criteria(svc) if svc.is_business
                     else engine._check_criteria(svc))
            cached = engine._criteria_rules(svc)
            self.assertEqual(list(cached), fresh)
            self.assertIs(engine._criteria_rules(svc), cached, "두 번째 호출은 같은 객체")

    def test_evaluation_same_before_and_after_cache(self):
        catalog = sample_catalog()
        for svc in catalog.services[:20]:
            svc.__dict__.pop(engine._TAIL_RULES_ATTR, None)
            before = engine.evaluate_service(svc, PERSONAL)
            engine._criteria_rules(svc)
            after = engine.evaluate_service(svc, PERSONAL)
            self.assertEqual(before, after)


class PseoItemsCacheTest(unittest.TestCase):
    def test_items_are_built_once(self):
        catalog = sample_catalog()
        first = pseo.items(catalog)
        self.assertIn("pseo_items", catalog.memo)
        stored = catalog.memo["pseo_items"]
        original = pseo._collect

        def boom(*_args, **_kwargs):
            raise AssertionError("캐시가 있는데 페이지 목록을 다시 만들었습니다")

        pseo._collect = boom
        try:
            second = pseo.items(catalog)
        finally:
            pseo._collect = original
        self.assertIs(catalog.memo["pseo_items"], stored)
        self.assertEqual([page["slug"] for page in first], [page["slug"] for page in second])
        self.assertEqual([len(page["services"]) for page in first],
                         [len(page["services"]) for page in second])

    def test_items_match_fresh_build(self):
        catalog = sample_catalog()
        cached = pseo.items(catalog)
        fresh = pseo._build_items(catalog)
        self.assertEqual([(page["slug"], len(page["services"]), page["indexable"])
                          for page in cached],
                         [(page["slug"], len(page["services"]), page["indexable"])
                          for page in fresh])


@unittest.skipUnless(HAS_DATA, "동기화 산출물이 없어 건너뜁니다")
class LiveCatalogEquivalenceTest(unittest.TestCase):
    """실데이터(1.2만 건)에서도 캐시 결과가 기준 계산과 같아야 한다."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(CATALOG)

    def test_region_personal_profile(self):
        self.assertEqual(engine.search(self.catalog, PERSONAL),
                         reference_search(self.catalog, PERSONAL))

    def test_region_business_profile(self):
        self.assertEqual(engine.search(self.catalog, BUSINESS_OPERATING),
                         reference_search(self.catalog, BUSINESS_OPERATING))

    def test_no_region_profile(self):
        self.assertEqual(engine.search(self.catalog, PERSONAL_NO_REGION, limit=5),
                         reference_search(self.catalog, PERSONAL_NO_REGION, limit=5))

    def test_second_call_is_cache_hit(self):
        engine.search(self.catalog, PERSONAL_CHILD, limit=7)
        original = engine.evaluate_service

        def boom(*_args, **_kwargs):
            raise AssertionError("캐시 적중인데 다시 판정했습니다")

        engine.evaluate_service = boom
        try:
            result = engine.search(self.catalog, PERSONAL_CHILD, limit=7)
        finally:
            engine.evaluate_service = original
        self.assertTrue(result["scanned"])
        self.assertEqual(len(result["results"]), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
