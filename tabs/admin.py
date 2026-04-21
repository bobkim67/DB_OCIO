# -*- coding: utf-8 -*-
"""Tab 6: Admin — 전체 펀드 운용 현황 (admin 전용).

운용보고 워크플로우는 별도 탭으로 분리:
  - Admin(운용보고_매크로): tabs/admin_macro.py
  - Admin(운용보고_펀드): tabs/admin_fund.py
"""

from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# ══════════════════════════════════════════
# 렌더링
# ══════════════════════════════════════════

def render(ctx):
    """Admin 탭 렌더링."""
    FUND_META = ctx['FUND_META']
    FUND_LIST = ctx['FUND_LIST']
    DB_CONNECTED = ctx['DB_CONNECTED']
    cached_load_fund_summary = ctx['cache']['load_fund_summary']

    # ── 섹션 1: 전체 펀드 운용 현황 ──
    st.markdown("#### 전체 펀드 운용 현황")

    _tab6_db = False
    if DB_CONNECTED:
        try:
            _summary_df = cached_load_fund_summary(FUND_LIST)
            if not _summary_df.empty:
                _tab6_db = True
        except Exception as _e:
            st.toast(f"Admin DB 오류, 목업 사용: {_e}", icon="⚠️")

    if _tab6_db:
        st.caption(f"DB 실데이터 | 기준일: {_summary_df['기준일자'].max().strftime('%Y-%m-%d')}")
        all_funds = pd.DataFrame()
        all_funds['펀드코드'] = _summary_df['FUND_CD']
        all_funds['펀드명'] = _summary_df['FUND_CD'].map(
            lambda x: FUND_META.get(x, {}).get('short', x))
        all_funds['AUM(억)'] = _summary_df['AUM_억'].round(1)
        all_funds['기준가'] = _summary_df['MOD_STPR'].round(2)
        if 'DD1_ERN_RT' in _summary_df.columns:
            _ern = pd.to_numeric(_summary_df['DD1_ERN_RT'].apply(
                lambda x: float(x) if x is not None else None), errors='coerce')
            all_funds['전일수익률(%)'] = (_ern * 100).round(4)
        else:
            all_funds['전일수익률(%)'] = 0.0
        all_funds['그룹'] = _summary_df['FUND_CD'].map(
            lambda x: FUND_META.get(x, {}).get('group', '기타'))
        all_funds['MP'] = _summary_df['FUND_CD'].map(
            lambda x: 'O' if FUND_META.get(x, {}).get('has_mp', False) else 'X')
        all_funds['듀레이션'] = _summary_df['FUND_DUR'].round(2) if 'FUND_DUR' in _summary_df.columns else '-'
    else:
        all_funds = pd.DataFrame([
            {'펀드코드': k, '펀드명': v['short'], 'AUM(억)': v['aum'],
             '그룹': v['group'],
             'YTD': f"{np.random.uniform(-1, 5):.2f}%",
             'BM대비': f"{np.random.uniform(-0.5, 1.5):+.2f}%p",
             'MP': 'O' if v['has_mp'] else 'X',
             'MP Gap': np.random.choice(['적정', 'Over', 'Under'], p=[0.6, 0.2, 0.2]) if v['has_mp'] else '-'}
            for k, v in FUND_META.items()
        ])

    all_funds = all_funds.sort_values('AUM(억)', ascending=False)
    st.dataframe(all_funds, hide_index=True, width="stretch", height=500)

    st.markdown("---")
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        st.markdown("#### AUM 분포")
        fig_aum = px.treemap(all_funds, path=['그룹', '펀드명'], values='AUM(억)',
                              color='AUM(억)', color_continuous_scale='Blues')
        fig_aum.update_layout(height=400, margin=dict(t=30, b=10))
        st.plotly_chart(fig_aum, width="stretch")
    with col_a2:
        st.markdown("#### 그룹별 AUM")
        group_aum = all_funds.groupby('그룹')['AUM(억)'].sum().sort_values(ascending=True)
        fig_group = go.Figure(go.Bar(
            x=group_aum.values, y=group_aum.index,
            orientation='h', marker_color='#636EFA',
            text=[f"{v:,.0f}억" for v in group_aum.values], textposition='outside'))
        fig_group.update_layout(height=400, margin=dict(t=30, l=100), xaxis_title='AUM (억원)')
        st.plotly_chart(fig_group, width="stretch")

    # (운용보고 워크플로우는 Admin(운용보고_매크로), Admin(운용보고_펀드) 탭으로 이동)
