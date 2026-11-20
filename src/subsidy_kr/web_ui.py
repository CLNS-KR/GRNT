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

from . import conditions, guides, programs, regions, site_verification
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
.report-table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:8px}
.report-table th,.report-table td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.report-table th{background:var(--bg);font-weight:700;white-space:nowrap;font-size:11.5px}
.report-table td.nowrap{white-space:nowrap}
.report-table td.soon{color:var(--warn);font-weight:800;background:var(--warn-soft)}
.report-table a{font-weight:700}
.report-sec{margin-top:18px}
.report-sec h3{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin:0 0 4px}
.report-sec h3 small{font-weight:500;color:var(--ink-soft);font-size:11.5px}
.report-actions{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}
.report-actions a,.report-actions button{font:inherit;font-size:13px;font-weight:700;padding:9px 14px;
  border-radius:10px;border:1px solid var(--line);background:var(--brand-soft);color:var(--brand-ink);
  text-decoration:none;cursor:pointer;min-height:40px;display:inline-flex;align-items:center}
.report-sum{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 4px}
.report-sum span{font-size:12.5px;font-weight:700;padding:5px 11px;border-radius:999px;
  background:var(--bg);border:1px solid var(--line);color:var(--ink-soft)}
.report-size{margin:12px 0 0;padding:11px 13px;border-radius:11px;background:var(--info-soft);color:var(--info);font-size:13px}
textarea{width:100%;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;
  line-height:1.6;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:10px;
  padding:11px 12px;resize:vertical;min-height:150px}
textarea:focus{outline:2px solid var(--brand);outline-offset:1px;border-color:transparent}
.anon{margin:10px 0 0;padding:10px 13px;border-radius:10px;background:var(--ok-soft);color:var(--ok);
  font-size:12.5px;line-height:1.6}
.batch-client{margin-top:8px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;
  background:var(--bg);font-size:13px}
.batch-client summary{cursor:pointer;font-weight:700;color:var(--ink)}
.batch-client p{margin:5px 0 0;font-size:12.5px;color:var(--ink-soft)}
.report-size ul{margin:6px 0 0;padding-left:18px}
.report-size li{margin:2px 0}
.guide-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:2px 20px;
  padding-left:18px;margin:8px 0 0;line-height:1.75;font-size:13.5px}
@media (max-width:680px){.guide-list{grid-template-columns:1fr}}
.answer{margin:14px 0 0;padding:14px 16px;border-radius:12px;background:var(--brand-soft);
  color:var(--brand-ink);font-size:15px;font-weight:600;line-height:1.65}
.answer b{display:block;font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--ink-soft);margin-bottom:4px;font-weight:800}
.checks{margin:8px 0 0;padding-left:20px;line-height:1.85;font-size:14px}
.checks li{margin:5px 0}
pre.code{margin:10px 0 0;padding:12px 14px;border-radius:10px;background:var(--bg);
  border:1px solid var(--line);overflow-x:auto;font-size:12.5px;line-height:1.6;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.crumb{margin:14px 0 0;font-size:12.5px;color:var(--ink-soft)}
.crumb a{color:var(--ink-soft)}
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
        '<label><input type="radio" name="track" value="agent">'
        '<span>사업자·대리인 리포트<small>세무·노무 담당자용 — 거래처 전달 표(CSV·인쇄)</small></span></label>'
        '</div>'
    )


def _agent_industry_options() -> str:
    """대표인 리포트용 업종 선택지(작업 중인 별칭 기준)."""
    order = ("manufacturing", "retail", "food", "ict", "service", "construction",
             "logistics", "agri", "education", "health", "culture", "energy", "finance", "etc")
    options = [f'<option value="{slug}">{programs.INDUSTRY_LABELS[slug]}</option>'
               for slug in order if slug in programs.INDUSTRY_LABELS]
    options.append('<option value="창업">예비창업자(업종 미정)</option>')
    return "".join(options)


def _interest_checks() -> str:
    labels = {
        "small_business": "소상공인",
        "sme": "중소기업",
        "labor": "고용·노무",
        "finance_tax": "정책자금·세제",
    }
    return "".join(
        f'<label><input type="checkbox" name="interest" value="{key}">'
        f'<span>{label}</span></label>'
        for key, label in labels.items()
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
        agent_industry_options=_agent_industry_options(),
        interest_checks=_interest_checks(),
        notice=notice,
        count=count,
        generated=generated,
        guides_footer=guides.footer_html(),
        extra_script=ENTRY_SCRIPT + BATCH_SCRIPT,
        verification=site_verification.meta_tags(),
    )


ENTRY_SCRIPT = """
(function(){
  // 가이드 페이지에서 넘어온 ?q=·?track= 로 폼을 미리 채우고 바로 조회한다.
  // 저장소·쿠키를 쓰지 않고 현재 주소만 읽는다.
  try{
    var params = new URLSearchParams(window.location.search || '');
    var track = params.get('track');
    if (track === 'personal' || track === 'business' || track === 'agent') {
      var radio = document.querySelector('input[name=track][value="' + track + '"]');
      if (radio) {
        radio.checked = true;
        radio.dispatchEvent(new Event('change', {bubbles: true}));
      }
    }
    var q = params.get('q');
    if (q) {
      var keyword = document.getElementById('keyword');
      var form = document.getElementById('check');
      if (keyword && form) {
        keyword.value = q;
        form.dispatchEvent(new Event('submit', {cancelable: true}));
      }
    }
  }catch(error){}
})();
"""

BATCH_SCRIPT = """
(function(){
  var box = document.getElementById('batch-csv');
  if (!box) { return; }
  var runBtn = document.getElementById('batch-run');
  var statusEl = document.getElementById('batch-status');
  var sumEl = document.getElementById('batch-summary');
  var noteEl = document.getElementById('batch-note');
  var actionsEl = document.getElementById('batch-actions');
  var previewEl = document.getElementById('batch-preview');
  var last = null;

  function mk(tag, cls, text){
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  function download(name, text, type){
    var blob = new Blob([text], {type: type || 'text/plain;charset=utf-8'});
    var url = URL.createObjectURL(blob);
    var anchor = document.createElement('a');
    anchor.href = url; anchor.download = name;
    document.body.appendChild(anchor); anchor.click(); document.body.removeChild(anchor);
    setTimeout(function(){ URL.revokeObjectURL(url); }, 10000);
  }

  function openReport(hash){
    if (!last || !last.report_html) { return; }
    var url = URL.createObjectURL(new Blob([last.report_html], {type: 'text/html'}));
    window.open(url + (hash || ''), '_blank', 'noopener');
    setTimeout(function(){ URL.revokeObjectURL(url); }, 60000);
  }

  function renderBatch(result){
    last = result;
    sumEl.innerHTML = ''; previewEl.innerHTML = ''; actionsEl.innerHTML = '';
    var summary = result.summary || {};
    [['거래처', (summary.clients || 0) + '곳'],
     ['추천 공고', (summary.matches || 0) + '건'],
     ['7일 내 마감 포함', (summary.clients_with_urgent || 0) + '곳'],
     ['후보 없음', (summary.no_match || 0) + '곳'],
     ['처리', (summary.elapsed_ms || 0) + 'ms']].forEach(function(pair){
      sumEl.appendChild(mk('span', null, pair[0] + ' ' + pair[1]));
    });

    var anonymity = result.anonymity || {};
    var dropped = anonymity.identity_columns_dropped || [];
    noteEl.hidden = false;
    noteEl.textContent = (anonymity.note_ko || '')
      + (dropped.length ? ' 버린 열: ' + dropped.join(', ') + '.' : '');

    var actions = [
      ['1페이지 요약 열기(인쇄·PDF)', function(){ openReport('#print'); }, 'a'],
      ['요약 HTML 다운로드', function(){
         if (last && last.report_html) { download('batch-client-reports.html', last.report_html, 'text/html;charset=utf-8'); }
       }, 'button'],
      ['CSV 다운로드', function(){
         if (last && last.csv) { download('grnt-batch-summary.csv', last.csv, 'text/csv;charset=utf-8'); }
       }, 'button']
    ];
    actions.forEach(function(spec){
      var node = mk(spec[2], null, spec[0]);
      if (spec[2] === 'a') { node.href = '#'; }
      node.addEventListener('click', function(event){
        if (spec[2] === 'a') { event.preventDefault(); }
        spec[1]();
      });
      actionsEl.appendChild(node);
    });
    actionsEl.hidden = false;

    var clients = result.clients || [];
    clients.slice(0, 20).forEach(function(client){
      var conditions = client.conditions || {};
      var region = (conditions.region || {}).label || '전국';
      var employees = (conditions.employees === null || conditions.employees === undefined)
        ? '미입력' : conditions.employees + '명';
      var details = mk('details', 'batch-client');
      details.appendChild(mk('summary', null,
        client.client_ref + ' · ' + (conditions.industry_label || '업종 미지정')
        + ' · 상시 ' + employees + ' · ' + region
        + ' · ' + (client.matches || []).length + '건'
        + (client.label ? ' · ' + client.label : '')));
      (client.matches || []).forEach(function(match){
        details.appendChild(mk('p', null,
          (match.d_day || '') + ' [' + (match.category_label || '') + '] ' + (match.name || '')
          + ' — ' + ((match.verdict || {}).label_ko || '')));
      });
      (client.notes_ko || []).forEach(function(note){
        details.appendChild(mk('p', null, '확인: ' + note));
      });
      previewEl.appendChild(details);
    });
    if (clients.length > 20) {
      previewEl.appendChild(mk('p', 'hint',
        '미리보기는 20곳까지입니다. 전체 요약은 위의 1페이지 요약·CSV로 받으세요.'));
    }
    if (!clients.length) {
      previewEl.appendChild(mk('p', 'hint', '거래처가 없습니다. CSV를 확인해 주세요.'));
    }
  }

  document.getElementById('batch-sample').addEventListener('click', function(){
    fetch('/v1/batch-match/sample.csv').then(function(response){ return response.text(); })
      .then(function(text){
        box.value = text.trim();
        statusEl.textContent = '샘플 5곳을 채웠습니다. 상호·사업자번호 열이 있어도 버려집니다.';
      }).catch(function(){
        statusEl.textContent = '샘플을 불러오지 못했습니다. 직접 붙여 넣어 주세요.';
      });
  });

  document.getElementById('batch-download-sample').addEventListener('click', function(){
    var anchor = document.createElement('a');
    anchor.href = '/v1/batch-match/sample.csv';
    anchor.download = 'grnt-batch-sample.csv';
    document.body.appendChild(anchor); anchor.click(); document.body.removeChild(anchor);
  });

  runBtn.addEventListener('click', function(){
    var csv = box.value.trim();
    if (!csv) {
      statusEl.textContent = 'CSV를 붙여 넣거나 샘플 CSV를 채워 주세요.';
      return;
    }
    runBtn.disabled = true;
    statusEl.textContent = '거래처를 매칭하는 중…';
    var payload = {
      csv: csv,
      top_n: document.getElementById('batch-top5').checked ? 5 : 3,
      allow_labels: document.getElementById('batch-labels').checked
    };
    fetch('/v1/batch-match', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    }).then(function(response){
      return response.json().then(function(body){ return {ok: response.ok, body: body}; });
    }).then(function(out){
      if (!out.body.ok) { throw new Error(out.body.message || out.body.error || 'error'); }
      statusEl.textContent = '';
      renderBatch(out.body.result || out.body);
      document.getElementById('batch-card').scrollIntoView({behavior:'smooth', block:'start'});
    }).catch(function(error){
      statusEl.textContent = '매칭하지 못했습니다(' + error.message
        + '). CSV 열 이름·거래처 수(최대 300곳)를 확인해 주세요.';
    }).finally(function(){
      runBtn.disabled = false;
    });
  });
})();
"""

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

        <div class="grid" id="agent-fields" hidden>
          <label class="field">
            <span class="lab">업종</span>
            <select id="agent_industry">
              <option value="">선택 안 함</option>
              {agent_industry_options}
            </select>
            <span class="hint">업종에 따라 적용되는 근로자·매출 기준이 달라집니다.</span>
          </label>
          <label class="field">
            <span class="lab">상시근로자 수</span>
            <input type="number" id="agent_employees" inputmode="numeric" min="0" max="100000"
                   step="1" placeholder="예: 3">
            <span class="hint">대표자 제외 · 월 60시간 미만 제외 · 60시간 이상 단시간은 0.5명</span>
          </label>
          <label class="field">
            <span class="lab">연매출 <span class="opt">억 원</span></span>
            <input type="number" id="agent_revenue_eok" inputmode="decimal" min="0" step="0.1"
                   placeholder="예: 2">
            <span class="hint">직전 사업연도 매출. 모르면 비워 두세요.</span>
          </label>
          <label class="field">
            <span class="lab">업력 <span class="opt">년</span></span>
            <input type="number" id="agent_years" inputmode="numeric" min="0" max="60"
                   step="1" placeholder="예: 4">
          </label>
          <label class="field">
            <span class="lab">기업 형태</span>
            <select id="agent_entity">
              <option value="">자동(규모 추정으로 결정)</option>
              {entity_options}
            </select>
          </label>
          <label class="field">
            <span class="lab">사업자 상태</span>
            <select id="agent_status">
              <option value="operating">사업자등록 후 운영 중</option>
              <option value="pre">예비창업자(사업자등록 전)</option>
            </select>
          </label>
          <div class="field full">
            <span class="lab">볼 묶음 <span class="opt">선택 · 비우면 네 묶음 전부</span></span>
            <div class="chips" id="interest-chips">{interest_checks}</div>
            <span class="hint">세무 담당이면 <strong>정책자금·세제</strong>, 노무 담당이면
            <strong>고용·노무</strong>만 켜도 됩니다.</span>
          </div>
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

    <section class="card" id="report-card" hidden>
      <h2>거래처 리포트</h2>
      <p class="sub" id="report-sub"></p>
      <div class="report-actions" id="report-actions"></div>
      <div class="report-sum" id="report-sum"></div>
      <div class="report-size" id="report-size" hidden></div>
      <div id="report-body"></div>
      <p class="foot" id="report-foot"></p>
    </section>

    <section class="card" id="batch-card">
      <h2>세무·노무사용 거래처 일괄 매칭 <span class="tag">익명 CSV</span></h2>
      <p class="sub">거래처 50~300곳을 한 번에 올리면 거래처마다 지금 신청할 만한 공고 3~5건을 골라
      <strong>1페이지 요약(인쇄·PDF)</strong>과 <strong>CSV</strong>로 정리합니다. 한 곳씩 돌리는
      &lsquo;사업자·대리인 리포트&rsquo;와 같은 판정 규격(같은 엔진·같은 묶음·같은 우선순위)을 씁니다.</p>
      <p class="anon"><strong>상호명·사업자번호는 서버 매칭에 쓰지 않고 조건 코드만 처리합니다.</strong><br>
      상호·사업자번호·대표자·연락처·이메일·상세주소 열은 <strong>값을 읽지 않고 버립니다</strong>
      (열 이름만 응답에 남김). 결과는 익명 코드 <code>client_ref</code> 기준이라, 원본 파일에서
      VLOOKUP 으로 다시 붙이면 됩니다.</p>
      <label class="field" style="margin-top:14px">
        <span class="lab">거래처 CSV</span>
        <textarea id="batch-csv" rows="8" spellcheck="false"
          placeholder="client_ref,industry,employees,revenue_bracket,business_age_years,region&#10;C-001,음식숙박,3,1억~2억,4,인천광역시 서구"></textarea>
        <span class="hint">열 이름은 한글도 됩니다(거래처코드·업종·직원수·연매출·업력·지역·비고).
        매출은 <code>revenue_krw</code>(원) 또는 <code>revenue_bracket</code>(구간) 중 하나로 주세요.</span>
      </label>
      <div class="actions" style="margin-top:12px">
        <button class="ghost" type="button" id="batch-sample">샘플 CSV 채우기</button>
        <button class="ghost" type="button" id="batch-download-sample">샘플 CSV 다운로드</button>
        <button class="primary" type="button" id="batch-run">거래처 일괄 매칭</button>
      </div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;font-size:13px;color:var(--ink-soft)">
        <label style="display:inline-flex;gap:6px;align-items:center">
          <input type="checkbox" id="batch-labels"> note 열을 표시용 라벨로 함께 보기(매칭 미사용)
        </label>
        <label style="display:inline-flex;gap:6px;align-items:center">
          <input type="checkbox" id="batch-top5" checked> 거래처당 5건(해제 시 3건)
        </label>
      </div>
      <div class="status" id="batch-status" role="status" aria-live="polite"></div>
      <div class="report-sum" id="batch-summary"></div>
      <p class="hint" id="batch-note" hidden></p>
      <div class="report-actions" id="batch-actions" hidden></div>
      <div id="batch-preview"></div>
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
        <a href="#batch-card">거래처 일괄 매칭(익명 CSV)</a>
        <a href="/s/">주제별 지원금 모아보기</a>
        <a href="/guides/">자주 묻는 지원금 질문</a>
        <a href="/v1/meta">서비스·데이터 상태</a>
        <a href="/v1/stats">익명 사용 통계</a>
        <a href="/llms.txt">AI·개발자용 안내</a>
      </div>
    </section>

    {guides_footer}

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
    var track = currentTrack();
    document.getElementById('personal-fields').hidden = track !== 'personal';
    document.getElementById('biz-fields').hidden = track !== 'business';
    document.getElementById('agent-fields').hidden = track !== 'agent';
    var runBtn = document.getElementById('run');
    if (runBtn) {{
      runBtn.textContent = track === 'agent' ? '거래처 리포트 만들기'
        : (track === 'business' ? '우리 회사 지원사업 확인하기' : '내 지원금 확인하기');
    }}
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

  var activeFilter = 'none';
  var activeKind = 'none';
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
    var fieldOrder = ['주거·주택', '보육·교육', '고용·창업·경제', '생활·복지', '보건·의료', '문화·여가', '농림·어업', '행정·기타'];
    // 이전 동적 필터 바 정리
    document.querySelectorAll('.sub-bar-dyn').forEach(function(elNode){{ elNode.remove(); }});

    // 1단: 큰 분류 (지원금·바우처 vs 교육·건강·프로그램) 딱 2개만 먼저 노출
    var grantCnt = allRows.filter(function(r){{ return r.benefit_kind !== 'program'; }}).length;
    var progCnt = allRows.filter(function(r){{ return r.benefit_kind === 'program'; }}).length;
    if (activeKind === 'grant' && grantCnt === 0 && progCnt > 0) {{ activeKind = 'none'; }}
    if (activeKind === 'program' && progCnt === 0 && grantCnt > 0) {{ activeKind = 'none'; }}
    var kindTabs = [
      ['grant', '지원금·바우처'],
      ['program', '교육·건강·프로그램']
    ];
    var kindCounts = {{ grant: grantCnt, program: progCnt }};
    kindTabs.forEach(function(pair){{
      var k = pair[0], label = pair[1];
      var kbtn = document.createElement('button');
      kbtn.type = 'button';
      kbtn.className = activeKind === k ? 'active' : '';
      kbtn.style.fontWeight = '600';
      kbtn.textContent = label + ' ' + kindCounts[k] + '건';
      kbtn.addEventListener('click', function(){{
        if (activeKind === k) {{
          activeKind = 'none';
          activeFilter = 'none';
          activeField = 'all';
        }} else {{
          activeKind = k;
          activeFilter = 'none';
          activeField = 'all';
        }}
        renderResults(lastData);
      }});
      counts.appendChild(kbtn);
    }});

    // 1단 필터 적용 (미선택 시 전체 목록 표시, 2·3단 필터 바는 숨김)
    var kindRows = activeKind === 'none'
      ? allRows
      : allRows.filter(function(r){{
          return activeKind === 'program'
            ? r.benefit_kind === 'program'
            : r.benefit_kind !== 'program';
        }});

    var verdictRows = kindRows;
    if (activeKind !== 'none') {{
      var subBox = document.createElement('div');
      subBox.className = 'sub-bar-dyn';
      subBox.style.marginTop = '10px';
      subBox.style.padding = '10px 12px';
      subBox.style.background = '#f8f9fb';
      subBox.style.border = '1px solid #e6e8ee';
      subBox.style.borderRadius = '10px';

      var labels = {{
        all: '전체',
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
      verdictBar.className = 'counts';
      Object.keys(labels).forEach(function(code){{
        var cnt = code === 'all' ? kindRows.length : (rowCounts[code] || 0);
        if (code !== 'all' && !cnt) return;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = activeFilter === code ? 'active' : '';
        btn.textContent = labels[code] + ' ' + cnt + '건';
        btn.addEventListener('click', function(){{
          activeFilter = (activeFilter === code) ? 'none' : code;
          activeField = 'all';
          renderResults(lastData);
        }});
        verdictBar.appendChild(btn);
      }});
      subBox.appendChild(verdictBar);

      if (activeFilter !== 'none') {{
        verdictRows = kindRows.filter(function(r){{
          if (activeFilter === 'all') return true;
          return r.verdict && r.verdict.code === activeFilter;
        }});
      }}

      if (activeFilter !== 'none') {{
        var fieldCounts = {{}};
        verdictRows.forEach(function(r){{
          var b = fieldBucket(r);
          fieldCounts[b] = (fieldCounts[b] || 0) + 1;
        }});
        var fieldBar = document.createElement('div');
        fieldBar.className = 'counts';
        fieldBar.style.marginTop = '8px';
        fieldBar.style.paddingTop = '8px';
        fieldBar.style.borderTop = '1px dashed #dde1ea';
        var fAllBtn = document.createElement('button');
        fAllBtn.type = 'button';
        fAllBtn.className = activeField === 'all' ? 'active' : '';
        fAllBtn.textContent = '전체 분야 ' + verdictRows.length + '건';
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
        subBox.appendChild(fieldBar);
      }}
      counts.parentNode.insertBefore(subBox, counts.nextSibling);
    }}

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

    var rows = verdictRows.filter(function(r){{
      if (activeField !== 'all' && fieldBucket(r) !== activeField) return false;
      return true;
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

  var lastReportPayload = null;

  function numberOrNull(id){{
    var raw = document.getElementById(id).value;
    if (raw === '' || raw === null) return null;
    var value = parseFloat(raw);
    return isNaN(value) ? null : value;
  }}

  function reportPayload(){{
    var payload = {{limit: 60}};
    if (sido.value) payload.sido = sido.value;
    if (sigungu.value) payload.sigungu = sigungu.value;
    var industry = document.getElementById('agent_industry').value;
    if (industry) payload.industry = industry;
    var employees = numberOrNull('agent_employees');
    if (employees !== null) payload.employees = employees;
    var revenue = numberOrNull('agent_revenue_eok');
    if (revenue !== null) payload.annual_revenue_eok = revenue;
    var years = numberOrNull('agent_years');
    if (years !== null) payload.biz_years = years;
    var entity = document.getElementById('agent_entity').value;
    if (entity) payload.biz_entity = entity;
    var statusValue = document.getElementById('agent_status').value;
    if (statusValue) payload.biz_status = statusValue;
    var interest = Array.prototype.slice
      .call(document.querySelectorAll('input[name=interest]:checked'))
      .map(function(input){{ return input.value; }});
    if (interest.length) payload.interest = interest;
    var kw = document.getElementById('keyword');
    if (kw && kw.value.trim()) payload.keyword = kw.value.trim();
    var closed = document.getElementById('include_closed');
    if (closed && closed.checked) payload.include_closed = true;
    return payload;
  }}

  function queryString(payload){{
    var params = [];
    Object.keys(payload || {{}}).forEach(function(key){{
      var value = payload[key];
      if (value === null || value === undefined || value === '') return;
      var list = Array.isArray(value) ? value : [value];
      list.forEach(function(item){{
        params.push(encodeURIComponent(key) + '=' + encodeURIComponent(String(item)));
      }});
    }});
    return params.join('&');
  }}

  function reportTable(rows){{
    var table = el('table', 'report-table');
    var head = el('thead');
    var headRow = el('tr');
    ['공고명', '소관기관', '지원유형', '마감일', 'D-day', '판정', '신청'].forEach(function(label){{
      headRow.appendChild(el('th', null, label));
    }});
    head.appendChild(headRow);
    table.appendChild(head);
    var body = el('tbody');
    rows.forEach(function(row){{
      var tr = el('tr');
      tr.appendChild(el('td', null, row.name || ''));
      tr.appendChild(el('td', null, row.agency || ''));
      tr.appendChild(el('td', null, row.support_type || ''));
      tr.appendChild(el('td', 'nowrap', row.deadline_date || row.deadline_text || '미기재'));
      tr.appendChild(el('td', 'nowrap' + (row.closing_soon ? ' soon' : ''), row.d_day || ''));
      tr.appendChild(el('td', 'nowrap', (row.verdict && row.verdict.label_ko) || ''));
      var linkCell = el('td', 'nowrap');
      if (row.link) {{
        var anchor = el('a', null, '신청');
        anchor.href = row.link;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
        linkCell.appendChild(anchor);
      }} else {{
        linkCell.textContent = '—';
      }}
      tr.appendChild(linkCell);
      body.appendChild(tr);
    }});
    table.appendChild(body);
    return table;
  }}

  function renderReport(data){{
    var result = data.result || {{}};
    var client = result.client || {{}};
    var summary = result.summary || {{}};
    var card = document.getElementById('report-card');
    var box = document.getElementById('report-body');
    var actions = document.getElementById('report-actions');
    var sum = document.getElementById('report-sum');
    box.innerHTML = ''; actions.innerHTML = ''; sum.innerHTML = '';
    document.getElementById('results-card').hidden = true;
    card.hidden = false;

    var employees = (client.employees === null || client.employees === undefined)
      ? '미입력' : client.employees + '명';
    var years = (client.biz_years === null || client.biz_years === undefined)
      ? '미입력' : String(Number(client.biz_years)) + '년';
    document.getElementById('report-sub').textContent =
      (client.industry_label || '업종 미지정') + ' · 상시근로자 ' + employees +
      ' · 연매출 ' + (client.annual_revenue_label || '미입력') +
      ' · 업력 ' + years + ' · ' + (client.region_label || '전국') +
      ' · ' + (result.scanned || 0) + '건을 대조했습니다.';

    var query = queryString(lastReportPayload);
    var csvLink = el('a', null, 'CSV 다운로드');
    csvLink.href = '/v1/report/export.csv?' + query;
    csvLink.setAttribute('download', '');
    actions.appendChild(csvLink);
    var printLink = el('a', null, '인쇄용 요약 뷰');
    printLink.href = '/v1/report/print.html?' + query;
    printLink.target = '_blank';
    printLink.rel = 'noopener noreferrer';
    actions.appendChild(printLink);

    [['후보', summary.total || 0], ['우선 검토', summary.high_priority || 0],
     ['마감임박 D-7', summary.d7_count || 0]].forEach(function(pair){{
      sum.appendChild(el('span', null, pair[0] + ' ' + pair[1] + '건'));
    }});
    (result.sections || []).forEach(function(section){{
      sum.appendChild(el('span', null, section.category_label + ' ' + section.count + '건'));
    }});

    var sizeBox = document.getElementById('report-size');
    var size = result.size_estimate || {{}};
    sizeBox.innerHTML = '';
    if (size.summary_ko) {{
      sizeBox.hidden = false;
      sizeBox.appendChild(el('strong', null, '규모 판단 — ' + size.summary_ko));
      var noteList = el('ul');
      (size.notes_ko || []).forEach(function(note){{
        noteList.appendChild(el('li', null, note));
      }});
      if (noteList.childNodes.length) sizeBox.appendChild(noteList);
    }} else {{
      sizeBox.hidden = true;
    }}

    if ((result.d7 || []).length) {{
      var d7Sec = el('div', 'report-sec');
      var d7Head = el('h3', null, '마감 임박(D-7)');
      d7Head.appendChild(el('small', null, '이번 주에 신청을 끝내야 하는 공고'));
      d7Sec.appendChild(d7Head);
      d7Sec.appendChild(reportTable(result.d7));
      box.appendChild(d7Sec);
    }}

    (result.sections || []).forEach(function(section){{
      var sec = el('div', 'report-sec');
      var title = el('h3', null, section.category_label || '');
      title.appendChild(el('small', null,
        (section.duty_ko || '') + ' · ' + (section.count || 0) + '건'));
      sec.appendChild(title);
      sec.appendChild(reportTable(section.rows || []));
      box.appendChild(sec);
    }});

    if (!(result.sections || []).length) {{
      box.appendChild(el('div', 'empty',
        '조건에 맞는 공고가 나오지 않았습니다. 업종·규모·지역을 바꿔 다시 시도해 보세요.'));
    }}

    var footText = result.disclaimer_ko || '';
    if ((result.notes_ko || []).length) {{
      footText += ' ' + result.notes_ko.join(' ');
    }}
    document.getElementById('report-foot').textContent = footText;
  }}

  function runReport(){{
    var button = document.getElementById('run');
    button.disabled = true;
    status.textContent = '거래처 리포트를 만드는 중…';
    lastReportPayload = reportPayload();
    fetch('/v1/tools/business_report', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(lastReportPayload)
    }}).then(function(response){{
      if (!response.ok) {{ throw new Error('HTTP ' + response.status); }}
      return response.json();
    }}).then(function(data){{
      if (!data.ok) {{ throw new Error(data.message || data.error || 'error'); }}
      status.textContent = '';
      renderReport(data);
      document.getElementById('report-card').scrollIntoView({{behavior:'smooth', block:'start'}});
    }}).catch(function(error){{
      status.textContent = '리포트를 만들지 못했습니다(' + error.message + '). 잠시 뒤 다시 시도해 주세요.';
    }}).finally(function(){{
      button.disabled = false;
    }});
  }}

  var form = document.getElementById('check');
  var status = document.getElementById('status');
  form.addEventListener('submit', function(event){{
    event.preventDefault();
    if (currentTrack() === 'agent') {{
      runReport();
      return;
    }}
    var button = document.getElementById('run');
    button.disabled = true;
    status.textContent = '판정 중…';
    var includeClosedEl = document.getElementById('include_closed');
    var kwEl = document.getElementById('keyword');
    var payload = {{
      profile: buildProfile(),
      limit: 200,
      balance_kinds: true,
      include_closed: !!(includeClosedEl && includeClosedEl.checked)
    }};
    if (kwEl && kwEl.value.trim()) {{
      payload.keyword = kwEl.value.trim();
    }}
    activeFilter = 'none';
    activeKind = 'none';
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
    if (currentTrack() === 'agent') {{
      sido.value = '인천광역시'; resetSigungu(); sigungu.value = '서해구';
      document.getElementById('agent_industry').value = 'food';
      document.getElementById('agent_employees').value = '3';
      document.getElementById('agent_revenue_eok').value = '2';
      document.getElementById('agent_years').value = '4';
      document.getElementById('agent_entity').value = '';
      document.getElementById('agent_status').value = 'operating';
      return;
    }}
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
<script>{extra_script}</script>
</body>
</html>
"""




def region_payload() -> Dict[str, Any]:
    return {sido: [name for _code, name in rows]
            for sido, rows in regions.SIGUNGU_BY_SIDO.items()}
