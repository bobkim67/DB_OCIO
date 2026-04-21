# -*- coding: utf-8 -*-
"""DB ALM 적합성 — DB형 퇴직연금 자산부채매칭 분석 (MOCKUP)."""

import streamlit as st
import plotly.graph_objects as go

from modules.mock_db_pension_data import (
    ALM_KPI, ALM_SENSITIVITY, ALM_CASHFLOW_BUCKETS, ALM_TARGET_RETURN,
)


def render(ctx):
    st.markdown("#### DB ALM 적합성")
    st.caption("MOCKUP 데이터 — 실데이터 연동 시 자동 교체")

    # ── 상단 KPI 카드 ──
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("적립률", f"{ALM_KPI['적립률']:.1f}%")
    with c2:
        st.metric("자산 듀레이션", f"{ALM_KPI['자산_듀레이션']:.1f}년")
    with c3:
        st.metric("부채 듀레이션", f"{ALM_KPI['부채_듀레이션']:.1f}년")
    with c4:
        gap = ALM_KPI['듀레이션_갭']
        st.metric("듀레이션 갭", f"{gap:+.1f}년")
    with c5:
        st.metric("헤지율", f"{ALM_KPI['금리민감도_헤지율']:.0f}%")
    with c6:
        req = ALM_KPI['필요수익률']
        cur = ALM_KPI['현재_기대수익률']
        color = "🟢" if cur >= req else "🔴"
        st.metric("필요수익률", f"{req:.1f}%")
        st.caption(f"기대수익률 {cur:.1f}% {color}")

    # ── 필요수익률 vs 기대수익률 강조 ──
    st.markdown("---")
    col_target, col_gauge = st.columns([3, 2])

    with col_target:
        st.markdown("##### 목표수익률 산출 (기여금 없이 자연증가분 충당)")
        t = ALM_TARGET_RETURN
        st.markdown(f"""
| 항목 | 금액(억원) |
|------|-----------|
| 기초 사외적립자산 | {t['기초_사외적립자산']:,.0f} |
| 근무원가 | {t['근무원가']:,.0f} |
| 이자원가 | {t['이자원가']:,.0f} |
| 기초율 가정 보정 | {t['기초율가정보정']:,.0f} |
| **자연증가 필요액** | **{t['자연증가_필요액']:,.0f}** |
| **필요수익률** | **{t['필요수익률']:.1f}%** |
""")
        st.caption("급여지급: {:,.0f}억원 / 기여금: {:,.0f}억원 (별도)".format(
            t['급여지급'], t['기여금']))
        st.info("단순화한 내부 관리지표 예시이며, 실데이터 연동 시 산식 조정 가능합니다.")

    with col_gauge:
        req = ALM_KPI['필요수익률']
        cur = ALM_KPI['현재_기대수익률']
        sufficient = cur >= req
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=cur,
            delta={'reference': req, 'relative': False, 'valueformat': '.1f',
                   'increasing': {'color': '#00CC96'}, 'decreasing': {'color': '#EF553B'}},
            title={'text': '기대수익률 vs 필요수익률'},
            number={'suffix': '%'},
            gauge={
                'axis': {'range': [0, 10]},
                'bar': {'color': '#00CC96' if sufficient else '#EF553B'},
                'threshold': {'line': {'color': '#333', 'width': 3}, 'thickness': 0.8, 'value': req},
                'steps': [
                    {'range': [0, req], 'color': '#FFE0E0'},
                    {'range': [req, 10], 'color': '#E0FFE0'},
                ],
            }
        ))
        fig_gauge.update_layout(height=250, margin=dict(t=40, b=10))
        st.plotly_chart(fig_gauge, use_container_width=True)

        if sufficient:
            st.success(f"현재 기대수익률({cur:.1f}%)이 필요수익률({req:.1f}%)을 충족합니다.")
        else:
            st.error(f"현재 기대수익률({cur:.1f}%)이 필요수익률({req:.1f}%)에 {req-cur:.1f}%p 부족합니다.")

    # ── 듀레이션 비교 + 금리 충격 ──
    st.markdown("---")
    col_dur, col_sens = st.columns(2)

    with col_dur:
        st.markdown("##### 자산 vs 부채 듀레이션")
        fig_dur = go.Figure()
        fig_dur.add_trace(go.Bar(
            x=['자산 듀레이션', '부채 듀레이션'],
            y=[ALM_KPI['자산_듀레이션'], ALM_KPI['부채_듀레이션']],
            marker_color=['#636EFA', '#EF553B'],
            text=[f"{ALM_KPI['자산_듀레이션']:.1f}년", f"{ALM_KPI['부채_듀레이션']:.1f}년"],
            textposition='outside'
        ))
        fig_dur.update_layout(height=300, margin=dict(t=10, b=20), yaxis_title='듀레이션 (년)')
        st.plotly_chart(fig_dur, use_container_width=True)

    with col_sens:
        st.markdown("##### 금리 충격 시 자산·부채 변화")
        scenarios = list(ALM_SENSITIVITY.keys())
        asset_chg = [ALM_SENSITIVITY[s][0] for s in scenarios]
        liab_chg = [ALM_SENSITIVITY[s][1] for s in scenarios]

        fig_sens = go.Figure()
        fig_sens.add_trace(go.Bar(name='자산 변화', x=scenarios, y=asset_chg, marker_color='#636EFA'))
        fig_sens.add_trace(go.Bar(name='부채 변화', x=scenarios, y=liab_chg, marker_color='#EF553B'))
        fig_sens.update_layout(barmode='group', height=300, margin=dict(t=10, b=20),
                                yaxis_title='변화율 (%)', legend=dict(orientation='h', y=1.05))
        st.plotly_chart(fig_sens, use_container_width=True)

    # ── Cash Flow Maturity Bucket ──
    st.markdown("---")
    col_cf, col_score = st.columns([3, 2])

    with col_cf:
        st.markdown("##### 예상 지급 Cash Flow (Maturity Bucket)")
        buckets = list(ALM_CASHFLOW_BUCKETS.keys())
        amounts = list(ALM_CASHFLOW_BUCKETS.values())
        fig_cf = go.Figure(go.Bar(
            x=buckets, y=amounts, marker_color='#AB63FA',
            text=[f"{a:,.0f}억" for a in amounts], textposition='outside'
        ))
        fig_cf.update_layout(height=300, margin=dict(t=10, b=20), yaxis_title='금액 (억원)')
        st.plotly_chart(fig_cf, use_container_width=True)

    with col_score:
        st.markdown("##### ALM 적합도 점수")
        # 간단한 점수: 헤지율 기반
        score = min(100, ALM_KPI['금리민감도_헤지율'] * 1.2)
        fig_score = go.Figure(go.Indicator(
            mode="gauge+number",
            value=score,
            title={'text': 'ALM 매칭 점수'},
            gauge={
                'axis': {'range': [0, 100]},
                'bar': {'color': '#636EFA'},
                'steps': [
                    {'range': [0, 40], 'color': '#FFE0E0'},
                    {'range': [40, 70], 'color': '#FFFDE0'},
                    {'range': [70, 100], 'color': '#E0FFE0'},
                ],
            }
        ))
        fig_score.update_layout(height=250, margin=dict(t=40, b=10))
        st.plotly_chart(fig_score, use_container_width=True)
        if score < 40:
            st.error("자산-부채 매칭이 매우 부족합니다.")
        elif score < 70:
            st.warning("자산-부채 매칭이 보통 수준입니다.")
        else:
            st.success("자산-부채 매칭이 양호합니다.")

    # ── 하단 요약 문구 ──
    st.markdown("---")
    st.markdown("##### 진단 요약")
    st.markdown(
        f"- 현재는 부채 듀레이션({ALM_KPI['부채_듀레이션']:.1f}년) 대비 "
        f"자산 듀레이션({ALM_KPI['자산_듀레이션']:.1f}년)이 짧아 "
        f"**금리 하락 시 적립률 변동성이 확대**될 수 있습니다.\n"
        f"- 기여금 없이 자연증가분을 상쇄하려면 **연 {ALM_KPI['필요수익률']:.1f}% 수준의 운용수익**이 필요합니다.\n"
        f"- 금리민감도 헤지율은 {ALM_KPI['금리민감도_헤지율']:.0f}%로, "
        f"금리 -100bp 충격 시 부채가 약 {abs(ALM_SENSITIVITY['-100bp'][1]):.1f}% 증가하는 반면 "
        f"자산은 {ALM_SENSITIVITY['-100bp'][0]:+.1f}%에 그쳐 **적립률 하락 리스크**가 존재합니다."
    )
