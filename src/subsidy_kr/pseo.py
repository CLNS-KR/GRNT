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
import html
import json

from .catalog import Catalog, tag_label
from . import redact, regions, site_verification

MIN_INDEX_ITEMS = 5
# 페이지 머리의 브랜드 문구는 h1 이 아니라 p 로, h1 은 페이지 주제에 쓴다(검색엔진이 제목을 고를 때
# 브랜드명이 아니라 주제를 잡게 하려는 것).
PAGE_CSS = (
    ".brand-name{margin:0;font-size:18px;letter-spacing:-.2px;font-weight:700}"
    ".brand-name a{color:inherit;text-decoration:none}"
    "h1.page-title{font-size:20px;margin:0 0 6px;letter-spacing:-.3px}"
)
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

SIDO_SLUGS = regions.SIDO_SLUGS
SLUG_TO_SIDO = regions.SLUG_TO_SIDO


def _collect(all_services: List[Any], spec: Dict[str, Any]) -> List[Any]:
    """(호환용) 서비스 목록에서 한 페이지의 제도를 고른다 — 테스트·스크립트가 쓴다."""
    out = []
    for svc in all_services:
        if not _matches(svc, spec):
            continue
        out.append(svc)
    out.sort(key=lambda svc: (svc.region.get("level") == "national", svc.name))
    return out


def _matches(svc: Any, spec: Dict[str, Any]) -> bool:
    if spec.get("tag") and spec["tag"] not in svc.tags:
        return False
    if spec.get("keyword"):
        word = spec["keyword"]
        if word not in f"{svc.name} {svc.target} {svc.content}":
            return False
    if spec.get("sido") and svc.region.get("sido") != spec["sido"]:
        return False
    if spec.get("national") and svc.region.get("level") != "national":
        return False
    return True


def _page_specs() -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for spec in TOPICS:
        specs.append({"slug": spec["slug"], "kind": "topic", "title": spec["title"],
                      "intro": spec["intro"], "tag": spec.get("tag"),
                      "keyword": spec.get("keyword"), "sido": ""})
    for sido, slug in SIDO_SLUGS.items():
        specs.append({"slug": slug, "kind": "region", "title": _region_title(sido),
                      "intro": _region_intro(sido), "tag": None, "keyword": None,
                      "sido": sido})
    return specs


def _region_title(sido: str) -> str:
    return f"{sido} 지원금 목록"


def _region_intro(sido: str) -> str:
    return (f"{sido} 소관 공고와 전국 공통 제도를 한 목록으로 모았습니다. 대상·지원내용·"
            "신청기한·문의처를 그대로 확인할 수 있고, 시·군·구별 공고 수와 마감 임박 "
            "현황은 지역 허브에서 봅니다.")


def _build_items(catalog: Catalog) -> List[Dict[str, Any]]:
    """페이지 목록을 만든다(카탈로그를 한 번만 훑는다).

    페이지마다 **제도 id 만** 담는다. 예전에는 `Service` 객체 목록을 통째로 붙들어
    `/s/` 를 한 번 열면 118~171MB 가 상주했다(Render 512MB OOM 원인). 화면에 그릴 때는
    필요한 앞 60건만 `catalog.get_many(...)` 로 읽는다.
    """
    specs = _page_specs()
    for page in specs:
        page["ids"] = []          # (전국 여부, 이름, id) — 정렬 뒤 id 만 남긴다
        page["local"] = 0
        page["missing"] = 0
    for svc in catalog.iter_services():
        national = svc.region.get("level") == "national"
        for page in specs:
            if not _matches(svc, page):
                continue
            page["ids"].append((national, svc.name, svc.service_id))
            if not national:
                page["local"] += 1
            if not svc.has_criteria:
                page["missing"] += 1
    pages: List[Dict[str, Any]] = []
    for page in specs:
        if not page["ids"]:
            continue
        page["ids"].sort()
        ids = [service_id for _national, _name, service_id in page["ids"]]
        pages.append({
            "slug": page["slug"], "kind": page["kind"], "title": page["title"],
            "intro": page["intro"], "count": len(ids), "service_ids": tuple(ids),
            "local": int(page["local"]), "missing": int(page["missing"]),
            "indexable": len(ids) >= MIN_INDEX_ITEMS,
        })
    return pages


def items(catalog: Catalog) -> List[Dict[str, Any]]:
    """렌더 가능한 페이지 목록(제도 1건 이상).

    카탈로그는 읽기 전용이므로 한 번 만든 목록을 재사용한다. 만드는 데 카탈로그 전체를
    주제 18 + 지역 16 번 훑기 때문에(실데이터 1.2만 건) 요청마다 다시 만들면 `/s/`·
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


def json_ld_blocks(page: Dict[str, Any], canonical: str, services: List[Any],
                   *, root: str) -> List[Dict[str, Any]]:
    """주제·지역 페이지 구조화 데이터 — CollectionPage + ItemList + BreadcrumbList.

    AI 검색이 "이 페이지가 어떤 목록인지, 몇 건인지, 첫 항목은 무엇인지"를 읽게 한다.
    목록 항목은 화면에 그린 순서 그대로 앞 10건만 넣는다(화면과 구조화 데이터를 맞춘다).
    """
    items = [
        {"@type": "ListItem", "position": index, "name": redact.mask_emails(str(svc.name)),
         "url": (svc.detail_url or svc.online_url or canonical)}
        for index, svc in enumerate(services[:10], start=1)
    ]
    collection: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": page["title"],
        "url": canonical,
        "description": page["intro"],
        "inLanguage": "ko-KR",
        "isPartOf": {"@type": "WebSite", "name": "GRNT", "url": root + "/"},
        "publisher": {"@type": "Organization", "name": "GRNT", "url": root + "/"},
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": int(page["count"]),
            "itemListOrder": "https://schema.org/ItemListOrderAscending",
            "itemListElement": items,
        },
    }
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "GRNT", "item": root + "/"},
            {"@type": "ListItem", "position": 2, "name": "주제·지역별 지원금 모음",
             "item": root + "/s/"},
            {"@type": "ListItem", "position": 3, "name": page["title"], "item": canonical},
        ],
    }
    return [collection, breadcrumb]


def _page(title: str, description: str, body: str, *, heading: str, noindex: bool = False,
          canonical_path: str = "/s/",
          json_ld: Optional[List[Dict[str, Any]]] = None) -> str:
    from . import legal, static_files
    from .web_ui import BASE_CSS

    robots = "noindex,follow" if noindex else "index,follow"
    canonical = static_files.base_url() + canonical_path
    esc = html.escape
    scripts = "".join(
        '<script type="application/ld+json">'
        + json.dumps(block, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        + "</script>\n"
        for block in (json_ld or [])
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="{robots}">
{site_verification.meta_tags()}<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:locale" content="ko_KR">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{static_files.base_url()}/static/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{canonical}">
{scripts}<style>{BASE_CSS}{PAGE_CSS}</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <div class="brand">
    <div class="mark" aria-hidden="true">G</div>
    <div><p class="brand-name"><a href="/">GRNT · 개인·창업 지원금 판정기</a></p>
    <p class="en">KOREA GRANT &amp; SUBSIDY INTELLIGENCE</p></div>
  </div>
  <div><a class="pill" href="/">내 조건으로 판정하기</a></div>
</header>
{body}
<p class="foot">공개 데이터(정부24 보조금24 자격 코드 · 창업진흥원 K-Startup · 중소벤처기업부 기업마당 공고 기반 사전 점검입니다. 금액·기한은 소관기관 원문을
확인하세요. 최종 수급·선정 여부는 소관기관 심사로 결정됩니다.<br>
{legal.landing_footer_html()}</p>
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
        # 원문에 담당자 이메일이 섞여 있어도 화면에는 가려서 내보낸다.
        name = redact.mask_emails(svc.name)
        agency = redact.mask_emails(svc.agency)
        content = redact.mask_emails(_clip(svc.content)) if svc.content else ""
        target = redact.mask_emails(_clip(svc.target)) or "원문 확인"
        deadline_text = redact.mask_emails(_clip(svc.deadline_text, 80)) or "미기재"
        contact = redact.mask_emails(_clip(svc.contact, 60)) or "미기재"
        business_summary = redact.mask_emails(svc.business_summary_text)
        criteria_note = ""
        if not svc.has_criteria and not svc.is_business:
            criteria_note = ' <span class="pill ghost">선정기준 원문 미기재 · 확인 필요</span>'
        tag = tag_label(svc.tags[0]) if svc.tags else svc.field_label
        region_label = svc.region.get("label") or ""
        if region_label == svc.agency or svc.region.get("level") == "national":
            region_label = ""
        track_badge = "창업·기업" if svc.is_business else "개인·가구"
        business_line = (f'<p class="meta">신청자격: {business_summary}</p>'
                         if business_summary else "")
        rows.append(
            '<div class="result">'
            f'<div class="result-head"><div><h4>{name}</h4>'
            f'<p class="meta">{track_badge} · {agency} · {tag}'
            f'{" · " + region_label if region_label else ""}</p></div>'
            f'<span class="badge check_needed">{svc.field_label}</span></div>'
            + (f'<p class="amount">{content}</p>' if content else "")
            + business_line
            + f'<p class="meta">대상: {target}</p>'
            + f'<p class="meta">신청기한: {deadline_text} · '
              f'문의: {contact}'
            + criteria_note + "</p>"
            + (f'<div class="links"><a href="{svc.detail_url}" rel="noopener noreferrer" '
               f'target="_blank">{"공고 상세" if svc.is_business else "정부24 상세"}</a></div>'
               if svc.detail_url else "")
            + "</div>"
        )
    return "".join(rows)


def _index_json_ld(pages: List[Dict[str, Any]], root: str, canonical: str) -> List[Dict[str, Any]]:
    """`/s/` 색인 구조화 데이터 — 주제·지역 목록을 ItemList 로 담는다."""
    items = [
        {"@type": "ListItem", "position": index, "name": page["title"],
         "url": f"{root}/s/{page['slug']}"}
        for index, page in enumerate(pages[:40], start=1)
    ]
    collection = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "주제·지역별 지원금 모음",
        "url": canonical,
        "inLanguage": "ko-KR",
        "isPartOf": {"@type": "WebSite", "name": "GRNT", "url": root + "/"},
        "publisher": {"@type": "Organization", "name": "GRNT", "url": root + "/"},
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(pages),
                       "itemListOrder": "https://schema.org/ItemListUnordered",
                       "itemListElement": items},
    }
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "GRNT", "item": root + "/"},
            {"@type": "ListItem", "position": 2, "name": "주제·지역별 지원금 모음",
             "item": canonical},
        ],
    }
    return [collection, breadcrumb]


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
            f' <span class="meta">제도 {page["count"]}건</span></li>'
            for page in sorted(rows, key=lambda page: (-page["count"], page["title"]))
        )

    business_count = stats.get("business", 0)
    personal_count = stats.get("personal", 0)
    body = f"""
<main>
  <section class="card" style="margin-top:16px">
    <h1 class="page-title">주제·지역별 지원금 모음</h1>
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
    from . import static_files

    root = static_files.base_url()
    return _page(
        "주제·지역별 정부·창업 지원금 모음 | GRNT",
        ("청년·출산·주거·구직·소상공인·창업·R&D 등 주제별, 시·도별 정부·지자체 지원금과 "
         "창업·기업 지원사업 목록·신청기한·문의처."),
        body,
        heading="주제·지역별 지원금 모음",
        json_ld=_index_json_ld(pages, root, root + "/s/"),
    )


def render_item(slug: str, catalog: Catalog) -> Optional[str]:
    page = next((item for item in items(catalog) if item["slug"] == slug), None)
    if page is None:
        return None
    noindex = not page["indexable"]
    count = int(page["count"])
    local = int(page.get("local") or 0)
    missing = int(page.get("missing") or 0)
    # 화면에 그릴 앞부분만 읽는다(예전에는 페이지마다 1.2만 건 목록을 통째로 들고 있었다).
    wanted = list(page["service_ids"])[:MAX_ROWS_PER_PAGE]
    services = catalog.get_many(wanted) if wanted else []
    region_hub = _region_hub_link(page)
    body = f"""
<main>
  <section class="card" style="margin-top:16px">
    <h1 class="page-title">{html.escape(page['title'])}</h1>
    <p class="sub">{html.escape(page['intro'])} 제도 {count}건(지자체 {local}건)을 정리했습니다.
    {f'이 중 {missing}건은 원본 선정기준이 비어 있어 &lsquo;확인 필요&rsquo;로 표시합니다.' if missing else ''}</p>
    <div class="links">
      <a class="pill" href="/">내 조건으로 판정하기</a>
      <a href="/s/">주제 전체 보기</a>
      {region_hub}
    </div>
    {f'<div class="notice">이 페이지는 제도가 {MIN_INDEX_ITEMS}건 미만이라 검색 노출에서 제외(noindex)됩니다. 내용은 그대로 유효합니다.</div>' if noindex else ''}
    {f'<div class="notice">목록이 길어 앞 {MAX_ROWS_PER_PAGE}건만 표시합니다(전체 {count}건). 조건을 넣어 판정하면 더 정확합니다.</div>' if count > MAX_ROWS_PER_PAGE else ''}
  </section>
  <section class="card">
    <h2>제도 목록</h2>
    {_service_rows(services)}
  </section>
</main>
"""
    from . import static_files

    root = static_files.base_url()
    canonical = f"{root}/s/{slug}"
    return _page(
        f"{page['title']} \u2014 대상·금액·신청기한 총정리 (2026) | GRNT",
        f"{page['title']} {count}건의 지원대상·금액·신청기한·문의처 정리. 자격 코드 기반 사전 점검.",
        body,
        heading=page["title"],
        noindex=noindex,
        canonical_path=f"/s/{slug}",
        json_ld=json_ld_blocks(page, canonical, services, root=root),
    )


def _region_hub_link(page: Dict[str, Any]) -> str:
    """지역 주제 페이지는 시·도 허브로 넘긴다 — 두 페이지의 검색 의도를 나눈다.

    `/s/seoul` 은 제도 목록(대상·금액·기한), `/regions/seoul` 은 시·군·구별 건수·마감 현황이다.
    같은 말을 두 번 쓰지 않고 서로를 가리키게 해 키워드 중복을 줄인다.
    """
    if page.get("kind") != "region":
        return ""
    sido = SLUG_TO_SIDO.get(page["slug"])
    if not sido:
        return ""
    return f'<a href="/regions/{page["slug"]}">{html.escape(sido)} 시·군·구별 현황·마감</a>'


def region_name_for_slug(slug: str) -> Optional[str]:
    return SLUG_TO_SIDO.get(slug)
