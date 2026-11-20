"""창업진흥원 K-Startup 지원사업 공고 API 클라이언트 (data.go.kr 15125364).

오퍼레이션 `getAnnouncementInformation01` 하나만 씁니다(지원사업 공고 정보).
같은 데이터셋의 통계보고서·콘텐츠·통합공고 오퍼레이션은 지원금 판정과 무관합니다.

요청
----
`page`·`perPage`·`returnType=json` 과 선택 조건
`cond[rcrt_prgs_yn::EQ]`(모집중 Y/마감 N) 등. 조건 필터는 서버가 완전히 적용하지
않는 사례가 보고되어 있어, 모집 상태·지역은 받은 뒤 한 번 더 거릅니다.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, List, Optional

from . import programs
from .datagokr import DataGoKrClient
from .version import __version__

BASE_URL = ("https://apis.data.go.kr/B552735/kisedKstartupService01/"
            "getAnnouncementInformation01")
DATASET_ID = "15125364"
DEFAULT_PER_PAGE = 100


class KStartupClient(DataGoKrClient):
    def __init__(self, service_key: str, base_url: str = BASE_URL, *,
                 timeout: float = 20.0, max_retries: int = 2,
                 sleep: Optional[Callable[[float], None]] = None,
                 opener: Optional[Callable[[str], bytes]] = None) -> None:
        kwargs: Dict[str, Any] = {"timeout": timeout, "max_retries": max_retries,
                                  "opener": opener,
                                  "user_agent": f"grnt/{__version__} (+data.go.kr 15125364)"}
        if sleep is not None:
            kwargs["sleep"] = sleep
        super().__init__(service_key, base_url, **kwargs)

    def announcement_page(self, page: int = 1, per_page: int = DEFAULT_PER_PAGE,
                          *, recruiting_only: bool = False) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "page": page,
            "perPage": max(1, int(per_page)),
            "returnType": "json",
        }
        if recruiting_only:
            params["cond[rcrt_prgs_yn::EQ]"] = "Y"
        return self.get_json(params)

    def iter_announcements(self, per_page: int = DEFAULT_PER_PAGE,
                           max_pages: Optional[int] = None,
                           *, recruiting_only: bool = False) -> Iterator[Dict[str, Any]]:
        page = 1
        total: Optional[int] = None
        while True:
            payload = self.announcement_page(page, per_page,
                                             recruiting_only=recruiting_only)
            rows = self.rows(payload)
            total = self.total(payload) if total is None else total
            for row in rows:
                yield row
            if not rows:
                return
            if total is not None and page * per_page >= total:
                return
            if len(rows) < per_page:
                return
            page += 1
            if max_pages is not None and page > max_pages:
                return

    def records(self, per_page: int = DEFAULT_PER_PAGE,
                max_pages: Optional[int] = None, *,
                recruiting_only: bool = False,
                max_records: Optional[int] = None) -> List[Dict[str, Any]]:
        """정규화된 레코드 목록(중복 공고 제거)."""
        seen: Dict[str, Dict[str, Any]] = {}
        for row in self.iter_announcements(per_page, max_pages,
                                           recruiting_only=recruiting_only):
            record = programs.normalize_kstartup(row)
            service_id = record.get("서비스ID")
            if not service_id or not record.get("서비스명"):
                continue
            seen[service_id] = record
            if max_records and len(seen) >= max_records:
                break
        return list(seen.values())
