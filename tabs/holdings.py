# -*- coding: utf-8 -*-
"""Tab 1: 편입종목 & MP Gap"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

from modules.charts import hex_to_rgba, make_nav
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

    view_mode = st.radio(
        "보기 모드", ["자산군별", "종목별"],
        horizontal=True, key="holdings_toggle"
    )

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
            st.toast(f"Tab1 보유종목 DB 오류, 목업 사용: {_e}", icon="⚠️")

    # ctx에 저장 (다른 탭에서 참조)
    ctx['_tab1_db'] = _tab1_db
    ctx['_tab1_hold'] = _tab1_hold

    col_hold2, col_gap2 = st.columns(2)

    with col_hold2:
        st.markdown("#### 편입종목 현황")
        if _tab1_db:
            _t1_date = _tab1_hold['기준일자'].iloc[0].strftime('%Y-%m-%d') if '기준일자' in _tab1_hold.columns else '최근'
            st.caption(f"{_t1_date} 기준 | 📡 DB")
        else:
            st.caption("2026-02-11 기준")

        if view_mode == "자산군별":
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
            fig_pie.update_layout(title='자산군별 비중', height=350, margin=dict(t=40, b=20), showlegend=False)
            st.plotly_chart(fig_pie, width="stretch")

            grp_display = grp.copy()
            grp_display.columns = ['자산군', '비중(%)', '평가금액(억)']
            st.dataframe(grp_display, hide_index=True, width="stretch")

        else:
            if _tab1_db:
                _sec_df = _tab1_hold[['자산군', 'ITEM_NM', '비중(%)', '평가금액(억)']].copy()
                _sec_df = _sec_df.rename(columns={'ITEM_NM': '종목명'})
                top_sec = _sec_df.nlargest(10, '비중(%)')
            else:
                _sec_df = SAMPLE_HOLDINGS_DETAIL
                top_sec = _sec_df.nlargest(10, '비중(%)')

            fig_pie_sec = go.Figure(data=[go.Pie(
                labels=top_sec['종목명'], values=top_sec['비중(%)'],
                hole=0.45, textinfo='label+percent',
                customdata=top_sec['평가금액(억)'].values,
                hovertemplate='%{label}<br>비중: %{percent}<br>평가금액: %{customdata:,.1f}(억)<extra></extra>'
            )])
            fig_pie_sec.update_layout(title='종목별 비중 (Top 10)', height=350, margin=dict(t=40, b=20), showlegend=False)
            st.plotly_chart(fig_pie_sec, width="stretch")

            if _tab1_db:
                _sec_df['_sort'] = _sec_df['자산군'].map(ASSET_CLASS_ORDER).fillna(99)
                _sec_sorted = _sec_df.sort_values(['_sort', '비중(%)'], ascending=[True, False]).drop(columns='_sort')
                st.dataframe(_sec_sorted, hide_index=True, width="stretch", height=400)
            else:
                display_cols2 = ['자산군', '종목명', '비중(%)', '평가금액(억)', '1D(%)', '1W(%)', '1M(%)', 'YTD(%)']
                st.dataframe(
                    SAMPLE_HOLDINGS_DETAIL[display_cols2].style.map(
                        lambda v: 'color: #EF553B' if isinstance(v, (int, float)) and v < 0 else (
                            'color: #00CC96' if isinstance(v, (int, float)) and v > 0 else ''),
                        subset=['1D(%)', '1W(%)', '1M(%)', 'YTD(%)']
                    ),
                    hide_index=True, width="stretch", height=400
                )

    with col_gap2:
        if fund_info['has_mp']:
            st.markdown("#### MP 대비 Gap 분석")
            st.caption("Over/Under weight 현황")

            if _tab1_db:
                _ap_weights = _tab1_hold.groupby('자산군')['비중(%)'].sum()
                _ap_weights = _ap_weights.reindex(ASSET_CLASSES).fillna(0)
                _ap_list = _ap_weights.values.tolist()
            else:
                _ap_list = [25.3, 30.1, 22.5, 8.2, 10.5, 0.0, 0.0, 3.4]

            _mp_8class = FUND_MP_DIRECT.get(selected_fund)
            if not _mp_8class:
                _mp_desc = FUND_MP_MAPPING.get(selected_fund)
                if DB_CONNECTED and _mp_desc:
                    try:
                        _mp_8class = cache['load_mp_weights_8class'](_mp_desc)
                    except Exception:
                        pass
            if _mp_8class:
                _mp_list = [_mp_8class.get(ac, 0.0) for ac in ASSET_CLASSES]
            else:
                _mp_list = [25.0, 30.0, 25.0, 10.0, 8.0, 0.0, 0.0, 2.0]

            gap_data = {
                '자산군': ASSET_CLASSES,
                '실제(%)': _ap_list,
                'MP(%)': _mp_list,
            }
            gap_df = pd.DataFrame(gap_data)
            gap_df['Gap(%p)'] = gap_df['실제(%)'] - gap_df['MP(%)']
            gap_df['상태'] = gap_df['Gap(%p)'].apply(
                lambda x: 'Over' if x > 5.0 else ('Under' if x < -5.0 else '적정')
            )

            colors = ['#EF553B' if g > 0 else '#636EFA' for g in gap_df['Gap(%p)']]
            fig_gap = go.Figure()
            fig_gap.add_trace(go.Bar(
                y=gap_df['자산군'], x=gap_df['Gap(%p)'],
                orientation='h', marker_color=colors,
                text=[f"{g:+.1f}%p" for g in gap_df['Gap(%p)']],
                textposition='outside'
            ))
            fig_gap.add_vline(x=0, line_dash="solid", line_color="black", line_width=1)
            fig_gap.add_vrect(x0=-5.0, x1=5.0, fillcolor="green", opacity=0.05,
                              annotation_text="허용범위 ±5.0%p", annotation_position="top right")
            fig_gap.update_layout(
                title='MP Gap (실제 - MP)', height=300, margin=dict(t=40, b=20, l=80),
                xaxis_title='Gap (%p)', yaxis=dict(autorange='reversed')
            )
            st.plotly_chart(fig_gap, width="stretch")

            fig_comp = go.Figure()
            fig_comp.add_trace(go.Bar(name='실제(AP)', x=ASSET_CLASSES, y=gap_df['실제(%)'], marker_color='#636EFA'))
            fig_comp.add_trace(go.Bar(name='MP', x=ASSET_CLASSES, y=gap_df['MP(%)'], marker_color='#EF553B', opacity=0.65))
            max_y = max(max(gap_df['실제(%)']), max(gap_df['MP(%)'])) * 1.2
            fig_comp.update_layout(title='AP vs MP 비중 비교', barmode='group', height=280,
                                     yaxis_title='비중(%)', yaxis_range=[0, max_y],
                                     legend=dict(orientation='h', y=1.05),
                                     margin=dict(t=50, b=20))
            st.plotly_chart(fig_comp, width="stretch")
        else:
            st.markdown("#### MP 미설정")
            st.info(f"'{fund_info['short']}' 펀드는 MP(Model Portfolio)가 설정되지 않은 펀드입니다.\n\n"
                    f"MP Gap 분석은 MP가 설정된 OCIO/MySuper 펀드에서만 사용 가능합니다.")
            st.markdown("")
            st.markdown("**MP 설정 펀드 목록:**")
            FUND_META = ctx['FUND_META']
            mp_funds = [f"{FUND_META[k]['short']}" for k in FUND_META if FUND_META[k]['has_mp']]
            st.write(", ".join(mp_funds))

    # 비중 추이
    st.markdown("---")
    st.markdown("#### 비중 추이")
    hist_dates = pd.bdate_range('2025-06-01', '2026-02-11', freq='BMS')

    _hist_db = False
    _hist_df = None
    if DB_CONNECTED:
        try:
            _hist_df = cache['load_holdings_history'](selected_fund, '20250601')
            if not _hist_df.empty and _hist_df['기준일자'].nunique() > 2:
                _hist_db = True
        except Exception:
            pass

    _tab0_db = ctx.get('_tab0_db', False)
    _nav_df = ctx.get('_nav_df')

    if view_mode == "자산군별":
        col_trend_al, col_trend_ar = st.columns(2)
        with col_trend_al:
            fig_stack = go.Figure()
            if _hist_db:
                for ac in ASSET_CLASSES:
                    _ac_data = _hist_df[_hist_df['AST_CLSF_CD_NM'].str.contains(ac[:2], na=False)]
                    if not _ac_data.empty:
                        _ac_grp = _ac_data.groupby('기준일자')['total_weight'].sum().sort_index()
                        fig_stack.add_trace(go.Scatter(
                            x=_ac_grp.index, y=_ac_grp.values, name=ac,
                            stackgroup='one', fillcolor=ASSET_COLORS.get(ac, '#999999'),
                            line=dict(width=0.5, color=ASSET_COLORS.get(ac, '#999999'))
                        ))
                if len(fig_stack.data) == 0:
                    for ac_nm in _hist_df['AST_CLSF_CD_NM'].unique():
                        _ac_data = _hist_df[_hist_df['AST_CLSF_CD_NM'] == ac_nm]
                        _ac_grp = _ac_data.groupby('기준일자')['total_weight'].sum().sort_index()
                        fig_stack.add_trace(go.Scatter(
                            x=_ac_grp.index, y=_ac_grp.values, name=str(ac_nm),
                            stackgroup='one',
                            line=dict(width=0.5)
                        ))
            else:
                base_weights = [25.3, 30.1, 22.5, 8.2, 10.5, 0.0, 0.0, 3.4]
                for i, ac in enumerate(ASSET_CLASSES):
                    w = base_weights[i] + np.cumsum(np.random.normal(0, 0.3, len(hist_dates)))
                    fig_stack.add_trace(go.Scatter(
                        x=hist_dates, y=w, name=ac,
                        stackgroup='one', fillcolor=ASSET_COLORS.get(ac, '#999999'),
                        line=dict(width=0.5, color=ASSET_COLORS.get(ac, '#999999'))
                    ))
            fig_stack.update_layout(title='자산군별 비중 추이',
                height=350, margin=dict(t=40, b=20),
                yaxis_title='비중 (%)', legend=dict(orientation='h', y=-0.25),
                hovermode='x unified')
            st.plotly_chart(fig_stack, width="stretch")
        with col_trend_ar:
            _render_nav_trend(hist_dates, fund_info, _tab0_db, _nav_df)
    else:
        col_trend_l, col_trend_r = st.columns(2)
        with col_trend_l:
            if _tab1_db:
                all_secs = _tab1_hold['ITEM_NM'].tolist()
                all_weights = _tab1_hold['비중(%)'].tolist()
            else:
                all_secs = SAMPLE_HOLDINGS_DETAIL['종목명'].tolist()
                all_weights = SAMPLE_HOLDINGS_DETAIL['비중(%)'].tolist()
            sec_palette = px.colors.qualitative.Plotly + px.colors.qualitative.Set2 + px.colors.qualitative.Pastel
            fig_stack = go.Figure()
            for i, sec in enumerate(all_secs):
                w = all_weights[i] + np.cumsum(np.random.normal(0, 0.15, len(hist_dates)))
                fig_stack.add_trace(go.Scatter(
                    x=hist_dates, y=w, name=sec,
                    stackgroup='one', fillcolor=sec_palette[i % len(sec_palette)],
                    line=dict(width=0.5, color=sec_palette[i % len(sec_palette)])
                ))
            fig_stack.update_layout(title='종목별 비중 추이 (전체)',
                height=350, margin=dict(t=40, b=20),
                yaxis_title='비중 (%)', legend=dict(orientation='h', y=-0.25, font=dict(size=9)),
                hovermode='x unified')
            st.plotly_chart(fig_stack, width="stretch")

        with col_trend_r:
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
        height=350, margin=dict(t=40, b=20),
        yaxis_title='NAV (억원)', hovermode='x unified',
        showlegend=False)
    st.plotly_chart(fig_nav, width="stretch")
