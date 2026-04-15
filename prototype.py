# === DB OCIO Webview -- UI Prototype v4 (모듈화) ===
# 탭별 모듈 분리: tabs/overview.py, tabs/holdings.py, tabs/brinson.py, tabs/macro.py, tabs/admin.py
# 실행: streamlit run prototype.py

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys, os

# modules/ 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.funds import FUND_BM, FUND_LIST, FUND_MP_MAPPING, FUND_MP_DIRECT
from modules.data_loader import (
    load_fund_nav, load_fund_nav_with_aum, load_fund_holdings_classified,
    load_fund_holdings_lookthrough,
    load_fund_holdings_history, load_fund_summary, load_scip_bm_prices,
    load_composite_bm_prices, load_dt_bm_prices, load_mp_weights_8class,
    load_vp_weights_8class, load_vp_nav, load_vp_rebal_date,
    load_all_fund_data, parse_data_blob,
    compute_brinson_attribution, compute_single_port_pa,
    load_macro_timeseries, load_macro_period_returns,
    load_holdings_history_8class,
    _FUND_INCEPTION_BASE,
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
    try:
        return load_fund_nav_with_aum(fund_code, start_date)
    except Exception:
        from modules.snapshot_fallback import load_nav_fallback
        return load_nav_fallback(fund_code, start_date)

@st.cache_data(ttl=600)
def cached_load_bm_prices(dataset_id, dataseries_id, start_date=None, currency=None):
    return load_scip_bm_prices(dataset_id, dataseries_id, start_date, currency)

@st.cache_data(ttl=600)
def cached_load_holdings(fund_code, date=None):
    try:
        return load_fund_holdings_classified(fund_code, date)
    except Exception:
        from modules.snapshot_fallback import load_holdings_fallback
        return load_holdings_fallback(fund_code)

@st.cache_data(ttl=600)
def cached_load_holdings_lookthrough(fund_code, date=None):
    try:
        return load_fund_holdings_lookthrough(fund_code, date)
    except Exception:
        from modules.snapshot_fallback import load_holdings_fallback
        return load_holdings_fallback(fund_code)

@st.cache_data(ttl=600)
def cached_load_holdings_history(fund_code, start_date=None):
    return load_fund_holdings_history(fund_code, start_date)

@st.cache_data(ttl=600)
def cached_load_fund_summary(fund_codes):
    try:
        return load_fund_summary(fund_codes)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=600)
def cached_load_all_fund_data(fund_codes_tuple, start_date=None):
    return load_all_fund_data(list(fund_codes_tuple), start_date)

@st.cache_data(ttl=600)
def cached_load_composite_bm(components_json, start_date=None):
    import json
    components = json.loads(components_json)
    return load_composite_bm_prices(components, start_date)

@st.cache_data(ttl=600)
def cached_load_dt_bm(fund_code, start_date=None):
    return load_dt_bm_prices(fund_code, start_date)

@st.cache_data(ttl=600)
def cached_load_mp_weights_8class(fund_desc, reference_date=None, cycle_phase=1):
    return load_mp_weights_8class(fund_desc, reference_date, cycle_phase)

@st.cache_data(ttl=600)
def cached_load_vp_weights_8class(fund_desc, reference_date=None, cycle_phase=1):
    return load_vp_weights_8class(fund_desc, reference_date, cycle_phase)

@st.cache_data(ttl=600)
def cached_load_vp_nav(fund_code, start_date=None):
    return load_vp_nav(fund_code, start_date)

@st.cache_data(ttl=600)
def cached_load_vp_rebal_date(fund_desc):
    return load_vp_rebal_date(fund_desc)

@st.cache_data(ttl=600)
def cached_compute_brinson(fund_code, start_date, end_date):
    return compute_brinson_attribution(fund_code, start_date, end_date)

@st.cache_data(ttl=600, show_spinner=False)
def cached_compute_single_port_pa(fund_code, start_date, end_date, fx_split=True, mapping_method='방법3'):
    try:
        return compute_single_port_pa(fund_code, start_date, end_date, fx_split, mapping_method)
    except Exception:
        from modules.snapshot_fallback import load_pa_fallback
        return load_pa_fallback(fund_code)

@st.cache_data(ttl=600)
def cached_load_macro_timeseries(keys_tuple=None, start_date='2017-01-01'):
    keys = list(keys_tuple) if keys_tuple else None
    return load_macro_timeseries(keys, start_date)

@st.cache_data(ttl=600)
def cached_load_macro_period_returns(macro_keys_tuple, start_date='2017-01-01'):
    macro_data = cached_load_macro_timeseries(macro_keys_tuple, start_date)
    return load_macro_period_returns(macro_data)

@st.cache_data(ttl=600)
def cached_load_holdings_history_8class(fund_code, start_date=None):
    return load_holdings_history_8class(fund_code, start_date)

# DB 접속 테스트
try:
    from modules.data_loader import get_connection
    _test_conn = get_connection('dt')
    _test_conn.close()
    DB_CONNECTED = True
except Exception:
    DB_CONNECTED = False

# DB 미연결 시 snapshot fallback 활성화
_SNAPSHOT_MODE = False
if not DB_CONNECTED:
    try:
        from modules.snapshot_fallback import has_snapshot
        _SNAPSHOT_MODE = has_snapshot('08K88')
        if _SNAPSHOT_MODE:
            DB_CONNECTED = True
    except ImportError:
        _SNAPSHOT_MODE = False

# ============================================================
# 펀드 메타 & 공통 설정
# ============================================================

FUND_META = {
    '07G04': {'name': 'OCIO알아서(채권혼합)(모)', 'short': 'OCIO채권혼합', 'aum': 1749.6, 'group': 'OCIO', 'has_mp': True},
    '07G03': {'name': '수익추구 모펀드', 'short': '수익추구모', 'aum': 888.2, 'group': '모펀드', 'has_mp': True},
    '07G02': {'name': '인컴추구 모펀드', 'short': '인컴추구모', 'aum': 883.4, 'group': '모펀드', 'has_mp': True},
    '08P22': {'name': 'OCIO알아서 프라임', 'short': 'OCIO프라임', 'aum': 815.9, 'group': 'OCIO', 'has_mp': True},
    '08K88': {'name': 'OCIO알아서 성장형', 'short': 'OCIO성장형', 'aum': 542.3, 'group': 'OCIO', 'has_mp': True},
    '08N33': {'name': 'OCIO알아서 베이직', 'short': 'OCIO베이직', 'aum': 241.1, 'group': 'OCIO', 'has_mp': True},
    '4JM12': {'name': '동부글로벌 Active', 'short': '동부Active', 'aum': 234.6, 'group': '외부위탁', 'has_mp': True},
    '2JM23': {'name': '오렌지라이프 자산배분B', 'short': '오렌지B', 'aum': 194.7, 'group': '외부위탁', 'has_mp': True},
    '08N81': {'name': 'OCIO알아서 액티브', 'short': 'OCIO액티브', 'aum': 188.7, 'group': 'OCIO', 'has_mp': True},
}

FUND_GROUPS = {
    '전체': list(FUND_META.keys()),
    'OCIO': ['07G04', '08N33', '08N81', '08P22'],
    '모펀드': ['07G02', '07G03'],
    '외부위탁': ['2JM23', '4JM12'],
}

ASSET_CLASSES = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', 'FX', '모펀드', '유동성']
ASSET_COLORS = {
    '국내주식': '#EF553B', '해외주식': '#636EFA', '국내채권': '#00CC96',
    '해외채권': '#AB63FA', '대체투자': '#FFA15A', 'FX': '#19D3F3',
    '모펀드': '#FF6692', '유동성': '#B6E880',
}
ASSET_CLASS_ORDER = {ac: i for i, ac in enumerate(ASSET_CLASSES)}

# 샘플 종목 데이터 (mockup fallback)
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
# 역할 선택 (admin / client)
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
            if st.button("Admin 으로 접속", width="stretch", type="primary"):
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
            if st.button("Client 로 접속", width="stretch"):
                st.session_state.logged_in = True
                st.session_state.user_role = "client"
                st.session_state.fund_access = list(FUND_META.keys())
                st.rerun()

    st.stop()


# ============================================================
# 상단: 사용자 정보 + 펀드 선택
# ============================================================

role_label = "Admin" if st.session_state.user_role == "admin" else "Client"
accessible = st.session_state.get('fund_access', list(FUND_META.keys()))

top1, top2, top3, top4, top5 = st.columns([2.5, 0.01, 1.5, 3.5, 1])

with top1:
    _DISPLAY_FUNDS = ['07G04', '08K88', '08N33', '08N81', '08P22', '2JM23', '4JM12']
    all_funds = [f for f in _DISPLAY_FUNDS if f in FUND_META]
    fund_labels = {k: f"{k}  {FUND_META[k].get('short', FUND_META[k].get('name','')[:20])}" for k in all_funds}
    # session_state에 이전 값이 남아있으면 새 옵션과 충돌하므로 제거
    _fund_key = "top_fund_sel"
    if _fund_key in st.session_state and st.session_state[_fund_key] not in all_funds:
        del st.session_state[_fund_key]
    default_fund_idx = all_funds.index('08K88') if '08K88' in all_funds else 0
    selected_fund = st.selectbox(
        "펀드 선택", options=all_funds, index=default_fund_idx,
        format_func=lambda x: fund_labels[x], label_visibility="collapsed",
        key=_fund_key
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
        st.write("")

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
# 탭 구성 + 공통 컨텍스트
# ============================================================

tab_names = ["Overview", "편입종목", "성과분석", "운용보고(펀드)", "운용보고(매크로)",
             "DB ALM 적합성", "퇴직연금 DB 현황", "Peer 비교"]
if st.session_state.user_role == "admin":
    tab_names += ["Admin(운용보고_매크로)", "Admin(운용보고_펀드)"]
tabs = st.tabs(tab_names)

# 캐시 함수 dict (탭 모듈에 전달)
cache = {
    'load_fund_nav': cached_load_fund_nav,
    'load_bm_prices': cached_load_bm_prices,
    'load_holdings': cached_load_holdings,
    'load_holdings_lookthrough': cached_load_holdings_lookthrough,
    'load_holdings_history': cached_load_holdings_history,
    'load_fund_summary': cached_load_fund_summary,
    'load_all_fund_data': cached_load_all_fund_data,
    'load_composite_bm': cached_load_composite_bm,
    'load_dt_bm': cached_load_dt_bm,
    'load_mp_weights_8class': cached_load_mp_weights_8class,
    'load_vp_weights_8class': cached_load_vp_weights_8class,
    'load_vp_nav': cached_load_vp_nav,
    'load_vp_rebal_date': cached_load_vp_rebal_date,
    'compute_brinson': cached_compute_brinson,
    'compute_single_port_pa': cached_compute_single_port_pa,
    'load_macro_timeseries': cached_load_macro_timeseries,
    'load_macro_period_returns': cached_load_macro_period_returns,
    'load_holdings_history_8class': cached_load_holdings_history_8class,
}

# 공통 컨텍스트 (각 탭 모듈에 전달)
ctx = {
    'selected_fund': selected_fund,
    'fund_info': fund_info,
    'lookthrough_on': lookthrough_on,
    'DB_CONNECTED': DB_CONNECTED,
    'FUND_BM': FUND_BM,
    'FUND_META': FUND_META,
    'FUND_LIST': FUND_LIST,
    'ASSET_CLASSES': ASSET_CLASSES,
    'ASSET_COLORS': ASSET_COLORS,
    'ASSET_CLASS_ORDER': ASSET_CLASS_ORDER,
    'SAMPLE_HOLDINGS_DETAIL': SAMPLE_HOLDINGS_DETAIL,
    'dates': dates,
    'cache': cache,
}

# ============================================================
# 탭 렌더링
# ============================================================

with tabs[0]:
    from tabs.overview import render as render_overview
    render_overview(ctx)

with tabs[1]:
    from tabs.holdings import render as render_holdings
    render_holdings(ctx)

with tabs[2]:
    from tabs.brinson import render as render_brinson
    render_brinson(ctx)

with tabs[3]:
    from tabs.report import render_pa as render_report_pa
    render_report_pa(ctx)

with tabs[4]:
    from tabs.report import render_macro as render_report_macro
    render_report_macro(ctx)

with tabs[5]:
    from tabs.db_alm import render as render_db_alm
    render_db_alm(ctx)

with tabs[6]:
    from tabs.db_bridge import render as render_db_bridge
    render_db_bridge(ctx)

with tabs[7]:
    from tabs.db_peer import render as render_db_peer
    render_db_peer(ctx)

if st.session_state.user_role == "admin" and len(tabs) > 8:
    with tabs[8]:
        from tabs.admin_macro import render as render_admin_macro
        render_admin_macro(ctx)
    with tabs[9]:
        from tabs.admin_fund import render as render_admin_fund
        render_admin_fund(ctx)
