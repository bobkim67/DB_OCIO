# -*- coding: utf-8 -*-
"""Admin(운용보고_매크로) — 시장 전체 debate workflow.

시장 전체에 대한 4인 debate 실행 → 검토 → 수정 → 승인.
펀드별 코멘트 생성은 Admin(운용보고_펀드) 탭에서 별도 수행.
"""

import re
from datetime import datetime

import pandas as pd
import streamlit as st

from market_research.report.report_store import (
    load_draft, load_final, update_draft_comment,
    approve_and_save_final, save_draft,
    get_status, load_evidence_quality_records,
    STATUS_NOT_GENERATED, STATUS_DRAFT, STATUS_EDITED, STATUS_APPROVED,
    OUTPUT_DIR,
)
from market_research.report.debate_service import (
    run_debate_and_save, METRICS_GUIDE,
)

# 시장 debate는 펀드 무관 → 고정 코드 사용
_MARKET_FUND_CODE = '_market'


def _status_label(status: str) -> str:
    return {
        STATUS_NOT_GENERATED: '미생성',
        STATUS_DRAFT: 'Draft',
        STATUS_EDITED: '수정됨',
        STATUS_APPROVED: '승인완료',
    }.get(status, status)


def _get_comment_text(draft: dict) -> str:
    """draft에서 표시할 코멘트 텍스트를 추출. legacy fallback 포함."""
    text = draft.get('draft_comment', '')
    if not text:
        text = draft.get('customer_comment', '')
    if not text:
        raw = draft.get('admin_comment', '') or draft.get('admin_comment_raw', '')
        if raw:
            text = re.sub(r'\[ref:(\d+)\]', r' \1)', raw)
    return text


def render(ctx):
    """Admin(운용보고_매크로) 탭."""
    st.markdown("#### 시장 Debate — 매크로 코멘트 생성")
    st.caption("시장 전체에 대한 4인 debate를 실행하고 코멘트를 검수합니다. 펀드별 코멘트는 별도 탭에서 생성합니다.")

    # ── 기간 선택 (마지막 생성 기간 기준 디폴트) ──
    from market_research.report.report_store import get_latest_market_period
    latest = get_latest_market_period()
    # 디폴트 파싱: "2026-Q1" → 분기/2026/1, "2026-04" → 월별/2026/4
    if latest and '-Q' in latest:
        _def_mode, _def_year, _def_num = '분기', int(latest[:4]), int(latest[-1])
    elif latest and '-' in latest:
        _def_mode, _def_year, _def_num = '월별', int(latest[:4]), int(latest[5:7])
    else:
        _def_mode = '월별'
        _def_year = datetime.now().year
        _def_num = max(1, datetime.now().month - 1)  # 전월

    col_mode, col_year, col_period = st.columns([1, 1, 1])
    with col_mode:
        mode = st.radio("기간 유형", ["월별", "분기"], index=["월별", "분기"].index(_def_mode),
                        horizontal=True, key="admm_mode")
    with col_year:
        year = st.number_input("년도", min_value=2025, max_value=2030,
                               value=_def_year, key="admm_year")
    with col_period:
        if mode == "월별":
            def_month = _def_num if _def_mode == '월별' else max(1, datetime.now().month - 1)
            period_num = st.number_input("월", min_value=1, max_value=12,
                                         value=def_month, key="admm_month")
            period_key = f"{year}-{period_num:02d}"
        else:
            def_q = _def_num if _def_mode == '분기' else (datetime.now().month - 1) // 3 + 1
            period_num = st.number_input("분기", min_value=1, max_value=4,
                                         value=def_q, key="admm_quarter")
            period_key = f"{year}-Q{period_num}"

    # ── 현재 상태 ──
    current_status = get_status(period_key, _MARKET_FUND_CODE)
    draft = load_draft(period_key, _MARKET_FUND_CODE)
    final = load_final(period_key, _MARKET_FUND_CODE)

    col_status, col_actions = st.columns([2, 1])
    with col_status:
        label = _status_label(current_status)
        if current_status == STATUS_APPROVED:
            st.success(f"상태: {label} | 승인: {final.get('approved_at', '?')}")
        elif current_status in (STATUS_DRAFT, STATUS_EDITED):
            gen_at = draft.get('generated_at', draft.get('debated_at', '?')) if draft else '?'
            st.info(f"상태: {label} | 생성: {gen_at}")
        else:
            st.warning(f"상태: {label}")

    with col_actions:
        generate = st.button("Debate 실행", key="admm_gen",
                             type="primary", use_container_width=True,
                             disabled=(current_status == STATUS_APPROVED))

    # ── Debate 실행 ──
    if generate:
        with st.spinner("4인 debate 실행 중... (1~2분 소요)"):
            try:
                draft = run_debate_and_save(mode, year, period_num, _MARKET_FUND_CODE, period_key)
                st.success(f"debate 완료 (생성: {draft.get('generated_at', '')})")
                st.rerun()
            except Exception as exc:
                st.error(f"debate 실패: {exc}")

    # ── Draft 검토/수정/승인 ──
    if draft and current_status != STATUS_NOT_GENERATED:
        st.markdown("---")

        st.markdown("##### Admin Summary")
        st.caption(draft.get('admin_summary', ''))

        with st.expander("합의 / 쟁점 / 테일리스크", expanded=False):
            st.markdown("**합의**")
            for p in draft.get('consensus_points', []):
                st.markdown(f"- {p}")
            st.markdown("**쟁점**")
            for d in draft.get('disagreements', []):
                if isinstance(d, dict):
                    st.markdown(f"**[{d.get('topic', '')}]**")
                    for role in ('bull', 'bear', 'quant', 'monygeek'):
                        if d.get(role):
                            st.caption(f"  {role}: {d[role]}")
            st.markdown("**테일 리스크**")
            for t in draft.get('tail_risks', []):
                st.markdown(f"- {t}")

        guide = draft.get('internal_metrics_guide', METRICS_GUIDE)
        if guide:
            with st.expander("내부 지표 가이드", expanded=False):
                for k, v in guide.items():
                    st.markdown(f"**{k}**: {v}")

        # Comment 수정
        st.markdown("##### Comment (수정 가능)")
        comment_text = _get_comment_text(draft)

        if comment_text and '\n' not in comment_text:
            sentences = re.split(r'(?<=[.다])\s+', comment_text)
            chunk_size = max(3, len(sentences) // 4)
            paragraphs = []
            for i in range(0, len(sentences), chunk_size):
                paragraphs.append(' '.join(sentences[i:i + chunk_size]))
            comment_text = '\n\n'.join(paragraphs)

        ta_key = f"admm_edit_{period_key}_{draft.get('generated_at', draft.get('debated_at', ''))}"
        edited = st.text_area("코멘트 수정", value=comment_text, height=400,
                              key=ta_key, label_visibility="collapsed",
                              disabled=(current_status == STATUS_APPROVED))

        col_save, col_approve, col_reset = st.columns([1, 1, 1])
        with col_save:
            if st.button("Draft 저장", key="admm_save", use_container_width=True,
                         disabled=(current_status == STATUS_APPROVED)):
                update_draft_comment(period_key, _MARKET_FUND_CODE, edited)
                st.success("Draft 저장 완료")
                st.rerun()
        with col_approve:
            if st.button("최종 승인", key="admm_approve", type="primary",
                          use_container_width=True,
                          disabled=(current_status == STATUS_APPROVED)):
                update_draft_comment(period_key, _MARKET_FUND_CODE, edited)
                path = approve_and_save_final(period_key, _MARKET_FUND_CODE)
                st.success(f"승인 완료: {path.name if path else '?'}")
                st.rerun()
        with col_reset:
            if current_status == STATUS_APPROVED:
                if st.button("승인 해제 (재수정)", key="admm_reset",
                             use_container_width=True):
                    fp = OUTPUT_DIR / period_key / f'{_MARKET_FUND_CODE}.final.json'
                    if fp.exists():
                        fp.unlink()
                    draft['status'] = STATUS_EDITED
                    save_draft(period_key, _MARKET_FUND_CODE, draft)
                    st.info("승인 해제됨.")
                    st.rerun()

        # 경고 요약
        val_summary = draft.get('validation_summary', {})
        sw_list = val_summary.get('sanitize_warnings', draft.get('_sanitize_warnings', []))

        critical_warns = [w for w in sw_list if isinstance(w, dict) and w.get('severity') == 'critical']
        warning_warns = [w for w in sw_list if isinstance(w, dict) and w.get('severity', 'warning') == 'warning']
        info_warns = [w for w in sw_list if isinstance(w, dict) and w.get('severity') == 'info']

        if sw_list:
            parts = []
            if critical_warns: parts.append(f'CRITICAL {len(critical_warns)}건')
            if warning_warns: parts.append(f'WARNING {len(warning_warns)}건')
            if info_warns: parts.append(f'INFO {len(info_warns)}건')

            if critical_warns:
                st.error(f'검수 필요: {" | ".join(parts)}')
                for w in critical_warns:
                    st.caption(f'&emsp;{w.get("message", "")}')
            elif warning_warns:
                st.warning(f'확인 권장: {" | ".join(parts)}')
                for w in warning_warns:
                    st.caption(f'&emsp;{w.get("message", "")}')
            if info_warns:
                with st.expander(f'INFO {len(info_warns)}건 (자동 처리됨)', expanded=False):
                    for w in info_warns:
                        st.caption(w.get('message', ''))

        # Evidence 상세
        annotations = draft.get('evidence_annotations', [])
        warn_refs = {}
        for w in sw_list:
            if isinstance(w, dict) and w.get('ref_no') is not None:
                warn_refs.setdefault(w['ref_no'], []).append(w.get('message', ''))

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
                rw = warn_refs.get(ref, [])
                icon = ' !!!' if rw else ''
                link = f'[{title}]({url})' if url else title
                st.caption(f'[ref:{ref}]{icon} {link} — {source}, {date} | 중요도 {sal:.2f} ({expl})')
                for wm in rw:
                    st.caption(f'&emsp;&emsp;!!! {wm}')

        # 관련 뉴스 (코멘트에 ref로 인용되지 않은 debate 입력 기사)
        related = draft.get('related_news', [])
        if related:
            st.markdown('---')
            st.markdown('**관련 뉴스**')
            for r in related:
                title = r.get('title', '')
                source = r.get('source', '')
                date = r.get('date', '')
                url = r.get('url', '')
                link = f'[{title}]({url})' if url else title
                st.caption(f'- {link} — {source}, {date}')

        # Evidence Quality
        eq = draft.get('evidence_quality', {})
        if eq:
            st.markdown('---')
            cols = st.columns(5)
            with cols[0]: st.metric("Total Refs", eq.get('total_refs', 0))
            with cols[1]: st.metric("Ref Mismatches", eq.get('ref_mismatches', 0))
            with cols[2]: st.metric("Tense Mismatches", eq.get('tense_mismatches', 0))
            with cols[3]: st.metric("Mismatch Rate", f"{eq.get('mismatch_rate', 0):.1%}")
            with cols[4]: st.metric("Evidence Count", eq.get('evidence_count', 0))

        # Coverage Metrics
        cov = draft.get('coverage_metrics', {})
        if cov:
            st.markdown('---')
            st.markdown('**Coverage**')
            cols_cov = st.columns(4)
            with cols_cov[0]:
                st.metric("가용 토픽", cov.get('available_topics_count', 0))
            with cols_cov[1]:
                st.metric("인용 토픽", cov.get('referenced_topics_count', 0))
            with cols_cov[2]:
                st.metric("인용 ref 수", cov.get('referenced_refs_count', 0))
            with cols_cov[3]:
                st.metric("수치 무출처", cov.get('uncited_numeric_count', 0))
            unreferenced = cov.get('unreferenced_topics', [])
            if unreferenced:
                st.caption(f'미인용 토픽: {", ".join(unreferenced)}')

    # ── 파일럿 모니터링 ──
    st.markdown("---")
    st.markdown("#### 파일럿 모니터링")
    records = load_evidence_quality_records()
    if records:
        eq_df = pd.DataFrame(records)
        st.dataframe(eq_df, hide_index=True, width="stretch")
        st.caption(f'누적 {len(eq_df)}회 | 평균 오매핑률 {eq_df["mismatch_rate"].mean():.1%}')
    else:
        st.info("debate 실행 기록 없음.")
