"""거래처 일괄 익명 매칭(세무·노무 사무소용) 테스트.

검증하는 것
-----------
1. CSV 경계 — 헤더 별칭·BOM·한글 열, 민감 열 값을 **읽지 않는지**, note 기본 폐기
2. 값 해석 — '2억'·'5천만원'·'1억~3억' 같은 매출 표기와 지역 표기
3. 매칭 — 거래처당 3~5건, 판정·마감·링크, 1차 필터가 엔진 판정과 같은 답을 내는지
4. 내보내기 — CSV(BOM·수식 주입·상호 열 없음), 1페이지 HTML(page-break·escape·버튼)
5. API·MCP·HTTP — 툴 등록·봉투·`/v1/batch-match` JSON·CSV 본문·샘플·내보내기
6. 성능 — 실데이터 기준 50·300곳이 2초 안에 끝나는지(없으면 샘플로 확인)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from subsidy_kr import agent_report, api, batch_client, engine, mcp_http  # noqa: E402
from subsidy_kr.catalog import load_catalog, sample_catalog  # noqa: E402
from subsidy_kr.server import make_handler  # noqa: E402
from subsidy_kr.store import Store  # noqa: E402

REAL_CATALOG = os.path.join(PROJECT, "data", "gov24", "catalog.json")
HAS_DATA = os.path.exists(REAL_CATALOG) or os.path.exists(REAL_CATALOG + ".gz")


def _csv(rows, header=None):
    header = header or ["client_ref", "industry", "employees", "revenue_bracket",
                        "business_age_years", "region", "note"]
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(row.get(column, "")) for column in header))
    return "\n".join(lines) + "\n"


BASIC_ROWS = [
    {"client_ref": "C-001", "industry": "음식숙박", "employees": "3",
     "revenue_bracket": "1억~2억", "business_age_years": "4", "region": "인천광역시 서구",
     "note": "음식점"},
    {"client_ref": "C-002", "industry": "제조", "employees": "8", "revenue_bracket": "30억~50억",
     "business_age_years": "9", "region": "경기도 화성시", "note": "부품"},
    {"client_ref": "C-003", "industry": "it", "employees": "5", "revenue_bracket": "",
     "business_age_years": "3", "region": "서울특별시 마포구", "note": ""},
    {"client_ref": "C-004", "industry": "도소매", "employees": "2",
     "revenue_bracket": "5천만원 미만", "business_age_years": "1", "region": "부산광역시 해운대구",
     "note": ""},
]


class ParseTest(unittest.TestCase):
    def test_money_formats(self):
        cases = {
            "2억": 200_000_000,
            "2.5억": 250_000_000,
            "5천만원": 50_000_000,
            "3,000만 원": 30_000_000,
            "200000000": 200_000_000,
            "1억2천만": 120_000_000,
        }
        for text, expected in cases.items():
            self.assertEqual(batch_client.parse_money_krw(text), expected, text)

    def test_money_rejects_garbage(self):
        for value in ("", "모름", "-", "abc"):
            self.assertIsNone(batch_client.parse_money_krw(value))

    def test_bracket_uses_upper_bound(self):
        self.assertEqual(batch_client.parse_bracket_krw("1억~3억")[0], 300_000_000)
        self.assertEqual(batch_client.parse_bracket_krw("5천만원 미만")[0], 50_000_000)
        amount, note = batch_client.parse_bracket_krw("3억 이상")
        self.assertEqual(amount, 300_000_000)
        self.assertIn("하한", note)

    def test_region_text(self):
        block = batch_client.parse_region_text("인천광역시 서구")
        self.assertEqual(block["sido"], "인천광역시")
        self.assertIn(block["level"], ("sido", "sigungu"))
        self.assertEqual(batch_client.parse_region_text("")["level"], "national")

    def test_industry_hints(self):
        self.assertEqual(batch_client.resolve_industry("IT·정보통신"), "ict")
        self.assertEqual(batch_client.resolve_industry("음식점"), "food")
        self.assertEqual(batch_client.resolve_industry("없는업종"), None)


class CsvBoundaryTest(unittest.TestCase):
    def test_korean_headers_and_bom(self):
        text = "\ufeff거래처코드,업종,직원수,연매출,업력,지역,비고\nC-100,음식숙박,3,200000000,4,인천 서구,메모\n"
        parsed = batch_client.parse_clients_csv(text)
        client = parsed["clients"][0]
        self.assertEqual(client["client_ref"], "C-100")
        self.assertEqual(client["industry"], "food")
        self.assertEqual(client["employees"], 3)
        self.assertEqual(client["revenue_krw"], 200_000_000)
        self.assertEqual(client["business_age_years"], 4.0)

    def test_sensitive_columns_are_named_not_read(self):
        text = _csv(
            [{"client_ref": "C-001", "company_name": "가상상사", "biz_no": "111-22-33333",
              "industry": "food", "employees": "3", "region": "인천광역시 서구"}],
            header=["client_ref", "company_name", "biz_no", "industry", "employees", "region"],
        )
        parsed = batch_client.parse_clients_csv(text)
        self.assertIn("company_name", parsed["columns_dropped_sensitive"])
        self.assertIn("biz_no", parsed["columns_dropped_sensitive"])
        serialized = json.dumps(parsed, ensure_ascii=False)
        self.assertNotIn("가상상사", serialized)
        self.assertNotIn("111-22-33333", serialized)
        client = parsed["clients"][0]
        self.assertNotIn("company_name", client)
        self.assertNotIn("biz_no", client)

    def test_note_dropped_by_default_and_kept_only_with_flag(self):
        text = _csv(BASIC_ROWS)
        parsed = batch_client.parse_clients_csv(text)
        self.assertEqual(parsed["clients"][0]["label"], "")
        labelled = batch_client.parse_clients_csv(text, allow_labels=True)
        self.assertEqual(labelled["clients"][0]["label"], "음식점")
        self.assertLessEqual(len(labelled["clients"][0]["label"]), batch_client.MAX_LABEL_LEN)

    def test_refs_are_generated_and_unique(self):
        text = _csv([{"industry": "food"}, {"client_ref": "C-001"}, {"client_ref": "C-001"}],
                    header=["client_ref", "industry"])
        parsed = batch_client.parse_clients_csv(text)
        refs = [client["client_ref"] for client in parsed["clients"]]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertEqual(refs[0], "C-001")
        self.assertTrue(refs[1].startswith("C-001"))

    def test_semicolon_and_tab_delimiters(self):
        text = "client_ref;industry;employees\nC-9;food;2\n"
        self.assertEqual(batch_client.parse_clients_csv(text)["clients"][0]["employees"], 2)

    def test_empty_and_header_only_raise(self):
        with self.assertRaises(ValueError):
            batch_client.parse_clients_csv("")
        with self.assertRaises(ValueError):
            batch_client.parse_clients_csv("client_ref,industry\n")

    def test_too_many_clients_raises(self):
        rows = [{"client_ref": f"C-{index:03d}", "industry": "food"} for index in range(3)]
        with self.assertRaises(ValueError):
            batch_client.parse_clients_csv(_csv(rows), max_clients=2)

    def test_json_mapping_input_drops_sensitive_keys(self):
        parsed = batch_client.clients_from_mappings([
            {"client_ref": "C-1", "상호명": "가상상사", "사업자번호": "111-22-33333",
             "industry": "food", "employees": 4},
        ])
        self.assertIn("상호명", parsed["columns_dropped_sensitive"])
        self.assertNotIn("가상상사", json.dumps(parsed, ensure_ascii=False))

    def test_sample_csv_contains_identity_headers(self):
        text = batch_client.sample_csv()
        header = text.splitlines()[0]
        self.assertIn("company_name", header)
        self.assertIn("biz_no", header)
        self.assertIn("revenue_krw", header)


class MatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()

    def test_each_client_gets_three_to_five(self):
        payload = batch_client.match_clients(self.catalog, {"csv": batch_client.sample_csv()})
        self.assertEqual(payload["summary"]["clients"], 5)
        for client in payload["clients"]:
            self.assertGreaterEqual(len(client["matches"]), 3)
            self.assertLessEqual(len(client["matches"]), 5)
            counts = client["counts"]
            self.assertEqual(counts["shown"], len(client["matches"]))
            self.assertGreaterEqual(counts["candidates"], counts["evaluated"])
            ranks = [match["rank"] for match in client["matches"]]
            self.assertEqual(ranks, list(range(1, len(ranks) + 1)))

    def test_matches_have_verdict_deadline_and_link(self):
        payload = batch_client.match_clients(self.catalog, {"csv": _csv(BASIC_ROWS)})
        allowed = {"eligible_likely", "check_needed", "insufficient_info"}
        for client in payload["clients"]:
            for match in client["matches"]:
                self.assertIn(match["verdict"]["code"], allowed)
                self.assertTrue(match["verdict"]["label_ko"])
                self.assertTrue(match["deadline_date"] or match["deadline_text"])
                if match["link"]:
                    self.assertTrue(match["link"].startswith("https://"))
                self.assertIn(match["category"], agent_report.CATEGORY_ORDER)

    def test_no_identity_anywhere_in_response(self):
        payload = batch_client.match_clients(self.catalog, {"csv": batch_client.sample_csv()})
        text = json.dumps({key: value for key, value in payload.items()
                           if key not in ("report_html", "csv")}, ensure_ascii=False)
        # 민감 열 **이름**은 익명성 안내에만 나오고, 값은 어디에도 없다.
        for value in ("예시상호", "000-00-00000"):
            self.assertNotIn(value, text)
        for key in ('"company_name":', '"biz_no":', '"label": "음식점"'):
            self.assertNotIn(key, text)
        for client in payload["clients"]:
            self.assertNotIn("company_name", client)
            self.assertNotIn("biz_no", client)

    def test_allow_labels_echoes_note(self):
        payload = batch_client.match_clients(
            self.catalog, {"csv": batch_client.sample_csv(), "allow_labels": True})
        self.assertTrue(payload["anonymity"]["labels_included"])
        self.assertEqual(payload["clients"][0]["label"], "음식점")

    def test_json_clients_input(self):
        payload = batch_client.match_clients(self.catalog, {"clients": [
            {"client_ref": "J-1", "industry": "food", "employees": 3,
             "annual_revenue_krw": 200_000_000, "biz_years": 4, "sido": "인천광역시"},
        ]})
        self.assertEqual(payload["inputs"]["source"], "json")
        self.assertEqual(payload["clients"][0]["client_ref"], "J-1")
        self.assertGreaterEqual(len(payload["clients"][0]["matches"]), 3)

    def test_missing_inputs_are_reported_not_invented(self):
        payload = batch_client.match_clients(self.catalog, {"csv": _csv([
            {"client_ref": "C-900", "industry": "", "employees": "", "revenue_bracket": "",
             "business_age_years": "", "region": ""}])})
        client = payload["clients"][0]
        self.assertTrue(client["notes_ko"])
        self.assertTrue(any("조건 값이 없습니다" in note for note in client["notes_ko"]))

    def test_top_n_is_clamped(self):
        for requested, expected in ((1, 3), (3, 3), (9, 5)):
            payload = batch_client.match_clients(self.catalog, {"csv": _csv(BASIC_ROWS[:1]),
                                                                "top_n": requested})
            self.assertEqual(payload["summary"]["top_n"], expected)
            self.assertLessEqual(len(payload["clients"][0]["matches"]), expected)

    def test_keyword_narrows_candidates(self):
        base = batch_client.match_clients(self.catalog, {"csv": _csv(BASIC_ROWS[:1])})
        narrowed = batch_client.match_clients(self.catalog, {"csv": _csv(BASIC_ROWS[:1]),
                                                             "keyword": "소상공인"})
        self.assertLessEqual(narrowed["clients"][0]["counts"]["candidates"],
                             base["clients"][0]["counts"]["candidates"])

    def test_include_closed_never_reduces_candidates(self):
        base = batch_client.match_clients(self.catalog, {"csv": _csv(BASIC_ROWS[:1])})
        wide = batch_client.match_clients(self.catalog, {"csv": _csv(BASIC_ROWS[:1]),
                                                         "include_closed": True})
        self.assertGreaterEqual(wide["clients"][0]["counts"]["candidates"],
                                base["clients"][0]["counts"]["candidates"])

    def test_separate_sido_sigungu_columns(self):
        text = _csv([{"client_ref": "S-1", "industry": "food", "employees": "3",
                      "sido": "인천광역시", "sigungu": "서구"}],
                    header=["client_ref", "industry", "employees", "sido", "sigungu"])
        client = batch_client.parse_clients_csv(text)["clients"][0]
        self.assertEqual(client["region"]["sido"], "인천광역시")
        self.assertEqual(client["region"]["level"], "sigungu")

    def test_requires_csv_or_clients(self):
        with self.assertRaises(ValueError):
            batch_client.match_clients(self.catalog, {})

    def test_category_selection_covers_groups(self):
        payload = batch_client.match_clients(self.catalog, {"csv": _csv(BASIC_ROWS)})
        seen = {match["category"] for client in payload["clients"]
                for match in client["matches"]}
        # 한 거래처가 한 묶음만 받는 경우는 그 공고만 후보일 때뿐이다. 전체로는 여러 묶음이 나온다.
        self.assertGreaterEqual(len(seen), 3, f"분류가 한쪽으로 쏠렸습니다: {seen}")

    def test_select_top_seeds_one_row_per_category(self):
        rows = []
        for category in agent_report.CATEGORY_ORDER:
            for index in range(2):
                rows.append({"category": category,
                             "priority": {"tier": "medium", "score": 4},
                             "days_left": 20,
                             "name": f"{category}-{index}",
                             "service_id": f"{category}-{index}"})
        rows.sort(key=agent_report._sort_key)
        picked = batch_client._select_top(rows, 4)
        self.assertEqual({row["category"] for row in picked},
                         set(agent_report.CATEGORY_ORDER))
        self.assertEqual(len(picked), 4)

    def test_anonymity_block_states_the_boundary(self):
        payload = batch_client.match_clients(self.catalog, {"csv": batch_client.sample_csv()})
        anonymity = payload["anonymity"]
        self.assertFalse(anonymity["identity_used_in_matching"])
        self.assertFalse(anonymity["stored"])
        self.assertIn("company_name", anonymity["identity_columns_dropped"])
        self.assertTrue(anonymity["note_ko"])


class FastScreenParityTest(unittest.TestCase):
    """1차 필터(`_fast_fail`)가 엔진의 구조화 FAIL 판단과 정확히 같은지."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.cards = batch_client._program_index(cls.catalog)

    def test_matches_engine_structural_fail(self):
        profiles = []
        for industry in ("food", "manufacturing", "ict", "retail", "service", None):
            for employees in (0, 3, 9, 15):
                for revenue in (50_000_000, 2_000_000_000):
                    for years in (0, 3, 10, 20):
                        args = {"industry": industry, "employees": employees,
                                "annual_revenue_krw": revenue, "biz_years": years,
                                "biz_status": "operating", "sido": "인천광역시"}
                        spec = agent_report._parse_inputs(args)
                        size = agent_report.size_estimate(spec["industry"], spec["employees"],
                                                          spec["revenue_krw"], "operating")
                        profiles.append((spec, agent_report._engine_profile(spec, size)))
        self.assertTrue(profiles)
        for spec, profile in profiles:
            business = profile.get("business") or {}
            region = profile.get("region") or {}
            context = {
                "region_level": region.get("level") or "national",
                "sido": region.get("sido") or "",
                "sigungu": region.get("sigungu") or "",
                "status": business.get("status"),
                "entity": business.get("entity"),
                "years": business.get("years"),
                "industry": business.get("industry"),
                "age": profile.get("age"),
                "sex": profile.get("sex"),
                "entity_cache": {},
            }
            for card in self.cards:
                self.assertEqual(
                    batch_client._fast_fail(card, context),
                    engine.structural_fail(card["svc"], profile) is not None,
                    f"{profile} / {card['svc'].name}",
                )


class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.payload = batch_client.match_clients(cls.catalog, {"csv": batch_client.sample_csv()})

    def test_csv_has_bom_header_and_no_identity_columns(self):
        text = batch_client.to_csv(self.payload)
        self.assertTrue(text.startswith("\ufeff"))
        header = text.splitlines()[2]
        self.assertIn("거래처코드", header)
        self.assertNotIn("상호", header)
        rows = [line for line in text.splitlines()[3:] if line.strip()]
        expected = sum(len(client["matches"]) for client in self.payload["clients"])
        self.assertGreaterEqual(len(rows), expected)

    def test_csv_neutralises_formula_injection(self):
        payload = batch_client.match_clients(
            self.catalog, {"csv": batch_client.sample_csv(), "allow_labels": True})
        payload["clients"][0]["label"] = "=cmd()"
        payload["clients"][0]["conditions"]["industry_label"] = "-2+3"
        text = batch_client.to_csv(payload)
        self.assertIn("'=cmd()", text)
        self.assertIn("'-2+3", text)

    def test_csv_lists_clients_without_matches(self):
        payload = {"clients": [{"client_ref": "C-EMPTY", "conditions": {},
                                "matches": [], "notes_ko": ["후보 없음"]}],
                   "summary": {}, "checked_at": "2026-11-20T00:00:00+09:00",
                   "disclaimer_ko": "x"}
        text = batch_client.to_csv(payload)
        self.assertIn("C-EMPTY", text)

    def test_report_html_has_one_page_per_client(self):
        html = batch_client.to_report_html(self.payload)
        self.assertIn("<!doctype html>", html)
        self.assertEqual(html.count('class="client-page"'), len(self.payload["clients"]))
        self.assertIn("page-break-after", html)
        self.assertIn('data-print="client-C-001"', html)
        self.assertIn('data-copy="client-C-001"', html)
        self.assertIn('data-save="client-C-001"', html)
        self.assertIn(batch_client.ANONYMITY_BADGE_KO, html)

    def test_report_html_escapes_values(self):
        payload = json.loads(json.dumps(self.payload))
        payload["clients"][0]["matches"][0]["name"] = "<script>alert(1)</script>"
        payload["clients"][0]["client_ref"] = "C-<b>1</b>"
        html = batch_client.to_report_html(payload)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<b>1</b>", html)

    def test_markdown_summary(self):
        payload = dict(self.payload)
        payload["summary_ko"] = batch_client.to_markdown(payload)
        text = payload["summary_ko"]
        self.assertIn("거래처 5곳", text)
        self.assertIn("[C-001]", text)

    def test_filename_has_no_identifiers(self):
        self.assertEqual(batch_client.filename_for(self.payload, "html"),
                         "batch-client-reports.html")
        self.assertRegex(batch_client.filename_for(self.payload, "csv"),
                         r"^grnt-batch-\d+-\d{8}\.csv$")


class ToolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()

    def test_tool_is_registered(self):
        names = [definition["name"] for definition in api.TOOL_DEFS]
        self.assertIn("batch_match_clients", names)
        self.assertEqual(len(api.mcp_tools()), 9)

    def test_call_returns_envelope(self):
        result = api.call_tool("batch_match_clients",
                               {"csv": _csv(BASIC_ROWS[:2]), "top_n": 3}, self.catalog)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "batch_match_clients")
        payload = result["result"]
        self.assertIn("summary_ko", payload)
        self.assertIn("clients", payload)
        self.assertIn("disclaimer_ko", payload)
        self.assertIn("export", payload)
        self.assertNotIn("report_html", payload)
        self.assertNotIn("csv", payload)

    def test_call_can_include_exports(self):
        result = api.call_tool("batch_match_clients",
                               {"csv": _csv(BASIC_ROWS[:1]), "include_report_html": True,
                                "include_csv": True}, self.catalog)
        payload = result["result"]
        self.assertIn("client-page", payload["report_html"])
        self.assertTrue(payload["csv"].startswith("\ufeff"))

    def test_invalid_input_is_error_not_crash(self):
        result = api.call_tool("batch_match_clients", {}, self.catalog)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_argument")

    def test_too_many_is_error(self):
        rows = [{"client_ref": f"C-{index:03d}", "industry": "food"} for index in range(3)]
        result = api.call_tool("batch_match_clients", {"csv": _csv(rows),
                                                       "clients": rows}, self.catalog)
        # CSV 3건은 정상이므로 clients 쪽만 301건으로 넘겨 확인한다.
        self.assertTrue(result["ok"])
        many = [{"client_ref": f"C-{index:03d}", "industry": "food"}
                for index in range(batch_client.MAX_CLIENTS + 1)]
        result = api.call_tool("batch_match_clients", {"clients": many}, self.catalog)
        self.assertFalse(result["ok"])
        self.assertIn("too_many_clients", result["message"])

    def test_service_meta_lists_tool(self):
        result = api.call_tool("get_service_meta", {}, self.catalog)
        self.assertIn("batch_match_clients", result["result"]["tools"])

    def test_text_summary_uses_batch_markdown(self):
        result = api.call_tool("batch_match_clients", {"csv": _csv(BASIC_ROWS[:1])},
                               self.catalog)
        text = api.text_summary(result)
        self.assertIn("거래처 1곳", text)

    def test_mcp_tools_list_and_call(self):
        listed = mcp_http.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                 catalog=self.catalog)
        names = [tool["name"] for tool in listed["result"]["tools"]]
        self.assertIn("batch_match_clients", names)
        called = mcp_http.handle({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "batch_match_clients",
                       "arguments": {"csv": _csv(BASIC_ROWS[:1]), "top_n": 3}}},
            catalog=self.catalog)
        result = called["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["tool"], "batch_match_clients")
        self.assertIn("clients", result["structuredContent"]["result"])


class HttpBatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = sample_catalog()
        cls.store = Store(":memory:")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.catalog, cls.store))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()

    def _request(self, path, data=None, content_type="application/json", method="POST"):
        url = f"http://127.0.0.1:{self.port}{path}"
        request = urllib.request.Request(url, data=data, method=method,
                                         headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode("utf-8"), dict(response.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), dict(exc.headers)

    def test_post_json_csv_payload(self):
        body = json.dumps({"csv": _csv(BASIC_ROWS[:2]), "top_n": 3}).encode("utf-8")
        status, text, headers = self._request("/v1/batch-match", body)
        self.assertEqual(status, 200)
        payload = json.loads(text)
        self.assertTrue(payload["ok"])
        result = payload["result"]
        self.assertEqual(len(result["clients"]), 2)
        self.assertIn("client-page", result["report_html"])
        self.assertTrue(result["csv"].startswith("\ufeff"))
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_post_raw_csv_text(self):
        status, text, _ = self._request("/v1/batch-match", _csv(BASIC_ROWS[:1]).encode("utf-8"),
                                        content_type="text/csv")
        self.assertEqual(status, 200)
        result = json.loads(text)["result"]
        self.assertEqual(result["clients"][0]["client_ref"], "C-001")

    def test_post_json_array(self):
        body = json.dumps([{"client_ref": "A-1", "industry": "food", "employees": 3}]).encode()
        status, text, _ = self._request("/v1/batch-match", body)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(text)["result"]["clients"][0]["client_ref"], "A-1")

    def test_get_sample_csv(self):
        status, text, headers = self._request("/v1/batch-match/sample.csv", method="GET")
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers["Content-Type"])
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("client_ref", text.splitlines()[0])

    def test_export_endpoints(self):
        body = json.dumps({"csv": _csv(BASIC_ROWS[:2])}).encode()
        status, text, headers = self._request("/v1/batch-match/export.csv", body)
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers["Content-Type"])
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(headers["X-Robots-Tag"], "noindex, nofollow")
        status, text, headers = self._request("/v1/batch-match/reports.html", body)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("inline", headers["Content-Disposition"])
        self.assertIn("client-page", text)

    def test_empty_body_is_400(self):
        status, text, _ = self._request("/v1/batch-match", b"")
        self.assertEqual(status, 400)
        self.assertFalse(json.loads(text)["ok"])

    def test_oversized_body_is_413(self):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = b"x" * (batch_client.MAX_CLIENTS + 600000)
            conn.putrequest("POST", "/v1/batch-match")
            conn.putheader("Content-Type", "text/plain")
            conn.putheader("Content-Length", str(len(payload)))
            conn.endheaders()
            try:
                conn.send(payload)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            resp = conn.getresponse()
            self.assertEqual(resp.status, 413)
        finally:
            conn.close()

    def test_too_many_clients_is_400(self):
        rows = [{"client_ref": f"C-{index:03d}", "industry": "food"}
                for index in range(batch_client.MAX_CLIENTS + 1)]
        status, text, _ = self._request("/v1/batch-match",
                                        json.dumps({"clients": rows}).encode())
        self.assertEqual(status, 400)
        self.assertIn("too_many_clients", json.loads(text)["message"])

    def test_web_page_has_batch_section(self):
        status, text, _ = self._request("/", method="GET")
        self.assertEqual(status, 200)
        for marker in ('id="batch-card"', 'id="batch-csv"', 'id="batch-run"',
                       'id="batch-download-sample"', 'id="batch-actions"',
                       '/v1/batch-match/sample.csv',
                       "상호명·사업자번호는 서버 매칭에 쓰지 않고 조건 코드만 처리합니다"):
            self.assertIn(marker, text)


class PerformanceTest(unittest.TestCase):
    """50·300곳이 한 번에 끝나는지 — 실데이터가 있으면 그걸로 잰다."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(REAL_CATALOG) if HAS_DATA else sample_catalog()
        batch_client._program_index(cls.catalog)

    def _run(self, count):
        started = time.perf_counter()
        payload = batch_client.match_clients(self.catalog, {"csv": batch_client.sample_batch(count)})
        elapsed = time.perf_counter() - started
        return payload, elapsed

    def test_fifty_clients(self):
        payload, elapsed = self._run(50)
        self.assertEqual(payload["summary"]["clients"], 50)
        self.assertLess(elapsed, 2.0, f"50곳 {elapsed:.2f}s")

    def test_three_hundred_clients(self):
        payload, elapsed = self._run(300)
        self.assertEqual(payload["summary"]["clients"], 300)
        self.assertEqual(payload["summary"]["matches"], 1500)
        self.assertLess(elapsed, 2.0, f"300곳 {elapsed:.2f}s")
        self.assertLess(payload["summary"]["elapsed_ms"], 2000)

    def test_repeat_run_is_not_slower(self):
        self._run(10)
        _payload, elapsed = self._run(300)
        self.assertLess(elapsed, 2.0)


@unittest.skipUnless(HAS_DATA, "동기화 산출물이 없어 건너뜁니다")
class LiveBatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(REAL_CATALOG)

    def test_live_catalog_matches_are_real_programs(self):
        payload = batch_client.match_clients(self.catalog, {"csv": _csv(BASIC_ROWS)})
        for client in payload["clients"]:
            for match in client["matches"]:
                self.assertIsNotNone(self.catalog.get(match["service_id"]), match["service_id"])

    def test_fast_screen_matches_engine_on_live_catalog(self):
        cards = batch_client._program_index(self.catalog)
        profiles = []
        for industry in ("food", "manufacturing", "ict", None):
            for employees in (2, 12):
                for region in ({"sido": "인천광역시", "sigungu": "서구"}, {"sido": "경기도"}):
                    args = {"industry": industry, "employees": employees,
                            "annual_revenue_krw": 500_000_000, "biz_years": 6,
                            "biz_status": "operating", **region}
                    spec = agent_report._parse_inputs(args)
                    size = agent_report.size_estimate(spec["industry"], spec["employees"],
                                                      spec["revenue_krw"], "operating")
                    profiles.append(agent_report._engine_profile(spec, size))
        checked = 0
        for profile in profiles:
            business = profile.get("business") or {}
            region = profile.get("region") or {}
            context = {
                "region_level": region.get("level") or "national",
                "sido": region.get("sido") or "",
                "sigungu": region.get("sigungu") or "",
                "status": business.get("status"),
                "entity": business.get("entity"),
                "years": business.get("years"),
                "industry": business.get("industry"),
                "age": profile.get("age"),
                "sex": profile.get("sex"),
                "entity_cache": {},
            }
            for card in cards[:400]:
                self.assertEqual(
                    batch_client._fast_fail(card, context),
                    engine.structural_fail(card["svc"], profile) is not None,
                    f"{business} / {card['svc'].name}",
                )
                checked += 1
        self.assertEqual(checked, len(profiles) * min(400, len(cards)))

    def test_no_identity_leaks_in_large_batch(self):
        payload = batch_client.match_clients(self.catalog,
                                             {"csv": batch_client.sample_batch(60)})
        text = json.dumps(payload["clients"], ensure_ascii=False)
        self.assertNotIn("예시상호", text)
        self.assertNotIn("company_name", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
