"""카탈로그 자동 갱신(`refresh_catalog`) 회귀 테스트.

확인하는 것
- 오프라인에서도 지금 있는 카탈로그로 **오늘 기준 만료 인덱스**를 다시 만든다.
- 재수집이 실패해도 기존 카탈로그를 지우지 않고 부분 실패로 끝난다.
- 압축본은 내용이 바뀌었을 때만 다시 쓴다(매일 불필요한 커밋 방지).
- dry-run 은 아무 파일도 쓰지 않고, 카탈로그가 없으면 실패로 끝난다.
"""
from __future__ import annotations

import contextlib
import gzip
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from subsidy_kr import refresh_catalog, usage  # noqa: E402


def _row(service_id: str, name: str, deadline: str) -> dict:
    return {
        "서비스ID": service_id,
        "서비스명": name,
        "서비스목적요약": "테스트용 제도",
        "소관기관명": "테스트기관",
        "서비스분야": "주거·자립",
        "사용자구분": "개인",
        "지원대상": "전국 만 19세 이상",
        "지원내용": "테스트 지원금",
        "신청기한": deadline,
    }


def _range(start: date, end: date) -> str:
    return f"{start.isoformat()} ~ {end.isoformat()}"


class RefreshCatalogTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="grnt-refresh-")
        self.addCleanup(shutil.rmtree, self.root, True)
        today = date.today()
        self.rows = [
            _row("T-EXPIRED-PAST", "이미 마감된 제도", _range(today - timedelta(days=60),
                                                            today - timedelta(days=30))),
            _row("T-EXPIRED-YESTERDAY", "어제 마감된 제도", _range(today - timedelta(days=10),
                                                                today - timedelta(days=1))),
            _row("T-OPEN-TOMORROW", "내일 마감되는 제도", _range(today - timedelta(days=5),
                                                             today + timedelta(days=1))),
            _row("T-OPEN-LATER", "아직 열린 제도", _range(today, today + timedelta(days=90))),
        ]

    # --- 도우미 -------------------------------------------------------------
    def _write_catalog(self, rows=None, name="catalog.json"):
        payload = {"meta": {"dataset_id": "TEST", "catalog_state": "synced",
                            "generated_on": "2026-01-01T00:00:00+09:00"},
                   "services": self.rows if rows is None else rows}
        path = os.path.join(self.root, name)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if name.endswith(".gz"):
            with gzip.open(path, "wb") as handle:
                handle.write(raw)
        else:
            with open(path, "wb") as handle:
                handle.write(raw)
        return payload

    def _read(self, name):
        with open(self._path(name), "rb") as handle:
            return handle.read()

    def _path(self, name):
        return os.path.join(self.root, name)

    def _index_counts(self):
        conn = sqlite3.connect(self._path("catalog.sqlite"))
        try:
            total = conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]
            expired = conn.execute("SELECT COUNT(*) FROM services WHERE is_expired = 1").fetchone()[0]
            return total, expired
        finally:
            conn.close()

    # --- 테스트 -------------------------------------------------------------
    def test_offline_rebuilds_index_with_today_flags(self):
        self._write_catalog()
        report = refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["state"], "index_only")
        total, expired = self._index_counts()
        self.assertEqual(total, 4)
        # 어제 마감 + 30일 지난 마감 = 2건이 오늘 기준 만료
        self.assertEqual(expired, 2)
        self.assertEqual(report["index"]["expired"], 2)
        self.assertEqual(report["index"]["open_total"], 2)
        self.assertTrue(os.path.exists(self._path("catalog.json.gz")))

    def test_gzip_matches_catalog_json(self):
        self._write_catalog()
        refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)
        with open(self._path("catalog.json"), "rb") as handle:
            raw = handle.read()
        with gzip.open(self._path("catalog.json.gz"), "rb") as handle:
            self.assertEqual(handle.read(), raw)

    def test_rerun_reports_no_change(self):
        self._write_catalog()
        first = refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)
        self.assertTrue(first["changes"]["gzip_changed"])
        second = refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)
        self.assertFalse(second["changes"]["gzip_changed"])
        self.assertFalse(second["changes"]["catalog_json_changed"])
        self.assertTrue(second["changes"]["index_rebuilt"])
        self.assertEqual(second["changes"]["expired_delta"], 0)

    def test_content_change_rewrites_gzip(self):
        self._write_catalog()
        refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)
        rows = [dict(row) for row in self.rows]
        rows[0]["지원내용"] = "금액이 바뀐 제도"
        self._write_catalog(rows=rows)
        report = refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)
        self.assertTrue(report["changes"]["gzip_changed"])

    def test_network_failure_keeps_existing_catalog(self):
        self._write_catalog()
        before = self._read("catalog.json")
        failure = {"ok": False, "state": "failed", "error": "network"}
        with mock.patch.object(refresh_catalog.sync_gov24, "sync_all", return_value=failure):
            report = refresh_catalog.refresh(data_dir=self.root, service_key="test-key", log=lambda _m: None)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["state"], "index_only")
        self.assertEqual(self._read("catalog.json"), before)
        self.assertTrue(any("재수집 실패" in warning for warning in report["warnings"]))
        self.assertEqual(self._index_counts()[0], 4)

    def test_sync_exception_is_tolerated(self):
        self._write_catalog(name="catalog.json.gz")  # 원본 없이 압축본만 있는 상태
        with mock.patch.object(refresh_catalog.sync_gov24, "sync_all",
                               side_effect=RuntimeError("boom")):
            report = refresh_catalog.refresh(data_dir=self.root, service_key="test-key", log=lambda _m: None)
        self.assertTrue(report["ok"], report)
        self.assertEqual(self._index_counts()[0], 4)

    def test_successful_sync_reports_refresh(self):
        def fake_sync(*_args, **_kwargs):
            self._write_catalog()
            return {"ok": True, "state": "synced", "stats": {"services": 4}}

        with mock.patch.object(refresh_catalog.sync_gov24, "sync_all", side_effect=fake_sync):
            report = refresh_catalog.refresh(data_dir=self.root, service_key="test-key", offline=False, log=lambda _m: None)
        self.assertTrue(report["ok"])
        self.assertEqual(report["state"], "refreshed")
        self.assertTrue(report["changes"]["catalog_json_changed"])

    def test_default_run_forces_fresh_fetch(self):
        self._write_catalog()
        calls = {}

        def fake_sync(*_args, **kwargs):
            calls.update(kwargs)
            return {"ok": True, "state": "synced"}

        with mock.patch.object(refresh_catalog.sync_gov24, "sync_all", side_effect=fake_sync):
            refresh_catalog.refresh(data_dir=self.root, service_key="test-key",
                                    log=lambda _m: None)
        # 7일 응답 캐시를 쓰면 '매일 갱신'이 의미가 없다 — 기본은 매번 새로 받는다
        self.assertEqual(calls.get("ttl_hours"), 0.0)
        self.assertTrue(calls.get("force"))
        # 지자체 자체 복지포털도 매일 다시 받는다(공공데이터 API 밖 데이터)
        self.assertTrue(calls.get("include_local_portals"))

    def test_missing_key_falls_back_to_offline(self):
        self._write_catalog()
        with mock.patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": "",
                                          "GOV24_SERVICE_KEY": ""}):
            with mock.patch.object(refresh_catalog.sync_gov24, "sync_all",
                                   side_effect=AssertionError("network must not run")):
                report = refresh_catalog.refresh(data_dir=self.root, log=lambda _m: None)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["offline"])
        self.assertTrue(any("인증키가 없어" in warning for warning in report["warnings"]))

    def test_dry_run_writes_nothing(self):
        self._write_catalog()
        report = refresh_catalog.refresh(data_dir=self.root, offline=True, dry_run=True, log=lambda _m: None)
        self.assertTrue(report["ok"])
        self.assertTrue(report["dry_run"])
        self.assertFalse(os.path.exists(self._path("catalog.sqlite")))
        self.assertFalse(os.path.exists(self._path("catalog.json.gz")))
        self.assertFalse(report["changes"]["index_rebuilt"])

    def test_missing_catalog_fails_without_writing(self):
        report = refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)
        self.assertFalse(report["ok"])
        self.assertEqual(report["state"], "no_catalog")
        self.assertEqual(os.listdir(self.root), [])

    def test_cli_returns_one_without_catalog(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = refresh_catalog.main(["--data-dir", self.root, "--offline", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["state"], "no_catalog")

    def test_cli_json_and_exit_code(self):
        self._write_catalog()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = refresh_catalog.main(["--data-dir", self.root, "--offline", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertTrue(report["ok"])
        self.assertEqual(report["catalog"]["services"], 4)

    def test_cli_rejects_unknown_source(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = refresh_catalog.main(["--data-dir", self.root, "--sources", "nope"])
        self.assertEqual(code, 2)
        self.assertIn("nope", err.getvalue())

    def test_index_meta_records_build_day(self):
        self._write_catalog()
        refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)
        conn = sqlite3.connect(self._path("catalog.sqlite"))
        try:
            value = conn.execute(
                "SELECT value_json FROM meta WHERE key = 'index_built_on'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(json.loads(value), date.today().isoformat())

    def test_report_has_no_personal_terms(self):
        """보고서·로그에 사용자 식별 정보가 새지 않는다(경로·건수만)."""
        self._write_catalog()
        report = refresh_catalog.refresh(data_dir=self.root, offline=True, log=lambda _m: None)
        text = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("@", text)
        self.assertIsNone(re.search(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}", text))


if __name__ == "__main__":
    unittest.main(verbosity=2)
