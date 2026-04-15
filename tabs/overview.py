# -*- coding: utf-8 -*-
"""Tab 0: Overview — 기준가, 누적수익률, 기간성과, 편입현황 도넛"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from dateutil.relativedelta import relativedelta

from modules.charts import make_sparkline, hex_to_rgba, make_nav, make_bm_nav, calc_sharpe
from modules.data_loader import _FUND_INCEPTION_BASE


def render(ctx):
    """Overview 탭 렌더링. ctx: 공통 컨텍스트 dict"""
    selected_fund = ctx['selected_fund']
    fund_info = ctx['fund_info']
    lookthrough_on = ctx['lookthrough_on']
    DB_CONNECTED = ctx['DB_CONNECTED']
    FUND_BM = ctx['FUND_BM']
    FUND_META = ctx['FUND_META']
    ASSET_CLASSES = ctx['ASSET_CLASSES']
    ASSET_COLORS = ctx['ASSET_COLORS']
    ASSET_CLASS_ORDER = ctx['ASSET_CLASS_ORDER']
    SAMPLE_HOLDINGS_DETAIL = ctx['SAMPLE_HOLDINGS_DETAIL']
    dates = ctx['dates']
    cache = ctx['cache']

    # --- DB 데이터 로드 (fallback: mockup) ---
    _tab0_db = False
    if DB_CONNECTED:
        try:
            _inception = FUND_META.get(selected_fund, {}).get('inception', '20220101')
            _nav_df = cache['load_fund_nav'](selected_fund, _inception)
            if not _nav_df.empty and len(_nav_df) > 10:
                nav_data = _nav_df['MOD_STPR'].values
                _nav_dates = _nav_df['기준일자'].values
                _aum_series = _nav_df['AUM_억'].values

                # BM 로드: DT(DWPM10041) 우선 → SCIP fallback (설정일부터)
                _bm_df = pd.DataFrame()
                try:
                    _bm_df = cache['load_dt_bm'](selected_fund, _inception)
                    if _bm_df.empty or len(_bm_df) < 10:
                        _bm_cfg = FUND_BM.get(selected_fund)
                        _bm_df = pd.DataFrame()
                        _scip_start = f'{_inception[:4]}-{_inception[4:6]}-{_inception[6:8]}'
                        if _bm_cfg and 'components' in _bm_cfg:
                            import json as _json
                            _bm_df = cache['load_composite_bm'](
                                _json.dumps(_bm_cfg['components']), _scip_start
                            )
                        elif _bm_cfg:
                            _bm_df = cache['load_bm_prices'](
                                _bm_cfg['dataset_id'], _bm_cfg['dataseries_id'],
                                _scip_start, _bm_cfg.get('currency')
                            )
                except Exception:
                    _bm_df = pd.DataFrame()
                if not _bm_df.empty and len(_bm_df) > 10:
                    _bm_df = _bm_df.set_index('기준일자')
                    _nav_idx = pd.DatetimeIndex(_nav_dates)
                    _bm_aligned = _bm_df.reindex(_nav_idx, method='ffill')['value'].values
                    if np.isnan(_bm_aligned).sum() < len(_bm_aligned) * 0.5:
                        bm_data = _bm_aligned[~np.isnan(_bm_aligned)] if np.isnan(_bm_aligned).any() else _bm_aligned
                        _min_len = min(len(nav_data), len(bm_data))
                        nav_data = nav_data[-_min_len:]
                        bm_data = bm_data[-_min_len:]
                        _aum_series = _aum_series[-_min_len:]
                        _nav_dates = _nav_dates[-_min_len:]
                        dates_for_tab0 = pd.DatetimeIndex(_nav_dates)
                        _tab0_db = True
                    else:
                        bm_data = None
                        dates_for_tab0 = pd.DatetimeIndex(_nav_dates)
                        _tab0_db = True
                else:
                    bm_data = None
                    dates_for_tab0 = pd.DatetimeIndex(_nav_dates)
                    _tab0_db = True
            else:
                raise ValueError("NAV empty")
        except Exception as _e:
            _tab0_db = False
            st.toast(f"Tab0 DB 오류, 목업 사용: {_e}", icon="⚠️")

    if not _tab0_db:
        nav_data = make_nav(n=len(dates))
        bm_data = make_bm_nav(n=len(dates))
        dates_for_tab0 = dates
        _aum_series = fund_info['aum'] + np.cumsum(np.random.normal(0, 2, len(dates)))

    _has_bm = bm_data is not None
    daily_ret = np.diff(nav_data) / nav_data[:-1]
    daily_bm_ret = np.diff(bm_data) / bm_data[:-1] if _has_bm else np.full(len(daily_ret), np.nan)

    latest_nav = nav_data[-1]
    prev_nav = nav_data[-2]
    nav_change = latest_nav - prev_nav
    nav_change_pct = (nav_change / prev_nav) * 100
    _si_base = _FUND_INCEPTION_BASE.get(selected_fund, nav_data[0])
    si_return = (nav_data[-1] / _si_base - 1) * 100
    _ytd_mask = dates_for_tab0 >= pd.Timestamp('2026-01-01')
    ytd_idx = len(dates_for_tab0) - _ytd_mask.sum()
    ytd_return = (nav_data[-1] / nav_data[max(ytd_idx, 0)] - 1) * 100 if ytd_idx < len(nav_data) else 0.0
    bm_si = (bm_data[-1] / bm_data[0] - 1) * 100 if _has_bm else np.nan
    bm_ytd = (bm_data[-1] / bm_data[max(ytd_idx, 0)] - 1) * 100 if (_has_bm and ytd_idx < len(bm_data)) else np.nan

    # --- 지표 카드 + 3개월 스파크라인 ---
    c1, c2, c3, c4 = st.columns(4)
    spark_n = min(66, len(nav_data))
    spark_dates = dates_for_tab0[-spark_n:]

    with c1:
        with st.container(border=True):
            from config.funds import FUND_META as _FM_FULL
            _inception = fund_info.get('inception', _FM_FULL.get(selected_fund, {}).get('inception', ''))
            if _inception:
                _inc_fmt = f"{_inception[:4]}-{_inception[4:6]}-{_inception[6:8]}"
            else:
                _inc_fmt = '-'
            st.metric("설정일", _inc_fmt)
            spark_data = (nav_data[-spark_n:] / nav_data[-spark_n] - 1) * 100
            st.plotly_chart(make_sparkline(spark_data, '#636EFA', spark_dates=spark_dates, suffix='%'),
                            width="stretch", key="spark1")

    with c2:
        with st.container(border=True):
            st.metric("YTD 수익률", f"{ytd_return:.2f}%")
            if _has_bm:
                _bm_spark_n = min(spark_n, len(bm_data))
                spark_data2 = (bm_data[-_bm_spark_n:] / bm_data[-_bm_spark_n] - 1) * 100
                st.plotly_chart(make_sparkline(spark_data2, '#EF553B', spark_dates=spark_dates[-_bm_spark_n:], suffix='%'),
                                width="stretch", key="spark2")
            else:
                st.caption("BM 미설정")

    with c3:
        with st.container(border=True):
            st.metric("기준가", f"{latest_nav:,.2f}")
            st.plotly_chart(make_sparkline(nav_data[-spark_n:], '#00CC96', spark_dates=spark_dates),
                            width="stretch", key="spark3")

    with c4:
        with st.container(border=True):
            _aum_latest = _aum_series[-1] if len(_aum_series) > 0 else fund_info['aum']
            st.metric("AUM", f"{_aum_latest:.0f}억원")
            aum_spark = _aum_series[-spark_n:] if len(_aum_series) >= spark_n else _aum_series
            st.plotly_chart(make_sparkline(aum_spark, '#AB63FA', spark_dates=spark_dates[-len(aum_spark):]),
                            width="stretch", key="spark4")

    if _tab0_db:
        st.caption("📡 실시간 DB 데이터")

    st.markdown("")

    # --- 기간별 성과 테이블 ---
    def _find_ref_value(dates_arr, data_arr, target_date):
        idx = pd.DatetimeIndex(dates_arr)
        mask = idx <= target_date
        if not mask.any():
            return np.nan
        pos = np.where(mask)[0][-1]
        return data_arr[pos]

    _end_dt = pd.Timestamp(dates_for_tab0[-1])
    _period_targets = {
        '1D': _end_dt - pd.Timedelta(days=1),
        '1W': _end_dt - pd.Timedelta(days=7),
        '1M': _end_dt - relativedelta(months=1),
        '3M': _end_dt - relativedelta(months=3),
        '6M': _end_dt - relativedelta(months=6),
        'YTD': pd.Timestamp(f'{_end_dt.year}0101'),
        '1Y': _end_dt - relativedelta(years=1),
        '설정 후': pd.Timestamp('1900-01-01'),
    }
    _end_nav = nav_data[-1]
    _end_bm = bm_data[-1] if _has_bm else np.nan

    row_port = {}
    row_bm = {}
    row_excess = {}
    row_vol = {}
    row_sharpe = {}
    period_order = ['1D', '1W', '1M', '3M', '6M', 'YTD', '1Y', '설정 후']
    for p in period_order:
        if p == '설정 후':
            _nav_base = _FUND_INCEPTION_BASE.get(selected_fund, nav_data[0])
            pr = (_end_nav / _nav_base - 1) * 100
            br = (_end_bm / bm_data[0] - 1) * 100 if _has_bm else np.nan
        else:
            target = _period_targets[p]
            ref_nav = _find_ref_value(dates_for_tab0, nav_data, target)
            ref_bm = _find_ref_value(dates_for_tab0, bm_data, target) if _has_bm else np.nan
            pr = (_end_nav / ref_nav - 1) * 100 if not np.isnan(ref_nav) and ref_nav != 0 else np.nan
            br = (_end_bm / ref_bm - 1) * 100 if (_has_bm and not np.isnan(ref_bm) and ref_bm != 0) else np.nan
        row_port[p] = f"{pr:.2f}%" if not np.isnan(pr) else ""
        row_bm[p] = f"{br:.2f}%" if not np.isnan(br) else ""
        exc = pr - br if not (np.isnan(pr) or np.isnan(br)) else np.nan
        row_excess[p] = f"{exc:+.2f}%p" if not np.isnan(exc) else ""
        _bday_map = {'1D': 1, '1W': 5, '1M': 22, '3M': 66, '6M': 132, '1Y': 252,
                     'YTD': max(1, len(dates_for_tab0) - ytd_idx), '설정 후': len(nav_data)-1}
        _n = _bday_map.get(p, len(daily_ret))
        _sh = calc_sharpe(daily_ret[-min(_n, len(daily_ret)):]) if _n <= len(daily_ret) else np.nan
        row_sharpe[p] = f"{_sh:.2f}" if not np.isnan(_sh) else ""
        _vol_slice = daily_ret[-min(_n, len(daily_ret)):]
        if len(_vol_slice) >= 5:
            _weekly = np.array([np.prod(1 + _vol_slice[i:i+5]) - 1 for i in range(0, len(_vol_slice)-4, 5)])
            _vol = np.std(_weekly, ddof=1) * np.sqrt(52) * 100 if len(_weekly) > 1 else np.nan
        else:
            _vol = np.nan
        row_vol[p] = f"{_vol:.2f}%" if not np.isnan(_vol) else ""

    _rows = [{'구분': '포트폴리오', **{p: row_port[p] for p in period_order}}]
    if _has_bm:
        _rows.append({'구분': 'BM', **{p: row_bm[p] for p in period_order}})
        _rows.append({'구분': '초과수익', **{p: row_excess[p] for p in period_order}})
    _rows.append({'구분': '변동성', **{p: row_vol[p] for p in period_order}})
    _rows.append({'구분': 'Sharpe', **{p: row_sharpe[p] for p in period_order}})
    perf_df = pd.DataFrame(_rows)

    st.dataframe(perf_df, hide_index=True, width="stretch", height=180 if _has_bm else 140)

    st.markdown("")

    # --- 누적수익률 (좌) + MDD (우) ---
    col_cum, col_mdd = st.columns(2)

    _chart_nav_base = _FUND_INCEPTION_BASE.get(selected_fund, nav_data[0])
    cum_ret = (nav_data / _chart_nav_base - 1) * 100

    with col_cum:
        fig = go.Figure()
        if _has_bm:
            cum_bm = (bm_data / bm_data[0] - 1) * 100
            excess = cum_ret - cum_bm
            fig.add_trace(go.Scatter(
                x=dates_for_tab0, y=excess, name='초과수익',
                fill='tozeroy',
                fillcolor='rgba(144, 238, 144, 0.20)',
                line=dict(color='rgba(144, 238, 144, 0.5)', width=0.8),
            ))
        fig.add_trace(go.Scatter(
            x=dates_for_tab0, y=cum_ret, name='포트폴리오',
            line=dict(color='#636EFA', width=2.5)
        ))
        if _has_bm:
            fig.add_trace(go.Scatter(
                x=dates_for_tab0, y=cum_bm, name='BM',
                line=dict(color='#EF553B', width=2, dash='dot')
            ))
        fig.update_traces(hovertemplate='%{y:.2f}%')
        fig.update_layout(
            title='누적수익률 추이',
            yaxis_title='수익률 (%)',
            yaxis_tickformat='.2f',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            height=400, margin=dict(t=50, b=30),
            hovermode='x unified'
        )
        st.plotly_chart(fig, width="stretch")

    with col_mdd:
        # MDD 계산: 고점 대비 낙폭
        running_max = np.maximum.accumulate(nav_data)
        drawdown = (nav_data / running_max - 1) * 100

        fig_mdd = go.Figure()
        fig_mdd.add_trace(go.Scatter(
            x=dates_for_tab0, y=drawdown, name='MDD',
            fill='tozeroy', fillcolor='rgba(239, 85, 59, 0.15)',
            line=dict(color='#EF553B', width=1.5),
        ))
        if _has_bm:
            bm_max = np.maximum.accumulate(bm_data)
            bm_dd = (bm_data / bm_max - 1) * 100
            fig_mdd.add_trace(go.Scatter(
                x=dates_for_tab0, y=bm_dd, name='BM MDD',
                line=dict(color='#636EFA', width=1, dash='dot'),
            ))
        current_mdd = drawdown[-1]
        max_mdd = np.min(drawdown)
        fig_mdd.update_traces(hovertemplate='%{y:.2f}%')
        fig_mdd.update_layout(
            title=f'MDD 추이 (현재: {current_mdd:.1f}%, 최대: {max_mdd:.1f}%)',
            yaxis_title='Drawdown (%)',
            yaxis_tickformat='.1f',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            height=400, margin=dict(t=50, b=30),
            hovermode='x unified'
        )
        st.plotly_chart(fig_mdd, width="stretch")

    # ctx에 다른 탭이 필요로 하는 데이터 저장
    ctx['nav_data'] = nav_data
    ctx['bm_data'] = bm_data
    ctx['dates_for_tab0'] = dates_for_tab0
    ctx['_aum_series'] = _aum_series
    ctx['_tab0_db'] = _tab0_db
    ctx['_nav_df'] = _nav_df if _tab0_db and '_nav_df' in dir() else None
