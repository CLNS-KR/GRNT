"""검증용 내장 샘플 — 창업·소상공인·기업 지원사업 12건.

왜 내장하나
-----------
`15125364`(K-Startup)·`15157820`(기업마당) 활용신청 전이거나 네트워크가 없어도
**기업 트랙 판정·검색·기한 캘린더·시계열 비교**를 오프라인으로 검증하기 위해서입니다.

원칙
----
- 필드 이름은 **실제 API 출력규격 그대로**입니다(K-Startup 은 `biz_pbanc_nm`·`biz_enyy`…,
  기업마당은 `pblancNm`·`reqstBeginEndDe`…). 그래서 샘플도 실데이터와 **같은 정규화 경로**를
  지납니다(`programs.normalize_kstartup` / `normalize_bizinfo`).
- 제도별 금액·기한·문의처는 **예시값**입니다. 응답은 항상 `data_state: "sample"` 로 밝힙니다.
- 일부러 여러 모양을 넣었습니다: 예비창업자 전용, 업력 제한, 연령 제한, 지자체 한정,
  모집 마감, '예산 소진 시까지' 기한, 구조화가 안 되는 자유서술 공고.
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import bizinfo, programs, startup

# --- K-Startup(15125364) 출력규격 그대로 ------------------------------------
SAMPLE_KSTARTUP: List[Dict[str, Any]] = [
    {
        "pbanc_sn": "900001",
        "biz_pbanc_nm": "2026년 예비창업패키지",
        "pbanc_ntrp_nm": "중소벤처기업부",
        "sprv_inst": "창업진흥원",
        "supt_biz_clsfc": "사업화",
        "aply_trgt": "일반인",
        "aply_trgt_ctnt": "공고일 기준 사업자등록이 없는 예비창업자",
        "supt_regin": "전국",
        "pbanc_rcpt_bgng_dt": "20261103",
        "pbanc_rcpt_end_dt": "20261205",
        "biz_enyy": "예비창업자",
        "biz_trgt_age": "만 20세 이상 ~ 만 39세 이하",
        "prfn_matr": "여성창업자, 사회적경제기업, 지역특화산업 가점",
        "rcrt_prgs_yn": "Y",
        "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900001",
        "biz_aply_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900001",
        "aply_mthd_onli_rcpt_istc": "K-Startup 온라인 접수",
        "refrnc_nm": "창업진흥원 사업문의 044-000-0000(예시)",
        "supt_biz_ctnt": "사업화 자금 최대 1억 원(평균 5천만 원)과 멘토링·교육(예시)",
    },
    {
        "pbanc_sn": "900002",
        "biz_pbanc_nm": "2026년 초기창업패키지",
        "pbanc_ntrp_nm": "중소벤처기업부",
        "sprv_inst": "창업진흥원",
        "supt_biz_clsfc": "사업화",
        "aply_trgt": "일반인",
        "aply_trgt_ctnt": "창업 3년 이내 창업기업",
        "supt_regin": "전국",
        "pbanc_rcpt_bgng_dt": "20261110",
        "pbanc_rcpt_end_dt": "20261128",
        "biz_enyy": "3년미만",
        "biz_trgt_age": "",
        "prfn_matr": "투자유치 실적, 기술보호 전략 우수",
        "rcrt_prgs_yn": "Y",
        "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900002",
        "biz_aply_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900002",
        "aply_mthd_onli_rcpt_istc": "K-Startup 온라인 접수",
        "refrnc_nm": "창업진흥원 사업문의 044-000-0001(예시)",
        "supt_biz_ctnt": "사업화 자금 최대 1억 원, 성장 지원 프로그램(예시)",
    },
    {
        "pbanc_sn": "900003",
        "biz_pbanc_nm": "2026년 청년창업사관학교 입교생 모집",
        "pbanc_ntrp_nm": "중소벤처기업부",
        "sprv_inst": "창업진흥원",
        "supt_biz_clsfc": "시설·공간·보육",
        "aply_trgt": "일반인",
        "aply_trgt_ctnt": "만 39세 이하 예비창업자 또는 창업 3년 이내 창업기업",
        "supt_regin": "전국",
        "pbanc_rcpt_bgng_dt": "20261201",
        "pbanc_rcpt_end_dt": "20261224",
        "biz_enyy": "3년미만",
        "biz_trgt_age": "만 20세 이상 ~ 만 39세 이하",
        "prfn_matr": "기술창업, 특허 보유",
        "rcrt_prgs_yn": "Y",
        "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900003",
        "biz_aply_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900003",
        "aply_mthd_onli_rcpt_istc": "K-Startup 온라인 접수",
        "refrnc_nm": "청년창업사관학교 044-000-0002(예시)",
        "supt_biz_ctnt": "사무공간, 사업화 자금 최대 1억 원, 멘토링(예시)",
    },
    {
        "pbanc_sn": "900004",
        "biz_pbanc_nm": "2026년 소상공인 일반경영안정자금",
        "pbanc_ntrp_nm": "중소벤처기업부",
        "sprv_inst": "소상공인시장진흥공단",
        "supt_biz_clsfc": "정책자금",
        "aply_trgt": "일반인",
        "aply_trgt_ctnt": "소상공인(연 매출 10억 원 이하 개인사업자)",
        "supt_regin": "전국",
        "pbanc_rcpt_bgng_dt": "20260102",
        "pbanc_rcpt_end_dt": "",
        "biz_enyy": "",
        "biz_trgt_age": "",
        "prfn_matr": "성실상환자, 고용유지 우수",
        "rcrt_prgs_yn": "Y",
        "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900004",
        "biz_aply_url": "",
        "aply_mthd_onli_rcpt_istc": "소상공인정책자금 온라인 신청",
        "refrnc_nm": "소상공인시장진흥공단 1357(예시)",
        "supt_biz_ctnt": "운영자금 최대 7천만 원, 연 2%대 융자(예시). 예산 소진 시 마감",
    },
    {
        "pbanc_sn": "900005",
        "biz_pbanc_nm": "2026년 소상공인 디지털 전환 지원",
        "pbanc_ntrp_nm": "중소벤처기업부",
        "sprv_inst": "소상공인시장진흥공단",
        "supt_biz_clsfc": "사업화",
        "aply_trgt": "일반인",
        "aply_trgt_ctnt": "소상공인",
        "supt_regin": "전국",
        "pbanc_rcpt_bgng_dt": "20261110",
        "pbanc_rcpt_end_dt": "20261212",
        "biz_enyy": "",
        "biz_trgt_age": "",
        "prfn_matr": "온라인 판로 미보유, 청년 소상공인",
        "rcrt_prgs_yn": "Y",
        "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900005",
        "biz_aply_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900005",
        "aply_mthd_onli_rcpt_istc": "온라인 접수",
        "refrnc_nm": "소상공인 디지털지원팀 044-000-0005(예시)",
        "supt_biz_ctnt": "디지털 기기·솔루션 도입비 최대 300만 원(예시)",
    },
    {
        "pbanc_sn": "900006",
        "biz_pbanc_nm": "2026년 인천 청년창업 지원금",
        "pbanc_ntrp_nm": "인천광역시",
        "sprv_inst": "인천테크노파크",
        "supt_biz_clsfc": "사업화",
        "aply_trgt": "일반인",
        "aply_trgt_ctnt": "인천에 사업장을 둔 만 39세 이하 예비창업자 또는 창업 3년 이내 창업기업",
        "supt_regin": "인천",
        "pbanc_rcpt_bgng_dt": "20261117",
        "pbanc_rcpt_end_dt": "20261218",
        "biz_enyy": "3년미만",
        "biz_trgt_age": "만 20세 이상 ~ 만 39세 이하",
        "prfn_matr": "인천 거주 1년 이상",
        "rcrt_prgs_yn": "Y",
        "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900006",
        "biz_aply_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900006",
        "aply_mthd_onli_rcpt_istc": "인천스타트업파크 온라인 접수",
        "refrnc_nm": "인천창업지원센터 032-000-0006(예시)",
        "supt_biz_ctnt": "사업화 자금 최대 5천만 원(예시)",
    },
    {
        "pbanc_sn": "900007",
        "biz_pbanc_nm": "2026년 경기도 스타트업 육성 지원",
        "pbanc_ntrp_nm": "경기도",
        "sprv_inst": "경기도경제과학진흥원",
        "supt_biz_clsfc": "멘토링·컨설팅",
        "aply_trgt": "일반인",
        "aply_trgt_ctnt": "경기도 소재 창업 7년 이내 중소기업",
        "supt_regin": "경기",
        "pbanc_rcpt_bgng_dt": "20261026",
        "pbanc_rcpt_end_dt": "20261106",
        "biz_enyy": "7년미만",
        "biz_trgt_age": "",
        "prfn_matr": "지역 전략산업",
        "rcrt_prgs_yn": "N",
        "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900007",
        "biz_aply_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900007",
        "aply_mthd_onli_rcpt_istc": "경기스타트업플랫폼 온라인 접수",
        "refrnc_nm": "경기도경제과학진흥원 031-000-0007(예시)",
        "supt_biz_ctnt": "멘토링·컨설팅, 판로 지원(예시). 모집 마감",
    },
    {
        "pbanc_sn": "900008",
        "biz_pbanc_nm": "2026년 TIPS 창업팀 지원",
        "pbanc_ntrp_nm": "중소벤처기업부",
        "sprv_inst": "한국엔젤투자협회",
        "supt_biz_clsfc": "R&D",
        "aply_trgt": "일반인",
        "aply_trgt_ctnt": "창업 7년 이내 기술기반 창업기업",
        "supt_regin": "전국",
        "pbanc_rcpt_bgng_dt": "20261101",
        "pbanc_rcpt_end_dt": "20261215",
        "biz_enyy": "7년미만",
        "biz_trgt_age": "",
        "prfn_matr": "민간 투자 유치, 기술성 평가 우수",
        "rcrt_prgs_yn": "Y",
        "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900008",
        "biz_aply_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900008",
        "aply_mthd_onli_rcpt_istc": "TIPS 운영사 추천 후 온라인 접수",
        "refrnc_nm": "TIPS 운영본부 044-000-0008(예시)",
        "supt_biz_ctnt": "R&D 최대 5억 원, 창업사업화 1억 원(예시)",
    },
    {
        "pbanc_sn": "900009",
        "biz_pbanc_nm": "2026년 1인 창조기업 지원센터 입주 모집",
        "pbanc_ntrp_nm": "중소벤처기업부",
        "sprv_inst": "창업진흥원",
        "supt_biz_clsfc": "시설·공간·보육",
        "aply_trgt": "일반인",
        "aply_trgt_ctnt": "예비창업자 또는 1인 창조기업",
        "supt_regin": "전국",
        "pbanc_rcpt_bgng_dt": "20261115",
        "pbanc_rcpt_end_dt": "20261210",
        "biz_enyy": "예비창업자",
        "biz_trgt_age": "",
        "prfn_matr": "지식서비스 분야",
        "rcrt_prgs_yn": "Y",
        "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900009",
        "biz_aply_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=900009",
        "aply_mthd_onli_rcpt_istc": "센터별 온라인 접수",
        "refrnc_nm": "1인창조기업지원센터 044-009-0009(예시)",
        "supt_biz_ctnt": "보육실, 컨설팅, 제작공간(예시)",
    },
]

# --- 기업마당(15157820) 출력규격 그대로 ------------------------------------
SAMPLE_BIZINFO: List[Dict[str, Any]] = [
    {
        "pblancId": "PBLN_900000000000010",
        "pblancNm": "2026년 중소기업 수출바우처 참여기업 모집",
        "jrsdInsttNm": "중소벤처기업부",
        "excInsttNm": "중소벤처기업진흥공단",
        "bsnsSumryCn": "수출 준비 중인 중소기업에 바우처 형태로 마케팅·인증·물류 서비스를 지원합니다.",
        "pldirSportRealmLclasCodeNm": "수출",
        "reqstBeginEndDe": "2026. 11. 4. ~ 2026. 12. 3.",
        "trgetNm": "중소기업",
        "hashtags": "수출,전국,제조업,중소기업",
        "reqstMthPapersCn": "수출바우처 통합관리시스템 온라인 접수",
        "refrncNm": "중소벤처기업진흥공단 수출지원팀 055-000-0010(예시)",
        "pblancUrl": "https://www.bizinfo.go.kr/sii/900000000000010",
        "rceptEngnHmpgUrl": "https://www.bizinfo.go.kr/sii/900000000000010",
        "creatPnttm": "2026-11-04 09:00:00",
        "updtPnttm": "2026-11-04 09:00:00",
        "inqireCo": 1200,
    },
    {
        "pblancId": "PBLN_900000000000011",
        "pblancNm": "2026년 서울시 소상공인 경영안정자금",
        "jrsdInsttNm": "서울특별시",
        "excInsttNm": "서울신용보증재단",
        "bsnsSumryCn": "서울 소재 소상공인의 운영자금 대출 이자를 지원합니다.",
        "pldirSportRealmLclasCodeNm": "금융",
        "reqstBeginEndDe": "예산 소진시까지",
        "trgetNm": "소상공인",
        "hashtags": "금융,서울,소상공인",
        "reqstMthPapersCn": "서울신용보증재단 지점 방문 또는 온라인 접수",
        "refrncNm": "서울신용보증재단 02-000-0011(예시)",
        "pblancUrl": "https://www.bizinfo.go.kr/sii/900000000000011",
        "rceptEngnHmpgUrl": "",
        "creatPnttm": "2026-10-20 10:00:00",
        "updtPnttm": "2026-11-12 15:20:00",
        "inqireCo": 5400,
    },
    {
        "pblancId": "PBLN_900000000000012",
        "pblancNm": "2026년 여성기업 창업·경영 지원사업",
        "jrsdInsttNm": "중소벤처기업부",
        "excInsttNm": "한국여성경제인협회",
        "bsnsSumryCn": "여성 예비창업자와 여성기업에 창업 교육·멘토링·판로를 지원합니다. 자세한 선정 기준은 공고문을 확인하세요.",
        "pldirSportRealmLclasCodeNm": "경영",
        "reqstBeginEndDe": "차수별 상이",
        "trgetNm": "중소기업",
        "hashtags": "경영,전국,여성기업,창업",
        "reqstMthPapersCn": "이메일 접수 및 협회 홈페이지 접수",
        "refrncNm": "한국여성경제인협회 02-000-0012(예시)",
        "pblancUrl": "https://www.bizinfo.go.kr/sii/900000000000012",
        "rceptEngnHmpgUrl": "https://www.bizinfo.go.kr/sii/900000000000012",
        "creatPnttm": "2026-11-06 11:00:00",
        "updtPnttm": "2026-11-06 11:00:00",
        "inqireCo": 830,
    },
]


def records() -> List[Dict[str, Any]]:
    """정규화된 샘플 레코드(샘플 표시를 붙여서)."""
    out: List[Dict[str, Any]] = []
    for row in SAMPLE_KSTARTUP:
        record = programs.normalize_kstartup(row)
        record["source"] = "sample"
        record["extra"] = {**record.get("extra", {}), "sample_from": "kstartup"}
        out.append(record)
    for row in SAMPLE_BIZINFO:
        record = programs.normalize_bizinfo(row)
        record["source"] = "sample"
        record["extra"] = {**record.get("extra", {}), "sample_from": "bizinfo"}
        out.append(record)
    return out


def services() -> List[Dict[str, Any]]:
    """복사본(호출부가 원본을 고치지 않게)."""
    return [dict(item) for item in records()]


def meta() -> Dict[str, Any]:
    return {
        "business_dataset_id": "SAMPLE-STARTUP-2026-11-19",
        "business_note_ko": (
            "창업·소상공인 샘플은 K-Startup(15125364)·기업마당(15157820) 출력규격 그대로 "
            "작성했고, 금액·기한·문의처는 예시값입니다. 활용신청 후 "
            "`python -m subsidy_kr.sync_gov24 --sources all` 로 실데이터를 받으면 대체됩니다."
        ),
    }


# 정규화 경로가 실제 클라이언트와 같은지 스스로 확인할 수 있게 남겨 둔다.
NORMALIZERS = (startup.DATASET_ID, bizinfo.DATASET_ID)
