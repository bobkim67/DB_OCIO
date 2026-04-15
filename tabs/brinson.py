# -*- coding: utf-8 -*-
"""Tab 3: 성과분석 (Brinson) — 3-Factor Attribution, 워터폴, 기여도"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

from modules.charts import make_nav, make_bm_nav
from config.funds import FUND_BM


def render(ctx):
    """Brinson PA 탭 렌더링. ctx: 공통 컨텍스트 dict"""
    selected_fund = ctx['selected_fund']
    fund_info = ctx['fund_info']
    DB_CONNECTED = ctx['DB_CONNECTED']
    FUND_BM_ctx = ctx['FUND_BM']
    FUND_META = ctx['FUND_META']
    ASSET_CLASSES = ctx['ASSET_CLASSES']
    ASSET_COLORS = ctx['ASSET_COLORS']
    ASSET_CLASS_ORDER = ctx['ASSET_CLASS_ORDER']
    SAMPLE_HOLDINGS_DETAIL = ctx['SAMPLE_HOLDINGS_DETAIL']
    cache = ctx['cache']
    dates = ctx['dates']

    st.markdown("")

    # 분석기간
    bc1, bc2 = st.columns([3, 1])
    with bc1:
        _ytd_start = datetime(datetime.now().year, 1, 1)
        _inception_str = FUND_META.get(selected_fund, {}).get('inception', '20220101')
        _inception_dt = datetime.strptime(_inception_str, '%Y%m%d')
        if _inception_dt.year == datetime.now().year:
            _ytd_start = _inception_dt
        _ytd_end = datetime.now() - timedelta(days=1)
        analysis_period = st.date_input("분석기간", value=(_ytd_start, _ytd_end),
                                         key='brinson_period')
    with bc2:
        pa_method = st.selectbox("자산군 분류", ["8분류", "5분류"], key='pa_method')

    pa_fx = st.toggle("FX 분리 (FX를 별도 자산군으로 분리하여 분석)", value=True, key='pa_fx')
    st.caption("ON: FX를 별도 자산군으로 분리 | OFF: FX 효과를 각 자산군에 포함")

    st.markdown("---")

    # --- PA 데이터: DB → fallback ---
    _brinson_db = False
    _brinson_result = None
    _brinson_fail_reason = ""
    _single_pa_result = None
    _single_pa_db = False

    if DB_CONNECTED and len(analysis_period) == 2:
        _pa_start = analysis_period[0].strftime('%Y%m%d')
        _pa_end = analysis_period[1].strftime('%Y%m%d')
        # 1) Brinson 3-Factor (기존)
        try:
            _brinson_result = cache['compute_brinson'](selected_fund, _pa_start, _pa_end)
            if _brinson_result and not _brinson_result['pa_df'].empty:
                _brinson_db = True
            elif _brinson_result is None:
                _brinson_fail_reason = f"MA000410에 '{selected_fund}' 펀드의 PA 데이터가 없거나 보유종목 매핑 실패"
        except Exception as e:
            _brinson_fail_reason = f"DB 조회 오류: {e}"
        # 2) Single Port PA (R 동일 PA) — 타임아웃 보호
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    cache['compute_single_port_pa'],
                    selected_fund, _pa_start, _pa_end, fx_split=pa_fx, mapping_method='방법3')
                _single_pa_result = future.result(timeout=15)
            if _single_pa_result is not None:
                _single_pa_db = True
        except concurrent.futures.TimeoutError:
            st.toast("PA 계산 시간 초과 (15초). Brinson fallback 사용.", icon="⚠️")
        except Exception as e:
            pass  # Brinson fallback으로 진행

    if _brinson_db:
        _pa_data = _brinson_result['pa_df']
        if pa_method == "5분류":
            # 8분류 → 5분류 축소 (FX/모펀드/유동성 → 유동성으로 합산)
            _pa5 = _pa_data[_pa_data['자산군'].isin(['국내주식','해외주식','국내채권','해외채권','대체투자'])].copy()
            _other = _pa_data[~_pa_data['자산군'].isin(['국내주식','해외주식','국내채권','해외채권','대체투자'])]
            _other_row = pd.DataFrame([{
                '자산군': '기타', 'AP비중': _other['AP비중'].sum(), 'BM비중': _other['BM비중'].sum(),
                'AP수익률': 0, 'BM수익률': 0,
                'Allocation': _other['Allocation'].sum(), 'Selection': _other['Selection'].sum(),
                'Cross': _other['Cross'].sum(), '기여수익률': _other['기여수익률'].sum()
            }])
            _pa_data = pd.concat([_pa5, _other_row], ignore_index=True)

        if not pa_fx and 'FX' in _pa_data['자산군'].values:
            _pa_data = _pa_data[_pa_data['자산군'] != 'FX']

        pa_asset_classes_display = _pa_data['자산군'].tolist()
        pa_ap_w_display = _pa_data['AP비중'].tolist()
        pa_bm_w_display = _pa_data['BM비중'].tolist()
        pa_ap_ret_display = _pa_data['AP수익률'].tolist()
        pa_bm_ret_display = _pa_data['BM수익률'].tolist()
        alloc_effects = _pa_data['Allocation'].tolist()
        select_effects = _pa_data['Selection'].tolist()
        cross_effects = _pa_data['Cross'].tolist()
        contrib_ret = _pa_data['기여수익률'].tolist()
        total_alloc = _brinson_result['total_alloc']
        total_select = _brinson_result['total_select']
        total_cross = _brinson_result['total_cross']
        total_excess = _brinson_result['total_excess']
        residual = _brinson_result.get('residual', 0.0)
        _fx_contrib = _brinson_result.get('fx_contrib', 0.0)
        _daily_brinson = _brinson_result.get('daily_brinson')
        _sec_contrib_db = _brinson_result.get('sec_contrib')
        _period_ap_ret = _brinson_result.get('period_ap_return', 0)
        _period_bm_ret = _brinson_result.get('period_bm_return', 0)
        st.caption("📡 DB 데이터 (dt.MA000410) — 일별 PA")
    else:
        # fallback mockup
        if pa_method == "5분류":
            pa_asset_classes_display = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자']
            pa_ap_w_display = [25.3, 30.1, 22.5, 8.2, 10.5]
            pa_bm_w_display = [25.0, 30.0, 25.0, 10.0, 8.0]
            pa_ap_ret_display = [2.31, 5.12, 0.82, 1.23, 3.45]
            pa_bm_ret_display = [1.98, 4.85, 0.75, 1.10, 3.12]
        else:
            pa_asset_classes_display = ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', 'FX', '모펀드', '유동성']
            pa_ap_w_display = [25.3, 30.1, 22.5, 8.2, 10.5, 1.2, 0.0, 2.2]
            pa_bm_w_display = [25.0, 30.0, 25.0, 10.0, 8.0, 0.0, 0.0, 2.0]
            pa_ap_ret_display = [2.31, 5.12, 0.82, 1.23, 3.45, 1.65, 0.0, 0.15]
            pa_bm_ret_display = [1.98, 4.85, 0.75, 1.10, 3.12, 1.57, 0.0, 0.10]

        if pa_fx and 'FX' not in pa_asset_classes_display:
            pa_asset_classes_display = pa_asset_classes_display + ['FX']
            fx_ap_w = sum(w for w, ac in zip(pa_ap_w_display, pa_asset_classes_display[:-1]) if '해외' in ac)
            pa_ap_w_display = pa_ap_w_display + [fx_ap_w]
            pa_bm_w_display = pa_bm_w_display + [fx_ap_w * 0.95]
            pa_ap_ret_display = pa_ap_ret_display + [1.65]
            pa_bm_ret_display = pa_bm_ret_display + [1.57]

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
        _fx_contrib = 0.0
        _daily_brinson = None
        _period_ap_ret = 0
        _period_bm_ret = 0
        _sec_contrib_db = None
        if _brinson_fail_reason:
            st.caption(f"⚠️ 목업 데이터 — {_brinson_fail_reason}")
        else:
            st.caption("⚠️ 목업 데이터")

    pa_tabs = st.tabs(["Brinson 분석", "수익률 비교", "개별포트 분석"])

    with pa_tabs[0]:
        # ── 자산군별 기여수익률: 좌=테이블, 우=개별포트 차트 ──
        col_tbl1, col_chart1 = st.columns([2, 3])
        with col_tbl1:
            st.markdown("##### 자산군별 기여수익률")
            if _single_pa_db:
                _spa_asset = _single_pa_result['asset_summary'].copy()
                _spa_display = _spa_asset[_spa_asset['자산군'] != '포트폴리오'].copy()
                _spa_port = _spa_asset[_spa_asset['자산군'] == '포트폴리오']
                if not _spa_port.empty:
                    _port_ret = _spa_port.iloc[0]['개별수익률'] * 100
                    st.caption(f"포트폴리오 수익률: **{_port_ret:+.2f}%**")
                brinson_df = pd.DataFrame({
                    '자산군': _spa_display['자산군'].tolist(),
                    '순자산비중': [f"{w*100:.1f}%" for w in _spa_display['순자산비중']],
                    '개별수익률': [f"{r*100:+.2f}%" for r in _spa_display['개별수익률']],
                    '기여수익률': [f"{c*100:+.2f}%" for c in _spa_display['기여수익률']],
                })
                st.dataframe(brinson_df, hide_index=True, width="stretch")
            else:
                brinson_df = pd.DataFrame({
                    '자산군': pa_asset_classes_display,
                    'AP비중': [f"{w:.1f}" for w in pa_ap_w_display],
                    'BM비중': [f"{w:.1f}" for w in pa_bm_w_display],
                    'AP수익률': [f"{r:+.2f}%" for r in pa_ap_ret_display],
                    'BM수익률': [f"{r:+.2f}%" for r in pa_bm_ret_display],
                    '기여수익률': [f"{c:+.2f}%" for c in contrib_ret],
                })
                st.dataframe(brinson_df, hide_index=True, width="stretch")

        with col_chart1:
            if _single_pa_db:
                _spa_d = _single_pa_result['asset_summary']
                _spa_d = _spa_d[_spa_d['자산군'] != '포트폴리오'].copy()
                _ac_names = _spa_d['자산군'].tolist()
                _ac_contrib = (_spa_d['기여수익률'] * 100).tolist()
                colors_cc = ['#EF553B' if c < 0 else '#636EFA' for c in _ac_contrib]
                fig_ctb = go.Figure(go.Bar(x=_ac_names, y=_ac_contrib, marker_color=colors_cc,
                                            text=[f"{c:+.2f}%" for c in _ac_contrib], textposition='outside'))
                fig_ctb.update_layout(title='자산군별 기여수익률 (PA)', height=400, yaxis_title='기여수익률(%)',
                                       margin=dict(t=60, b=40, l=40, r=40))
            else:
                colors_cc = ['#EF553B' if c < 0 else '#636EFA' for c in contrib_ret]
                fig_ctb = go.Figure(go.Bar(x=pa_asset_classes_display, y=contrib_ret, marker_color=colors_cc,
                                            text=[f"{c:+.2f}%" for c in contrib_ret], textposition='outside'))
                fig_ctb.update_layout(title='자산군별 기여수익률', height=400, yaxis_title='기여수익률(%)')
            st.plotly_chart(fig_ctb, width="stretch")

        # ── 초과성과 요인분해: 좌=테이블, 우=워터폴 차트 ──
        col_tbl2, col_chart2 = st.columns([2, 3])
        with col_tbl2:
            st.markdown("##### 초과성과 요인분해")
            _excess_total = total_excess
            decomp_df = pd.DataFrame({
                '요인': ['Allocation Effect', 'Selection Effect', 'Cross Effect', '유동성/기타', '합계'],
                '기여도': [f"{total_alloc:+.2f}%", f"{total_select:+.2f}%", f"{total_cross:+.2f}%",
                         f"{residual:+.2f}%", f"{_excess_total:+.2f}%"],
                '비율': [f"{abs(total_alloc)/max(abs(_excess_total),0.01)*100:.0f}%",
                        f"{abs(total_select)/max(abs(_excess_total),0.01)*100:.0f}%",
                        f"{abs(total_cross)/max(abs(_excess_total),0.01)*100:.0f}%",
                        f"{abs(residual)/max(abs(_excess_total),0.01)*100:.0f}%",
                        '100%']
            })
            if _fx_contrib != 0:
                st.caption(f"FX 기여: {_fx_contrib:+.2f}%")
            st.dataframe(decomp_df, hide_index=True, width="stretch")

        with col_chart2:
            fig_wf = go.Figure(go.Waterfall(
                name="", orientation="v",
                x=['Allocation', 'Selection', 'Cross', '유동성/기타', '초과수익률'],
                y=[total_alloc, total_select, total_cross, residual, _excess_total],
                measure=['relative', 'relative', 'relative', 'relative', 'total'],
                connector_line_color='#888',
                increasing_marker_color='#636EFA',
                decreasing_marker_color='#EF553B',
                totals_marker_color='#00CC96',
                text=[f"{total_alloc:+.2f}%", f"{total_select:+.2f}%", f"{total_cross:+.2f}%",
                      f"{residual:+.2f}%", f"{_excess_total:+.2f}%"],
                textposition='outside'
            ))
            _all_vals = [total_alloc, total_select, total_cross, residual, _excess_total]
            _y_min = min(0, min(_all_vals)) * 1.4
            _y_max = max(0, max(_all_vals)) * 1.4
            fig_wf.update_layout(title='초과성과 요인분해 (Brinson)', height=400, yaxis_title='기여도 (%)',
                                  yaxis_range=[_y_min, _y_max])
            st.plotly_chart(fig_wf, width="stretch")

    with pa_tabs[1]:
        # AP vs BM 누적수익률: DB NAV 데이터 활용
        _pa_ap_cum = None
        _pa_bm_cum = None
        _pa_dates = None
        if DB_CONNECTED and len(analysis_period) == 2:
            try:
                _pa_nav_df = cache['load_fund_nav'](selected_fund, analysis_period[0].strftime('%Y%m%d'))
                if not _pa_nav_df.empty:
                    _pa_nav_ts = _pa_nav_df.set_index('기준일자')['MOD_STPR'].sort_index()
                    _pa_ap_cum = (_pa_nav_ts / _pa_nav_ts.iloc[0] - 1) * 100
                    _pa_dates = _pa_nav_ts.index
                    # BM 누적수익률: DT 우선 → SCIP fallback
                    _bm_nav_df = cache['load_dt_bm'](selected_fund, analysis_period[0].strftime('%Y%m%d'))
                    if _bm_nav_df.empty or len(_bm_nav_df) < 10:
                        _bm_cfg = FUND_BM.get(selected_fund)
                        if _bm_cfg:
                            import json as _json_pa
                            _bm_nav_df = cache['load_composite_bm'](_json_pa.dumps(_bm_cfg['components']),
                                                                    analysis_period[0].strftime('%Y-%m-%d'))
                    if not _bm_nav_df.empty:
                        _bm_col = 'composite_price' if 'composite_price' in _bm_nav_df.columns else 'value'
                        if _bm_col in _bm_nav_df.columns:
                            _bm_nav_ts = _bm_nav_df.set_index('기준일자')[_bm_col].sort_index()
                            _common_pa = _pa_nav_ts.index.intersection(_bm_nav_ts.index).sort_values()
                            if len(_common_pa) > 10:
                                _pa_ap_cum = (_pa_nav_ts.reindex(_common_pa) / _pa_nav_ts.reindex(_common_pa).iloc[0] - 1) * 100
                                _pa_bm_cum = (_bm_nav_ts.reindex(_common_pa) / _bm_nav_ts.reindex(_common_pa).iloc[0] - 1) * 100
                                _pa_dates = _common_pa
            except Exception:
                pass

        if _pa_ap_cum is not None and _pa_dates is not None:
            if _pa_bm_cum is None:
                _pa_bm_cum = _pa_ap_cum * 0.85  # BM 없으면 근사
            excess_cum = _pa_ap_cum - _pa_bm_cum
        else:
            comp_dates_pa = pd.bdate_range('2025-07-01', periods=150)
            _pa_ap_cum = (make_nav(1000, 0.0003, 0.004, 150) / 1000 - 1) * 100
            _pa_bm_cum = (make_nav(1000, 0.00025, 0.003, 150) / 1000 - 1) * 100
            excess_cum = _pa_ap_cum - _pa_bm_cum
            _pa_dates = comp_dates_pa

        fig_ret = go.Figure()
        fig_ret.add_trace(go.Scatter(
            x=_pa_dates, y=excess_cum, name='초과수익',
            fill='tozeroy', fillcolor='rgba(144, 238, 144, 0.20)',
            line=dict(color='rgba(144, 238, 144, 0.5)', width=0.8)
        ))
        fig_ret.add_trace(go.Scatter(x=_pa_dates, y=_pa_ap_cum, name='AP (포트폴리오)',
                                      line=dict(color='#636EFA', width=2.5)))
        fig_ret.add_trace(go.Scatter(x=_pa_dates, y=_pa_bm_cum, name='BM',
                                      line=dict(color='#EF553B', width=2, dash='dot')))
        fig_ret.update_layout(title='AP vs BM 누적수익률', height=450,
                                yaxis_title='수익률(%)', hovermode='x unified',
                                legend=dict(orientation='h', y=1.05))
        st.plotly_chart(fig_ret, width="stretch")

    with pa_tabs[2]:
        col_pl, col_pr = st.columns(2)
        with col_pl:
            st.markdown("##### 종목별 기여수익률")
            if _single_pa_db:
                _sec_sum = _single_pa_result['sec_summary'].copy()
                _sec_sum = _sec_sum[~_sec_sum['종목코드'].isin(['유동성및기타'])].copy()
                _sec_sum['개별수익률(%)'] = (_sec_sum['개별수익률'] * 100).round(4)
                _sec_sum['기여수익률(%)'] = (_sec_sum['기여수익률'] * 100).round(4)
                _sec_sum['비중(%)'] = (_sec_sum['순자산비중'] * 100).round(2)
                sec_display = _sec_sum[['자산군', '종목명', '비중(%)', '개별수익률(%)', '기여수익률(%)']].copy()
                for _nc in ['비중(%)', '개별수익률(%)', '기여수익률(%)']:
                    sec_display[_nc] = sec_display[_nc].round(2)
                _ac_order = {ac: i for i, ac in enumerate(ASSET_CLASSES)}
                sec_display['_sort'] = sec_display['자산군'].map(_ac_order).fillna(99)
                sec_display = sec_display.sort_values(['_sort', '기여수익률(%)'], ascending=[True, False]).drop(columns='_sort').reset_index(drop=True)
                _h = max(200, 35 * len(sec_display) + 40)
                st.dataframe(sec_display.style.format({'비중(%)': '{:.2f}', '개별수익률(%)': '{:.2f}', '기여수익률(%)': '{:.2f}'}).map(
                    lambda v: 'color: #EF553B' if isinstance(v, (int, float)) and v < 0 else (
                        'color: #00CC96' if isinstance(v, (int, float)) and v > 0 else ''),
                    subset=['개별수익률(%)', '기여수익률(%)']
                ), hide_index=True, width="stretch", height=_h)
                st.caption(f"📡 R 동일 PA — 전 종목 ({len(sec_display)}개)")
            elif _sec_contrib_db is not None and not _sec_contrib_db.empty:
                sec_contrib = _sec_contrib_db.head(10)
                st.dataframe(sec_contrib.style.map(
                    lambda v: 'color: #EF553B' if isinstance(v, float) and v < 0 else (
                        'color: #00CC96' if isinstance(v, float) and v > 0 else ''),
                    subset=['수익률(%)', '기여수익률(%)']
                ), hide_index=True, width="stretch")
            else:
                sec_contrib = pd.DataFrame({
                    '자산군': ['국내주식','국내주식','해외주식','해외주식','해외주식','국내채권','국내채권','대체투자'],
                    '종목명': ['KODEX200','TIGER KOSPI','SPY','QQQ','VWO','국고3Y','통안2Y','맥쿼리인프라'],
                    '수익률(%)': [2.31, 1.82, 5.12, 7.21, -1.30, 0.82, 0.51, 3.45],
                    '기여수익률(%)': [0.24, 0.15, 0.63, 0.73, -0.06, 0.10, 0.05, 0.17]
                })
                st.dataframe(sec_contrib, hide_index=True, width="stretch")

        with col_pr:
            if _single_pa_db:
                _sec_for_chart = _single_pa_result['sec_summary'].copy()
                _sec_for_chart = _sec_for_chart[~_sec_for_chart['종목코드'].isin(['유동성및기타'])].copy()
                _sec_for_chart['기여수익률(%)'] = (_sec_for_chart['기여수익률'] * 100).round(2)
                _sec_for_chart['개별수익률(%)'] = (_sec_for_chart['개별수익률'] * 100).round(2)
                _sec_for_chart['비중(%)'] = (_sec_for_chart['순자산비중'] * 100).round(2)
                if '종목코드' not in _sec_for_chart.columns:
                    _sec_for_chart['종목코드'] = ''

                _col_filter1, _col_filter2 = st.columns(2)
                with _col_filter1:
                    _available_classes = ['전체'] + sorted(_sec_for_chart['자산군'].unique().tolist())
                    _sel_class = st.selectbox("자산군", _available_classes, key="pa_sec_class_filter")
                with _col_filter2:
                    _metric_options = ['기여수익률(%)', '개별수익률(%)', '비중(%)']
                    _sel_metric = st.selectbox("정렬 기준", _metric_options, key="pa_sec_metric")

                if _sel_class != '전체':
                    _filtered = _sec_for_chart[_sec_for_chart['자산군'] == _sel_class]
                else:
                    _filtered = _sec_for_chart

                # 선택 지표 기준 내림차순 정렬
                _sorted = _filtered.sort_values(_sel_metric, ascending=False)

                from modules.item_abbrev import abbreviate
                _codes = _sorted['종목코드'].tolist()
                _names = [abbreviate(c, n) for c, n in zip(_codes, _sorted['종목명'])]
                _vals = _sorted[_sel_metric].tolist()
                _colors = ['#EF553B' if v < 0 else '#636EFA' for v in _vals]
                _suffix = '%'

                fig_sec = go.Figure(go.Bar(
                    y=_names[::-1], x=_vals[::-1], orientation='h',
                    marker_color=_colors[::-1],
                    text=[f"{v:+.2f}{_suffix}" for v in _vals[::-1]], textposition='outside'
                ))
                _x_abs = max(abs(min(_vals)), abs(max(_vals))) if _vals else 1
                _x_range = _x_abs * 1.5
                _chart_h = max(250, 30 * len(_sorted) + 40)
                fig_sec.update_layout(
                    height=_chart_h, margin=dict(t=10, b=20, l=120, r=40),
                    xaxis_title=_sel_metric,
                    xaxis_range=[-_x_range, _x_range] if any(v < 0 for v in _vals) else [0, _x_range],
                )
                st.plotly_chart(fig_sec, width="stretch")
            else:
                colors_cc = ['#EF553B' if c < 0 else '#636EFA' for c in contrib_ret]
                fig_ctb = go.Figure(go.Bar(x=pa_asset_classes_display, y=contrib_ret, marker_color=colors_cc,
                                            text=[f"{c:+.2f}%" for c in contrib_ret], textposition='outside'))
                fig_ctb.update_layout(height=350, yaxis_title='기여수익률(%)')
                st.plotly_chart(fig_ctb, width="stretch")


    # (기여수익률 추이 탭 삭제됨)
