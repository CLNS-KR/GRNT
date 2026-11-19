"""로컬 JSON 캐시 — 원본 응답을 7일 TTL 로 보관한다.

왜 파일 캐시인가
---------------
- 실데이터 전체(약 1만 건)는 한 번 받아 두면 7일 동안 그대로 쓸 수 있습니다.
- 배포 환경(Render 무료 플랜)은 영구 디스크가 없어 재시작 시 사라집니다.
  서버는 동기화 산출물(`data/gov24/catalog.json`)이 없으면 내장 샘플로 뜨고,
  있으면 그것을 읽어 바로 실데이터로 동작합니다.

원자적 쓰기(temp → replace)로 중간에 죽어도 깨진 JSON 이 남지 않게 합니다.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

KST = timezone(timedelta(hours=9))
DEFAULT_TTL_HOURS = 24 * 7


def now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def age_hours(stamp: Optional[str]) -> float:
    try:
        then = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return 1e9
    if then.tzinfo is None:
        then = then.replace(tzinfo=KST)
    return max(0.0, (datetime.now(KST) - then).total_seconds() / 3600.0)


class JsonCache:
    def __init__(self, root: str) -> None:
        self.root = root

    def path(self, name: str) -> str:
        safe = "".join(ch for ch in str(name) if ch.isalnum() or ch in "._-") or "cache"
        return os.path.join(self.root, f"{safe}.json")

    def load(self, name: str, ttl_hours: float = DEFAULT_TTL_HOURS) -> Tuple[Optional[Dict[str, Any]], float]:
        """(payload, 경과시간). 없거나 TTL 을 넘겼으면 (None, 경과시간)."""
        target = self.path(name)
        try:
            with open(target, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            return None, 1e9
        if not isinstance(payload, dict):
            return None, 1e9
        hours = age_hours(payload.get("fetched_at"))
        if ttl_hours >= 0 and hours > ttl_hours:
            return None, hours
        return payload, hours

    def load_any(self, name: str) -> Tuple[Optional[Dict[str, Any]], float]:
        """TTL 과 무관하게 읽는다(오래된 스냅샷을 '오래됨'으로 표시해 쓰는 용도)."""
        return self.load(name, ttl_hours=-1)

    def save(self, name: str, payload: Dict[str, Any]) -> str:
        os.makedirs(self.root, exist_ok=True)
        target = self.path(name)
        body = dict(payload)
        body.setdefault("fetched_at", now_iso())
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root,
                                             delete=False, suffix=".tmp")
        try:
            json.dump(body, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, target)
        return target

    def exists(self, name: str) -> bool:
        return os.path.exists(self.path(name))
