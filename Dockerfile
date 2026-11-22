# GRNT · 개인·창업 통합 지원금 판정기
# 서버 이미지 — 표준 라이브러리만 쓰므로 pip install 단계가 없습니다.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="GRNT" \
      org.opencontainers.image.description="Korean personal + startup/SME grant eligibility checker (web UI + JSON API + MCP)" \
      org.opencontainers.image.version="0.4.9"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8787 \
    SUBSIDY_KR_DATA=/app/data/gov24 \
    SUBSIDY_KR_DB=/app/data/app.sqlite

WORKDIR /app

RUN adduser --disabled-password --gecos "" --uid 10001 app \
    && mkdir -p /app/data/gov24

COPY --chown=app:app src/ /app/src/
# 공유 미리보기(og:image) — static/og.png(1200×630). 파일이 없어도 서버는 표준 라이브러리로
# 만든 대체 PNG 를 내려보내지만, 이미지에 넣어 두면 브랜드 카드가 그대로 나간다.
COPY --chown=app:app static/ /app/static/
# data/ 를 통째로 넣는다 — 저장소에 커밋된 data/gov24/catalog.json.gz(약 3.8MB) 가
# 함께 들어가서 이미지가 샘플이 아니라 12,429건 실데이터로 뜬다. 원본 catalog.json 이
# 있으면 로더가 그쪽을 먼저 읽는다. (캐시·DB는 .dockerignore 가 제외)
COPY --chown=app:app data/ /app/data/

RUN chown -R app:app /app/data
USER app

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8787')+'/healthz', timeout=4)"

# 서버는 공공 API 키가 필요 없습니다(공개 판정 전용). 실데이터 동기화는 빌드 후 별도 실행합니다.
CMD ["python", "-m", "subsidy_kr.server"]
