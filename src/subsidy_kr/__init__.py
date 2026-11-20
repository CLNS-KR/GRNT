"""GRNT — 개인·창업 통합 지원금 자격 판정기 (MVP).

구성
----
- `engine`       결정론적 자격 판정(개인 JA 코드 + 창업·기업 공고 자격)
- `catalog`      내장 샘플 ↔ 동기화 실데이터, 두 트랙 통합
- `programs`     K-Startup·기업마당 공고 → 판정용 레코드(업력·연령·대상·업종)
- `gov24`        15113968 보조금24 API 클라이언트
- `startup`      15125364 K-Startup API 클라이언트
- `bizinfo`      15157820 기업마당 API 클라이언트
- `datagokr`     세 API 공통 전송·키 마스킹·응답 봉투 해석
- `sync_gov24`   통합 동기화 CLI(+일자별 스냅샷)
- `snapshots`    일자별 카탈로그 스냅샷·변경 비교
- `api`          MCP/JSON 툴 9종
- `agent_report`  사업자·대리인 리포트(거래처 1곳)
- `batch_client`  거래처 일괄 익명 매칭(50~300곳)
- `server`       웹 UI · JSON API · MCP(Streamable HTTP)
- `mcp_stdio`    로컬 실행형 MCP(stdio)
"""
from .version import (SERVICE_NAME, SERVICE_SUBTITLE_EN, SERVICE_TAGLINE, SERVICE_TITLE_KO,
                      __version__)

__all__ = ["__version__", "SERVICE_NAME", "SERVICE_TITLE_KO", "SERVICE_TAGLINE",
           "SERVICE_SUBTITLE_EN"]
