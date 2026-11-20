"""주제·지역별 정적 랜딩 페이지 (`/s/`, `/s/{slug}`).

thin content 방지 규칙
---------------------
- 제도가 **5건 이상**인 페이지만 검색엔진에 노출(`index,follow`)하고 사이트맵에 넣습니다.
- 1~4건은 화면은 만들되 `noindex,follow` 로 두고 사이트맵에서 뺍니다.
- 0건은 404 입니다.
이 규칙은 페이지마다 그 지역·주제의 실제 제도 목록과 담당 기관·기준일을 넣을 수 있을 때만
색인하는 방식입니다(내용 없는 페이지를 대량 생성하지 않기 위함).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .catalog import Catalog, tag_label
from . import site_verification

MIN_INDEX_ITEMS = 5
# 한 페이지에 보여 줄 최대 제도 수(실데이터에서 400건짜리 주제도 한 장에 담기지 않게)
MAX_ROWS_PER_PAGE = 60

TOPICS: List[Dict[str, Any]] = [
    {"slug": "cheongnyeon", "title": "청년 지원금", "tag": "youth",
     "intro": "만 19~34세 청년이 신청할 수 있는 월세·구직·자산형성 제도를 모았습니다."},
    {"slug": "chulsan-imsin", "title": "출산·임신 지원금", "tag": "birth",
     "intro": "임신·출산 가구가 확인해야 할 현금·이용권 제도입니다. 아동 대상 제도는 자녀 나이로 판정합니다."},
    {"slug": "yua-yangyuk", "title": "아동·양육 지원금", "tag": "parenting",
     "intro": "영유아·아동 양육 가구를 위한 수당과 보육 지원입니다."},
    {"slug": "jugeo-wolse", "title": "주거·월세·전세 지원", "tag": "housing",
     "intro": "무주택·월세·전세 가구가 확인할 주거비 지원 제도입니다."},
    {"slug": "gu-jik-chwieop", "title": "구직·취업 지원금", "tag": "job",
     "intro": "미취업·구직자의 활동비와 취업지원 제도입니다."},
    {"slug": "sosanggongin", "title": "소상공인·창업 지원", "tag": "small_business",
     "intro": "개인사업자·소상공인 대상 융자·지원 제도입니다(개인 자격과 별도 판정)."},
    {"slug": "jangaein", "title": "장애인 지원", "tag": "disabled",
     "intro": "장애인 대상 소득·활동 지원 제도입니다."},
    {"slug": "hanbumo", "title": "한부모·조손 지원", "tag": "single_parent",
     "intro": "한부모·조손 가구의 양육비·생활 지원입니다."},
    {"slug": "dajanyeo", "title": "다자녀 지원", "tag": "multi_child",
     "intro": "자녀 2명 이상 가구가 확인할 지원 제도입니다."},
    {"slug": "gyoyuk-janghak", "title": "교육·장학금", "tag": "education",
     "intro": "학비·등록금 지원 제도입니다."},
    {"slug": "nongeomin", "title": "농업인 지원", "tag": "farmer",
     "intro": "농업인·농가 대상 지원 제도입니다."},
    {"slug": "saenggye-sodeuk", "title": "생계·소득 지원", "tag": "income",
     "intro": "소득이 낮은 가구의 생계·소득 보전 제도입니다."},
    {"slug": "mujutaek", "title": "무주택 가구 지원", "keyword": "무주택",
     "intro": "무주택 요건이 붙은 주거·자금 지원 제도입니다."},
    # 창업·기업 트랙(K-Startup·기업마당)
    {"slug": "changup-jiwon", "title": "창업 지원사업", "tag": "startup",
     "intro": "예비창업자·초기창업기업이 신청할 수 있는 사업화·보육·멘토링 사업입니다."},
    {"slug": "yeobi-changup", "title": "예비창업패키지·예비창업자 지원", "keyword": "예비창업",
     "intro": "사업자등록 전 예비창업자가 신청할 수 있는 창업지원 사업입니다."},
    {"slug": "sosanggongin-jageum", "title": "소상공인 정책자금·융자", "tag": "finance",
     "intro": "소상공인·개인사업자를 위한 융자·보증·이자 지원 사업입니다."},
    {"slug": "suchul-panro", "title": "수출·판로 지원", "tag": "export",
     "intro": "중소기업의 수출 준비·판로 개설을 돕는 바우처·마케팅 사업입니다."},
    {"slug": "rnd-gisul", "title": "R&D·기술개발 지원", "tag": "rnd",
     "intro": "기술창업·중소기업 R&D와 사업화를 지원하는 사업입니다."},
]

SIDO_SLUGS: Dict[str, str] = {
    "서울특별시": "seoul", "부산광역시": "busan", "대구광역시": "daegu",
    "인천광역시": "incheon", "광주광역시": "gwangju", "대전광역시": "daejeon",
    "울산광역시": "ulsan", "세종특별자치시": "sejong", "경기도": "gyeonggi",
    "강원특별자치도": "gangwon", "충청북도": "chungbuk", "충청남도": "chungnam",
    "전북특별자치도": "jeonbuk", "전라남도": "jeonnam", "경상북도": "gyeongbuk",
    "경상남도": "gyeongnam", "제주특별자치도": "jeju",
}
SLUG_TO_SIDO = {slug: sido for sido, slug in SIDO_SLUGS.items()}


def _collect(all_services: List[Any], spec: Dict[str, Any]) -> List[Any]:
    out = []
    for svc in all_services:
        if spec.get("tag") and spec["tag"] not in svc.tags:
            continue
        if spec.get("keyword"):
            word = spec["keyword"]
            if word not in f"{svc.name} {svc.target} {svc.content}":
                continue
        if spec.get("sido") and svc.region.get("sido") != spec["sido"]:
            continue
        if spec.get("national") and svc.region.get("level") != "national":
            continue
        out.append(svc)
    out.sort(key=lambda svc: (svc.region.get("level") == "national", svc.name))
    return out


def _build_items(catalog: Catalog) -> List[Dict[str, Any]]:
    """페이지 목록을 실제로 만든다(카탈로그 전체를 주제·지역별로 1회만 훑는다)."""
    all_services = catalog.services
    pages: List[Dict[str, Any]] = []
    for spec in TOPICS:
        services = _collect(all_services, spec)
        if not services:
            continue
        pages.append({
            "slug": spec["slug"], "kind": "topic", "title": spec["title"],
            "intro": spec["intro"], "services": services,
            "indexable": len(services) >= MIN_INDEX_ITEMS,
        })
    for sido, slug in SIDO_SLUGS.items():
        services = _collect(all_services, {"sido": sido})
        if not services:
            continue
        pages.append({
            "slug": slug, "kind": "region", "title": f"{sido} 지원금",
            "intro": f"{sido} 소관 제도와 전국 제도를 함께 정리했습니다.",
            "services": services,
            "indexable": len(services) >= MIN_INDEX_ITEMS,
        })
    return pages


def items(catalog: Catalog) -> List[Dict[str, Any]]:
    """렌더 가능한 페이지 목록(제도 1건 이상).

    카탈로그는 읽기 전용이므로 한 번 만든 목록을 재사용한다. 만드는 데 카탈로그 전체를
    주제 18 + 지역 17 번 훑기 때문에(실데이터 1.2만 건) 요청마다 다시 만들면 `/s/`·
    `/s/{slug}`·`/sitemap.xml` 이 수 초 걸린다.
    """
    cached = catalog.memo.get("pseo_items")
    if cached is None:
        cached = tuple(_build_items(catalog))
        catalog.memo["pseo_items"] = cached
    return list(cached)


def slugs(catalog: Optional[Catalog] = None) -> List[str]:
    if catalog is None:
        from .catalog import load_catalog

        catalog = load_catalog()
    return [page["slug"] for page in items(catalog)]


def indexable_paths(catalog: Catalog) -> List[str]:
    return ["/s/"] + [f"/s/{page['slug']}" for page in items(catalog) if page["indexable"]]


def _page(title: str, description: str, body: str, *, noindex: bool = False,
          canonical_path: str = "/s/") -> str:
    from . import static_files
    from .web_ui import BASE_CSS

    robots = "noindex,follow" if noindex else "index,follow"
    canonical = static_files.base_url() + canonical_path
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{title}</title>
<meta name="description" content="{description}">
<meta name="robots" content="{robots}">
{site_verification.meta_tags()}<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:locale" content="ko_KR">
<link rel="canonical" href="{canonical}">
<style>{BASE_CSS}</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <div class="brand">
    <div class="mark" aria-hidden="true">G</div>
    <div><h1>GRNT · 개인·창업 지원금 판정기</h1>
    <p class="en">KOREA GRANT &amp; SUBSIDY INTELLIGENCE</p></div>
  </div>
  <div><a class="pill" href="/">내 조건으로 판정하기</a></div>
</header>
{body}
<p class="foot">공개 데이터(정부24 보조금24 자격 코드 · 창업진흥원 K-Startup · 중소벤처기업부 기업마당 공고 기반 사전 점검입니다. 금액·기한은 소관기관 원문을
확인하세요. 최종 수급·선정 여부는 소관기관 심사로 결정됩니다.</p>
</div>
</body>
</html>
"""


def _clip(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _service_rows(services: List[Any]) -> str:
    rows = []
    for svc in services[:MAX_ROWS_PER_PAGE]:
        criteria_note = ""
        if not svc.has_criteria and not svc.is_business:
            criteria_note = ' <span class="pill ghost">선정기준 원문 미기재 · 확인 필요</span>'
        tag = tag_label(svc.tags[0]) if svc.tags else svc.field_label
        region_label = svc.region.get("label") or ""
        if region_label == svc.agency or svc.region.get("level") == "national":
            region_label = ""
        track_badge = "창업·기업" if svc.is_business else "개인·가구"
        business_line = (f'<p class="meta">신청자격: {svc.business_summary_text}</p>'
                         if svc.business_summary_text else "")
        rows.append(
            '<div class="result">'
            f'<div class="result-head"><div><h4>{svc.name}</h4>'
            f'<p class="meta">{track_badge} · {svc.agency} · {tag}'
            f'{" · " + region_label if region_label else ""}</p></div>'
            f'<span class="badge check_needed">{svc.field_label}</span></div>'
            + (f'<p class="amount">{_clip(svc.content)}</p>' if svc.content else "")
            + business_line
            + f'<p class="meta">대상: {_clip(svc.target) or "원문 확인"}</p>'
            + f'<p class="meta">신청기한: {_clip(svc.deadline_text, 80) or "미기재"} · '
              f'문의: {_clip(svc.contact, 60) or "미기재"}'
            + criteria_note + "</p>"
            + (f'<div class="links"><a href="{svc.detail_url}" rel="noopener noreferrer" '
               f'target="_blank">{"공고 상세" if svc.is_business else "정부24 상세"}</a></div>'
               if svc.detail_url else "")
            + "</div>"
        )
    return "".join(rows)


def render_index(catalog: Catalog) -> str:
    pages = items(catalog)
    topics = [page for page in pages if page["kind"] == "topic"]
    areas = [page for page in pages if page["kind"] == "region"]
    stats = catalog.stats()
    generated = (str(catalog.meta.get("generated_on") or catalog.meta.get("fetched_at")
                     or "")[:10] or "내장 샘플")

    def _links(rows: List[Dict[str, Any]]) -> str:
        return "".join(
            f'<li><a href="/s/{page["slug"]}">{page["title"]}</a>'
            f' <span class="meta">제도 {len(page["services"])}건</span></li>'
            for page in sorted(rows, key=lambda page: (-len(page["services"]), page["title"]))
        )

    business_count = stats.get("business", 0)
    personal_count = stats.get("personal", 0)
    body = f"""
<main>
  <section class="card" style="margin-top:16px">
    <h2>주제별 지원금</h2>
    <p class="sub">제도 {stats['services']:,}건(개인·가구 {personal_count:,} · 창업·기업 {business_count:,})을
    주제별로 묶었습니다. 각 페이지에서 대상·금액·신청기한·문의처를
    확인하고, <a href="/">내 조건으로 판정</a>하면 받을 가능성과 확인 필요 항목을 나눠 볼 수 있습니다.</p>
    <ul style="line-height:2;padding-left:20px">{_links(topics)}</ul>
  </section>
  <section class="card">
    <h2>지역별 지원금</h2>
    <p class="sub">지자체 제도는 소관기관명으로 지역을 판별합니다. 시·도별 공고 수·분야 분포·마감 임박
    목록은 <a href="/regions/">시·도별 지원금</a>에서 한 장으로 볼 수 있습니다. 시·군·구 단위 판정은
    <a href="/">판정 화면</a>에서 시·군·구를 함께 골라 주세요.</p>
    <ul style="line-height:2;padding-left:20px">{_links(areas)}</ul>
  </section>
  <section class="card">
    <h2>데이터</h2>
    <p class="sub">출처: 정부24 보조금24(15113968) · 창업진흥원 K-Startup(15125364) ·
    중소벤처기업부 기업마당(15157820) · 기준일 {generated} ·
    지자체 선정기준 공백 {stats['local_missing_criteria']:,}건은 &lsquo;확인 필요&rsquo;로 표시합니다.</p>
  </section>
</main>
"""
    return _page(
        "주제·지역별 정부·창업 지원금 모음 | GRNT",
        ("청년·출산·주거·구직·소상공인·창업·R&D 등 주제별, 시·도별 정부·지자체 지원금과 "
         "창업·기업 지원사업 목록·신청기한·문의처."),
        body,
    )


def render_item(slug: str, catalog: Catalog) -> Optional[str]:
    page = next((item for item in items(catalog) if item["slug"] == slug), None)
    if page is None:
        return None
    noindex = not page["indexable"]
    services = page["services"]
    local = sum(1 for svc in services if svc.region.get("level") != "national")
    missing = sum(1 for svc in services if not svc.has_criteria)
    body = f"""
<main>
  <section class="card" style="margin-top:16px">
    <h2>{page['title']}</h2>
    <p class="sub">{page['intro']} 제도 {len(services)}건(지자체 {local}건)을 정리했습니다.
    {f'이 중 {missing}건은 원본 선정기준이 비어 있어 &lsquo;확인 필요&rsquo;로 표시합니다.' if missing else ''}</p>
    <div class="links">
      <a class="pill" href="/">내 조건으로 판정하기</a>
      <a href="/s/">주제 전체 보기</a>
    </div>
    {f'<div class="notice">이 페이지는 제도가 {MIN_INDEX_ITEMS}건 미만이라 검색 노출에서 제외(noindex)됩니다. 내용은 그대로 유효합니다.</div>' if noindex else ''}
    {f'<div class="notice">목록이 길어 앞 {MAX_ROWS_PER_PAGE}건만 표시합니다(전체 {len(services)}건). 조건을 넣어 판정하면 더 정확합니다.</div>' if len(services) > MAX_ROWS_PER_PAGE else ''}
  </section>
  <section class="card">
    <h3>제도 목록</h3>
    {_service_rows(services)}
  </section>
</main>
"""
    return _page(
        f"{page['title']} 총정리 (2026) | SUBSIDY-KR",
        f"{page['title']} {len(services)}건의 지원대상·금액·신청기한·문의처 정리. 자격 코드 기반 사전 점검.",
        body,
        noindex=noindex,
        canonical_path=f"/s/{slug}",
    )


def region_name_for_slug(slug: str) -> Optional[str]:
    return SLUG_TO_SIDO.get(slug)
