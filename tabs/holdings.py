# -*- coding: utf-8 -*-
"""Tab 1: 편입종목 & MP Gap"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

from modules.charts import hex_to_rgba, make_nav
from modules.duration_fetcher import compute_weighted_duration, DURATION_SOURCES
from config.funds import FUND_MP_MAPPING, FUND_MP_DIRECT


def render(ctx):
    selected_fund = ctx['selected_fund']
    fund_info = ctx['fund_info']
    lookthrough_on = ctx['lookthrough_on']
    DB_CONNECTED = ctx['DB_CONNECTED']
    ASSET_CLASSES = ctx['ASSET_CLASSES']
    ASSET_COLORS = ctx['ASSET_COLORS']
    ASSET_CLASS_ORDER = ctx['ASSET_CLASS_ORDER']
    SAMPLE_HOLDINGS_DETAIL = ctx['SAMPLE_HOLDINGS_DETAIL']
    cache = ctx['cache']

    # DB 보유종목 로드
    _tab1_db = False
    _tab1_hold = None
    if DB_CONNECTED:
        try:
            if lookthrough_on:
                _tab1_hold = cache['load_holdings_lookthrough'](selected_fund)
            else:
                _tab1_hold = cache['load_holdings'](selected_fund)
            if not _tab1_hold.empty:
                _tab1_db = True
            else:
                raise ValueError("Holdings empty")
        except Exception as _e:
            st.toast(f"보유종목 DB 오류, 목업 사용: {_e}", icon="⚠️")

    ctx['_tab1_db'] = _tab1_db
    ctx['_tab1_hold'] = _tab1_hold

    if _tab1_db:
        _t1_date = _tab1_hold['기준일자'].iloc[0].strftime('%Y-%m-%d') if '기준일자' in _tab1_hold.columns else '최근'
        st.caption(f"{_t1_date} 기준")

    # ── 채권성 가중평균 듀레이션·YTM 카드 ──
    _dur_summary = None
    if _tab1_db and 'ITEM_CD' in _tab1_hold.columns:
        try:
            _dur_summary = compute_weighted_duration(
                list(zip(_tab1_hold['ITEM_CD'], _tab1_hold['비중(%)']))
            )
        except Exception as _e:
            st.toast(f"듀레이션 fetch 실패: {_e}", icon="⚠️")
    if _dur_summary and _dur_summary['covered_weight'] > 0:
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.metric(
                "Duration (채권만)",
                f"{_dur_summary['duration_bond']:.2f}년" if _dur_summary['duration_bond'] is not None else "—",
                help=f"매핑 종목 {len(_dur_summary['components'])}건 (분모=채권 비중)",
            )
        with c2:
            st.metric(
                "YTM (채권만)",
                f"{_dur_summary['ytm_bond']:.2f}%" if _dur_summary['ytm_bond'] is not None else "—",
            )
        with c3:
            st.metric(
                "Duration (전체)",
                f"{_dur_summary['duration_overall']:.2f}년" if _dur_summary['duration_overall'] is not None else "—",
                help="전체 보유비중 분모 (미매핑 종목 dur=0 가정)",
            )
        with c4:
            st.metric(
                "YTM (전체)",
                f"{_dur_summary['ytm_overall']:.2f}%" if _dur_summary['ytm_overall'] is not None else "—",
            )
        with c5:
            st.metric(
                "채권성 비중",
                f"{_dur_summary['covered_weight']:.1f}%",
                help=f"매핑된 종목 합산 / 전체 {_dur_summary['total_weight']:.1f}%",
            )

    # 좌=자산군별, 우=종목별
    col_asset, col_item = st.columns(2)

    with col_asset:
        st.markdown("#### 자산군별")
        if _tab1_db:
            grp = _tab1_hold.groupby('자산군').agg(
                {'비중(%)': 'sum', '평가금액(억)': 'sum'}
            ).reset_index()
        else:
            grp = SAMPLE_HOLDINGS_DETAIL.groupby('자산군').agg(
                {'비중(%)': 'sum', '평가금액(억)': 'sum'}
            ).reset_index()
        grp['_sort'] = grp['자산군'].map(ASSET_CLASS_ORDER).fillna(99)
        grp = grp.sort_values('_sort').drop(columns='_sort')

        fig_pie = go.Figure(data=[go.Pie(
            labels=grp['자산군'], values=grp['비중(%)'],
            hole=0.45, textinfo='label+percent',
            marker_colors=[ASSET_COLORS.get(a, '#999') for a in grp['자산군']],
            customdata=grp['평가금액(억)'].values,
            hovertemplate='%{label}<br>비중: %{percent}<br>평가금액: %{customdata:,.1f}(억)<extra></extra>'
        )])
        fig_pie.update_layout(height=300, margin=dict(t=10, b=10), showlegend=False)
        st.plotly_chart(fig_pie, width="stretch")

        grp_display = grp.copy()
        grp_display.columns = ['자산군', '비중(%)', '평가금액(억)']
        st.dataframe(grp_display, hide_index=True, width="stretch")

    with col_item:
        st.markdown("#### 종목별")
        if _tab1_db:
            _cols = ['자산군', 'ITEM_NM', '비중(%)', '평가금액(억)']
            if 'ITEM_CD' in _tab1_hold.columns:
                _cols.insert(0, 'ITEM_CD')
            _sec_df = _tab1_hold[_cols].copy()
            _sec_df = _sec_df.rename(columns={'ITEM_NM': '종목명'})
        else:
            _sec_df = SAMPLE_HOLDINGS_DETAIL.copy()

        # 유동성 → 현금성자산 / 기타 분리
        _CASH_ITEMS = {'예금', 'USD DEPOSIT'}
        _liq_mask = _sec_df['자산군'] == '유동성'
        _sec_df.loc[_liq_mask & _sec_df['종목명'].isin(_CASH_ITEMS), '자산군'] = '현금성자산'
        _sec_df.loc[_liq_mask & ~_sec_df['종목명'].isin(_CASH_ITEMS), '자산군'] = '기타'

        top_sec = _sec_df.nlargest(10, '비중(%)')

        fig_pie_sec = go.Figure(data=[go.Pie(
            labels=top_sec['종목명'], values=top_sec['비중(%)'],
            hole=0.45, textinfo='label+percent',
            customdata=top_sec['평가금액(억)'].values,
            hovertemplate='%{label}<br>비중: %{percent}<br>평가금액: %{customdata:,.1f}(억)<extra></extra>'
        )])
        fig_pie_sec.update_layout(height=350, margin=dict(t=10, b=40), showlegend=False)
        st.plotly_chart(fig_pie_sec, width="stretch")

        st.markdown("")  # 간격

        if _tab1_db or not _sec_df.empty:
            _sec_df['_sort'] = _sec_df['자산군'].map(ASSET_CLASS_ORDER).fillna(99)
            _sec_sorted = _sec_df.sort_values(['_sort', '비중(%)'], ascending=[True, False]).drop(columns='_sort')
            _sec_sorted = _sec_sorted[_sec_sorted['비중(%)'] > 0.01]

            # 듀레이션·YTM 컬럼 join (매핑된 종목만 값 채움)
            if _dur_summary and 'ITEM_CD' in _sec_sorted.columns:
                _comp_map = {c['item_cd']: c for c in _dur_summary['components']}
                _sec_sorted['Duration'] = _sec_sorted['ITEM_CD'].map(
                    lambda ic: _comp_map.get(ic, {}).get('duration')
                )
                _sec_sorted['YTM(%)'] = _sec_sorted['ITEM_CD'].map(
                    lambda ic: _comp_map.get(ic, {}).get('ytm')
                )
                # ITEM_CD 컬럼은 표시 시 숨김
                _sec_sorted = _sec_sorted.drop(columns=['ITEM_CD'])

            _h = max(200, 35 * len(_sec_sorted) + 40)
            _col_cfg = {}
            if 'Duration' in _sec_sorted.columns:
                _col_cfg['Duration'] = st.column_config.NumberColumn('Duration', format='%.2f')
            if 'YTM(%)' in _sec_sorted.columns:
                _col_cfg['YTM(%)'] = st.column_config.NumberColumn('YTM(%)', format='%.2f')
            st.dataframe(_sec_sorted, hide_index=True, width="stretch", height=_h,
                         column_config=_col_cfg if _col_cfg else None)

    # 비중 추이
    st.markdown("---")
    st.markdown("#### 비중 추이")
    hist_dates = pd.bdate_range('2025-06-01', '2026-02-11', freq='BMS')

    _hist_db = False
    _hist_8class = None
    if DB_CONNECTED:
        try:
            _hist_8class = cache['load_holdings_history_8class'](selected_fund)
            if _hist_8class is not None and not _hist_8class.empty and len(_hist_8class) > 2:
                _hist_db = True
        except Exception:
            pass

    _tab0_db = ctx.get('_tab0_db', False)
    _nav_df = ctx.get('_nav_df')

    col_trend_al, col_trend_ar = st.columns(2)
    with col_trend_al:
        fig_stack = go.Figure()
        if _hist_db:
            ac_cols = [c for c in _hist_8class.columns if c != '기준일자']
            # 100% 환산
            _row_totals = _hist_8class[ac_cols].sum(axis=1).replace(0, 1)
            for ac in ASSET_CLASSES:
                if ac in ac_cols:
                    vals = _hist_8class[ac] / _row_totals * 100
                    if vals.sum() > 0:
                        fig_stack.add_trace(go.Scatter(
                            x=_hist_8class['기준일자'], y=vals, name=ac,
                            stackgroup='one', fillcolor=ASSET_COLORS.get(ac, '#999'),
                            line=dict(width=0.5, color=ASSET_COLORS.get(ac, '#999'))
                        ))
        fig_stack.update_layout(title='자산군별 비중 추이',
            height=350, margin=dict(t=40, b=20, l=40, r=10),
            yaxis_title='비중 (%)', yaxis_range=[0, 100],
            legend=dict(orientation='h', y=-0.15, font=dict(size=9)),
            hovermode='x unified')
        st.plotly_chart(fig_stack, width="stretch")
    with col_trend_ar:
        _render_nav_trend(hist_dates, fund_info, _tab0_db, _nav_df)


def _render_nav_trend(hist_dates, fund_info, _tab0_db, _nav_df):
    """NAV 시계열 영역차트 (비중추이 우측)"""
    if _tab0_db and _nav_df is not None and not _nav_df.empty:
        _recent_nav = _nav_df[_nav_df['기준일자'] >= '2025-06-01']
        if not _recent_nav.empty:
            fig_nav = go.Figure()
            fig_nav.add_trace(go.Scatter(
                x=_recent_nav['기준일자'], y=_recent_nav['AUM_억'], name='NAV',
                fill='tozeroy', fillcolor=hex_to_rgba('#636EFA', 0.15),
                line=dict(color='#636EFA', width=2)
            ))
        else:
            nav_hist = make_nav(start=fund_info['aum'] * 1e8, mu=0.0003, sigma=0.003, n=len(hist_dates))
            fig_nav = go.Figure()
            fig_nav.add_trace(go.Scatter(
                x=hist_dates, y=nav_hist / 1e8, name='NAV',
                fill='tozeroy', fillcolor=hex_to_rgba('#636EFA', 0.15),
                line=dict(color='#636EFA', width=2)
            ))
    else:
        nav_hist = make_nav(start=fund_info['aum'] * 1e8, mu=0.0003, sigma=0.003, n=len(hist_dates))
        fig_nav = go.Figure()
        fig_nav.add_trace(go.Scatter(
            x=hist_dates, y=nav_hist / 1e8, name='NAV',
            fill='tozeroy', fillcolor=hex_to_rgba('#636EFA', 0.15),
            line=dict(color='#636EFA', width=2)
        ))
    fig_nav.update_layout(title='NAV 시계열',
        height=350, margin=dict(t=40, b=20, l=40, r=10),
        yaxis_title='NAV (억원)', hovermode='x unified',
        showlegend=False)
    st.plotly_chart(fig_nav, width="stretch")
