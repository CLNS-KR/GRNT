"""검색 동의어 확장(`synonyms.py`) 테스트 — 사전·정렬·두 백엔드 일치·과매칭 방지."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import engine, synonyms  # noqa: E402
from subsidy_kr.api import call_tool  # noqa: E402
from subsidy_kr.catalog import Catalog, sample_catalog, search_text  # noqa: E402
from subsidy_kr.catalog import normalize_service  # noqa: E402
from subsidy_kr.sample_data import services as sample_services  # noqa: E402
from subsidy_kr.sqlite_store import SQLiteCatalog, build_sqlite_from_rows  # noqa: E402

TODAY = "2026-11-21"


def profile(**extra):
    raw = {"age": 34, "income_band": "JA0203", "situations": ["no_home"],
           "region": {"sido": "인천광역시", "sigungu": "서구"}}
    raw.update(extra)
    return engine.normalize_profile(raw)


class DictionaryTest(unittest.TestCase):
    def test_every_weight_is_a_low_priority_alias(self):
        for cluster in synonyms.CLUSTERS:
            for term, weight in cluster:
                self.assertGreater(weight, 0.0, term)
                self.assertLessEqual(weight, 1.0, term)
                # 사전 밖에서 쓰일 때(다른 말로 검색했을 때)는 항상 직접 일치보다 낮다
                for _other, effective in synonyms.variants(term)[1:]:
                    self.assertLess(effective, 1.0, term)

    def test_no_duplicate_terms_across_clusters(self):
        seen = {}
        for index, cluster in enumerate(synonyms.CLUSTERS):
            for term, _weight in cluster:
                self.assertNotIn(term, seen, f"{term}: {seen.get(term)} · {index}")
                seen[term] = index

    def test_briefed_pairs_expand(self):
        pairs = {
            "월세": ("주거비", "임차료"),
            "배달비": ("택배비", "배달앱"),
            "전기세": ("전기요금",),
            "산후조리": ("산모",),
            "창업자금": ("창업지원", "사업화"),
            "인건비": ("고용장려금", "채용지원"),
            "폐업": ("재기", "희망리턴"),
            "육아휴직": ("출산휴가", "육아"),
            "병원비": ("의료비",),
            "학자금": ("등록금", "장학금"),
            "치매": ("장기요양", "요양보호"),
        }
        for word, expected in pairs.items():
            terms = [term for term, _weight in synonyms.variants(word)]
            for needle in expected:
                self.assertIn(needle, terms, f"{word} → {needle}")

    def test_direct_term_comes_first_with_full_weight(self):
        group = synonyms.variants("전기세")[0]
        self.assertEqual(group[0], "전기세")
        for _term, weight in synonyms.variants("전기세")[1:]:
            self.assertLess(weight, 1.0)

    def test_variant_count_is_capped(self):
        for word in ("전기세", "배달비", "인건비", "학자금", "창업자금"):
            self.assertLessEqual(len(synonyms.variants(word)), synonyms.MAX_VARIANTS, word)

    def test_josa_is_stripped_only_for_known_words(self):
        self.assertEqual(synonyms.normalize("월세가"), "월세")
        self.assertEqual(synonyms.normalize("전기세는?"), "전기세")
        self.assertEqual(synonyms.normalize("학자금으로"), "학자금")
        # 낱말의 일부인 '도'는 떼지 않는다
        self.assertEqual(synonyms.normalize("없는제도"), "없는제도")
        self.assertEqual(synonyms.normalize("제도"), "제도")

    def test_unknown_words_are_not_expanded(self):
        phone = "010-" "1234-" "5678"
        for word in ("없는제도", phone, "인천광역시"):
            self.assertEqual([term for term, _ in synonyms.plan(word)[0]], [word])
        self.assertFalse(synonyms.is_expanded("없는제도"))
        self.assertIsNone(synonyms.describe("없는제도"))

    def test_multiple_words_are_and_groups(self):
        groups = synonyms.plan("청년 월세")
        self.assertEqual(len(groups), 2)
        self.assertTrue(synonyms.matches("청년 월세 지원", groups))
        self.assertTrue(synonyms.matches("청년 주거비 지원", groups))
        self.assertFalse(synonyms.matches("청년 지원", groups))

    def test_direct_match_scores_higher_than_synonym(self):
        groups = synonyms.plan("월세")
        direct = synonyms.score("청년월세 지원", "청년월세 지원 월세", groups)
        alias = synonyms.score("청년 주거비 지원", "청년 주거비 지원", groups)
        self.assertGreater(direct, alias)
        self.assertGreater(alias, 0)
        self.assertEqual(synonyms.score("아무 관련 없는 제도", "아무 관련 없는 제도", groups), 0)


class CatalogSearchTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_josa_query_finds_the_topic(self):
        names = [svc.name for svc in self.catalog.search("월세가")]
        self.assertIn("청년월세 한시 특별지원", names)

    def test_synonym_brings_related_posting(self):
        strict = [svc.name for svc in self.catalog.search("월세", expand=False)]
        expanded = [svc.name for svc in self.catalog.search("월세", expand=True)]
        self.assertNotIn("부산광역시 청년 주거비 지원", strict)
        self.assertIn("부산광역시 청년 주거비 지원", expanded)
        # 직접 일치가 항상 앞 — 확장으로 들어온 주거비 제도가 1위가 되지 않는다
        self.assertIn("월세", expanded[0])
        self.assertNotIn("부산광역시 청년 주거비 지원", expanded[:2])

    def test_expand_can_be_turned_off(self):
        self.assertEqual([svc.name for svc in self.catalog.search("학자금", expand=False)], [])
        self.assertTrue([svc.name for svc in self.catalog.search("학자금", expand=True)])

    def test_nonsense_query_stays_empty(self):
        self.assertEqual(self.catalog.search("없는제도"), [])
        self.assertEqual(self.catalog.search("010-" "1234-" "5678"), [])


class SQliteSearchParityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        rows = sample_services()
        meta = {"generated_on": f"{TODAY}T00:00:00+09:00", "data_state": "live_sync"}
        path = os.path.join(self.tmp, "catalog.sqlite")
        build_sqlite_from_rows(rows, meta, path)
        self.sqlite = SQLiteCatalog(path)
        self.memory = Catalog([normalize_service(row) for row in rows], meta)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_search_text_is_shared(self):
        for svc in self.sqlite.services:
            self.assertEqual(search_text(svc), search_text(self.memory.get(svc.service_id)))

    def test_same_hits_on_both_backends(self):
        for query in ("월세", "학자금", "청년", "없는제도"):
            with self.subTest(query=query):
                self.assertEqual([svc.service_id for svc in self.sqlite.search(query)],
                                 [svc.service_id for svc in self.memory.search(query)])

    def test_engine_expansion_matches_on_both_backends(self):
        prof = profile()
        for query in ("월세", "학자금"):
            with self.subTest(query=query):
                memory = engine.search(self.memory, prof, keyword=query, limit=50,
                                       include_ineligible=True, expand_keyword=True)
                sqlite = engine.search(self.sqlite, prof, keyword=query, limit=50,
                                       include_ineligible=True, expand_keyword=True)
                self.assertEqual(sorted(row["service_id"] for row in memory["results"]),
                                 sorted(row["service_id"] for row in sqlite["results"]))


class EngineExpansionTest(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_expansion_is_off_by_default(self):
        strict = engine.search(self.catalog, profile(), keyword="학자금", limit=50,
                               include_ineligible=True)
        self.assertEqual(strict["results"], [])

    def test_expansion_fills_zero_result_search(self):
        expanded = engine.search(self.catalog, profile(region=None), keyword="학자금",
                                 limit=50, include_ineligible=True, include_closed=True,
                                 expand_keyword=True)
        names = [row["name"] for row in expanded["results"]]
        self.assertIn("국가장학금", names)

    def test_direct_hits_stay_ahead_of_expanded_hits(self):
        result = engine.search(self.catalog, profile(region=None), keyword="월세가", limit=50,
                               include_ineligible=True, include_closed=True, expand_keyword=True)
        names = [row["name"] for row in result["results"]]
        direct = {"청년월세 한시 특별지원", "인천광역시 서구 청년월세 지원"}
        self.assertTrue(direct.issubset(set(names)))
        self.assertIn("부산광역시 청년 주거비 지원", names)
        # 질의어를 담은 제도가 동의어로만 걸린 제도보다 앞
        self.assertTrue(set(names[:2]) == direct)

    def test_expanded_search_does_not_drop_direct_results(self):
        strict = engine.search(self.catalog, profile(region=None), keyword="월세", limit=50,
                               include_ineligible=True, include_closed=True)
        expanded = engine.search(self.catalog, profile(region=None), keyword="월세", limit=50,
                                 include_ineligible=True, include_closed=True,
                                 expand_keyword=True)
        strict_ids = {row["service_id"] for row in strict["results"]}
        expanded_ids = {row["service_id"] for row in expanded["results"]}
        self.assertTrue(strict_ids.issubset(expanded_ids))
        self.assertGreater(expanded["scanned"], strict["scanned"])

    def test_cache_separates_expanded_and_strict(self):
        strict = engine.search(self.catalog, profile(region=None), keyword="월세", limit=5,
                               include_ineligible=True, include_closed=True)
        expanded = engine.search(self.catalog, profile(region=None), keyword="월세", limit=5,
                                 include_ineligible=True, include_closed=True,
                                 expand_keyword=True)
        self.assertNotEqual(strict, expanded)

    def test_service_meta_declares_search_behavior(self):
        meta = call_tool("get_service_meta", {}, self.catalog)["result"]["search"]
        self.assertEqual(meta["synonym_groups"], len(synonyms.CLUSTERS))
        self.assertEqual(meta["max_variants_per_word"], synonyms.MAX_VARIANTS)
        self.assertTrue(meta["direct_match_first"])
        self.assertTrue(any("→" in item for item in meta["expands"]))
        self.assertIn("동의어", meta["note_ko"])

    def test_api_payload_explains_expansion(self):
        payload = call_tool("search_subsidies",
                            {"profile": {"age": 34, "income_band": "JA0203"},
                             "keyword": "학자금"}, self.catalog)["result"]
        self.assertIn("동의어 확장", payload["keyword_note_ko"])
        plain = call_tool("search_subsidies",
                          {"profile": {"age": 34, "income_band": "JA0203"},
                           "keyword": "없는제도"}, self.catalog)["result"]
        self.assertNotIn("keyword_note_ko", plain)


if __name__ == "__main__":
    unittest.main(verbosity=2)
