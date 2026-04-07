# -*- coding: utf-8 -*-
"""Tab 5: 매크로 지표 대시보드.

SCIP DB 시계열 데이터 기반 매크로 지표 분석.
TR Decomposition, EPS/PE, USD/KRW, 글로벌 금리 등.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from modules.charts import make_nav
from modules.data_loader import parse_data_blob


def render(ctx):
    """매크로 지표 탭 렌더링.

    Parameters
    ----------
    ctx : dict
        selected_fund, fund_info, DB_CONNECTED, cache, dates
    """
    DB_CONNECTED = ctx['DB_CONNECTED']
    cache = ctx['cache']

    st.markdown("#### 매크로 지표 대시보드")
    st.caption("SCIP DB 시계열 데이터 기반 | 자동 업데이트")

    # ── 자산군별 벤치마크 수익률 (SCIP 실시간) ──
    try:
        import sys as _sys4
        _sys4.path.insert(0, str(Path(__file__).resolve().parent.parent)) if 'market_research' not in str(_sys4.path) else None
        from market_research.comment_engine import load_benchmark_period_returns, BENCHMARK_MAP as _BM_MAP
        _bm_period = load_benchmark_period_returns()
    except Exception:
        _bm_period = {}

    if _bm_period:
        _bm_env_title, _bm_env_toggle = st.columns([4, 1])
        with _bm_env_title:
            st.markdown("### 자산군별 벤치마크 수익률")
        with _bm_env_toggle:
            _bm_krw_toggle = st.toggle("원화환산", key='bm_krw_toggle_top')

        # 테이블 구축
        _bm_rows = []
        _bm_layout = [
            ('주식', '글로벌', '', '글로벌주식'),
            ('', '국내', '시장', 'KOSPI'),
            ('', '', 'KOSPI200', 'KOSPI200'),
            ('', '미국', '시장', 'S&P500'),
            ('', '', '성장', '미국성장주'),
            ('', '', '가치', '미국가치주'),
            ('', '', '중소형', 'Russell2000'),
            ('', '', '고배당', '고배당'),
            ('', '미국외 선진국', '', '미국외선진국'),
            ('', '신흥시장', '', '신흥국주식'),
            ('채권', '글로벌(UH)', '', '글로벌채권UH'),
            ('', '글로벌(H to USD)', '', '글로벌채권H'),
            ('', '글로벌(H to KRW)', '', '글로벌채권HKRW'),
            ('', '국내', '국채3년', '매경채권국채3년'),
            ('', '', '국고10년', 'KRX10년채권'),
            ('', '', '종합채권', 'KAP종합채권'),
            ('', '미국', '종합채권', '미국종합채권'),
            ('', '', '투자등급', '미국IG'),
            ('', '', '하이일드', '미국HY'),
            ('', '신흥시장', '달러표시', '신흥국채권'),
            ('대체', '금', '', 'Gold'),
            ('', 'WTI', '', 'WTI'),
            ('', '미국리츠', '', '미국리츠'),
            ('', '원자재종합', '', '원자재종합'),
            ('통화', 'DXY', '', 'DXY'),
            ('', 'EMCI', '', 'EMCI'),
            ('', 'EUR/USD', '', 'EURUSD'),
            ('', 'JPY/USD', '', 'JPYUSD'),
            ('', 'GBP/USD', '', 'GBPUSD'),
            ('', 'CAD/USD', '', 'CADUSD'),
            ('', 'AUD/USD', '', 'AUDUSD'),
            ('', 'USD/KRW', '', 'USDKRW'),
        ]
        _period_cols = ['1D', '1W', '1M', '3M', '6M', '1Y', 'YTD']
        _ref_date_str = ''
        for _cat, _mid, _sub, _key in _bm_layout:
            _d = _bm_period.get(_key, {})
            if not _ref_date_str and _d.get('ref_date'):
                _ref_date_str = _d['ref_date']
            _lv = _d.get('level')
            _row = {
                '대분류': _cat, '중분류': _mid, '소분류': _sub,
                '지표': _key if not _mid else (_sub if _sub else _mid),
                '현재값': f'{_lv:,.2f}' if _lv and _lv > 100 else (f'{_lv:.4f}' if _lv and _lv < 1 else (f'{_lv:,.2f}' if _lv else '')),
            }
            for _p in _period_cols:
                _row[_p] = _d.get(_p)
            _bm_rows.append(_row)

        _bm_df = pd.DataFrame(_bm_rows)

        # 원화환산: 해외 자산에 USDKRW 변동 가산
        if _bm_krw_toggle:
            _usdkrw_rets = _bm_period.get('USDKRW', {})
            _bm_df_active = _bm_df.copy()
            _domestic_keys = {'KOSPI', 'KOSPI200', 'KOSPI_PRICE', '매경채권국채3년', 'KRX10년채권', 'KAP종합채권', 'USDKRW'}
            _fx_keys = {'DXY', 'EMCI', 'EURUSD', 'JPYUSD', 'GBPUSD', 'CADUSD', 'AUDUSD', 'USDKRW'}
            for _i, (_cat, _mid, _sub, _key) in enumerate(_bm_layout):
                if _key in _domestic_keys or _key in _fx_keys:
                    continue
                for _p in _period_cols:
                    _v = _bm_df_active.at[_i, _p]
                    _fx = _usdkrw_rets.get(_p)
                    if _v is not None and _fx is not None:
                        _bm_df_active.at[_i, _p] = _v + _fx
        else:
            _bm_df_active = _bm_df

        # 포맷팅
        _bm_display = _bm_df_active.copy()
        for _p in _period_cols:
            _bm_display[_p] = _bm_df_active[_p].apply(lambda v: f'{v:+.2f}%' if pd.notna(v) and v is not None else '')

        def _style_bm_val(val):
            if isinstance(val, str):
                stripped = val.replace('%', '').strip()
                try:
                    v = float(stripped)
                    return 'color: #636EFA' if v < 0 else ('color: #EF553B' if v > 0 else '')
                except (ValueError, TypeError):
                    pass
            return ''

        _bm_height = max(300, 32 * len(_bm_display) + 40)
        _styled_bm = _bm_display.style.map(_style_bm_val, subset=_period_cols)
        _styled_bm = _styled_bm.set_properties(**{'font-size': '12px'})
        _styled_bm = _styled_bm.set_properties(subset=['대분류'], **{'font-weight': 'bold', 'background-color': '#f8f9fa'})
        st.dataframe(_styled_bm, hide_index=True, width="stretch", height=_bm_height)
        st.caption(f"📡 SCIP DB 실시간 | 기준일: {_ref_date_str} | 단위: % (수익률)")

    st.markdown("---")

    with st.expander("Bloomberg 데이터 엑셀 업로드", expanded=False):
        st.markdown("""
        **엑셀 파일 형식 안내:**
        - **Sheet 1 (TR_Index)**: Date | MXWD | MXUS | MXWOU | MXEF | ... (Tot_Return_Index_Net_Dvds)
        - **Sheet 2 (Valuation)**: Date | MXWD_PE | MXWD_EPS | MXUS_PE | MXUS_EPS | ...
        - **Sheet 3 (Benchmarks)**: Date | KOSPI | SPX | RTY | ... (PX_Last)
        - **Sheet 4 (FX)**: Date | USDKRW | DXY | EURUSD | ...
        - **Sheet 5 (Rates)**: Date | USGG2Y | USGG10Y | KBPMG10Y | ...
        """)
        uploaded_file = st.file_uploader("엑셀 파일 업로드 (.xlsx)", type=['xlsx', 'xls'], key='macro_upload')
        if uploaded_file:
            st.success(f"'{uploaded_file.name}' 업로드 완료! 데이터를 분석 중...")

    st.markdown("---")

    # --- 매크로 데이터: DB → fallback mockup ---
    _macro_db = False
    _macro_data = {}

    # DB에서 매크로 시계열 로드 시도
    _macro_keys = ('MSCI ACWI', 'S&P 500', 'MSCI Korea', 'MSCI EM', 'MSCI World ex US',
                   'MSCI ACWI_PE', 'MSCI ACWI_EPS', 'S&P 500_PE', 'S&P 500_EPS',
                   'MSCI Korea_PE', 'MSCI Korea_EPS', 'MSCI EM_PE', 'MSCI EM_EPS',
                   'USD/KRW', 'VIX', 'MOVE', 'US HY OAS', 'Gold')
    if DB_CONNECTED:
        try:
            _macro_data = cache['load_macro_timeseries'](_macro_keys, '2017-01-01')
            if _macro_data and len(_macro_data) > 3:
                _macro_db = True
        except Exception:
            pass

    # mockup fallback
    macro_dates = pd.bdate_range('2024-01-02', '2026-02-11', freq='B')
    n_md = len(macro_dates)

    # PE/EPS/TR 데이터 구성 (DB or mockup)
    all_val_tickers = ['MSCI ACWI', 'S&P 500', 'MSCI EM', 'MSCI Korea', 'MSCI World ex US']
    pe_data = {}
    eps_data = {}
    tr_indices = {}

    for tk in all_val_tickers:
        pe_key = f'{tk}_PE'
        eps_key = f'{tk}_EPS'
        if _macro_db and pe_key in _macro_data:
            _pe_df = _macro_data[pe_key]
            pe_data[tk] = _pe_df.set_index('기준일자')['value']
        if _macro_db and eps_key in _macro_data:
            _eps_df = _macro_data[eps_key]
            eps_data[tk] = _eps_df.set_index('기준일자')['value']
        if _macro_db and tk in _macro_data:
            _tr_df = _macro_data[tk]
            tr_indices[tk] = _tr_df.set_index('기준일자')['value']

    # mockup으로 보충
    pe_bases = [18.5, 22.1, 13.8, 10.5, 15.8]
    eps_bases = [45.0, 55.0, 28.0, 32.0, 38.0]
    tr_mus = [0.0003, 0.0004, 0.0001, 0.0002, 0.00025]
    tr_sigmas = [0.008, 0.009, 0.012, 0.010, 0.008]
    for i, tk in enumerate(all_val_tickers):
        if tk not in pe_data:
            pe_data[tk] = pd.Series(pe_bases[i] + np.cumsum(np.random.normal(0, 0.05, n_md)), index=macro_dates)
        if tk not in eps_data:
            eps_data[tk] = pd.Series(eps_bases[i] + np.cumsum(np.random.normal(0.01, 0.08, n_md)), index=macro_dates)
        if tk not in tr_indices:
            tr_indices[tk] = pd.Series(100 * np.cumprod(1 + np.random.normal(tr_mus[i], tr_sigmas[i], n_md)), index=macro_dates)

    if _macro_db:
        st.caption("📡 SCIP DB 시계열 데이터")
        # 날짜 범위를 DB 데이터 기준으로 조정
        _all_dates = set()
        for v in [pe_data, eps_data, tr_indices]:
            for ts in v.values():
                if hasattr(ts, 'index'):
                    _all_dates.update(ts.index)
        if _all_dates:
            macro_dates = pd.DatetimeIndex(sorted(_all_dates))
            n_md = len(macro_dates)
    else:
        st.caption("⚠️ 목업 데이터 (DB 연결 시 SCIP 실데이터로 자동 전환)")

    # --- Total Return Decomposition ---
    st.markdown("### Total Return Decomposition")
    st.caption("TR = PE Ratio Growth + EPS Growth + Other (Dividend + Residual)")

    decomp_ticker = st.selectbox(
        "지수 선택", list(pe_data.keys()), key='tr_decomp_ticker'
    )
    decomp_period = st.radio("기간", ['3M', '6M', 'YTD', '1Y'], horizontal=True, key='tr_decomp_period')
    _ytd_bdays = len(macro_dates[macro_dates >= '2026-01-01']) if len(macro_dates[macro_dates >= '2026-01-01']) > 0 else 22
    period_map_macro = {'3M': 66, '6M': 132, 'YTD': _ytd_bdays, '1Y': 252}
    n_period = min(period_map_macro[decomp_period], n_md - 1)

    tr_arr = tr_indices[decomp_ticker].values if hasattr(tr_indices[decomp_ticker], 'values') else tr_indices[decomp_ticker]
    pe_arr = pe_data[decomp_ticker].values if hasattr(pe_data[decomp_ticker], 'values') else pe_data[decomp_ticker]
    eps_arr = eps_data[decomp_ticker].values if hasattr(eps_data[decomp_ticker], 'values') else eps_data[decomp_ticker]

    total_return = (tr_arr[-1] / tr_arr[max(0, -(n_period+1))] - 1) * 100 if len(tr_arr) > n_period else 0
    pe_growth = (pe_arr[-1] / pe_arr[max(0, -(n_period+1))] - 1) * 100 if len(pe_arr) > n_period else 0
    eps_growth = (eps_arr[-1] / eps_arr[max(0, -(n_period+1))] - 1) * 100 if len(eps_arr) > n_period else 0
    other = total_return - pe_growth - eps_growth

    dc1, dc2 = st.columns([3, 2])
    with dc1:
        fig_decomp = go.Figure(go.Waterfall(
            name="", orientation="v",
            x=['PE Ratio Growth', 'EPS Growth', 'Other (Div+Res)', 'Total Return'],
            y=[pe_growth, eps_growth, other, total_return],
            measure=['relative', 'relative', 'relative', 'total'],
            connector_line_color='#888',
            increasing_marker_color='#636EFA',
            decreasing_marker_color='#EF553B',
            totals_marker_color='#00CC96',
            text=[f"{pe_growth:+.1f}%", f"{eps_growth:+.1f}%", f"{other:+.1f}%", f"{total_return:+.1f}%"],
            textposition='outside'
        ))
        fig_decomp.update_layout(
            title=f'{decomp_ticker} Total Return Decomposition ({decomp_period})',
            height=420, yaxis_title='수익률 (%)', margin=dict(t=50, b=30)
        )
        st.plotly_chart(fig_decomp, width="stretch")

    with dc2:
        st.markdown("##### Decomposition Summary")
        summary_df = pd.DataFrame({
            '요인': ['PE Ratio Growth', 'EPS Growth', 'Other (Dividend+Residual)', 'Total Return'],
            '기여(%)': [f"{pe_growth:+.2f}", f"{eps_growth:+.2f}", f"{other:+.2f}", f"{total_return:+.2f}"],
            '비중': [
                f"{abs(pe_growth)/max(abs(total_return),0.01)*100:.0f}%",
                f"{abs(eps_growth)/max(abs(total_return),0.01)*100:.0f}%",
                f"{abs(other)/max(abs(total_return),0.01)*100:.0f}%",
                '100%'
            ]
        })
        st.dataframe(summary_df, hide_index=True, width="stretch")

        st.markdown("##### 현재 Valuation")
        vc1, vc2 = st.columns(2)
        vc1.metric("PE Ratio", f"{pe_arr[-1]:.1f}x",
                    f"{pe_arr[-1] - pe_arr[-22]:+.1f}x (1M)")
        vc2.metric("EPS", f"${eps_arr[-1]:.1f}",
                    f"{(eps_arr[-1]/eps_arr[-22]-1)*100:+.1f}% (1M)")

    st.markdown("---")

    # --- EPS & PE Ratio: 전체 기간, 모든 티커, 멀티셀렉트 위젯 (#5) ---
    st.markdown("### 주요 벤치마크 EPS & PE Ratio 추이")
    selected_val_tickers = st.multiselect(
        "표시할 티커 선택", all_val_tickers,
        default=all_val_tickers,
        key='val_ticker_select'
    )

    val_mode_c1, val_mode_c2 = st.columns([2, 1])
    with val_mode_c1:
        val_display_mode = st.radio("표시 모드", ['실제 값', 'Growth Rate'], horizontal=True, key='val_display_mode')
    with val_mode_c2:
        growth_period_val = None
        if val_display_mode == 'Growth Rate':
            growth_period_val = st.selectbox("Growth 기간", ['1M', '3M', '6M', 'YTD', '1Y'], key='growth_period_select')

    val_colors = px.colors.qualitative.Plotly + px.colors.qualitative.Set2

    if selected_val_tickers:
        if val_display_mode == 'Growth Rate':
            gp_map = {'1M': 22, '3M': 66, '6M': 132, '1Y': 252,
                       'YTD': max(1, len(macro_dates[macro_dates >= '2026-01-01']))}
            n_shift = min(gp_map.get(growth_period_val, 66), n_md - 1)
            fig_val = make_subplots(rows=1, cols=2,
                                     subplot_titles=(f'PE Ratio Growth Rate ({growth_period_val})',
                                                     f'EPS Growth Rate ({growth_period_val})'))
            for i, tk in enumerate(selected_val_tickers):
                c = val_colors[i % len(val_colors)]
                pe_s = pe_data[tk] if isinstance(pe_data[tk], pd.Series) else pd.Series(pe_data[tk], index=macro_dates)
                eps_s = eps_data[tk] if isinstance(eps_data[tk], pd.Series) else pd.Series(eps_data[tk], index=macro_dates)
                start_idx = max(0, len(pe_s) - n_shift - 1)
                pe_trimmed = pe_s.iloc[start_idx:]
                pe_indexed = (pe_trimmed / pe_trimmed.iloc[0] - 1) * 100
                eps_trimmed = eps_s.iloc[start_idx:]
                eps_indexed = (eps_trimmed / eps_trimmed.iloc[0] - 1) * 100
                fig_val.add_trace(go.Scatter(
                    x=pe_trimmed.index, y=pe_indexed.values, name=tk,
                    line=dict(color=c, width=2),
                    legendgroup=tk, showlegend=True
                ), row=1, col=1)
                fig_val.add_trace(go.Scatter(
                    x=eps_trimmed.index, y=eps_indexed.values, name=tk,
                    line=dict(color=c, width=2, dash='dot'),
                    legendgroup=tk, showlegend=False
                ), row=1, col=2)
            fig_val.update_layout(height=400, hovermode='x unified',
                                   legend=dict(orientation='h', y=1.10))
            fig_val.update_yaxes(title_text='PE Growth (%)', row=1, col=1)
            fig_val.update_yaxes(title_text='EPS Growth (%)', row=1, col=2)
        else:
            fig_val = make_subplots(rows=1, cols=2, subplot_titles=('PE Ratio 추이', 'EPS 추이'))
            for i, tk in enumerate(selected_val_tickers):
                c = val_colors[i % len(val_colors)]
                pe_s = pe_data[tk] if isinstance(pe_data[tk], pd.Series) else pd.Series(pe_data[tk], index=macro_dates)
                eps_s = eps_data[tk] if isinstance(eps_data[tk], pd.Series) else pd.Series(eps_data[tk], index=macro_dates)
                fig_val.add_trace(go.Scatter(
                    x=pe_s.index, y=pe_s.values, name=tk,
                    line=dict(color=c, width=2),
                    legendgroup=tk, showlegend=True
                ), row=1, col=1)
                fig_val.add_trace(go.Scatter(
                    x=eps_s.index, y=eps_s.values, name=tk,
                    line=dict(color=c, width=2, dash='dot'),
                    legendgroup=tk, showlegend=False
                ), row=1, col=2)
            fig_val.update_layout(height=400, hovermode='x unified',
                                   legend=dict(orientation='h', y=1.10))
            fig_val.update_yaxes(title_text='PE Ratio (x)', row=1, col=1)
            fig_val.update_yaxes(title_text='EPS ($)', row=1, col=2)
        st.plotly_chart(fig_val, width="stretch")

    st.markdown("---")

    # --- 원화 가치 분석 (#6, #7) ---
    st.markdown("### 원화 가치 분석")

    # USD/KRW: DB → fallback
    _usdkrw_ts = None
    if _macro_db and 'USD/KRW' in _macro_data:
        _usdkrw_df = _macro_data['USD/KRW']
        if not _usdkrw_df.empty:
            _usdkrw_ts = _usdkrw_df.set_index('기준일자')['value'].sort_index()

    if _usdkrw_ts is not None and len(_usdkrw_ts) > 100:
        fx_full_dates = _usdkrw_ts.index
        usdkrw_full = _usdkrw_ts.values
    else:
        fx_full_dates = pd.bdate_range('2017-01-02', '2026-02-11', freq='B')
        np.random.seed(77)
        usdkrw_full = 1150 + np.cumsum(np.random.normal(0.15, 2.5, len(fx_full_dates)))

    n_fx = len(fx_full_dates)
    # DXY는 mockup 유지 (SCIP에 DXY 시계열 미존재 or 별도 dataset 필요)
    np.random.seed(77)
    dxy_full = 101 + np.cumsum(np.random.normal(-0.005, 0.25, n_fx))

    col_fx1, col_fx2 = st.columns(2)

    with col_fx1:
        # 왼쪽: USD/KRW만 (#6)
        fig_krw = go.Figure()
        fig_krw.add_trace(go.Scatter(x=fx_full_dates, y=usdkrw_full, name='USD/KRW',
                                      line=dict(color='#AB63FA', width=2.5)))
        fig_krw.update_layout(title='USD/KRW', height=400,
                                yaxis_title='원/달러', hovermode='x unified',
                                legend=dict(orientation='h', y=1.05))
        st.plotly_chart(fig_krw, width="stretch")

    with col_fx2:
        # 오른쪽: USDKRW 일간수익률 - DXY 일간수익률 + 2.24σ 밴드 (#6)
        usdkrw_ret = np.diff(usdkrw_full) / usdkrw_full[:-1]
        dxy_ret = np.diff(dxy_full) / dxy_full[:-1]
        spread = usdkrw_ret - dxy_ret
        spread_dates = fx_full_dates[1:]

        # 누적 spread 또는 레벨 표시 — 롤링 평균과 밴드
        window = 60
        spread_rolling_mean = pd.Series(spread).rolling(window).mean().values
        spread_rolling_std = pd.Series(spread).rolling(window).std().values
        upper_band = spread_rolling_mean + 2.24 * spread_rolling_std
        lower_band = spread_rolling_mean - 2.24 * spread_rolling_std

        fig_spread = go.Figure()
        # 밴드 영역
        fig_spread.add_trace(go.Scatter(
            x=spread_dates, y=upper_band * 100, name='+2.24σ',
            line=dict(color='rgba(100,100,100,0.3)', width=1, dash='dash'),
            showlegend=True
        ))
        fig_spread.add_trace(go.Scatter(
            x=spread_dates, y=lower_band * 100, name='-2.24σ',
            line=dict(color='rgba(100,100,100,0.3)', width=1, dash='dash'),
            fill='tonexty', fillcolor='rgba(100,126,234,0.06)',
            showlegend=True
        ))
        # 평균선
        fig_spread.add_trace(go.Scatter(
            x=spread_dates, y=spread_rolling_mean * 100, name='평균',
            line=dict(color='#888', width=1.5, dash='dot')
        ))
        # 실제 spread
        fig_spread.add_trace(go.Scatter(
            x=spread_dates, y=spread * 100, name='KRW Return - DXY Return',
            line=dict(color='#EF553B', width=1.2)
        ))
        fig_spread.update_layout(
            title='USD/KRW 일간수익률 - DXY 일간수익률 (60일 롤링)',
            height=400, yaxis_title='수익률 차이 (%)',
            hovermode='x unified',
            legend=dict(orientation='h', y=1.10, font=dict(size=10))
        )
        st.plotly_chart(fig_spread, width="stretch")

    # #7: 주요 통화 기간수익률 제거

    st.markdown("---")

    # --- 글로벌 금리 추이 (#8) ---
    st.markdown("### 글로벌 금리 추이")

    # 금리 데이터: SCIP dataset (Treasury 2Y=6, 10Y=2) dataseries 7(YTM) 로드 시도
    _rates_db = False
    _rate_data = {}
    if DB_CONNECTED:
        try:
            from modules.data_loader import load_scip_prices as _lsp
            # US Treasury 2Y(6), 10Y(2), KR는 SCIP에 별도 dataset 필요
            _rates_raw = _lsp([2, 6], [7], '2024-01-01')
            if not _rates_raw.empty:
                for ds_id, label in [(2, 'US 10Y'), (6, 'US 2Y')]:
                    _sub = _rates_raw[_rates_raw['dataset_id'] == ds_id].copy()
                    if not _sub.empty:
                        _sub['value'] = _sub['data'].apply(lambda b: parse_data_blob(b))
                        _sub = _sub.dropna(subset=['value'])
                        _rate_data[label] = _sub.set_index('기준일자')['value'].sort_index()
                if _rate_data:
                    _rates_db = True
        except Exception:
            pass

    monthly_dates = pd.date_range('2024-01-01', '2026-02-01', freq='MS')
    n_rates = len(monthly_dates)

    if _rates_db and 'US 10Y' in _rate_data:
        # DB 데이터를 월말 리샘플
        us_10y_ts = _rate_data.get('US 10Y', pd.Series(dtype=float))
        us_2y_ts = _rate_data.get('US 2Y', pd.Series(dtype=float))
        if len(us_10y_ts) > 10:
            monthly_dates = us_10y_ts.resample('MS').last().dropna().index
            n_rates = len(monthly_dates)
            us_10y = us_10y_ts.resample('MS').last().dropna().values
            us_2y = us_2y_ts.resample('MS').last().dropna().values[:n_rates] if len(us_2y_ts) > 0 else us_10y - 0.2
        else:
            us_10y = 4.3 + np.cumsum(np.random.normal(-0.01, 0.08, n_rates))
            us_2y = 4.5 + np.cumsum(np.random.normal(-0.015, 0.06, n_rates))
    else:
        us_10y = 4.3 + np.cumsum(np.random.normal(-0.01, 0.08, n_rates))
        us_2y = 4.5 + np.cumsum(np.random.normal(-0.015, 0.06, n_rates))

    # 한국 금리는 mockup (SCIP에 KR 국채 YTM 별도 dataset)
    kr_10y = 3.5 + np.cumsum(np.random.normal(-0.01, 0.05, n_rates))
    kr_2y = 3.3 + np.cumsum(np.random.normal(-0.01, 0.04, n_rates))
    us_base = np.full(n_rates, 5.25)
    us_base[n_rates//2:] = 4.50
    kr_base = np.full(n_rates, 3.50)
    kr_base[n_rates*2//3:] = 3.00

    col_rate1, col_rate2 = st.columns(2)

    with col_rate1:
        # 왼쪽: 미국+한국 국채금리 통합 (#8)
        fig_bonds = go.Figure()
        fig_bonds.add_trace(go.Scatter(x=monthly_dates, y=us_10y, name='US 10Y',
                                        line=dict(color='#636EFA', width=2.5)))
        fig_bonds.add_trace(go.Scatter(x=monthly_dates, y=us_2y, name='US 2Y',
                                        line=dict(color='#636EFA', width=1.5, dash='dot')))
        fig_bonds.add_trace(go.Scatter(x=monthly_dates, y=kr_10y, name='KR 10Y',
                                        line=dict(color='#EF553B', width=2.5)))
        fig_bonds.add_trace(go.Scatter(x=monthly_dates, y=kr_2y, name='KR 2Y',
                                        line=dict(color='#EF553B', width=1.5, dash='dot')))
        all_rates = np.concatenate([us_10y, us_2y, kr_10y, kr_2y])
        fig_bonds.update_layout(title='미국/한국 국채금리', height=380,
                                  yaxis_title='금리 (%)',
                                  yaxis_range=[min(all_rates)*0.9, max(all_rates)*1.1],
                                  hovermode='x unified',
                                  legend=dict(orientation='h', y=1.08))
        st.plotly_chart(fig_bonds, width="stretch")

    with col_rate2:
        # 오른쪽: 미국/한국 기준금리 (#8)
        fig_policy = go.Figure()
        fig_policy.add_trace(go.Scatter(x=monthly_dates, y=us_base, name='미국 기준금리',
                                         line=dict(color='#636EFA', width=2.5, shape='hv')))
        fig_policy.add_trace(go.Scatter(x=monthly_dates, y=kr_base, name='한국 기준금리',
                                         line=dict(color='#EF553B', width=2.5, shape='hv')))
        all_base = np.concatenate([us_base, kr_base])
        fig_policy.update_layout(title='기준금리 (미국/한국)', height=380,
                                   yaxis_title='금리 (%)',
                                   yaxis_range=[min(all_base)*0.85, max(all_base)*1.15],
                                   hovermode='x unified',
                                   legend=dict(orientation='h', y=1.08))
        st.plotly_chart(fig_policy, width="stretch")

    st.markdown("---")

    # (기존 자산군별 벤치마크 mockup + 히트맵 삭제 — 상단 SCIP 실시간 테이블로 대체)
    # (기존 히트맵 삭제 — SCIP 실시간 테이블로 대체)
