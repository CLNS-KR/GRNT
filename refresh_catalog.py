#!/usr/bin/env python3
"""편의용 실행 파일 — `python refresh_catalog.py` 로도 자동 갱신할 수 있게 감싼 것입니다.

실제 구현은 `src/subsidy_kr/refresh_catalog.py` 에 있고, 권장 실행 방법은 다음과 같습니다.

    PYTHONPATH=src python -m subsidy_kr.refresh_catalog --help

cron 예시(매일 04:10 KST):
    10 4 * * * cd /srv/GRNT && DATA_GO_KR_SERVICE_KEY=... python refresh_catalog.py --json
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from subsidy_kr.refresh_catalog import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
