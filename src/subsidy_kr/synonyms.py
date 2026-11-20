"""검색어 확장 — 사람이 쓰는 말을 공고문의 말로 잇는 동의어 사전.

왜 필요한가
-----------
공고문은 "주거비", "임차료", "에너지바우처"처럼 제도 용어로 적혀 있는데, 사람은
"월세", "전기세", "병원비"처럼 생활어로 검색합니다. 검색이 단어 그대로의 부분 일치만
보면 생활어 질의는 0~1건에서 멈춥니다. 이 모듈이 그 간격을 메웁니다.

원칙
----
1. **직접 일치가 먼저**: 확장어는 가중치가 낮아, 같은 조건이면 질의어를 그대로 담은
   공고가 항상 위에 옵니다(과매칭으로 원래 결과가 밀려나지 않게).
2. **넓은 말은 낮은 가중치**: "출산"·"돌봄"처럼 수백 건에 걸리는 말은 보조 가중치를
   낮게 두고, 검색어로 직접 들어왔을 때만 1.0을 줍니다.
3. **조사·문장부호 제거**: "월세가", "전기세는?"처럼 붙여 쓴 말도 사전에 닿게 합니다.
4. **사전에 없으면 그대로**: 사전에 없는 말(지역명·숫자·제도명)은 확장하지 않습니다.
   확장은 되돌릴 수 없는 판단이 아니라 검색의 재현율을 넓히는 장치이므로, 여기에 없는
   주제는 조용히 원래 동작(부분 일치)으로 남깁니다.

가중치는 0~1 사이이고, 점수는 정수로 돌려줍니다(정렬 키로 쓰기 위함).
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

#: 한 단어에서 만들 수 있는 표기 수 상한(질의당 SQL LIKE 폭주 방지).
MAX_VARIANTS = 6

#: 두 글자 이상 조사·어미 — 형태가 분명해 그대로 떼어 낸다.
JOSA_LONG: Tuple[str, ...] = (
    "으로부터", "에서부터", "이라고", "이라고는", "에게서", "으로서", "으로써",
    "에서는", "에게는", "한테는", "부터는", "까지는", "보다는", "처럼은",
    "으로", "에서", "에게", "한테", "부터", "까지", "보다", "처럼", "이나", "이라",
    "이며", "이고", "이다", "입니다", "이에요", "예요", "에는", "에도", "라고",
)
#: 한 글자 조사 — "제도"의 '도'처럼 낱말의 일부일 수 있어, 사전에 있는 말로 돌아갈 때만 뗀다.
JOSA_SHORT: Tuple[str, ...] = (
    "은", "는", "이", "가", "을", "를", "도", "에", "의", "로", "만", "와", "과",
    "랑", "나", "께",
)

_PUNCT = " \t\r\n\"'`“”‘’«»()[]{}<>,.;:!?·…~-—_/\\|@#$%^&*+=※"

#: 동의어 묶음 — (표기, 보조 가중치). 보조 가중치는 "다른 말로 검색했을 때" 쓰인다.
#: 그 말로 직접 검색하면 1.0이 된다.
CLUSTERS: Tuple[Tuple[Tuple[str, float], ...], ...] = (
    # 주거
    (("월세", 1.0), ("월세보조", 0.8), ("주거비", 0.5), ("임차료", 0.5), ("임대료", 0.4)),
    (("전세", 1.0), ("전세자금", 0.7), ("전세대출", 0.7), ("임차보증금", 0.6),
     ("보증금", 0.35)),
    (("전세임대", 1.0), ("매입임대", 0.9), ("행복주택", 0.8), ("공공임대", 0.7),
     ("임대주택", 0.7)),
    # 소상공인 비용
    (("배달비", 1.0), ("배달앱", 0.8), ("배달", 0.5), ("택배비", 0.9), ("택배", 0.6),
     ("배송비", 0.8), ("중개수수료", 0.5)),
    (("전기세", 1.0), ("전기요금", 0.9), ("전력", 0.5), ("가스요금", 0.8),
     ("도시가스", 0.7), ("난방비", 0.6), ("에너지", 0.4)),
    (("인건비", 1.0), ("고용장려금", 0.8), ("채용장려금", 0.9), ("채용지원", 0.7),
     ("임금지원", 0.7), ("고용촉진", 0.8), ("사회보험료", 0.5), ("고용보험", 0.4)),
    (("폐업", 1.0), ("폐업지원", 0.9), ("희망리턴", 0.9), ("재창업", 0.8), ("재기", 0.7),
     ("점포철거", 0.7), ("철거비", 0.6)),
    (("창업자금", 1.0), ("창업지원", 0.8), ("사업화", 0.6), ("창업초기", 0.5),
     ("예비창업", 0.5), ("창업", 0.3)),
    # 가계·건강
    (("산후조리", 1.0), ("산후조리원", 0.9), ("산모", 0.6), ("임산부", 0.5)),
    (("육아휴직", 1.0), ("부모육아휴직", 0.8), ("출산휴가", 0.8), ("배우자출산휴가", 0.7),
     ("육아", 0.35)),
    (("보육", 1.0), ("아이돌봄", 0.8), ("어린이집", 0.7), ("유아학비", 0.6), ("돌봄", 0.4)),
    (("병원비", 1.0), ("의료비", 0.6), ("진료비", 0.6), ("치료비", 0.5), ("본인부담", 0.4)),
    (("치매", 1.0), ("노인장기요양", 0.9), ("장기요양", 0.7), ("요양보호", 0.6),
     ("간병", 0.5)),
    (("학자금", 1.0), ("학자금대출", 0.9), ("국가장학금", 0.8), ("등록금", 0.7),
     ("장학금", 0.7), ("학비", 0.6)),
    (("실업급여", 1.0), ("구직급여", 0.9), ("구직활동", 0.6), ("취업지원", 0.5),
     ("실업", 0.5)),
    (("채무조정", 1.0), ("신용회복", 0.9), ("개인회생", 0.9), ("파산", 0.6), ("연체", 0.4)),
    (("긴급복지", 1.0), ("위기지원", 0.7), ("생계비", 0.5)),
    (("기초연금", 1.0), ("노령연금", 0.7), ("국민연금", 0.6), ("노인일자리", 0.5),
     ("연금", 0.4)),
)

#: 표기 → (묶음, 보조 가중치)
CLUSTER_INDEX: dict = {}
for _cluster in CLUSTERS:
    for _term, _weight in _cluster:
        CLUSTER_INDEX.setdefault(_term, (_cluster, _weight))

#: 확장하지 않는 아주 짧은 말(한 글자) — 노이즈가 크다.
MIN_WORD = 2


def normalize(word: str) -> str:
    """문장부호·조사를 떼어 낸 표기(사전 조회용).

    한 글자 조사는 사전에 있는 말로 돌아갈 때만 뗀다 — "없는제도"의 '도'처럼
    낱말의 일부를 잘라 엉뚱한 표기를 만들지 않기 위해서다.
    """
    text = str(word or "").strip().strip(_PUNCT)
    if len(text) <= MIN_WORD:
        return text
    for josa in JOSA_LONG:
        if text.endswith(josa) and len(text) - len(josa) >= MIN_WORD:
            return text[: -len(josa)]
    for josa in JOSA_SHORT:
        if text.endswith(josa) and len(text) - len(josa) >= MIN_WORD:
            stem = text[: -len(josa)]
            if stem in CLUSTER_INDEX:
                return stem
    return text


def variants(word: str) -> List[Tuple[str, float]]:
    """한 단어의 표기 목록 — (표기, 가중치). 직접 표기는 항상 1.0."""
    raw = str(word or "").strip().strip(_PUNCT)
    if not raw:
        return []
    out: List[Tuple[str, float]] = [(raw, 1.0)]
    key = normalize(raw)
    if key and key != raw:
        out.append((key, 1.0))
    entry = CLUSTER_INDEX.get(key)
    if entry is None and len(key) > 4:
        # "월세지원"·"전기세감면"처럼 뒤에 말이 붙은 경우 앞의 사전 표기를 찾는다.
        for term in sorted(CLUSTER_INDEX, key=len, reverse=True):
            if len(term) >= MIN_WORD and term in key and len(key) - len(term) <= 4:
                entry = CLUSTER_INDEX[term]
                break
    if entry is not None:
        cluster, _weight = entry
        for term, weight in sorted(cluster, key=lambda pair: -pair[1]):
            if term == key or any(term == seen for seen, _ in out):
                continue
            out.append((term, min(weight, 0.95)))
    # 직접 표기(raw·조사 제거형)가 늘 앞에 온다 — 잘라도 질의어는 남는다.
    return out[:MAX_VARIANTS]


def plan(keyword: str) -> List[List[Tuple[str, float]]]:
    """질의 → 단어별 표기 묶음. 단어 사이는 AND, 묶음 안은 OR."""
    words = [word for word in re.split(r"\s+", str(keyword or "").strip()) if word.strip(_PUNCT)]
    groups: List[List[Tuple[str, float]]] = []
    for word in words:
        group = variants(word)
        if group:
            groups.append(group)
    return groups


def terms(keyword_or_plan) -> List[str]:
    """확장된 모든 표기(중복 제거) — SQL LIKE·디버깅용."""
    groups = keyword_or_plan if isinstance(keyword_or_plan, (list, tuple)) else plan(keyword_or_plan)
    out: List[str] = []
    for group in groups:
        for term, _weight in group:
            if term not in out:
                out.append(term)
    return out


def is_expanded(keyword: str) -> bool:
    """사전이 실제로 표기를 늘려 주는 질의인가(사용자에게 알려 줄 때 쓴다)."""
    return any(len(group) > 1 for group in plan(keyword))


def _best(needle_text: str, group: Sequence[Tuple[str, float]]) -> float:
    best = 0.0
    for term, weight in group:
        count = needle_text.count(term)
        if count:
            # 같은 표기가 여러 번 나와도 점수는 완만하게만 오른다.
            best = max(best, weight * (1.0 + min(count, 3) * 0.25))
    return best


def score(name: str, haystack: str, groups: Sequence[Sequence[Tuple[str, float]]],
          *, name_bonus: float = 3.0) -> int:
    """질의 묶음이 문서에 얼마나 맞는지 — 0 이면 불일치(AND)."""
    if not groups:
        return 0
    total = 0.0
    bonus = 0.0
    for group in groups:
        hit = _best(haystack, group)
        if hit <= 0:
            return 0
        total += hit
        bonus += _best(name, group)
    return int(round((total + name_bonus * bonus) * 10))


def matches(haystack: str, groups: Sequence[Sequence[Tuple[str, float]]]) -> bool:
    """모든 단어 묶음이 하나 이상의 표기로 걸리는가(엄격 AND + 동의어 OR)."""
    return all(_best(haystack, group) > 0 for group in groups)


def literal_hit(name: str, haystack: str,
                keyword: str) -> bool:
    """질의어를 한 글자도 바꾸지 않고 담고 있는가(직접 일치 우선 정렬용)."""
    words = [word for word in re.split(r"\s+", str(keyword or "").strip()) if word.strip(_PUNCT)]
    text = f"{name} {haystack}"
    return bool(words) and all(word in text for word in words)


def sql_like_terms(keyword: str, *, literal_only: bool = False) -> List[str]:
    """SQL LIKE 에 넘길 표기 목록(OR) — literal_only 면 원문 단어만."""
    if literal_only:
        return [word for word in re.split(r"\s+", str(keyword or "").strip()) if word.strip(_PUNCT)]
    return terms(plan(keyword))


def describe(keyword: str) -> Optional[str]:
    """화면·응답에 붙일 한 줄 설명(확장이 일어난 경우에만)."""
    groups = plan(keyword)
    expanded = [group for group in groups if len(group) > 1]
    if not expanded:
        return None
    parts = []
    for group in expanded:
        head = group[0][0]
        others = [term for term, _weight in group[1:3]]
        if others:
            parts.append(f"{head}→{'·'.join(others)}")
    return "동의어 확장: " + ", ".join(parts) if parts else None

