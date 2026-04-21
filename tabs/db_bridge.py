# -*- coding: utf-8 -*-
"""퇴직연금 DB 현황 — DBO/사외적립자산 변동 원인 분석 (MOCKUP)."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from modules.mock_db_pension_data import (
    BRIDGE_DBO, BRIDGE_ASSET, BRIDGE_KPI, BRIDGE_HISTORY,
)


def _mini_bar(values, color='#636EFA', height=60, width=120):
    """미니 바차트 (카드 우측 삽입용)."""
    fig = go.Figure(go.Bar(
        x=list(range(len(values))), y=values,
        marker_color=color, opacity=0.7,
    ))
    fig.update_layout(
        height=height, width=width,
        margin=dict(t=0, b=0, l=0, r=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig


def render(ctx):
    st.markdown("#### 퇴직연금 DB 현황")
    st.caption("MOCKUP 데이터 — 실데이터 연동 시 자동 교체")

    k = BRIDGE_KPI
    h = BRIDGE_HISTORY
    dbo_chg = k['기말_DBO'] - k['기초_DBO']
    asset_chg = k['기말_자산'] - k['기초_자산']
    dbo_growth_pct = dbo_chg / k['기초_DBO'] * 100
    asset_growth_pct = asset_chg / k['기초_자산'] * 100
    funding_ratio = k['기말_자산'] / k['기말_DBO'] * 100
    required_ret = dbo_chg / k['기초_자산'] * 100

    # 직전 3~4개년 데이터
    hist_dbo = h['DBO'][-4:]
    hist_asset = h['사외적립자산'][-4:]
    hist_fr = h['적립률'][-4:]
    hist_dbo_gr = h['DBO_증가율'][-4:]
    hist_ret = h['운용수익률'][-4:]

    # ── 상단 KPI 카드 (6개) ──
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    with c1:
        st.metric("기말 DBO", f"{k['기말_DBO']:,.0f}억",
                  delta=f"전년대비 {dbo_chg:+,.0f}억 ({dbo_growth_pct:+.1f}%)", delta_color="inverse")

    with c2:
        st.metric("기말 사외적립자산", f"{k['기말_자산']:,.0f}억",
                  delta=f"전년대비 {asset_chg:+,.0f}억 ({asset_growth_pct:+.1f}%)")

    with c3:
        prev_fr = h['적립률'][-2] if len(h['적립률']) >= 2 else funding_ratio
        fr_delta = funding_ratio - prev_fr
        st.metric("적립비율", f"{funding_ratio:.1f}%",
                  delta=f"전년대비 {fr_delta:+.1f}%p",
                  help="사외적립자산 / 기말 DBO")

    with c4:
        prev_dbo_gr = h['DBO_증가율'][-2] if len(h['DBO_증가율']) >= 2 else dbo_growth_pct
        dbo_gr_delta = dbo_growth_pct - prev_dbo_gr
        st.metric("DBO 증가율", f"{dbo_growth_pct:.1f}%",
                  delta=f"전년대비 {dbo_gr_delta:+.1f}%p", delta_color="inverse")

    with c5:
        prev_ret = h['운용수익률'][-2] if len(h['운용수익률']) >= 2 else k['당기_운용수익률']
        ret_delta = k['당기_운용수익률'] - prev_ret
        st.metric("운용수익률", f"{k['당기_운용수익률']:.1f}%",
                  delta=f"전년대비 {ret_delta:+.1f}%p")

    with c6:
        gap = k['당기_운용수익률'] - dbo_growth_pct
        st.metric("수익률 - DBO증가율", f"{gap:+.1f}%p",
                  help="운용수익률이 DBO 증가율을 상회해야 기여금 없이 적립률 유지 가능")

    # ── 워터폴 차트 2개 ──
    st.markdown("---")
    col_dbo, col_asset = st.columns(2)

    with col_dbo:
        st.markdown("##### DBO 변동내역")
        d = BRIDGE_DBO
        labels = ['기초 DBO', '근무원가', '이자원가', '보험수리손익', '급여지급', '제도변경/기타', '기말 DBO']
        values = [d['기초_DBO'], d['근무원가'], d['이자원가'], d['보험수리손익'],
                  d['급여지급'], d['제도변경_기타'], d['기말_DBO']]
        measures = ['absolute', 'relative', 'relative', 'relative', 'relative', 'relative', 'total']

        fig_dbo = go.Figure(go.Waterfall(
            name="DBO", orientation="v",
            x=labels, y=values, measure=measures,
            connector_line_color='#888',
            increasing_marker_color='#EF553B',
            decreasing_marker_color='#636EFA',
            totals_marker_color='#AB63FA',
            text=[f"{v:+,.0f}억" if m not in ('absolute', 'total') else f"{v:,.0f}억"
                  for v, m in zip(values, measures)],
            textposition='outside'
        ))
        all_cum = [values[0]]
        for v, m in zip(values[1:], measures[1:]):
            all_cum.append(all_cum[-1] + v if m == 'relative' else v)
        fig_dbo.update_layout(height=400, margin=dict(t=10, b=30),
                               yaxis_title='금액 (억원)',
                               yaxis_range=[min(all_cum) * 0.92, max(all_cum) * 1.05])
        st.plotly_chart(fig_dbo, use_container_width=True)

    with col_asset:
        st.markdown("##### 사외적립자산 변동내역")
        a = BRIDGE_ASSET
        labels = ['기초 자산', '기여금', '운용수익', '급여지급', '기타', '기말 자산']
        values = [a['기초_자산'], a['사용자_기여금'], a['운용수익'],
                  a['급여지급'], a['사업결합_이전_기타'], a['기말_자산']]
        measures = ['absolute', 'relative', 'relative', 'relative', 'relative', 'total']

        fig_asset = go.Figure(go.Waterfall(
            name="자산", orientation="v",
            x=labels, y=values, measure=measures,
            connector_line_color='#888',
            increasing_marker_color='#00CC96',
            decreasing_marker_color='#EF553B',
            totals_marker_color='#636EFA',
            text=[f"{v:+,.0f}억" if m not in ('absolute', 'total') else f"{v:,.0f}억"
                  for v, m in zip(values, measures)],
            textposition='outside'
        ))
        all_cum_a = [values[0]]
        for v, m in zip(values[1:], measures[1:]):
            all_cum_a.append(all_cum_a[-1] + v if m == 'relative' else v)
        fig_asset.update_layout(height=400, margin=dict(t=10, b=30),
                                 yaxis_title='금액 (억원)',
                                 yaxis_range=[min(all_cum_a) * 0.92, max(all_cum_a) * 1.05])
        st.plotly_chart(fig_asset, use_container_width=True)

    # ── DBO 증가분 vs 운용수익 (5개년) + 5개년 추이 ──
    st.markdown("---")
    col_gap_chart, col_trend = st.columns(2)

    with col_gap_chart:
        st.markdown("##### DBO 증가분 vs 운용수익 (5개년)")
        years = h['연도']
        dbo_inc = h['DBO_증가분']
        op_inc = h['운용수익']
        dbo_gr = h['DBO_증가율']
        op_ret = h['운용수익률']

        fig_gap = go.Figure()
        fig_gap.add_trace(go.Bar(
            name='DBO 증가분', x=years, y=dbo_inc,
            marker_color='rgba(239,85,59,0.35)',
            text=[f"{v:,.0f}" for v in dbo_inc], textposition='outside'
        ))
        fig_gap.add_trace(go.Bar(
            name='운용수익', x=years, y=op_inc,
            marker_color='rgba(0,204,150,0.35)',
            text=[f"{v:,.0f}" for v in op_inc], textposition='outside'
        ))
        fig_gap.add_trace(go.Scatter(
            name='DBO 증가율', x=years, y=dbo_gr, yaxis='y2',
            line=dict(color='#EF553B', width=2.5),
            mode='lines+markers+text',
            text=[f"{v:.1f}%" for v in dbo_gr], textposition='top center',
            textfont=dict(size=12, color='#EF553B')
        ))
        fig_gap.add_trace(go.Scatter(
            name='운용수익률', x=years, y=op_ret, yaxis='y2',
            line=dict(color='#00CC96', width=2.5),
            mode='lines+markers+text',
            text=[f"{v:.1f}%" for v in op_ret], textposition='bottom center',
            textfont=dict(size=12, color='#00CC96')
        ))
        fig_gap.update_layout(
            barmode='group', height=380,
            yaxis=dict(title='금액 (억원)'),
            yaxis2=dict(title='수익률 (%)', overlaying='y', side='right',
                        range=[min(min(dbo_gr), min(op_ret)) - 4, max(max(dbo_gr), max(op_ret)) + 4]),
            legend=dict(orientation='h', y=1.08, font=dict(size=10)),
            margin=dict(t=10, b=20),
            xaxis=dict(showgrid=False, showline=False, ticks=''),
        )
        st.plotly_chart(fig_gap, use_container_width=True)

    with col_trend:
        st.markdown("##### 최근 5개년 DBO / 사외적립자산 추이")
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Bar(name='DBO', x=h['연도'], y=h['DBO'],
                                    marker_color='rgba(239,85,59,0.35)'))
        fig_trend.add_trace(go.Bar(name='사외적립자산', x=h['연도'], y=h['사외적립자산'],
                                    marker_color='rgba(99,110,250,0.35)'))
        fig_trend.add_trace(go.Scatter(
            name='적립률', x=h['연도'], y=h['적립률'], yaxis='y2',
            line=dict(color='#00CC96', width=2.5), mode='lines+markers+text',
            text=[f"{r:.1f}%" for r in h['적립률']], textposition='top center',
            textfont=dict(size=12, color='#00CC96')
        ))
        fig_trend.update_layout(
            barmode='group', height=380,
            yaxis=dict(title='금액 (억원)'),
            yaxis2=dict(title='적립률 (%)', overlaying='y', side='right', range=[70, 110]),
            legend=dict(orientation='h', y=1.08, font=dict(size=10)),
            margin=dict(t=10, b=20),
            xaxis=dict(showgrid=False, showline=False, ticks=''),
        )
        st.plotly_chart(fig_trend, use_container_width=True)

    # (진단 요약 삭제됨)
