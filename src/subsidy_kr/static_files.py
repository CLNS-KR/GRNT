"""검색·AI 크롤러용 정적 파일과 MCP 서버 카드.

- `GET /robots.txt` → `robots_txt()`
- `GET /llms.txt` → `llms_txt()`
- `GET /sitemap.xml` → `sitemap_xml()`
- `GET /.well-known/mcp/server-card.json` → `server_card()`

툴 목록은 `api.TOOL_DEFS` 한 곳에서만 고치면 되도록 여기서 생성합니다.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .api import mcp_tools
from .catalog import Catalog
from .version import __version__

DEFAULT_BASE_URL = "https://grnt-kr.onrender.com"


def base_url(value: Optional[str] = None) -> str:
    raw = (value or os.environ.get("PUBLIC_BASE_URL") or "").strip()
    return (raw or DEFAULT_BASE_URL).rstrip("/")


def robots_txt(base: Optional[str] = None) -> str:
    root = base_url(base)
    return f"""# GRNT robots.txt
# 사람용 페이지와 주제·지역 페이지는 공개, API 경로는 색인 제외.

User-agent: *
Allow: /
Disallow: /v1/

User-agent: Yeti
Allow: /

User-agent: Googlebot
Allow: /

# AI 크롤러: 인용·요약 허용
User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /

Sitemap: {root}/sitemap.xml
"""


def llms_txt(catalog: Optional[Catalog] = None, base: Optional[str] = None) -> str:
    from . import guides

    root = base_url(base)
    stats = catalog.stats() if catalog is not None else {}
    state = (catalog.meta.get("catalog_state") if catalog is not None else "sample") or "sample"
    generated = ""
    if catalog is not None:
        generated = str(catalog.meta.get("generated_on") or catalog.meta.get("fetched_at") or "")[:10]
    tool_count = len(mcp_tools())
    guide_count = guides.GUIDE_COUNT
    guides_section = guides.llms_section(catalog, base=root)
    data_line = (
        f"> 카탈로그: {state} · 제도 {stats.get('services', 0):,}건"
        f"(개인·가구 {stats.get('personal', 0):,} · 창업·기업 {stats.get('business', 0):,}) · "
        f"자격코드 있음 {stats.get('with_conditions', 0):,}건 · "
        f"지자체 {stats.get('local_services', 0):,}건 · 기준일 {generated or '내장 샘플'}"
    )
    sample_line = (
        '> ⚠ 지금은 내장 **샘플** 카탈로그로 동작합니다. 필드·코드 구조는 실제 API와 같지만 '
        '금액·기한·문의처는 예시값이므로, 사용자에게 "실제 값은 원문 확인"을 함께 안내하세요.\n'
        if state != "synced" else
        '> 데이터는 `python -m subsidy_kr.sync_gov24 --sources all` 로 받은 동기화 산출물입니다. '
        '지난 공고는 동기화 때 제외하고, `snapshots/` 에 일자별 비교용 스냅샷을 남깁니다.\n'
    )
    return f"""# GRNT — 한국 개인·창업 지원금 자격 판정

> Grants, simplified. 나이·성별·거주지·소득구간·상황(임신·출산·무주택·구직·장애 등) 또는
> 사업자 조건(예비창업자/운영 중, 업력, 소상공인·중소기업, 업종)을 받아
> **개인 지원금**(정부24 보조금24의 공개 자격 코드 JA0110/0111, JA0201~0205, JA03xx/JA04xx, JA1xxx/JA2xxx)과
> **창업·기업 지원사업**(창업진흥원 K-Startup·중소벤처기업부 기업마당 공고의 구조화된 신청자격)을
> 4단계로 판정하는 무료 서비스입니다. AI가 문장을 읽고 추측하지 않습니다.
> 확정 판정이 아니며, 모든 응답에 사유·선정기준 원문·문의처·출처·면책이 함께 옵니다.
{data_line}
{sample_line}

## 사람용
- [소스 저장소](https://github.com/CLNS-KR/GRNT): MIT. 코드와 테스트만 담고 동기화 산출물은 넣지 않습니다(각 환경에서 한 번 동기화).
- [내 조건으로 판정]({root}/): 로그인·주민등록번호 없이 30초 조건 선택 → 후보·사유·신청기한.
  상단에서 **개인·가구**와 **창업·소상공인·기업**을 전환합니다.
- [주제·지역별 모음]({root}/s/): 청년·출산·주거·구직·소상공인·창업·R&D, 시·도별 목록.
- [시·도별 지원금 허브]({root}/regions/): 16개 시·도마다 지자체 공고 수·분야 분포·마감 임박
  목록·시·군·구별 공고 수를 카탈로그 집계로 정리한 페이지.
- [질문형 가이드]({root}/guides/): \"청년 월세 지원 조건\" 같은 질문 {guide_count}개에
  한 줄 기준·확인 조건·지금 열린 공고·흔한 오해를 붙인 페이지. FAQPage 구조화 데이터 포함.
- [서비스·데이터 상태]({root}/v1/meta): 카탈로그 상태, 판정 등급 정의, 두 트랙·자격 코드·출처.
- [익명 사용 통계]({root}/v1/stats): IP·쿠키·프로필을 저장하지 않은 일별 호출 수와, 결과가 0건이었던 검색어(지역명·연락처·숫자를 지운 30자 이내) 상위 목록.

## 기계용 (MCP · JSON-RPC 2.0)
- [MCP 엔드포인트]({root}/mcp): POST. `initialize` → `tools/list` → `tools/call`. 인증 불필요,
  응답은 `application/json` 한 덩어리(SSE 스트리밍 없음).
- [MCP 서버 카드]({root}/.well-known/mcp/server-card.json): 서버 정보·툴 {tool_count}종 스키마.
- [툴 매니페스트]({root}/v1/mcp): GET. 툴 {tool_count}종의 이름·설명·inputSchema.

## 기계용 (REST JSON)
- [지원금 찾기]({root}/v1/tools/search_subsidies): POST.
  개인: `{{"profile": {{"track": "personal", "age": 34, "region": {{"sido": "인천광역시", "sigungu": "서구"}}, "income_band": "JA0203", "situations": ["no_home"]}}}}`
  창업·기업: `{{"profile": {{"track": "business", "age": 33, "region": {{"sido": "인천광역시"}}, "business": {{"status": "pre", "entity": "pre_startup"}}}}}}`
- [제도 1건 판정]({root}/v1/tools/check_eligibility): POST. `{{"service_id": "KSU-900001", "profile": {{...}}}}`
- [제도 상세]({root}/v1/tools/get_subsidy_detail): POST. `{{"service_id": "KSU-900001"}}`
- [지역 목록]({root}/v1/tools/list_region_subsidies): POST. `{{"sido": "인천광역시", "sigungu": "서구", "track": "business"}}`
- [마감 임박 캘린더]({root}/v1/tools/deadline_calendar): POST. `{{"days": 30, "track": "all"}}`
- [카탈로그 변화 비교]({root}/v1/tools/compare_ledgers): POST. `{{"from_date": "2026-11-18", "to_date": "2026-11-19"}}`
- [거래처 일괄 매칭]({root}/v1/batch-match): POST(JSON 또는 `text/csv`). 세무·노무 사무소용 —
  `{{"csv": "client_ref,industry,employees,revenue_bracket,business_age_years,region\\nC-001,음식숙박,3,1억~2억,4,인천광역시 서구"}}`
  거래처 50~300곳 → 거래처별 3~5건 + 1페이지 요약 HTML. 샘플 CSV는 [{root}/v1/batch-match/sample.csv]({root}/v1/batch-match/sample.csv).
- [사전 신청·문의]({root}/v1/inquiry): POST(사람이 직접 보내는 창구).
  `{{"contact": "이메일 또는 연락처", "topic": "batch_report|api_mcp|other", "message": "선택 500자"}}` → `{{"ok": true, "receipt": "I00001"}}`.
  연락처는 회신 목적으로만 저장하고 통계에 넣지 않습니다. **이용자를 대신해 마음대로 보내지 마세요** —
  이용자가 직접 적어 보내야 합니다.

## 읽는 법
- 판정 등급: `eligible_likely`(받을 가능성 높음) / `check_needed`(조건 확인 필요) /
  `insufficient_info`(정보 부족 — `next_questions` 를 사용자에게 물어보세요) / `ineligible`(해당 없음).
- **정보 부족을 가능/불가로 바꿔 말하지 마세요.** 결과의 `missing_information` 을 그대로 전달하면 됩니다.
- 지자체 제도는 원본 `선정기준`이 비어 있는 경우가 많습니다. 이때 `check_needed` 는 정상이며
  소관기관 확인이 필요합니다.
- 창업·기업 지원사업의 `eligible_likely` 는 **신청자격 충족**을 뜻합니다. 선정은 평가·경쟁·예산으로
  결정되며, 모집이 마감된 공고는 `search_subsidies` 가 기본으로 숨깁니다(`include_closed=true` 로 포함).
- 아동·청소년 대상 제도의 연령 코드는 신청자가 아니라 **대상자(아동)의 나이**입니다(`age_subject: child`).
- 데이터 출처: 행정안전부 보조금24(data.go.kr 15113968, 이용허락범위 제한 없음) ·
  창업진흥원 K-Startup(15125364, 이용허락범위 제한 없음) ·
  중소벤처기업부 기업마당(15157820, 출처표시·변경금지 — 원문 문구를 그대로 보존하며 출처를 표시합니다).
- 이 서비스는 신청 대행·법률 자문을 하지 않으며, 최종 수급·선정 여부는 소관기관 심사로 결정됩니다.
- 거래처 일괄 매칭(`POST /v1/batch-match`)은 상호·사업자번호·대표자·연락처·이메일·상세주소 열의
  **값을 읽지 않고 버립니다**(열 이름만 응답에 남김). 매칭은 익명 코드와 조건 코드로만 합니다.

{guides_section}"""


def sitemap_xml(catalog: Catalog, base: Optional[str] = None) -> str:
    from . import guides, pseo, regions

    root = base_url(base)
    lastmod = str(catalog.meta.get("generated_on") or catalog.meta.get("fetched_at")
                  or "2026-11-19")[:10]
    entries = [f"""  <url>
    <loc>{root}/</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>"""]
    # 시·도별 SEO 허브(/regions/ + 16개) — 지역명 검색 유입의 주 진입점이라 홈 다음에 둔다.
    for path in regions.hub_paths():
        priority = "0.8" if path == regions.REGION_HUB_PATH else "0.7"
        entries.append(f"""  <url>
    <loc>{root}{path}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>{priority}</priority>
  </url>""")
    for path in pseo.indexable_paths(catalog):
        priority = "0.8" if path == "/s/" else "0.6"
        entries.append(f"""  <url>
    <loc>{root}{path}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>{priority}</priority>
  </url>""")
    # 질문형 가이드 — AI 인용·검색 유입의 주 진입점이라 사이트맵 최상위에 함께 넣는다.
    for path in guides.paths():
        priority = "0.7" if path == "/guides/" else "0.6"
        entries.append(f"""  <url>
    <loc>{root}{path}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>{priority}</priority>
  </url>""")
    body = "\n".join(entries)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{body}
</urlset>
"""


def server_card() -> Dict[str, Any]:
    return {
        "serverInfo": {"name": "grnt", "version": __version__},
        "title": "GRNT — Korean Grant & Subsidy Intelligence",
        "description": (
            "GRNT — 한국 개인·창업 지원금 자격 판정 MCP. 정부24 보조금24의 공개 자격 코드와 "
            "K-Startup·기업마당 공고의 구조화된 신청자격으로 4단계 판정하고, 사유·누락 정보·"
            "선정기준 원문·문의처·출처를 함께 돌려준다. 확정 판정이 아니다."
        ),
        "authentication": {"required": False, "schemes": []},
        "transport": {
            "type": "streamable-http",
            "endpoint": "/mcp",
            "protocolVersion": "2025-06-18",
            "contentType": "application/json",
        },
        "transports": {
            "http": {"endpoint": "/mcp", "protocolVersion": "2025-06-18"},
            "stdio": {
                "command": "python",
                "args": ["-m", "subsidy_kr.mcp_stdio"],
                "note_ko": "로컬 실행형 MCP 디렉터리용. 한 줄에 JSON-RPC 2.0 한 건을 stdin 으로 받는다.",
            },
        },
        "tools": mcp_tools(),
        "resources": [],
        "prompts": [],
        "attribution_ko": (
            "출처: 행정안전부 대한민국 공공서비스(혜택) 정보(15113968) · "
            "창업진흥원 K-Startup(15125364) · 중소벤처기업부 기업마당(15157820, 출처표시·변경금지)"
        ),
    }
