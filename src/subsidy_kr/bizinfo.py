"""중소벤처기업부 기업마당 중소기업 지원사업 공고 API 클라이언트 (data.go.kr 15157820).

오퍼레이션 `pblancBsnsService` 하나만 씁니다. 요청 변수는 `pageNo`·`numOfRows`·
`dataType=json` 과 선택 조건(`hashtags`·`searchLclasId`·`registDe`·`updtPnttm`)입니다.

이용 조건 주의
-------------
기업마당 데이터는 **출처표시·변경금지** 조건입니다. 그래서 이 모듈은 공고 문구를
요약·수정하지 않고 그대로 옮기고, 응답마다 출처를 붙입니다(programs.SOURCE_ATTRIBUTION).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, List, Optional

from . import programs
from .version import __version__
from .datagokr import DataGoKrClient

BASE_URL = "https://apis.data.go.kr/1421000/bizinfo/pblancBsnsService"
DATASET_ID = "15157820"
DEFAULT_PER_PAGE = 100


class BizinfoClient(DataGoKrClient):
    def __init__(self, service_key: str, base_url: str = BASE_URL, *,
                 timeout: float = 20.0, max_retries: int = 2,
                 sleep: Optional[Callable[[float], None]] = None,
                 opener: Optional[Callable[[str], bytes]] = None) -> None:
        kwargs: Dict[str, Any] = {"timeout": timeout, "max_retries": max_retries,
                                  "opener": opener,
                                  "user_agent": f"grnt/{__version__} (+data.go.kr 15157820)"}
        if sleep is not None:
            kwargs["sleep"] = sleep
        super().__init__(service_key, base_url, **kwargs)

    def notice_page(self, page: int = 1, per_page: int = DEFAULT_PER_PAGE,
                    *, hashtags: Optional[List[str]] = None,
                    field_code: Optional[str] = None,
                    regist_day: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "pageNo": page,
            "numOfRows": max(1, min(int(per_page), 100)),
            "dataType": "json",
        }
        if hashtags:
            params["hashtags"] = ",".join(hashtags)
        if field_code:
            params["searchLclasId"] = field_code
        if regist_day:
            params["registDe"] = regist_day
        return self.get_json(params)

    def iter_notices(self, per_page: int = DEFAULT_PER_PAGE,
                     max_pages: Optional[int] = None,
                     **filters: Any) -> Iterator[Dict[str, Any]]:
        page = 1
        total: Optional[int] = None
        while True:
            payload = self.notice_page(page, per_page, **filters)
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
                max_records: Optional[int] = None,
                **filters: Any) -> List[Dict[str, Any]]:
        seen: Dict[str, Dict[str, Any]] = {}
        for row in self.iter_notices(per_page, max_pages, **filters):
            record = programs.normalize_bizinfo(row)
            service_id = record.get("서비스ID")
            if not service_id or not record.get("서비스명"):
                continue
            seen[service_id] = record
            if max_records and len(seen) >= max_records:
                break
        return list(seen.values())
