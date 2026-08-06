# -*- coding: utf-8 -*-
"""자산군 어휘 정규화 — 코멘트 파이프라인 공용 (2026-08-05).

★ 배경: 같은 "자산군"이 소스마다 다른 라벨로 온다.

| 소스 | 대체자산 | 현금성 |
|------|---------|--------|
| PA·보유 (`compute_single_port_pa` 방법3, `BRINSON_METHOD_CLASSES`) | `대체` | `유동성및기타` |
| 거래 (`load_fund_net_trades`) | `대체투자` | `유동성` |

`fund_comment_service` 의 미편입 자산군 판정이 **거래 어휘**로 된 상수 집합과
**보유 어휘**로 온 키를 직접 비교하고 있어, 금을 *보유만 하고 매매하지 않은* 펀드는
`대체투자` 가 항상 "미편입"으로 판정됐다 (2026-08-05 실측 확인 —
08N81 은 7월에 금을 *매매* 했기 때문에 우연히 정상 동작했다).

여기서 canonical 어휘를 **PA·보유 쪽(`대체`/`유동성및기타`)** 으로 통일한다.
PA 기여도 서술이 코멘트 본문에 그대로 인용되므로 그쪽이 정본이다.
"""

# canonical 자산군 (현금성 제외) — 코멘트가 서술 대상으로 삼는 집합
CANONICAL_CLASSES = ('국내주식', '해외주식', '국내채권', '해외채권', '대체', 'FX')

# 현금성·집계행 — 보유 판정과 시드 조립에서 모두 제외한다.
#   '포트폴리오' 는 compute_single_port_pa asset_summary 의 합계행.
#   '모펀드' 는 look-through 이전 단계의 자사 모투자신탁 버킷.
NON_NARRATIVE = frozenset({'유동성', '유동성및기타', '포트폴리오', '모펀드', '보수비용'})

# 소스별 별칭 → canonical
_ALIAS = {
    '대체투자': '대체',
    '원자재': '대체',
    '환율(FX)': 'FX',
    '환율': 'FX',
}

# 서술 순서. 시장동향과 전망의 관행적 순서가 다르다 (2026-07 승인본 실측):
#   시장동향: 글로벌 증시 → 국내 증시 → 미국 채권 → 국내 금리 → 금 → 외환
#   전망    : 국내주식 → 글로벌 주식 → 채권 → 금
MARKET_ORDER = ('해외주식', '국내주식', '해외채권', '국내채권', '대체', 'FX')
OUTLOOK_ORDER = ('국내주식', '해외주식', '국내채권', '해외채권', '대체', 'FX')


def normalize(label: str) -> str | None:
    """자산군 라벨 → canonical. 현금성·집계행·미지 라벨은 None."""
    if not label:
        return None
    s = str(label).strip()
    s = _ALIAS.get(s, s)
    if s in NON_NARRATIVE:
        return None
    return s if s in CANONICAL_CLASSES else None


def normalize_keys(mapping) -> set[str]:
    """dict/iterable 의 자산군 키들을 canonical set 으로. 미지 라벨은 버린다."""
    if not mapping:
        return set()
    keys = mapping.keys() if hasattr(mapping, 'keys') else mapping
    return {c for c in (normalize(k) for k in keys) if c}


def active_classes(holdings: dict | None, trades: dict | None,
                   *, min_weight: float = 0.0) -> set[str]:
    """기간 중 '실제로 다룬' 자산군 = 기말 보유 ∪ 기간 중 거래.

    min_weight > 0 이면 보유 비중이 그 미만인 자산군은 보유로 치지 않는다
    (거래가 있었다면 거래 쪽에서 살아남는다). 거래는 금액 부호가 섞이므로
    비중 임계를 적용하지 않는다.
    """
    held = set()
    for k, v in (holdings or {}).items():
        c = normalize(k)
        if not c:
            continue
        try:
            if float(v) < min_weight:
                continue
        except (TypeError, ValueError):
            pass
        held.add(c)
    return held | normalize_keys(trades)


def excluded_classes(holdings: dict | None, trades: dict | None,
                     *, min_weight: float = 0.0) -> set[str]:
    """canonical 전체 − active. 코멘트에서 언급을 금지할 자산군."""
    return set(CANONICAL_CLASSES) - active_classes(
        holdings, trades, min_weight=min_weight)


def ordered(classes, section: str = 'market') -> list[str]:
    """canonical 집합을 서술 순서로 정렬."""
    order = OUTLOOK_ORDER if section == 'outlook' else MARKET_ORDER
    s = set(classes or ())
    return [c for c in order if c in s]
