# -*- coding: utf-8 -*-
"""Report tab UI — 운용보고 뷰어.

v6: client/admin 모드 분리.
  - Client: approved final만 표시 (draft/warning/evidence raw 미노출)
  - Admin: draft + final + evidence quality + warning summary + 메타데이터 표시
  - 계산 없음 — 저장된 JSON만 읽어 표시

데이터 경로:
  - 펀드별 PA 캐시: report_cache/{YYYY-MM}/{fund_code}.json
  - 시장 코멘트 (신규): report_output/{period}/{fund_code}.final.json (approved)
  - 시장 코멘트 (기존): debate_published/{period}.json (하위호환)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_ROOT = _REPO_ROOT / "market_research" / "data" / "report_cache"
_CATALOG_PATH = _CACHE_ROOT / "catalog.json"
_MACRO_CSV = _REPO_ROOT / 'market_research' / 'data' / 'macro' / 'indicators.csv'

DISPLAY_ASSET_CLASSES = ["국내주식", "해외주식", "국내채권", "해외채권", "대체투자"]


# ══════════════════════════════════════════
# JSON 로딩 유틸리티
# ══════════════════════════════════════════

def _load_catalog():
    if not _CATALOG_PATH.exists():
        return None
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def _available_periods():
    periods = []
    if not _CACHE_ROOT.exists():
        return periods
    for d in sorted(_CACHE_ROOT.iterdir()):
        if d.is_dir() and d.name not in ('__pycache__',):
            periods.append(d.name)
    return periods


def _load_period_funds(period_name):
    d = _CACHE_ROOT / period_name
    if not d.exists():
        return []
    funds = []
    for f in sorted(d.glob("*.json")):
        if f.stem in ('catalog', 'enriched_digest', 'news_content_pool'):
            continue
        funds.append(f.stem)
    return funds


def _load_payload(period_name, fund_code):
    path = _CACHE_ROOT / period_name / f"{fund_code}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _get_asset_value(mapping, asset_class):
    if asset_class in mapping:
        return mapping.get(asset_class, 0.0)
    if asset_class == "대체투자":
        return (
            mapping.get("대체투자", 0.0)
            + mapping.get("대체", 0.0)
            + mapping.get("원자재", 0.0)
        )
    return 0.0


def _clean_item_name(value):
    text = str(value or "").strip()
    if re.fullmatch(r"KR[A-Z0-9]{10,}", text):
        return "종목명 미매핑"
    if re.fullmatch(r"[A-Z0-9]{6,}", text):
        return "종목명 미매핑"
    if re.fullmatch(r"\d{5,}", text):
        return "종목명 미매핑"
    text = re.sub(r"^(KR[A-Z0-9]{8,}|[A-Z0-9]{5,}|\d{5,})\s+", "", text)
    text = re.sub(r"\s+\((KR[A-Z0-9]{8,}|[A-Z0-9]{5,}|\d{5,})\)$", "", text)
    text = text.strip(" -")
    return text or "종목명 미매핑"


# ══════════════════════════════════════════
# 운용보고 탭 — PA 기여도 + 코멘트 뷰어
# ══════════════════════════════════════════

def render_pa(_ctx=None):
    """펀드 코멘트 뷰어. report_output의 draft/final JSON을 읽어서 표시."""
    st.markdown("#### 운용보고 — 펀드 코멘트")

    is_admin = st.session_state.get('user_role') == 'admin'

    from market_research.report.report_store import (
        list_periods, list_approved_periods, list_approved_funds,
        list_funds_in_period, load_final, load_draft,
    )

    if is_admin:
        all_periods = list_periods()
    else:
        all_periods = list_approved_periods()

    if not all_periods:
        st.info("승인된 코멘트가 아직 없습니다." if not is_admin else "발행된 코멘트가 없습니다.")
        return

    sel_period = st.selectbox("기간", all_periods, index=0, key="report_period_sel")

    # 상단 공통 펀드 선택 바 연동
    sel_fund = _ctx.get('selected_fund', '') if _ctx else ''
    if not sel_fund:
        st.info("상단에서 펀드를 선택하세요.")
        return

    # 데이터 로딩: client는 final only
    if is_admin:
        data = load_final(sel_period, sel_fund) or load_draft(sel_period, sel_fund)
    else:
        data = load_final(sel_period, sel_fund)

    if not data:
        st.info("승인된 코멘트가 아직 없습니다." if not is_admin else "코멘트가 없습니다.")
        return

    # 메타
    meta_parts = []
    if data.get('generated_at'):
        meta_parts.append(f"생성: {data['generated_at']}")
    if data.get('approved_at'):
        meta_parts.append(f"승인: {data['approved_at']}")
    if meta_parts:
        st.caption(" | ".join(meta_parts))

    # 코멘트 본문
    comment = data.get('final_comment') or data.get('draft_comment', '')
    if comment:
        paragraphs = [p.strip() for p in comment.split('\n') if p.strip()]
        for para in paragraphs:
            st.markdown(f'&emsp;{para}', unsafe_allow_html=True)
            st.markdown('')

    else:
        st.info("코멘트가 비어 있습니다.")

    # admin: 상태 + data_snapshot
    if is_admin:
        status = data.get('status', '')
        if status:
            label = {'draft_generated': 'Draft', 'edited': '수정됨', 'approved': '승인완료'}.get(status, status)
            st.caption(f"상태: {label}")

        snap = data.get('data_snapshot', {})
        if snap.get('trades'):
            st.markdown("---")
            st.markdown("**거래 요약**")
            trades = snap['trades']
            rows = []
            for ac, v in sorted(trades.items()):
                if ac in ('유동성', '모펀드'):
                    continue
                rows.append({'자산군': ac, '매수(억)': v.get('buy', 0), '매도(억)': v.get('sell', 0), '순매수(억)': v.get('net', 0)})
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# ══════════════════════════════════════════
# 운용보고(전체) 탭 — 시장 코멘트 뷰어
# ══════════════════════════════════════════

# 코멘트에서 탐지할 지표 키워드 → indicators.csv 컬럼 매핑
_CHART_KEYWORD_MAP = {
    'DXY': ('DXY', '달러인덱스 (DXY)'),
    '달러인덱스': ('DXY', '달러인덱스 (DXY)'),
    'USDKRW': ('USDKRW', '원/달러 환율'),
    '원/달러': ('USDKRW', '원/달러 환율'),
    '원·달러': ('USDKRW', '원/달러 환율'),
    '달러/원': ('USDKRW', '원/달러 환율'),
    '선물환': ('F_USDKRW', '달러/원 선물환'),
    'F_USDKRW': ('F_USDKRW', '달러/원 선물환'),
    'UST 2Y': ('UST_2Y', '미국채 2년 (%)'),
    'UST 10Y': ('UST_10Y', '미국채 10년 (%)'),
    '미국채 2년': ('UST_2Y', '미국채 2년 (%)'),
    '미국채 10년': ('UST_10Y', '미국채 10년 (%)'),
    '미 국채': ('UST_10Y', '미국채 10년 (%)'),
    '미국 국채': ('UST_10Y', '미국채 10년 (%)'),
    '2년-10년': ('US_2Y10Y', '미국채 2Y-10Y 스프레드'),
    'MOVE': ('MOVE', 'MOVE 지수'),
    'VIX': ('VIX', 'VIX 지수'),
    '변동성 지수': ('MOVE', 'MOVE 지수'),
    'KOSPI': ('KOSPI', 'KOSPI (KRW)'),
    '코스피': ('KOSPI', 'KOSPI (KRW)'),
    'S&P': ('SP500', 'S&P 500 (USD)'),
    'S&P500': ('SP500', 'S&P 500 (USD)'),
    'STOXX': ('MSCI_EAFE', 'MSCI EAFE (선진국)'),
    '신흥국': ('VWO', 'VWO 신흥국 (USD)'),
    'MSCI EM': ('VWO', 'VWO 신흥국 (USD)'),
    '성장주': ('US_GROWTH', 'VUG 미국 성장주 (USD)'),
    '가치주': ('US_VALUE', 'VTV 미국 가치주 (USD)'),
    '하이일드': ('USHY', 'iShares US HY (USD)'),
    'HY': ('USHY', 'iShares US HY (USD)'),
    '신흥국채권': ('EM_BOND', 'VWOB 신흥국 달러채권 (USD)'),
    '신흥국 채권': ('EM_BOND', 'VWOB 신흥국 달러채권 (USD)'),
    'EM채권': ('EM_BOND', 'VWOB 신흥국 달러채권 (USD)'),
    'WTI': ('WTI', 'WTI 원유 ($/배럴)'),
    '유가': ('WTI', 'WTI 원유 ($/배럴)'),
    '국제유가': ('WTI', 'WTI 원유 ($/배럴)'),
    'GOLD': ('GOLD', '금 ($/oz)'),
    '금': ('GOLD', '금 ($/oz)'),
    '브렌트': ('BRENT', '브렌트유 ($/배럴)'),
}


def _render_comment_with_sources(comment: str, annotations: list,
                                 related_news: list = None):
    """코멘트를 문단 분리 + 하단 출처/관련 뉴스로 렌더링."""
    display = comment

    paragraphs = [p.strip() for p in display.split('\n') if p.strip()]
    if len(paragraphs) <= 1:
        sentences = re.split(r'(?<=[.다])\s+', display)
        chunk_size = max(3, len(sentences) // 4)
        paragraphs = []
        for i in range(0, len(sentences), chunk_size):
            paragraphs.append(' '.join(sentences[i:i + chunk_size]))

    for para in paragraphs:
        st.markdown(f'&emsp;{para}', unsafe_allow_html=True)
        st.markdown('')

    if annotations:
        st.markdown('---')
        st.markdown('**출처**')
        for ann in annotations:
            ref = ann.get('ref', '')
            title = ann.get('title', '')
            source = ann.get('source', '')
            date = ann.get('date', '')
            url = ann.get('url', '')
            sal = ann.get('salience', 0)
            expl = ann.get('salience_explanation', '')
            link = f'[{title}]({url})' if url else title
            sal_str = f' | 중요도 {sal:.2f} ({expl})' if sal else ''
            st.caption(f'[ref:{ref}] {link} — {source}, {date}{sal_str}')

    if related_news:
        st.markdown('---')
        st.markdown('**관련 뉴스**')
        for r in related_news:
            title = r.get('title', '')
            source = r.get('source', '')
            date = r.get('date', '')
            url = r.get('url', '')
            link = f'[{title}]({url})' if url else title
            st.caption(f'- {link} — {source}, {date}')


def _render_indicator_charts(comment: str, period: str):
    """코멘트에 언급된 지표의 최근 차트를 표시."""
    if not _MACRO_CSV.exists():
        return

    detected = {}
    for keyword, (col, label) in _CHART_KEYWORD_MAP.items():
        if keyword in comment and col not in detected:
            detected[col] = label

    if not detected:
        return

    df = pd.read_csv(_MACRO_CSV, index_col=0, parse_dates=True)

    if '-Q' in period:
        year = int(period[:4])
        q = int(period[-1])
        start_month = (q - 1) * 3 + 1
        end_month = q * 3
        start_date = pd.Timestamp(year, start_month, 1)
        # 분기 말일: end_month의 다음달 1일 - 1일
        end_date = pd.Timestamp(year, end_month, 1) + pd.DateOffset(months=1) - pd.DateOffset(days=1)
    else:
        start_date = pd.Timestamp(period + '-01')
        end_date = start_date + pd.DateOffset(months=1) - pd.DateOffset(days=1)

    available = [(col, label) for col, label in detected.items() if col in df.columns]
    if not available:
        return

    import plotly.graph_objects as go

    st.markdown('---')
    st.markdown('**관련 지표 추이**')

    cols_per_row = 3
    for i in range(0, len(available), cols_per_row):
        row_items = available[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for j, (col, label) in enumerate(row_items):
            with cols[j]:
                series = df.loc[start_date:end_date, col].dropna()
                if series.empty:
                    st.caption(f'{label}: 데이터 없음')
                    continue
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=series.index, y=series.values,
                    mode='lines', name=label,
                    line=dict(width=2, color='#636EFA')))
                last_val = series.iloc[-1]
                first_val = series.iloc[0]
                chg = last_val - first_val
                chg_pct = (chg / first_val * 100) if first_val != 0 else 0
                color = '#EF553B' if chg >= 0 else '#636EFA'
                y_min, y_max = series.min(), series.max()
                y_margin = (y_max - y_min) * 0.05 if y_max != y_min else abs(y_min) * 0.01
                fig.update_layout(
                    title=dict(text=f'{label}', font=dict(size=12)),
                    height=200,
                    margin=dict(t=30, b=20, l=40, r=10),
                    showlegend=False,
                    xaxis=dict(showgrid=False),
                    yaxis=dict(showgrid=True, gridcolor='#f0f0f0',
                               range=[y_min - y_margin, y_max + y_margin]))
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                st.caption(
                    f'최신: {last_val:,.2f} | '
                    f'변동: <span style="color:{color}">{chg:+,.2f} ({chg_pct:+.1f}%)</span>',
                    unsafe_allow_html=True)


def _load_comment_for_client(period: str, fund_code: str | None = None) -> dict | None:
    """Client용: approved final만 반환. draft/legacy는 절대 반환하지 않는다."""
    from market_research.report.report_store import load_final, list_approved_funds

    if fund_code:
        return load_final(period, fund_code)
    approved = list_approved_funds(period)
    if approved:
        return load_final(period, approved[0])
    return None


def _load_comment_for_admin(period: str, fund_code: str | None = None) -> dict | None:
    """Admin용: final → draft 순으로 반환. legacy fallback 없음."""
    from market_research.report.report_store import (
        load_final, load_draft, list_approved_funds,
    )

    if fund_code:
        final = load_final(period, fund_code)
        if final:
            return final
        draft = load_draft(period, fund_code)
        if draft:
            return draft
    else:
        approved = list_approved_funds(period)
        if approved:
            return load_final(period, approved[0])

    return None


def render_macro(_ctx=None):
    """시장 코멘트 뷰어.

    - Client 모드 (기본): approved final만 표시. draft/warning/evidence raw 미노출.
    - Admin 모드: draft + final + evidence quality + warning + 메타데이터 모두 표시.
    """
    st.markdown("#### 시장 코멘트")

    # 현재는 내부 운영용 role flag 기반 UI 분기.
    # production-grade auth는 범위 밖. 지금은 운영상 분리.
    is_admin = st.session_state.get('user_role') == 'admin'

    from market_research.report.report_store import (
        list_periods, list_approved_periods, list_approved_funds,
        list_funds_in_period,
    )

    # 기간 목록: admin은 모든 기간, client는 승인된 기간만
    if is_admin:
        all_periods = list_periods()
    else:
        all_periods = list_approved_periods()

    if not all_periods:
        st.info("승인된 코멘트가 아직 없습니다." if not is_admin else "발행된 코멘트가 없습니다.")
        return

    selected_period = st.selectbox("기간", all_periods, index=0, key="macro_pub_select")

    # 시장 코멘트는 항상 _market 고정 (펀드 드롭다운 없음)
    _MARKET_CODE = '_market'
    if is_admin:
        data = _load_comment_for_admin(selected_period, _MARKET_CODE)
    else:
        data = _load_comment_for_client(selected_period, _MARKET_CODE)

    if not data:
        if is_admin:
            st.warning(f"{selected_period} 발행본을 찾을 수 없습니다.")
        else:
            st.info("승인된 코멘트가 아직 없습니다.")
        return

    status = data.get('status', '')

    # ── 메타 정보 ──
    meta_parts = []
    if data.get('generated_at'):
        meta_parts.append(f"생성: {data['generated_at']}")
    elif data.get('debated_at'):
        meta_parts.append(f"생성: {data['debated_at']}")
    if data.get('approved_at'):
        meta_parts.append(f"승인: {data['approved_at']}")
    if meta_parts:
        st.caption(" | ".join(meta_parts))

    # ── 코멘트 본문 ──
    comment = data.get('final_comment') or data.get('customer_comment') or data.get('draft_comment', '')
    annotations = data.get('evidence_annotations', [])
    related_news = data.get('related_news', [])

    if comment:
        _render_comment_with_sources(comment, annotations, related_news)
    else:
        st.info("코멘트가 비어 있습니다.")

    # 관련 지표 차트
    if comment:
        _render_indicator_charts(comment, selected_period)

    # ── Admin 전용 섹션 ──
    if is_admin:
        # Evidence quality 요약
        eq = data.get('evidence_quality', data.get('_evidence_quality', {}))
        if eq:
            st.markdown('---')
            st.markdown('**Evidence Quality**')
            cols_eq = st.columns(4)
            with cols_eq[0]:
                st.metric("Total Refs", eq.get('total_refs', 0))
            with cols_eq[1]:
                st.metric("Ref Mismatches", eq.get('ref_mismatches', 0))
            with cols_eq[2]:
                st.metric("Tense Mismatches", eq.get('tense_mismatches', 0))
            with cols_eq[3]:
                rate = eq.get('mismatch_rate', 0)
                st.metric("Mismatch Rate", f"{rate:.1%}")

        # Warning summary
        val_summary = data.get('validation_summary', {})
        wc = val_summary.get('warning_counts', {})
        if wc:
            st.markdown('---')
            st.markdown('**Warning Summary**')
            cols_wc = st.columns(3)
            with cols_wc[0]:
                c = wc.get('critical', 0)
                st.metric("Critical", c, delta_color="inverse" if c > 0 else "off")
            with cols_wc[1]:
                st.metric("Warning", wc.get('warning', 0))
            with cols_wc[2]:
                st.metric("Info", wc.get('info', 0))

        # 상태 표시
        if status:
            label_map = {
                'draft_generated': 'Draft',
                'edited': '수정됨',
                'approved': '승인완료',
            }
            st.caption(f"상태: {label_map.get(status, status)}")

    # (합의/쟁점/테일리스크는 Admin(운용보고_매크로) 탭에서 확인)


# ══════════════════════════════════════════
# 헬퍼
# ══════════════════════════════════════════

def _show_cli_guide(fund_code, period=None):
    st.markdown("---")
    st.markdown("**CLI에서 코멘트를 생성하세요:**")
    if period and 'Q' in period:
        year = period[:4]
        quarter = period[-1]
        st.code(f"python -m market_research.report.cli build {fund_code} -q {quarter} -y {year}")
    else:
        st.code(f"python -m market_research.report.cli build {fund_code} -q 1 -y 2026")
    st.caption("--edit 옵션으로 debate 결과를 수정할 수 있습니다.")


# legacy 호환
def render(_ctx=None):
    render_pa(_ctx)
