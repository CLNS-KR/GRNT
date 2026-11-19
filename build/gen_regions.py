#!/usr/bin/env python3
"""`src/subsidy_kr/regions_data.py` 생성 스크립트 (개발용, 배포 이미지에는 넣지 않습니다).

원본: 국가공간정보포털(V-World) 행정구역 경계 시군구 GeoJSON (2023-07-29 배포본)
      https://github.com/KnellBalm/kr-admin-geojson (공개 미러)
사용: python build/gen_regions.py [--source URL] [--out PATH]
결과: 시도 17 × 시군구 250건의 (코드, 이름) 표만 남깁니다(경계·좌표 없음, 약 12KB).
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import urllib.request

DEFAULT_SOURCE = "https://raw.githubusercontent.com/KnellBalm/kr-admin-geojson/main/sig.geojson"
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "src", "subsidy_kr", "regions_data.py")

HEADER = '''"""시도·시군구 명부(행정표준코드 앞 5자리).

출처: 국가공간정보포털(V-World) 행정구역 경계 2023-07-29 배포본의 시군구 250건 중
코드·한글명만 추출해 내장했습니다(경계·좌표 없음). 행정구역 개편 시 갱신이 필요하며,
`regions.py` 의 별칭 표가 개편 전후 이름을 함께 받아 줍니다.
생성 스크립트: `build/gen_regions.py` (개발용, 배포 이미지에는 포함하지 않음)
"""
from __future__ import annotations

# {시도: [(시군구코드 5자리, 시군구명), ...]}
SIGUNGU_BY_SIDO = {
'''


def build(source: str) -> str:
    with urllib.request.urlopen(source, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = sorted((feature["properties"]["SIG_CD"],
                   feature["properties"]["SIDO_NM"],
                   feature["properties"]["SIG_KOR_NM"])
                  for feature in payload["features"])
    grouped: "collections.OrderedDict[str, list]" = collections.OrderedDict()
    for code, sido, name in rows:
        grouped.setdefault(sido, []).append((code, name))
    body = [HEADER]
    for sido, items in grouped.items():
        body.append(f'    "{sido}": [\n')
        for code, name in items:
            body.append(f'        ("{code}", "{name}"),\n')
        body.append("    ],\n")
    body.append("}\n")
    return "".join(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="시군구 명부 생성")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()
    text = build(args.source)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"wrote {args.out} ({len(text):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
