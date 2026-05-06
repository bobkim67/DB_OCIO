"""Regression: _adapt_compute_single_port_pa (Q-FIX-2).

LLM 호출 0, mock DataFrame 만 사용. compute_single_port_pa 의 새 schema
(asset_summary DataFrame) → 구버전 키 (pa_by_class / fund_return /
holdings_end / holdings_diff) 변환의 정확성 검증.

단위:
  compute_single_port_pa : decimal (-0.0271 = -2.71%)
  adapter return         : % 단위 (-2.71)
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _make_asset_summary_df():
    """compute_single_port_pa 의 실 schema 모킹 (08N81 1Q 기준)."""
    import pandas as pd
    return pd.DataFrame([
        {'자산군': '포트폴리오', '분석시작일': '2026-01-08', '분석종료일': '2026-03-31',
         '개별수익률': -0.027088, '기여수익률': -0.027088,
         '순자산비중': 1.000000, '순비중변화': 0.000000},
        {'자산군': '국내주식', '분석시작일': '2026-01-08', '분석종료일': '2026-03-31',
         '개별수익률': 0.073561, '기여수익률': -0.001544,
         '순자산비중': 0.119885, '순비중변화': 0.073006},
        {'자산군': '해외주식', '분석시작일': '2026-01-08', '분석종료일': '2026-03-31',
         '개별수익률': -0.123097, '기여수익률': -0.040739,
         '순자산비중': 0.320743, '순비중변화': -0.043875},
        {'자산군': '국내채권', '분석시작일': '2026-01-08', '분석종료일': '2026-03-31',
         '개별수익률': -0.021200, '기여수익률': -0.005300,
         '순자산비중': 0.250000, '순비중변화': 0.020000},
        {'자산군': '유동성', '분석시작일': '2026-01-08', '분석종료일': '2026-03-31',
         '개별수익률': 0.005000, '기여수익률': 0.000500,
         '순자산비중': 0.100000, '순비중변화': 0.000000},
    ])


def test_adapter_basic():
    """기본 케이스 — fund_return, pa_by_class, holdings_end 정상 변환 + 단위 % 변환."""
    from market_research.report.fund_comment_service import _adapt_compute_single_port_pa
    df = _make_asset_summary_df()
    pa_result = {'asset_summary': df, 'sec_summary': None, 'fund_code': '08N81'}
    out = _adapt_compute_single_port_pa(pa_result)

    # fund_return: 포트폴리오 row 의 개별수익률 -0.027088 × 100 = -2.7088
    assert out['fund_return'] is not None
    assert abs(out['fund_return'] - (-2.7088)) < 0.001, (
        f'fund_return mismatch: {out["fund_return"]}'
    )

    # pa_by_class: 자산군 4개 (포트폴리오 제외)
    assert len(out['pa_by_class']) == 4
    assert '포트폴리오' not in out['pa_by_class']
    # 해외주식 기여 -0.040739 × 100 = -4.0739
    assert abs(out['pa_by_class']['해외주식'] - (-4.0739)) < 0.001

    # holdings_end: 비중 0 초과만 (모든 row 가 양수라 4개 포함)
    assert len(out['holdings_end']) == 4
    # 해외주식 비중 0.320743 × 100 = 32.0743
    assert abs(out['holdings_end']['해외주식'] - 32.0743) < 0.001

    # holdings_diff: 미산출 → 빈 list + warning
    assert out['holdings_diff'] == []
    assert any('holdings_diff' in w for w in out['warnings'])


def test_adapter_zero_weight_excluded():
    """순자산비중 = 0 자산군은 holdings_end 에서 제외."""
    import pandas as pd
    from market_research.report.fund_comment_service import _adapt_compute_single_port_pa
    df = pd.DataFrame([
        {'자산군': '포트폴리오', '개별수익률': -0.01, '기여수익률': -0.01, '순자산비중': 1.0},
        {'자산군': '국내주식', '개별수익률': 0.05, '기여수익률': 0.025, '순자산비중': 0.5},
        {'자산군': '해외채권', '개별수익률': 0.0, '기여수익률': 0.0, '순자산비중': 0.0},
    ])
    out = _adapt_compute_single_port_pa({'asset_summary': df})
    assert '국내주식' in out['holdings_end']
    assert '해외채권' not in out['holdings_end'], (
        f'0 비중 자산군이 포함됨: {out["holdings_end"]}'
    )
    # pa_by_class 는 0 이라도 포함 (기여 정보)
    assert '해외채권' in out['pa_by_class']


def test_adapter_no_asset_summary():
    """asset_summary 없으면 빈 결과 + warning."""
    from market_research.report.fund_comment_service import _adapt_compute_single_port_pa
    out = _adapt_compute_single_port_pa({'sec_summary': None, 'fund_code': '08N81'})
    assert out['fund_return'] is None
    assert out['pa_by_class'] == {}
    assert out['holdings_end'] == {}
    assert any('asset_summary missing' in w for w in out['warnings'])


def test_adapter_empty_dataframe():
    """빈 DataFrame → 빈 결과 + warning."""
    import pandas as pd
    from market_research.report.fund_comment_service import _adapt_compute_single_port_pa
    out = _adapt_compute_single_port_pa({'asset_summary': pd.DataFrame()})
    assert out['fund_return'] is None
    assert out['pa_by_class'] == {}
    assert any('empty' in w for w in out['warnings'])


def test_adapter_not_a_dict():
    """pa_result 가 dict 아니면 warning."""
    from market_research.report.fund_comment_service import _adapt_compute_single_port_pa
    out = _adapt_compute_single_port_pa(None)
    assert out['fund_return'] is None
    assert any('not a dict' in w for w in out['warnings'])


def test_adapter_no_portfolio_row():
    """포트폴리오 row 없으면 fund_return=None 이지만 pa_by_class 는 채워짐."""
    import pandas as pd
    from market_research.report.fund_comment_service import _adapt_compute_single_port_pa
    df = pd.DataFrame([
        {'자산군': '국내주식', '개별수익률': 0.05, '기여수익률': 0.025, '순자산비중': 0.5},
    ])
    out = _adapt_compute_single_port_pa({'asset_summary': df})
    assert out['fund_return'] is None
    assert '국내주식' in out['pa_by_class']
    assert abs(out['pa_by_class']['국내주식'] - 2.5) < 0.001


def test_adapter_missing_columns():
    """일부 컬럼 누락 시에도 graceful (KeyError 잡고 진행)."""
    import pandas as pd
    from market_research.report.fund_comment_service import _adapt_compute_single_port_pa
    df = pd.DataFrame([
        {'자산군': '포트폴리오', '개별수익률': -0.02},  # 기여수익률 / 순자산비중 없음
        {'자산군': '국내주식', '개별수익률': 0.05},
    ])
    out = _adapt_compute_single_port_pa({'asset_summary': df})
    # fund_return 만 추출됨
    assert abs(out['fund_return'] - (-2.0)) < 0.001
    # pa_by_class / holdings_end 는 비어있음
    assert out['pa_by_class'] == {}
    assert out['holdings_end'] == {}


if __name__ == '__main__':
    for fn in [
        test_adapter_basic,
        test_adapter_zero_weight_excluded,
        test_adapter_no_asset_summary,
        test_adapter_empty_dataframe,
        test_adapter_not_a_dict,
        test_adapter_no_portfolio_row,
        test_adapter_missing_columns,
    ]:
        fn()
        print(f'PASS {fn.__name__}')
    print('ALL PASS')
