# -*- coding: utf-8 -*-
"""Report tab UI — 순수 JSON 뷰어.

v5: CLI에서 생성된 JSON만 읽고 표시. LLM 호출 없음.
    - 월별 캐시: report_cache/{YYYY-MM}/{fund_code}.json (version 2~3)
    - 분기별 캐시: report_cache/{YYYY}Q{N}/{fund_code}.json (version 4)
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

DISPLAY_ASSET_CLASSES = ["국내주식", "해외주식", "국내채권", "해외채권", "대체투자"]


# ══════════════════════════════════════════
# JSON 로딩 유틸리티
# ══════════════════════════════════════════

def _load_catalog():
    if not _CATALOG_PATH.exists():
        return None
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def _available_periods():
    """캐시 디렉토리에서 사용 가능한 기간 목록 반환."""
    periods = []
    if not _CACHE_ROOT.exists():
        return periods
    for d in sorted(_CACHE_ROOT.iterdir()):
        if d.is_dir() and d.name not in ('__pycache__',):
            # 분기: 2026Q1, 월: 2026-03
            periods.append(d.name)
    return periods


def _load_period_funds(period_name):
    """특정 기간 디렉토리의 펀드 JSON 목록."""
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
    """기간+펀드 JSON 로드."""
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
    """PA 기여도 + 코멘트 뷰어. CLI에서 생성된 JSON만 표시."""
    st.markdown("#### 운용보고 — 코멘트 뷰어")

    fund_code = _ctx["selected_fund"] if _ctx else None
    if not fund_code:
        st.info("상단에서 펀드를 선택하세요.")
        return

    # ── 기간 선택 ──
    periods = _available_periods()
    if not periods:
        st.warning("캐시된 보고서가 없습니다.")
        _show_cli_guide(fund_code)
        return

    # 선택한 펀드가 포함된 기간만 필터
    valid_periods = [p for p in periods if fund_code in _load_period_funds(p)]
    if not valid_periods:
        st.info(f"{fund_code}의 캐시된 보고서가 없습니다.")
        _show_cli_guide(fund_code)
        return

    selected_period = st.selectbox(
        "기간", valid_periods,
        index=len(valid_periods) - 1,  # 최신
        key="report_period_select",
    )

    # ── JSON 로드 ──
    payload = _load_payload(selected_period, fund_code)
    if not payload:
        st.warning(f"{selected_period}/{fund_code} 데이터 없음.")
        return

    version = payload.get("version", 0)

    # data는 version 4에서 'data', version 2~3에서 'context'
    data = payload.get("data") or payload.get("context", {})
    output = payload.get("output", {})
    inputs = payload.get("inputs", {})

    st.caption(
        f"v{version} | 생성: {payload.get('generated_at', '?')[:16]}"
    )

    # ══════════════════════════════════════════
    # 코멘트 표시
    # ══════════════════════════════════════════
    comment = output.get("comment", "")
    if comment:
        st.markdown("---")
        st.markdown("**코멘트**")

        # 편집 가능 텍스트 영역
        edited = st.text_area(
            "코멘트 내용", value=comment, height=400,
            key="report_comment_editor", label_visibility="collapsed",
        )

        # 메타 정보
        meta_cols = st.columns(3)
        with meta_cols[0]:
            st.caption(f"모델: {output.get('model', '?')}")
        with meta_cols[1]:
            usage = output.get('token_usage', {})
            st.caption(f"토큰: {usage.get('input_tokens', 0)} in + {usage.get('output_tokens', 0)} out")
        with meta_cols[2]:
            st.caption(f"비용: ${output.get('cost', 0):.4f}")

        # 다운로드
        st.download_button(
            "다운로드 (.txt)",
            data=edited.encode("utf-8"),
            file_name=f"report_{selected_period}_{fund_code}.txt",
            mime="text/plain", key="report_download",
        )

        # inputs 확인
        if inputs:
            with st.expander("입력 데이터 (inputs)"):
                source = inputs.get("source", "?")
                st.caption(f"source: {source}")
                for key in ["market_view", "position_rationale", "outlook", "risk", "additional"]:
                    val = inputs.get(key, "")
                    if val:
                        st.markdown(f"**{key}**")
                        st.text(val[:300])
    else:
        st.info("코멘트가 아직 생성되지 않았습니다.")
        _show_cli_guide(fund_code, selected_period)

    # ══════════════════════════════════════════
    # 데이터 테이블
    # ══════════════════════════════════════════
    st.markdown("---")

    pa = data.get("pa", {})
    holdings = data.get("holdings") or data.get("holdings_end", {})
    fund_ret = data.get("fund_ret")

    # 펀드 수익률
    if fund_ret:
        ret_val = fund_ret.get("return") if isinstance(fund_ret, dict) else fund_ret
        if ret_val is not None:
            st.metric("펀드 수익률", f"{ret_val:+.2f}%")

    # 자산군별 기여수익률
    if pa:
        st.markdown("**자산군별 기여수익률**")
        summary_rows = []
        total_weight = 0.0
        total_contrib = 0.0
        display_classes = DISPLAY_ASSET_CLASSES + ["유동성"]
        for asset_class in display_classes:
            contrib = _get_asset_value(pa, asset_class)
            weight = _get_asset_value(holdings, asset_class)
            total_weight += weight
            total_contrib += contrib
            if abs(contrib) >= 0.005 or weight > 0.1:
                summary_rows.append({
                    "자산군": asset_class,
                    "보유비중": f"{weight:.1f}%",
                    "기여수익률": f"{contrib:+.2f}%",
                })
        fee_contrib = _get_asset_value(pa, "보수비용")
        if abs(fee_contrib) >= 0.005:
            total_contrib += fee_contrib
            summary_rows.append({
                "자산군": "보수비용",
                "보유비중": "-",
                "기여수익률": f"{fee_contrib:+.2f}%",
            })
        summary_rows.append({
            "자산군": "계",
            "보유비중": f"{total_weight:.1f}%",
            "기여수익률": f"{total_contrib:+.2f}%",
        })
        if summary_rows:
            st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)

    # 종목별 기여도 상세
    pa_items = data.get("pa_items")
    if pa_items:
        with st.expander("종목별 기여도 상세", expanded=False):
            pa_df = pd.DataFrame(pa_items)
            if not pa_df.empty:
                pa_df = pa_df.sort_values(["asset_class", "item_name"], ascending=True).copy()
                pa_df["item_name"] = pa_df["item_name"].map(_clean_item_name)
                display_cols = ["asset_class", "item_name"]
                pa_df["기여도"] = pa_df["contrib_pct"].map(lambda v: f"{v:+.2f}%")
                if "weight_pct" in pa_df.columns:
                    pa_df["비중"] = pa_df["weight_pct"].map(lambda v: f"{v:.1f}%")
                    display_cols.append("비중")
                if "item_return_pct" in pa_df.columns:
                    pa_df["Normalized 수익률"] = pa_df["item_return_pct"].map(lambda v: f"{v:+.2f}%")
                    display_cols.append("Normalized 수익률")
                display_cols.append("기여도")
                total_row = {"자산군": "계", "종목명": ""}
                if "weight_pct" in pa_df.columns:
                    total_row["비중"] = f'{pa_df["weight_pct"].sum():.1f}%'
                if "item_return_pct" in pa_df.columns:
                    total_row["Normalized 수익률"] = "-"
                total_row["기여도"] = f'{pa_df["contrib_pct"].sum():+.2f}%'
                total_df = pd.concat([
                    pa_df[display_cols].rename(columns={"asset_class": "자산군", "item_name": "종목명"}),
                    pd.DataFrame([total_row]),
                ], ignore_index=True)
                st.dataframe(total_df, hide_index=True, use_container_width=True)

    # 비중 변화
    holdings_diff = data.get("holdings_diff", [])
    if holdings_diff:
        with st.expander("비중 변화", expanded=False):
            diff_rows = []
            for d in holdings_diff:
                diff_rows.append({
                    "자산군": d["asset_class"],
                    "이전": f"{d['prev']:.1f}%",
                    "현재": f"{d['cur']:.1f}%",
                    "변화": f"{d['change']:+.1f}%p",
                    "방향": d["direction"],
                })
            st.dataframe(pd.DataFrame(diff_rows), hide_index=True, use_container_width=True)


# ══════════════════════════════════════════
# 운용보고(전체) 탭 — 발행 코멘트 조회
# ══════════════════════════════════════════

_PUBLISHED_DIR = Path(__file__).resolve().parent.parent / 'market_research' / 'data' / 'debate_published'
_MACRO_CSV = Path(__file__).resolve().parent.parent / 'market_research' / 'data' / 'macro' / 'indicators.csv'

# 코멘트에서 탐지할 지표 키워드 → indicators.csv 컬럼 매핑
_CHART_KEYWORD_MAP = {
    # 달러/환율
    'DXY': ('DXY', '달러인덱스 (DXY)'),
    '달러인덱스': ('DXY', '달러인덱스 (DXY)'),
    'USDKRW': ('USDKRW', '원/달러 환율'),
    '원/달러': ('USDKRW', '원/달러 환율'),
    '원·달러': ('USDKRW', '원/달러 환율'),
    '달러/원': ('USDKRW', '원/달러 환율'),
    '선물환': ('F_USDKRW', '달러/원 선물환'),
    'F_USDKRW': ('F_USDKRW', '달러/원 선물환'),
    # 금리
    'UST 2Y': ('UST_2Y', '미국채 2년 (%)'),
    'UST 10Y': ('UST_10Y', '미국채 10년 (%)'),
    '미국채 2년': ('UST_2Y', '미국채 2년 (%)'),
    '미국채 10년': ('UST_10Y', '미국채 10년 (%)'),
    '미 국채': ('UST_10Y', '미국채 10년 (%)'),
    '미국 국채': ('UST_10Y', '미국채 10년 (%)'),
    '2년-10년': ('US_2Y10Y', '미국채 2Y-10Y 스프레드'),
    # 변동성
    'MOVE': ('MOVE', 'MOVE 지수'),
    'VIX': ('VIX', 'VIX 지수'),
    '변동성 지수': ('MOVE', 'MOVE 지수'),
    # 주식
    'KOSPI': ('MSCI_KOREA', 'MSCI Korea'),
    'S&P': ('SP500_TR', 'S&P 500 TR'),
    'STOXX': ('MSCI_EAFE', 'MSCI EAFE (선진국)'),
    # 원자재
    'WTI': ('WTI', 'WTI 원유 ($/배럴)'),
    '유가': ('WTI', 'WTI 원유 ($/배럴)'),
    '국제유가': ('WTI', 'WTI 원유 ($/배럴)'),
    'GOLD': ('GOLD', '금 ($/oz)'),
    '금': ('GOLD', '금 ($/oz)'),
    '브렌트': ('BRENT', '브렌트유 ($/배럴)'),
}


def _render_comment_with_sources(comment: str, annotations: list):
    """코멘트를 문단 분리 + 하단 출처 목록으로 렌더링. inline ref는 제거."""
    import re

    # client: inline ref 완전 제거 (ref 오매핑 방지)
    display = re.sub(r'\s*\[ref:\d+\]', '', comment)
    display = re.sub(r'\s*\d+\)', '', display)  # 첨자 N) 형태도 제거

    # 문단 분리
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

    # 하단 출처 목록 (번호 없이, 기사 정보만)
    if annotations:
        st.markdown('---')
        st.markdown('**참고 뉴스**')
        for ann in annotations:
            title = ann.get('title', '')
            source = ann.get('source', '')
            date = ann.get('date', '')
            url = ann.get('url', '')
            if url:
                st.caption(f'- [{title}]({url}) — {source}, {date}')
            else:
                st.caption(f'- {title} — {source}, {date}')


def _render_indicator_charts(comment: str, period: str):
    """코멘트에 언급된 지표의 최근 3개월 차트를 표시."""
    if not _MACRO_CSV.exists():
        return

    import pandas as pd

    # 언급된 지표 탐지
    detected = {}
    for keyword, (col, label) in _CHART_KEYWORD_MAP.items():
        if keyword in comment and col not in detected:
            detected[col] = label

    if not detected:
        return

    df = pd.read_csv(_MACRO_CSV, index_col=0, parse_dates=True)

    # 기간: 해당 월의 1일 ~ 말일 (운용보고와 동일 구간)
    if '-Q' in period:
        year = int(period[:4])
        q = int(period[-1])
        start_month = (q - 1) * 3 + 1
        end_month = q * 3
        start_date = pd.Timestamp(year, start_month, 1)
        end_date = pd.Timestamp(year, end_month, 28) + pd.DateOffset(days=3)
        end_date = end_date - pd.DateOffset(days=end_date.day)  # 말일
    else:
        start_date = pd.Timestamp(period + '-01')
        end_date = start_date + pd.DateOffset(months=1) - pd.DateOffset(days=1)

    available = [(col, label) for col, label in detected.items() if col in df.columns]
    if not available:
        return

    import plotly.graph_objects as go

    st.markdown('---')
    st.markdown('**관련 지표 추이**')

    # 3열 레이아웃
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
                    line=dict(width=2, color='#636EFA'),
                ))
                last_val = series.iloc[-1]
                first_val = series.iloc[0]
                chg = last_val - first_val
                chg_pct = (chg / first_val * 100) if first_val != 0 else 0
                color = '#EF553B' if chg >= 0 else '#636EFA'
                # y축: 데이터 min/max에 5% 여유
                y_min, y_max = series.min(), series.max()
                y_margin = (y_max - y_min) * 0.05 if y_max != y_min else abs(y_min) * 0.01
                fig.update_layout(
                    title=dict(text=f'{label}', font=dict(size=12)),
                    height=200,
                    margin=dict(t=30, b=20, l=40, r=10),
                    showlegend=False,
                    xaxis=dict(showgrid=False),
                    yaxis=dict(
                        showgrid=True, gridcolor='#f0f0f0',
                        range=[y_min - y_margin, y_max + y_margin],
                    ),
                )
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                st.caption(
                    f'최신: {last_val:,.2f} | '
                    f'변동: <span style="color:{color}">{chg:+,.2f} ({chg_pct:+.1f}%)</span>',
                    unsafe_allow_html=True,
                )


def render_macro(_ctx=None):
    """발행된 시장 코멘트 조회 (읽기 전용)."""
    st.markdown("#### 시장 코멘트")

    if not _PUBLISHED_DIR.exists():
        st.warning("발행된 코멘트가 없습니다.")
        return

    pub_files = sorted(_PUBLISHED_DIR.glob("*.json"), reverse=True)
    if not pub_files:
        st.warning("발행된 코멘트가 없습니다.")
        return

    period_options = [f.stem for f in pub_files]
    selected = st.selectbox("기간", period_options, index=0, key="macro_pub_select")

    pub_file = _PUBLISHED_DIR / f"{selected}.json"
    if not pub_file.exists():
        st.warning(f"{selected} 발행본을 찾을 수 없습니다.")
        return

    data = json.loads(pub_file.read_text(encoding='utf-8'))

    # 메타 정보
    debated_at = data.get('debated_at', '')
    edited_at = data.get('edited_at', '')
    meta_parts = [f"debate 생성: {debated_at}"]
    if edited_at:
        meta_parts.append(f"최종수정: {edited_at}")
    st.caption(" | ".join(meta_parts))

    # 코멘트 (문단 분리 + 하단 출처 목록, inline ref 제거)
    customer_comment = data.get('customer_comment', '')
    annotations = data.get('evidence_annotations', [])

    if customer_comment:
        _render_comment_with_sources(customer_comment, annotations)
    else:
        st.info("코멘트가 비어 있습니다.")

    # 관련 지표 차트
    _render_indicator_charts(customer_comment, selected)

    # 합의 / 쟁점 / 테일리스크
    with st.expander("합의 / 쟁점 / 테일리스크", expanded=False):
        consensus = data.get('consensus_points', [])
        if consensus:
            st.markdown("**합의**")
            for p in consensus:
                st.markdown(f"- {p}")

        disagreements = data.get('disagreements', [])
        if disagreements:
            st.markdown("**쟁점**")
            for d in disagreements:
                if isinstance(d, dict):
                    st.markdown(f"**[{d.get('topic', '')}]**")
                    for role in ('bull', 'bear', 'quant', 'monygeek'):
                        if d.get(role):
                            st.caption(f"  {role}: {d[role]}")

        tail_risks = data.get('tail_risks', [])
        if tail_risks:
            st.markdown("**테일 리스크**")
            for t in tail_risks:
                st.markdown(f"- {t}")


# ══════════════════════════════════════════
# 헬퍼
# ══════════════════════════════════════════

def _show_cli_guide(fund_code, period=None):
    """CLI 실행 안내."""
    st.markdown("---")
    st.markdown("**CLI에서 코멘트를 생성하세요:**")
    if period and 'Q' in period:
        year = period[:4]
        quarter = period[-1]
        st.code(f"python -m market_research.report_cli build {fund_code} -q {quarter} -y {year}")
    else:
        st.code(f"python -m market_research.report_cli build {fund_code} -q 1 -y 2026")
    st.caption("--edit 옵션으로 debate 결과를 수정할 수 있습니다.")


# legacy 호환
def render(_ctx=None):
    render_pa(_ctx)
