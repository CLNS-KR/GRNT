"""공공서비스 레코드 → 판정용 `Service` 객체, 그리고 카탈로그 로딩.

카탈로그 두 가지 모드
---------------------
- `sample`  : 내장 샘플(`sample_data.py` + `sample_programs.py`). 키·네트워크 없이 전체 기능 검증용.
- `synced`  : `python -m subsidy_kr.sync_gov24` 가 만든 `data/gov24/catalog.json`.
              같은 내용의 압축본 `catalog.json.gz` 만 있어도 읽습니다(저장소·이미지에 넣는
              배포용 형태 — 24MB → 3.8MB). 둘 다 있으면 압축하지 않은 파일을 먼저 씁니다.

두 모드는 **같은 정규화 경로**를 지납니다. 실데이터로 바뀌어도 판정·MCP·웹 UI 코드는
그대로입니다. 카탈로그에는 두 트랙이 함께 들어갑니다.

| 트랙 | 출처 | 판정 근거 |
|---|---|---|
| `personal` | 정부24 보조금24(15113968) | JA 자격 코드 |
| `business` | K-Startup(15125364)·기업마당(15157820) | 공고의 구조화 필드(업력·연령·지역·대상) |
"""
from __future__ import annotations

from datetime import date
import gzip
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Dict, Iterable, List, Optional

from . import conditions, deadlines, programs, regions, sample_data, sample_programs

# 서비스분야 → 화면용 짧은 이름
FIELD_LABELS: Dict[str, str] = {
    "주거·자립": "주거",
    "보육·교육": "보육·교육",
    "생활지원": "생활",
    "고용·창업": "고용·창업",
    "보건·의료": "보건",
    "농림축산어업": "농림·어업",
    "행정·안전": "행정",
    "문화·체육·관광": "문화",
    # 창업·기업 트랙(K-Startup·기업마당)의 지원분야
    "사업화": "사업화",
    "시설·공간·보육": "시설·공간",
    "시설ㆍ공간ㆍ보육": "시설·공간",
    "멘토링·컨설팅·교육": "멘토링",
    "멘토링ㆍ컨설팅ㆍ교육": "멘토링",
    "정책자금": "정책자금",
    "행사·네트워크": "행사",
    "행사ㆍ네트워크": "행사",
    "R&D": "R&D",
}

CRITERIA_FLAGS: List[tuple] = [
    ("재산", "재산 기준 포함"),
    ("소득인정액", "소득인정액(재산 반영) 기준"),
    ("거주기간", "거주기간 요건"),
    ("전입", "전입 요건"),
    ("부양의무자", "부양의무자 기준"),
    ("성적", "성적 요건"),
    ("가점", "가점"),
    ("선착순", "선착순 마감"),
    ("추첨", "추첨 선정"),
    ("예산", "예산 소진 시 마감"),
]

# '대상자'가 신청자가 아니라 아동·청소년인 제도. 연령 코드는 그 대상자의 나이다.
_CHILD_TARGET_WORDS = ("아동", "영아", "유아", "출생아", "자녀", "청소년",
                       "초등학생", "중학생", "고등학생")

TAG_RULES: List[tuple] = [
    ("youth", "청년", ("청년",)),
    ("birth", "출산·임신", ("출산", "임신", "임산부", "난임", "첫만남", "부모급여")),
    ("parenting", "아동·양육", ("아동", "영아", "유아", "양육", "보육")),
    ("housing", "주거·월세·전세", ("주거", "월세", "전세", "임대", "무주택", "주택")),
    ("job", "구직·취업", ("구직", "취업", "고용", "일자리")),
    ("small_business", "소상공인·창업", ("소상공인", "창업", "사업자", "정책자금")),
    ("disabled", "장애인", ("장애",)),
    ("single_parent", "한부모", ("한부모", "조손")),
    ("multi_child", "다자녀", ("다자녀", "셋째")),
    ("education", "교육·장학", ("장학", "학비", "등록금", "교육", "아카데미")),
    ("farmer", "농업인", ("농업", "농산물", "농림", "어업", "축산", "임업")),
    ("income", "생계·소득", ("생계", "장려금", "수당", "급여", "소득")),
    ("energy", "에너지·생활", ("에너지", "전기", "가스", "문화누리")),
    # 창업·기업 트랙 전용
    ("startup", "창업지원", ("예비창업", "초기창업", "창업기업", "스타트업", "보육센터", "입주")),
    ("finance", "자금·융자", ("융자", "정책자금", "보증", "대출", "투자")),
    ("rnd", "R&D·기술", ("R&D", "기술개발", "특허", "기술사업화")),
    ("export", "수출·판로", ("수출", "바우처", "판로", "해외")),
]


@dataclass
class Service:
    service_id: str
    name: str
    purpose: str
    agency: str
    agency_code: str
    agency_type: str
    field: str
    user_type: str
    target: str
    criteria: str
    content: str
    support_type: str
    how: str
    deadline_text: str
    receipt_agency: str
    contact: str
    detail_url: str
    online_url: str
    documents: str
    updated_at: str
    conditions: Dict[str, Any]
    region: Dict[str, str]
    source: str = "sample"           # sample | gov24 | kstartup | bizinfo
    extra: Dict[str, Any] = field(default_factory=dict)
    track: str = programs.TRACK_PERSONAL
    business: Dict[str, Any] = field(default_factory=dict)

    # --- 파생 값 -------------------------------------------------------------
    @property
    def is_business(self) -> bool:
        return self.track == programs.TRACK_BUSINESS

    @property
    def track_label(self) -> str:
        return programs.track_label(self.track)

    @property
    def attribution(self) -> str:
        return programs.source_attribution(self.source)

    @property
    def business_summary_text(self) -> str:
        return programs.business_summary(self.business) if self.business else ""

    @cached_property
    def fingerprint(self) -> str:
        """일자별 스냅샷에서 '이 제도가 바뀌었는가'를 판단하는 해시."""
        parts = [self.name, self.agency, self.deadline_text, self.content, self.target,
                 self.field, self.support_type, str(self.business.get("recruiting")),
                 str(self.business.get("max_years")), str(self.business.get("max_age")),
                 self.criteria]
        digest = hashlib.sha256("\u241f".join(parts).encode("utf-8"))
        return digest.hexdigest()[:32]

    # --- 파생 값 -------------------------------------------------------------
    @cached_property
    def groups(self) -> Dict[str, List[str]]:
        return conditions.group_codes(self.conditions)

    @cached_property
    def age(self) -> Dict[str, Any]:
        return conditions.age_range(self.conditions)

    @cached_property
    def income_bands(self) -> List[str]:
        return conditions.income_bands(self.conditions)

    @cached_property
    def gender_scope(self) -> str:
        return conditions.gender_scope(self.conditions)

    @property
    def has_criteria(self) -> bool:
        return bool(str(self.criteria or "").strip())

    @cached_property
    def criteria_flags(self) -> List[str]:
        text = str(self.criteria or "")
        return [label for keyword, label in CRITERIA_FLAGS if keyword in text]

    @cached_property
    def unpredictable_allocation(self) -> bool:
        text = str(self.criteria or "") + " " + str(self.deadline_text or "")
        return any(word in text for word in ("선착순", "추첨", "예산 소진", "예산소진"))

    @cached_property
    def age_subject(self) -> str:
        """`applicant`(신청자 본인) 또는 `child`(아동·청소년)."""
        text = f"{self.name} {self.target}"
        return "child" if any(word in text for word in _CHILD_TARGET_WORDS) else "applicant"

    @cached_property
    def deadline(self) -> Dict[str, Any]:
        return deadlines.parse_deadline(self.deadline_text, title=self.name)

    @property
    def is_expired(self) -> bool:
        if self.is_business and self.business.get("recruiting") == "closed":
            return True
        dl = self.deadline
        if dl.get("expired"):
            return True
        end_date = dl.get("end_date")
        if end_date and end_date < date.today().isoformat():
            return True
        return False

    @cached_property
    def tags(self) -> List[str]:
        text = " ".join([self.name, self.purpose, self.target, self.field,
                         " ".join(self.business.get("hashtags") or []),
                         " ".join(conditions.CODE_CATALOG.get(c, ("", ""))[1]
                                  for c in self.conditions)])
        return [slug for slug, _label, words in TAG_RULES if any(w in text for w in words)]

    @cached_property
    def field_label(self) -> str:
        return FIELD_LABELS.get(self.field, self.field or "기타")

    @property
    def condition_labels(self) -> List[str]:
        return [conditions.describe_code(code) for code in self.conditions]

    def summary(self, *, detail: bool = False) -> Dict[str, Any]:
        block: Dict[str, Any] = {
            "service_id": self.service_id,
            "name": self.name,
            "agency": self.agency,
            "agency_type": self.agency_type,
            "field": self.field,
            "field_label": self.field_label,
            "region": self.region,
            "support_type": self.support_type,
            "target": self.target,
            "contact": self.contact,
            "deadline": self.deadline,
            "detail_url": self.detail_url,
            "online_url": self.online_url,
            "updated_at": self.updated_at,
            "track": self.track,
            "track_label": self.track_label,
            "source": self.source,
            "source_label": programs.source_label(self.source),
            "attribution_ko": self.attribution,
            "tags": self.tags,
            "conditions": [
                {"code": code, "label": conditions.CODE_CATALOG.get(code, ("", code))[1],
                 "value": value}
                for code, value in self.conditions.items()
            ],
        }
        if detail:
            block.update({
                "purpose": self.purpose,
                "criteria": self.criteria,
                "criteria_state": "present" if self.has_criteria else "missing",
                "criteria_flags": self.criteria_flags,
                "content": self.content,
                "how": self.how,
                "documents": self.documents,
                "receipt_agency": self.receipt_agency,
                "deadline_text": self.deadline_text,
                "age_subject": self.age_subject,
                "business": self.business or None,
                "business_summary_ko": self.business_summary_text,
                "fingerprint": self.fingerprint,
            })
        return block


def _text(raw: Dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return default


def normalize_service(raw: Dict[str, Any], source: str = "sample") -> Service:
    """API 레코드(또는 동기화 산출물) → `Service`."""
    service_id = _text(raw, "서비스ID", "SVC_ID", "service_id")
    agency = _text(raw, "소관기관명", "agency")
    region = raw.get("region") if isinstance(raw.get("region"), dict) else None
    if not region:
        region = regions.parse_agency_region(agency)
    conds = conditions.normalize_conditions(raw.get("conditions") or raw)
    track = str(raw.get("track") or "").strip() or programs.TRACK_PERSONAL
    if track not in programs.TRACK_LABELS:
        track = programs.TRACK_PERSONAL
    business = raw.get("business") if isinstance(raw.get("business"), dict) else {}
    row_source = str(raw.get("source") or "").strip()
    if source == "gov24" and row_source:
        # 동기화 산출물은 행마다 출처를 가지고 있다(gov24·kstartup·bizinfo·sample).
        source = row_source
    return Service(
        service_id=service_id,
        name=_text(raw, "서비스명", "name"),
        purpose=_text(raw, "서비스목적요약", "서비스목적", "purpose"),
        agency=agency,
        agency_code=_text(raw, "소관기관코드", "agency_code"),
        agency_type=_text(raw, "소관기관유형", "agency_type"),
        field=_text(raw, "서비스분야", "field"),
        user_type=_text(raw, "사용자구분", "user_type"),
        target=_text(raw, "지원대상", "target"),
        criteria=_text(raw, "선정기준", "criteria"),
        content=_text(raw, "지원내용", "content"),
        support_type=_text(raw, "지원유형", "support_type"),
        how=_text(raw, "신청방법", "how"),
        deadline_text=_text(raw, "신청기한", "deadline"),
        receipt_agency=_text(raw, "접수기관", "접수기관명", "receipt_agency"),
        contact=_text(raw, "전화문의", "문의처", "contact"),
        detail_url=_text(raw, "상세조회URL", "detail_url"),
        online_url=_text(raw, "온라인신청사이트URL", "online_url"),
        documents=_text(raw, "구비서류", "documents"),
        updated_at=_text(raw, "수정일시", "updated_at"),
        conditions=conds,
        region=region,
        source=source,
        extra={**{k: v for k, v in raw.items()
                  if k in ("조회수", "등록일시", "부서명", "법령", "자치법규", "공고일련번호",
                           "공고ID", "해시태그", "지원분야", "접수시작일", "접수종료일")},
               **(raw.get("extra") if isinstance(raw.get("extra"), dict) else {})},
        track=track,
        business=business,
    )


class Catalog:
    """서비스 목록 + 색인. 읽기 전용으로만 쓴다."""

    def __init__(self, services: List[Service], meta: Dict[str, Any]) -> None:
        self.services = services
        self.meta = meta
        self.by_id = {svc.service_id: svc for svc in services}
        self._stats: Optional[Dict[str, Any]] = None
        self._by_sido: Dict[str, List[Service]] = {}
        # 요청과 무관한 파생값 캐시(카탈로그는 읽기 전용이다). `engine`·`pseo` 가 함께 쓴다.
        # 서버는 이 객체 하나를 프로세스 수명 동안 재사용하므로, 여기에 계산 결과를 두면
        # 요청마다 1.2만 건을 다시 훑지 않아도 된다.
        self.memo: Dict[str, Any] = {}
        # 모집이 마감된 공고 수(기업 마감 + 신청기한 지난 개인/기업 공고)
        self.closed_business_count = sum(
            1 for svc in services
            if svc.is_business and svc.business.get("recruiting") == "closed"
        )
        self.expired_count = sum(1 for svc in services if svc.is_expired)
        for svc in services:
            if svc.region.get("sido") and svc.region.get("level") in ("sido", "sigungu"):
                self._by_sido.setdefault(svc.region["sido"], []).append(svc)

    # --- 조회 ---------------------------------------------------------------
    def get(self, service_id: str) -> Optional[Service]:
        return self.by_id.get(str(service_id or "").strip())

    def all(self) -> List[Service]:
        return list(self.services)

    def by_track(self, track: Optional[str] = None) -> List[Service]:
        if track in (None, "", "all"):
            return list(self.services)
        return [svc for svc in self.services if svc.track == track]

    def track_services(self, track: str) -> List[Service]:
        return [svc for svc in self.services if svc.track == track]

    def by_region(self, sido: Optional[str] = None,
                  sigungu: Optional[str] = None,
                  *, include_national: bool = True) -> List[Service]:
        province = regions.canonical_sido(sido)
        district = regions.canonical_sigungu(province, sigungu) if province else None
        out: List[Service] = []
        for svc in self.services:
            level = svc.region.get("level")
            if level == "national":
                if include_national:
                    out.append(svc)
                continue
            if not province:
                continue
            if svc.region.get("sido") != province:
                continue
            if district and level == "sigungu" and svc.region.get("sigungu") != district:
                continue
            out.append(svc)
        return out

    def search(self, keyword: str, limit: int = 20,
               *, region: Optional[Dict[str, str]] = None) -> List[Service]:
        words = [word for word in re.split(r"\s+", str(keyword or "").strip()) if word]
        if not words:
            return []
        hits: List[tuple] = []
        for svc in self.services:
            haystack = (f"{svc.name} {svc.purpose} {svc.target} {svc.content} {svc.agency} "
                        f"{' '.join(svc.business.get('hashtags') or [])}")
            score = sum(haystack.count(word) for word in words)
            if not score:
                continue
            if region and region.get("level") in ("sido", "sigungu"):
                match = regions.match_region(region, svc.region)
                if match["state"] == "mismatch":
                    continue
            # 이름에 걸린 단어에 가중치를 준다
            score += 3 * sum(svc.name.count(word) for word in words)
            hits.append((score, svc))
        hits.sort(key=lambda pair: (-pair[0], pair[1].name))
        return [svc for _score, svc in hits[:max(1, limit)]]

    def stats(self) -> Dict[str, Any]:
        """카탈로그 통계(한 번 계산해 재사용). 4만 건에서도 매 요청 재계산하지 않는다."""
        if self._stats is not None:
            return self._stats
        total = len(self.services)
        with_conditions = sum(1 for svc in self.services if svc.conditions)
        local = [svc for svc in self.services if svc.region.get("level") != "national"]
        local_missing = [svc for svc in local if not svc.has_criteria]
        business = [svc for svc in self.services if svc.is_business]
        recruiting = sum(1 for svc in business
                         if svc.business.get("recruiting") == "open")
        by_source: Dict[str, int] = {}
        for svc in self.services:
            by_source[svc.source] = by_source.get(svc.source, 0) + 1
        self._stats = {
            "services": total,
            "with_conditions": with_conditions,
            "without_conditions": total - with_conditions,
            "local_services": len(local),
            "local_missing_criteria": len(local_missing),
            "local_missing_criteria_note_ko": (
                "지자체 제도 중 선정기준이 비어 있는 건수입니다. 실데이터에서 이 비율이 높을수록 "
                "'확인 필요' 판정이 늘어납니다."
            ),
            "agencies": len({svc.agency for svc in self.services if svc.agency}),
            "sido_covered": len(self._by_sido),
            "personal": total - len(business),
            "business": len(business),
            "business_recruiting_now": recruiting,
            "by_track": {programs.TRACK_PERSONAL: total - len(business),
                         programs.TRACK_BUSINESS: len(business)},
            "by_source": by_source,
        }
        return self._stats


def data_dir_from_env(default: Optional[str] = None) -> str:
    raw = (os.environ.get("SUBSIDY_KR_DATA") or "").strip()
    if raw:
        return raw
    if default:
        return default
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(project_root, "data", "gov24")


def sample_catalog() -> Catalog:
    meta = sample_data.meta()
    meta.update(sample_programs.meta())
    meta.update({
        "catalog_state": "sample",
        "source_note_ko": (
            "15113968·15125364·15157820 승인 전이거나 오프라인일 때 쓰는 내장 샘플입니다."
            " 구조·필드는 실제 API와 같고 금액·기한은 예시값입니다."
        ),
    })
    rows = (sample_data.services()
            + sample_programs.services())
    return Catalog([normalize_service(raw, source="sample") for raw in rows], meta)


CATALOG_FILENAME = "catalog.json"
CATALOG_GZIP_SUFFIX = ".gz"


def catalog_candidates(target: str) -> List[str]:
    """읽을 후보 경로 — 압축하지 않은 원본을 먼저, 그다음 `.gz` 압축본."""
    if target.endswith(CATALOG_GZIP_SUFFIX):
        return [target]
    return [target, target + CATALOG_GZIP_SUFFIX]


def read_catalog_payload(path: str) -> Any:
    """`catalog.json` 또는 `catalog.json.gz` 를 읽어 JSON 으로 돌려준다."""
    if path.endswith(CATALOG_GZIP_SUFFIX):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_catalog(path: Optional[str] = None) -> Catalog:
    """동기화 산출물(원본 또는 압축본)이 있으면 그것을, 없으면 샘플을 읽는다."""
    target = path or os.path.join(data_dir_from_env(), CATALOG_FILENAME)
    source = next((candidate for candidate in catalog_candidates(target)
                   if os.path.exists(candidate)), None)
    if source is None:
        return sample_catalog()
    try:
        payload = read_catalog_payload(source)
        rows = payload.get("services") or []
        if not rows:
            raise ValueError("empty_catalog")
        meta = dict(payload.get("meta") or {})
        meta["catalog_state"] = "synced"
        meta.setdefault("data_state", "live_sync")
        meta["catalog_file"] = os.path.basename(source)
        meta["catalog_compressed"] = source.endswith(CATALOG_GZIP_SUFFIX)
        services = [normalize_service(row, source="gov24") for row in rows]
    except (OSError, EOFError, ValueError, TypeError, json.JSONDecodeError):
        catalog = sample_catalog()
        catalog.meta["fallback_reason_ko"] = (
            "동기화 산출물(catalog.json / catalog.json.gz)을 읽지 못해 내장 샘플로 동작합니다."
        )
        return catalog
    return Catalog(services, meta)


def iter_tags() -> Iterable[str]:
    for slug, _label, _words in TAG_RULES:
        yield slug


def tag_label(slug: str) -> str:
    for key, label, _words in TAG_RULES:
        if key == slug:
            return label
    return slug
