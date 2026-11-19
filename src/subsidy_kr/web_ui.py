"""사람용 단일 페이지 웹 UI (`GET /`) — 로그인 없이 30초 조건 선택.

원칙
----
1. **외부 의존 0**: CSS·JS·아이콘 전부 인라인(CDN·폰트·트래커 없음). CSP가 외부 로드를 막는다.
2. **개인정보 최소**: 주민등록번호·이름·연락처를 받지 않는다. 입력값은 요청 1회로만 쓰고
   서버에 저장하지 않는다(카운터에도 남기지 않음).
3. **단정 금지**: 판정 문구는 "가능성/확인 필요/정보 부족/해당 없음" 네 가지로만 쓴다.
4. **근거 우선**: 카드마다 사유·선정기준 원문·문의처·기준일·출처를 접어서 함께 보여 준다.
5. **두 트랙**: '개인·가구'와 '창업·소상공인·기업'을 한 화면에서 전환한다.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from . import conditions, programs, regions, site_verification
from .version import __version__

SERVICE_NAME = "GRNT"
SERVICE_TITLE_KO = "개인·창업 통합 지원금 판정기"
SERVICE_TAGLINE = "Grants, simplified."
SERVICE_SUBTITLE_EN = "KOREA GRANT & SUBSIDY INTELLIGENCE"

BASE_CSS = """
:root{
  --bg:#f5f7fb; --card:#ffffff; --ink:#12161f; --ink-soft:#525c6d; --line:#dde3ec;
  --brand:#1c5bd8; --brand-soft:#e8effc; --brand-ink:#12327a;
  --ok:#0d7a4a; --ok-soft:#e2f5ea; --warn:#8a5300; --warn-soft:#fdf0d8;
  --info:#1e5d91; --info-soft:#e6f0f9; --danger:#9c2b26; --danger-soft:#fbe9e7;
  --radius:14px;
}
@media (prefers-color-scheme: dark){
  :root{--bg:#0d1117; --card:#161b22; --ink:#e9eef6; --ink-soft:#a9b3c3; --line:#293240;
    --brand:#7fa6ff; --brand-soft:#18243d; --brand-ink:#cfe0ff;
    --ok:#5fd39a; --ok-soft:#12291f; --warn:#f0bb63; --warn-soft:#2a2113;
    --info:#8ab8e8; --info-soft:#132436; --danger:#f0998f; --danger-soft:#2c1615;}
}
*{box-sizing:border-box}
[hidden]{display:none !important}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-size:16px;line-height:1.55;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif}
a{color:var(--brand);text-underline-offset:2px}
.wrap{max-width:940px;margin:0 auto;padding:0 16px 72px}
header.top{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;
  padding:22px 0 16px;border-bottom:1px solid var(--line)}
.brand{display:flex;gap:12px;align-items:center;min-width:0}
.mark{width:40px;height:40px;border-radius:12px;background:var(--brand);color:#fff;display:flex;
  align-items:center;justify-content:center;font-weight:800;font-size:19px;flex:0 0 auto}
.brand h1{margin:0;font-size:18px;letter-spacing:-.2px}
.brand p{margin:2px 0 0;font-size:12.5px;color:var(--ink-soft)}
.brand p.en{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase}
.pill{font-size:11.5px;font-weight:700;padding:4px 10px;border-radius:999px;
  background:var(--brand-soft);color:var(--brand-ink);white-space:nowrap}
.pill.ghost{background:transparent;color:var(--ink-soft);border:1px solid var(--line)}
.notice{margin:16px 0 0;padding:11px 14px;border-radius:11px;background:var(--warn-soft);
  color:var(--warn);font-size:13px;border:1px solid transparent}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:20px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.card+.card{margin-top:14px}
h2{font-size:17px;margin:0 0 6px;letter-spacing:-.2px}
h3{font-size:14.5px;margin:0 0 8px}
.sub{margin:0 0 16px;color:var(--ink-soft);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.grid .full{grid-column:1/-1}
@media (max-width:680px){.grid{grid-template-columns:1fr}}
.field{display:block}
.field>.lab{display:block;font-size:13px;font-weight:700;margin-bottom:5px}
.field>.lab .opt{font-weight:500;color:var(--ink-soft);font-size:11.5px;margin-left:4px}
input[type=text],input[type=number],select{width:100%;font:inherit;font-size:15px;color:var(--ink);
  background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:11px 12px;appearance:none}
select{cursor:pointer}
input:focus,select:focus{outline:2px solid var(--brand);outline-offset:1px;border-color:transparent}
.hint{display:block;margin-top:5px;font-size:11.5px;color:var(--ink-soft)}
.seg{display:flex;gap:6px;flex-wrap:wrap}
.seg label{position:relative;flex:1 1 0;min-width:76px}
.seg input{position:absolute;opacity:0;width:1px;height:1px}
.seg span{display:block;text-align:center;cursor:pointer;font-size:13.5px;font-weight:700;
  padding:10px 6px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink-soft)}
.seg input:checked+span{background:var(--brand-soft);border-color:var(--brand);color:var(--brand-ink)}
.seg input:focus-visible+span{outline:2px solid var(--brand);outline-offset:2px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chips label{position:relative}
.chips input{position:absolute;opacity:0;width:1px;height:1px}
.chips span{display:inline-block;cursor:pointer;font-size:13px;font-weight:600;padding:9px 12px;
  border:1px solid var(--line);border-radius:999px;background:var(--bg);color:var(--ink-soft)}
.chips input:checked+span{background:var(--brand-soft);border-color:var(--brand);color:var(--brand-ink)}
.chips input:focus-visible+span{outline:2px solid var(--brand);outline-offset:2px}
.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:18px}
button.primary{font:inherit;font-size:15.5px;font-weight:800;color:#fff;background:var(--brand);
  border:0;border-radius:12px;padding:14px 24px;cursor:pointer;min-height:48px}
button.primary:disabled{opacity:.6;cursor:progress}
button.ghost{font:inherit;font-size:14px;font-weight:600;color:var(--ink-soft);background:transparent;
  border:1px solid var(--line);border-radius:11px;padding:12px 16px;cursor:pointer;min-height:44px}
.status{margin-top:14px;font-size:13.5px;color:var(--ink-soft);min-height:20px}
.empty{padding:26px 6px;text-align:center;color:var(--ink-soft);font-size:14px}
.result{border:1px solid var(--line);border-radius:12px;padding:15px 16px;background:var(--card)}
.result+.result{margin-top:10px}
.result-head{display:flex;gap:10px;justify-content:space-between;align-items:flex-start;flex-wrap:wrap}
.result h4{margin:0;font-size:15.5px;letter-spacing:-.2px}
.badge{font-size:11.5px;font-weight:800;padding:4px 9px;border-radius:999px;white-space:nowrap}
.badge.eligible_likely{background:var(--ok-soft);color:var(--ok)}
.badge.check_needed{background:var(--warn-soft);color:var(--warn)}
.badge.insufficient_info{background:var(--info-soft);color:var(--info)}
.badge.ineligible{background:var(--danger-soft);color:var(--danger)}
.meta{margin:6px 0 0;font-size:12.5px;color:var(--ink-soft)}
.amount{margin:10px 0 0;font-size:13.5px;font-weight:500;line-height:1.5;color:var(--ink);
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.amount.expanded{display:block;-webkit-line-clamp:unset;overflow:visible}
.more-btn{margin-top:4px;padding:0;border:0;background:none;color:var(--brand);font:inherit;
  font-size:12.5px;font-weight:700;cursor:pointer}
.card-links{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
.card-links a.btn-link{font-size:12.5px;font-weight:700;padding:6px 11px;border-radius:8px;
  background:var(--brand-soft);color:var(--brand-ink);text-decoration:none}
.card-links a.btn-link:hover{text-decoration:underline}
.deadline-pill{font-size:11.5px;font-weight:700;padding:4px 9px;border-radius:999px;
  background:var(--bg);color:var(--ink-soft);border:1px solid var(--line)}
.deadline-pill.soon{background:var(--warn-soft);color:var(--warn);border-color:transparent}
.kw-chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.kw-chips button{font:inherit;font-size:12px;font-weight:600;padding:5px 10px;border-radius:999px;
  background:var(--bg);border:1px solid var(--line);color:var(--ink-soft);cursor:pointer}
.kw-chips button:hover{border-color:var(--brand);color:var(--brand-ink)}
.why{margin:10px 0 0;font-size:13px;color:var(--ink-soft)}
.why ul{margin:4px 0 0;padding-left:18px}
.ask{margin:10px 0 0;padding:10px 12px;border-radius:10px;background:var(--info-soft);color:var(--info);font-size:13px}
.ask ul{margin:4px 0 0;padding-left:18px}
details{margin-top:10px;font-size:13px;color:var(--ink-soft)}
details summary{cursor:pointer;font-weight:700;color:var(--brand-ink)}
details p{margin:6px 0 0}
.links{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;font-size:13px}
.foot{margin-top:22px;font-size:12px;color:var(--ink-soft);line-height:1.7}
.foot a{color:var(--ink-soft)}
.counts{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
.counts button{font-size:12.5px;font-weight:700;padding:6px 12px;border-radius:999px;
  background:var(--bg);border:1px solid var(--line);color:var(--ink-soft);cursor:pointer;font-family:inherit}
.counts button.active{background:var(--brand);border-color:var(--brand);color:#fff}
.counts button.active{background:var(--brand);border-color:var(--brand);color:#fff}
.track{display:flex;gap:8px;margin:0 0 16px;flex-wrap:wrap}
.track label{position:relative;flex:1 1 200px}
.track input{position:absolute;opacity:0;width:1px;height:1px}
.track span{display:block;cursor:pointer;padding:13px 14px;border:1px solid var(--line);
  border-radius:12px;background:var(--bg);color:var(--ink-soft);font-weight:700;font-size:14px}
.track span small{display:block;font-weight:500;font-size:11.5px;margin-top:2px}
.track input:checked+span{background:var(--brand-soft);border-color:var(--brand);color:var(--brand-ink)}
.track input:focus-visible+span{outline:2px solid var(--brand);outline-offset:2px}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:3px 8px;border-radius:999px;
  background:var(--bg);border:1px solid var(--line);color:var(--ink-soft);margin-left:6px}
.origin{font-size:11.5px;color:var(--ink-soft);margin-top:8px}
"""


def _sido_options() -> str:
    return "".join(f'<option value="{name}">{name}</option>' for name in regions.sido_names())


def _sigungu_map() -> str:
    data = {sido: [name for _code, name in rows]
            for sido, rows in regions.SIGUNGU_BY_SIDO.items()}
    return json.dumps(data, ensure_ascii=False)


def _situation_chips() -> str:
    keys = ["pregnant", "birth", "parenting", "multi_child", "no_home", "single_household",
            "single_parent", "jobseeker", "worker", "college_student", "disabled",
            "small_business", "farmer", "multicultural", "veteran"]
    out = []
    for key in keys:
        spec = conditions.SITUATIONS[key]
        out.append(
            f'<label><input type="checkbox" name="situation" value="{key}">'
            f'<span>{spec["label_ko"]}</span></label>'
        )
    return "".join(out)


def _income_options() -> str:
    labels = {
        "JA0201": "중위소득 50% 이하",
        "JA0202": "51~75%",
        "JA0203": "76~100%",
        "JA0204": "101~200%",
        "JA0205": "200% 초과",
    }
    return "".join(f'<option value="{code}">{label}</option>' for code, label in labels.items())


def _track_switch() -> str:
    return (
        '<div class="track" role="radiogroup" aria-label="지원금 종류 선택">'
        '<label><input type="radio" name="track" value="personal" checked>'
        '<span>개인·가구<small>정부·지자체 복지·주거·청년 지원금</small></span></label>'
        '<label><input type="radio" name="track" value="business">'
        '<span>창업·소상공인·기업<small>예비창업·업력·소상공인·중소기업 지원사업</small></span></label>'
        '</div>'
    )


def _entity_options() -> str:
    return "".join(
        f'<option value="{key}">{programs.ENTITY_LABELS[key]}</option>'
        for key in ("sole_proprietor", "small_business", "sme", "corporate", "venture",
                    "social_enterprise")
    )


def _industry_options() -> str:
    return "".join(
        f'<option value="{key}">{label}</option>'
        for key, label in programs.INDUSTRY_LABELS.items()
    )


def render_page(catalog_meta: Optional[Dict[str, Any]] = None) -> str:
    meta = catalog_meta or {}
    is_sample = str(meta.get("catalog_state") or "sample") != "synced"
    stats = meta.get("stats") or {}
    count = int(stats.get("services") or 0)
    personal = int(stats.get("personal") or 0)
    business = int(stats.get("business") or 0)
    generated = str(meta.get("generated_on") or "")[:10]
    notice = (
        '<div class="notice" role="status"><strong>지금은 샘플 데이터로 동작합니다.</strong> '
        "구조·판정 규격은 실제 API와 같지만 금액·기한은 예시값입니다. "
        "공공데이터포털 15113968·15125364·15157820 승인 후 "
        "<code>python -m subsidy_kr.sync_gov24 --sources all</code> 을 실행하면 실데이터로 바뀝니다.</div>"
        if is_sample else
        f'<div class="notice" role="status" style="background:var(--ok-soft);color:var(--ok)">'
        f"실데이터 기준일 {generated or '미상'} · 제도 {count:,}건"
        f"(개인 {personal:,} · 창업·기업 {business:,}) · "
        "지자체 선정기준 공백은 원본 그대로 두고 &lsquo;확인 필요&rsquo;로 표시합니다.</div>"
    )
    return PAGE_TEMPLATE.format(
        service_name=SERVICE_NAME,
        title=SERVICE_TITLE_KO,
        tagline=SERVICE_TAGLINE,
        subtitle_en=SERVICE_SUBTITLE_EN,
        version=__version__,
        css=BASE_CSS,
        sido_options=_sido_options(),
        sigungu_map=_sigungu_map(),
        chips=_situation_chips(),
        income_options=_income_options(),
        track_switch=_track_switch(),
        entity_options=_entity_options(),
        industry_options=_industry_options(),
        notice=notice,
        count=count,
        generated=generated,
        verification=site_verification.meta_tags(),
    )


PAGE_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{service_name} · {title}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%231c5bd8'/%3E%3Ctext x='16' y='23' font-size='16' font-weight='700' fill='white' text-anchor='middle' font-family='sans-serif'%3EG%3C/text%3E%3C/svg%3E">
<meta name="description" content="나이·거주지·소득구간·상황, 또는 사업자 조건(예비창업·업력·소상공인·중소기업)만 고르면 개인 지원금과 창업·기업 지원사업 후보와 근거를 30초 안에 정리합니다. 로그인 없음, 주민등록번호 없음, 서버 저장 없음. 확정 판정이 아닌 사전 점검입니다.">
<meta property="og:type" content="website">
<meta property="og:title" content="GRNT — 개인·창업 통합 지원금 판정기">
<meta property="og:description" content="Grants, simplified. 개인 복지 지원금과 창업·소상공인·기업 지원사업을 한 화면에서 조건별로 판정합니다. 로그인 없이 30초.">
<meta property="og:locale" content="ko_KR">
<meta name="twitter:card" content="summary">
<meta name="robots" content="index,follow">
{verification}<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"WebApplication","name":"{service_name}",
"applicationCategory":"FinanceApplication","operatingSystem":"Web","inLanguage":"ko-KR",
"isAccessibleForFree":true,"offers":{{"@type":"Offer","price":"0","priceCurrency":"KRW"}},
"description":"한국 개인·창업 지원금 자격 사전 점검. 공개 자격 코드와 공고 신청자격 기반 결정론 판정, 로그인 없음."}}
</script>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand">
      <div class="mark" aria-hidden="true">G</div>
      <div>
        <h1>{service_name} · {title}</h1>
        <p class="en">{subtitle_en}</p>
        <p>{tagline} 로그인·주민등록번호 없이 내 조건만 확인합니다.</p>
      </div>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <span class="pill">무료</span>
      <span class="pill ghost">v{version}</span>
    </div>
  </header>
  {notice}

  <main>
    <section class="card" style="margin-top:16px">
      <h2>내 조건 입력</h2>
      <p class="sub">아는 것만 채우면 됩니다. 비워 둔 항목은 &lsquo;정보 부족&rsquo;으로 정직하게 표시하고,
      무엇을 더 넣어야 판정되는지 알려 드립니다.</p>
      <form id="check" autocomplete="off">
        {track_switch}
        <div class="grid">
          <label class="field">
            <span class="lab">지역(거주지 / 사업장) <span class="opt">선택</span></span>
            <select id="sido" name="sido">
              <option value="">선택 안 함</option>
              {sido_options}
            </select>
          </label>
          <label class="field">
            <span class="lab">시·군·구 <span class="opt">선택</span></span>
            <select id="sigungu" name="sigungu"><option value="">선택 안 함</option></select>
            <span class="hint">지자체 제도는 시·군·구까지 있어야 정확합니다.</span>
          </label>
          <label class="field">
            <span class="lab">출생연도</span>
            <input type="number" id="birth_year" name="birth_year" inputmode="numeric"
                   min="1900" max="2026" step="1" placeholder="예: 1992">
            <span class="hint">만 나이는 연도 차이로 계산합니다(생일 전이면 1살 차이).</span>
          </label>
          <div class="field">
            <span class="lab">성별 <span class="opt">성별 제한 사업 판정용</span></span>
            <div class="seg">
              <label><input type="radio" name="sex" value="male"><span>남성</span></label>
              <label><input type="radio" name="sex" value="female"><span>여성</span></label>
            </div>
          </div>
        </div>

        <div class="grid" id="personal-fields">
          <label class="field">
            <span class="lab">가구원 수 <span class="opt">선택</span></span>
            <select id="household_size" name="household_size">
              <option value="">선택 안 함</option>
              <option>1</option><option>2</option><option>3</option><option>4</option>
              <option>5</option><option>6</option><option>7</option><option>8</option>
            </select>
          </label>
          <label class="field">
            <span class="lab">가구 소득 (기준 중위소득)</span>
            <select id="income_band" name="income_band">
              <option value="">모르겠음 / 선택 안 함</option>
              {income_options}
            </select>
            <span class="hint">소득구간 조건이 있는 제도만 이 값으로 판정합니다.</span>
          </label>
          <div class="field full">
            <span class="lab">해당하는 상황 <span class="opt">복수 선택</span></span>
            <div class="chips" id="chips">{chips}</div>
            <span class="hint">아무것도 고르지 않으면 &lsquo;해당 없음&rsquo;으로 판정합니다. 모르면 입력하지 말고
            아래 버튼만 눌러도 됩니다(그때는 &lsquo;정보 부족&rsquo;으로 답합니다).</span>
          </div>
          <label class="field full">
            <span class="lab">자녀 출생연도 <span class="opt">선택 · 아동 대상 제도용</span></span>
            <input type="text" id="children_years" name="children_years"
                   placeholder="예: 2024, 2026 (쉼표로 구분)">
          </label>
        </div>

        <div class="grid" id="biz-fields" hidden>
          <label class="field">
            <span class="lab">창업 상태</span>
            <select id="biz_status" name="biz_status">
              <option value="">선택 안 함</option>
              <option value="pre">예비창업자(사업자등록 전)</option>
              <option value="operating">사업자등록 후 운영 중</option>
            </select>
            <span class="hint">공고마다 예비창업자만/사업자만/둘 다 받습니다.</span>
          </label>
          <label class="field">
            <span class="lab">업력 <span class="opt">운영 중일 때</span></span>
            <input type="number" id="biz_years" name="biz_years" inputmode="numeric"
                   min="0" max="60" step="1" placeholder="예: 2">
            <span class="hint">창업 후 경과 연수입니다. 모르면 비워 두세요.</span>
          </label>
          <label class="field">
            <span class="lab">기업 규모 · 형태</span>
            <select id="biz_entity" name="biz_entity">
              <option value="">선택 안 함</option>
              {entity_options}
            </select>
            <span class="hint">개인사업자·소상공인은 중소기업 요건도 함께 충족합니다.</span>
          </label>
          <label class="field">
            <span class="lab">업종 <span class="opt">업종 제한 사업 판정용</span></span>
            <select id="biz_industry" name="biz_industry">
              <option value="">선택 안 함</option>
              {industry_options}
            </select>
          </label>
        </div>

        <div style="margin-top:14px">
          <label class="field">
            <span class="lab">키워드 필터 <span class="opt">선택 · 찾고 싶은 지원금만 좁혀 보기</span></span>
            <input type="text" id="keyword" name="keyword" placeholder="예: 출산, 전세, 청년, 육아, 소상공인">
          </label>
          <div class="kw-chips" id="kw-chips">
            <button type="button" data-kw="출산">출산·임신</button>
            <button type="button" data-kw="전세">전세·주거</button>
            <button type="button" data-kw="청년">청년</button>
            <button type="button" data-kw="육아">육아·돌봄</button>
            <button type="button" data-kw="소상공인">소상공인</button>
          </div>
        </div>

        <div style="margin-top:12px">
          <label style="display:inline-flex;align-items:center;gap:6px;font-size:13.5px;color:var(--ink-soft);cursor:pointer">
            <input type="checkbox" id="include_closed"> 지난(마감) 공고도 포함해서 보기
          </label>
        </div>

        <div class="actions">
          <button class="primary" type="submit" id="run">내 지원금 확인하기</button>
          <button class="ghost" type="button" id="fill-demo">예시로 채워 보기</button>
        </div>
        <div class="status" id="status" role="status" aria-live="polite"></div>
      </form>
    </section>

    <section class="card" id="results-card" hidden>
      <h2>판정 결과</h2>
      <p class="sub" id="results-sub"></p>
      <div class="counts" id="counts"></div>
      <div id="results"></div>
      <p class="foot" id="results-foot"></p>
    </section>

    <section class="card">
      <h2>이 판정은 어떻게 하나요</h2>
      <p class="sub"><strong>개인·가구</strong>는 정부24 <strong>보조금24</strong>가 제도마다 공개한
      <strong>자격 코드</strong>(연령·성별·중위소득 구간·생애·가구·직업)를 제 조건과 대조합니다.
      <strong>창업·소상공인·기업</strong>은 <strong>K-Startup</strong>·<strong>기업마당</strong> 공고의
      구조화된 신청자격(업력·연령·지역·대상·성별)을 대조합니다. AI가 문장을 읽고 추측하지 않습니다.</p>
      <div class="links">
        <a href="/s/">주제별 지원금 모아보기</a>
        <a href="/v1/meta">서비스·데이터 상태</a>
        <a href="/v1/stats">익명 사용 통계</a>
        <a href="/llms.txt">AI·개발자용 안내</a>
      </div>
    </section>

    <p class="foot">
      <strong>개인정보</strong> — 이름·주민등록번호·전화번호를 받지 않습니다. 입력한 나이·지역·소득구간·
      사업자 조건은 판정 계산에만 쓰고 서버에 저장하지 않습니다(브라우저 저장소도 쓰지 않음). 서버에는
      툴 이름과 판정 등급의 <em>익명 일별 횟수</em>만 남습니다.<br>
      <strong>한계</strong> — 공개 데이터 기반 사전 점검이며 수급·선정 자격을 확정하지 않습니다.
      재산·거주기간 등 코드로 표현되지 않은 요건과 지자체 원본 공백, 공고문의 서술형 요건은
      &lsquo;확인 필요&rsquo;로 표시합니다. 창업·기업 사업의 &lsquo;받을 가능성 높음&rsquo;은 신청자격
      충족을 뜻하고, 선정은 평가·경쟁으로 결정됩니다. 최종 판단은 소관기관 심사입니다.
    </p>
  </main>
</div>
<script>
(function(){{
  var SIGUNGU = {sigungu_map};
  var sido = document.getElementById('sido');
  var sigungu = document.getElementById('sigungu');
  function resetSigungu(){{
    var list = SIGUNGU[sido.value] || [];
    sigungu.innerHTML = '<option value="">선택 안 함</option>';
    list.forEach(function(name){{
      var option = document.createElement('option');
      option.value = name; option.textContent = name;
      sigungu.appendChild(option);
    }});
  }}
  sido.addEventListener('change', resetSigungu);
  resetSigungu();

  function currentTrack(){{
    var picked = document.querySelector('input[name=track]:checked');
    return picked ? picked.value : 'personal';
  }}
  function applyTrack(){{
    var business = currentTrack() === 'business';
    document.getElementById('personal-fields').hidden = business;
    document.getElementById('biz-fields').hidden = !business;
  }}
  Array.prototype.slice.call(document.querySelectorAll('input[name=track]'))
    .forEach(function(input){{ input.addEventListener('change', applyTrack); }});
  applyTrack();

  function selectedSituations(){{
    return Array.prototype.slice.call(document.querySelectorAll('input[name=situation]:checked'))
      .map(function(input){{ return input.value; }});
  }}

  function buildProfile(){{
    var profile = {{}};
    var track = currentTrack();
    profile.track = track;
    if (document.getElementById('birth_year').value) {{
      profile.birth_year = parseInt(document.getElementById('birth_year').value, 10);
    }}
    var sex = document.querySelector('input[name=sex]:checked');
    if (sex) {{ profile.sex = sex.value; }}
    if (sido.value || sigungu.value) {{
      profile.region = {{ sido: sido.value, sigungu: sigungu.value }};
    }}
    if (track === 'business') {{
      var business = {{}};
      if (document.getElementById('biz_status').value) {{
        business.status = document.getElementById('biz_status').value;
      }}
      if (document.getElementById('biz_entity').value) {{
        business.entity = document.getElementById('biz_entity').value;
      }}
      if (document.getElementById('biz_years').value) {{
        business.years = parseFloat(document.getElementById('biz_years').value);
      }}
      if (document.getElementById('biz_industry').value) {{
        business.industry = document.getElementById('biz_industry').value;
      }}
      profile.business = business;
    }} else {{
      if (document.getElementById('household_size').value) {{
        profile.household_size = parseInt(document.getElementById('household_size').value, 10);
      }}
      if (document.getElementById('income_band').value) {{
        profile.income_band = document.getElementById('income_band').value;
      }}
      profile.situations = selectedSituations();
      var years = document.getElementById('children_years').value
        .split(/[,\\s]+/).filter(Boolean).map(function(value){{ return parseInt(value, 10); }})
        .filter(function(value){{ return value > 1900; }});
      if (years.length) {{ profile.children_years = years; }}
    }}
    return profile;
  }}

  function el(tag, className, text){{
    var node = document.createElement(tag);
    if (className) {{ node.className = className; }}
    if (text !== undefined) {{ node.textContent = text; }}
    return node;
  }}

  var activeFilter = 'all';
  var activeKind = 'all';
  var activeField = 'all';
  var lastData = null;

  function renderResults(data){{
    lastData = data;
    var result = data.result || {{}};
    var card = document.getElementById('results-card');
    var box = document.getElementById('results');
    var counts = document.getElementById('counts');
    box.innerHTML = ''; counts.innerHTML = '';
    card.hidden = false;

    var allRows = result.results || [];
    // 이전 동적 필터 바 정리
    document.querySelectorAll('.sub-bar-dyn').forEach(function(elNode){{ elNode.remove(); }});

    // 1단: 큰 분류 (지원금·바우처 vs 교육·건강·프로그램 vs 전체)
    var grantCnt = allRows.filter(function(r){{ return r.benefit_kind !== 'program'; }}).length;
    var progCnt = allRows.filter(function(r){{ return r.benefit_kind === 'program'; }}).length;
    if (activeKind === 'grant' && grantCnt === 0 && progCnt > 0) {{ activeKind = 'all'; }}
    var kindTabs = [
      ['grant', '지원금·바우처'],
      ['program', '교육·건강·프로그램'],
      ['all', '전체 보기']
    ];
    var kindCounts = {{ grant: grantCnt, program: progCnt, all: allRows.length }};
    kindTabs.forEach(function(pair){{
      var k = pair[0], label = pair[1];
      var kbtn = document.createElement('button');
      kbtn.type = 'button';
      kbtn.className = activeKind === k ? 'active' : '';
      kbtn.style.fontWeight = '600';
      kbtn.textContent = label + ' ' + kindCounts[k] + '건';
      kbtn.addEventListener('click', function(){{
        activeKind = k;
        activeField = 'all';
        activeFilter = 'all';
        renderResults(lastData);
      }});
      counts.appendChild(kbtn);
    }});

    // 현재 선택된 큰 분류에 해당하는 행들 기준으로 판정·분야 건수 계산
    var kindRows = allRows.filter(function(r){{
      if (activeKind === 'grant') return r.benefit_kind !== 'program';
      if (activeKind === 'program') return r.benefit_kind === 'program';
      return true;
    }});

    var labels = {{
      all: '전체 판정',
      eligible_likely: '받을 가능성 높음',
      check_needed: '조건 확인 필요',
      insufficient_info: '정보 부족'
    }};
    var rowCounts = {{all: kindRows.length, eligible_likely: 0, check_needed: 0, insufficient_info: 0}};
    kindRows.forEach(function(r){{
      var c = r.verdict && r.verdict.code;
      if (rowCounts[c] !== undefined) {{ rowCounts[c] += 1; }}
    }});
    var verdictBar = document.createElement('div');
    verdictBar.className = 'counts sub-bar-dyn';
    verdictBar.style.marginTop = '8px';
    Object.keys(labels).forEach(function(code){{
      var cnt = code === 'all' ? kindRows.length : (rowCounts[code] || 0);
      if (code !== 'all' && !cnt) return;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = activeFilter === code ? 'active' : '';
      btn.textContent = labels[code] + ' ' + cnt + '건';
      btn.addEventListener('click', function(){{
        activeFilter = code;
        renderResults(lastData);
      }});
      verdictBar.appendChild(btn);
    }});

    function fieldBucket(row){{
      var fl = String(row.field_label || row.field || '기타').trim();
      if (/주거|주택|전세|월세/.test(fl)) return '주거·주택';
      if (/보육|교육|아동|양육/.test(fl)) return '보육·교육';
      if (/고용|창업|사업화|정책자금|R&D|멘토링/.test(fl)) return '고용·창업·경제';
      if (/보건|의료|건강/.test(fl)) return '보건·의료';
      if (/문화|체육|관광|행사/.test(fl)) return '문화·여가';
      if (/농림|어업/.test(fl)) return '농림·어업';
      if (/생활|복지/.test(fl)) return '생활·복지';
      return '행정·기타';
    }}
    var fieldOrder = ['주거·주택', '보육·교육', '고용·창업·경제', '생활·복지', '보건·의료', '문화·여가', '농림·어업', '행정·기타'];
    var fieldCounts = {{}};
    kindRows.forEach(function(r){{
      var b = fieldBucket(r);
      fieldCounts[b] = (fieldCounts[b] || 0) + 1;
    }});
    var fieldBar = document.createElement('div');
    fieldBar.className = 'counts sub-bar-dyn';
    fieldBar.style.marginTop = '6px';
    var fAllBtn = document.createElement('button');
    fAllBtn.type = 'button';
    fAllBtn.className = activeField === 'all' ? 'active' : '';
    fAllBtn.textContent = '전체 분야 ' + kindRows.length + '건';
    fAllBtn.addEventListener('click', function(){{ activeField = 'all'; renderResults(lastData); }});
    fieldBar.appendChild(fAllBtn);
    fieldOrder.forEach(function(fb){{
      if (!fieldCounts[fb]) return;
      var fbBtn = document.createElement('button');
      fbBtn.type = 'button';
      fbBtn.className = activeField === fb ? 'active' : '';
      fbBtn.textContent = fb + ' ' + fieldCounts[fb] + '건';
      fbBtn.addEventListener('click', function(){{ activeField = fb; renderResults(lastData); }});
      fieldBar.appendChild(fbBtn);
    }});
    counts.parentNode.insertBefore(verdictBar, counts.nextSibling);
    counts.parentNode.insertBefore(fieldBar, verdictBar.nextSibling);

    var trackNote = result.track === 'business' ? '창업·기업 트랙' : '개인·가구 트랙';
    var hiddenNote = result.closed_hidden ? (' · 지난 공고 ' + result.closed_hidden + '건 제외') : '';
    document.getElementById('results-sub').textContent =
      trackNote + ' · 제도 ' + (result.scanned || 0) + '건을 대조했습니다' + hiddenNote + '. ' +
      '위 탭을 눌러 판정별로 골라 볼 수 있습니다.';

    var portalStatus = result.local_portal_status || null;
    if (portalStatus && portalStatus.supported === false && portalStatus.notice_ko) {{
      var notice = el('div', 'notice');
      notice.style.margin = '0 0 14px';
      notice.textContent = '구·군청 자체 공지 안내: ' + portalStatus.notice_ko;
      box.appendChild(notice);
    }}

    var rows = kindRows.filter(function(r){{
      if (activeField !== 'all' && fieldBucket(r) !== activeField) return false;
      if (activeFilter === 'all') return true;
      return r.verdict && r.verdict.code === activeFilter;
    }});
    if (!rows.length) {{
      box.appendChild(el('div', 'empty',
        activeFilter === 'all'
          ? '조건에 맞는 후보가 나오지 않았습니다. 지역·소득구간·상황 또는 사업자 조건을 바꿔 다시 시도해 보세요.'
          : '선택한 분류에 해당하는 상위 결과가 없습니다. 다른 탭을 누르거나 소득구간·상황 조건을 더 입력해 보세요.'));
    }}
    function buildCard(row){{
      var wrap = el('div', 'result');
      wrap.style.padding = '12px 14px';
      var head = el('div', 'result-head');
      head.style.cursor = 'pointer';
      var left = el('div');
      var title = el('h4');
      title.appendChild(document.createTextNode(row.name || ''));
      title.appendChild(el('span', 'tag', row.track === 'business' ? '창업·기업' : '개인·가구'));
      var deadlineInfo = (row.application || {{}}).deadline || {{}};
      var dLeft = deadlineInfo.days_left;
      if (dLeft !== null && dLeft !== undefined && dLeft >= 0 && dLeft <= 7) {{
        var dBadge = el('span', 'deadline-pill soon', 'D-' + dLeft + ' 마감임박');
        dBadge.style.marginLeft = '6px';
        title.appendChild(dBadge);
      }}
      left.appendChild(title);
      var metaParts = [
        row.agency || '',
        row.field_label || '',
        row.benefit_kind === 'program' ? '교육·건강·프로그램' : '지원금·혜택',
        (row.region && row.region.label ? row.region.label : '')
      ].filter(Boolean);
      var deadlineLabel = deadlineInfo.label_ko || (row.application || {{}}).deadline_text || '';
      if (deadlineLabel && !(dLeft !== null && dLeft !== undefined && dLeft >= 0 && dLeft <= 7)) {{
        metaParts.push(deadlineLabel);
      }}
      left.appendChild(el('p', 'meta', metaParts.join(' · ')));
      head.appendChild(left);
      head.appendChild(el('span', 'badge ' + row.verdict.code, row.verdict.label_ko));
      wrap.appendChild(head);

      var details = el('details');
      details.style.marginTop = '8px';
      details.appendChild(el('summary', null, '설명 · 판정 근거 · 신청 방법 보기'));
      head.addEventListener('click', function(){{ details.open = !details.open; }});

      if (row.business_summary_ko) {{
        details.appendChild(el('p', 'meta', '신청자격: ' + row.business_summary_ko));
      }}
      if (row.amount) {{
        var amt = el('p', 'amount', row.amount);
        amt.classList.add('expanded');
        amt.style.marginTop = '8px';
        details.appendChild(amt);
      }}

      if (row.online_url || row.detail_url) {{
        var quick = el('div', 'card-links');
        quick.style.marginTop = '8px';
        if (row.online_url) {{
          var onBtn = el('a', 'btn-link', '온라인 신청');
          onBtn.href = row.online_url; onBtn.target = '_blank'; onBtn.rel = 'noopener noreferrer';
          quick.appendChild(onBtn);
        }}
        if (row.detail_url) {{
          var detBtn = el('a', 'btn-link', '공고·상세 보기');
          detBtn.href = row.detail_url; detBtn.target = '_blank'; detBtn.rel = 'noopener noreferrer';
          quick.appendChild(detBtn);
        }}
        details.appendChild(quick);
      }}

      var why = el('div', 'why');
      why.appendChild(el('strong', null, '판정 근거'));
      var list = el('ul');
      (row.why || []).forEach(function(rule){{
        if (rule.state === 'pass' || rule.state === 'fail' || rule.state === 'unknown') {{
          list.appendChild(el('li', null, rule.reason_ko));
        }}
      }});
      why.appendChild(list);
      details.appendChild(why);

      var missing = row.missing_information || [];
      if (missing.length) {{
        var ask = el('div', 'ask');
        ask.appendChild(el('strong', null, '이걸 알려 주시면 더 정확히 판정합니다'));
        var ul = el('ul');
        missing.forEach(function(item){{ ul.appendChild(el('li', null, item.question_ko)); }});
        ask.appendChild(ul);
        details.appendChild(ask);
      }}

      var deadline = (row.application || {{}}).deadline || {{}};
      var lines = [
        '신청기한: ' + ((row.application || {{}}).deadline_text || deadline.label_ko || '미기재'),
        '신청방법: ' + ((row.application || {{}}).how || '미기재'),
        '문의처: ' + (row.contact || '미기재'),
        '데이터 기준일: ' + (row.source_updated_at || '미기재')
      ];
      if (row.criteria_excerpt) {{
        lines.push('선정기준(원문): ' + row.criteria_excerpt +
          (row.criteria_state === 'missing' ? ' — 원본에 선정기준이 비어 있습니다.' : ''));
      }}
      lines.forEach(function(line){{ details.appendChild(el('p', null, line)); }});
      if (row.criteria_flags && row.criteria_flags.length) {{
        details.appendChild(el('p', null, '원문에 함께 있는 요건: ' + row.criteria_flags.join(', ')));
      }}
      if (row.attribution_ko) {{
        details.appendChild(el('p', 'origin', row.attribution_ko));
      }}
      wrap.appendChild(details);
      return wrap;
    }}

    if (activeField === 'all' && rows.length > 0) {{
      var grouped = {{}};
      rows.forEach(function(r){{
        var b = fieldBucket(r);
        if (!grouped[b]) grouped[b] = [];
        grouped[b].push(r);
      }});
      fieldOrder.forEach(function(fb){{
        var list = grouped[fb];
        if (!list || !list.length) return;
        var sec = el('div', 'field-group');
        sec.style.margin = '14px 0 18px';
        var hdr = el('h3', null, fb + ' (' + list.length + '건)');
        hdr.style.cssText = 'font-size:15px;margin:0 0 8px;padding:6px 10px;background:#f3f4f6;border-radius:8px;display:flex;justify-content:space-between;align-items:center;';
        sec.appendChild(hdr);
        var PREVIEW = 5;
        list.slice(0, PREVIEW).forEach(function(r){{ sec.appendChild(buildCard(r)); }});
        if (list.length > PREVIEW) {{
          var extraWrap = el('div', null);
          extraWrap.style.display = 'none';
          list.slice(PREVIEW).forEach(function(r){{ extraWrap.appendChild(buildCard(r)); }});
          sec.appendChild(extraWrap);
          var moreG = el('button', 'btn-link', '+ ' + fb + ' 나머지 ' + (list.length - PREVIEW) + '건 더 보기');
          moreG.type = 'button';
          moreG.style.marginTop = '6px';
          moreG.addEventListener('click', function(){{
            var open = extraWrap.style.display !== 'none';
            extraWrap.style.display = open ? 'none' : 'block';
            moreG.textContent = open
              ? ('+ ' + fb + ' 나머지 ' + (list.length - PREVIEW) + '건 더 보기')
              : (fb + ' 접기');
          }});
          sec.appendChild(moreG);
        }}
        box.appendChild(sec);
      }});
    }} else {{
      rows.forEach(function(row){{ box.appendChild(buildCard(row)); }});
    }}

    var notes = (result.profile && result.profile.missing_core) || [];
    document.getElementById('results-foot').textContent = notes.length
      ? '추가로 알려 주시면 판정이 늘어납니다: ' + notes.map(function(item){{return item.question_ko;}}).join(' ')
      : (result.disclaimer_ko || '');
  }}

  var form = document.getElementById('check');
  var status = document.getElementById('status');
  form.addEventListener('submit', function(event){{
    event.preventDefault();
    var button = document.getElementById('run');
    button.disabled = true;
    status.textContent = '판정 중…';
    var includeClosedEl = document.getElementById('include_closed');
    var kwEl = document.getElementById('keyword');
    var payload = {{
      profile: buildProfile(),
      limit: 200,
      include_closed: !!(includeClosedEl && includeClosedEl.checked)
    }};
    if (kwEl && kwEl.value.trim()) {{
      payload.keyword = kwEl.value.trim();
    }}
    activeFilter = 'all';
    activeKind = 'grant';
    activeField = 'all';
    fetch('/v1/tools/search_subsidies', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload)
    }}).then(function(response){{
      if (!response.ok) {{ throw new Error('HTTP ' + response.status); }}
      return response.json();
    }}).then(function(data){{
      if (!data.ok) {{ throw new Error(data.message || data.error || 'error'); }}
      status.textContent = '';
      renderResults(data);
      document.getElementById('results-card').scrollIntoView({{behavior:'smooth', block:'start'}});
    }}).catch(function(error){{
      status.textContent = '조회에 실패했습니다(' + error.message + '). 잠시 뒤 다시 시도해 주세요.';
    }}).finally(function(){{
      button.disabled = false;
    }});
  }});

  Array.prototype.slice.call(document.querySelectorAll('#kw-chips button')).forEach(function(btn){{
    btn.addEventListener('click', function(){{
      var kwInput = document.getElementById('keyword');
      if (kwInput) {{
        kwInput.value = btn.getAttribute('data-kw') || '';
        form.dispatchEvent(new Event('submit', {{cancelable: true}}));
      }}
    }});
  }});

  document.getElementById('fill-demo').addEventListener('click', function(){{
    document.getElementById('birth_year').value = '1992';
    document.querySelector('input[name=sex][value=male]').checked = true;
    sido.value = '인천광역시'; resetSigungu(); sigungu.value = '서해구';
    if (currentTrack() === 'business') {{
      document.getElementById('biz_status').value = 'pre';
      document.getElementById('biz_entity').value = 'pre_startup';
      document.getElementById('biz_years').value = '';
    }} else {{
      document.getElementById('household_size').value = '2';
      document.getElementById('income_band').value = 'JA0203';
      ['no_home', 'worker', 'birth'].forEach(function(key){{
        var input = document.querySelector('input[name=situation][value="' + key + '"]');
        if (input) {{ input.checked = true; }}
      }});
    }}
  }});
}})();
</script>
</body>
</html>
"""




def region_payload() -> Dict[str, Any]:
    return {sido: [name for _code, name in rows]
            for sido, rows in regions.SIGUNGU_BY_SIDO.items()}
