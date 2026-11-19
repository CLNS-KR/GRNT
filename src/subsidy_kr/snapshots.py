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

import json
import os
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from .cache import now_iso
from .catalog import data_dir_from_env

SNAPSHOT_DIRNAME = "snapshots"
INDEX_FILE = "index.json"
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


def save_snapshot(payload: Dict[str, Any], directory: Optional[str] = None) -> str:
    root = directory or snapshot_dir()
    os.makedirs(root, exist_ok=True)
    day = str(payload.get("meta", {}).get("day") or today_kst())
    target = os.path.join(root, f"{day}.json")
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, target)
    _update_index(root, day, payload)
    return target


def load_snapshot(day: str, directory: Optional[str] = None) -> Optional[Dict[str, Any]]:
    root = directory or snapshot_dir()
    target = os.path.join(root, f"{day}.json")
    try:
        with open(target, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def list_snapshots(directory: Optional[str] = None) -> List[Dict[str, Any]]:
    root = directory or snapshot_dir()
    index = _read_index(root)
    days = index.get("days") or []
    if days:
        return sorted(days, key=lambda row: str(row.get("day") or ""))
    # 색인이 없으면 파일에서 복구
    out: List[Dict[str, Any]] = []
    try:
        names = sorted(name for name in os.listdir(root) if name.endswith(".json")
                       and name != INDEX_FILE)
    except OSError:
        return []
    for name in names:
        payload = load_snapshot(name[:-5], root)
        if payload:
            out.append(dict(payload.get("meta") or {}))
    return out


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
    """스냅샷 두 장을 비교한다(없으면 사유를 그대로 돌려준다)."""
    root = directory or snapshot_dir()
    days = [str(row.get("day")) for row in list_snapshots(root) if row.get("day")]
    latest = day_b or (days[-1] if days else None)
    earlier = day_a
    if not earlier:
        earlier = days[-2] if len(days) >= 2 else None
    if not latest or not earlier:
        return {"ok": False, "error": "snapshot_missing",
                "available_days": days,
                "message_ko": ("비교할 스냅샷이 2장 이상 필요합니다. "
                               "`python -m subsidy_kr.sync_gov24 --sources all` 을 날마다 실행하면 "
                               "`snapshots/{날짜}.json` 이 쌓입니다.")}
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
