# GRNT — 개인·창업 통합 지원금 판정기

> **Grants, simplified.** · KOREA GRANT & SUBSIDY INTELLIGENCE
>
> "나 지원금 받을 수 있어?"와 "우리 회사·가게가 받을 수 있어?"에 **근거와 함께** 답하는 서비스.
> 개인은 나이·지역·소득구간·상황(임신·출산·무주택·구직·장애 등)을, 창업·기업은 사업자 조건
> (예비창업자/운영 중, 업력, 소상공인·중소기업, 업종)을 넣으면
> **정부24 보조금24의 공개 자격 코드**와 **K-Startup·기업마당 공고의 신청자격**으로 후보를 판정하고,
> 사유·누락 정보·선정기준 원문·신청기한·문의처·출처를 같이 돌려줍니다.
> 로그인 없음, 주민등록번호 없음, 판정 입력은 서버에 저장하지 않음(문의 카드에 직접 적은 회신용 연락처만 별도).

- 웹 UI: `GET /` — 개인·가구 ↔ 창업·소상공인·기업 ↔ **사업자·대리인 리포트** 3탭, 30초 조건 선택
- JSON API: `POST /v1/tools/{tool}` — 툴 9종
- 거래처 전달용: `POST`(또는 `GET`) `/v1/report/export.csv` · `/v1/report/print.html` — 세무사·노무사용 요약 표(1곳)
- 거래처 일괄(익명): `POST /v1/batch-match` — 세무·노무사무소 거래처 50~300곳 CSV → 거래처별 3~5건 + 1페이지 요약 HTML·CSV
- 사전 신청·문의: `POST /v1/inquiry` — 홈 화면 푸터 위 미니 카드(세무·노무사 리포트·대량 매칭 문의)가 보내는 창구. 연락처는 회신 목적으로만 저장하고 통계에는 넣지 않습니다. 선택 필드 `cohort`(별칭 `source`)로 무료 베타·소개 유입 태그(`beta_pilot`, `citechart` 등 40자)를 붙일 수 있습니다
- MCP: `POST /mcp` · `POST /v1/mcp` (Streamable HTTP JSON-RPC 2.0) + `python -m subsidy_kr.mcp_stdio`
- 정적 SEO: `GET /s/` · `GET /s/{slug}` (개인 주제 + 창업·R&D 주제 + 지역), `/robots.txt`, `/llms.txt`, `/sitemap.xml`
- 시·도 허브: `GET /regions/` · `GET /regions/{slug}` — 16개 시·도별 공고 수·분야 분포·마감 임박 목록·시·군·구별 공고 수(FAQPage·BreadcrumbList·WebPage JSON-LD)
- 질문형 가이드: `GET /guides/` · `GET /guides/{slug}` — AI·검색에 묻는 질문 81개(FAQPage JSON-LD)
- 고지 페이지: `GET /privacy` · `GET /terms` · `GET /about` — 개인정보 처리방침(문의 연락처 180일 보관·삭제 요청 경로)·이용약관(확정 판정 아님·책임 한계)·서비스 소개(데이터 출처·3종 생태계)를 서버 렌더 정적 HTML로 제공. 홈·주제·지역·가이드 푸터와 `sitemap.xml` 에서 이어집니다
- 공유 카드: `/static/og.png`(1200×630) + 홈·가이드·고지 페이지의 `canonical`·`og:image` 메타
- 일자별 스냅샷(0.4.6): 카탈로그 갱신 때 `snapshots/{날짜}.json.gz` 한 장을 적재하고, 배포 이미지에 기준일 스냅샷을 함께 넣어 `compare_ledgers` 가 프로덕션에서 `snapshot_missing` 으로 비지 않게 했습니다(기준일 1장뿐이면 `state: baseline_only` 로 정직하게 답합니다)
- 사용 통계 구분(0.4.6): `/v1/stats` 의 `traffic.by_channel`(사람이 여는 페이지·크롤러 파일·REST API·MCP·정적 자산·없는 주소)과 `traffic.by_client`(브라우저·봇·기타) — UA 원문·IP·쿠키는 저장하지 않습니다
- 거래처 매칭 정교화(0.4.7): 익명 CSV 에 `industry_keyword`(세부 업종·취급품목)·`entity`(기업 형태, 소상공인여부 Y/N 포함)·`employment`(청년·고령·육아휴직·장애인·사회보험료)·`employees_bracket`(5인 미만)·`founded_year`(설립연도) 열을 더 받습니다. 거래처마다 **탈락 사유**(지역·업력·연령·업종·기업 형태·상위 후보 밖)를 사유별로 세고, 결과 1건마다 엔진 판정에서 온 **판정 근거**를 붙입니다. 고용 이슈는 '청년일자리'·'시니어인턴십'처럼 고용 지원을 뜻하는 결합 표현만 잡습니다('고령군' 같은 지역명 오탐 방지)
- AI 검색 구조화 데이터(0.4.7): 홈은 Organization·WebSite(SearchAction)·WebApplication 을 `@graph` 한 덩어리로 묶어 `@id` 로 연결하고, `/s/`·`/s/{slug}` 는 CollectionPage·ItemList·BreadcrumbList 를 냅니다. robots.txt 에 OAI-SearchBot·Claude-SearchBot·Google-Extended·CCBot·Applebot-Extended 를 더하고, llms.txt 에 '구조화 데이터(JSON-LD)' 안내를 넣었습니다
- 검색 동의어: `keyword` 검색은 **생활어 사전**(`synonyms.py`)으로 단어를 넓혀 봅니다 — "전기세"→전기요금·가스요금, "병원비"→의료비·진료비, "배달비"→택배비·배달앱. 질의어를 그대로 담은 제도가 항상 먼저 나옵니다
- API 키 없이 동작: 저장소에는 원본 동기화 산출물(25MB) 대신 **압축본 `data/gov24/catalog.json.gz`(약 3.8MB)** 만 둡니다.
  로더는 `catalog.json` 이 있으면 그것을, 없으면 `catalog.json.gz` 를 읽습니다 — 그래서 클론·이미지·Render 가
  동기화 없이 바로 실데이터로 뜹니다. 내장 샘플(개인 20 + 창업·기업 12)은 둘 다 없을 때의 오프라인 대체입니다.
  `data/gov24/catalog.json` 을 새로 만들면(아래 3분 실행) 그 파일이 압축본보다 우선합니다.
  압축본은 `.github/workflows/refresh-catalog.yml` 이 매일 04:00 KST 에 자동 갱신합니다(아래 4-1).
- 저장소: <https://github.com/CLNS-KR/GRNT> · 이미지: `docker build -t grnt .`
- 실데이터 기준(2026-11-21 라이브 `/healthz`): **제도 13,167건 — 개인·가구 11,668 · 창업·기업 1,499**
  (정부24 보조금24 10,891 · K-Startup 196 · 기업마당 1,303 · 지자체 자체 복지포털 777, 소관기관 1,179곳).
  숫자는 `/healthz`·`/v1/meta` 가 알려 주는 현재값이라 매일 조금씩 움직입니다.

---

## 1. 3분 실행

```bash
# 파이썬 3.11+ · 외부 패키지 0개(표준 라이브러리만)
PYTHONPATH=src python -m subsidy_kr.server          # http://localhost:8787
# 테스트
PYTHONPATH=src python -m unittest discover -s src/tests
```

실데이터로 바꾸려면(선택, 세 데이터셋 모두 자동승인):

```bash
# 1) data.go.kr 활용신청 — 15113968(보조금24) · 15125364(K-Startup) · 15157820(기업마당)
# 2) 통합 동기화 (개인 + 창업·기업 + 일자별 스냅샷)
export DATA_GO_KR_SERVICE_KEY="발급받은키"        # 또는 프로젝트 .env (.gitignore 포함)
PYTHONPATH=src python -m subsidy_kr.sync_gov24 --sources all
# 3) 서버 재시작 → /healthz 의 catalog_state 가 "synced" 로 바뀝니다
```

`--sources` 는 `gov24`(기본) · `startup` · `bizinfo` · `all` 입니다.
동기화 옵션은 `--help` 참고: `--ttl-days 7`, `--force`, `--from-cache`, `--max-services 100`,
`--max-programs 500`(시험), `--grace-days 30`(마감 후 유지일), `--include-expired`,
`--conditions-mode per-id --ids SMP-0001,...`, `--dry-run`.

---

## 2. 두 트랙, 하나의 판정 규격

| 트랙 | 데이터 | 판정 근거 | 비고 |
|---|---|---|---|
| `personal` 개인·가구 | 정부24 **보조금24**(`15113968`) | JA 자격 코드(성별·연령·중위소득·생애·가구·직업) | 지자체 선정기준 공백은 원본 그대로 |
| `business` 창업·소상공인·기업 | 창업진흥원 **K-Startup**(`15125364`), 중소벤처기업부 **기업마당**(`15157820`) | 공고의 구조화된 신청자격(업력·연령·지역·대상·성별·업종) | 모집 마감은 기본 숨김 |

### 개인 트랙 — 보조금24 JA 코드

| 묶음 | 코드 | 규칙 |
|---|---|---|
| 성별 | `JA0101` 남 / `JA0102` 여 | 한쪽만 켜져 있으면 그 성별만 대상 |
| 연령 | `JA0110` 시작 ~ `JA0111` 종료 | 0 이하 = 하한 없음, 100 이상(원천에 120) = 상한 없음 |
| 중위소득 | `JA0201`~`JA0205` | 켜진 구간 안에 사용자 구간이 있어야 함(구간끼리 OR) |
| 생애·직업 | `JA0301`~`JA0330`, `JA13xx`, `JA2xxx` | **묶음 안은 OR** |
| 가구 | `JA0401`~`JA0414` | **묶음 안은 OR**, `JA0410`(해당사항없음)이면 누구나 |
| 사업자 | `JA11xx`, `JA12xx`, `JA21xx`, `JA22xx` | 개인 사용자는 사업자 요건에서 갈림 |

묶음 **사이**는 AND 입니다(예: "임산부이면서 무주택"). 각 묶음의 `해당사항없음` 코드가 켜져 있으면 그 묶음은 누구나 통과합니다.

### 창업·기업 트랙 — 공고 신청자격

| 요소 | 읽는 방법 | 판정 |
|---|---|---|
| 업력 | `biz_enyy`(K-Startup), 본문 "창업 3년 이내", 기업마당 개요 문장 | 예비창업자는 업력 0년으로 통과, 운영 중이면 `years ≤ max_years` |
| 연령 | `biz_trgt_age`("만 20세 이상 ~ 만 39세 이하") | 만 나이 범위 |
| 대상 | `aply_trgt_ctnt`·`trgetNm`의 예비창업자·창업기업·소상공인·중소기업·법인·벤처·사회적기업 | 예비/운영 × 기업형태 |
| 지역 | `supt_regin`(전국/시·도), 기업마당 소관기관명 | 전국·시도·시군구 |
| 성별 | "여성 예비창업자"·"여성기업" | 여성/남성 제한 |
| 업종 | 원문에 업종 제한이 **명시된 경우만** 판정 조건 | 해시태그 업종은 검색·표시용 |
| 모집 | `rcrt_prgs_yn` | 마감 공고는 `check_needed` + 기본 숨김 |

> 실호출로 확인한 함정: K-Startup 의 `biz_enyy`·`biz_trgt_age` 는 단일 값이 아니라
> **허용하는 조건의 목록**입니다(`예비창업자,1년미만,…,10년미만`). 그래서 여러 값이 오면
> 합집합(가장 넓은 쪽)으로 읽고, 단일 값일 때만 제한으로 판정합니다. 구조화 컬럼과 본문 문장이
> 다르면 더 좁은 쪽을 씁니다(놓치는 것보다 낫습니다).

### 4단계 판정

| 등급 | 뜻 |
|---|---|
| `eligible_likely` | 공개된 조건을 모두 충족 |
| `check_needed` | 조건은 맞지만 **원본 선정기준 공백**·자격 코드 없음·추첨·선착순·예산 소진·모집 마감 등 확인 필요 |
| `insufficient_info` | 입력이 없어 가능/불가를 말하지 않음 — **무엇을 더 물어야 하는지** 함께 반환 |
| `ineligible` | 조건과 명확히 어긋남 — 어긋난 항목과 원문 기준 반환 |

### 일부러 이렇게 만든 것

1. **모르면 모른다고 한다.** 소득구간을 안 넣으면 `insufficient_info` 이지, "아마 될 거예요"라고 하지 않습니다. 조건을 하나도 안 넣으면 판정하지 않습니다.
2. **지자체 공백을 메우지 않는다.** 원본 `선정기준`이 비어 있으면 `check_needed` + "소관기관 확인" 문구. (실데이터에서 지자체 수천 건이 이 상태입니다.)
3. **자격 코드가 없으면 단정하지 않는다.** 코드 없는 제도는 `check_needed`("원문 기준으로만 확인 가능")입니다.
4. **아동 제도의 연령은 아동 나이로.** `age_subject: "child"` 이면 신청자 나이로 탈락시키지 않고 `children_years` 를 물어봅니다.
5. **지역은 소관기관명으로.** `중구`·`서구`처럼 여러 시도에 있는 이름은 찍지 않고 `local_unresolved`/`unknown` 으로 남깁니다(틀린 필터보다 정직한 미확인이 낫습니다).
6. **기업 트랙의 '가능성 높음'은 신청자격 충족이다.** 모집형 사업이라 선정은 평가·경쟁으로 결정된다는 문구를 항상 함께 붙입니다.
7. **기업마당 문구는 고치지 않는다.** '출처표시·변경금지' 조건이라 HTML 태그만 걷어내고 원문 문구를 보존하며, 응답마다 출처를 붙입니다.

---

## 3. 툴 9종

| 툴 | 입력 | 출력 요점 |
|---|---|---|
| `search_subsidies` | `profile`(개인 조건 + `track` + `business`), `limit`, `tag`, `keyword`, `include_closed` | 후보 + 트랙·등급별 건수 + 사유 + `next_questions` |
| `check_eligibility` | `service_id`, `profile` | 단건 판정 + 어긋난 항목 + 누락 정보 |
| `get_subsidy_detail` | `service_id`, (`profile` 선택) | 선정기준 원문·구비서류·문의처·신청링크·출처(+판정) |
| `list_region_subsidies` | `sido`, (`sigungu`), `track` | 지역 제도 + 전국 제도 목록 |
| `deadline_calendar` | `days`(기본 30), `track`, `sido`/`sigungu`, `keyword` | 마감 임박 캘린더(날짜별) + 날짜 미기재 건수 |
| `compare_ledgers` | `from_date`, `to_date`, `service_id` | 일자별 스냅샷 비교: 추가·삭제·기간/금액/대상/모집상태 변경 |
| `business_report` | `industry`, `employees`, `annual_revenue_krw`(또는 `annual_revenue_eok`), `biz_years`, `sido`/`sigungu`, `interest[]` | 세무사·노무사용 **거래처 리포트** — 소상공인/중소기업/고용·노무/정책자금·세제 네 묶음 + 우선순위 + D-7 |
| `batch_match_clients` | `csv`(또는 `clients[]`), `top_n`(3~5), `allow_labels` | 거래처 50~300곳 **일괄 익명 매칭** — 거래처별 상위 3~5건 + 1페이지 요약 |
| `get_service_meta` | — | 카탈로그·두 트랙·판정 등급·자격 코드·기업 조건·스냅샷·개인정보 설정 |

```bash
# 개인
curl -s localhost:8787/v1/tools/search_subsidies -H 'Content-Type: application/json' -d '{
  "profile": {"track": "personal", "age": 34, "sex": "male",
              "region": {"sido": "인천광역시", "sigungu": "서구"},
              "income_band": "JA0203", "situations": ["no_home", "worker"]}
}'

# 창업·기업 (예비창업자)
curl -s localhost:8787/v1/tools/search_subsidies -H 'Content-Type: application/json' -d '{
  "profile": {"track": "business", "age": 33, "sex": "male",
              "region": {"sido": "인천광역시", "sigungu": "서구"},
              "business": {"status": "pre", "entity": "pre_startup"}}
}'

# 마감 임박 30일 (두 트랙)
curl -s localhost:8787/v1/tools/deadline_calendar -d '{"days": 30}' -H 'Content-Type: application/json'

# 어제 → 오늘 카탈로그 변화
curl -s localhost:8787/v1/tools/compare_ledgers -d '{}' -H 'Content-Type: application/json'
```

```bash
# 세무사·노무사용 거래처 리포트 (인천 서해구 음식점 · 상시근로자 3명 · 연매출 2억)
curl -s localhost:8787/v1/tools/business_report -H 'Content-Type: application/json' -d '{
  "sido": "인천광역시", "sigungu": "서해구", "industry": "음식숙박",
  "employees": 3, "annual_revenue_eok": 2, "biz_years": 4
}'

# 같은 조건을 거래처 전달용 CSV / 인쇄용 요약 뷰로
curl -s -X POST localhost:8787/v1/report/export.csv -H 'Content-Type: application/json' \
  -d '{"sido":"인천광역시","sigungu":"서해구","industry":"음식숙박","employees":3,"annual_revenue_eok":2}' -o report.csv
open "http://localhost:8787/v1/report/print.html?industry=food&employees=3&annual_revenue_eok=2"
```

```bash
# 거래처 일괄(익명) — CSV 300곳까지, 상호·사업자번호 열은 값을 읽지 않는다
curl -s localhost:8787/v1/batch-match -H 'Content-Type: text/csv' --data-binary @clients.csv
curl -s localhost:8787/v1/batch-match/sample.csv -o grnt-batch-sample.csv
# 같은 본문으로 1페이지 요약(인쇄·PDF)·CSV 요약을 받는다
curl -s -X POST localhost:8787/v1/batch-match/reports.html -H 'Content-Type: text/csv' \
  --data-binary @clients.csv -o batch-reports.html
```

```bash
# MCP (JSON-RPC 2.0)
curl -s localhost:8787/mcp -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"tools/call",
  "params":{"name":"get_service_meta","arguments":{}}
}'
```

프로필 필드: `track`·`age`·`birth_year`·`birth_date`·`sex`·`region{sido,sigungu}`·`household_size`·
`income_percent`·`income_band`(JA0201~0205)·`situations[]`·`children_years[]`·
`business{status(pre|operating), entity, years, industry}`.
`situations` 를 **빈 배열로 보내면 "해당 없음"**, 아예 빼면 "모름"으로 판정합니다.
`business.status` 만 넣어도 대부분 판정됩니다.

---

## 3-1. 사업자·대리인 리포트 (세무·노무)

개인은 "내가 받을 수 있나"를 묻지만, 세무사·노무사·컨설턴트는 **거래처 여러 곳**을 맡기고
"이 사업장이 지금 신청할 만한 공고"를 표로 정리해 전달합니다. 그래서 웹 UI 에 세 번째 탭과
`business_report` 툴을 따로 두었습니다.

| 입력 | 판단 |
|---|---|
| 업종 | 적용되는 상시근로자·매출 기준(제조·건설·운수 10명 / 그 밖 5명) |
| 상시근로자 수 | 소상공인 공통 요건 10명 미만 + 업종별 요건 |
| 연매출(직전 사업연도) | 「중소기업기본법 시행령」 별표 3(2025-09-01 개정) 업종별 기준 |
| 업력·사업자 상태 | 예비창업자는 규모 판정을 건너뜁니다 |

- **네 묶음 분류** — 소상공인 / 중소기업 / **고용·노무** / **정책자금·세제**. '중소기업'처럼 모든
  기업 공고에 붙는 대상 표시는 주제로 보지 않습니다. 고용·세제 키워드가 하나라도 걸리면 그쪽을
  주 분류로 삼아 노무·세무 담당자가 자기 영역을 놓치지 않게 했습니다.
- **우선순위** — 규모 적합 + 판정 등급 + 마감 D-7 + 업종·지역 일치를 점수로 합쳐
  `우선 검토 / 검토 / 참고` 세 단계로 표시하고, 7일 이내 마감은 표에서 색으로 강조합니다.
- **거래처 전달용 산출물** — 공고명·소관기관·지원유형·마감일·D-day·신청 링크가 들어간 CSV(엑셀에서
  바로 열리도록 UTF-8 BOM)와 인쇄용 요약 뷰(A4, `@media print`). CSV 는 `=`, `+`, `-`, `@` 로
  시작하는 셀에 따옴표를 붙여 수식 주입을 막습니다.
- **개인정보 없음** — 상호·대표자·연락처를 받지 않습니다. 파일명도 업종·날짜만 씁니다.

규모 판정은 **추정**입니다. 확정은 소상공인시장진흥공단의 소상공인 확인서·중소기업 확인서로 하며,
그 문구를 응답의 `scope_limits_ko` 에 함께 넣습니다.

---

## 3-2. 거래처 일괄 익명 매칭 (50~300곳)

세무·노무 사무소는 거래처를 수십~수백 곳 맡깁니다. 한 곳씩 리포트를 돌리는 대신, 거래처
목록 CSV 하나로 **거래처마다 지금 신청할 만한 공고 3~5건**을 뽑아 1페이지 요약(인쇄·PDF)과
CSV로 정리합니다. `POST /v1/batch-match`, `batch_match_clients` 툴, 웹 UI 의
&ldquo;거래처 일괄 매칭(익명 CSV)&rdquo; 카드가 모두 같은 계산을 씁니다.

| 입력 열 | 내용 |
|---|---|
| `client_ref` | 익명 코드(`C-001`). 없으면 순서대로 붙입니다 |
| `industry` | 업종 — 한글·코드 모두(`음식숙박`, `food`, `IT·정보통신`) |
| `employees` | 상시근로자 수(대표자 제외, 월 60시간 미만 제외) |
| `revenue_krw` 또는 `revenue_bracket` | 연매출(원) 또는 구간(`1억~3억`, `5천만원 미만`) |
| `business_age_years` | 업력(년) |
| `region` | `시도 시군구`(`인천광역시 서구`) |
| `note` | 표시용 라벨 — 기본으로 버립니다(`allow_labels=true` 일 때만, 매칭엔 안 씀) |

- **익명 경계** — `company_name`·`biz_no`·대표자·연락처·이메일·주민등록번호·상세주소 열은
  헤더만 확인하고 **값을 꺼내지 않습니다**. 매칭 함수에 들어가는 것은 익명 코드와 조건 코드
  (업종 슬러그·근로자 수·매출·업력·시도/시군구)뿐이고, 응답에는 **버린 열 이름만** 남깁니다.
  라벨을 붙이지 않으면 `client_ref` 로 사무소 원본 파일에서 VLOOKUP 하면 됩니다.
- **2단 매칭** — ①`engine.structural_fail` 로 구조화 요건에서 명확히 어긋난 공고만 걷어내고
  (정밀 판정에서도 `ineligible` 이라 결과가 달라지지 않음), ②남은 후보를 우선순위 근사 점수로
  24건까지 줄여 `engine.evaluate_service` 로 정밀 판정합니다. 거래처 300곳 × 전국 사업 공고
  1.5천 건을 **1초 안**에 끝냅니다(응답의 `summary.elapsed_ms`).
- **거래처별 1페이지** — `to_report_html` 이 A4 `page-break` 로 거래처마다 한 장을 만들고,
  장마다 `요약 복사`·`이 장만 인쇄`·`이 장 HTML 저장` 버튼이 붙습니다
  (`POST /v1/batch-match/reports.html` → `batch-client-reports.html`).
  CSV 요약은 `/v1/batch-match/export.csv`(BOM·수식 주입 방지).
- **한계** — 거래처당 상위 24건만 정밀 판정합니다. 규모 판정은 추정이고, 선정은 평가·경쟁으로
  결정됩니다. 응답의 `scope_limits_ko` 에 같은 문구를 넣습니다.

---

## 3-3. 질문형 가이드 `/guides/` (AI 인용·검색 유입)

사람들은 ChatGPT·Perplexity·네이버에 "청년 월세 지원 조건"처럼 **질문**으로 묻습니다. 그때
인용되려면 질문 하나에 답 하나가 있는 페이지와, 기계가 읽을 구조화 데이터가 함께 있어야 합니다.
`/guides/` 아래 81개 페이지가 그 역할을 합니다(기본 36개 + 2026-11 생활·육아·연말정산·소상공인 롱테일 15개
+ 2026-11 소상공인·예비창업자·가계 10개 — 고용촉진장려금, 아이돌봄, 신혼부부 전세자금 이자지원,
1인 자영업자 고용보험료, 학자금대출, 채무조정, 장기요양보험, 긴급복지, 예비창업 자금 조달, 배달·택배비
+ 2026-11 20개 — 전세보증금 반환보증, 청년 전세임대주택, 임산부 교통비, 배우자 출산휴가 급여,
양육수당과 보육료, 청년도전지원사업, 육아기 근로시간 단축 급여, 국민연금 추납·임의계속가입,
근로장려금 기한 후 신청, 청년도약계좌 중도해지, 통신비 감면, 건강보험 피부양자, 초기창업패키지,
사업주 장애인 고용지원, 폐업 시 근로자 정리, 카드·결제 수수료 지원, 지원금 환수·정산,
중소기업 정책자금 심사, 마감 임박 공고 확인, 공고문 읽는 순서).

| 구성 | 내용 |
|---|---|
| 한 줄 기준 | 그 질문에 대한 짧은 답. 금액·수치는 해마다 바뀌므로 고정하지 않고 공고문 확인으로 남깁니다 |
| 확인해야 할 조건 | 나이·소득·재산·서류 등 4~6개 체크포인트 |
| 지금 열려 있는 관련 공고 | 카탈로그 검색 결과에서 **마감되지 않은 것만** 최대 5건, 없으면 0건이라고 씁니다 |
| 흔히 하는 착각 | "나이만 맞으면 다 받는다" 같은 실제 오해 |
| AI·에이전트용 | `/mcp` 주소와 `/v1/tools/search_subsidies` 호출 예시(같은 조건) |
| 구조화 데이터 | `FAQPage`(질문 4개씩) + `BreadcrumbList` JSON-LD |

- 가이드의 **"내 조건으로 확인하기"** 는 `/?q=질문키워드&track=…` 로 판정 화면을 미리 채워
  바로 조회까지 실행합니다(브라우저 저장소를 쓰지 않고 주소만 읽습니다).
- 홈 화면 푸터에 가이드 링크를 자동으로 노출하고, `/sitemap.xml`(우선순위 0.6~0.7)과
  `/llms.txt`(질문 + 한 줄 기준)에 함께 싣습니다.
- 익명 카운터에는 `/guides/{slug}` 버킷이 따로 남아 **어떤 질문이 유입을 만드는지** 셉니다.

---

## 3-4. 시·도별 지원금 허브 `/regions/`

검색창에 들어오는 것은 주제만이 아니라 **지역명**입니다("인천 지원금", "경기도 소상공인 지원금").
`/regions/` 아래 18개 페이지(목록 1 + 시·도 17)가 그 자리를 맡습니다. 숫자는 전부 카탈로그
집계값이고, 집계할 수 없는 것(선정 확률·예상 수령액)은 쓰지 않습니다.

| 구성 | 내용 |
|---|---|
| 통계 | 지자체 공고 수 · 신청 가능(마감 전) · 마감 임박(14일) · 전국 공통 공고 수 |
| 분야 분포 | 마감 전 지자체 공고를 `field` 로 센 상위 6개(막대는 건수 비례) |
| 지금 신청할 수 있는 공고 | 개인·가구 먼저, 그다음 마감이 가까운 순으로 최대 10건 |
| 전국 공통 | 거주지와 무관한 전국 제도 5건 |
| 시·군·구별 공고 | 소관기관명으로 시·군·구까지 판별된 건수(상위 10곳) |
| 구조화 데이터 | `WebPage` + `FAQPage` + `BreadcrumbList`, canonical, `/sitemap.xml` 우선순위 0.7~0.8 |
| 전환 | "내 조건으로 {시·도} 지원금 바로 조회하기" → `/?track=personal&sido={시·도}`(폼 자동 채움·조회) |

- 지역 판별은 `regions.parse_agency_region` 이 소관기관명으로만 합니다. `중구`·`서구`처럼 여러
  시도에 있는 이름은 임의로 찍지 않고 **확인 필요**로 남깁니다(틀린 지역으로 거르는 것보다 낫습니다).
- 집계는 카탈로그를 한 번만 훑어 16개를 모두 만들고 `catalog.memo` 에 두므로, 두 번째 요청부터는
  즉시 응답합니다(`SQLiteCatalog`·`Catalog` 공통).
- `/v1/meta` 의 `regions` 키에 16개 슬러그·URL 이 들어 있어 에이전트도 지역 페이지를 바로 찾습니다.

---

## 3-5. 사전 신청·문의 (리드 수집 창구)

유료화(세무·노무사 거래처 리포트·대량 매칭, CLNS Pro 등) 전에 **관심 있는 사람의 연락처를
받아 두는 최소한의 창구**입니다. 홈 화면 맨 아래(푸터 바로 위)의 작은 카드 하나가 전부이고,
판정 화면과 코드·저장 경로를 완전히 분리했습니다.

```bash
curl -s localhost:8787/v1/inquiry -H 'Content-Type: application/json' -d '{
  "contact": "회신받을 연락처",
  "topic": "batch_report",
  "message": "거래처 80곳을 매달 돌리고 싶습니다. CSV 형식이 궁금합니다."
}'
```

| 필드 | 규칙 |
|---|---|
| `contact` | 이메일 또는 연락처, **3~120자**(제어문자·줄바꿈 제거) |
| `topic` | `batch_report`(거래처 리포트·대량 매칭) · `api_mcp`(API·MCP 연동) · `other` |
| `message` | 선택, **0~500자**(줄바꿈은 보존) |

응답은 `{"ok": true, "receipt": "I00001", ...}` 에 주제 라벨·다음 안내만 담고 **연락처는 돌려주지
않습니다**(같은 화면·중간 캐시에 개인정보를 한 번 더 남기지 않으려고). 검증 실패는 `400`,
`GET` 은 `405`, 하루 상한(200건)을 넘으면 `429` 입니다.

- **저장 위치** — 판정 입력과 다른 SQLite 표 `inquiries`. 연락처·내용만 들어가고 나이·지역·소득
  같은 프로필은 읽지도 않습니다.
- **통계와 분리** — `/v1/stats` 는 이 표를 읽지 않습니다. 경로 카운터에는 `/v1/inquiry` 라는
  익명 키 하나만 늘고, 응답에는 `privacy.inquiries` 로 "통계에 넣지 않는다"는 사실만 적습니다.
- **중복·상한** — 같은 날 같은 내용은 한 번만 저장하고(새로고침·두 번 클릭), 하루 200건을 넘으면
  더 받지 않습니다. CAPTCHA 는 두지 않았습니다(무료 인스턴스 자원을 먼저 지키는 쪽을 택했습니다).
- **보관 기간** — 서버가 시작할 때 `180일`이 지난 문의를 지웁니다(`usage.purge_inquiries`).
  회신이 끝난 연락처를 계속 들고 있지 않기 위해서입니다.
- **받은 문의 보기** — 운영자는 DB 에서 직접 읽습니다(공개 읽기 엔드포인트를 두지 않았습니다).

```bash
sqlite3 data/app.sqlite "select id, day, topic, contact, message from inquiries order by id desc limit 20"
```

> 무료 Render 플랜은 영구 디스크가 없어 **재배포하면 문의도 사라집니다**. 리드를 살리려면
> `GRNT_STATS_PATH` 를 영속 디스크 안 파일로 잡고, 재배포 전에 위 쿼리로 백업해 두세요.
> (카운터와 같은 DB 를 쓰므로 디스크를 붙이면 통계도 함께 살아납니다.)

---

## 3-6. 검색 동의어 확장 `synonyms.py` (0.4.1)

공고문은 "주거비·임차료·에너지바우처"처럼 제도 용어로 적혀 있는데, 사람은 "월세·전기세·병원비"로
검색합니다. 검색이 단어 그대로의 부분 일치만 보면 이런 질의는 0~1건에서 멈춥니다.
`synonyms.py` 가 생활어를 공고 용어로 이어 주고, 세 곳(메모리 카탈로그·SQLite 카탈로그·판정 엔진)이
같은 사전을 봅니다.

| 규칙 | 내용 |
|---|---|
| 직접 일치 우선 | 확장어는 가중치가 낮아, 같은 판정이면 질의어를 그대로 담은 제도가 항상 먼저 나옵니다 |
| 넓은 말은 낮은 가중치 | "출산·돌봄"처럼 수백 건에 걸리는 말은 보조 가중치를 낮게 두고, 검색어로 직접 들어왔을 때만 1.0 |
| 조사 제거 | "월세가"·"전기세는?"처럼 붙여 쓴 말도 사전에 닿습니다(한 글자 조사는 사전에 있는 말로 돌아갈 때만 뗌) |
| 사전에 없으면 그대로 | 지역명·숫자·제도명은 확장하지 않습니다 — 없는 주제를 만들어 내지 않습니다 |
| 상한 | 한 단어당 표기 6개까지(질의당 `LIKE` 폭주 방지) |

`search_subsidies` 응답에는 확장이 일어난 경우 `keyword_note_ko`(예: "동의어 확장: 병원비→의료비·진료비")가
붙습니다. 넓힌 결과는 질의어 일치 → 관련도 → 판정 순으로 줄을 세우므로, 원래 결과가 밀려나지 않습니다.

---

## 3-7. 행정개편·결과 상한 정리 (0.4.2)

라이브 전수검수에서 드러난 P0/P1 결함을 고친 버전입니다.

| 항목 | 0.4.1 | 0.4.2 |
|---|---|---|
| 결과 상한 | `search_subsidies` 가 서버에서 **50건으로 캡** | 최대 **200건** (웹 UI·API 동일) |
| 1단 탭 숫자 | 반환 목록(50건)을 세서 34/16 처럼 **할당량이 건수로 노출** | `kind_counts` — 상한 전 전체 집계 |
| 판정 진입 | '조건 확인 필요'가 50건 캡에 밀려 1~2건만 노출, 창업 트랙은 2단 필터 자체가 사라짐 | 판정별 전체 건수를 먼저 보여 주고, 목록에 없는 건수면 `verdict` 로 **서버 재조회**(예: 확인 필요 253건 전체) |
| 시·도 | 17개(개편 전) | **16개** — 2026-07-01 전남광주통합특별시 출범 |
| 인천 시·군·구 | 중구·동구·서해구 (개편 전) | 제물포구·영종구·서해구·**검단구** (+ 미추홀·연수·남동·부평·계양·강화·옹진) |
| 이전 주소 | — | `/regions/gwangju`·`/s/jeonnam` 등은 새 통합 페이지로 **301** |
| '전국' 오분류 | 천안복지재단·전주시복지재단·안산인재육성재단 등 109건이 전국으로 내려와 타지역 검색에 혼입 | 기관명의 시·군·구·시도·재단명으로 지역을 추론(막히면 `local_unresolved`), 전국은 진짜 전국 제도만 |
| `/s/` 브랜드 | `<title>` 이 `\| SUBSIDY-KR` | `\| GRNT` |
| 전송 크기 | 50건 그대로(~250KB)·압축 없음 | 200건을 **gzip** 으로 (~900KB→~76KB, HTML ~105KB→~28KB) |
| 404 | non-`/v1/` 도 raw JSON | 사람용 HTML 404(홈·주제·지역·가이드 링크) |

지역 택소노미에는 버전(`regions.SCHEMA_VERSION`)이 붙었습니다. 개편 전에 만든 `catalog.sqlite`
(지역 컬럼)는 로더가 자동으로 다시 만듭니다 — 그대로 두면 sido 로 거르는 SQL 이 새 지역 사용자를 놓칩니다.

---

## 3-10. 질문형 가이드 20종 추가·공개 문안 익명성 정리 (0.4.5)

가이드를 **61개 → 81개**로 늘렸습니다. 새 20개는 소상공인·청년·임신/출산·중소기업·창업자가
실제로 검색하는 질문이고, 기존 61개와 질문이 겹치지 않습니다.

| 분야 | 새 질문 |
|---|---|
| 주거 | 전세보증금 반환보증의 가입 주체·보증료, 청년 전세임대주택의 대기·후보 주택 요건 |
| 출산·가족 | 임산부 교통비(지자체 바우처) 신청·사용처, 배우자 출산휴가 급여 지급 주체, 양육수당과 보육료의 대체 관계 |
| 일자리 | 청년도전지원사업과 구직급여 중복 여부, 육아기 근로시간 단축 급여 요건 |
| 소득·생활비 | 국민연금 추납·임의계속가입, 근로장려금 기한 후 신청, 청년도약계좌 중도해지, 통신비 감면, 건강보험 피부양자 |
| 창업·소상공인 | 초기창업패키지 업력 기준, 사업주 장애인 고용지원, 폐업 시 4대보험·퇴직금 정리, 카드·결제 수수료 지원, 지원금 환수·정산, 중소기업 정책자금 심사 |
| 활용법 | 마감 임박 공고 확인(`deadline_calendar`), 공고문 읽는 순서 |

- 새 가이드도 **금액·수치를 고정하지 않습니다**(`test_guides_expansion_81.test_new_guides_do_not_fix_amounts`).
- `FAQPage`(질문 4개)·`BreadcrumbList` JSON-LD, `/sitemap.xml`, `/llms.txt`, 홈 푸터, `/v1/meta` 의 `guides.count`
  가 모두 자동으로 81개를 반영합니다.
- 공개 저장소 문안에서 외부 협업자 표기를 **중립 표현("외부 코드 검수 제보")** 으로 바꿨습니다
  (`README.md` 3-8절, `src/tests/test_lightweight_queries.py` 주석).

## 3-9. 무료 베타 유입 태그·생태계 링크 (0.4.4)

`POST /v1/inquiry` 에 **선택** 필드 `cohort`(별칭 `source`)를 더했습니다. 무료 베타 테스터나
소개 글(예: `citechart`)에서 온 문의를 나중에 구분해 셀 수 있게 하는 40자 이내 태그입니다.

```bash
curl -s -X POST https://grnt-kr.onrender.com/v1/inquiry \
  -H 'Content-Type: application/json' \
  -d '{"contact":"...","topic":"batch_report","cohort":"beta_pilot"}'
# → {"ok":true,"receipt":"I00001","topic":"batch_report","cohort":"beta_pilot", ...}
```

| 항목 | 동작 |
|---|---|
| 허용값 | 영문 소문자·숫자와 `.` `_` `:` `-`, 1~40자(대문자는 소문자로 정규화). 빈 값·미전송은 종전과 동일 |
| 저장 | `inquiries.cohort` (기존 DB는 기동 시 열만 자동 추가) |
| 사본·알림 | `GRNT_INQUIRY_SINK` JSONL 과 `GRNT_INQUIRY_WEBHOOK` 본문에 `cohort` 포함(웹훅의 `source:"grnt"` 는 서비스 이름으로 그대로) |
| 운영 요약 | `usage.inquiry_summary(store)` 의 `by_cohort` — 태그별 건수만 세고 연락처·내용은 읽지 않음(GRNT 는 별도 관리자 엔드포인트가 없어 DB·미러 파일·이 헬퍼로 확인) |
| 공개 통계 | `/v1/stats` 에는 넣지 않음(종전 익명 계약 유지) |
| 잘못된 값 | `400 invalid_cohort` + 한국어 안내, 저장하지 않음 |

웹 화면의 `같이 쓰는 서비스` 카드와 푸터에서는 CLNS(수입·유통)·FRNC(프랜차이즈)로 한 줄씩
이어집니다 — 세 서비스 모두 무료·회원가입 없음입니다. 웹 문의 카드도 `/?cohort=beta_pilot`
처럼 태그가 붙은 링크로 들어오면 그 값을 함께 보냅니다(형식이 틀리면 보내지 않음).

## 3-8. 메모리·속도·색인 정리 (0.4.3)

외부 코드 검수 제보로 들어온 긴급/높음/운영 개선점을 재검증해 고친 버전입니다.
Render 무료(0.1 vCPU·512MB)에서 **OOM 과 28초 지연**을 만들던 지점이 모두 사라졌습니다.

| 항목 | 0.4.2 | 0.4.3 |
|---|---|---|
| `/healthz` | `len(catalog.services)` 로 매 호출마다 SQLite 13,130행 재적재(라이브 10.4~14.0초) | `catalog.stats()` 캐시로 **수 ms** |
| 후보 목록 캐시 | 목록 **개수**만 32개 제한 → 지역·키워드를 바꿔 13~20회 검색하면 Service 객체 36,000개+(130MB+) | **담긴 객체 수 상한**(`POOL_CACHE_MAX_ITEMS`) LRU — 상한을 넘으면 오래된 목록부터 축출 |
| 판정 루프 | 후보 1.2만 건의 결과 dict(사유·안내문·지문)를 **전부 생성**해 한 번 검색에 100MB+ 피크 | `assess()` 로 (정렬 키, 판정)만 훑고, 화면에 돌려줄 줄만 `evaluate_service` 로 생성 |
| 프로필 없는 검색 | 후보 전부 판정 — 로컬 2.6초·라이브 28초 | 조건이 비면 후보가 모두 같은 판정이라, SQL 색인의 건수+종류별 상위만 읽음 — **로컬 0.11초** |
| pSEO 페이지 목록 | `memo["pseo_items"]` 가 Service 객체 목록 전체를 고정(118~171MB) | 페이지마다 **제도 id·건수만** 보관, 그릴 때 앞 60건만 로드(메모 1.5MB) |
| `/regions/{slug}` 집계 | `catalog.services` 로 1.3만 건 일괄 적재(첫 방문 40MB+) | 스트림 1회 + 시·도별 상위 8건만 유지(트레이스 피크 3.7MB) |
| 마감 캘린더 | 1.3만 건을 읽어 파이썬에서 마감일 비교 | SQL 색인 `deadline_end` 로 **기간에 걸리는 줄만** 읽음 |
| pSEO `<h1>` | 모든 페이지가 브랜드명(`GRNT · …`) | 페이지 주제(예: `청년 지원금`, `서울특별시 지자체 지원금 현황`) |
| `/s/seoul` ↔ `/regions/seoul` | 제목·의도가 거의 같음 | `/s/{시도}` = **지원금 목록**(대상·금액·기한), `/regions/{시도}` = **지자체 지원금 현황**(시·군·구별 건수·마감) + 상호 링크 |
| 동시 처리 | `ThreadingHTTPServer` 무제한 | 동시 처리 세마포어(기본 4) + IP별 분당 요청 상한(일반 300·무거운 120) — 넘으면 429/503, `/healthz` 는 예외 |
| 문의 유실 | 무료 플랜 재배포 시 SQLite 초기화 | 접수 로그(번호·주제만) + 선택 기능 `GRNT_INQUIRY_SINK`(JSONL) · `GRNT_INQUIRY_WEBHOOK`(알림) |

SQLite 색인에는 `benefit_kind`·`deadline_end` 열과 `index_schema` 버전이 붙었습니다. 예전 DB 는
로더가 자동으로 다시 만듭니다(없으면 경량 조회가 빈 결과를 냅니다).

환경변수(선택): `GRNT_MAX_CONCURRENCY`(기본 4) · `GRNT_RATE_LIMIT`(분당, 0이면 끔) ·
`GRNT_RATE_LIMIT_HEAVY` · `GRNT_INQUIRY_SINK` · `GRNT_INQUIRY_WEBHOOK`.

---

## 4. 일자별 스냅샷(변경 이력)

지원사업 공고는 기간·예산·자격이 조용히 바뀝니다. 그래서 동기화할 때마다
`data/gov24/snapshots/{YYYY-MM-DD}.json` 한 장과 `snapshots/index.json` 을 남깁니다.

- 스냅샷에는 비교용 필드만 저장합니다(이름·기관·분야·마감일·금액·대상·모집상태·지문).
  `fingerprint` 는 원문 전체를 정규화한 해시라 "바뀌었다/안 바뀌었다"가 한눈에 나옵니다.
- `compare_ledgers` 는 두 장을 비교해 **추가·삭제·변경(필드별 from→to)** 을 돌려줍니다.
- 같은 날 다시 돌리면 그날 스냅샷을 덮어쓰고, 비교 기준은 **직전 날짜**로 잡습니다.
- K-Startup 은 2016년부터 3만 건이 오고 서버가 기간 필터를 적용하지 않습니다. 그래서 받은 뒤
  `programs.is_current()` 로 **마감 30일 지난 공고**를 빼고 저장합니다(`--grace-days`, `--include-expired`).

```bash
PYTHONPATH=src python -m subsidy_kr.sync_gov24 --sources all     # 날마다 한 번
# → 오늘/어제 스냅샷이 쌓이면 compare_ledgers 가 변화를 알려 줍니다
```

스냅샷은 날마다 한 장씩 쌓입니다(현재 약 9~10MB/일, 전량 13,167건 기준). 그래서
`data/gov24/` 는 원본·캐시·스냅샷을 **커밋하지 않습니다**(`.gitignore`). 예외는 압축 카탈로그
`data/gov24/catalog.json.gz` 한 파일입니다 — 배포 환경이 샘플 대신 실데이터로 뜨게 하는
3.8MB 짜리 산출물입니다. `data/gov24/cache/` 는 git·Docker 양쪽에서 제외됩니다
(`.gitignore`·`.dockerignore`).

동기화 뒤 압축본을 갱신하려면(원본은 그대로 두고 같은 내용을 gzip 으로):

```bash
python - <<'PY'
import gzip, pathlib
src = pathlib.Path("data/gov24/catalog.json")
dst = src.with_suffix(".json.gz")
with src.open("rb") as f, gzip.GzipFile(dst, "wb", compresslevel=9, mtime=0) as g:
    g.write(f.read())
print(dst, dst.stat().st_size)
PY
```

### 4-1. 매일 자동 갱신 — `refresh_catalog`

`catalog.json.gz` 를 그대로 두면 마감된 공고가 "열림"으로 남고, `catalog.sqlite` 의 만료
플래그도 이미지를 구운 날에 머뭅니다. `refresh_catalog` 는 재수집 → **오늘 기준 만료 인덱스
재생성** → (내용이 바뀐 경우만) 압축본 갱신을 한 번에 처리합니다.

```bash
DATA_GO_KR_SERVICE_KEY=... PYTHONPATH=src python -m subsidy_kr.refresh_catalog   # 재수집+인덱스+압축본
PYTHONPATH=src python -m subsidy_kr.refresh_catalog --offline                     # 네트워크 없이 만료 인덱스만 회전
PYTHONPATH=src python -m subsidy_kr.refresh_catalog --dry-run --json              # 무엇이 바뀔지만 확인
```

- 재수집이 일부 실패해도 **기존 카탈로그를 보존**하고 진행합니다(부분 실패 허용).
  인증키가 없으면 자동으로 오프라인 경로로 떨어져 만료 인덱스만 다시 만듭니다.
  `sync_gov24` 의 7일 응답 캐시는 기본으로 무시하고 매번 새로 받습니다(`--ttl-days` 로 완화).
- 지자체 자체 복지포털(부평복지ON·인천 맞춤형수혜·인천 1인가구·서울 WIS·경기민원24·세종·브라보)
  도 함께 다시 받습니다. 포털 하나가 0건이면 **그 포털 항목만** 기존 것을 유지합니다
  (포털 개편·차단은 흔한 실패라, 조용히 카탈로그가 줄어드는 것을 막습니다). `--no-local` 로 끕니다.
- 지자체 포털 행은 서비스ID 접두어(`BOKJION`·`ICBENEFIT`·`IC1IN`·`SEOULWIS`·`GG24`·`SEJONG`·`BROSO`)
  로 구분해 같은 제도를 두 번 담지 않습니다.
- 압축본은 **내용이 바뀌었을 때만** 씁니다(압축을 풀어 비교 — gzip mtime·압축레벨 차이로
  매일 커밋이 생기는 일을 막습니다).
- 종료코드: `0` = 갱신 또는 인덱스 재생성 완료(부분 실패 포함), `1` = 쓸 카탈로그가 없음.
- `.github/workflows/refresh-catalog.yml` 이 매일 `0 19 * * *` UTC(04:00 KST)에 돌고,
  바뀐 `data/gov24/catalog.json.gz` 만 커밋합니다(`contents: write`). `catalog.sqlite`(49MB)는
  기본 커밋하지 않습니다 — 배포 때 압축본에서 다시 만들어지고, 매일 쌓으면 저장소가 1년에
  약 1.4GB 커집니다. 필요하면 워크플로를 수동 실행하며 `commit_sqlite` 를 켜면 됩니다.

---

## 5. 구조

```
subsidy-kr/                                     (패키지 경로는 그대로, 서비스명은 GRNT)
├── Dockerfile · render.yaml · server.json      배포·레지스트리 정의
├── sync_gov24.py                               편의 실행 파일
├── build/gen_regions.py                        시군구 명부 생성(개발용)
├── data/gov24/                                 catalog.json.gz(배포용 커밋) · 원본 catalog.json·snapshots/(로컬 전용)
└── src/
    ├── subsidy_kr/
    │   ├── engine.py          결정론 판정(개인 JA 코드 + 창업·기업 자격)
    │   ├── catalog.py         레코드 정규화·색인·샘플/실데이터 전환
    │   ├── conditions.py      JA 코드 표·상황 태그
    │   ├── programs.py        K-Startup·기업마당 → 판정용 레코드(업력·연령·대상·업종)
    │   ├── sample_data.py     내장 샘플 20건(개인)
    │   ├── sample_programs.py 내장 샘플 12건(창업·소상공인·기업·기업마당 형식)
    │   ├── gov24.py           15113968 클라이언트(키 마스킹·재시도)
    │   ├── startup.py         15125364 K-Startup 클라이언트
    │   ├── bizinfo.py         15157820 기업마당 클라이언트
    │   ├── datagokr.py        공통 전송·키 마스킹·응답 봉투 해석
    │   ├── sync_gov24.py      통합 동기화 CLI(+스냅샷)
    │   ├── refresh_catalog.py 자동 갱신(재수집 → 오늘 기준 만료 인덱스 → 압축본)
    │   ├── snapshots.py       일자별 스냅샷·변경 비교
    │   ├── cache.py           JSON 캐시(7일 TTL, 원자적 쓰기)
    │   ├── store.py           SQLite(스냅샷·익명 카운터·문의 접수)
    │   ├── deadlines.py       신청기한 자유 텍스트 파서
    │   ├── api.py             툴 9종 정의 + 사전 신청·문의 접수(`submit_inquiry`)
    │   ├── models.py          판정 등급 정의(네 단어)
    │   ├── agent_report.py    사업자·대리인 리포트(규모 판단·분류·CSV/인쇄)
    │   ├── batch_client.py    거래처 일괄 익명 매칭(CSV 경계·1페이지 요약·CSV)
    │   ├── mcp_http.py        JSON-RPC 2.0
    │   ├── mcp_stdio.py       stdio 전송
    │   ├── server.py          HTTP 라우팅
    │   ├── web_ui.py          인라인 CSS/JS 단일 페이지(3탭 + 푸터 위 문의 카드)
    │   ├── pseo.py            /s/ 주제·지역 페이지(thin content 규칙)
    │   ├── regions.py         시도·시군구 정규화(소관기관명→지역) + /regions/ 시·도별 허브
    │   ├── local_portals.py   지자체 자체 복지포털 수집(부평·인천·서울WIS·경기·세종 등)
    │   ├── guides.py          /guides/ 질문형 가이드 81개(FAQPage·실시간 공고 연결)
│   ├── synonyms.py        검색어 동의어 사전(생활어 ↔ 공고 용어, 가중치·직접 일치 우선)
    │   ├── static_files.py    robots·llms·sitemap·server-card
    │   ├── site_verification.py 검색엔진 소유확인 메타태그·확인 파일(환경변수)
    │   ├── usage.py           익명 일별 카운터 + 문의 폼 검증·저장 경계
    │   └── version.py         버전
    └── tests/                 unittest 33개 파일 · 612건
```

### 5-1. 응답 시간과 캐시

실데이터 13,167건에서는 요청마다 카탈로그를 다시 훑는 것이 느립니다(Render 무료 0.1 vCPU 에서
`search_subsidies` 한 번에 5.9초). 카탈로그는 읽기 전용이므로 다음을 한 번만 계산해 재사용합니다.

| 캐시 | 위치 | 아끼는 것 |
|---|---|---|
| 후보 목록(필터 조합별) | `engine._candidate_pool` | 매 호출 1.3만 건 필터링 |
| 판정 결과((프로필, 옵션)별 LRU, 반환 행 수 6,000개 상한) | `engine._ResultCache` | 같은 조건 재요청 전부 |
| 제도별 선정기준·소득·상황 요건 문구 | `engine._criteria_rules` 등 | 프로필과 무관한 문자열·라벨 재계산 |
| `/s/` 주제·지역 페이지 목록 | `pseo.items` | 페이지·사이트맵마다 35번 훑던 것 |

**판정은 바뀌지 않습니다.** `src/tests/test_search_cache.py` 가 캐시 도입 전과 같은 계산을
그대로 다시 구현해, 샘플과 실데이터(전국 1.3만 건 포함)에서 결과가 완전히 같은지 비교합니다.

---

## 6. 데이터와 정직한 한계

| 데이터 | 식별자 | 이용 조건 |
|---|---|---|
| 행정안전부 대한민국 공공서비스(혜택) 정보 | `15113968` | 이용허락범위 **제한 없음** |
| 창업진흥원 K-Startup 지원사업 공고 | `15125364` | 이용허락범위 **제한 없음** |
| 중소벤처기업부 중소기업 지원사업 공고(기업마당) | `15157820` | **출처표시·변경금지** — 원문 문구 보존 + 출처 표시 |

- 개발계정 호출 한도는 데이터셋마다 10,000건/일입니다. K-Startup 은 전량 31페이지(1,000건/페이지)로 받습니다.
- 내장 샘플(`catalog_state: "sample"`)은 **필드·코드 구조만 실제와 같고 금액·기한은 예시값**입니다. 화면·API 응답이 항상 `data_state` 와 함께 이 사실을 밝힙니다.
- 지자체 제도의 `선정기준` 공백은 원본 그대로 둡니다. 이 서비스의 가치는 그 공백을 **메우는 척하지 않는 것**입니다.
- 창업·기업 공고는 자격 요건이 **서술형**인 경우가 많습니다. 구조화하지 못한 요건은 `check_needed` 로 남기고 원문을 안내합니다.
- 신청 대행·법률 자문이 아니며, 최종 수급·선정 여부는 소관기관 심사로 결정됩니다.
- 신청기한은 자유 텍스트라, 확실히 읽히는 날짜만 구조화하고 나머지는 `unknown` 으로 둡니다.

## 7. 개인정보

| 항목 | 처리 |
|---|---|
| 판정 입력의 이름·주민등록번호·전화번호 | 받지 않음 |
| 나이·지역·소득구간·임신/장애 여부, 사업자 조건(업력·업종) | 요청 처리 중 메모리에서만 사용, **저장 안 함** |
| 쿠키·localStorage | 쓰지 않음 |
| 서버 로그 | 경로·상태코드만(질의문·본문 미기록) |
| 통계 | 날짜·경로·툴명·판정 등급·0건/오류 **횟수**만 |
| 0건 검색어 | **결과가 0건이었던 검색어만**, 전화번호·주민등록번호·이메일·URL·@핸들·2자리 이상 숫자·시·도/시·군·구 이름을 지운 뒤 최대 30자 |
| 스냅샷 | 제도 정보만(프로필·질의문 없음) |
| 문의 카드에 직접 적은 연락처 | 회신 목적으로만 별도 표 `inquiries` 에 저장(최대 180일 뒤 삭제), **응답에 되돌리지 않고 `/v1/stats` 에 넣지 않음** |
| 외부 전송 | 없음(서버가 공공 API를 대신 호출하지 않음 — 동기화는 오프라인 배치) |

공고문 원문에 포함된 **기관 담당자 이메일·전화**는 공개된 기관 연락처로, 사용자 개인정보와 다릅니다.
`src/`·문서·설정에는 이메일·전화·실명을 쓰지 않으며 테스트가 이를 검사합니다.
다만 그 연락처가 담긴 동기화 산출물(`data/gov24/`)은 저장소·이미지에 넣지 않습니다.

검색어는 **결과가 0건일 때만** 남깁니다 — 결과가 있던 검색어는 저장하지 않습니다. 남길 때도
숫자(나이·연도)·전화번호·주민번호·이메일·URL·@핸들과 시·도/시·군·구 이름을 지우고 30자로
자릅니다(예: `인천 서구 청년 월세` → `청년 월세`). 이 집계는 "사람들이 찾는데
없는 제도"를 드러내 다음 데이터 확충의 근거로만 쓰이고, `/v1/stats` 에 일별 상위 20개로
노출됩니다. 프로필 입력값(나이·소득구간·임신 여부)은 이 경로에서도 읽지 않습니다.
사람 이름·상호는 낱말만으로 판별할 수 없어 지우지 못합니다(입력란에 제도·분야 낱말 예시를 둡니다).

## 8. 배포

```bash
docker build -t grnt . && docker run -p 8787:8787 grnt   # 기본은 내장 샘플(32건)
```

**Render** — `render.yaml` Blueprint 로 그대로 배포합니다(서비스명 `grnt-kr` → `https://grnt-kr.onrender.com`, Docker, free, singapore,
healthCheck `/healthz`). 서버는 공공 API 키가 필요 없고, `.env` 없이도 뜹니다.

무료 플랜은 영구 디스크가 없어 재배포 시 익명 카운터·스냅샷과 **문의 접수분**이 초기화됩니다.
외부 유료 DB 없이 통계·문의를 살리려면 영속 디스크(예: Render Disk)를 붙이고 `GRNT_STATS_PATH`
를 그 안의 파일로 지정하세요. 백업은 `GET /v1/stats?days=30` 의 JSON 을 받아 두거나 그 SQLite
파일을 복사하면 됩니다(엔드포인트 구조는 그대로라 기존 소비자가 깨지지 않습니다).

| 항목 | 값 |
|---|---|
| Runtime | Docker (`./Dockerfile`, context `.`) |
| Health check | `/healthz` |
| 환경변수(기본) | `PUBLIC_BASE_URL=https://grnt-kr.onrender.com` · `SUBSIDY_KR_DATA=/app/data/gov24` · `SUBSIDY_KR_DB=/app/data/app.sqlite` |
| 환경변수(실데이터 동기화 시에만) | `DATA_GO_KR_SERVICE_KEY` — 서버 기동에는 불필요, Render Shell 동기화에만 |
| 환경변수(검색엔진 소유확인, 선택) | `GOOGLE_SITE_VERIFICATION` · `NAVER_SITE_VERIFICATION` · `SITE_VERIFICATION_FILES` — 아래 8-1 |
| 환경변수(통계·문의 보존, 선택) | `GRNT_STATS_PATH` — 익명 카운터와 문의 접수를 따로 둘 SQLite 경로. 비어 있으면 `SUBSIDY_KR_DB` |
| 환경변수(동시 처리·빈도 상한, 선택) | `GRNT_MAX_CONCURRENCY`(기본 4) · `GRNT_RATE_LIMIT`(분당 300) · `GRNT_RATE_LIMIT_HEAVY`(분당 120) — `/healthz` 는 제외 |
| 환경변수(문의 유실 대비, 선택) | `GRNT_INQUIRY_SINK`(JSONL 파일) · `GRNT_INQUIRY_WEBHOOK`(알림 URL) |

### 8-1. 검색엔진 소유확인(구글 서치콘솔·네이버 서치어드바이저)

코드 수정 없이 환경변수만 넣고 재시작하면 확인이 끝납니다. 아무 것도 넣지 않으면 응답은 이전과
완전히 같습니다.

| 환경변수 | 값 | 결과 |
|---|---|---|
| `GOOGLE_SITE_VERIFICATION` | 구글 서치콘솔이 발급한 토큰(`content` 값) | `/`·`/s/`·`/s/{slug}` head 에 `<meta name="google-site-verification" content="...">` |
| `NAVER_SITE_VERIFICATION` | 네이버 서치어드바이저 토큰 | 같은 head 에 `<meta name="naver-site-verification" content="...">` |
| `SITE_VERIFICATION_FILES` | JSON 한 줄. 예: `{"naver1a2b3c.html": "naver-site-verification: naver1a2b3c.html"}` | 루트 경로(`/naver1a2b3c.html`)로 파일 본문을 서빙(GET·HEAD) |

로컬에서 확인:

```bash
GOOGLE_SITE_VERIFICATION=abc123 SITE_VERIFICATION_FILES='{"g1.html":"google-site-verification: g1.html"}' \
  PYTHONPATH=src python -m subsidy_kr.server
curl -s localhost:8787/ | grep site-verification
curl -s localhost:8787/g1.html
```

배포 직후 첫 요청은 sleep 에서 깨어나 30~60초 걸릴 수 있고, `/healthz` 의 `catalog_state` 가
`sample` 이면 아직 실데이터가 없다는 뜻입니다. 실데이터는 Render Shell 에서
`PYTHONPATH=/app/src python -m subsidy_kr.sync_gov24 --sources all` 로 한 번 받습니다(무료 플랜은
영구 디스크가 없어 재배포 시 초기화됩니다 — 그때는 다시 동기화하거나 유료 디스크를 붙입니다).

`server.json` 의 `name`(`io.github.CLNS-KR/grnt`)·`repository` 는 실제 GitHub 소유자
(`CLNS-KR/GRNT`)에 맞춰 두었고, 공개 주소(`websiteUrl`·`remotes`)는 `https://grnt-kr.onrender.com` 입니다.
MCP Registry 는 그 주소의 `/healthz` 가 살아 있는 것을 확인한 뒤 `v0.4.7` 태그로 게시합니다.

## 9. 라이선스

MIT (아래 LICENSE). 공공데이터 자체의 이용 조건은 원 제공기관(행정안전부·창업진흥원·중소벤처기업부) 안내를 따릅니다.
