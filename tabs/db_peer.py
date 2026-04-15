# -*- coding: utf-8 -*-
"""Peer 비교 — DART 공시 기반 동종업계 비교 분석 (MOCKUP)."""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

from modules.mock_db_pension_data import PEER_COMPANIES, PEER_KPI


def render(ctx):
    st.markdown("#### Peer 비교")
    st.caption("MOCKUP 데이터 — DART 연동 시 자동 교체")

    df = pd.DataFrame(PEER_COMPANIES)
    company = df[df['회사명'] == '당사'].iloc[0]

    # ── 필터 (UI만, mockup 필터링) ──
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    with col_f1:
        sel_industry = st.selectbox("업종", ['전체'] + sorted(df['업종'].unique().tolist()), key="peer_industry")
    with col_f2:
        sel_size = st.selectbox("규모", ['전체'] + sorted(df['규모'].unique().tolist()), key="peer_size")
    with col_f3:
        st.selectbox("회계기준", ['K-IFRS'], key="peer_acct")
    with col_f4:
        st.selectbox("연결/별도", ['연결', '별도'], key="peer_scope")

    # 필터 적용
    filtered = df.copy()
    if sel_industry != '전체':
        filtered = filtered[(filtered['업종'] == sel_industry) | (filtered['회사명'] == '당사')]
    if sel_size != '전체':
        filtered = filtered[(filtered['규모'] == sel_size) | (filtered['회사명'] == '당사')]

    peers = filtered[filtered['회사명'] != '당사']

    # ── 상단 KPI 카드 ──
    st.markdown("---")
    peer_avg_fr = peers['적립률'].mean() if not peers.empty else 0
    peer_avg_ret = peers['수익률'].mean() if not peers.empty else 0
    peer_avg_dbo = peers['DBO성장률'].mean() if not peers.empty else 0
    peer_avg_gic = peers['원리금보장비중'].mean() if not peers.empty else 0
    peer_avg_bond = peers['채권비중'].mean() if not peers.empty else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        d = company['적립률'] - peer_avg_fr
        st.metric("적립률", f"{company['적립률']:.1f}%",
                  delta=f"Peer 대비 {d:+.1f}%p")
    with c2:
        d = company['수익률'] - peer_avg_ret
        st.metric("운용수익률", f"{company['수익률']:.1f}%",
                  delta=f"Peer 대비 {d:+.1f}%p")
    with c3:
        d = company['DBO성장률'] - peer_avg_dbo
        st.metric("DBO 성장률", f"{company['DBO성장률']:.1f}%",
                  delta=f"Peer 대비 {d:+.1f}%p", delta_color="inverse")
    with c4:
        d = company['원리금보장비중'] - peer_avg_gic
        st.metric("원리금보장 비중", f"{company['원리금보장비중']:.1f}%",
                  delta=f"Peer 대비 {d:+.1f}%p", delta_color="inverse")
    with c5:
        d = company['채권비중'] - peer_avg_bond
        st.metric("채권 비중", f"{company['채권비중']:.1f}%",
                  delta=f"Peer 대비 {d:+.1f}%p")

    # ── 적립률 분포 + 당사 위치 ──
    st.markdown("---")
    col_box, col_scatter = st.columns(2)

    with col_box:
        st.markdown("##### 적립률 분포")
        all_fr = filtered['적립률'].tolist()
        sorted_fr = sorted(all_fr)
        my_rank = sum(1 for x in sorted_fr if x <= company['적립률'])
        pctile = my_rank / len(sorted_fr) * 100

        fig_box = go.Figure()
        fig_box.add_trace(go.Box(y=peers['적립률'], name='Peer', marker_color='#636EFA',
                                  boxpoints='all', jitter=0.3))
        fig_box.add_trace(go.Scatter(
            x=['Peer'], y=[company['적립률']], mode='markers',
            marker=dict(color='#EF553B', size=15, symbol='star'),
            name='당사'
        ))
        fig_box.update_layout(height=350, margin=dict(t=10, b=20), yaxis_title='적립률 (%)',
                               showlegend=True, legend=dict(orientation='h', y=1.05))
        st.plotly_chart(fig_box, use_container_width=True)
        st.caption(f"당사 적립률 **상위 {100-pctile:.0f}%** (Peer {len(peers)}개사 기준)")

    with col_scatter:
        st.markdown("##### 수익률 vs DBO 성장률")
        fig_sc = go.Figure()
        fig_sc.add_trace(go.Scatter(
            x=peers['수익률'], y=peers['DBO성장률'],
            mode='markers+text', text=peers['회사명'],
            textposition='top center', textfont_size=9,
            marker=dict(color='#636EFA', size=10, opacity=0.7),
            name='Peer'
        ))
        fig_sc.add_trace(go.Scatter(
            x=[company['수익률']], y=[company['DBO성장률']],
            mode='markers+text', text=['당사'],
            textposition='top center', textfont_size=11,
            marker=dict(color='#EF553B', size=16, symbol='star'),
            name='당사'
        ))
        fig_sc.update_layout(height=350, margin=dict(t=10, b=20),
                              xaxis_title='운용수익률 (%)', yaxis_title='DBO 성장률 (%)',
                              showlegend=True, legend=dict(orientation='h', y=1.05))
        st.plotly_chart(fig_sc, use_container_width=True)

    # ── 자산구성 비교 ──
    st.markdown("---")
    st.markdown("##### 자산구성 비교")
    asset_cols = ['원리금보장비중', '채권비중', '주식비중', '대체비중']
    asset_labels = ['원리금보장', '채권', '주식', '대체투자']
    colors = ['#B6E880', '#00CC96', '#636EFA', '#AB63FA']

    # 당사 + peer 평균
    comp_data = pd.DataFrame({
        '구분': ['당사', 'Peer 평균'],
        '원리금보장': [company['원리금보장비중'], peer_avg_gic],
        '채권': [company['채권비중'], peer_avg_bond],
        '주식': [company['주식비중'], peers['주식비중'].mean() if not peers.empty else 0],
        '대체투자': [company['대체비중'], peers['대체비중'].mean() if not peers.empty else 0],
    })

    fig_stack = go.Figure()
    for i, label in enumerate(asset_labels):
        fig_stack.add_trace(go.Bar(
            name=label, x=comp_data['구분'], y=comp_data[label],
            marker_color=colors[i],
            text=[f"{v:.0f}%" for v in comp_data[label]], textposition='inside'
        ))
    fig_stack.update_layout(barmode='stack', height=300, margin=dict(t=10, b=20),
                             yaxis_title='비중 (%)', legend=dict(orientation='h', y=1.05))
    st.plotly_chart(fig_stack, use_container_width=True)

    # ── Peer Ranking Table ──
    st.markdown("---")
    st.markdown("##### Peer Ranking")

    rank_df = filtered[['회사명', '업종', '규모', '적립률', '수익률', 'DBO성장률', '원리금보장비중', '채권비중']].copy()
    rank_df = rank_df.sort_values('적립률', ascending=False).reset_index(drop=True)
    rank_df.index = rank_df.index + 1
    rank_df.index.name = '순위'

    # Percentile 계산
    all_fr_sorted = sorted(filtered['적립률'].tolist())
    all_ret_sorted = sorted(filtered['수익률'].tolist())
    my_fr_pctile = sum(1 for x in all_fr_sorted if x <= company['적립률']) / len(all_fr_sorted) * 100
    my_ret_pctile = sum(1 for x in all_ret_sorted if x <= company['수익률']) / len(all_ret_sorted) * 100
    my_bond_pctile = sum(1 for x in sorted(filtered['채권비중'].tolist()) if x <= company['채권비중']) / len(filtered) * 100

    col_pct1, col_pct2, col_pct3 = st.columns(3)
    with col_pct1:
        st.info(f"적립률 **상위 {100-my_fr_pctile:.0f}%**")
    with col_pct2:
        st.info(f"수익률 **상위 {100-my_ret_pctile:.0f}%**")
    with col_pct3:
        st.info(f"채권비중 **상위 {100-my_bond_pctile:.0f}%**")

    def _highlight_company(row):
        if row['회사명'] == '당사':
            return ['background-color: #FFF3E0'] * len(row)
        return [''] * len(row)

    st.dataframe(rank_df.style.apply(_highlight_company, axis=1),
                 use_container_width=True, height=max(200, 35 * len(rank_df) + 40))
