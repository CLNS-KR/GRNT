"""정적 고지 페이지 — `/privacy` · `/terms` · `/about`.

왜 서버 렌더 정적 HTML 인가
--------------------------
- 사람·검색 크롤러·AI 크롤러가 같은 내용을 본다(JS 없음, 외부 CDN 없음 → CSP 그대로).
- 판정 도구는 "무엇을 받지 않는지"를 먼저 밝혀야 신뢰가 생긴다. 그 문구를 한 곳에 두고
  세 주소가 같은 내용을 쓴다.

익명 운영 원칙
--------------
실명·직업·개인 연락처·상대 서비스 핸들을 쓰지 않는다. 문의·삭제 요청 경로는 서비스 자체
접수(`POST /v1/inquiry`)와 공개 저장소 Issues 만 쓴다.
"""
from __future__ import annotations

from typing import Dict, Optional

from . import static_files
from .version import SERVICE_NAME, SERVICE_TAGLINE, __version__

SERVICE = SERVICE_NAME
TAGLINE = SERVICE_TAGLINE
REPO_URL = "https://github.com/CLNS-KR/GRNT"
REPO_ISSUES = REPO_URL + "/issues"
SIBLINGS = (
    ("https://clns-kr.onrender.com/", "CLNS", "한국 수입 규제 사전 점검"),
    ("https://frnc.onrender.com/", "FRNC", "프랜차이즈 창업 전 리스크 체크"),
)
EFFECTIVE_DATE = "2026-11-21"

TITLES: Dict[str, str] = {
    "privacy": "개인정보 처리방침",
    "terms": "이용약관",
    "about": "서비스 소개",
}
DESCRIPTIONS: Dict[str, str] = {
    "privacy": "GRNT가 받지 않는 정보, 익명 카운터에 남는 것, 0건 검색어 처리, 문의 연락처 180일 보관과 삭제 요청 경로입니다.",
    "terms": "GRNT는 무료 정보 제공 서비스입니다. 확정 판정·전문가 자문이 아니며 근거와 한계를 밝힙니다.",
    "about": "개인·창업 지원금 판정기 GRNT의 대상, 데이터 출처(보조금24·K-Startup·기업마당·지자체 포털), 판정 4단계를 소개합니다.",
}

_CSS = """
:root{--bg:#0b1019;--card:#121a2b;--line:#243252;--ink:#e8edf5;--soft:#9fb3d9;--brand:#7ea6ff}
@media (prefers-color-scheme:light){:root{--bg:#f6f8fc;--card:#fff;--line:#dbe3f2;--ink:#16213a;--soft:#4c5f80;--brand:#1c5bd8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
.wrap{max-width:780px;margin:0 auto;padding:32px 20px 64px}
.top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.top a.brand{color:var(--ink);text-decoration:none;font-weight:800;font-size:20px;letter-spacing:.02em}
.top span{color:var(--soft);font-size:13px}
h1{font-size:26px;line-height:1.35;margin:18px 0 6px}
h2{font-size:18px;margin:30px 0 8px}
p,li{color:var(--ink)}
.meta{color:var(--soft);font-size:13px;margin:0 0 18px}
ul{padding-left:20px;margin:8px 0}
li{margin:6px 0}
a{color:var(--brand)}
code{font-size:13px;background:rgba(126,166,255,.14);padding:1px 5px;border-radius:5px}
.nav{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--soft)}
.nav a{margin-right:10px}
footer{margin-top:28px;font-size:12px;color:var(--soft)}
"""

_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {service}</title>
<meta name="description" content="{description}">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{service}">
<meta property="og:title" content="{title} · {service}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
<meta property="og:locale" content="ko_KR">
<meta property="og:image" content="{root}/static/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <a class="brand" href="/">{service}</a>
    <span>{tagline} · 개인·창업 지원금 판정</span>
  </div>
  <h1>{title}</h1>
  <p class="meta">시행일 {effective} · 버전 {version} · 무료 베타</p>
  {body}
  <div class="nav">{nav}</div>
  <footer>© 2026 {service} · 익명 운영 무료 베타 · 이 페이지는 사전 점검 서비스의 고지이며 법률 자문이 아닙니다.</footer>
</div>
</body>
</html>
"""


def _page(slug: str, body: str, base: Optional[str] = None) -> str:
    root = static_files.base_url(base)
    canonical = f"{root}/{slug}"
    nav_items = ['<a href="/">지원금 판정</a>', '<a href="/s/">주제별</a>',
                 '<a href="/regions/">시·도별</a>', '<a href="/guides/">자주 묻는 질문</a>']
    for other, title in TITLES.items():
        if other != slug:
            nav_items.append(f'<a href="/{other}">{title}</a>')
    return _PAGE.format(title=TITLES[slug], description=DESCRIPTIONS[slug], canonical=canonical,
                        service=SERVICE, tagline=TAGLINE, css=_CSS, version=__version__,
                        effective=EFFECTIVE_DATE, body=body, nav="".join(nav_items), root=root)


def _privacy(base: Optional[str] = None) -> str:
    body = f"""
<p>GRNT는 회원가입·로그인이 없고, 결제도 받지 않습니다. 지원금 판정에 필요한 조건만 입력받아
그 자리에서 계산하고, <strong>입력값 자체는 저장하지 않습니다</strong>. 아래에 예외와 보관 기간을 적었습니다.</p>

<h2>받지 않는 정보</h2>
<ul>
  <li>이름·주민등록번호·전화번호·주소·건강정보: 판정에 쓰지 않고 저장하지 않습니다.</li>
  <li>회원 계정·비밀번호·소셜 로그인: 만들지 않습니다.</li>
  <li>브라우저 쿠키·광고 식별자·추적 스크립트: 쓰지 않습니다. 입력값을 브라우저 저장소에 남기지도 않습니다.</li>
</ul>

<h2>판정에 쓰는 입력</h2>
<p>나이(또는 출생연도)·성별·시·도/시·군·구·가구원 수·소득구간·해당 상황, 사업자 조건(예비창업/운영,
업력·업종·기업 형태)은 <strong>응답을 계산하는 동안에만</strong> 메모리에 있습니다. 결과를 만든 뒤
서버에 저장하지 않고, 결과 화면에도 개인을 특정할 값은 남기지 않습니다.</p>

<h2>익명 카운터에 남는 것</h2>
<ul>
  <li>날짜·경로·툴 이름·판정 등급의 <em>호출 횟수</em>만 남깁니다.</li>
  <li>IP 주소·User-Agent 원문·쿠키·Referer·세션 ID는 저장하지 않습니다. 요청 빈도 제한에 쓰는 IP는
  메모리에만 두고 60초 뒤 버립니다.</li>
  <li><strong>요청 종류</strong> — 브라우저인지 봇인지의 구분(브라우저·봇·기타 3종)만 셉니다. User-Agent 원문은 남기지 않습니다(봇 판별은 문자열 표식 기준의 참고 수치).</li>
</ul>

<h2>0건으로 끝난 검색어만 예외적으로</h2>
<p>"찾는 제도가 없다"를 개선하는 데만 쓰기 위해, <strong>결과가 0건이었던 검색어</strong>를 비식별 처리해
최대 30자로 남깁니다. 전화번호·주민등록번호·이메일·URL·@핸들·2자리 이상 숫자(나이·연도)·
시·도/시·군·구 이름은 지운 뒤 남깁니다. 검색 결과와 입력 프로필은 저장하지 않습니다.</p>

<h2>문의할 때 남기는 연락처</h2>
<ul>
  <li>세무·노무사 리포트·대량 매칭 문의(<code>POST /v1/inquiry</code>)에 적은 연락처는 <strong>그 문의에
  회신하는 용도로만</strong> 씁니다.</li>
  <li>보관 기간은 접수일로부터 <strong>180일</strong>이며, 기간이 지나면 지웁니다. 통계·공개 화면에는 넣지 않습니다.</li>
</ul>

<h2>삭제 요청</h2>
<ul>
  <li>문의로 남긴 연락처나 0건 검색어 기록의 삭제를 원하시면 서비스 내 문의(<code>POST /v1/inquiry</code>)에
  <strong>삭제 요청</strong>이라고 적어 보내 주세요. 확인 후 지체 없이 지웁니다.</li>
  <li>공개 저장소 <a href="{REPO_ISSUES}" target="_blank" rel="noopener noreferrer">이슈</a>로도 요청할 수 있습니다.
  이슈는 공개되므로 개인정보는 적지 마세요.</li>
</ul>

<h2>제3자 제공·처리 위탁</h2>
<ul>
  <li>수집한 정보를 제3자에게 판매·제공하지 않습니다. 국외 이전도 하지 않습니다.</li>
  <li>서비스는 호스팅 사업자 위에서 동작합니다. 호스팅 사업자의 플랫폼 접속 로그는 이 서비스 코드가
  저장하는 정보와 별개로 그 사업자 정책을 따릅니다.</li>
</ul>

<h2>공공데이터에 포함된 정보</h2>
<p>보조금24·K-Startup·기업마당·지자체 포털 공고에는 담당 부서·문의처가 들어 있습니다. GRNT는 이를
제도 안내로만 보여 주고 별도로 수집하지 않습니다.</p>

<h2>문의</h2>
<p>개인정보 처리에 관한 문의는 서비스 내 문의 접수 또는 공개 저장소
<a href="{REPO_ISSUES}" target="_blank" rel="noopener noreferrer">이슈</a>로 받습니다. 운영자 개인 연락처는
공개하지 않습니다(익명 운영 원칙).</p>
"""
    return _page("privacy", body, base)


def _terms(base: Optional[str] = None) -> str:
    body = f"""
<p>GRNT는 개인·창업 지원금을 <strong>미리 확인해 보는 무료 사전 점검 도구</strong>입니다. 신청 전에
아래 범위와 한계를 확인해 주세요.</p>

<h2>서비스가 하는 일</h2>
<ul>
  <li>나이·지역·소득구간·상황, 또는 사업자 조건을 넣으면 공개 자격 코드와 공고 신청자격을 대조해
  <strong>후보와 근거</strong>를 정리합니다.</li>
  <li>신청 시기(마감 임박)·지역별·주제별 목록과, 결과가 왜 그렇게 나왔는지(판정 사유)를 함께 보여 줍니다.</li>
</ul>

<h2>서비스가 하지 않는 일</h2>
<ul>
  <li>수급·선정 여부를 확정하지 않습니다. 판정은 사전 점검이며, 실제 결정은 소관기관 심사입니다.</li>
  <li>정부·지자체의 공식 신청 대행이 아닙니다. 신청서 작성·접수·서류 검토를 대신하지 않습니다.</li>
  <li>세무·노무·법률 자문을 대신하지 않습니다. 사업자 판단은 세무사·노무사·변호사 등 전문가와 상의하세요.</li>
</ul>

<h2>데이터와 정확성</h2>
<ul>
  <li>공공데이터포털 보조금24, 창업진흥원 K-Startup, 중소벤처기업부 기업마당, 지자체 자체 복지포털을
  활용합니다. 원본을 그대로 중계하지 않고 결합·정규화한 판정을 제공합니다.</li>
  <li>공고는 기간·예산·자격이 수시로 바뀌고, 갱신이 늦거나 지역 포털이 개편될 수 있습니다.
  지난 공고는 수집에서 제외하지만 누락·오기가 있을 수 있습니다.</li>
  <li>지자체 자체 포털 중 연동하지 못한 곳은 화면에 사실대로 표시합니다.</li>
</ul>

<h2>이용자의 책임</h2>
<ul>
  <li>입력한 조건의 정확성은 이용자에게 있습니다. 결과는 입력한 조건이 맞다는 전제로 계산됩니다.</li>
  <li>자동화된 과도한 호출, 서비스 우회·부하 유발, 결과를 확정 판정처럼 재판매·재게시하는 행위는
  제한될 수 있습니다.</li>
  <li>거래처 일괄 매칭(CSV)을 쓸 때는 상호·사업자번호·대표자·연락처 열을 비우고 내부 참조값만 보내야
  하며, 그 책임은 이용자에게 있습니다.</li>
</ul>

<h2>책임의 한계</h2>
<ul>
  <li>서비스는 '있는 그대로' 제공됩니다. 무료 베타이며 중단·변경·오류가 있을 수 있습니다.</li>
  <li>서비스 이용으로 발생한 신청 기회 상실·지원금 미수령·판단 착오 등 결과에 대해, 고의 또는 중대한
  과실이 없는 한 책임지지 않습니다.</li>
</ul>

<h2>약관의 변경</h2>
<p>내용이 바뀌면 이 페이지의 시행일과 버전을 갱신합니다. 중요한 변경은 서비스 화면에서 알립니다.</p>

<h2>준거법</h2>
<p>이 약관은 대한민국 법에 따릅니다.</p>
"""
    return _page("terms", body, base)


def _about(base: Optional[str] = None) -> str:
    siblings = "".join(
        f'<li><a href="{url}" target="_blank" rel="noopener noreferrer"><strong>{name}</strong></a> — {desc}</li>'
        for url, name, desc in SIBLINGS
    )
    body = f"""
<p><strong>GRNT</strong>는 "내가 받을 수 있는 지원금이 무엇인지"를 조건 몇 개로 30초 안에 정리해 주는
무료 사전 점검 서비스입니다. {TAGLINE}</p>

<h2>누구를 위한 서비스인가</h2>
<ul>
  <li>청년·신혼부부·한부모·다자녀·어르신 등 개인·가구 지원금을 찾는 사람</li>
  <li>예비창업자·소상공인·중소기업으로 지원사업을 찾는 사람</li>
  <li>거래처 수십~수백 곳의 지원 가능성을 한 번에 확인하려는 세무·노무 사무소(익명 일괄 매칭)</li>
</ul>

<h2>무엇을 답하나</h2>
<ul>
  <li>개인 트랙: 보조금24 자격 코드(JA)로 판정하는 복지·주거·출산·교육 지원</li>
  <li>창업·기업 트랙: K-Startup·기업마당 공고의 신청자격(업력·연령·지역·대상·업종)으로 판정</li>
  <li>마감 임박 달력, 시·도별·주제별 모아보기, 판정 사유와 근거 공고 링크</li>
</ul>

<h2>판정 4단계</h2>
<p><code>eligible_likely</code> 받을 가능성 높음 · <code>check_needed</code> 조건 확인 필요 ·
<code>insufficient_info</code> 정보 부족 · <code>ineligible</code> 해당 없음. 넷 다 사전 점검이며 최종 선정은
소관기관이 결정합니다.</p>

<h2>데이터 출처</h2>
<p>공공데이터포털 보조금24(정부24), 창업진흥원 K-Startup, 중소벤처기업부 기업마당, 그리고 부평복지ON·
인천 맞춤형수혜·서울 WIS·경기민원24·세종·브라보 등 지자체 자체 복지포털입니다.</p>

<h2>쓰는 방법</h2>
<ul>
  <li>사람: <a href="/">지원금 판정</a>에서 조건을 고르고 결과를 봅니다.</li>
  <li>검색·AI: <a href="/s/">주제별</a>·<a href="/regions/">시·도별</a>·<a href="/guides/">자주 묻는 질문</a>이
  정적 HTML로 열려 있습니다.</li>
  <li>개발자: MCP(<code>POST /mcp</code>) · REST(<code>POST /v1/tools/&lt;tool&gt;</code>)로 같은 판정을 받습니다.</li>
</ul>

<h2>같이 쓰는 서비스</h2>
<ul>{siblings}</ul>
<p>세 서비스는 같은 원칙으로 운영합니다 — 무료, 로그인 없음, 익명 운영, 근거 표시,
확정 판정 대신 확인 항목 제시.</p>

<h2>만든 방식과 한계</h2>
<p>표준 라이브러리만으로 동작하고, 카탈로그는 SQLite로 색인해 빠르게 검색합니다. 무료 베타라
시·군·구 단위 커버리지에 빈 곳이 있을 수 있고, 그런 경우 화면에 사실대로 표시합니다.</p>
"""
    return _page("about", body, base)


_RENDERERS = {"privacy": _privacy, "terms": _terms, "about": _about}


def is_page(path: str) -> bool:
    """`/privacy`·`/privacy/` 처럼 이 모듈이 답하는 주소인지."""
    return str(path or "").strip("/").lower() in _RENDERERS


def render(path: str, base: Optional[str] = None) -> Optional[str]:
    """슬러그(`privacy`·`terms`·`about`) 또는 경로로 HTML 을 만든다. 모르는 주소면 None."""
    slug = str(path or "").strip("/").lower()
    renderer = _RENDERERS.get(slug)
    return renderer(base) if renderer else None


def footer_links_html() -> str:
    """홈 푸터에 붙는 고지 링크 묶음."""
    items = " · ".join(f'<a href="/{slug}">{title}</a>' for slug, title in TITLES.items())
    return f'<span class="legal-links">{items}</span>'
