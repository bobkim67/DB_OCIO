# -*- coding: utf-8 -*-
"""Admin(운용보고_펀드) — 펀드별 코멘트 생성/검수.

시장 전체 debate 결과를 기반으로, 각 펀드의 편입 자산군에 맞춰 개별 코멘트를 생성한다.
"""

import re
from datetime import datetime

import streamlit as st

from market_research.report.report_store import (
    load_draft, load_final, update_draft_comment,
    approve_and_save_final, save_draft,
    get_status, OUTPUT_DIR,
    STATUS_NOT_GENERATED, STATUS_DRAFT, STATUS_EDITED, STATUS_APPROVED,
)

# 시장 debate 코드 (admin_macro.py와 동일)
_MARKET_FUND_CODE = '_market'


def _status_label(status: str) -> str:
    return {
        STATUS_NOT_GENERATED: '미생성',
        STATUS_DRAFT: 'Draft',
        STATUS_EDITED: '수정됨',
        STATUS_APPROVED: '승인완료',
    }.get(status, status)


def render(ctx):
    """Admin(운용보고_펀드) 탭."""
    st.markdown("#### 펀드별 코멘트 생성")
    st.caption("시장 debate 결과를 기반으로 펀드별 편입 자산군에 맞춘 코멘트를 생성합니다.")

    # ── 기간/펀드 선택 (마지막 생성 기간 기준 디폴트) ──
    from market_research.report.report_store import get_latest_period_for_fund
    top_fund = ctx.get('selected_fund', '')
    latest = get_latest_period_for_fund(top_fund) if top_fund else None
    if latest and '-Q' in latest:
        _def_mode, _def_year, _def_num = '분기', int(latest[:4]), int(latest[-1])
    elif latest and '-' in latest:
        _def_mode, _def_year, _def_num = '월별', int(latest[:4]), int(latest[5:7])
    else:
        _def_mode = '월별'
        _def_year = datetime.now().year
        _def_num = max(1, datetime.now().month - 1)

    fund_code = ctx.get('selected_fund', '')

    col_mode, col_year, col_period = st.columns([1, 1, 1])
    with col_mode:
        mode = st.radio("기간 유형", ["월별", "분기"], index=["월별", "분기"].index(_def_mode),
                        horizontal=True, key="admf_mode")
    with col_year:
        year = st.number_input("년도", min_value=2025, max_value=2030,
                               value=_def_year, key="admf_year")
    with col_period:
        if mode == "월별":
            def_month = _def_num if _def_mode == '월별' else max(1, datetime.now().month - 1)
            period_num = st.number_input("월", min_value=1, max_value=12,
                                         value=def_month, key="admf_month")
            period_key = f"{year}-{period_num:02d}"
        else:
            def_q = _def_num if _def_mode == '분기' else (datetime.now().month - 1) // 3 + 1
            period_num = st.number_input("분기", min_value=1, max_value=4,
                                         value=def_q, key="admf_quarter")
            period_key = f"{year}-Q{period_num}"

    # ── 시장 debate 상태 확인 (approved final 우선, edited draft fallback) ──
    market_final = load_final(period_key, _MARKET_FUND_CODE)
    market_draft = load_draft(period_key, _MARKET_FUND_CODE)
    market_payload = market_final or market_draft  # final 우선

    if not market_payload:
        st.warning(f"{period_key} 시장 debate가 아직 실행되지 않았습니다. Admin(운용보고_매크로) 탭에서 먼저 실행하세요.")
        return

    market_label = '승인완료' if market_final else _status_label(market_draft.get('status', ''))
    market_gen = (market_payload.get('generated_at', '') or market_payload.get('debated_at', '?'))
    st.info(f"시장 debate 상태: {market_label} | 생성: {market_gen}")

    # ── 펀드별 코멘트 상태 ──
    fund_status = get_status(period_key, fund_code)
    fund_draft = load_draft(period_key, fund_code)
    fund_final = load_final(period_key, fund_code)

    st.markdown("---")

    col_st, col_act = st.columns([2, 1])
    with col_st:
        label = _status_label(fund_status)
        if fund_status == STATUS_APPROVED:
            st.success(f"{fund_code} 상태: {label} | 승인: {fund_final.get('approved_at', '?')}")
        elif fund_status in (STATUS_DRAFT, STATUS_EDITED):
            st.info(f"{fund_code} 상태: {label}")
        else:
            st.warning(f"{fund_code} 상태: {label}")

    with col_act:
        generate = st.button("펀드 코멘트 생성", key="admf_gen", type="primary",
                             use_container_width=True,
                             disabled=(fund_status == STATUS_APPROVED))

    # ── 펀드 코멘트 생성 (fund_comment_service 호출) ──
    if generate:
        with st.spinner(f"{fund_code} 코멘트 생성 중... (Opus, ~30초)"):
            try:
                from market_research.report.fund_comment_service import generate_fund_comment_and_save

                fund_draft_data = generate_fund_comment_and_save(
                    mode=mode, year=year, period_num=period_num,
                    fund_code=fund_code, period_key=period_key,
                    market_payload=market_payload,
                )
                cost = fund_draft_data.get('cost_usd', 0)
                st.success(f"{fund_code} 코멘트 생성 완료 (비용: ${cost:.2f})")
                for w in fund_draft_data.get('data_warnings', []):
                    st.warning(w)
                st.rerun()
            except Exception as exc:
                st.error(f"생성 실패: {exc}")

    # ── 펀드 Draft 검토/수정/승인 ──
    if fund_draft and fund_status != STATUS_NOT_GENERATED:
        comment_text = fund_draft.get('draft_comment', '') or fund_draft.get('customer_comment', '')

        if comment_text and '\n' not in comment_text:
            sentences = re.split(r'(?<=[.다])\s+', comment_text)
            chunk_size = max(3, len(sentences) // 4)
            paragraphs = []
            for i in range(0, len(sentences), chunk_size):
                paragraphs.append(' '.join(sentences[i:i + chunk_size]))
            comment_text = '\n\n'.join(paragraphs)

        st.markdown("##### Comment (수정 가능)")
        ta_key = f"admf_edit_{fund_code}_{period_key}_{fund_draft.get('generated_at', '')}"
        edited = st.text_area("코멘트 수정", value=comment_text, height=400,
                              key=ta_key, label_visibility="collapsed",
                              disabled=(fund_status == STATUS_APPROVED))

        col_save, col_approve, col_reset = st.columns([1, 1, 1])
        with col_save:
            if st.button("Draft 저장", key="admf_save", use_container_width=True,
                         disabled=(fund_status == STATUS_APPROVED)):
                update_draft_comment(period_key, fund_code, edited)
                st.success("Draft 저장 완료")
                st.rerun()
        with col_approve:
            if st.button("최종 승인", key="admf_approve", type="primary",
                         use_container_width=True,
                         disabled=(fund_status == STATUS_APPROVED)):
                update_draft_comment(period_key, fund_code, edited)
                path = approve_and_save_final(period_key, fund_code)
                st.success(f"승인 완료: {path.name if path else '?'}")
                st.rerun()
        with col_reset:
            if fund_status == STATUS_APPROVED:
                if st.button("승인 해제", key="admf_reset", use_container_width=True):
                    fp = OUTPUT_DIR / period_key / f'{fund_code}.final.json'
                    if fp.exists():
                        fp.unlink()
                    fund_draft['status'] = STATUS_EDITED
                    save_draft(period_key, fund_code, fund_draft)
                    st.info("승인 해제됨.")
                    st.rerun()

    # ── 거래내역 + 비중 변화 테이블 ──
    st.markdown("---")
    st.markdown("##### 거래내역 / 비중 변화")

    try:
        from market_research.report.fund_comment_service import _resolve_dates
        prev_last, cur_last, _, _, _ = _resolve_dates(mode, year, period_num)
    except Exception:
        prev_last, cur_last = None, None

    if prev_last and cur_last:
        import pandas as pd
        from modules.data_loader import (
            load_fund_net_trades, load_fund_trade_detail,
            load_fund_holdings_weight,
        )

        net_trades = load_fund_net_trades(fund_code, prev_last, cur_last)
        holdings_start = load_fund_holdings_weight(fund_code, prev_last)
        holdings_end_df = load_fund_holdings_weight(fund_code, cur_last)
        trade_detail = load_fund_trade_detail(fund_code, prev_last, cur_last)

        # 종목별 거래 집계 (기간 합산)
        trade_by_item = pd.DataFrame()
        if not trade_detail.empty:
            buy_df = trade_detail[trade_detail['매수매도'] == '매수'].groupby(['자산군', '종목명'])['금액(억)'].sum().rename('매수(억)')
            sell_df = trade_detail[trade_detail['매수매도'] == '매도'].groupby(['자산군', '종목명'])['금액(억)'].sum().rename('매도(억)')
            trade_by_item = pd.concat([buy_df, sell_df], axis=1).fillna(0)
            trade_by_item['순매수(억)'] = trade_by_item['매수(억)'] - trade_by_item['매도(억)']
            trade_by_item = trade_by_item.reset_index()

        # 종목별 기초/기말 비중 매핑
        start_items = holdings_start.set_index('종목명')[['자산군', '비중(%)', '평가금액(억)']].rename(
            columns={'비중(%)': '기초(%)', '평가금액(억)': '기초(억)'}) if not holdings_start.empty else pd.DataFrame()
        end_items = holdings_end_df.set_index('종목명')[['자산군', '비중(%)', '평가금액(억)']].rename(
            columns={'비중(%)': '기말(%)', '평가금액(억)': '기말(억)'}) if not holdings_end_df.empty else pd.DataFrame()

        # 전체 종목 합치기
        all_items = set()
        if not start_items.empty:
            all_items |= set(start_items.index)
        if not end_items.empty:
            all_items |= set(end_items.index)
        if not trade_by_item.empty:
            all_items |= set(trade_by_item['종목명'])

        rows = []
        for item in sorted(all_items):
            has_si = not start_items.empty and item in start_items.index
            has_ei = not end_items.empty and item in end_items.index
            has_ti = not trade_by_item.empty and item in trade_by_item['종목명'].values

            si = start_items.loc[item] if has_si else None
            ei = end_items.loc[item] if has_ei else None
            ti = trade_by_item[trade_by_item['종목명'] == item].iloc[0] if has_ti else None

            ac = ''
            for src in [si, ei, ti]:
                if src is not None and src.get('자산군', ''):
                    val = src['자산군']
                    ac = val.iloc[0] if isinstance(val, pd.Series) else str(val)
                    if ac:
                        break
            ac = ac or '기타'

            rows.append({
                '자산군': ac,
                '종목명': item,
                '기초(%)': round(float(si['기초(%)']) if si is not None and '기초(%)' in si.index else 0, 2),
                '매수(억)': round(float(ti['매수(억)']) if ti is not None else 0, 1),
                '매도(억)': round(float(ti['매도(억)']) if ti is not None else 0, 1),
                '순매수(억)': round(float(ti['순매수(억)']) if ti is not None else 0, 1),
                '기말(%)': round(float(ei['기말(%)']) if ei is not None and '기말(%)' in ei.index else 0, 2),
            })

        if rows:
            detail_df = pd.DataFrame(rows)

            # 유동성 중 예금/USD DEPOSIT 외는 '기타'로 묶기
            _KEEP_CASH = {'예금', 'USD DEPOSIT'}
            mask = (detail_df['자산군'] == '유동성') & (~detail_df['종목명'].isin(_KEEP_CASH))
            if mask.any():
                etc_row = detail_df[mask].sum(numeric_only=True).to_dict()
                etc_row['자산군'] = '유동성'
                etc_row['종목명'] = '기타 유동성'
                detail_df = pd.concat([detail_df[~mask], pd.DataFrame([etc_row])], ignore_index=True)

            detail_df = detail_df.sort_values(['자산군', '기말(%)'], ascending=[True, False])

            # 비중변화 계산
            detail_df['비중변화(%p)'] = detail_df['기말(%)'] - detail_df['기초(%)']

            # 자산군 소계행 삽입
            final_rows = []
            for ac in sorted(detail_df['자산군'].unique()):
                sub = detail_df[detail_df['자산군'] == ac]
                subtotal = {
                    '자산군': ac,
                    '종목명': f'[{ac} 합계]',
                    '기초(%)': round(sub['기초(%)'].sum(), 1),
                    '기말(%)': round(sub['기말(%)'].sum(), 1),
                    '비중변화(%p)': round(sub['기말(%)'].sum() - sub['기초(%)'].sum(), 1),
                    '매수(억)': round(sub['매수(억)'].sum(), 1),
                    '매도(억)': round(sub['매도(억)'].sum(), 1),
                    '순매수(억)': round(sub['순매수(억)'].sum(), 1),
                }
                final_rows.append(subtotal)
                for _, r in sub.iterrows():
                    row_dict = r.to_dict()
                    row_dict['자산군'] = ''
                    final_rows.append(row_dict)

            result_df = pd.DataFrame(final_rows)

            # 필드 순서: 자산군, 종목명, 기초, 기말, 비중변화, 매수, 매도, 순매수
            col_order = ['자산군', '종목명', '기초(%)', '기말(%)', '비중변화(%p)', '매수(억)', '매도(억)', '순매수(억)']
            result_df = result_df[[c for c in col_order if c in result_df.columns]]

            # 부호 포맷: 비중변화에 +/- , 순매수에 + 부호
            def _sign(v, decimals=1):
                v = round(float(v), decimals)
                return f'+{v}' if v > 0 else str(v)

            result_df['비중변화(%p)'] = result_df['비중변화(%p)'].apply(lambda x: _sign(x))
            result_df['순매수(억)'] = result_df['순매수(억)'].apply(lambda x: _sign(x))

            st.dataframe(result_df, hide_index=True, use_container_width=True, height=500)
        else:
            st.info("데이터 없음")
    else:
        st.info("영업일 데이터 없음")
