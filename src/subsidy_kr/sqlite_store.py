"""SQLite 기반 카탈로그 저장소 — Render 무료 512MB RAM 환경 OOM 방지용.

전체 `catalog.json.gz`(1.3만+ 건)를 메모리에 상주시키지 않고,
지역·트랙·마감 여부 인덱스를 탄 SQL `SELECT`로 필요한 후보만 읽어 `Service`로 변환한다.
기존 `Catalog` 클래스와 동일한 조회 메서드(`get`, `by_region`, `by_track`, `search`, `stats`)를 제공한다.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from . import programs, regions, synonyms
from .catalog import BROWSE_CACHE_MAX, Catalog, Service, normalize_service, search_text

# 색인 스키마 버전 — json·지역 택소노미와 따로 본다. 계산해 둔 열(종류·마감일)이 없는
# 예전 DB 를 그대로 쓰면 경량 조회가 빈 결과를 내므로, 다르면 `load_catalog` 이 다시 만든다.
INDEX_SCHEMA = 2

# 프로필 없는 둘러보기의 정렬 — `catalog.browse_sort_key` 와 같은 순서(종류·지역·마감).
# `?` 두 개는 기준일(YYYY-MM-DD)이다(마감 임박도는 오늘 기준이라 저장하지 않고 계산한다).
_BROWSE_ORDER = (
    "CASE region_level WHEN 'sigungu' THEN 0 WHEN 'sido' THEN 1 ELSE 2 END, "
    "CASE WHEN deadline_end <> '' "
    "     AND julianday(deadline_end) - julianday(?) BETWEEN 0 AND 7 THEN 0 "
    "     WHEN deadline_end <> '' "
    "     AND julianday(deadline_end) - julianday(?) BETWEEN 0 AND 30 THEN 1 "
    "     ELSE 2 END, "
    "CASE WHEN deadline_end = '' THEN '9999-12-31' ELSE deadline_end END, idx"
)


def build_sqlite_from_rows(
    rows: List[Dict[str, Any]],
    meta: Dict[str, Any],
    db_path: str,
) -> None:
    """정규화 전 raw service dict 목록을 SQLite DB 파일로 저장한다."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    tmp_path = db_path + ".tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    conn = sqlite3.connect(tmp_path)
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute(
            """
            CREATE TABLE services (
                idx INTEGER PRIMARY KEY,
                service_id TEXT UNIQUE NOT NULL,
                track TEXT NOT NULL,
                region_level TEXT NOT NULL,
                sido TEXT NOT NULL,
                sigungu TEXT NOT NULL,
                is_expired INTEGER NOT NULL,
                is_closed_biz INTEGER NOT NULL,
                has_conditions INTEGER NOT NULL,
                has_criteria INTEGER NOT NULL,
                recruiting TEXT NOT NULL,
                agency TEXT NOT NULL,
                source TEXT NOT NULL,
                name TEXT NOT NULL,
                search_text TEXT NOT NULL,
                benefit_kind TEXT NOT NULL,
                deadline_end TEXT NOT NULL,
                row_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)"
        )

        insert_rows: List[Tuple[Any, ...]] = []
        closed_biz_count = 0
        expired_count = 0
        for idx, raw in enumerate(rows):
            svc = normalize_service(raw, source="gov24")
            is_exp = 1 if svc.is_expired else 0
            is_closed_biz = (
                1 if (svc.is_business and svc.business.get("recruiting") == "closed") else 0
            )
            if is_exp:
                expired_count += 1
            if is_closed_biz:
                closed_biz_count += 1
            reg = svc.region or {}
            recruiting = str((svc.business or {}).get("recruiting") or "")
            body = search_text(svc)
            # 종류·마감일은 프로필과 무관하게 정해지므로 색인할 때 한 번만 계산해 둔다.
            # 이 두 열이 경량 조회(둘러보기·마감 캘린더)를 SQL 만으로 처리하게 해 준다.
            benefit_kind = "program" if svc.benefit_kind == "program" else "grant"
            deadline_end = str((svc.deadline or {}).get("end_date") or "")
            insert_rows.append(
                (
                    idx,
                    svc.service_id,
                    svc.track,
                    reg.get("level") or "national",
                    reg.get("sido") or "",
                    reg.get("sigungu") or "",
                    is_exp,
                    is_closed_biz,
                    1 if svc.conditions else 0,
                    1 if svc.has_criteria else 0,
                    recruiting,
                    svc.agency or "",
                    svc.source or "gov24",
                    svc.name or "",
                    body,
                    benefit_kind,
                    deadline_end,
                    json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
                )
            )

        conn.executemany(
            """
            INSERT INTO services (
                idx, service_id, track, region_level, sido, sigungu,
                is_expired, is_closed_biz, has_conditions, has_criteria,
                recruiting, agency, source, name, search_text,
                benefit_kind, deadline_end, row_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_rows,
        )
        conn.execute(
            "CREATE INDEX idx_services_filter ON services (track, region_level, sido, sigungu, is_expired)"
        )
        conn.execute("CREATE INDEX idx_services_region ON services (region_level, sido, sigungu)")
        conn.execute("CREATE INDEX idx_services_deadline ON services (deadline_end)")

        meta_to_save = dict(meta)
        meta_to_save["_closed_business_count"] = closed_biz_count
        meta_to_save["_expired_count"] = expired_count
        # 지역 택소노미 버전 — 개편으로 sido·sigungu 열이 낡으면 load_catalog 가 다시 만든다.
        meta_to_save["region_schema"] = regions.SCHEMA_VERSION
        # 색인 스키마 버전 — 이 열(benefit_kind·deadline_end)이 없으면 다시 만든다.
        meta_to_save["index_schema"] = INDEX_SCHEMA
        for k, v in meta_to_save.items():
            conn.execute(
                "INSERT INTO meta (key, value_json) VALUES (?, ?)",
                (str(k), json.dumps(v, ensure_ascii=False)),
            )
        conn.commit()
    finally:
        conn.close()

    os.replace(tmp_path, db_path)


class SQLiteCatalog:
    """SQLite 파일에서 필요한 제도만 온디맨드로 읽어 `Service` 객체로 제공하는 카탈로그."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.memo: Dict[str, Any] = {}
        self._stats: Optional[Dict[str, Any]] = None
        self.meta: Dict[str, Any] = {}

        conn = self._connect()
        try:
            for k, v_json in conn.execute("SELECT key, value_json FROM meta"):
                self.meta[k] = json.loads(v_json)
            self.closed_business_count = int(self.meta.pop("_closed_business_count", 0))
            self.expired_count = int(self.meta.pop("_expired_count", 0))
            row = conn.execute("SELECT COUNT(*) FROM services").fetchone()
            self._total = int(row[0]) if row else 0
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False)

    @staticmethod
    def _row_to_service(row_json: str) -> Service:
        return normalize_service(json.loads(row_json), source="gov24")

    def __len__(self) -> int:
        return self._total

    @property
    def services(self) -> List[Service]:
        """전체 목록이 꼭 필요한 호출자(pSEO 등)를 위한 지연 로드."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT row_json FROM services ORDER BY idx").fetchall()
            return [self._row_to_service(r[0]) for r in rows]
        finally:
            conn.close()

    def get(self, service_id: str) -> Optional[Service]:
        sid = str(service_id or "").strip()
        if not sid:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT row_json FROM services WHERE service_id = ?", (sid,)
            ).fetchone()
            return self._row_to_service(row[0]) if row else None
        finally:
            conn.close()

    def get_many(self, service_ids: Any) -> List[Service]:
        """여러 건을 요청 순서대로 — 목록 페이지가 필요한 만큼만 읽는다."""
        ids = [str(sid or "").strip() for sid in service_ids]
        ids = [sid for sid in ids if sid]
        if not ids:
            return []
        conn = self._connect()
        try:
            marks = ",".join("?" for _ in ids)
            rows = conn.execute(
                f"SELECT service_id, row_json FROM services WHERE service_id IN ({marks})",
                ids,
            ).fetchall()
        finally:
            conn.close()
        found = {sid: self._row_to_service(row_json) for sid, row_json in rows}
        return [found[sid] for sid in ids if sid in found]

    def iter_services(self) -> Any:
        """전체를 한 건씩 스트림 — 1.2만 건을 한 번에 메모리에 올리지 않는다."""
        conn = self._connect()
        try:
            for (row_json,) in conn.execute("SELECT row_json FROM services ORDER BY idx"):
                yield self._row_to_service(row_json)
        finally:
            conn.close()

    def all(self) -> List[Service]:
        return self.services

    def by_track(self, track: Optional[str] = None) -> List[Service]:
        if track in (None, "", "all"):
            return self.services
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT row_json FROM services WHERE track = ? ORDER BY idx", (track,)
            ).fetchall()
            return [self._row_to_service(r[0]) for r in rows]
        finally:
            conn.close()

    def track_services(self, track: str) -> List[Service]:
        return self.by_track(track)

    def by_region(
        self,
        sido: Optional[str] = None,
        sigungu: Optional[str] = None,
        *,
        include_national: bool = True,
    ) -> List[Service]:
        province = regions.canonical_sido(sido)
        district = regions.canonical_sigungu(province, sigungu) if province else None
        clauses: List[str] = []
        params: List[Any] = []
        if include_national:
            clauses.append("region_level = 'national'")
        if province:
            if district:
                clauses.append(
                    "(sido = ? AND (region_level = 'sido' OR (region_level = 'sigungu' AND sigungu = ?)))"
                )
                params.extend([province, district])
            else:
                clauses.append("(sido = ? AND region_level IN ('sido', 'sigungu'))")
                params.append(province)
        if not clauses:
            return []
        where = " OR ".join(clauses)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT row_json FROM services WHERE {where} ORDER BY idx", params
            ).fetchall()
            return [self._row_to_service(r[0]) for r in rows]
        finally:
            conn.close()

    def query_pool(
        self,
        *,
        sido: Optional[str] = None,
        sigungu: Optional[str] = None,
        track: str = "all",
        business_declared: bool = False,
        include_closed: bool = False,
        tag: Optional[str] = None,
        keyword: Optional[str] = None,
        keyword_expand: bool = False,
        max_scan: int = 20000,
    ) -> List[Service]:
        """트랙·지역·마감·키워드 필터를 SQL 레벨에서 1차로 좁혀 필요한 행만 로드한다."""
        conds: List[str] = []
        params: List[Any] = []

        if track == programs.TRACK_BUSINESS:
            conds.append("track = ?")
            params.append(programs.TRACK_BUSINESS)
        elif track == programs.TRACK_PERSONAL or not business_declared:
            conds.append("track = ?")
            params.append(programs.TRACK_PERSONAL)

        if not include_closed:
            conds.append("is_expired = 0")

        province = regions.canonical_sido(sido)
        district = regions.canonical_sigungu(province, sigungu) if province else None
        if province:
            if district:
                conds.append(
                    "(region_level = 'national' OR (sido = ? AND (region_level = 'sido' OR (region_level = 'sigungu' AND sigungu = ?))))"
                )
                params.extend([province, district])
            else:
                conds.append(
                    "(region_level = 'national' OR (sido = ? AND region_level IN ('sido', 'sigungu')))"
                )
                params.append(province)

        keyword_groups: List[List[tuple]] = []
        if keyword:
            if keyword_expand:
                keyword_groups = synonyms.plan(keyword)
            else:
                keyword_groups = [[(term, 1.0)] for term in
                                  synonyms.sql_like_terms(keyword, literal_only=True)]
            # 단어 사이는 AND, 한 단어의 표기들은 OR — 예전 동작(단어별 LIKE AND)과 같다.
            for group in keyword_groups:
                marks = " OR ".join("search_text LIKE ?" for _ in group)
                conds.append(f"({marks})")
                params.extend(f"%{term}%" for term, _weight in group)

        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        sql = f"SELECT row_json FROM services {where} ORDER BY idx LIMIT ?"
        params.append(int(max_scan))

        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

        out: List[Service] = []
        for (row_json,) in rows:
            svc = self._row_to_service(row_json)
            if not include_closed and svc.is_expired:
                continue
            if tag and tag not in svc.tags:
                continue
            if keyword_groups and keyword_expand and not synonyms.matches(search_text(svc), keyword_groups):
                continue
            out.append(svc)
        return out

    def search(
        self,
        keyword: str,
        limit: int = 20,
        *,
        region: Optional[Dict[str, str]] = None,
        expand: bool = True,
    ) -> List[Service]:
        """키워드 검색 — 단어별 동의어까지 함께 본다(직접 일치가 항상 위)."""
        groups = (synonyms.plan(keyword) if expand
                  else [[(word, 1.0)]
                        for word in synonyms.sql_like_terms(keyword, literal_only=True)])
        if not groups:
            return []
        like_terms = [term for group in groups for term, _weight in group]
        if not like_terms:
            return []
        where = " OR ".join("search_text LIKE ?" for _ in like_terms)
        params: List[Any] = [f"%{term}%" for term in like_terms]
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT row_json FROM services WHERE {where} ORDER BY idx",
                params,
            ).fetchall()
        finally:
            conn.close()

        hits: List[Tuple[int, Service]] = []
        for (row_json,) in rows:
            svc = self._row_to_service(row_json)
            haystack = search_text(svc)
            score = synonyms.score(svc.name, haystack, groups)
            if not score:
                continue
            if region and region.get("level") in ("sido", "sigungu"):
                match = regions.match_region(region, svc.region)
                if match["state"] == "mismatch":
                    continue
            hits.append((score, svc))
        hits.sort(key=lambda pair: (-pair[0], pair[1].name))
        return [svc for _score, svc in hits[: max(1, limit)]]

    # --- 경량 조회 (프로필 없는 검색 · 마감 캘린더) --------------------------
    def _scope_sql(self, *, track: str = "all", business_declared: bool = False,
                   include_closed: bool = False, sido: Optional[str] = None,
                   sigungu: Optional[str] = None) -> Tuple[List[str], List[Any]]:
        """`query_pool` 과 같은 트랙·마감·지역 조건을 SQL 조각으로 만든다."""
        conds: List[str] = []
        params: List[Any] = []
        if track == programs.TRACK_BUSINESS:
            conds.append("track = ?")
            params.append(programs.TRACK_BUSINESS)
        elif track == programs.TRACK_PERSONAL or not business_declared:
            conds.append("track = ?")
            params.append(programs.TRACK_PERSONAL)
        if not include_closed:
            conds.append("is_expired = 0")
        province = regions.canonical_sido(sido)
        district = regions.canonical_sigungu(province, sigungu) if province else None
        if province:
            if district:
                conds.append(
                    "(region_level = 'national' OR (sido = ? AND (region_level = 'sido' "
                    "OR (region_level = 'sigungu' AND sigungu = ?))))"
                )
                params.extend([province, district])
            else:
                conds.append(
                    "(region_level = 'national' OR (sido = ? AND region_level IN ('sido', 'sigungu')))"
                )
                params.append(province)
        return conds, params

    @staticmethod
    def _where(conds: List[str]) -> str:
        return (" WHERE " + " AND ".join(conds)) if conds else ""

    def browse_pool(self, *, sido: Optional[str] = None, sigungu: Optional[str] = None,
                    track: str = "all", business_declared: bool = False,
                    include_closed: bool = False, max_scan: int = 20000,
                    per_kind: int = 20, today: Optional[date] = None) -> Dict[str, Any]:
        """프로필 없이 둘러보는 검색 — 건수와 종류별 상위 목록만 SQL 로 가져온다.

        조건이 없는 검색은 후보가 전부 같은 판정('확인 필요 — 정보 부족')이다. 그래서
        1.3만 건을 Service 객체로 읽어 판정하지 않고, 건수는 COUNT 로, 보여 줄 줄은
        정렬 상위 몇 건만 읽는다(라이브 `GET /s/`·기본 검색의 28초 지연·OOM 원인 제거).
        """
        conds, params = self._scope_sql(track=track, business_declared=business_declared,
                                        include_closed=include_closed, sido=sido,
                                        sigungu=sigungu)
        limit = max(0, int(max_scan))
        per = max(1, int(per_kind))
        ref = (today or date.today()).isoformat()
        key = (sido or "", sigungu or "", str(track), bool(business_declared),
               bool(include_closed), limit, per, ref)
        cache = self.memo.get("browse_pools")
        if cache is None:
            cache = {}
            self.memo["browse_pools"] = cache
        cached = cache.get(key)
        if cached is not None:
            return cached
        by_kind: Dict[str, int] = {"grant": 0, "program": 0}
        top: Dict[str, List[Service]] = {"grant": [], "program": []}
        count_sql = (
            "SELECT benefit_kind, COUNT(*) FROM (SELECT benefit_kind FROM services"
            + self._where(conds)
            + " ORDER BY idx LIMIT ?) GROUP BY benefit_kind"
        )
        conn = self._connect()
        try:
            for kind, count in conn.execute(count_sql, [*params, limit]):
                by_kind[str(kind)] = int(count)
            per_kind_conds = conds + ["benefit_kind = ?"]
            rows_sql = (
                "SELECT row_json FROM services" + self._where(per_kind_conds)
                + " ORDER BY " + _BROWSE_ORDER + " LIMIT ?"
            )
            for kind in ("grant", "program"):
                rows = conn.execute(rows_sql, [*params, kind, ref, ref, per]).fetchall()
                top[kind] = [self._row_to_service(row[0]) for row in rows]
        finally:
            conn.close()
        payload = {"total": sum(by_kind.values()), "by_kind": by_kind, "services": top}
        while len(cache) >= BROWSE_CACHE_MAX:
            cache.pop(next(iter(cache)))
        cache[key] = payload
        return payload

    def deadline_between(self, *, start: date, until: date, track: str = "all",
                         business_declared: bool = False, sido: Optional[str] = None,
                         sigungu: Optional[str] = None,
                         keyword: Optional[str] = None) -> Dict[str, Any]:
        """마감일이 `start`~`until` 사이인 제도만 — 마감 캘린더가 필요한 줄만 읽는다."""
        # 캘린더의 `track="all"` 은 '두 트랙 모두'다(개인 트랙 기본값과 다르다).
        conds, params = self._scope_sql(track=track, business_declared=True,
                                        include_closed=True, sido=sido, sigungu=sigungu)
        word = str(keyword or "").strip()
        if word:
            # 파이썬의 `keyword in svc.name` 과 같은 부분 일치(대소문자 구분, %·_ 해석 없음).
            conds.append("instr(name, ?) > 0")
            params.append(word)
        start_iso, until_iso = start.isoformat(), until.isoformat()
        conn = self._connect()
        try:
            counts = conn.execute(
                "SELECT COUNT(*), "
                "COALESCE(SUM(deadline_end = ''), 0), "
                "COALESCE(SUM(deadline_end <> '' AND deadline_end < ?), 0) FROM services"
                + self._where(conds),
                [start_iso, *params],
            ).fetchone()
            rows = conn.execute(
                "SELECT row_json FROM services"
                + self._where(conds + ["deadline_end >= ?", "deadline_end <= ?"])
                + " ORDER BY deadline_end, idx",
                [*params, start_iso, until_iso],
            ).fetchall()
        finally:
            conn.close()
        return {
            "services": [self._row_to_service(row[0]) for row in rows],
            "total": int((counts or [0, 0, 0])[0] or 0),
            "unscheduled": int((counts or [0, 0, 0])[1] or 0),
            "expired": int((counts or [0, 0, 0])[2] or 0),
        }

    def stats(self) -> Dict[str, Any]:
        if self._stats is not None:
            return self._stats
        conn = self._connect()
        try:
            total = self._total
            with_conditions = conn.execute(
                "SELECT COUNT(*) FROM services WHERE has_conditions = 1"
            ).fetchone()[0]
            local_cnt = conn.execute(
                "SELECT COUNT(*) FROM services WHERE region_level != 'national'"
            ).fetchone()[0]
            local_missing = conn.execute(
                "SELECT COUNT(*) FROM services WHERE region_level != 'national' AND has_criteria = 0"
            ).fetchone()[0]
            biz_cnt = conn.execute(
                "SELECT COUNT(*) FROM services WHERE track = ?",
                (programs.TRACK_BUSINESS,),
            ).fetchone()[0]
            recruiting = conn.execute(
                "SELECT COUNT(*) FROM services WHERE track = ? AND recruiting = 'open'",
                (programs.TRACK_BUSINESS,),
            ).fetchone()[0]
            agencies = conn.execute(
                "SELECT COUNT(DISTINCT agency) FROM services WHERE agency != ''"
            ).fetchone()[0]
            sido_covered = conn.execute(
                "SELECT COUNT(DISTINCT sido) FROM services WHERE sido != '' AND region_level IN ('sido', 'sigungu')"
            ).fetchone()[0]
            by_source = {
                src: cnt
                for src, cnt in conn.execute(
                    "SELECT source, COUNT(*) FROM services GROUP BY source"
                ).fetchall()
            }
        finally:
            conn.close()

        self._stats = {
            "services": total,
            "with_conditions": with_conditions,
            "without_conditions": total - with_conditions,
            "local_services": local_cnt,
            "local_missing_criteria": local_missing,
            "local_missing_criteria_note_ko": (
                "지자체 제도 중 선정기준이 비어 있는 건수입니다. 실데이터에서 이 비율이 높을수록 "
                "'확인 필요' 판정이 늘어납니다."
            ),
            "agencies": agencies,
            "sido_covered": sido_covered,
            "personal": total - biz_cnt,
            "business": biz_cnt,
            "business_recruiting_now": recruiting,
            "by_track": {
                programs.TRACK_PERSONAL: total - biz_cnt,
                programs.TRACK_BUSINESS: biz_cnt,
            },
            "by_source": by_source,
        }
        return self._stats
