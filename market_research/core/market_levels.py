# -*- coding: utf-8 -*-
"""시장 레벨 사실 — 레벨의 정본은 DB (SCIP). 코멘트 체인 공용 (2026-09-02).

## 왜 공용인가

원래 `report/market_seed.py` 안에 있었다(2026-09-01, `24f38c1`). 시드만 레벨을
지어내는 게 아니라 **시장 debate synthesis 도 같은 자리에서 지어낼 수 있어서**
같은 블록을 양쪽에 공급하려고 core 로 올렸다. 한쪽만 고치면 같은 달 보고서
안에서 레벨이 갈린다.

## 확정된 규약

- **레벨·고저의 정본은 DB.** 브리핑 본문에는 보통 변동률만 있고 레벨이 없어서,
  "레벨로 쓰라"는 규칙만 걸면 모델이 없는 레벨을 만들어낸다.
  실측(2026-09-01): 시드가 8월말 달러/원을 "1,530원대"로 썼다(실제 1,368.60).
- ★ **고저는 종가 기준이다.** 사내 DB 어디에도 지수 장중 고저가 없다 —
  SCIP 253(KOSPI)의 dataseries 는 9(TR)·15(FG Price)·48(PX_LAST) 로 전부 종가이고,
  `back_dataseries` 에 HIGH/LOW/INTRA 이름 패턴 0건, `dt.MI_DJISU`(eod00d_*)·
  `BMJISU`·`MI_DSJISU`·`BB_IDXEVT` 에도 고저 컬럼이 없다.
  `solution.sol_index_inform` 은 매핑 테이블(OHLC 없음).
  → 프롬프트는 반드시 "종가 기준"으로 라벨링하고 **장중 표현 금지**를 함께 건다.
  2026-09-02 사용자 결정: 블룸버그 `PX_HIGH`/`PX_LOW` 수집안은 채택하지 않는다.
- ⚠ `period_bounds` 의 "기초 = 직전 기간의 마지막 날" 규약은
  `core/period_window.py`(08K88 예외 창)와 **다른 규약이다. 합치지 말 것.**
  ([[reference_pa_period_start_offbyone]] 계열 함정)
- 진행 중인 기간은 종료일을 today 로 clamp 한다. `DWCI10220` 에 미래 영업일이
  등록돼 있어 clamp 없이는 데이터 없는 날짜를 잡는다.

## 시리즈 선정 — 자산군당 대표 1개

코멘트가 서술 대상으로 삼는 canonical 자산군(`core/asset_class.CANONICAL_CLASSES`)에
1:1로 붙인다. 숫자를 늘리려는 게 아니라 **자산군별 서술이 인용할 정답을 주는 것**이
목적이므로 그 이상 늘리지 않는다 (2026-09-02 사용자: "사실 숫자는 아예 안 들어가도
된다. 다만 월간 고점 저점 정도는").

⚠ **국내채권은 대표 레벨 지표가 없다.** SCIP 에 국고채 금리(yield) 시리즈가 없고
KIS/KAP 계열은 전부 지수라 "국고채 10년 x.xx%" 식 인용의 근거가 되지 못한다.
→ 블록에서 제외한다. 규칙이 "블록에 없으면 레벨을 쓰지 말라"로 받으므로,
비워두는 게 잘못된 숫자를 주는 것보다 안전하다.
"""
from __future__ import annotations

# (dataset_id, dataseries_id, blob_key, 표시라벨, 소수자리, 자산군, kind)
#   blob_key=None 이면 blob 의 첫 값을 쓴다 (단일 숫자 / 단일 키 blob).
#   자산군 = core.asset_class.CANONICAL_CLASSES 또는 None(자산군에 안 붙는 보조지표).
#   kind='px'    → 변화를 **퍼센트**로 (지수·환율·상품 가격)
#   kind='yield' → 변화를 **bp**로. ⚠ 금리를 퍼센트 변화로 쓰면 오해를 부른다 —
#                  4.71%→4.75% 는 +4bp 이지 "+0.72%" 가 아니다.
# 전부 2026-09-02 에 SCIP 에서 실재·최신성 확인함.
LEVEL_SERIES: tuple[tuple, ...] = (
    (253, 15, 'KRW', 'KOSPI',          2, '국내주식', 'px'),
    (271, 15, 'USD', 'S&P 500',        2, '해외주식', 'px'),
    (2,    7, None,  '미국채 10년물',    2, '해외채권', 'yield'),
    (408, 48, None,  '금(달러/온스)',    2, '대체',    'px'),
    (31,   6, 'USD', '달러/원',         2, 'FX',      'px'),
    (105, 48, None,  '달러지수(DXY)',   2, None,      'px'),
)

# 프롬프트 블록 제목 — 인용 규칙이 이 문자열을 가리키므로 양쪽이 같아야 한다.
LEVEL_BLOCK_HEADING = '## 시장 레벨 — DB 실측 (레벨은 여기 숫자만 인용 · 고저는 종가 기준)'


def period_bounds(period: str):
    """period 키 → (기초일, 기말일) 달력 경계. 기초 = 직전 기간의 마지막 날.

    ⚠ `core/period_window.py` 와 합치지 말 것 (위 모듈 docstring 참조).
    """
    import datetime as _dt
    import re as _r
    from calendar import monthrange

    def eom(y, m):
        return _dt.date(y, m, monthrange(y, m)[1])

    s_ = (period or '').strip()
    today = _dt.date.today()
    m = _r.fullmatch(r'(\d{4})-(\d{2})', s_)
    if m:
        y, mo = int(m[1]), int(m[2])
        prev = eom(y - 1, 12) if mo == 1 else eom(y, mo - 1)
        return prev, min(eom(y, mo), today)
    m = _r.fullmatch(r'(\d{4})-Q([1-4])(\.QTD)?', s_)
    if m:
        y, q = int(m[1]), int(m[2])
        start = eom(y - 1, 12) if q == 1 else eom(y, (q - 1) * 3)
        end = today if m[3] else eom(y, q * 3)
        return start, min(end, today)
    # 반기 — `.HTD` 없으면 마감된 반기(종료일 = 반기말), 있으면 진행 중(종료일 = today).
    m = _r.fullmatch(r'(\d{4})-H([12])(\.HTD)?', s_)
    if m:
        y, h = int(m[1]), int(m[2])
        start = eom(y - 1, 12) if h == 1 else eom(y, 6)
        end = today if m[3] else eom(y, 6 if h == 1 else 12)
        return start, min(end, today)
    m = _r.fullmatch(r'(\d{4})-YTD', s_)
    if m:
        return eom(int(m[1]) - 1, 12), today
    return None


def market_level_facts(period: str) -> list | None:
    """['- KOSPI: 6,595.45 (07/31) → 6,820.02 (08/31) = +3.40% · 기간중 종가 저~고 …'].

    DB 실패는 fail-open (None) — 프롬프트에서 블록이 통째로 빠지고,
    규칙이 "블록이 없으면 레벨을 쓰지 말라"로 받으므로 무중단이다.
    """
    try:
        bounds = period_bounds(period)
        if not bounds:
            return None
        start, end = bounds
        import json as _json

        import pandas as _pd

        from modules.data_loader import get_pandas_connection

        def _px(blob, key=None):
            t = blob.decode('utf-8') if isinstance(blob, (bytes, bytearray)) else str(blob)
            t = t.strip()
            if t.startswith('{'):
                o = _json.loads(t)
                return float(o[key]) if key and key in o else float(list(o.values())[0])
            return float(t.replace(',', ''))

        # ⚠ OR 는 반드시 괄호로 묶는다 — 안 묶으면 AND 가 먼저 걸려 한쪽 시리즈가
        #   날짜 필터 없이 전 이력을 긁어온다.
        warm = (_pd.Timestamp(start) - _pd.Timedelta(days=40)).strftime('%Y-%m-%d')
        pairs = ' OR '.join(f'(dataset_id={d} AND dataseries_id={sid})'
                            for d, sid, *_ in LEVEL_SERIES)
        sql = (f"SELECT dataset_id, DATE(timestamp_observation) d, data "
               f"FROM back_datapoint WHERE ({pairs}) "
               f"AND timestamp_observation >= '{warm}' "
               f"AND timestamp_observation <= '{end:%Y-%m-%d}' "
               f"ORDER BY timestamp_observation")
        conn = get_pandas_connection('SCIP')
        try:
            df = _pd.read_sql(sql, conn)
        finally:
            conn.close()
        if df.empty:
            return None

        out = []
        for ds, _sid, key, label, nd, _ac, kind in LEVEL_SERIES:
            sub = df[df['dataset_id'] == ds]
            if sub.empty:
                continue
            sv = _pd.Series({_pd.Timestamp(r['d']): _px(r['data'], key)
                             for _, r in sub.iterrows()}).sort_index()
            a = sv[sv.index <= _pd.Timestamp(start)]
            b = sv[sv.index <= _pd.Timestamp(end)]
            if a.empty or b.empty:
                continue
            v0, v1 = float(a.iloc[-1]), float(b.iloc[-1])
            if kind == 'yield':
                chg_s = f'{(v1 - v0) * 100:+.0f}bp'
                unit = '%'
            else:
                chg_s = f'{((v1 / v0 - 1) * 100 if v0 else 0.0):+.2f}%'
                unit = ''
            # 기간 중 고저 — ★종가 기준. 장중이 아니다 (모듈 docstring 참조).
            win = sv[(sv.index > _pd.Timestamp(start)) & (sv.index <= _pd.Timestamp(end))]
            line = (f'- {label}: {v0:,.{nd}f}{unit} ({a.index[-1]:%m/%d}) → '
                    f'{v1:,.{nd}f}{unit} ({b.index[-1]:%m/%d}) = {chg_s}')
            if not win.empty:
                line += (f' · 기간중 종가 저~고 '
                         f'{win.min():,.{nd}f}{unit}~{win.max():,.{nd}f}{unit}')
            out.append(line)
        return out or None
    except Exception:
        return None


def level_block(period: str) -> str:
    """프롬프트에 그대로 붙일 레벨 블록. 사실이 없으면 빈 문자열."""
    facts = market_level_facts(period)
    if not facts:
        return ''
    return LEVEL_BLOCK_HEADING + '\n' + '\n'.join(facts)
