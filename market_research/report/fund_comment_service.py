# -*- coding: utf-8 -*-
"""Fund Comment Service — 펀드별 코멘트 생성 서비스.

시장 debate 산출물(final/edited draft)을 입력으로 받아,
펀드별 PA/보유비중/거래내역 데이터와 결합해 Opus로 코멘트를 생성한다.

이 모듈이 담당하는 것:
  - 시장 comment payload → 펀드 코멘트용 inputs 변환
  - 펀드 데이터 로딩 + 요약
  - comment_engine.build_report_prompt() / generate_report_from_inputs() 호출
  - fund draft 저장

이 모듈이 담당하지 않는 것:
  - Streamlit UI (st.* 호출 없음)
  - 시장 debate 실행 (debate_service.py 담당)
  - 뉴스 수집/분류/정제/GraphRAG (외부 배치 담당)
"""
from __future__ import annotations

import time
import uuid
from datetime import date

from market_research.report.report_store import (
    save_draft, load_draft, load_final,
    STATUS_DRAFT,
)

# fund draft는 별도 경로에 저장 (시장 debate와 분리)
FUND_REPORT_TYPE = 'fund'


# ══════════════════════════════════════════
# 시장 comment → inputs 변환
# ══════════════════════════════════════════

def _market_comment_to_inputs(market_payload: dict) -> dict:
    """시장 final/edited draft → 펀드 코멘트용 inputs dict.

    approved final 우선, 없으면 edited draft fallback.
    raw dict/list를 그대로 넣지 않고 LLM 친화적 텍스트로 정규화한다.
    """
    if not market_payload:
        return {}

    inputs = {'source': 'market_debate'}

    # market_view: 코멘트 본문 (final > draft)
    comment = (market_payload.get('final_comment', '')
               or market_payload.get('draft_comment', '')
               or market_payload.get('customer_comment', ''))
    if comment:
        inputs['market_view'] = comment

    # outlook: 합의 포인트 (자연어 bullet)
    consensus = market_payload.get('consensus_points', [])
    if consensus:
        bullets = [f'- {p}' for p in consensus[:3]]
        inputs['outlook'] = '\n'.join(bullets)

    # risk: 쟁점 + 테일리스크 (중복 제거, 텍스트 정리)
    risk_parts = []
    for d in market_payload.get('disagreements', [])[:3]:
        if isinstance(d, dict):
            topic = d.get('topic', '')
            bear = d.get('bear', '')
            if bear:
                risk_parts.append(f'- [{topic}] {bear}')
        elif isinstance(d, str):
            risk_parts.append(f'- {d}')
    for t in market_payload.get('tail_risks', [])[:2]:
        risk_parts.append(f'- [테일리스크] {t}')
    if risk_parts:
        inputs['risk'] = '\n'.join(risk_parts)

    # evidence_annotations 전달 (R6-A) — build_report_prompt 가 [ref:N] 인용 가능한
    # evidence 목록으로 변환. ref 번호는 시장 debate 가 부여한 값 그대로 사용.
    ann = market_payload.get('evidence_annotations') or []
    if ann:
        inputs['evidence_annotations'] = ann

    return inputs


# ══════════════════════════════════════════
# 펀드 데이터 요약 (프롬프트용)
# ══════════════════════════════════════════

def _adapt_compute_single_port_pa(pa_result: dict) -> dict:
    """compute_single_port_pa 의 새 schema (asset_summary DataFrame) 를
    fund_comment_service 가 사용하는 구버전 형태로 변환 (Q-FIX-2, 2026-05-06).

    배경:
      compute_single_port_pa 는 asset_summary / port_daily_returns / sec_summary
      등 DataFrame 중심 schema 로 진화했으나, generate_fund_comment_and_save 는
      구버전 키 (pa_by_class / fund_return / holdings_end / holdings_diff) 를
      dict.get() 함 → 모두 빈 dict / None 반환. 08K88 / 4JM12 / 08N81 등
      production 의 data_snapshot.fund_return=None 의 근본 원인.

    단위 변환:
      compute_single_port_pa : decimal (-0.0271 = -2.71%, 0.1199 = 11.99%)
      _summarize_fund_data_for_prompt : % 단위 (':+.2f%' 포매팅)
      → adapter 가 × 100 으로 % 단위 통일. round 4 자릿수.

    Returns:
        {
          'fund_return'  : float | None     # 포트폴리오 row 의 개별수익률 (%)
          'pa_by_class'  : dict[str, float] # 자산군 → 기여수익률 (%)
          'holdings_end' : dict[str, float] # 자산군 → 순자산비중 (%)
          'holdings_diff': list             # 미산출 (별도 task — sec 변동 비교 필요)
          'warnings'     : list[str]
        }

    asset_summary 가 None / DataFrame 아님 / 빈 결과 시 warning 기록 후 빈 dict 반환.
    """
    out = {
        'fund_return': None,
        'pa_by_class': {},
        'holdings_end': {},
        'holdings_diff': [],
        'warnings': [],
    }
    if not isinstance(pa_result, dict):
        out['warnings'].append('pa_result not a dict')
        return out
    asset_summary = pa_result.get('asset_summary')
    if asset_summary is None:
        out['warnings'].append('asset_summary missing in pa_result')
        return out
    if not hasattr(asset_summary, 'iterrows'):
        out['warnings'].append(
            f'asset_summary not DataFrame: type={type(asset_summary).__name__}'
        )
        return out
    if len(asset_summary) == 0:
        out['warnings'].append('asset_summary empty')
        return out

    PORT_LABEL = '포트폴리오'
    for _, row in asset_summary.iterrows():
        try:
            ac = row.get('자산군') if hasattr(row, 'get') else row['자산군']
        except Exception:
            continue
        if not ac:
            continue
        if ac == PORT_LABEL:
            try:
                ret = row.get('개별수익률') if hasattr(row, 'get') else row['개별수익률']
                if ret is not None:
                    out['fund_return'] = round(float(ret) * 100, 4)
            except (TypeError, ValueError, KeyError):
                pass
            continue
        # 자산군 row
        try:
            contrib = row.get('기여수익률') if hasattr(row, 'get') else row['기여수익률']
            if contrib is not None:
                out['pa_by_class'][ac] = round(float(contrib) * 100, 4)
        except (TypeError, ValueError, KeyError):
            pass
        try:
            wgh = row.get('순자산비중') if hasattr(row, 'get') else row['순자산비중']
            if wgh is not None:
                wgh_pct = round(float(wgh) * 100, 4)
                if wgh_pct > 0:  # 0 이상만 — 빈 자산군 제거
                    out['holdings_end'][ac] = wgh_pct
        except (TypeError, ValueError, KeyError):
            pass

    # holdings_diff 는 별도 task — sec_summary 또는 holdings_start vs end 비교 필요
    out['warnings'].append('holdings_diff not yet computed (Q-FIX-2 후속 task)')
    return out


def _summarize_fund_data_for_prompt(pa: dict, holdings: dict,
                                     trades: dict, bm: dict) -> dict:
    """원자료를 프롬프트에 넣기 좋은 요약본으로 축약.

    full raw table이 아닌 핵심만 추출.
    """
    summary = {}

    # PA: 상위 기여 3개 + 하위 기여 3개
    if pa:
        sorted_pa = sorted(pa.items(), key=lambda x: x[1], reverse=True)
        top3 = sorted_pa[:3]
        bottom3 = sorted_pa[-3:]
        pa_lines = []
        pa_lines.append('상위 기여:')
        for cls, v in top3:
            if abs(v) >= 0.01:
                pa_lines.append(f'  {cls}: {v:+.2f}%')
        pa_lines.append('하위 기여:')
        for cls, v in bottom3:
            if abs(v) >= 0.01:
                pa_lines.append(f'  {cls}: {v:+.2f}%')
        summary['pa_summary'] = '\n'.join(pa_lines)

    # 보유비중: 자산군별 비중
    if holdings:
        hold_lines = [f'  {cls}: {wt:.1f}%' for cls, wt in
                      sorted(holdings.items(), key=lambda x: -x[1]) if wt > 0.5]
        summary['holdings_summary'] = '\n'.join(hold_lines)

    # 거래내역: 순매수 상위 3개 + 순매도 상위 3개 (유동성 제외)
    if trades:
        non_cash = {k: v for k, v in trades.items() if k not in ('유동성', '모펀드')}
        sorted_trades = sorted(non_cash.items(), key=lambda x: x[1]['net'], reverse=True)
        trade_lines = []
        # 순매수 상위
        for cls, v in sorted_trades[:3]:
            if v['net'] > 0:
                trade_lines.append(f'- {cls} 순매수 {v["net"]:+.1f}억')
        # 순매도 상위
        for cls, v in sorted_trades[-3:]:
            if v['net'] < 0:
                trade_lines.append(f'- {cls} 순매도 {v["net"]:+.1f}억')
        if trade_lines:
            summary['trades_summary'] = '\n'.join(trade_lines)

    return summary


# ══════════════════════════════════════════
# 펀드 코멘트 생성 + 저장
# ══════════════════════════════════════════

def _resolve_dates(mode: str, year: int, period_num: int):
    """기간 유형에 따른 영업일 범위 계산."""
    from market_research.report.comment_engine import (
        load_business_days, load_business_days_quarter,
    )
    if mode == '분기':
        bdays = load_business_days_quarter(year, period_num)
        quarter = period_num
    else:
        bdays = load_business_days(year, period_num)
        quarter = (period_num - 1) // 3 + 1

    if not bdays:
        return None, None, None, None, quarter

    # load_business_days returns dict: {prev_month_last, cur_month_last, business_days, ...}
    if isinstance(bdays, dict):
        prev_last = bdays.get('prev_month_last')
        cur_last = bdays.get('cur_month_last')
    else:
        # list fallback
        cur_last = bdays[-1]
        prev_last = bdays[0]

    if not prev_last or not cur_last:
        return None, None, None, None, quarter

    def _int_to_date(d):
        s = str(int(d))
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))

    start_dt = _int_to_date(prev_last)
    end_dt = _int_to_date(cur_last)
    return int(prev_last), int(cur_last), start_dt, end_dt, quarter


def generate_fund_comment_and_save(
    mode: str, year: int, period_num: int,
    fund_code: str, period_key: str,
    market_payload: dict,
) -> dict:
    """펀드 코멘트 생성: 데이터 로딩 → 시장 payload 변환 → Opus 호출 → fund draft 저장.

    Streamlit 의존성 없음. tabs/admin_fund.py에서 호출한다.

    Parameters
    ----------
    mode : '월별' | '분기'
    year, period_num : 연도, 월(1~12) 또는 분기(1~4)
    fund_code : 펀드코드 (e.g. '08P22')
    period_key : 기간 키 (e.g. '2026-04', '2026-Q1')
    market_payload : 시장 debate final/edited draft (load_final 또는 load_draft 결과)
    """
    data_warnings = []

    # 1. 영업일 범위
    prev_last, cur_last, start_dt, end_dt, quarter = _resolve_dates(mode, year, period_num)
    if not cur_last:
        data_warnings.append(f'{period_key} 영업일 데이터 없음')

    # 2. BM 수익률
    bm = {}
    if prev_last and cur_last:
        try:
            from market_research.report.comment_engine import _load_bm_returns_for_range
            bm = _load_bm_returns_for_range(prev_last, cur_last)
        except Exception as e:
            data_warnings.append(f'BM 수익률 로드 실패: {e}')

    # 3. PA 기여도 + 보유비중
    pa = {}
    fund_ret = None
    holdings_end = {}
    holdings_diff = []
    if start_dt and end_dt:
        try:
            from modules.data_loader import compute_single_port_pa
            pa_result = compute_single_port_pa(
                fund_code,
                start_date=start_dt.strftime('%Y%m%d'),
                end_date=end_dt.strftime('%Y%m%d'),
            )
            if pa_result:
                # Q-FIX-2 (2026-05-06): asset_summary DataFrame 새 schema → 구버전 키 변환
                adapted = _adapt_compute_single_port_pa(pa_result)
                pa = adapted['pa_by_class']
                fund_ret = adapted['fund_return']
                holdings_end = adapted['holdings_end']
                holdings_diff = adapted['holdings_diff']
                for w in adapted.get('warnings', []):
                    data_warnings.append(f'PA adapter: {w}')
        except Exception as e:
            data_warnings.append(f'PA 데이터 로드 실패: {e}')

    # 4. 거래내역
    trades = {}
    if prev_last and cur_last:
        try:
            from modules.data_loader import load_fund_net_trades
            trades = load_fund_net_trades(fund_code, prev_last, cur_last)
        except Exception as e:
            data_warnings.append(f'거래내역 로드 실패: {e}')

    # 5. 가격 패턴
    price_patterns = {}
    if prev_last and cur_last:
        try:
            from market_research.report.comment_engine import load_bm_price_patterns
            price_patterns = load_bm_price_patterns(prev_last, cur_last)
        except Exception:
            pass

    # 6. 시장 payload → inputs 변환
    inputs = _market_comment_to_inputs(market_payload)

    # 6.5. 펀드 미편입 자산군 파악 (market_view 필터링용)
    all_asset_classes = {'국내주식', '해외주식', '국내채권', '해외채권', '대체투자', 'FX', '유동성'}
    held_classes = set(holdings_end.keys()) if holdings_end else set()
    traded_classes = set(trades.keys()) if trades else set()
    active_classes = (held_classes | traded_classes) - {'유동성', '모펀드'}
    excluded_classes = all_asset_classes - active_classes - {'유동성'}

    # market_view 상단에 편입 제한 지시를 강하게 삽입
    if excluded_classes and inputs.get('market_view'):
        excluded_str = ', '.join(sorted(excluded_classes))
        constraint = (
            f'[중요] 이 펀드는 {excluded_str} 자산을 편입하지 않습니다. '
            f'{excluded_str} 관련 시장 동향(금 가격, 달러선물, NDF 등)은 코멘트에서 완전히 제외하세요.\n\n'
        )
        inputs['market_view'] = constraint + inputs['market_view']

    # 7. 펀드 데이터 요약
    fund_summary = _summarize_fund_data_for_prompt(pa, holdings_end, trades, bm)

    # 거래 요약을 inputs에 추가 (프롬프트에 자연스럽게 주입)
    additional_parts = []
    if fund_summary.get('trades_summary'):
        additional_parts.append(f'[기간 중 거래 요약]\n{fund_summary["trades_summary"]}')

    # (편입 제한은 market_view 상단에서 이미 처리됨)

    if additional_parts:
        inputs['additional'] = inputs.get('additional', '') + '\n\n' + '\n\n'.join(additional_parts)

    # 8. data_ctx 구성
    data_ctx = {
        'bm': bm,
        'fund_ret': fund_ret,
        'pa': pa,
        'holdings_end': holdings_end,
        'holdings_diff': holdings_diff,
        'price_patterns': price_patterns,
    }

    # 9. LLM 호출 (Opus)
    from market_research.report.comment_engine import generate_report_from_inputs
    result = generate_report_from_inputs(
        fund_code, year, quarter, data_ctx, inputs,
        model='claude-opus-4-6',
        start_date=start_dt, end_date=end_dt,
    )

    comment_text_raw = result.get('comment', '')
    cost = result.get('cost', 0)
    token_usage = result.get('token_usage', {})

    # 9.5. R6-A — [ref:N] 검증 + raw / customer 분리
    # 시장 debate 의 evidence_annotations 를 그대로 재사용 (ref 번호 일관)
    fund_evidence_annotations = inputs.get('evidence_annotations') or []
    from market_research.report.evidence_trace import (
        validate_citations, strip_refs,
    )
    citation_result = validate_citations(comment_text_raw,
                                            fund_evidence_annotations)
    comment_citations = citation_result['comment_citations']
    citation_validation = citation_result['citation_validation']
    customer_comment = strip_refs(comment_text_raw)

    # inputs_used 에는 evidence_annotations 풀더미 저장 금지 (200자 트렁크 적용 안됨)
    # — 원자료는 별도 top-level evidence_annotations 필드로
    inputs_used = {}
    for k, v in inputs.items():
        if k == 'evidence_annotations':
            continue
        inputs_used[k] = v[:200] if isinstance(v, str) else v

    # 10. fund draft 저장 (P1-① — 펀드 코멘트도 자체 run ID 1회 발급)
    debate_run_id = uuid.uuid4().hex
    draft_data = {
        'fund_code': fund_code,
        'period': period_key,
        'report_type': FUND_REPORT_TYPE,
        'status': STATUS_DRAFT,
        'debate_run_id': debate_run_id,
        # R6-A: client 노출은 customer 만, raw 는 admin 전용
        'draft_comment': customer_comment,
        'draft_comment_raw': comment_text_raw,
        'comment_citations': comment_citations,
        'citation_validation': citation_validation,
        'evidence_annotations': fund_evidence_annotations,
        'market_debate_period': period_key,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'model': 'claude-opus-4-6',
        'cost_usd': round(cost, 3),
        'token_usage': token_usage,
        'data_warnings': data_warnings,
        'data_snapshot': {
            'bm_count': len(bm),
            'pa_classes': list(pa.keys()),
            'holdings_top3': sorted(holdings_end.items(), key=lambda x: -x[1])[:3] if holdings_end else [],
            'fund_return': fund_ret,
            'trades': trades,
        },
        'inputs_used': inputs_used,
        'edit_history': [],
    }

    save_draft(period_key, fund_code, draft_data)
    return draft_data
