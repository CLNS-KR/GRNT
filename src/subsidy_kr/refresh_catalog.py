"""마감 공고 자동 갱신 — `python -m subsidy_kr.refresh_catalog`.

하루 한 번(또는 원하는 주기로) 돌려 다음 세 가지를 한 번에 처리합니다.

1. **재수집** — 보조금24(15113968)·K-Startup(15125364)·기업마당(15157820) **그리고 지자체 자체
   복지포털**(부평복지ON·인천 맞춤형수혜·인천 1인가구·서울 WIS·경기민원24·세종·브라보)을
   `sync_gov24.sync_all`(include_local_portals)로 다시 받아 `catalog.json` 을 갱신합니다.
   네트워크·인증키·포털 개편으로 일부 소스가 실패해도 기존 카탈로그 행으로 메우므로
   **부분 실패를 허용**합니다.
2. **만료 인덱스 재생성** — 오늘 날짜 기준으로 `catalog.sqlite` 를 다시 만들어
   `is_expired`·`is_closed_biz` 플래그와 마감 인덱스가 현재 상태를 반영하게 합니다.
   `catalog.sqlite` 는 배포 이미지에서 처음 뜰 때 만들어지므로, 서버를 오래 켜 두면
   만료 플래그가 그 시점에 머뭅니다. 이 단계가 그 드리프트를 없앱니다.
3. **배포 산출물** — 내용이 실제로 바뀌었을 때만 `catalog.json.gz`(3.8MB, 유일한 커밋 대상)를
   다시 씁니다. 압축을 풀어 내용으로 비교하므로 gzip 헤더(mtime)만 다른 경우에는 커밋이 생기지 않습니다.

쓰는 법
-------
    DATA_GO_KR_SERVICE_KEY=... PYTHONPATH=src python -m subsidy_kr.refresh_catalog
    PYTHONPATH=src python -m subsidy_kr.refresh_catalog --offline --dry-run --json
    PYTHONPATH=src python -m subsidy_kr.refresh_catalog --data-dir /tmp/cat --offline

- `--offline`: 네트워크를 쓰지 않고 지금 있는 `catalog.json`·`catalog.json.gz` 로 인덱스만
  다시 만듭니다(만료 플래그 회전). CI 에 키 시크릿이 없을 때도 이 경로로 안전하게 끝납니다.
- `--dry-run`: 네트워크를 쓰지 않고 **현재 카탈로그 기준으로** 무엇이 바뀔지만 보고합니다
  (파일을 쓰지 않음).
- `--no-local`: 지자체 포털 수집을 빼고 공공데이터 API만 받습니다.
- 종료코드: 0 = 갱신 또는 인덱스 재생성 완료(부분 실패 포함), 1 = 쓸 카탈로그가 없음.

설계 요점
---------
- 모든 쓰기는 임시 파일 → `os.replace` 로 원자적입니다(서버가 읽는 중이어도 깨지지 않음).
- 카탈로그가 비면 **기존 파일을 지우지 않고** 실패로 끝납니다(`state: no_catalog`).
- CI 는 `.github/workflows/refresh-catalog.yml` 이 담당합니다(매일 19:00 UTC = 04:00 KST).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sqlite3
import sys
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import programs, snapshots, sync_gov24
from .catalog import normalize_service, read_catalog_payload, stats_from_rows
from .sqlite_store import build_sqlite_from_rows

CATALOG_FILE = "catalog.json"
GZIP_FILE = "catalog.json.gz"
INDEX_FILE = "catalog.sqlite"
ALL_SOURCES = ("gov24", "startup", "bizinfo")


def _log(message: str) -> None:
    print(message, flush=True)


def default_data_dir() -> str:
    return sync_gov24.default_data_dir()


def _paths(root: str) -> Dict[str, str]:
    return {"json": os.path.join(root, CATALOG_FILE),
            "gzip": os.path.join(root, GZIP_FILE),
            "index": os.path.join(root, INDEX_FILE)}


def read_payload(root: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """지금 있는 카탈로그(원본 우선, 없으면 압축본)를 읽는다. 없으면 ({}, None)."""
    for path in (os.path.join(root, CATALOG_FILE), os.path.join(root, GZIP_FILE)):
        if not os.path.exists(path):
            continue
        try:
            payload = read_catalog_payload(path)
        except (OSError, EOFError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("services"):
            return payload, path
    return {}, None


def _file_sha(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def index_counts(path: str) -> Dict[str, int]:
    """`catalog.sqlite` 의 플래그 분포(만료·모집마감·열린 개인/창업)."""
    if not os.path.exists(path):
        return {}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        def count(where: str = "", params: Tuple[Any, ...] = ()) -> int:
            sql = "SELECT COUNT(*) FROM services" + (f" WHERE {where}" if where else "")
            row = conn.execute(sql, params).fetchone()
            return int(row[0]) if row else 0

        personal, business = programs.TRACK_PERSONAL, programs.TRACK_BUSINESS
        return {
            "services": count(),
            "expired": count("is_expired = 1"),
            "closed_business": count("is_closed_biz = 1"),
            "open_total": count("is_expired = 0"),
            "open_personal": count("is_expired = 0 AND track = ?", (personal,)),
            "open_business": count("is_expired = 0 AND track = ?", (business,)),
        }
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def rebuild_index(root: str, payload: Dict[str, Any],
                  log: Callable[[str], None] = _log) -> Dict[str, Any]:
    """오늘 날짜 기준으로 `catalog.sqlite` 를 다시 만든다(원자적 교체)."""
    paths = _paths(root)
    rows = [row for row in (payload.get("services") or []) if isinstance(row, dict)]
    if not rows:
        raise ValueError("empty_catalog")
    meta = dict(payload.get("meta") or {})
    meta["catalog_state"] = "synced"
    meta.setdefault("data_state", "live_sync")
    meta["index_built_on"] = date.today().isoformat()
    build_sqlite_from_rows(rows, meta, paths["index"])
    log(f"인덱스 재생성: {paths['index']} ({len(rows):,}건)")
    return index_counts(paths["index"])


def write_gzip(root: str, payload: Dict[str, Any]) -> bool:
    """압축본의 **내용**이 다를 때만 다시 쓴다. 바뀌었으면 True.

    gzip 헤더의 mtime·압축 레벨은 내용이 같아도 바이트를 바꿉니다. 그대로 두면 매일
    커밋이 생기므로 압축을 풀어 내용으로만 비교합니다.
    """
    target = _paths(root)["gzip"]
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        with gzip.open(target, "rb") as handle:
            if handle.read() == raw:
                return False
    except (OSError, EOFError, ValueError):
        pass
    os.makedirs(root, exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(gzip.compress(raw, compresslevel=9, mtime=0))
    os.replace(tmp, target)
    return True


def _snapshot_note(payload: Dict[str, Any]) -> Dict[str, Any]:
    meta = payload.get("meta") or {}
    return {"generated_on": meta.get("generated_on"),
            "snapshot_day": meta.get("snapshot_day"),
            "catalog_state": meta.get("catalog_state"),
            "sources": meta.get("sources"),
            "warnings": meta.get("warnings") or []}


def refresh(service_key: Optional[str] = None, *, data_dir: Optional[str] = None,
            sources: Tuple[str, ...] = ALL_SOURCES, offline: bool = False,
            dry_run: bool = False, compress: bool = True, ttl_hours: float = 0.0,
            grace_days: int = 30, max_pages: Optional[int] = None,
            delay: float = 0.0, include_local_portals: bool = True,
            broso_max_pages: int = 8,
            log: Callable[[str], None] = _log) -> Dict[str, Any]:
    """재수집 → 만료 인덱스 재생성 → (바뀐 경우) 압축본 갱신. 결과 요약을 돌려준다."""
    root = data_dir or default_data_dir()
    paths = _paths(root)
    warnings: List[str] = []
    today = date.today().isoformat()

    # dry-run 은 "지금 있는 카탈로그로 무엇이 바뀔지"만 본다 — 네트워크·파일 쓰기를 모두 하지 않는다.
    if dry_run:
        offline = True

    before_json_sha = _file_sha(paths["json"])
    before_counts = index_counts(paths["index"])

    sync_report: Dict[str, Any] = {"ok": False, "state": "skipped",
                                   "message": "offline"}
    if not offline and not (service_key or sync_gov24._key_from_env()):
        offline = True
        warnings.append("인증키가 없어 재수집을 건너뜁니다 — 기존 카탈로그로 인덱스만 재생성합니다.")
        log("경고: DATA_GO_KR_SERVICE_KEY 가 없어 오프라인 모드로 진행합니다.")
    if not offline:
        try:
            sync_report = sync_gov24.sync_all(
                service_key, data_dir=root, ttl_hours=ttl_hours, sources=tuple(sources),
                force=ttl_hours <= 0, grace_days=grace_days, max_pages=max_pages,
                delay=delay, include_local_portals=include_local_portals,
                broso_max_pages=broso_max_pages, log=log)
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 기존 데이터로 진행한다
            sync_report = {"ok": False, "state": "failed", "error": type(exc).__name__}
        if not sync_report.get("ok"):
            reason = sync_report.get("error") or sync_report.get("message") or "unknown"
            warnings.append(f"재수집 실패({reason}) — 기존 카탈로그로 진행합니다.")
            log(f"경고: 재수집 실패({reason})")

    payload, source_path = read_payload(root)
    if not payload:
        return {
            "ok": False, "state": "no_catalog", "day": today, "dry_run": dry_run,
            "offline": offline, "data_dir": root, "warnings": warnings,
            "message": ("재수집에 실패했고 기존 catalog.json / catalog.json.gz 도 없습니다. "
                        "인증키·네트워크를 확인하거나 동기화를 먼저 한 번 실행하세요."),
            "sources": sync_report,
        }

    rows = payload.get("services") or []
    # meta.stats·meta.tracks 를 **행 배열과 다시 맞춘다**. 재수집이 실패해 기존 카탈로그로
    # 끝난 실행(CI 에 키가 없을 때의 --offline 포함)이 병합 뒤 건수와 어긋난 옛 값을
    # 압축본에 그대로 다시 쓰던 문제를 막는다(지자체 포털 병합 뒤 홈 12,429 vs llms 13,416).
    if rows:
        stats = stats_from_rows(rows)
        meta = dict(payload.get("meta") or {})
        meta["stats"] = stats
        meta["tracks"] = stats["by_track"]
        payload["meta"] = meta
    result: Dict[str, Any] = {
        "ok": True,
        "state": "refreshed" if sync_report.get("ok") else "index_only",
        "day": today,
        "dry_run": dry_run,
        "offline": offline,
        "data_dir": root,
        "catalog": {"source_file": os.path.basename(source_path or ""),
                    "services": len(rows), **_snapshot_note(payload)},
        "sources": sync_report,
        "warnings": warnings + [w for w in (payload.get("meta") or {}).get("warnings") or []
                                if w not in warnings],
    }

    after_counts: Dict[str, Any] = {}
    index_written = False
    try:
        if dry_run:
            after_counts = before_counts or {"services": len(rows)}
        else:
            after_counts = rebuild_index(root, payload, log=log)
            index_written = True
    except (OSError, ValueError, TypeError) as exc:
        warnings.append(f"만료 인덱스 재생성 실패({type(exc).__name__})")
        result["ok"] = False
        result["state"] = "index_failed"

    gzip_written = False
    if compress and not dry_run:
        gzip_written = write_gzip(root, payload)
        log(f"압축본: {'갱신' if gzip_written else '변경 없음'} ({paths['gzip']})")

    # 일자별 스냅샷 — 재수집이 성공했든(부분 실패 포함) 기존 카탈로그로 끝났든, 그날의
    # 카탈로그 상태를 한 장 남긴다. `compare_ledgers` 는 이 파일이 있어야 동작하고,
    # `snapshots/` 는 저장소·이미지에 함께 넣어 두므로(압축본) 배포 환경도 기준일을 갖는다.
    snapshot_written: Optional[str] = None
    if not dry_run:
        try:
            # sync_gov24 와 같은 규칙으로 정규화한다 — 서비스ID 중복은 마지막 행,
            # source 는 행이 스스로 밝힌 값(없으면 gov24). 그래야 전날 스냅샷과
            # 같은 제도를 같은 ID 로 비교한다(0.4.6 에서 기준일 스냅샷을 적재하며 확인).
            by_id: Dict[str, Any] = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                service_id = str(row.get("서비스ID") or "").strip()
                if service_id:
                    by_id[service_id] = row
            services = [normalize_service(row, source=str(row.get("source") or "gov24"))
                        for row in by_id.values()]
            snapshot_written = snapshots.write_snapshot(
                services, today, snapshots.snapshot_dir(root), compress=True,
                note_ko="카탈로그 갱신 시 적재한 일자별 스냅샷입니다.")
            log(f"스냅샷: {snapshot_written}")
        except (OSError, ValueError, TypeError) as exc:
            warnings.append(f"스냅샷 적재 실패({type(exc).__name__})")

    after_json_sha = _file_sha(paths["json"])
    expired_delta = (after_counts.get("expired", 0) - before_counts.get("expired", 0)
                     if before_counts.get("expired") is not None
                     and after_counts.get("expired") is not None else None)
    total_delta = (after_counts.get("services", 0) - before_counts.get("services", 0)
                   if before_counts.get("services") is not None else None)

    result["index"] = {"path": paths["index"] if index_written else None,
                       "rebuilt": index_written,
                       "built_on": today, **after_counts}
    result["changes"] = {
        "catalog_json_changed": (after_json_sha is not None
                                  and before_json_sha != after_json_sha),
        "gzip_changed": gzip_written,
        "index_rebuilt": index_written,
        "previous": before_counts or None,
        "expired_delta": expired_delta,
        "total_delta": total_delta,
    }
    result["files"] = ([paths["index"]] if index_written else []) + \
                      ([paths["gzip"]] if gzip_written else []) + \
                      ([snapshot_written] if snapshot_written else [])
    result["snapshot"] = {"path": snapshot_written, "day": today,
                          "available_days": len(snapshots.list_snapshots(
                              snapshots.snapshot_dir(root)))}
    return result


def _human_report(report: Dict[str, Any]) -> str:
    if not report.get("ok") and report.get("state") == "no_catalog":
        return f"실패: {report.get('message')}"
    index = report.get("index") or {}
    catalog = report.get("catalog") or {}
    changes = report.get("changes") or {}
    lines = [
        f"[{report.get('day')}] 카탈로그 갱신 — {report.get('state')}"
        + (" (dry-run)" if report.get("dry_run") else ""),
        f"  카탈로그: {catalog.get('services', 0):,}건 · 생성 {catalog.get('generated_on') or '-'}"
        f" · 파일 {catalog.get('source_file') or '-'}",
        (f"  만료 인덱스: 만료 {index.get('expired', 0):,} · 모집마감 "
         f"{index.get('closed_business', 0):,} · 열림 {index.get('open_total', 0):,}"
         f" (개인 {index.get('open_personal', 0):,} / 창업 {index.get('open_business', 0):,})"),
        f"  변경: 카탈로그 {'O' if changes.get('catalog_json_changed') else 'X'}"
        f" · 압축본 {'O' if changes.get('gzip_changed') else 'X'}"
        f" · 인덱스 {'O' if changes.get('index_rebuilt') else 'X'}"
        + (f" · 만료 증가 {changes['expired_delta']:+d}"
           if isinstance(changes.get("expired_delta"), int) else ""),
    ]
    for warning in report.get("warnings") or []:
        lines.append(f"  경고: {warning}")
    snapshot = report.get("snapshot") or {}
    if snapshot.get("path"):
        lines.append(f"  스냅샷: {snapshot.get('path')} (보관 {snapshot.get('available_days', 0)}일)")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m subsidy_kr.refresh_catalog",
        description=("지원금 카탈로그 자동 갱신 — 재수집(보조금24·K-Startup·기업마당) → "
                     "오늘 기준 만료 인덱스 재생성 → 바뀐 경우 catalog.json.gz 갱신"),
    )
    parser.add_argument("--key", default="", help="data.go.kr 인증키(없으면 DATA_GO_KR_SERVICE_KEY)")
    parser.add_argument("--data-dir", default="", help="카탈로그 디렉터리(기본 data/gov24)")
    parser.add_argument("--sources", default=",".join(ALL_SOURCES),
                        help="쉼표 구분 소스: gov24,startup,bizinfo,all")
    parser.add_argument("--offline", action="store_true",
                        help="네트워크 없이 기존 카탈로그로 인덱스만 재생성")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 결과만 확인")
    parser.add_argument("--no-compress", action="store_true", help="catalog.json.gz 갱신 생략")
    parser.add_argument("--no-local", action="store_true",
                        help="지자체 자체 복지포털 수집 생략(공공데이터 API만)")
    parser.add_argument("--ttl-days", type=float, default=0.0,
                        help="캐시 재사용 기간(일). 0=매번 새로 받기(기본)")
    parser.add_argument("--grace-days", type=int, default=30,
                        help="마감 후 이 기간이 지난 공고는 수집에서 제외")
    parser.add_argument("--max-pages", type=int, default=0, help="페이지 제한(시험용, 0=전량)")
    parser.add_argument("--delay", type=float, default=0.0, help="호출 간 대기(초)")
    parser.add_argument("--json", action="store_true", help="요약을 JSON 으로 출력")
    args = parser.parse_args(argv)

    raw_sources = [item.strip() for item in str(args.sources or "").split(",") if item.strip()]
    if not raw_sources or "all" in raw_sources:
        sources: Tuple[str, ...] = ALL_SOURCES
    else:
        unknown = [item for item in raw_sources if item not in ALL_SOURCES]
        if unknown:
            print(f"실패: 알 수 없는 소스 {','.join(unknown)} (사용: {', '.join(ALL_SOURCES)}, all)",
                  file=sys.stderr)
            return 2
        sources = tuple(raw_sources)

    report = refresh(
        args.key or None,
        data_dir=args.data_dir or None,
        sources=sources,
        offline=args.offline,
        dry_run=args.dry_run,
        compress=not args.no_compress,
        ttl_hours=max(0.0, float(args.ttl_days)) * 24,
        grace_days=max(0, int(args.grace_days)),
        max_pages=int(args.max_pages) or None,
        delay=max(0.0, float(args.delay)),
        include_local_portals=not args.no_local,
        log=(lambda message: None) if args.json else _log,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(_human_report(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
