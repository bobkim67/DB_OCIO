# === DB OCIO Webview -- UI Prototype v3 ===
# 14개 항목 UI 개선 반영
# 실행: streamlit run prototype.py

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import io
import sys, os

# modules/ 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.funds import FUND_BM, FUND_LIST, FUND_MP_MAPPING, FUND_MP_DIRECT
from modules.data_loader import (
    load_fund_nav, load_fund_nav_with_aum, load_fund_holdings_classified,
    load_fund_holdings_lookthrough,
    load_fund_holdings_history, load_fund_summary, load_scip_bm_prices,
    load_composite_bm_prices, load_mp_weights_8class,
    load_all_fund_data, parse_data_blob,
)

st.set_page_config(
    page_title="DB OCIO 운용 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================================
# DB 접속 확인 + 캐싱 레이어
# ============================================================

@st.cache_data(ttl=600)
def cached_load_fund_nav(fund_code, start_date=None):
    return load_fund_nav_with_aum(fund_code, start_date)

@st.cache_data(ttl=600)
def cached_load_bm_prices(dataset_id, dataseries_id, start_date=None, currency=None):
    return load_scip_bm_prices(dataset_id, dataseries_id, start_date, currency)

@st.cache_data(ttl=600)
def cached_load_holdings(fund_code, date=None):
    return load_fund_holdings_classified(fund_code, date)

@st.cache_data(ttl=600)
def cached_load_holdings_lookthrough(fund_code, date=None):
    return load_fund_holdings_lookthrough(fund_code, date)

@st.cache_data(ttl=600)
def cached_load_holdings_history(fund_code, start_date=None):
    return load_fund_holdings_history(fund_code, start_date)

@st.cache_data(ttl=600)
def cached_load_fund_summary(fund_codes):
    return load_fund_summary(fund_codes)

@st.cache_data(ttl=600)
def cached_load_all_fund_data(fund_codes_tuple, start_date=None):
    return load_all_fund_data(list(fund_codes_tuple), start_date)

@st.cache_data(ttl=600)
def cached_load_composite_bm(components_json, start_date=None):
    """복합 BM 캐시 래퍼. components_json: JSON 문자열 (hashable)"""
    import json
    components = json.loads(components_json)
    return load_composite_bm_prices(components, start_date)

@st.cache_data(ttl=600)
def cached_load_mp_weights_8class(fund_desc, reference_date=None, cycle_phase=1):
    return load_mp_weights_8class(fund_desc, reference_date, cycle_phase)

# DB 접속 테스트
try:
    from modules.data_loader import get_connection
    _test_conn = get_connection('dt')
    _test_conn.close()
    DB_CONNECTED = True
except Exception:
    DB_CONNECTED = False

# ============================================================
# 펀드 메타 & 샘플 데이터
# ============================================================

FUND_META = {
    '07J34': {'name': 'MySuper 성장형', 'short': 'MySuper성장', 'aum': 2370.8, 'group': 'MySuper', 'has_mp': True},
    '07J48': {'name': 'MySuper 수익추구', 'short': 'MySuper수익', 'aum': 2261.1, 'group': 'MySuper', 'has_mp': True},
    '07G04': {'name': 'OCIO알아서(채권혼합)(모)', 'short': 'OCIO채권혼합', 'aum': 1749.6, 'group': 'OCIO', 'has_mp': True},
    '07J49': {'name': 'MySuper 인컴추구', 'short': 'MySuper인컴', 'aum': 1548.8, 'group': 'MySuper', 'has_mp': True},
    '07J41': {'name': 'MySuper 안정형', 'short': 'MySuper안정', 'aum': 1358.0, 'group': 'MySuper', 'has_mp': True},
    '07G03': {'name': '수익추구 모펀드', 'short': '수익추구모', 'aum': 888.2, 'group': '모펀드', 'has_mp': True},
    '07G02': {'name': '인컴추구 모펀드', 'short': '인컴추구모', 'aum': 883.4, 'group': '모펀드', 'has_mp': True},
    '08P22': {'name': 'OCIO알아서 프라임', 'short': 'OCIO프라임', 'aum': 815.9, 'group': 'OCIO', 'has_mp': True},
    '08K88': {'name': 'OCIO알아서 성장형(사모)', 'short': 'OCIO성장사모', 'aum': 542.3, 'group': 'OCIO', 'has_mp': True},
    '07P70': {'name': '골든그로스', 'short': '골든그로스', 'aum': 518.5, 'group': '기타', 'has_mp': False},
    '08N33': {'name': 'OCIO알아서 베이직', 'short': 'OCIO베이직', 'aum': 241.1, 'group': 'OCIO', 'has_mp': True},
    '4JM12': {'name': '동부글로벌 Active', 'short': '동부Active', 'aum': 234.6, 'group': '외부위탁', 'has_mp': False},
    '2JM23': {'name': '오렌지라이프 자산배분B', 'short': '오렌지B', 'aum': 194.7, 'group': '외부위탁', 'has_mp': False},
    '08N81': {'name': 'OCIO알아서 액티브', 'short': 'OCIO액티브', 'aum': 188.7, 'group': 'OCIO', 'has_mp': True},
    '07W15': {'name': '디딤CPI+', 'short': '디딤CPI+', 'aum': 90.3, 'group': '기타', 'has_mp': False},
    '1JM96': {'name': 'ABL글로벌배당인컴', 'short': 'ABL배당', 'aum': 46.1, 'group': '외부위탁', 'has_mp': False},
    '06X08': {'name': 'OCIO RSP(사모)', 'short': 'OCIO_RSP', 'aum': 40.6, 'group': 'OCIO', 'has_mp': True},
    '07J27': {'name': 'OCIO알아서 인컴형', 'short': 'OCIO인컴', 'aum': 19.9, 'group': 'OCIO', 'has_mp': True},
    '07J20': {'name': 'OCIO알아서 수익형', 'short': 'OCIO수익', 'aum': 8.5, 'group': 'OCIO', 'has_mp': True},
    '1JM98': {'name': 'ABL글로벌배당(달러)', 'short': 'ABL달러', 'aum': 1.9, 'group': '외부위탁', 'has_mp': False},
    '09L94': {'name': 'MySuper 인컴추구형(모)', 'short': 'MySuper인컴모', 'aum': 1.3, 'group': 'MySuper', 'has_mp': True},
}

FUND_GROUPS = {
    '전체': list(FUND_META.keys()),
    'OCIO 알아서': ['06X08', '07G04', '07J20', '07J27', '08K88', '08N33', '08N81', '08P22'],
    'MySuper': ['07J34', '07J41', '07J48', '07J49', '09L94'],
    '모펀드': ['07G02', '07G03'],
    '외부위탁': ['1JM96', '1JM98', '2JM23', '4JM12'],
    '기타': ['07P70', '07W15'],
}

ASSET_CLASSES = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', 'FX', '모펀드', '유동성']
ASSET_COLORS = {
    '국내주식': '#EF553B', '해외주식': '#636EFA', '국내채권': '#00CC96',
    '해외채권': '#AB63FA', '대체투자': '#FFA15A', 'FX': '#19D3F3',
    '모펀드': '#FF6692', '유동성': '#B6E880',
}
# 자산군 정렬 순서 (테이블/차트용)
ASSET_CLASS_ORDER = {ac: i for i, ac in enumerate(ASSET_CLASSES)}

# 자산군별 관련 시장지표 매핑 (운용보고 탭 필터용, 대분류-중분류 기준)
ASSET_TO_MARKET_INDICATORS = {
    '국내주식': [('주식', '국내')],
    '해외주식': [('주식', '미국'), ('주식', '글로벌'), ('주식', '신흥시장'), ('변동성', '주식'), ('변동성', '채권')],
    '국내채권': [('채권', '국내금리'), ('채권', '기준금리')],
    '해외채권': [('채권', '미국금리'), ('채권', '기준금리'), ('채권', '크레딧')],
    '대체투자': [('원자재', '에너지'), ('원자재', '귀금속')],
    'FX':       [('FX', '주요환율')],
    '모펀드':   [],
    '유동성':   [('채권', '기준금리')],
}
ALWAYS_SHOW_INDICATORS = [('FX', '주요환율'), ('경제지표', '물가')]

# 샘플 종목 데이터 (자산군별 + 종목별) — 기간수익률 추가 (#4)
SAMPLE_HOLDINGS_DETAIL = pd.DataFrame({
    '자산군': ['국내주식','국내주식','국내주식','해외주식','해외주식','해외주식','해외주식',
             '국내채권','국내채권','국내채권','해외채권','해외채권','대체투자','대체투자','유동성'],
    '종목명': ['KODEX 200', 'TIGER KOSPI', 'Samsung SDI', 'SPY', 'QQQ', 'VWO', 'iShares MSCI ACWI',
             '국고03750-2603', '통안02-260', 'KB RISE 30Y국채', 'iShares US AGG', 'PIMCO Income',
             '맥쿼리인프라', 'JR Global REIT', 'MMF'],
    '비중(%)': [10.2, 8.5, 6.6, 12.3, 10.1, 4.7, 3.0, 12.5, 10.0, 5.8, 5.2, 3.0, 4.5, 2.0, 1.6],
    '평가금액(억)': [241.9, 201.6, 156.5, 291.7, 239.5, 111.5, 71.1, 296.4, 237.1, 137.5, 123.3, 71.1, 106.7, 47.4, 37.9],
    '1D(%)': [0.32, 0.28, -0.15, 0.45, 0.68, -0.22, 0.31, 0.05, 0.03, 0.08, 0.06, 0.04, 0.12, 0.09, 0.01],
    '1W(%)': [1.05, 0.82, -0.42, 1.52, 2.10, -0.68, 1.12, 0.15, 0.10, 0.25, 0.18, 0.12, 0.45, 0.30, 0.05],
    '1M(%)': [2.3, 1.8, -0.5, 5.1, 7.2, -1.3, 3.8, 0.8, 0.5, 1.1, 1.2, 0.9, 3.4, 2.1, 0.3],
    'YTD(%)': [3.5, 2.8, -1.2, 6.8, 9.5, -0.8, 5.2, 1.0, 0.6, 1.5, 1.5, 1.1, 4.2, 2.8, 0.4],
})

np.random.seed(42)
dates = pd.bdate_range('2024-01-02', '2026-02-11', freq='B')

def make_nav(start=1000, mu=0.0003, sigma=0.005, n=None):
    if n is None: n = len(dates)
    returns = np.random.normal(mu, sigma, n)
    nav = start * np.cumprod(1 + returns)
    return nav

def make_bm_nav():
    return make_nav(start=1000, mu=0.00025, sigma=0.004)

def calc_sharpe(returns_arr, rf_annual=0.03, periods_per_year=252):
    if len(returns_arr) < 2: return np.nan
    ann_ret = np.mean(returns_arr) * periods_per_year
    ann_vol = np.std(returns_arr, ddof=1) * np.sqrt(periods_per_year)
    return (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else np.nan

def hex_to_rgba(hex_color, alpha=0.08):
    """hex 색상을 rgba 문자열로 변환"""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f'rgba({r},{g},{b},{alpha})'

def make_sparkline(data, color='#636EFA', height=60, spark_dates=None):
    """미니 스파크라인 차트 생성 (카드 내장용, x축 날짜 표기)"""
    if 'rgb' in color:
        fc = color.replace(')', f',0.08)').replace('rgb', 'rgba')
    else:
        fc = hex_to_rgba(color, 0.08)
    x_vals = spark_dates if spark_dates is not None else list(range(len(data)))
    fig = go.Figure(go.Scatter(
        x=x_vals, y=data, mode='lines', line=dict(color=color, width=1.5),
        fill='tozeroy', fillcolor=fc
    ))
    show_xaxis = spark_dates is not None
    fig.update_layout(
        height=height, margin=dict(t=0, b=18 if show_xaxis else 0, l=0, r=0),
        xaxis=dict(visible=show_xaxis, showgrid=False, tickformat='%m/%d',
                   nticks=4, tickfont=dict(size=9, color='#aaa')),
        yaxis=dict(visible=False),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
        showlegend=False
    )
    return fig


# ============================================================
# CSS
# ============================================================

st.markdown("""
<style>
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #667eea11, #764ba211);
        border: 1px solid #e0e0e0;
        border-radius: 12px;
        padding: 12px 16px;
    }
    div[data-testid="stMetric"] label { font-size: 0.85rem !important; color: #555 !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0 0; padding: 8px 20px; font-weight: 500; }
    thead th { background-color: #f8f9fa !important; font-weight: 600 !important; }
    section[data-testid="stSidebar"] { display: none; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 역할 선택 (admin / client 택1)
# ============================================================

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_role = None

if not st.session_state.logged_in:
    st.markdown("")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div style="text-align:center; padding: 60px 40px; background: linear-gradient(135deg, #667eea22, #764ba222);
                    border-radius: 20px; margin-top: 40px;">
            <h1 style="font-size: 2.5rem; margin-bottom: 10px;">DB OCIO 운용 대시보드</h1>
            <p style="font-size: 1.1rem; color: #666; margin-bottom: 10px;">
                DB형 퇴직연금 OCIO 운용 현황을 한눈에 확인하세요
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("")
        st.markdown("")

        btn1, btn2 = st.columns(2)

        with btn1:
            st.markdown("""
            <div style="text-align:center; padding: 24px; border: 2px solid #667eea;
                        border-radius: 12px; background: #667eea08; margin-bottom: 10px;">
                <h3 style="color: #667eea; margin-bottom: 5px;">Admin</h3>
                <p style="color: #888; font-size: 0.9rem;">전체 펀드 조회 및 관리</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Admin 으로 접속", use_container_width=True, type="primary"):
                st.session_state.logged_in = True
                st.session_state.user_role = "admin"
                st.session_state.fund_access = list(FUND_META.keys())
                st.rerun()

        with btn2:
            st.markdown("""
            <div style="text-align:center; padding: 24px; border: 2px solid #764ba2;
                        border-radius: 12px; background: #764ba208; margin-bottom: 10px;">
                <h3 style="color: #764ba2; margin-bottom: 5px;">Client</h3>
                <p style="color: #888; font-size: 0.9rem;">할당 펀드 조회</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Client 로 접속", use_container_width=True):
                st.session_state.logged_in = True
                st.session_state.user_role = "client"
                st.session_state.fund_access = ['07J34', '07J41', '07J48', '07J49', '09L94']
                st.rerun()

    st.stop()


# ============================================================
# 상단: 사용자 정보 + 펀드 선택
# ============================================================

role_label = "Admin" if st.session_state.user_role == "admin" else "Client"
accessible = st.session_state.get('fund_access', list(FUND_META.keys()))

top1, top2, top3, top4, top5 = st.columns([1.2, 1.3, 1.5, 3.5, 1])

with top1:
    group_options = [g for g in FUND_GROUPS if any(f in accessible for f in FUND_GROUPS[g])]
    selected_group = st.selectbox("펀드 그룹", group_options, index=0, label_visibility="collapsed")

with top2:
    group_funds = sorted([f for f in FUND_GROUPS[selected_group] if f in accessible])
    fund_options = {k: f"{k}  {FUND_META[k]['short']}" for k in group_funds}
    selected_fund = st.selectbox(
        "펀드 선택", options=list(fund_options.keys()),
        format_func=lambda x: fund_options[x], label_visibility="collapsed"
    )

# 모펀드 존재 여부 사전 확인 + look-through 토글
_has_mother_fund = False
lookthrough_on = False
if DB_CONNECTED:
    try:
        _check_hold = cached_load_holdings(selected_fund)
        if not _check_hold.empty:
            _has_mother_fund = (_check_hold['자산군'] == '모펀드').any()
    except Exception:
        pass

with top3:
    if _has_mother_fund:
        lookthrough_on = st.toggle("Look-through", value=False, key="lookthrough_toggle",
                                    help="모펀드를 하위 종목으로 전개")
    else:
        st.write("")  # 빈 공간

with top4:
    fund_info = FUND_META[selected_fund]
    st.markdown(
        f"**{fund_info['name']}** &nbsp; | &nbsp; "
        f"<span style='color:#888'>코드: {selected_fund} &nbsp;|&nbsp; "
        f"그룹: {fund_info['group']} &nbsp;|&nbsp; "
        f"MP: {'있음' if fund_info['has_mp'] else '미설정'}</span>",
        unsafe_allow_html=True
    )

with top5:
    tc1, tc2 = st.columns(2)
    with tc1:
        color = "#667eea" if st.session_state.user_role == "admin" else "#764ba2"
        st.markdown(f"<span style='color:{color}; font-weight:600'>{role_label}</span>", unsafe_allow_html=True)
    with tc2:
        if st.button("나가기", key="logout_btn"):
            st.session_state.logged_in = False
            st.rerun()

st.markdown("---")

# ============================================================
# 탭 구성
# ============================================================

tab_names = ["Overview", "편입종목 & MP Gap", "AP vs VP 분석", "성과분석(Brinson)", "매크로 지표", "운용보고"]
if st.session_state.user_role == "admin":
    tab_names.append("Admin")
tabs = st.tabs(tab_names)


# ============================================================
# Tab 1: Overview
# ============================================================

with tabs[0]:
    # --- DB 데이터 로드 (fallback: mockup) ---
    _tab0_db = False
    if DB_CONNECTED:
        try:
            _nav_df = cached_load_fund_nav(selected_fund, '20240101')
            if not _nav_df.empty and len(_nav_df) > 10:
                nav_data = _nav_df['MOD_STPR'].values
                _nav_dates = _nav_df['기준일자'].values
                _aum_series = _nav_df['AUM_억'].values

                # BM 로드 (복합 BM 지원, BM 미설정 펀드는 스킵)
                _bm_cfg = FUND_BM.get(selected_fund)
                _bm_df = pd.DataFrame()
                if _bm_cfg and 'components' in _bm_cfg:
                    import json as _json
                    _bm_df = cached_load_composite_bm(
                        _json.dumps(_bm_cfg['components']), '2024-01-01'
                    )
                elif _bm_cfg:
                    _bm_df = cached_load_bm_prices(
                        _bm_cfg['dataset_id'], _bm_cfg['dataseries_id'],
                        '2024-01-01', _bm_cfg.get('currency')
                    )
                if not _bm_df.empty and len(_bm_df) > 10:
                    # BM을 NAV 날짜에 맞춰 정렬
                    _bm_df = _bm_df.set_index('기준일자')
                    _nav_idx = pd.DatetimeIndex(_nav_dates)
                    _bm_aligned = _bm_df.reindex(_nav_idx, method='ffill')['value'].values
                    if np.isnan(_bm_aligned).sum() < len(_bm_aligned) * 0.5:
                        bm_data = _bm_aligned[~np.isnan(_bm_aligned)] if np.isnan(_bm_aligned).any() else _bm_aligned
                        # 길이 맞추기
                        _min_len = min(len(nav_data), len(bm_data))
                        nav_data = nav_data[-_min_len:]
                        bm_data = bm_data[-_min_len:]
                        _aum_series = _aum_series[-_min_len:]
                        _nav_dates = _nav_dates[-_min_len:]
                        dates_for_tab0 = pd.DatetimeIndex(_nav_dates)
                        _tab0_db = True
                    else:
                        raise ValueError("BM align failed")
                elif _bm_cfg is None:
                    raise ValueError("BM 미설정")
                else:
                    raise ValueError("BM 데이터 부족")
            else:
                raise ValueError("NAV empty")
        except Exception as _e:
            _tab0_db = False
            st.toast(f"Tab0 DB 오류, 목업 사용: {_e}", icon="⚠️")

    if not _tab0_db:
        nav_data = make_nav()
        bm_data = make_bm_nav()
        dates_for_tab0 = dates
        _aum_series = fund_info['aum'] + np.cumsum(np.random.normal(0, 2, len(dates)))

    daily_ret = np.diff(nav_data) / nav_data[:-1]
    daily_bm_ret = np.diff(bm_data) / bm_data[:-1]

    latest_nav = nav_data[-1]
    prev_nav = nav_data[-2]
    nav_change = latest_nav - prev_nav
    nav_change_pct = (nav_change / prev_nav) * 100
    si_return = (nav_data[-1] / nav_data[0] - 1) * 100
    _ytd_mask = dates_for_tab0 >= pd.Timestamp('2026-01-01')
    ytd_idx = len(dates_for_tab0) - _ytd_mask.sum()
    ytd_return = (nav_data[-1] / nav_data[max(ytd_idx, 0)] - 1) * 100 if ytd_idx < len(nav_data) else 0.0
    bm_si = (bm_data[-1] / bm_data[0] - 1) * 100
    bm_ytd = (bm_data[-1] / bm_data[max(ytd_idx, 0)] - 1) * 100 if ytd_idx < len(bm_data) else 0.0

    # --- 지표 카드 + 3개월 스파크라인 (카드 내장) ---
    c1, c2, c3, c4 = st.columns(4)
    spark_n = min(66, len(nav_data))  # ~3개월
    spark_dates = dates_for_tab0[-spark_n:]

    with c1:
        with st.container(border=True):
            st.metric("설정이후 수익률", f"{si_return:.2f}%", f"{si_return - bm_si:.2f}%p vs BM")
            spark_data = (nav_data[-spark_n:] / nav_data[-spark_n] - 1) * 100
            st.plotly_chart(make_sparkline(spark_data, '#636EFA', spark_dates=spark_dates),
                            use_container_width=True, key="spark1")

    with c2:
        with st.container(border=True):
            st.metric("YTD 수익률", f"{ytd_return:.2f}%", f"{ytd_return - bm_ytd:.2f}%p vs BM")
            _bm_spark_n = min(spark_n, len(bm_data))
            spark_data2 = (bm_data[-_bm_spark_n:] / bm_data[-_bm_spark_n] - 1) * 100
            st.plotly_chart(make_sparkline(spark_data2, '#EF553B', spark_dates=spark_dates[-_bm_spark_n:]),
                            use_container_width=True, key="spark2")

    with c3:
        with st.container(border=True):
            st.metric("기준가", f"{latest_nav:,.2f}",
                      f"{nav_change:+,.2f} ({nav_change_pct:+.2f}%)", delta_color="normal")
            st.plotly_chart(make_sparkline(nav_data[-spark_n:], '#00CC96', spark_dates=spark_dates),
                            use_container_width=True, key="spark3")

    with c4:
        with st.container(border=True):
            _aum_latest = _aum_series[-1] if len(_aum_series) > 0 else fund_info['aum']
            _aum_prev_month = _aum_series[-22] if len(_aum_series) > 22 else _aum_latest
            _aum_change = _aum_latest - _aum_prev_month
            st.metric("AUM", f"{_aum_latest:.0f}억원", f"전월 대비 {_aum_change:+.0f}억")
            aum_spark = _aum_series[-spark_n:] if len(_aum_series) >= spark_n else _aum_series
            st.plotly_chart(make_sparkline(aum_spark, '#AB63FA', spark_dates=spark_dates[-len(aum_spark):]),
                            use_container_width=True, key="spark4")

    if _tab0_db:
        st.caption("📡 실시간 DB 데이터")

    st.markdown("")

    # --- 기간별 성과 테이블: 1D, 1W 추가, SI → "설정 후" (#0) ---
    def get_period_return(data, n):
        if n >= len(data): return np.nan
        return (data[-1] / data[-(n+1)] - 1) * 100

    def get_period_sharpe(rets, n):
        if n >= len(rets): return np.nan
        return calc_sharpe(rets[-n:])

    periods = {
        '1D': 1, '1W': 5, '1M': 22, '3M': 66, '6M': 132,
        'YTD': max(1, len(dates_for_tab0) - ytd_idx), '1Y': 252, '설정 후': len(nav_data)-1
    }
    row_port = {p: f"{get_period_return(nav_data, n):.2f}%" for p, n in periods.items()}
    row_bm = {p: f"{get_period_return(bm_data, n):.2f}%" for p, n in periods.items()}
    row_excess = {}
    row_sharpe = {}
    for p, n in periods.items():
        pr = get_period_return(nav_data, n)
        br = get_period_return(bm_data, n)
        row_excess[p] = f"{pr - br:+.2f}%p"
        _sh = get_period_sharpe(daily_ret, min(n, len(daily_ret)))
        row_sharpe[p] = f"{_sh:.2f}" if not np.isnan(_sh) else ""

    perf_df = pd.DataFrame({
        '구분': ['포트폴리오', 'BM', '초과수익', 'Sharpe'],
        **{p: [row_port[p], row_bm[p], row_excess[p], row_sharpe[p]] for p in periods}
    })

    st.dataframe(perf_df, hide_index=True, use_container_width=True, height=180)

    st.markdown("")

    # --- 레이아웃 변경: 편입현황 (좌) + 누적수익률/DD (우) (#2) ---
    col_hold, col_chart = st.columns([2, 3])

    with col_hold:
        st.markdown("#### 최근 편입현황")

        # DB 보유종목 로드 (fallback: SAMPLE_HOLDINGS_DETAIL) — lookthrough_on 반영
        _holdings_db = False
        if DB_CONNECTED:
            try:
                _hold_df = cached_load_holdings_lookthrough(selected_fund) if lookthrough_on else cached_load_holdings(selected_fund)
                if not _hold_df.empty:
                    _hold_date = _hold_df['기준일자'].iloc[0].strftime('%Y-%m-%d') if '기준일자' in _hold_df.columns else '최근'
                    st.caption(f"{_hold_date} 기준 | {fund_info['short']}")
                    asset_weights = _hold_df.groupby('자산군')['비중(%)'].sum()
                    asset_weights = asset_weights.reindex(ASSET_CLASSES).fillna(0)
                    _holdings_db = True
                else:
                    raise ValueError("Holdings empty")
            except Exception as _e:
                st.toast(f"보유종목 DB 오류, 목업 사용: {_e}", icon="⚠️")

        if not _holdings_db:
            st.caption(f"2026-02-11 기준 | {fund_info['short']}")
            asset_weights = SAMPLE_HOLDINGS_DETAIL.groupby('자산군')['비중(%)'].sum()
            asset_weights = asset_weights.reindex(ASSET_CLASSES).fillna(0)

        # 자산군별 비중 도넛 — 호버에 평가금액(억) 표시
        if _holdings_db:
            _evl_by_class = _hold_df.groupby('자산군')['평가금액(억)'].sum().reindex(ASSET_CLASSES).fillna(0)
        else:
            _evl_by_class = SAMPLE_HOLDINGS_DETAIL.groupby('자산군')['평가금액(억)'].sum().reindex(ASSET_CLASSES).fillna(0)
        fig_donut = go.Figure(data=[go.Pie(
            labels=asset_weights.index, values=asset_weights.values,
            hole=0.50, textinfo='label+percent',
            marker_colors=[ASSET_COLORS.get(a, '#999') for a in asset_weights.index],
            textfont_size=11,
            customdata=_evl_by_class.values,
            hovertemplate='%{label}<br>비중: %{percent}<br>평가금액: %{customdata:,.1f}(억)<extra></extra>'
        )])
        fig_donut.update_layout(height=260, margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
        st.plotly_chart(fig_donut, use_container_width=True)

        # 전체 보유종목 테이블 — 자산군 순서 → 비중 내림차순
        st.markdown("#### 전체 보유종목")
        if _holdings_db:
            _h_display = _hold_df[['자산군', 'ITEM_NM', '비중(%)', '평가금액(억)']].copy()
            _h_display = _h_display.rename(columns={'ITEM_NM': '종목명'})
            _h_display['_sort'] = _h_display['자산군'].map(ASSET_CLASS_ORDER).fillna(99)
            _h_display = _h_display.sort_values(['_sort', '비중(%)'], ascending=[True, False]).drop(columns='_sort')
            st.dataframe(_h_display, hide_index=True, use_container_width=True, height=450)
        else:
            display_cols = ['자산군', '종목명', '비중(%)', '평가금액(억)', '1D(%)', '1W(%)', '1M(%)', 'YTD(%)']
            holdings_display = SAMPLE_HOLDINGS_DETAIL[display_cols].copy()
            num_cols = ['비중(%)', '평가금액(억)', '1D(%)', '1W(%)', '1M(%)', 'YTD(%)']
            fmt_dict = {c: '{:.2f}' for c in num_cols}
            st.dataframe(
                holdings_display.style.format(fmt_dict).map(
                    lambda v: 'color: #EF553B' if isinstance(v, (int, float)) and v < 0 else (
                        'color: #00CC96' if isinstance(v, (int, float)) and v > 0 else ''),
                    subset=['1D(%)', '1W(%)', '1M(%)', 'YTD(%)']
                ),
                hide_index=True, use_container_width=True, height=450
            )

    with col_chart:
        cum_ret = (nav_data / nav_data[0] - 1) * 100
        cum_bm = (bm_data / bm_data[0] - 1) * 100
        excess = cum_ret - cum_bm

        fig = go.Figure()
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
        fig.add_trace(go.Scatter(
            x=dates_for_tab0, y=cum_bm, name='BM',
            line=dict(color='#EF553B', width=2, dash='dot')
        ))
        fig.update_layout(
            title='누적수익률 추이',
            yaxis_title='수익률 (%)',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            height=500, margin=dict(t=50, b=30),
            hovermode='x unified'
        )
        st.plotly_chart(fig, use_container_width=True)


# ============================================================
# Tab 2: 편입종목 & MP Gap
# ============================================================

with tabs[1]:
    view_mode = st.radio(
        "보기 모드", ["자산군별", "종목별"],
        horizontal=True, key="holdings_toggle"
    )

    # DB 보유종목 로드 (Tab 1 공유) — lookthrough_on은 상단 토글
    _tab1_db = False
    _tab1_hold = None
    if DB_CONNECTED:
        try:
            if lookthrough_on:
                _tab1_hold = cached_load_holdings_lookthrough(selected_fund)
            else:
                _tab1_hold = cached_load_holdings(selected_fund)
            if not _tab1_hold.empty:
                _tab1_db = True
            else:
                raise ValueError("Holdings empty")
        except Exception as _e:
            st.toast(f"Tab1 보유종목 DB 오류, 목업 사용: {_e}", icon="⚠️")

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
            st.plotly_chart(fig_pie, use_container_width=True)

            grp_display = grp.copy()
            grp_display.columns = ['자산군', '비중(%)', '평가금액(억)']
            st.dataframe(grp_display, hide_index=True, use_container_width=True)

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
            st.plotly_chart(fig_pie_sec, use_container_width=True)

            # 종목별 테이블 — 자산군 순서 → 비중 내림차순
            if _tab1_db:
                _sec_df['_sort'] = _sec_df['자산군'].map(ASSET_CLASS_ORDER).fillna(99)
                _sec_sorted = _sec_df.sort_values(['_sort', '비중(%)'], ascending=[True, False]).drop(columns='_sort')
                st.dataframe(_sec_sorted, hide_index=True, use_container_width=True, height=400)
            else:
                display_cols2 = ['자산군', '종목명', '비중(%)', '평가금액(억)', '1D(%)', '1W(%)', '1M(%)', 'YTD(%)']
                st.dataframe(
                    SAMPLE_HOLDINGS_DETAIL[display_cols2].style.map(
                        lambda v: 'color: #EF553B' if isinstance(v, (int, float)) and v < 0 else (
                            'color: #00CC96' if isinstance(v, (int, float)) and v > 0 else ''),
                        subset=['1D(%)', '1W(%)', '1M(%)', 'YTD(%)']
                    ),
                    hide_index=True, use_container_width=True, height=400
                )

    with col_gap2:
        if fund_info['has_mp']:
            st.markdown("#### MP 대비 Gap 분석")
            st.caption("Over/Under weight 현황")

            # 실제 AP 비중: DB에서 가져온 자산군별 비중 (MP는 Phase 2에서 연결)
            if _tab1_db:
                _ap_weights = _tab1_hold.groupby('자산군')['비중(%)'].sum()
                _ap_weights = _ap_weights.reindex(ASSET_CLASSES).fillna(0)
                _ap_list = _ap_weights.values.tolist()
            else:
                _ap_list = [25.3, 30.1, 22.5, 8.2, 10.5, 0.0, 0.0, 3.4]

            # MP 비중 로드 (직접지정 → DB → fallback)
            _mp_8class = FUND_MP_DIRECT.get(selected_fund)
            if not _mp_8class:
                _mp_desc = FUND_MP_MAPPING.get(selected_fund)
                if DB_CONNECTED and _mp_desc:
                    try:
                        _mp_8class = cached_load_mp_weights_8class(_mp_desc)
                    except Exception:
                        pass
            if _mp_8class:
                _mp_list = [_mp_8class.get(ac, 0.0) for ac in ASSET_CLASSES]
            else:
                _mp_list = [25.0, 30.0, 25.0, 10.0, 8.0, 0.0, 0.0, 2.0]  # fallback

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
            st.plotly_chart(fig_gap, use_container_width=True)

            fig_comp = go.Figure()
            fig_comp.add_trace(go.Bar(name='실제(AP)', x=ASSET_CLASSES, y=gap_df['실제(%)'], marker_color='#636EFA'))
            fig_comp.add_trace(go.Bar(name='MP', x=ASSET_CLASSES, y=gap_df['MP(%)'], marker_color='#EF553B', opacity=0.65))
            max_y = max(max(gap_df['실제(%)']), max(gap_df['MP(%)'])) * 1.2
            fig_comp.update_layout(title='AP vs MP 비중 비교', barmode='group', height=280,
                                     yaxis_title='비중(%)', yaxis_range=[0, max_y],
                                     legend=dict(orientation='h', y=1.05),
                                     margin=dict(t=50, b=20))
            st.plotly_chart(fig_comp, use_container_width=True)
        else:
            st.markdown("#### MP 미설정")
            st.info(f"'{fund_info['short']}' 펀드는 MP(Model Portfolio)가 설정되지 않은 펀드입니다.\n\n"
                    f"MP Gap 분석은 MP가 설정된 OCIO/MySuper 펀드에서만 사용 가능합니다.")
            st.markdown("")
            st.markdown("**MP 설정 펀드 목록:**")
            mp_funds = [f"{FUND_META[k]['short']}" for k in FUND_META if FUND_META[k]['has_mp']]
            st.write(", ".join(mp_funds))

    # 비중 추이
    st.markdown("---")
    st.markdown("#### 비중 추이")
    hist_dates = pd.bdate_range('2025-06-01', '2026-02-11', freq='BMS')

    # DB 비중 히스토리 로드
    _hist_db = False
    _hist_df = None
    if DB_CONNECTED:
        try:
            _hist_df = cached_load_holdings_history(selected_fund, '20250601')
            if not _hist_df.empty and _hist_df['기준일자'].nunique() > 2:
                _hist_db = True
        except Exception:
            pass

    if view_mode == "자산군별":
        col_trend_al, col_trend_ar = st.columns(2)
        with col_trend_al:
            fig_stack = go.Figure()
            if _hist_db:
                # DB 데이터로 자산군별 비중 추이
                for ac in ASSET_CLASSES:
                    _ac_data = _hist_df[_hist_df['AST_CLSF_CD_NM'].str.contains(ac[:2], na=False)]
                    if not _ac_data.empty:
                        _ac_grp = _ac_data.groupby('기준일자')['total_weight'].sum().sort_index()
                        fig_stack.add_trace(go.Scatter(
                            x=_ac_grp.index, y=_ac_grp.values, name=ac,
                            stackgroup='one', fillcolor=ASSET_COLORS[ac],
                            line=dict(width=0.5, color=ASSET_COLORS[ac])
                        ))
                # fallback: 자산군 매핑이 안 되면 전체 raw 표시
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
                        stackgroup='one', fillcolor=ASSET_COLORS[ac],
                        line=dict(width=0.5, color=ASSET_COLORS[ac])
                    ))
            fig_stack.update_layout(title='자산군별 비중 추이',
                height=350, margin=dict(t=40, b=20),
                yaxis_title='비중 (%)', legend=dict(orientation='h', y=-0.25),
                hovermode='x unified')
            st.plotly_chart(fig_stack, use_container_width=True)
        with col_trend_ar:
            # NAV 시계열: DB 우선
            if _tab0_db and '_nav_df' in dir() and not _nav_df.empty:
                _recent_nav = _nav_df[_nav_df['기준일자'] >= '2025-06-01']
                if not _recent_nav.empty:
                    fig_nav_a = go.Figure()
                    fig_nav_a.add_trace(go.Scatter(
                        x=_recent_nav['기준일자'], y=_recent_nav['AUM_억'], name='NAV',
                        fill='tozeroy', fillcolor=hex_to_rgba('#636EFA', 0.15),
                        line=dict(color='#636EFA', width=2)
                    ))
                else:
                    nav_hist_a = make_nav(start=fund_info['aum'] * 1e8, mu=0.0003, sigma=0.003, n=len(hist_dates))
                    fig_nav_a = go.Figure()
                    fig_nav_a.add_trace(go.Scatter(
                        x=hist_dates, y=nav_hist_a / 1e8, name='NAV',
                        fill='tozeroy', fillcolor=hex_to_rgba('#636EFA', 0.15),
                        line=dict(color='#636EFA', width=2)
                    ))
            else:
                nav_hist_a = make_nav(start=fund_info['aum'] * 1e8, mu=0.0003, sigma=0.003, n=len(hist_dates))
                fig_nav_a = go.Figure()
                fig_nav_a.add_trace(go.Scatter(
                    x=hist_dates, y=nav_hist_a / 1e8, name='NAV',
                    fill='tozeroy', fillcolor=hex_to_rgba('#636EFA', 0.15),
                    line=dict(color='#636EFA', width=2)
                ))
            fig_nav_a.update_layout(title='NAV 시계열',
                height=350, margin=dict(t=40, b=20),
                yaxis_title='NAV (억원)', hovermode='x unified',
                showlegend=False)
            st.plotly_chart(fig_nav_a, use_container_width=True)
    else:
        # 종목별: 전체 종목 표시 (좌) + NAV 시계열 영역차트 (우)
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
            st.plotly_chart(fig_stack, use_container_width=True)

        with col_trend_r:
            if _tab0_db and '_nav_df' in dir() and not _nav_df.empty:
                _recent_nav2 = _nav_df[_nav_df['기준일자'] >= '2025-06-01']
                if not _recent_nav2.empty:
                    fig_nav = go.Figure()
                    fig_nav.add_trace(go.Scatter(
                        x=_recent_nav2['기준일자'], y=_recent_nav2['AUM_억'], name='NAV',
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
            st.plotly_chart(fig_nav, use_container_width=True)


# ============================================================
# Tab 3: AP vs VP 분석 (#8)
# ============================================================

with tabs[2]:
    if fund_info['has_mp']:
        st.markdown("#### AP vs VP Gap 분석")
        st.caption("AP(Actual Portfolio) vs VP(Virtual Portfolio) 비중 괴리 및 복제 성과 추적")

        # VP 개념 설명
        with st.expander("VP (Virtual Portfolio) 개념 안내", expanded=False):
            st.markdown("""
            | 포트폴리오 | 의미 | 용도 |
            |-----------|------|------|
            | **AP** (Actual Portfolio) | 실제 운용 포트폴리오 | 기준 (실적) |
            | **VP** (Virtual Portfolio) | 목표 포트폴리오 (구성자산 동적 조정) | 복제 성과 추적, 리밸런싱 판단 |
            | **MP** (Model Portfolio) | 장기 전략 포트폴리오 | 전략적 자산배분 기준 |

            **리밸런싱 트리거 기준** (R: position_module_20260204.R)
            - 괴리율 (VP vs MP, 주식+대체 대분류): **> 5%** (GG, MS, TDF, ACE TDF) / **> 3%** (TIF)
            - 괴리율 (VP vs MP, 주식+대체 소분류): **> 5%** (GG, MS, TDF, ACE TDF) / **> 3%** (TIF)
            - 위험자산비중(VP) > 위험자산비중 상한
            - 채권 듀레이션 복제율 (AP/MP): **80% ~ 120%**

            **신호 분류:**
            - :red_circle: 빨강 (리밸런싱 필요): >= 5% (일반) / >= 3% (TIF)
            - :large_orange_circle: 주황 (주의): >= 3% (일반) / >= 2% (TIF)
            - :green_circle: 초록 (적정): < 3% (일반) / < 2% (TIF)

            **최근 VP 리밸런싱:** `solution.sol_VP_rebalancing_inform` 테이블의 `리밸런싱날짜` 최근값
            """)

        st.markdown("---")

        # 샘플 VP/AP 데이터 (VP/AP는 Phase 3에서 DB 연동 예정)
        vp_weights = [26.0, 29.0, 24.0, 9.0, 9.5, 0.0, 0.0, 2.5]
        ap_weights_vp = [25.3, 30.1, 22.5, 8.2, 10.5, 0.0, 0.0, 3.4]
        # MP 비중: 직접지정 → DB 로드 → fallback
        _mp_8class_t2 = FUND_MP_DIRECT.get(selected_fund)
        if not _mp_8class_t2:
            _mp_desc_t2 = FUND_MP_MAPPING.get(selected_fund)
            if DB_CONNECTED and _mp_desc_t2:
                try:
                    _mp_8class_t2 = cached_load_mp_weights_8class(_mp_desc_t2)
                except Exception:
                    pass
        if _mp_8class_t2:
            mp_weights = [_mp_8class_t2.get(ac, 0.0) for ac in ASSET_CLASSES]
        else:
            mp_weights = [25.0, 30.0, 25.0, 10.0, 8.0, 0.0, 0.0, 2.0]

        vp_gap_df = pd.DataFrame({
            '자산군': ASSET_CLASSES,
            'AP(%)': ap_weights_vp,
            'VP(%)': vp_weights,
            'MP(%)': mp_weights,
            'AP-VP Gap(%p)': [a - v for a, v in zip(ap_weights_vp, vp_weights)],
            'VP-MP Gap(%p)': [v - m for v, m in zip(vp_weights, mp_weights)],
        })

        # 지표 카드
        ap_vp_total_gap = sum(abs(a - v) for a, v in zip(ap_weights_vp, vp_weights))
        vp_mp_total_gap = sum(abs(v - m) for v, m in zip(vp_weights, mp_weights))
        vp_c1, vp_c2, vp_c3, vp_c4 = st.columns(4)
        vp_c1.metric("AP-VP 총괴리", f"{ap_vp_total_gap:.1f}%p", "적정" if ap_vp_total_gap < 10 else "주의")
        vp_c2.metric("VP-MP 총괴리", f"{vp_mp_total_gap:.1f}%p", "적정" if vp_mp_total_gap < 10 else "주의")
        vp_c3.metric("최근 VP 리밸런싱", "2026-02-03")
        vp_c4.metric("VP 추적오차", "0.15%", "-0.03%p")

        st.markdown("")

        col_vp1, col_vp2 = st.columns(2)

        with col_vp1:
            st.markdown("##### AP vs VP vs MP 비중 비교")
            fig_vp_comp = go.Figure()
            fig_vp_comp.add_trace(go.Bar(name='AP (실제)', x=ASSET_CLASSES, y=ap_weights_vp,
                                          marker_color='#636EFA'))
            fig_vp_comp.add_trace(go.Bar(name='VP (목표)', x=ASSET_CLASSES, y=vp_weights,
                                          marker_color='#00CC96', opacity=0.75))
            fig_vp_comp.add_trace(go.Bar(name='MP (전략)', x=ASSET_CLASSES, y=mp_weights,
                                          marker_color='#EF553B', opacity=0.5))
            fig_vp_comp.update_layout(barmode='group', height=380, yaxis_title='비중(%)',
                                        legend=dict(orientation='h', y=1.08))
            st.plotly_chart(fig_vp_comp, use_container_width=True)

        with col_vp2:
            st.markdown("##### AP-VP Gap / VP-MP Gap")
            gap_colors_av = ['#EF553B' if g > 0 else '#636EFA' for g in vp_gap_df['AP-VP Gap(%p)']]
            fig_vp_gap = make_subplots(rows=1, cols=2, subplot_titles=('AP - VP Gap', 'VP - MP Gap'))
            fig_vp_gap.add_trace(go.Bar(
                y=ASSET_CLASSES, x=vp_gap_df['AP-VP Gap(%p)'], orientation='h',
                marker_color=gap_colors_av,
                text=[f"{g:+.1f}" for g in vp_gap_df['AP-VP Gap(%p)']], textposition='outside',
                showlegend=False
            ), row=1, col=1)
            gap_colors_vm = ['#EF553B' if g > 0 else '#636EFA' for g in vp_gap_df['VP-MP Gap(%p)']]
            fig_vp_gap.add_trace(go.Bar(
                y=ASSET_CLASSES, x=vp_gap_df['VP-MP Gap(%p)'], orientation='h',
                marker_color=gap_colors_vm,
                text=[f"{g:+.1f}" for g in vp_gap_df['VP-MP Gap(%p)']], textposition='outside',
                showlegend=False
            ), row=1, col=2)
            fig_vp_gap.update_layout(height=380, margin=dict(l=80))
            fig_vp_gap.update_yaxes(autorange='reversed')
            st.plotly_chart(fig_vp_gap, use_container_width=True)

        # #5: 상세 테이블 - 컬럼 헤더에서 (%) 제거, 셀에 % 포맷, 상태별 음영
        st.markdown("##### 자산군별 Gap 상세")
        vp_display = pd.DataFrame({
            '자산군': ASSET_CLASSES,
            'AP': [f"{v:.1f}%" for v in ap_weights_vp],
            'VP': [f"{v:.1f}%" for v in vp_weights],
            'MP': [f"{v:.1f}%" for v in mp_weights],
            'AP-VP Gap': [f"{a-v:+.1f}%p" for a, v in zip(ap_weights_vp, vp_weights)],
            'VP-MP Gap': [f"{v-m:+.1f}%p" for v, m in zip(vp_weights, mp_weights)],
            'AP-VP 상태': [('Over' if a-v > 5.0 else ('Under' if a-v < -5.0 else '적정'))
                          for a, v in zip(ap_weights_vp, vp_weights)],
        })

        def color_status(val):
            if val == '적정':
                return 'background-color: #d4edda; color: #155724'
            else:
                return 'background-color: #fff3cd; color: #856404'

        st.dataframe(
            vp_display.style.map(color_status, subset=['AP-VP 상태']),
            hide_index=True, use_container_width=True
        )

        # #4: Gap 추이 + 누적수익률 side by side
        st.markdown("---")
        col_gap_l, col_gap_r = st.columns(2)

        with col_gap_l:
            st.markdown("##### Gap 추이 (AP-VP)")
            gap_hist_dates = pd.bdate_range('2025-06-01', '2026-02-11', freq='BMS')
            fig_gap_trend = go.Figure()
            for i, ac in enumerate(ASSET_CLASSES):
                base_gap = vp_gap_df['AP-VP Gap(%p)'].iloc[i]
                gap_series = base_gap + np.cumsum(np.random.normal(0, 0.3, len(gap_hist_dates)))
                fig_gap_trend.add_trace(go.Scatter(
                    x=gap_hist_dates, y=gap_series, name=ac,
                    line=dict(color=ASSET_COLORS.get(ac, '#999'), width=2)
                ))
            fig_gap_trend.add_hline(y=0, line_dash="solid", line_color="black", line_width=1)
            fig_gap_trend.add_hrect(y0=-5.0, y1=5.0, fillcolor="green", opacity=0.04,
                                     annotation_text="허용범위 ±5.0%p")
            fig_gap_trend.update_layout(height=400, yaxis_title='Gap (%p)',
                                         yaxis=dict(dtick=2),
                                         hovermode='x unified',
                                         legend=dict(orientation='h', y=-0.20, font=dict(size=9)))
            st.plotly_chart(fig_gap_trend, use_container_width=True)

        with col_gap_r:
            st.markdown("##### AP vs VP 누적수익률 비교")
            _n_vp = len(nav_data)
            vp_nav = make_nav(1000, 0.00028, 0.0048, _n_vp)
            ap_cum_vp = (nav_data / nav_data[0] - 1) * 100
            vp_cum = (vp_nav / vp_nav[0] - 1) * 100
            te = ap_cum_vp - vp_cum
            _vp_dates = dates_for_tab0 if len(dates_for_tab0) == _n_vp else pd.bdate_range(end='2026-02-23', periods=_n_vp)

            fig_vp_perf = go.Figure()
            fig_vp_perf.add_trace(go.Scatter(
                x=_vp_dates, y=te, name='추적오차 (AP-VP)',
                fill='tozeroy', fillcolor='rgba(255,161,90,0.15)',
                line=dict(color='#FFA15A', width=0.8)
            ))
            fig_vp_perf.add_trace(go.Scatter(x=_vp_dates, y=ap_cum_vp, name='AP (실제)',
                                               line=dict(color='#636EFA', width=2.5)))
            fig_vp_perf.add_trace(go.Scatter(x=_vp_dates, y=vp_cum, name='VP (목표)',
                                               line=dict(color='#00CC96', width=2, dash='dot')))
            fig_vp_perf.update_layout(height=400, yaxis_title='수익률(%)', hovermode='x unified',
                                        legend=dict(orientation='h', y=1.05))
            st.plotly_chart(fig_vp_perf, use_container_width=True)

    else:
        st.markdown("#### VP 미설정")
        st.info(f"'{fund_info['short']}' 펀드는 VP(Virtual Portfolio)가 설정되지 않은 펀드입니다.\n\n"
                f"VP Gap 분석은 MP가 설정된 OCIO/MySuper 펀드에서만 사용 가능합니다.")


# ============================================================
# Tab 4: 성과분석 (Brinson)
# ============================================================

with tabs[3]:
    st.markdown("#### Brinson Performance Attribution")

    # 분석기간
    bc1, bc2 = st.columns([3, 1])
    with bc1:
        analysis_period = st.date_input("분석기간", value=(datetime(2025, 7, 1), datetime(2026, 2, 11)),
                                         key='brinson_period')
    with bc2:
        pa_method = st.selectbox("자산군 분류", ["방법1", "방법2"], key='pa_method')

    # FX 분리 토글 — 분석기간 아래 배치 (#13)
    pa_fx = st.toggle("FX 분리 (FX를 별도 자산군으로 분리하여 분석)", value=True, key='pa_fx')
    st.caption("ON: FX를 별도 자산군으로 분리 | OFF: FX 효과를 각 자산군에 포함")

    st.markdown("---")

    # 자산군 분류 방법에 따른 데이터 변경 (#12)
    if pa_method == "방법1":
        pa_asset_classes = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자']
        pa_ap_w = [25.3, 30.1, 22.5, 8.2, 10.5]
        pa_bm_w = [25.0, 30.0, 25.0, 10.0, 8.0]
        pa_ap_ret = [2.31, 5.12, 0.82, 1.23, 3.45]
        pa_bm_ret = [1.98, 4.85, 0.75, 1.10, 3.12]
    else:  # 방법2: 더 세분화된 분류
        pa_asset_classes = ['국내주식', '미국주식', '미국외선진', '신흥국주식', '국내채권', '해외채권', '대체투자']
        pa_ap_w = [25.3, 20.5, 5.3, 4.3, 22.5, 8.2, 10.5]
        pa_bm_w = [25.0, 20.0, 5.0, 5.0, 25.0, 10.0, 8.0]
        pa_ap_ret = [2.31, 6.10, 3.50, 1.80, 0.82, 1.23, 3.45]
        pa_bm_ret = [1.98, 5.80, 3.20, 1.50, 0.75, 1.10, 3.12]

    # FX 분리 적용 (#13)
    if pa_fx:
        pa_asset_classes_display = pa_asset_classes + ['FX']
        fx_ap_w = sum(w for w, ac in zip(pa_ap_w, pa_asset_classes) if '해외' in ac or '미국' in ac or '신흥' in ac)
        fx_bm_w = sum(w for w, ac in zip(pa_bm_w, pa_asset_classes) if '해외' in ac or '미국' in ac or '신흥' in ac)
        pa_ap_w_display = pa_ap_w + [fx_ap_w]
        pa_bm_w_display = pa_bm_w + [fx_bm_w]
        # FX 분리: 해외자산 수익률에서 FX 효과 제거
        fx_return = 1.65  # 샘플 원달러 변동 기여
        pa_ap_ret_display = []
        pa_bm_ret_display = []
        for i, ac in enumerate(pa_asset_classes):
            if '해외' in ac or '미국' in ac or '신흥' in ac:
                # FX 제외: (1+r_total)/(1+r_fx) - 1
                pa_ap_ret_display.append(round((1 + pa_ap_ret[i]/100)/(1 + fx_return/100) - 1, 4) * 100)
                pa_bm_ret_display.append(round((1 + pa_bm_ret[i]/100)/(1 + fx_return/100) - 1, 4) * 100)
            else:
                pa_ap_ret_display.append(pa_ap_ret[i])
                pa_bm_ret_display.append(pa_bm_ret[i])
        pa_ap_ret_display.append(fx_return)
        pa_bm_ret_display.append(fx_return * 0.95)
    else:
        pa_asset_classes_display = pa_asset_classes
        pa_ap_w_display = pa_ap_w
        pa_bm_w_display = pa_bm_w
        pa_ap_ret_display = pa_ap_ret
        pa_bm_ret_display = pa_bm_ret

    # Brinson 계산
    alloc_effects = [(pa_ap_w_display[i] - pa_bm_w_display[i]) * pa_bm_ret_display[i] / 100
                     for i in range(len(pa_asset_classes_display))]
    select_effects = [pa_bm_w_display[i] * (pa_ap_ret_display[i] - pa_bm_ret_display[i]) / 100
                      for i in range(len(pa_asset_classes_display))]
    cross_effects = [(pa_ap_w_display[i] - pa_bm_w_display[i]) * (pa_ap_ret_display[i] - pa_bm_ret_display[i]) / 100
                     for i in range(len(pa_asset_classes_display))]
    contrib_ret = [pa_ap_w_display[i] * pa_ap_ret_display[i] / 100
                   for i in range(len(pa_asset_classes_display))]

    total_alloc = sum(alloc_effects)
    total_select = sum(select_effects)
    total_cross = sum(cross_effects)
    total_excess = total_alloc + total_select + total_cross
    residual = 0.05

    pa_tabs = st.tabs(["Brinson 분석", "수익률 비교", "비중 비교", "개별포트 분석"])

    with pa_tabs[0]:
        col_tbl, col_chart = st.columns([2, 3])
        with col_tbl:
            st.markdown("##### 자산군별 기여수익률")
            brinson_df = pd.DataFrame({
                '자산군': pa_asset_classes_display,
                'AP비중': [f"{w:.1f}" for w in pa_ap_w_display],
                'BM비중': [f"{w:.1f}" for w in pa_bm_w_display],
                'AP수익률': [f"{r:+.2f}%" for r in pa_ap_ret_display],
                'BM수익률': [f"{r:+.2f}%" for r in pa_bm_ret_display],
                '기여수익률': [f"{c:+.2f}%" for c in contrib_ret],
            })
            st.dataframe(brinson_df, hide_index=True, use_container_width=True)

            st.markdown("##### 초과성과 요인분해")
            decomp_df = pd.DataFrame({
                '요인': ['Allocation Effect', 'Selection Effect', 'Cross Effect', '유동성/기타', '합계'],
                '기여도': [f"{total_alloc:+.2f}%", f"{total_select:+.2f}%", f"{total_cross:+.2f}%",
                         f"{residual:+.2f}%", f"{total_excess + residual:+.2f}%"],
                '비율': [f"{abs(total_alloc)/max(abs(total_excess+residual),0.01)*100:.0f}%",
                        f"{abs(total_select)/max(abs(total_excess+residual),0.01)*100:.0f}%",
                        f"{abs(total_cross)/max(abs(total_excess+residual),0.01)*100:.0f}%",
                        f"{abs(residual)/max(abs(total_excess+residual),0.01)*100:.0f}%",
                        '100%']
            })
            st.dataframe(decomp_df, hide_index=True, use_container_width=True)

        with col_chart:
            fig_wf = go.Figure(go.Waterfall(
                name="", orientation="v",
                x=['Allocation', 'Selection', 'Cross', '유동성/기타', '합계'],
                y=[total_alloc, total_select, total_cross, residual, total_excess + residual],
                measure=['relative', 'relative', 'relative', 'relative', 'total'],
                connector_line_color='#888',
                increasing_marker_color='#636EFA',
                decreasing_marker_color='#EF553B',
                totals_marker_color='#00CC96',
                text=[f"{total_alloc:+.2f}%", f"{total_select:+.2f}%", f"{total_cross:+.2f}%",
                      f"{residual:+.2f}%", f"{total_excess+residual:+.2f}%"],
                textposition='outside'
            ))
            fig_wf.update_layout(title='초과성과 요인분해 (Brinson)', height=450, yaxis_title='기여도 (%)')
            st.plotly_chart(fig_wf, use_container_width=True)

    with pa_tabs[1]:
        ap_cum = (make_nav(1000, 0.0003, 0.004, 150) / 1000 - 1) * 100
        bm_cum2 = (make_nav(1000, 0.00025, 0.003, 150) / 1000 - 1) * 100
        comp_dates = pd.bdate_range('2025-07-01', periods=150)
        excess_cum = ap_cum - bm_cum2

        fig_ret = go.Figure()
        fig_ret.add_trace(go.Scatter(
            x=comp_dates, y=excess_cum, name='초과수익',
            fill='tozeroy', fillcolor='rgba(144, 238, 144, 0.20)',
            line=dict(color='rgba(144, 238, 144, 0.5)', width=0.8)
        ))
        fig_ret.add_trace(go.Scatter(x=comp_dates, y=ap_cum, name='AP (포트폴리오)',
                                      line=dict(color='#636EFA', width=2.5)))
        fig_ret.add_trace(go.Scatter(x=comp_dates, y=bm_cum2, name='BM',
                                      line=dict(color='#EF553B', width=2, dash='dot')))
        fig_ret.update_layout(title='AP vs BM 누적수익률', height=450,
                                yaxis_title='수익률(%)', hovermode='x unified',
                                legend=dict(orientation='h', y=1.05))
        st.plotly_chart(fig_ret, use_container_width=True)

    with pa_tabs[2]:
        st.markdown("##### AP vs BM 비중 비교")
        gap_vals_pa = [a - b for a, b in zip(pa_ap_w_display, pa_bm_w_display)]

        col_wl, col_wr = st.columns(2)
        with col_wl:
            fig_wcomp = go.Figure()
            fig_wcomp.add_trace(go.Bar(name='AP', x=pa_asset_classes_display, y=pa_ap_w_display, marker_color='#636EFA'))
            fig_wcomp.add_trace(go.Bar(name='BM', x=pa_asset_classes_display, y=pa_bm_w_display, marker_color='#EF553B', opacity=0.65))
            fig_wcomp.update_layout(title='자산군별 AP vs BM 비중', barmode='group', height=380,
                                     yaxis_title='비중(%)', legend=dict(orientation='h', y=1.05))
            st.plotly_chart(fig_wcomp, use_container_width=True)

        with col_wr:
            colors_g = ['#EF553B' if g > 0 else '#636EFA' for g in gap_vals_pa]
            fig_gbar = go.Figure()
            fig_gbar.add_trace(go.Bar(
                y=pa_asset_classes_display, x=gap_vals_pa,
                orientation='h', marker_color=colors_g,
                text=[f"{g:+.1f}%p" for g in gap_vals_pa], textposition='outside'
            ))
            fig_gbar.add_vline(x=0, line_color="black", line_width=1)
            fig_gbar.update_layout(title='AP-BM Gap', height=380,
                                    margin=dict(l=100), xaxis_title='Gap(%p)',
                                    yaxis=dict(autorange='reversed'))
            st.plotly_chart(fig_gbar, use_container_width=True)

        wcomp_df = pd.DataFrame({
            '자산군': pa_asset_classes_display,
            'AP비중(%)': pa_ap_w_display, 'BM비중(%)': pa_bm_w_display,
            'Gap(%p)': gap_vals_pa,
            '상태': ['Over' if g > 1.5 else ('Under' if g < -1.5 else '적정') for g in gap_vals_pa]
        })
        st.dataframe(wcomp_df, hide_index=True, use_container_width=True)

    with pa_tabs[3]:
        col_pl, col_pr = st.columns(2)
        with col_pl:
            st.markdown("##### 종목별 기여수익률")
            sec_contrib = pd.DataFrame({
                '자산군': ['국내주식','국내주식','해외주식','해외주식','해외주식','국내채권','국내채권','대체투자'],
                '종목명': ['KODEX200','TIGER KOSPI','SPY','QQQ','VWO','국고3Y','통안2Y','맥쿼리인프라'],
                '수익률(%)': [2.31, 1.82, 5.12, 7.21, -1.30, 0.82, 0.51, 3.45],
                '기여수익률(%)': [0.24, 0.15, 0.63, 0.73, -0.06, 0.10, 0.05, 0.17]
            })
            st.dataframe(sec_contrib.style.map(
                lambda v: 'color: #EF553B' if isinstance(v, float) and v < 0 else (
                    'color: #00CC96' if isinstance(v, float) and v > 0 else ''),
                subset=['수익률(%)', '기여수익률(%)']
            ), hide_index=True, use_container_width=True)

        with col_pr:
            st.markdown("##### 자산군별 기여수익률")
            colors_cc = ['#EF553B' if c < 0 else '#636EFA' for c in contrib_ret]
            fig_ctb = go.Figure(go.Bar(x=pa_asset_classes_display, y=contrib_ret, marker_color=colors_cc,
                                        text=[f"{c:+.2f}%" for c in contrib_ret], textposition='outside'))
            fig_ctb.update_layout(title='자산군별 기여수익률', height=350, yaxis_title='기여수익률(%)')
            st.plotly_chart(fig_ctb, use_container_width=True)


# ============================================================
# Tab 5: 매크로 지표
# ============================================================

with tabs[4]:
    st.markdown("#### 매크로 지표 대시보드")
    st.caption("Bloomberg 데이터 엑셀 업로드 기반 | 주간 업데이트")

    with st.expander("Bloomberg 데이터 엑셀 업로드", expanded=False):
        st.markdown("""
        **엑셀 파일 형식 안내:**
        - **Sheet 1 (TR_Index)**: Date | MXWD | MXUS | MXWOU | MXEF | ... (Tot_Return_Index_Net_Dvds)
        - **Sheet 2 (Valuation)**: Date | MXWD_PE | MXWD_EPS | MXUS_PE | MXUS_EPS | ... (BEST_PE_RATIO, BEST_EPS)
        - **Sheet 3 (Benchmarks)**: Date | KOSPI | SPX | RTY | ... (PX_Last)
        - **Sheet 4 (FX)**: Date | USDKRW | DXY | EURUSD | ... (px_last)
        - **Sheet 5 (Rates)**: Date | USGG2Y | USGG10Y | KBPMG10Y | ... (px_last)
        """)
        uploaded_file = st.file_uploader("엑셀 파일 업로드 (.xlsx)", type=['xlsx', 'xls'], key='macro_upload')
        if uploaded_file:
            st.success(f"'{uploaded_file.name}' 업로드 완료! 데이터를 분석 중...")

    st.markdown("---")

    # --- 샘플 데이터 (확장) ---
    macro_dates = pd.bdate_range('2024-01-02', '2026-02-11', freq='B')
    n_md = len(macro_dates)

    # 전체 티커 PE/EPS 데이터 (#5 확장)
    all_val_tickers = ['MSCI ACWI', 'MSCI US', 'MSCI EM', 'MSCI Korea', 'S&P500',
                       'NASDAQ 100', 'Russell 2000', 'MSCI World ex US', 'MSCI World']
    pe_data = {}
    eps_data = {}
    pe_bases = [18.5, 21.2, 13.8, 10.5, 22.1, 28.5, 16.2, 15.8, 19.0]
    eps_bases = [45.0, 52.0, 28.0, 32.0, 55.0, 18.0, 22.0, 38.0, 48.0]
    for i, tk in enumerate(all_val_tickers):
        pe_data[tk] = pe_bases[i] + np.cumsum(np.random.normal(0, 0.05, n_md))
        eps_data[tk] = eps_bases[i] + np.cumsum(np.random.normal(0.01, 0.08, n_md))

    tr_indices = {}
    tr_mus = [0.0003, 0.0004, 0.0002, 0.0001, 0.0004, 0.0005, 0.0002, 0.00025, 0.00035]
    tr_sigmas = [0.008, 0.009, 0.010, 0.012, 0.009, 0.012, 0.011, 0.008, 0.009]
    for i, tk in enumerate(all_val_tickers):
        tr_indices[tk] = 100 * np.cumprod(1 + np.random.normal(tr_mus[i], tr_sigmas[i], n_md))

    # --- Total Return Decomposition ---
    st.markdown("### Total Return Decomposition")
    st.caption("TR = PE Ratio Growth + EPS Growth + Other (Dividend + Residual)")

    decomp_ticker = st.selectbox(
        "지수 선택", list(pe_data.keys()), key='tr_decomp_ticker'
    )
    decomp_period = st.radio("기간", ['3M', '6M', 'YTD', '1Y'], horizontal=True, key='tr_decomp_period')
    period_map_macro = {'3M': 66, '6M': 132, 'YTD': len(macro_dates) - len(macro_dates[macro_dates >= '2026-01-01']), '1Y': 252}
    n_period = min(period_map_macro[decomp_period], n_md - 1)

    tr_arr = tr_indices[decomp_ticker]
    pe_arr = pe_data[decomp_ticker]
    eps_arr = eps_data[decomp_ticker]

    total_return = (tr_arr[-1] / tr_arr[-(n_period+1)] - 1) * 100
    pe_growth = (pe_arr[-1] / pe_arr[-(n_period+1)] - 1) * 100
    eps_growth = (eps_arr[-1] / eps_arr[-(n_period+1)] - 1) * 100
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
        st.plotly_chart(fig_decomp, use_container_width=True)

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
        st.dataframe(summary_df, hide_index=True, use_container_width=True)

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

    # 표시 모드 토글: 실제 값 vs Growth Rate
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
                       'YTD': len(macro_dates) - len(macro_dates[macro_dates >= '2026-01-01'])}
            n_shift = min(gp_map.get(growth_period_val, 66), n_md - 1)
            start_idx = max(0, n_md - n_shift - 1)
            trimmed_dates = macro_dates[start_idx:]
            fig_val = make_subplots(rows=1, cols=2,
                                     subplot_titles=(f'PE Ratio Growth Rate ({growth_period_val})',
                                                     f'EPS Growth Rate ({growth_period_val})'))
            for i, tk in enumerate(selected_val_tickers):
                c = val_colors[i % len(val_colors)]
                pe_s = pd.Series(pe_data[tk], index=macro_dates)
                pe_trimmed = pe_s.iloc[start_idx:]
                pe_indexed = (pe_trimmed / pe_trimmed.iloc[0] - 1) * 100
                eps_s = pd.Series(eps_data[tk], index=macro_dates)
                eps_trimmed = eps_s.iloc[start_idx:]
                eps_indexed = (eps_trimmed / eps_trimmed.iloc[0] - 1) * 100
                fig_val.add_trace(go.Scatter(
                    x=trimmed_dates, y=pe_indexed.values, name=tk,
                    line=dict(color=c, width=2),
                    legendgroup=tk, showlegend=True
                ), row=1, col=1)
                fig_val.add_trace(go.Scatter(
                    x=trimmed_dates, y=eps_indexed.values, name=tk,
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
                fig_val.add_trace(go.Scatter(
                    x=macro_dates, y=pe_data[tk], name=tk,
                    line=dict(color=c, width=2),
                    legendgroup=tk, showlegend=True
                ), row=1, col=1)
                fig_val.add_trace(go.Scatter(
                    x=macro_dates, y=eps_data[tk], name=tk,
                    line=dict(color=c, width=2, dash='dot'),
                    legendgroup=tk, showlegend=False
                ), row=1, col=2)
            fig_val.update_layout(height=400, hovermode='x unified',
                                   legend=dict(orientation='h', y=1.10))
            fig_val.update_yaxes(title_text='PE Ratio (x)', row=1, col=1)
            fig_val.update_yaxes(title_text='EPS ($)', row=1, col=2)
        st.plotly_chart(fig_val, use_container_width=True)

    st.markdown("---")

    # --- 원화 가치 분석 (#6, #7) ---
    st.markdown("### 원화 가치 분석")

    # 2017.1.1 이후 데이터 생성
    fx_full_dates = pd.bdate_range('2017-01-02', '2026-02-11', freq='B')
    n_fx = len(fx_full_dates)
    np.random.seed(77)
    usdkrw_full = 1150 + np.cumsum(np.random.normal(0.15, 2.5, n_fx))
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
        st.plotly_chart(fig_krw, use_container_width=True)

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
        st.plotly_chart(fig_spread, use_container_width=True)

    # #7: 주요 통화 기간수익률 제거

    st.markdown("---")

    # --- 글로벌 금리 추이 (#8) ---
    st.markdown("### 글로벌 금리 추이")
    monthly_dates = pd.date_range('2024-01-01', '2026-02-01', freq='MS')
    n_rates = len(monthly_dates)

    us_10y = 4.3 + np.cumsum(np.random.normal(-0.01, 0.08, n_rates))
    us_2y = 4.5 + np.cumsum(np.random.normal(-0.015, 0.06, n_rates))
    kr_10y = 3.5 + np.cumsum(np.random.normal(-0.01, 0.05, n_rates))
    kr_2y = 3.3 + np.cumsum(np.random.normal(-0.01, 0.04, n_rates))
    us_base = np.full(n_rates, 5.25)
    us_base[n_rates//2:] = 4.50  # 금리 인하
    kr_base = np.full(n_rates, 3.50)
    kr_base[n_rates*2//3:] = 3.00  # 금리 인하

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
        st.plotly_chart(fig_bonds, use_container_width=True)

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
        st.plotly_chart(fig_policy, use_container_width=True)

    st.markdown("---")

    # --- 자산군별 벤치마크 수익률 (시장환경 종합 + 기존 벤치마크 테이블 병합) ---
    env_title_col, env_toggle_col = st.columns([4, 1])
    with env_title_col:
        st.markdown("### 자산군별 벤치마크 수익률")
    with env_toggle_col:
        env_krw_toggle = st.toggle("원화환산", key='env_krw_toggle')
    macro_env_data = pd.DataFrame([
        # === 주식 ===
        # 주식 - 국내
        {'대분류': '주식', '중분류': '국내', '소분류': '시장', '지표': 'KOSPI', '현재값': '2,685.3', '1D': -0.15, '1W': -0.52, '1M': -1.23, '3M': 2.85, '6M': -3.10, '1Y': 5.42, 'YTD': -1.23, 'Source': 'Bloomberg', 'dataseries': 'TOT RETURN INDEX NET DVDS', 'dataset_name': 'KOSPI Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'KOSDAQ', '현재값': '812.5', '1D': 0.28, '1W': 0.65, '1M': 0.82, '3M': -1.35, '6M': -5.20, '1Y': -2.15, 'YTD': 0.82, 'Source': 'Bloomberg', 'dataseries': 'TOT RETURN INDEX NET DVDS', 'dataset_name': 'KOSDAQ Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'KOSPI 200', '현재값': '368.9', '1D': -0.12, '1W': -0.45, '1M': -0.95, '3M': 3.10, '6M': -2.85, '1Y': 6.15, 'YTD': -0.95, 'Source': 'Bloomberg', 'dataseries': 'TOT RETURN INDEX NET DVDS', 'dataset_name': 'KOSPI 200 Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': 'MSCI KR', '지표': 'MSCI Korea', '현재값': '72.5', '1D': 0.85, '1W': 3.20, '1M': 5.42, '3M': 12.50, '6M': 15.80, '1Y': 21.80, 'YTD': 5.42, 'Source': 'Factset', 'dataseries': 'FG Return', 'dataset_name': 'iShares MSCI South Korea ETF', '최근기준일': '2026-01-31'},
        # 주식 - 미국
        {'대분류': '', '중분류': '미국', '소분류': '시장', '지표': 'S&P 500', '현재값': '6,025.1', '1D': 0.45, '1W': 1.12, '1M': 2.31, '3M': 5.85, '6M': 8.42, '1Y': 18.50, 'YTD': 2.31, 'Source': 'Factset', 'dataseries': 'FG Total Return Index (Unhedged)', 'dataset_name': 'S&P 500 Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'NASDAQ 100', '현재값': '21,350.8', '1D': 0.68, '1W': 1.85, '1M': 3.12, '3M': 7.25, '6M': 10.80, '1Y': 24.30, 'YTD': 3.12, 'Source': 'Bloomberg', 'dataseries': 'TOT RETURN INDEX NET DVDS', 'dataset_name': 'NASDAQ100 Total Return Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '성장', '지표': 'SPYG', '현재값': '82.3', '1D': 0.55, '1W': 1.65, '1M': 3.55, '3M': 8.10, '6M': 12.35, '1Y': 26.80, 'YTD': 3.55, 'Source': 'Factset', 'dataseries': 'FG Return', 'dataset_name': 'SPDR Portfolio S&P 500 Growth ETF', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'CRSP US Large Cap Growth', '현재값': '195.2', '1D': -0.32, '1W': -1.15, '1M': -4.95, '3M': -2.30, '6M': 5.80, '1Y': 15.20, 'YTD': -4.95, 'Source': 'Factset', 'dataseries': 'FG Return', 'dataset_name': 'CRSP US Large Growth Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '가치', '지표': 'CRSP US Large Cap Value', '현재값': '158.7', '1D': 0.42, '1W': 1.35, '1M': 5.86, '3M': 8.50, '6M': 10.20, '1Y': 14.80, 'YTD': 5.86, 'Source': 'Factset', 'dataseries': 'FG Return', 'dataset_name': 'CRSP US Large Value Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'SPYV', '현재값': '52.8', '1D': 0.38, '1W': 1.20, '1M': 4.92, '3M': 7.85, '6M': 9.50, '1Y': 13.60, 'YTD': 4.92, 'Source': 'Factset', 'dataseries': 'FG Return', 'dataset_name': 'SPDR Portfolio S&P 500 Value ETF', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '중소형', '지표': 'Russell 2000', '현재값': '2,280.5', '1D': 0.22, '1W': 0.75, '1M': 1.05, '3M': -0.85, '6M': 3.20, '1Y': 8.50, 'YTD': 1.05, 'Source': 'Factset', 'dataseries': 'FG Return', 'dataset_name': 'Russell 2000 Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '고배당', '지표': 'DJ Dividend 100', '현재값': '5,120.3', '1D': 0.52, '1W': 1.80, '1M': 3.85, '3M': 7.20, '6M': 9.80, '1Y': 12.33, 'YTD': 3.85, 'Source': 'Bloomberg', 'dataseries': 'TOT RETURN INDEX NET DVDS', 'dataset_name': 'Dow Jones U.S. Dividend 100 Index', '최근기준일': '2026-01-31'},
        # 주식 - 글로벌/선진국/EM
        {'대분류': '', '중분류': '글로벌', '소분류': '', '지표': 'MSCI ACWI', '현재값': '812.5', '1D': 0.35, '1W': 0.92, '1M': 1.85, '3M': 4.50, '6M': 7.20, '1Y': 15.80, 'YTD': 1.85, 'Source': 'Factset', 'dataseries': 'FG Net Total Return Index', 'dataset_name': 'MSCI ACWI Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '선진국', '소분류': '', '지표': 'MSCI World', '현재값': '3,520.1', '1D': 0.30, '1W': 0.85, '1M': 1.13, '3M': 4.20, '6M': 6.80, '1Y': 16.50, 'YTD': 1.13, 'Source': 'Bloomberg', 'dataseries': 'TOT RETURN INDEX NET DVDS', 'dataset_name': 'M1WD Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '미국외 선진국', '소분류': '', '지표': 'MSCI World ex US', '현재값': '2,180.5', '1D': 0.48, '1W': 1.25, '1M': 4.96, '3M': 6.80, '6M': 5.20, '1Y': 8.90, 'YTD': 4.96, 'Source': 'Factset', 'dataseries': 'FG Return', 'dataset_name': 'MSCI World ex-USA Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '신흥시장', '소분류': '', '지표': 'MSCI EM', '현재값': '1,085.3', '1D': 0.25, '1W': 0.68, '1M': 2.45, '3M': 3.85, '6M': 1.50, '1Y': 5.20, 'YTD': 2.45, 'Source': 'Factset', 'dataseries': 'FG Return', 'dataset_name': 'MSCI EM (Emerging Markets) Index', '최근기준일': '2026-01-31'},
        # === 채권 - 지수 ===
        {'대분류': '채권', '중분류': '지수-글로벌(UH to USD)', '소분류': '', '지표': 'Barclays Global Agg. Bond', '현재값': '480.2', '1D': 0.02, '1W': 0.08, '1M': 0.35, '3M': -0.52, '6M': 1.20, '1Y': 2.85, 'YTD': 0.35, 'Source': 'Factset', 'dataseries': 'FG Total Return Index (Unhedged)', 'dataset_name': 'Bloomberg Global Aggregate Total Return Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '지수-글로벌(H to USD)', '소분류': '', '지표': 'Barclays Global Agg. Bond (H)', '현재값': '520.1', '1D': 0.01, '1W': 0.05, '1M': 0.12, '3M': -0.35, '6M': 0.85, '1Y': 2.10, 'YTD': 0.12, 'Source': 'Factset', 'dataseries': 'FG Total Return Index (Hedged)', 'dataset_name': 'Bloomberg Global Aggregate Total Return Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '지수-글로벌(H to KRW)', '소분류': '', '지표': 'Barclays Global Agg. Bond (KRW)', '현재값': '105.8', '1D': 0.00, '1W': 0.02, '1M': 0.00, '3M': -0.15, '6M': 0.55, '1Y': 1.80, 'YTD': 0.00, 'Source': 'Bloomberg', 'dataseries': 'TOT RETURN INDEX NET DVDS', 'dataset_name': 'Bloomberg Global Aggregate TR Index Hedged KRW', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '지수-국내', '소분류': '국채3년', '지표': '매경채권지수', '현재값': '230.5', '1D': -0.02, '1W': -0.08, '1M': -0.35, '3M': 0.45, '6M': 1.10, '1Y': 2.50, 'YTD': -0.35, 'Source': 'KIS', 'dataseries': 'KIS Bond Index', 'dataset_name': 'MK MSB Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '국고10년', '지표': 'KRX 10년채권지수', '현재값': '145.8', '1D': -0.08, '1W': -0.35, '1M': -1.94, '3M': 0.85, '6M': 2.50, '1Y': 4.20, 'YTD': -1.94, 'Source': 'KIS', 'dataseries': 'KIS Bond Index', 'dataset_name': 'KIS 10Y KTB Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '종합채권', '지표': 'KBP 종합지수', '현재값': '188.3', '1D': -0.05, '1W': -0.22, '1M': -1.51, '3M': 0.65, '6M': 1.80, '1Y': 3.50, 'YTD': -1.51, 'Source': 'Bloomberg', 'dataseries': 'TOT RETURN INDEX NET DVDS', 'dataset_name': 'KAP 종합채권 총수익 지수(AA- 이상)', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '지수-미국', '소분류': '종합채권', '지표': 'Barclays US Agg. Bond', '현재값': '2,180.5', '1D': -0.01, '1W': -0.05, '1M': -0.13, '3M': -0.85, '6M': 0.52, '1Y': 1.95, 'YTD': -0.13, 'Source': 'Factset', 'dataseries': 'FG Total Return Index (Unhedged)', 'dataset_name': 'Bloomberg US Aggregate Bond Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '투자등급', '지표': 'iBoxx Investment Grade', '현재값': '320.8', '1D': -0.02, '1W': -0.08, '1M': -0.21, '3M': -0.55, '6M': 0.80, '1Y': 2.30, 'YTD': -0.21, 'Source': 'Factset', 'dataseries': 'FG Return', 'dataset_name': 'iBoxx USD Liquid Investment Grade Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '하이일드', '지표': 'iBoxx High Yield', '현재값': '285.1', '1D': 0.05, '1W': 0.15, '1M': 0.54, '3M': 1.20, '6M': 2.85, '1Y': 5.80, 'YTD': 0.54, 'Source': 'Factset', 'dataseries': 'FG Return', 'dataset_name': 'iBoxx USD Liquid High Yield Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '지수-신흥시장', '소분류': '달러표시국채', '지표': 'JP Morgan EM Bond', '현재값': '880.5', '1D': 0.03, '1W': 0.10, '1M': 0.36, '3M': -0.25, '6M': 1.50, '1Y': 3.85, 'YTD': 0.36, 'Source': 'Bloomberg', 'dataseries': 'TOT RETURN INDEX NET DVDS', 'dataset_name': 'J.P. Morgan EMBI Global Core Index', '최근기준일': '2026-01-31'},
        # === 채권 - 금리 (bp 단위) ===
        {'대분류': '', '중분류': '금리-국내', '소분류': '국채', '지표': '국고채 3Y', '현재값': '2.65%', '1D': -1, '1W': -3, '1M': -8, '3M': 15, '6M': -25, '1Y': -42, 'YTD': -8, 'Source': 'Factset', 'dataseries': 'FG Yield (YTM)', 'dataset_name': 'KR Treasury 5Y', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': '국고채 10Y', '현재값': '2.85%', '1D': -1, '1W': -2, '1M': -3, '3M': 12, '6M': -18, '1Y': -35, 'YTD': -3, 'Source': 'Factset', 'dataseries': 'FG Yield (YTM)', 'dataset_name': 'KR Treasury 10Y', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '금리-미국', '소분류': '국채', '지표': 'US Treasury 2Y', '현재값': '4.15%', '1D': -2, '1W': -5, '1M': -15, '3M': -8, '6M': -45, '1Y': -72, 'YTD': -15, 'Source': 'Factset', 'dataseries': 'FG Yield (YTM)', 'dataset_name': 'Treasury 2Y', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'US Treasury 10Y', '현재값': '4.25%', '1D': -1, '1W': -4, '1M': -12, '3M': 5, '6M': -30, '1Y': -55, 'YTD': -12, 'Source': 'Factset', 'dataseries': 'FG Yield (YTM)', 'dataset_name': 'Treasury 10Y', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '금리-기준금리', '소분류': '정책금리', '지표': '한국 기준금리', '현재값': '3.00%', '1D': 0, '1W': 0, '1M': 0, '3M': -25, '6M': -50, '1Y': -50, 'YTD': 0, 'Source': 'Factset', 'dataseries': 'Interest Rate (Short Term)', 'dataset_name': 'KR Macro Data', '최근기준일': '2026-01-24'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': '미국 기준금리', '현재값': '4.50%', '1D': 0, '1W': 0, '1M': 0, '3M': 0, '6M': -25, '1Y': -75, 'YTD': 0, 'Source': 'Factset', 'dataseries': 'Interest Rate (Short Term)', 'dataset_name': 'US Macro Data', '최근기준일': '2026-01-29'},
        # === 채권 - 스프레드 (bp 단위) ===
        {'대분류': '', '중분류': '스프레드-크레딧', '소분류': '', '지표': 'US IG Spread', '현재값': '85bp', '1D': -1, '1W': -2, '1M': -5, '3M': -12, '6M': -18, '1Y': -25, 'YTD': -5, 'Source': 'Factset', 'dataseries': 'FG Yield (YTM)', 'dataset_name': 'iBoxx USD Liquid Investment Grade Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'US HY Spread', '현재값': '305bp', '1D': -2, '1W': -5, '1M': -12, '3M': -25, '6M': -35, '1Y': -55, 'YTD': -12, 'Source': 'Factset', 'dataseries': 'FG Yield (YTM)', 'dataset_name': 'ICE BofA US High Yield Constrained Index', '최근기준일': '2026-01-31'},
        # === FX (% 단위) ===
        {'대분류': 'FX', '중분류': '주요환율', '소분류': '달러', '지표': 'USD/KRW', '현재값': '1,432.5', '1D': 0.12, '1W': 0.35, '1M': 1.15, '3M': 2.80, '6M': 4.50, '1Y': 6.20, 'YTD': 1.15, 'Source': 'Bloomberg', 'dataseries': 'PX_LAST', 'dataset_name': 'USD-KRW', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'DXY', '현재값': '104.2', '1D': 0.08, '1W': 0.25, '1M': 0.82, '3M': 1.50, '6M': 3.20, '1Y': 4.80, 'YTD': 0.82, 'Source': 'Bloomberg', 'dataseries': 'PX_LAST', 'dataset_name': 'US Dollar Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '유로', '지표': 'EUR/USD', '현재값': '1.0815', '1D': -0.05, '1W': -0.18, '1M': -0.65, '3M': -1.20, '6M': -2.80, '1Y': -4.50, 'YTD': -0.65, 'Source': 'Bloomberg', 'dataseries': 'PX_LAST', 'dataset_name': 'EURUSD', '최근기준일': '2026-01-31'},
        # === 원자재 (% 단위) ===
        {'대분류': '원자재', '중분류': '에너지', '소분류': '원유', '지표': 'WTI', '현재값': '$72.1', '1D': -0.35, '1W': -0.85, '1M': -1.52, '3M': -5.20, '6M': -8.50, '1Y': -12.30, 'YTD': -1.52, 'Source': 'Factset', 'dataseries': 'FG Price', 'dataset_name': 'Crude Oil WTI NYM $/bbl', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '귀금속', '소분류': '', '지표': 'Gold', '현재값': '$2,850', '1D': 0.25, '1W': 0.80, '1M': 3.21, '3M': 5.50, '6M': 12.80, '1Y': 18.50, 'YTD': 3.21, 'Source': 'Factset', 'dataseries': 'FG Price', 'dataset_name': 'Gold NYM $/ozt', '최근기준일': '2026-01-31'},
        # === 변동성 (포인트 단위) ===
        {'대분류': '변동성', '중분류': '주식', '소분류': '', '지표': 'VIX', '현재값': '14.5', '1D': -0.35, '1W': -0.80, '1M': -2.30, '3M': -3.50, '6M': -5.20, '1Y': -8.50, 'YTD': -2.30, 'Source': 'Bloomberg', 'dataseries': 'PX_LAST', 'dataset_name': 'VIX Index', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '채권', '소분류': '', '지표': 'MOVE', '현재값': '98.3', '1D': -0.50, '1W': -1.20, '1M': -5.20, '3M': -8.50, '6M': -12.30, '1Y': -18.50, 'YTD': -5.20, 'Source': 'Bloomberg', 'dataseries': 'PX_LAST', 'dataset_name': 'MOVE Index', '최근기준일': '2026-01-30'},
        # === 경제지표 (%p 단위) ===
        {'대분류': '경제지표', '중분류': '물가', '소분류': '한국', '지표': 'CPI (YoY)', '현재값': '2.3%', '1D': 0.0, '1W': 0.0, '1M': -0.1, '3M': -0.3, '6M': -0.5, '1Y': -0.8, 'YTD': -0.1, 'Source': 'Factset', 'dataseries': 'CPI Inflation (%Chg YoY)', 'dataset_name': 'KR Macro Data', '최근기준일': '2026-01-05'},
        {'대분류': '', '중분류': '', '소분류': '미국', '지표': 'CPI (YoY)', '현재값': '2.9%', '1D': 0.0, '1W': 0.0, '1M': -0.2, '3M': -0.4, '6M': -0.6, '1Y': -1.0, 'YTD': -0.2, 'Source': 'Factset', 'dataseries': 'CPI Inflation (%Chg YoY)', 'dataset_name': 'US Macro Data', '최근기준일': '2026-01-15'},
    ])

    # 비수익률 행 식별 (금리/스프레드/변동성/경제지표): bp/포인트/%p 단위
    _env_ff = macro_env_data.copy()
    _env_ff['_대분류'] = _env_ff['대분류'].replace('', np.nan).ffill()
    _env_ff['_중분류'] = _env_ff['중분류'].replace('', np.nan).ffill()
    _is_bp_row = _env_ff['_중분류'].str.contains('금리|스프레드', na=False)
    _is_vol_row = _env_ff['_대분류'] == '변동성'
    _is_econ_row = _env_ff['_대분류'] == '경제지표'

    period_cols = ['1D', '1W', '1M', '3M', '6M', '1Y', 'YTD']

    # 원화환산: 해외 자산(국내주식/국내채권/경제지표 제외)에 +1.5% 가산 (mockup)
    _domestic_cats = {'국내', '지수-국내', '금리-국내', '금리-기준금리'}
    _non_fx_cats = {'변동성', '경제지표'}
    _is_domestic = _env_ff['_중분류'].isin(_domestic_cats) | _env_ff['_대분류'].isin(_non_fx_cats)
    _is_non_return = _is_bp_row | _is_vol_row | _is_econ_row

    if env_krw_toggle:
        macro_env_data_active = macro_env_data.copy()
        for col in period_cols:
            macro_env_data_active.loc[~_is_domestic & ~_is_non_return, col] = \
                macro_env_data.loc[~_is_domestic & ~_is_non_return, col] + 1.5
    else:
        macro_env_data_active = macro_env_data

    # 행별 유형 태그 칼럼 추가 (포맷/스타일링 용)
    _row_type = pd.Series('return', index=macro_env_data.index)
    _row_type[_is_bp_row] = 'bp'
    _row_type[_is_vol_row] = 'vol'
    _row_type[_is_econ_row] = 'econ'

    def _make_env_formatter(row_types, src_data):
        """행별 유형에 맞는 포맷터 dict 생성"""
        def _fmt(val, rtype):
            if pd.isna(val):
                return ''
            v = float(val)
            if rtype == 'bp':
                return '0bp' if v == 0 else (f'{v:+.0f}bp' if abs(v) >= 1 else f'{v:+.1f}bp')
            if rtype == 'vol':
                return f'{v:+.2f}' if v != 0 else '0.00'
            if rtype == 'econ':
                return f'{v:+.1f}%p' if v != 0 else '0.0%p'
            return f'{v:+.2f}%' if v != 0 else '0.00%'
        # 포맷된 문자열 DataFrame 생성 (표시 전용)
        fmt_df = pd.DataFrame(index=src_data.index, columns=period_cols)
        for idx in src_data.index:
            rt = row_types.iloc[idx]
            for col in period_cols:
                fmt_df.at[idx, col] = _fmt(src_data.at[idx, col], rt)
        return fmt_df

    _fmt_df = _make_env_formatter(_row_type, macro_env_data_active)

    # 표시용 DataFrame: 숫자 칼럼은 포맷된 문자열로 교체
    macro_env_display = macro_env_data_active.copy()
    for col in period_cols:
        macro_env_display[col] = _fmt_df[col]

    def style_env_period(val):
        """기간 칼럼 텍스트 색상: 음수 파랑, 양수 빨강"""
        if isinstance(val, str):
            stripped = val.replace('%', '').replace('bp', '').replace('%p', '').strip()
            try:
                v = float(stripped)
                if v < 0:
                    return 'color: #636EFA'
                elif v > 0:
                    return 'color: #EF553B'
            except (ValueError, TypeError):
                pass
        return ''

    def style_env_source(val):
        colors = {'Factset': '#e8f0fe', 'Bloomberg': '#fef7e0', 'KIS': '#e8f5e9'}
        bg = colors.get(val, '')
        return f'background-color: {bg}' if bg else ''

    env_height = max(200, 35 * len(macro_env_display) + 40)
    # 1. 기간 칼럼 텍스트 색상
    styled_env = macro_env_display.style.map(style_env_period, subset=period_cols)
    # 2. Source 배경색
    styled_env = styled_env.map(style_env_source, subset=['Source'])
    # 3. 기본 스타일
    styled_env = styled_env.set_properties(**{'font-size': '12px'})
    styled_env = styled_env.set_properties(subset=['대분류'], **{'font-weight': 'bold', 'background-color': '#f8f9fa'})
    styled_env = styled_env.set_properties(subset=['dataseries', 'dataset_name'], **{'font-size': '10px', 'color': '#888'})
    st.dataframe(styled_env, hide_index=True, use_container_width=True, height=env_height)
    st.caption("* Source: 데이터 출처 | dataseries/dataset_name: SCIP DB 매핑 정보 | 금리/스프레드: bp 단위, 변동성: 포인트, 경제지표: %p")

    st.markdown("---")

    # --- 벤치마크 수익률 히트맵 (고정 기간) (#8, #13) ---
    st.markdown("### 주요 벤치마크 기간수익률")
    bm_selected_periods = ['1M', '3M', 'YTD', '1Y', '3Y', '5Y']

    bm_names = ['MSCI ACWI', 'MSCI US', 'MSCI Korea', 'S&P500', 'KOSPI 200', 'NASDAQ 100',
                'SPYG', 'Russell 2000', 'MSCI EM', 'Barclays Global Agg', 'Bloomberg Commodity', 'Gold']
    heatmap_data = np.random.uniform(-5, 15, (len(bm_names), len(bm_selected_periods)))
    heatmap_df = pd.DataFrame(heatmap_data, index=bm_names, columns=bm_selected_periods)

    pastel_colorscale = [
        [0.0, '#f8d7da'], [0.25, '#fef3cd'], [0.5, '#fff9e6'],
        [0.75, '#d4edda'], [1.0, '#c3e6cb']
    ]
    fig_hm = px.imshow(heatmap_df, text_auto='.1f', color_continuous_scale=pastel_colorscale,
                        aspect='auto', labels=dict(color='수익률(%)'))
    fig_hm.update_layout(height=420, margin=dict(t=20, b=20, l=150),
                          font=dict(size=12))
    fig_hm.update_traces(textfont=dict(size=11, color='#333'))
    st.plotly_chart(fig_hm, use_container_width=True)

    st.markdown("---")



# ============================================================
# Tab 6: 운용보고
# ============================================================

with tabs[5]:
    st.markdown("#### 운용보고서")

    # #9: 보고서 드롭다운 (상단 배치)
    rpt_top1, rpt_top2 = st.columns([2, 2])
    with rpt_top1:
        reports = ['2026년 1월 월간', '2025년 4분기', '2025년 12월 월간', '2025년 11월 월간', '2025년 3분기']
        selected_report = st.selectbox("보고서 선택", reports, key='report_select')
    with rpt_top2:
        # 보고 기간 결정
        report_periods = {
            '2026년 1월 월간': ('2025-12-31', '2026-01-31'),
            '2025년 4분기': ('2025-09-30', '2025-12-31'),
            '2025년 12월 월간': ('2025-11-30', '2025-12-31'),
            '2025년 11월 월간': ('2025-10-31', '2025-11-30'),
            '2025년 3분기': ('2025-06-30', '2025-09-30'),
        }
        rpt_start, rpt_end = report_periods[selected_report]
        st.markdown(f"**보고 기간**: {rpt_start} ~ {rpt_end}")

    st.markdown("---")

    # #10: 매크로 요약 - 펀드 보유 자산군 기반 관련 지표만 선별 표시
    rpt_env_title_col, rpt_env_toggle_col = st.columns([4, 1])
    with rpt_env_title_col:
        st.markdown(f"**1. 시장 환경** &nbsp; | &nbsp; {rpt_start} ~ {rpt_end}")
    with rpt_env_toggle_col:
        rpt_krw_toggle = st.toggle("원화환산", key='rpt_krw_toggle')

    # 전체 시장지표 데이터 (대분류/중분류/소분류 3단 계층 + Source)
    all_market_indicators = pd.DataFrame([
        {'대분류': '주식', '중분류': '국내', '소분류': '시장', '지표': 'KOSPI', '현재값': '2,685.3', '기간변동': '-1.23%', 'Source': 'Bloomberg', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'KOSDAQ', '현재값': '812.5', '기간변동': '+0.82%', 'Source': 'Bloomberg', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'KOSPI 200', '현재값': '368.9', '기간변동': '-0.95%', 'Source': 'Bloomberg', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '미국', '소분류': '시장', '지표': 'S&P 500', '현재값': '6,025.1', '기간변동': '+2.31%', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'NASDAQ 100', '현재값': '21,350.8', '기간변동': '+3.12%', 'Source': 'Bloomberg', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '성장', '지표': 'SPYG', '현재값': '82.3', '기간변동': '+3.55%', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '중소형', '지표': 'Russell 2000', '현재값': '2,280.5', '기간변동': '+1.05%', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '글로벌', '소분류': '', '지표': 'MSCI ACWI', '현재값': '812.5', '기간변동': '+1.85%', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '신흥시장', '소분류': '', '지표': 'MSCI EM', '현재값': '1,085.3', '기간변동': '+2.45%', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '채권', '중분류': '국내금리', '소분류': '국채', '지표': '국고채 3Y', '현재값': '2.65%', '기간변동': '-8bp', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': '국고채 10Y', '현재값': '2.85%', '기간변동': '-3bp', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '미국금리', '소분류': '국채', '지표': 'US Treasury 2Y', '현재값': '4.15%', '기간변동': '-15bp', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'US Treasury 10Y', '현재값': '4.25%', '기간변동': '-12bp', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '기준금리', '소분류': '정책금리', '지표': '한국 기준금리', '현재값': '3.00%', '기간변동': '0bp', 'Source': 'Factset', '최근기준일': '2026-01-24'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': '미국 기준금리', '현재값': '4.50%', '기간변동': '0bp', 'Source': 'Factset', '최근기준일': '2026-01-29'},
        {'대분류': '', '중분류': '크레딧', '소분류': '스프레드', '지표': 'US IG Spread', '현재값': '85bp', '기간변동': '-5bp', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'US HY Spread', '현재값': '305bp', '기간변동': '-12bp', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': 'FX', '중분류': '주요환율', '소분류': '달러', '지표': 'USD/KRW', '현재값': '1,432.5', '기간변동': '+1.15%', 'Source': 'Bloomberg', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '', '지표': 'DXY', '현재값': '104.2', '기간변동': '+0.82%', 'Source': 'Bloomberg', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '', '소분류': '유로', '지표': 'EUR/USD', '현재값': '1.0815', '기간변동': '-0.65%', 'Source': 'Bloomberg', '최근기준일': '2026-01-31'},
        {'대분류': '원자재', '중분류': '에너지', '소분류': '원유', '지표': 'WTI', '현재값': '$72.1', '기간변동': '-1.52%', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '귀금속', '소분류': '', '지표': 'Gold', '현재값': '$2,850', '기간변동': '+3.21%', 'Source': 'Factset', '최근기준일': '2026-01-31'},
        {'대분류': '변동성', '중분류': '주식', '소분류': '', '지표': 'VIX', '현재값': '14.5', '기간변동': '-2.30', 'Source': 'Bloomberg', '최근기준일': '2026-01-31'},
        {'대분류': '', '중분류': '채권', '소분류': '', '지표': 'MOVE', '현재값': '98.3', '기간변동': '-5.20', 'Source': 'Bloomberg', '최근기준일': '2026-01-30'},
        {'대분류': '경제지표', '중분류': '물가', '소분류': '한국', '지표': 'CPI (YoY)', '현재값': '2.3%', '기간변동': '-0.1%p', 'Source': 'Factset', '최근기준일': '2026-01-05'},
        {'대분류': '', '중분류': '', '소분류': '미국', '지표': 'CPI (YoY)', '현재값': '2.9%', '기간변동': '-0.2%p', 'Source': 'Factset', '최근기준일': '2026-01-15'},
    ])

    # 현재 펀드 보유 자산군에 따라 관련 지표만 필터링
    fund_asset_classes = set(SAMPLE_HOLDINGS_DETAIL['자산군'].unique())  # TODO: DB 연동 시 selected_fund 기반 조회
    relevant_cats = set(ALWAYS_SHOW_INDICATORS)
    for ac in fund_asset_classes:
        if ac in ASSET_TO_MARKET_INDICATORS:
            for cat in ASSET_TO_MARKET_INDICATORS[ac]:
                relevant_cats.add(cat)

    # 대분류가 빈 문자열인 행은 이전 대분류의 중분류를 참조 → forward fill 후 필터
    _mkt_ff = all_market_indicators.copy()
    _mkt_ff['_대분류'] = _mkt_ff['대분류'].replace('', np.nan).ffill()
    _mkt_ff['_중분류'] = _mkt_ff['중분류'].replace('', np.nan).ffill()
    _mkt_ff['_match'] = _mkt_ff.apply(lambda r: (r['_대분류'], r['_중분류']) in relevant_cats, axis=1)
    market_indicators = all_market_indicators[_mkt_ff['_match']].reset_index(drop=True)

    n_filtered = len(all_market_indicators) - len(market_indicators)
    filter_note = f" (펀드 보유 자산군 기반 {len(market_indicators)}개 선별)" if n_filtered > 0 else ""

    # 원화환산 적용 (mockup: 해외 자산 수익률에 +1.5% 가산)
    if rpt_krw_toggle:
        _mkt_disp_ff = market_indicators.copy()
        _mkt_disp_ff['_대분류'] = _mkt_disp_ff['대분류'].replace('', np.nan).ffill()
        _mkt_disp_ff['_중분류'] = _mkt_disp_ff['중분류'].replace('', np.nan).ffill()
        _rpt_domestic = {'국내', '국내금리', '기준금리'}
        _rpt_non_pct = {'변동성', '경제지표'}
        market_indicators_active = market_indicators.copy()
        for idx in market_indicators_active.index:
            mid = _mkt_disp_ff.at[idx, '_중분류']
            cat = _mkt_disp_ff.at[idx, '_대분류']
            val_str = market_indicators_active.at[idx, '기간변동']
            if mid in _rpt_domestic or cat in _rpt_non_pct:
                continue
            # %로 끝나는 수익률만 변환 (bp, 포인트 등은 제외)
            if isinstance(val_str, str) and val_str.endswith('%') and 'bp' not in val_str and '%p' not in val_str:
                cleaned = val_str.replace('%', '').replace('+', '')
                try:
                    v = float(cleaned) + 1.5
                    market_indicators_active.at[idx, '기간변동'] = f'{v:+.2f}%'
                except ValueError:
                    pass
    else:
        market_indicators_active = market_indicators

    def style_change(val):
        if isinstance(val, str) and val.startswith('-'):
            return 'color: #636EFA'
        elif isinstance(val, str) and val.startswith('+'):
            return 'color: #EF553B'
        return ''

    def style_mkt_source(val):
        colors = {'Factset': '#e8f0fe', 'Bloomberg': '#fef7e0'}
        bg = colors.get(val, '')
        return f'background-color: {bg}' if bg else ''

    mkt_height = max(200, 35 * len(market_indicators_active) + 40)
    styled_mkt = market_indicators_active.style.map(style_change, subset=['기간변동'])
    styled_mkt = styled_mkt.map(style_mkt_source, subset=['Source'])
    styled_mkt = styled_mkt.set_properties(**{'font-size': '12px'})
    styled_mkt = styled_mkt.set_properties(subset=['대분류'], **{'font-weight': 'bold', 'background-color': '#f8f9fa'})
    st.dataframe(styled_mkt, hide_index=True, use_container_width=True, height=mkt_height)

    st.caption(f"* 해당 펀드 보유 자산군 관련 지표만 표시{filter_note}. Source: 데이터 출처")

    st.markdown("""
    - **글로벌 주식**: S&P500 +2.3%, NASDAQ +3.1%. AI 관련주 중심 강세 지속
    - **금리**: 미국 10년 금리 4.25%로 하락. 인플레이션 둔화 시그널에 금리 인하 기대 유지
    - **환율**: 원달러 1,432원. 달러 강세 기조 속 원화 약세 지속
    - **원자재**: 금 가격 사상 최고치 경신. WTI $72 수준 안정
    """)

    # 성과 요약 섹션
    st.markdown("---")
    st.markdown("**2. 운용 성과**")

    perf_rpt = pd.DataFrame({
        '구분': ['포트폴리오', 'BM', '초과수익'],
        f'{selected_report}': ['+1.23%', '+0.98%', '+0.25%p'],
        'YTD': ['+1.23%', '+0.98%', '+0.25%p'],
        '설정이후': ['+15.85%', '+13.20%', '+2.65%p'],
    })
    st.dataframe(perf_rpt, hide_index=True, use_container_width=True)

    st.markdown("""
    - **Brinson 분석**: Selection Effect (+0.82%p)가 주요 초과수익 원인
    - **해외주식**: QQQ, SPY 기여 +0.73%p. AI/반도체 섹터 강세 수혜
    - **국내채권**: 듀레이션 확대 (+3.2Y→3.5Y) 기여 +0.10%p
    """)

    # #12: 자산군별 Brinson + 매크로 매핑 코멘트 (배분효과 + 선별효과 코멘트 분리)
    st.markdown("**2-1. 자산군별 운용성과 & 시장환경 매핑**")
    brinson_macro_df = pd.DataFrame({
        '자산군': ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자'],
        'Alloc.': ['+0.01%', '-0.03%', '+0.05%', '+0.02%', '+0.04%'],
        'Select.': ['+0.15%', '+0.63%', '+0.10%', '-0.02%', '+0.08%'],
        'Cross': ['+0.00%', '-0.01%', '+0.01%', '+0.00%', '+0.01%'],
        '합계': ['+0.16%', '+0.59%', '+0.16%', '+0.00%', '+0.13%'],
        '주요 매크로 요인': [
            'KOSPI +22.5% (반도체 업황 호조)',
            'S&P500 +2.3%, NASDAQ +3.1% (AI/빅테크)',
            '국고10Y 2.85% (-3bp, 금리인하 기대)',
            'US10Y 4.25% (-12bp, 인플레 둔화)',
            '맥쿼리인프라 +3.4% (인프라 투자 확대)'
        ],
        '배분효과 코멘트': [
            '(+0.01%p) BM 대비 국내주식 소폭 확대. 반도체 랠리 수혜 제한적',
            '(-0.03%p) 해외주식 비중 축소. AI 강세장 대비 비중 부족',
            '(+0.05%p) 채권 비중 확대. 듀레이션 롱 전략 유효',
            '(+0.02%p) 해외채권 비중 확대. 금리 하락 수혜',
            '(+0.04%p) 대체투자 비중 확대. 인프라 편입 효과'
        ],
        '선별효과 코멘트': [
            '(+0.15%p) 삼성전자/SK하이닉스 비중확대 성공. AI 반도체 수출 호조',
            '(+0.63%p) QQQ/SPY 중심 AI섹터 수혜 극대화. NVDA, META 실적 호조',
            '(+0.10%p) 국고채 30년물 롱 듀레이션 전환 적시 실행',
            '(-0.02%p) IG 스프레드 축소 미활용. 회사채 편입 기회 미포착',
            '(+0.08%p) 맥쿼리인프라 적시 편입. 배당수익률 5.2% 확보'
        ]
    })
    st.dataframe(brinson_macro_df, hide_index=True, use_container_width=True)

    st.markdown("**2-2. 종목별 운용성과 하이라이트**")
    sec_macro_df = pd.DataFrame({
        '종목': ['QQQ', 'SPY', 'KODEX 200', '국고03750-2603', 'VWO', '맥쿼리인프라'],
        '수익률': ['+7.21%', '+5.12%', '+2.31%', '+0.82%', '-1.30%', '+3.45%'],
        '기여도': ['+0.73%', '+0.63%', '+0.24%', '+0.10%', '-0.06%', '+0.17%'],
        '매크로 요인': [
            'NASDAQ +3.1%, AI 인프라 투자 가속화',
            'S&P500 +2.3%, 미국 GDP +2.8%',
            'KOSPI +22.5%, 반도체 수출 +31%',
            '국고채 금리 -3bp, 한은 완화적 기조',
            'EM -1.3%, 중국 PMI 49.1',
            '인프라 투자 확대 정책, 금리인하 수혜'
        ],
        '코멘트': [
            'NVDA, META 실적 호조에 AI 섹터 강세. 비중확대 적중',
            '미국 경기 연착륙 유지. 대형주 안정적 성과',
            '반도체 수출 증가, 국내 시장 탄력 회복',
            '듀레이션 확대(3.2Y→3.5Y) 전략 유효',
            '위안화 약세 지속. 비중축소 검토 필요',
            '안정적 배당수익률 5.2%, CAPEX 확대 수혜'
        ]
    })
    st.dataframe(sec_macro_df, hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("**3. Total Return Decomposition (주요 벤치마크)**")
    decomp_rpt = pd.DataFrame({
        '지수': ['MSCI ACWI', 'MSCI US', 'MSCI EM', 'S&P500'],
        'PE Growth': ['+1.5%', '+2.1%', '-0.8%', '+2.3%'],
        'EPS Growth': ['+3.2%', '+4.1%', '+1.5%', '+4.5%'],
        'Other': ['+0.5%', '+0.3%', '+0.8%', '+0.2%'],
        'Total Return': ['+5.2%', '+6.5%', '+1.5%', '+7.0%'],
    })
    st.dataframe(decomp_rpt, hide_index=True, use_container_width=True)

    st.markdown("""
    - 미국 시장: EPS 성장 주도의 건전한 상승. PE 확장도 기여
    - EM 시장: PE 수축에도 불구, EPS 성장이 양(+)의 수익률 견인
    """)

    st.markdown("---")
    st.markdown("**4. 주요 시장 이슈 & 뉴스 매핑**")
    st.caption("보고 기간 중 주요 이슈를 자산군/지표별로 매핑하여 운용성과 코멘트의 근거로 활용")

    news_data = pd.DataFrame([
        {'날짜': '2026-01-29', '대분류': '주식', '관련지표': 'S&P 500, NASDAQ',
         '이슈': 'FOMC 금리 동결 (4.25~4.50%). 파월 "인플레 둔화 진전 확인" 발언',
         '출처': 'Reuters', 'URL': 'https://www.reuters.com/'},
        {'날짜': '2026-01-28', '대분류': '주식', '관련지표': 'NASDAQ, SPYG',
         '이슈': 'DeepSeek R1 공개로 AI 반도체주 급락. NVDA -17%, 필라델피아 반도체 -9.2%',
         '출처': 'Bloomberg', 'URL': 'https://www.bloomberg.com/'},
        {'날짜': '2026-01-24', '대분류': '채권', '관련지표': '한국 기준금리',
         '이슈': '한은 기준금리 3.00% 동결. 금통위원 2인 인하소수의견',
         '출처': '한국은행', 'URL': 'https://www.bok.or.kr/'},
        {'날짜': '2026-01-15', '대분류': '경제지표', '관련지표': 'US CPI',
         '이슈': '미국 12월 CPI 2.9% (YoY), 전월비 +0.4%. 에너지 가격 반등',
         '출처': 'BLS', 'URL': 'https://www.bls.gov/'},
        {'날짜': '2026-01-10', '대분류': 'FX', '관련지표': 'USD/KRW',
         '이슈': '원/달러 1,450원 돌파 후 하락. 수출 호조 + 외국인 주식 순매수',
         '출처': '연합뉴스', 'URL': 'https://www.yna.co.kr/'},
        {'날짜': '2026-01-08', '대분류': '원자재', '관련지표': 'Gold',
         '이슈': '금 가격 $2,850 사상 최고치. 중앙은행 금 매입 + 지정학 리스크',
         '출처': 'Reuters', 'URL': 'https://www.reuters.com/'},
    ])

    def make_url_link(row):
        return f'<a href="{row["URL"]}" target="_blank">{row["출처"]}</a>'
    news_data['출처(링크)'] = news_data.apply(make_url_link, axis=1)
    news_display = news_data[['날짜', '대분류', '관련지표', '이슈', '출처(링크)']].copy()
    st.markdown(news_display.to_html(escape=False, index=False), unsafe_allow_html=True)

    with st.expander("뉴스 매핑 활용 방안 (향후 구현)"):
        st.markdown("""
        **목표**: 보고 기간 중 자산군/지표 관련 주요 뉴스를 자동 수집하여 운용 코멘트 작성에 활용

        **구현 계획**:
        1. **뉴스 수집**: 보고 기간 내 주요 언론사(Reuters, Bloomberg, 연합뉴스 등) 기사 크롤링
        2. **자산군 매핑**: NLP 기반 기사 → 자산군/지표 자동 분류
        3. **코멘트 병합**: 시장환경 테이블의 '기간변동' + 관련 뉴스 → 운용성과 코멘트 초안 자동 생성
        4. **출처 URL**: 각 코멘트에 근거 뉴스 URL을 footnote로 첨부

        **데이터 흐름**:
        ```
        뉴스 API/크롤링 → 자산군 자동분류 → DB 저장(SCIP or solution)
            → 보고 기간 필터 → 시장환경 + 벤치마크 수익률 매핑
            → LLM 기반 코멘트 초안 생성 → 운용역 검토/수정 → 보고서 반영
        ```

        **코멘트 생성 예시**:
        > 해외주식 선별효과 (+0.63%p): 1월 FOMC 금리 동결 후 S&P500 +2.3% 상승.
        > 다만 DeepSeek R1 공개(1/28)로 AI 반도체주 급락, NASDAQ -4.1%.
        > QQQ/SPY 중심 포지션이 AI 섹터 급락 전 수혜를 극대화.
        > [Reuters](url), [Bloomberg](url)
        """)

    st.markdown("---")
    st.markdown("**5. 운용계획 & 리스크**")
    rc1, rc2 = st.columns(2)
    with rc1:
        st.markdown("**운용 방향**")
        st.markdown("""
        - **국내주식**: KOSPI 2,700~2,900 밴드
        - **해외주식**: 미국 기술주 중심 유지
        - **채권**: 듀레이션 확대 전환
        - **대체투자**: 인프라 추가 편입 검토
        """)
    with rc2:
        st.markdown("**리스크 요인**")
        st.markdown("""
        - 미국 인플레이션 재가속 가능성
        - 글로벌 지정학 리스크 (중동/대만해협)
        - 일본 BOJ 금리 인상 → 엔 캐리 청산 우려
        - 원달러 1,450원 돌파 시 환헤지 조정 필요
        """)

    st.markdown("---")
    st.download_button(
        "보고서 다운로드 (Excel 형식, 준비중)",
        data=b"placeholder",
        file_name=f"DB_OCIO_Report_{selected_report.replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        disabled=True
    )


# ============================================================
# Tab 6: Admin (admin only)
# ============================================================

if st.session_state.user_role == "admin" and len(tabs) > 6:
    with tabs[6]:
        st.markdown("#### 전체 펀드 운용 현황")

        # DB 펀드 요약 로드 (fallback: FUND_META 기반 mockup)
        _tab6_db = False
        if DB_CONNECTED:
            try:
                _summary_df = cached_load_fund_summary(FUND_LIST)
                if not _summary_df.empty:
                    _tab6_db = True
            except Exception as _e:
                st.toast(f"Admin DB 오류, 목업 사용: {_e}", icon="⚠️")

        if _tab6_db:
            st.caption(f"📡 DB 실데이터 | 기준일: {_summary_df['기준일자'].max().strftime('%Y-%m-%d')}")
            all_funds = pd.DataFrame()
            all_funds['펀드코드'] = _summary_df['FUND_CD']
            all_funds['펀드명'] = _summary_df['FUND_CD'].map(
                lambda x: FUND_META.get(x, {}).get('short', x)
            )
            all_funds['AUM(억)'] = _summary_df['AUM_억'].round(1)
            all_funds['기준가'] = _summary_df['MOD_STPR'].round(2)
            all_funds['전일수익률(%)'] = (_summary_df['DD1_ERN_RT'] * 100).round(4) if 'DD1_ERN_RT' in _summary_df.columns else 0.0
            all_funds['그룹'] = _summary_df['FUND_CD'].map(
                lambda x: FUND_META.get(x, {}).get('group', '기타')
            )
            all_funds['MP'] = _summary_df['FUND_CD'].map(
                lambda x: 'O' if FUND_META.get(x, {}).get('has_mp', False) else 'X'
            )
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
        st.dataframe(all_funds, hide_index=True, use_container_width=True, height=500)

        st.markdown("---")
        col_a1, col_a2 = st.columns(2)
        with col_a1:
            st.markdown("#### AUM 분포")
            fig_aum = px.treemap(all_funds, path=['그룹', '펀드명'], values='AUM(억)',
                                  color='AUM(억)', color_continuous_scale='Blues')
            fig_aum.update_layout(height=400, margin=dict(t=30, b=10))
            st.plotly_chart(fig_aum, use_container_width=True)

        with col_a2:
            st.markdown("#### 그룹별 AUM")
            group_aum = all_funds.groupby('그룹')['AUM(억)'].sum().sort_values(ascending=True)
            fig_group = go.Figure(go.Bar(
                x=group_aum.values, y=group_aum.index,
                orientation='h', marker_color='#636EFA',
                text=[f"{v:,.0f}억" for v in group_aum.values], textposition='outside'
            ))
            fig_group.update_layout(height=400, margin=dict(t=30, l=100), xaxis_title='AUM (억원)')
            st.plotly_chart(fig_group, use_container_width=True)
