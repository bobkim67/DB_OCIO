# -*- coding: utf-8 -*-
"""공통 차트 헬퍼 함수"""
import numpy as np
import plotly.graph_objects as go


def hex_to_rgba(hex_color, alpha=0.08):
    """hex 색상을 rgba 문자열로 변환"""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f'rgba({r},{g},{b},{alpha})'


def make_sparkline(data, color='#636EFA', height=60, spark_dates=None, fmt=',.2f', suffix=''):
    """미니 스파크라인 차트 생성 (카드 내장용, x축 날짜 표기)"""
    if 'rgb' in color:
        fc = color.replace(')', f',0.08)').replace('rgb', 'rgba')
    else:
        fc = hex_to_rgba(color, 0.08)
    x_vals = spark_dates if spark_dates is not None else list(range(len(data)))
    fig = go.Figure(go.Scatter(
        x=x_vals, y=data, mode='lines', line=dict(color=color, width=1.5),
        fill='tozeroy', fillcolor=fc,
        hovertemplate=f'%{{y:{fmt}}}{suffix}<extra></extra>'
    ))
    show_xaxis = spark_dates is not None
    fig.update_layout(
        height=height, margin=dict(t=0, b=18 if show_xaxis else 0, l=0, r=0),
        xaxis=dict(visible=show_xaxis, showgrid=False, tickformat='%m/%d',
                   nticks=4, tickfont=dict(size=9, color='#aaa')),
        yaxis=dict(visible=False,
                   range=[min(data) - (max(data)-min(data))*0.05,
                          max(data) + (max(data)-min(data))*0.05] if max(data) != min(data) else None),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        modebar=dict(remove=['zoom', 'pan', 'select', 'lasso', 'zoomIn', 'zoomOut',
                             'autoScale', 'resetScale', 'toImage']),
    )
    return fig


def make_nav(start=1000, mu=0.0003, sigma=0.005, n=500):
    """mockup NAV 생성"""
    returns = np.random.normal(mu, sigma, n)
    nav = start * np.cumprod(1 + returns)
    return nav


def make_bm_nav(n=500):
    return make_nav(start=1000, mu=0.00025, sigma=0.004, n=n)


def calc_sharpe(returns_arr, rf_annual=0.03, periods_per_year=252):
    if len(returns_arr) < 2: return np.nan
    ann_ret = np.mean(returns_arr) * periods_per_year
    ann_vol = np.std(returns_arr, ddof=1) * np.sqrt(periods_per_year)
    return (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else np.nan
