"""일자별 카탈로그 스냅샷 — 변경 이력 추적.

왜 필요한가
-----------
지원사업 공고는 **기간·예산·자격이 조용히 바뀝니다**. 오늘의 카탈로그만 덮어쓰면
"무엇이 바뀌었는지"를 잃습니다. 그래서 동기화할 때마다 `snapshots/{YYYY-MM-DD}.json`
한 장을 남기고, `snapshots/index.json` 에 그날의 요약과 직전 스냅샷 대비 변화 건수를 적습니다.

무엇을 저장하나
---------------
- 카탈로그 전체가 아니라 **비교에 필요한 필드만**(이름·기관·분야·마감일·금액·대상·모집상태·지문).
- `fingerprint` 는 위 필드를 정규화해 만든 해시입니다. 본문 전체를 비교하지 않으므로
  스냅샷 파일이 작고, "바뀌었다/안 바뀌었다"가 한눈에 나옵니다.

개인정보
--------
여기에는 제도 정보만 들어갑니다. 사용자 프로필·질의문·IP 는 어떤 스냅샷에도 남지 않습니다.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from .cache import now_iso
from .catalog import data_dir_from_env

SNAPSHOT_DIRNAME = "snapshots"
INDEX_FILE = "index.json"
SNAPSHOT_SUFFIX = ".json"
GZIP_SUFFIX = ".json.gz"
DIFF_FIELDS: List[str] = ["name", "agency", "field", "deadline_end", "deadline_text",
                          "amount", "target", "recruiting", "track"]


def snapshot_dir(data_dir: Optional[str] = None) -> str:
    base = data_dir or data_dir_from_env()
    return os.path.join(base, SNAPSHOT_DIRNAME)


def today_kst() -> str:
    return date.today().isoformat()


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _entry(service: Any) -> Dict[str, Any]:
    deadline = service.deadline or {}
    business = service.business or {}
    return {
        "name": _clip(service.name, 160),
        "agency": _clip(service.agency, 80),
        "track": service.track,
        "source": service.source,
        "field": service.field,
        "deadline_end": deadline.get("end_date") or "",
        "deadline_text": _clip(service.deadline_text, 120),
        "amount": _clip(service.content, 160),
        "target": _clip(service.target, 160),
        "recruiting": business.get("recruiting") or "",
        "fingerprint": service.fingerprint,
    }


def build_snapshot(services: Iterable[Any], day: Optional[str] = None,
                   *, note_ko: str = "") -> Dict[str, Any]:
    """`Service` 목록 → 스냅샷 페이로드."""
    entries: Dict[str, Dict[str, Any]] = {}
    by_track: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    for service in services:
        if not service.service_id:
            continue
        entries[service.service_id] = _entry(service)
        by_track[service.track] = by_track.get(service.track, 0) + 1
        by_source[service.source] = by_source.get(service.source, 0) + 1
    return {
        "meta": {
            "day": day or today_kst(),
            "generated_on": now_iso(),
            "services": len(entries),
            "by_track": by_track,
            "by_source": by_source,
            "note_ko": note_ko or (
                "비교용 필드만 담은 일자별 카탈로그 스냅샷입니다. 이름·마감·금액·대상·모집상태가 "
                "같으면 같은 제도로 봅니다."
            ),
        },
        "services": entries,
    }


def save_snapshot(payload: Dict[str, Any], directory: Optional[str] = None,
                  *, compress: bool = False) -> str:
    """스냅샷 1장을 원자적으로 쓴다.

    `compress=True` 면 `{날짜}.json.gz` 로 씁니다(저장소·이미지에 넣는 기준일 스냅샷용 —
    12,000건 기준 9MB → 2MB). 읽는 쪽은 두 형식을 모두 받습니다(`load_snapshot`).
    같은 날짜의 다른 형식 파일은 지워 하루가 두 장으로 세어지지 않게 합니다.
    """
    root = directory or snapshot_dir()
    os.makedirs(root, exist_ok=True)
    day = str(payload.get("meta", {}).get("day") or today_kst())
    suffix = GZIP_SUFFIX if compress else SNAPSHOT_SUFFIX
    target = os.path.join(root, f"{day}{suffix}")
    tmp = target + ".tmp"
    raw = json.dumps(payload, ensure_ascii=False)
    if compress:
        with open(tmp, "wb") as handle:
            handle.write(gzip.compress(raw.encode("utf-8"), compresslevel=9, mtime=0))
    else:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(raw)
    os.replace(tmp, target)
    other = os.path.join(root, f"{day}" + (SNAPSHOT_SUFFIX if compress else GZIP_SUFFIX))
    try:
        if os.path.exists(other):
            os.remove(other)
    except OSError:
        pass
    _update_index(root, day, payload)
    return target


def write_snapshot(services: Iterable[Any], day: Optional[str] = None,
                   directory: Optional[str] = None, *, compress: bool = False,
                   note_ko: str = "") -> str:
    """`Service` 목록 → 스냅샷 페이로드 → 저장까지 한 번에.

    `refresh_catalog`·기동 시 기준일 적재가 쓰는 진입점입니다. 반환값은 저장 경로입니다.
    """
    payload = build_snapshot(services, day, note_ko=note_ko)
    return save_snapshot(payload, directory, compress=compress)


def _path_for(day: str, root: str) -> Optional[str]:
    """그 날짜의 스냅샷 파일 경로(원본 우선, 없으면 압축본)."""
    for suffix in (SNAPSHOT_SUFFIX, GZIP_SUFFIX):
        path = os.path.join(root, f"{day}{suffix}")
        if os.path.exists(path):
            return path
    return None


def load_snapshot(day: str, directory: Optional[str] = None) -> Optional[Dict[str, Any]]:
    root = directory or snapshot_dir()
    target = _path_for(str(day), root)
    if not target:
        return None
    try:
        if target.endswith(GZIP_SUFFIX):
            with gzip.open(target, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        else:
            with open(target, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
    except (OSError, EOFError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def days_on_disk(directory: Optional[str] = None) -> List[str]:
    """디렉터리에 실제로 있는 스냅샷 날짜(색인과 무관)."""
    root = directory or snapshot_dir()
    try:
        names = os.listdir(root)
    except OSError:
        return []
    days = set()
    for name in names:
        if name.startswith(INDEX_FILE):
            continue
        if name.endswith(GZIP_SUFFIX):
            days.add(name[: -len(GZIP_SUFFIX)])
        elif name.endswith(SNAPSHOT_SUFFIX) and not name.endswith(".tmp"):
            days.add(name[: -len(SNAPSHOT_SUFFIX)])
    return sorted(day for day in days if day)


def list_snapshots(directory: Optional[str] = None) -> List[Dict[str, Any]]:
    root = directory or snapshot_dir()
    index = _read_index(root)
    rows: Dict[str, Dict[str, Any]] = {}
    for row in index.get("days") or []:
        if isinstance(row, dict) and row.get("day"):
            rows[str(row["day"])] = row
    # 색인에 없는 날짜(저장소에 함께 커밋한 압축 스냅샷 등)는 파일 메타로 채운다.
    for day in days_on_disk(root):
        if day in rows:
            continue
        payload = load_snapshot(day, root)
        if payload:
            rows[day] = dict(payload.get("meta") or {})
            rows[day].setdefault("day", day)
    return sorted(rows.values(), key=lambda row: str(row.get("day") or ""))


def latest_day(directory: Optional[str] = None) -> Optional[str]:
    days = [str(row.get("day")) for row in list_snapshots(directory) if row.get("day")]
    return days[-1] if days else None


def _read_index(root: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(root, INDEX_FILE), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"days": []}
    return payload if isinstance(payload, dict) else {"days": []}


def _update_index(root: str, day: str, payload: Dict[str, Any]) -> None:
    index = _read_index(root)
    days = [row for row in (index.get("days") or [])
            if isinstance(row, dict) and str(row.get("day")) != day]
    previous = max((str(row.get("day")) for row in days), default=None)
    meta = dict(payload.get("meta") or {})
    entry = {
        "day": day,
        "generated_on": meta.get("generated_on"),
        "services": meta.get("services", 0),
        "by_track": meta.get("by_track", {}),
        "by_source": meta.get("by_source", {}),
    }
    if previous:
        before = load_snapshot(previous, root)
        if before:
            diff = diff_snapshots(before, payload)
            entry.update({"compared_to": previous, "added": len(diff["added"]),
                          "removed": len(diff["removed"]),
                          "changed": len(diff["changed"])})
    days.append(entry)
    days.sort(key=lambda row: str(row.get("day") or ""))
    tmp = os.path.join(root, INDEX_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"days": days}, handle, ensure_ascii=False)
    os.replace(tmp, os.path.join(root, INDEX_FILE))


def diff_snapshots(before: Dict[str, Any], after: Dict[str, Any],
                   *, limit: Optional[int] = None) -> Dict[str, Any]:
    """두 스냅샷의 추가·삭제·변경을 계산한다."""
    old = before.get("services") or {}
    new = after.get("services") or {}
    added: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    changed: List[Dict[str, Any]] = []
    for service_id, entry in new.items():
        if service_id not in old:
            added.append({"service_id": service_id, **{k: entry.get(k) for k in
                                                       ("name", "agency", "track", "deadline_end")}})
            continue
        previous = old[service_id]
        if previous.get("fingerprint") == entry.get("fingerprint"):
            continue
        fields: Dict[str, Dict[str, Any]] = {}
        for key in DIFF_FIELDS:
            if previous.get(key) != entry.get(key):
                fields[key] = {"from": previous.get(key), "to": entry.get(key)}
        if not fields:
            fields = {"content": {
                "from": "",
                "to": "본문 문구가 바뀌었습니다(스냅샷은 요약 필드만 저장 — 원문은 카탈로그에서 확인)",
            }}
        changed.append({"service_id": service_id, "name": entry.get("name"),
                        "agency": entry.get("agency"), "track": entry.get("track"),
                        "changes": fields})
    for service_id, entry in old.items():
        if service_id not in new:
            removed.append({"service_id": service_id,
                            **{k: entry.get(k) for k in ("name", "agency", "track",
                                                          "deadline_end")}})
    added.sort(key=lambda row: (str(row.get("track")), str(row.get("name"))))
    removed.sort(key=lambda row: (str(row.get("track")), str(row.get("name"))))
    changed.sort(key=lambda row: (str(row.get("track")), str(row.get("name"))))
    if limit is not None and limit > 0:
        added, removed, changed = added[:limit], removed[:limit], changed[:limit]
    return {
        "from_day": (before.get("meta") or {}).get("day"),
        "to_day": (after.get("meta") or {}).get("day"),
        "added": added,
        "removed": removed,
        "changed": changed,
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
    }


def compare_days(day_a: Optional[str], day_b: Optional[str],
                 directory: Optional[str] = None, *, limit: Optional[int] = None,
                 service_id: Optional[str] = None) -> Dict[str, Any]:
    """스냅샷 두 장을 비교한다(없으면 사유를 그대로 돌려준다).

    기준일이 **한 장뿐**이면 오류가 아니라 `state: "baseline_only"` 로 답합니다 —
    프로덕션처럼 아직 하루치만 적재된 상태에서 빈 응답(`snapshot_missing`)을 내지 않고,
    "기준일 1장은 있고 전일 대비 비교는 다음 적재부터"라고 밝히기 위해서입니다.
    """
    root = directory or snapshot_dir()
    days = [str(row.get("day")) for row in list_snapshots(root) if row.get("day")]
    latest = day_b or (days[-1] if days else None)
    earlier = day_a
    if not earlier:
        earlier = days[-2] if len(days) >= 2 else None
    if latest and not earlier:
        return {"ok": True, "state": "baseline_only", "from_day": None, "to_day": latest,
                "added": [], "removed": [], "changed": [],
                "counts": {"added": 0, "removed": 0, "changed": 0},
                "available_days": days, "snapshot_dir": root,
                "message_ko": (f"비교 기준일이 {latest} 1장뿐입니다. 기준일은 정상적으로 적재됐고, "
                               "전일 대비 변화 비교는 다음 적재(매일 04:00 KST 갱신)부터 제공됩니다. "
                               "지금은 `get_service_meta` 의 카탈로그 통계로 현재 상태를 확인하세요.")}
    if not latest or not earlier:
        return {"ok": False, "error": "snapshot_missing",
                "available_days": days,
                "message_ko": ("비교할 스냅샷이 아직 없습니다. "
                               "`python -m subsidy_kr.refresh_catalog`(또는 `sync_gov24 --sources all`)을 "
                               "실행하면 `snapshots/{날짜}.json` 이 적재되고, 다음 날부터 전일 대비 "
                               "비교를 제공합니다.")}
    payload_a = load_snapshot(earlier, root)
    payload_b = load_snapshot(latest, root)
    if not payload_a or not payload_b:
        return {"ok": False, "error": "snapshot_missing", "available_days": days,
                "message_ko": f"{earlier} 또는 {latest} 스냅샷 파일을 읽지 못했습니다."}
    diff = diff_snapshots(payload_a, payload_b, limit=limit)
    if service_id:
        diff["added"] = [row for row in diff["added"] if row["service_id"] == service_id]
        diff["removed"] = [row for row in diff["removed"] if row["service_id"] == service_id]
        diff["changed"] = [row for row in diff["changed"] if row["service_id"] == service_id]
        diff["counts"] = {"added": len(diff["added"]), "removed": len(diff["removed"]),
                          "changed": len(diff["changed"])}
    diff.update({"ok": True, "snapshot_dir": root, "available_days": days,
                 "services": {"from": len(payload_a.get("services") or {}),
                              "to": len(payload_b.get("services") or {})}})
    return diff


def history(service_id: str, directory: Optional[str] = None) -> List[Dict[str, Any]]:
    """한 제도의 날짜별 상태(있으면)."""
    out: List[Dict[str, Any]] = []
    root = directory or snapshot_dir()
    for row in list_snapshots(root):
        day = str(row.get("day") or "")
        payload = load_snapshot(day, root) if day else None
        entry = (payload or {}).get("services", {}).get(service_id) if payload else None
        if entry:
            out.append({"day": day, **entry})
    return out


def ensure_baseline(services: Iterable[Any], directory: Optional[str] = None,
                    day: Optional[str] = None, *, compress: bool = False) -> Optional[str]:
    """그 날짜 스냅샷이 없으면 지금 카탈로그로 1장 적재한다(있으면 아무것도 하지 않음).

    배포 이미지에 스냅샷이 한 장도 없는 환경(무료 플랜·새 볼륨)에서도 `compare_ledgers` 가
    `snapshot_missing` 으로 비지 않게 하는 장치입니다. 기동 시와 카탈로그 갱신 후에 부릅니다.
    """
    target_day = day or today_kst()
    root = directory or snapshot_dir()
    if _path_for(target_day, root):
        return None
    payload = build_snapshot(services, target_day,
                             note_ko="기동 시 현재 카탈로그로 적재한 기준일 스냅샷입니다.")
    if not payload.get("services"):
        return None
    return save_snapshot(payload, root, compress=compress)
