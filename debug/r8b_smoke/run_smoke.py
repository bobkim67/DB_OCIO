"""R8-B live smoke — 펀드 1개 / 기간 1개 LLM 호출 검증.

목표:
  1. agent 가 실제 asset_movement_commentary 를 채우는지
  2. fund_comment 가 자산군별 구조화 설명을 우선 사용하는지
  3. [ref:N] citation + R6-A validation 정상 작동
  4. report_output 무수정 (debug/r8b_smoke/ 에만 저장)

대상:
  fund=08K88, period=2026-04 (월별)

사용법:
  python debug/r8b_smoke/run_smoke.py

출력:
  debug/r8b_smoke/2026-04/_market.json    — debate 결과
  debug/r8b_smoke/2026-04/08K88.draft.json — fund_comment 결과
  debug/r8b_smoke/2026-04/_smoke_report.json — 검증 metric
"""
from __future__ import annotations

import json
import sys
import uuid
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUT_DIR = PROJECT_ROOT / "debug" / "r8b_smoke" / "2026-04"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PERIOD = "2026-04"
FUND = "08K88"
YEAR = 2026
MONTH = 4


def step1_market_debate() -> dict:
    """run_market_debate 직접 호출 (debate_service.save_draft 우회)."""
    from market_research.report.debate_engine import run_market_debate
    print(f"[1/3] run_market_debate(year={YEAR}, month={MONTH}) ...")
    t0 = time.time()
    result = run_market_debate(YEAR, MONTH)
    elapsed = time.time() - t0
    print(f"    완료 ({elapsed:.1f}s, run_id={result.get('debate_run_id')[:12]})")
    # 저장 (debug 영역)
    fp = OUT_DIR / "_market.json"
    fp.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"    저장: {fp.relative_to(PROJECT_ROOT)}")
    return result


def step2_fund_comment(market_result: dict) -> dict:
    """fund_comment 생성 — generate_fund_comment_and_save 의 logic 을 inline 으로 복제하되
    save_draft 없이 debug 에만 저장."""
    print(f"\n[2/3] fund_comment for {FUND} ...")
    from market_research.report.fund_comment_service import (
        _market_comment_to_inputs, _adapt_compute_single_port_pa,
        _summarize_fund_data_for_prompt, _resolve_dates,
    )
    from market_research.report.evidence_trace import (
        validate_citations, strip_refs,
    )
    from market_research.report.comment_engine import (
        _load_bm_returns_for_range, load_bm_price_patterns,
        generate_report_from_inputs,
    )
    from modules.data_loader import compute_single_port_pa, load_fund_net_trades

    # 1. 영업일 범위 (월별)
    prev_last, cur_last, start_dt, end_dt, quarter = _resolve_dates("월별", YEAR, MONTH)
    print(f"    영업일: {prev_last} ~ {cur_last} (quarter={quarter})")

    data_warnings: list[str] = []
    bm = {}
    pa = {}; fund_ret = None; holdings_end = {}; holdings_diff = []
    try:
        bm = _load_bm_returns_for_range(prev_last, cur_last)
    except Exception as e:
        data_warnings.append(f"BM load fail: {e}")
    try:
        pa_result = compute_single_port_pa(
            FUND,
            start_date=start_dt.strftime('%Y%m%d'),
            end_date=end_dt.strftime('%Y%m%d'),
        )
        if pa_result:
            adapted = _adapt_compute_single_port_pa(pa_result)
            pa = adapted['pa_by_class']
            fund_ret = adapted['fund_return']
            holdings_end = adapted['holdings_end']
            holdings_diff = adapted['holdings_diff']
    except Exception as e:
        data_warnings.append(f"PA fail: {e}")
    try:
        trades = load_fund_net_trades(FUND, prev_last, cur_last)
    except Exception as e:
        data_warnings.append(f"trades fail: {e}")
        trades = {}
    try:
        price_patterns = load_bm_price_patterns(prev_last, cur_last)
    except Exception:
        price_patterns = {}

    # 2. market_payload — debate result 의 synthesis + asset_movement_*
    synth = market_result.get('synthesis') or {}
    market_payload = {
        'final_comment': '',  # final 없음, draft 만
        'draft_comment': synth.get('customer_comment', ''),
        'consensus_points': synth.get('consensus_points', []),
        'disagreements': synth.get('disagreements', []),
        'tail_risks': synth.get('tail_risks', []),
        'evidence_annotations': synth.get('evidence_annotations', []),
        # R8-B-impl: asset_movement_* pass-through
        'asset_movement_anchors': market_result.get('asset_movement_anchors'),
        'asset_movement_commentary': market_result.get('asset_movement_commentary') or [],
    }

    # 3. inputs 변환
    inputs = _market_comment_to_inputs(market_payload)
    fund_summary = _summarize_fund_data_for_prompt(pa, holdings_end, trades, bm)
    if fund_summary.get('trades_summary'):
        inputs['additional'] = (inputs.get('additional', '') + '\n\n'
                                 + f"[기간 중 거래 요약]\n{fund_summary['trades_summary']}")

    data_ctx = {'bm': bm, 'fund_ret': fund_ret, 'pa': pa,
                'holdings_end': holdings_end, 'holdings_diff': holdings_diff,
                'price_patterns': price_patterns}

    # 4. LLM 호출
    print(f"    Opus call ...")
    t0 = time.time()
    result = generate_report_from_inputs(
        FUND, YEAR, quarter, data_ctx, inputs,
        model='claude-opus-4-6',
        start_date=start_dt, end_date=end_dt,
    )
    elapsed = time.time() - t0
    print(f"    완료 ({elapsed:.1f}s, cost=${result.get('cost', 0):.4f})")

    comment_text_raw = result.get('comment', '')
    fund_evidence_annotations = inputs.get('evidence_annotations') or []

    # 5. R6-A citation validation
    citation_result = validate_citations(comment_text_raw, fund_evidence_annotations)
    customer_comment = strip_refs(comment_text_raw)

    inputs_used = {k: (v[:200] if isinstance(v, str) else v)
                    for k, v in inputs.items() if k != 'evidence_annotations'}

    draft_data = {
        'fund_code': FUND, 'period': PERIOD, 'report_type': 'fund',
        'status': 'draft (smoke)',
        'debate_run_id': uuid.uuid4().hex,
        'draft_comment': customer_comment,
        'draft_comment_raw': comment_text_raw,
        'comment_citations': citation_result['comment_citations'],
        'citation_validation': citation_result['citation_validation'],
        'evidence_annotations': fund_evidence_annotations,
        'asset_movement_anchors': market_result.get('asset_movement_anchors'),
        'asset_movement_commentary': market_result.get('asset_movement_commentary') or [],
        'market_debate_period': PERIOD,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'model': 'claude-opus-4-6',
        'cost_usd': round(result.get('cost', 0), 4),
        'token_usage': result.get('token_usage', {}),
        'data_warnings': data_warnings,
        'data_snapshot': {'bm_count': len(bm), 'pa_classes': list(pa.keys()),
                          'holdings_top3': sorted(holdings_end.items(), key=lambda x: -x[1])[:3] if holdings_end else [],
                          'fund_return': fund_ret, 'trades': trades},
        'inputs_used': inputs_used,
    }

    fp = OUT_DIR / f"{FUND}.draft.json"
    fp.write_text(json.dumps(draft_data, ensure_ascii=False, indent=2, default=str),
                  encoding="utf-8")
    print(f"    저장: {fp.relative_to(PROJECT_ROOT)}")
    return draft_data


def step3_verify(market_result: dict, fund_draft: dict) -> dict:
    print(f"\n[3/3] R8-B / R6-A 검증 ...")

    # market debate result
    anchors = market_result.get('asset_movement_anchors') or {}
    amc = market_result.get('asset_movement_commentary') or []
    coverage = (anchors or {}).get('coverage_summary', {})

    # agents 측 amc 카운트
    agent_amc_total = 0
    agent_amc_per_agent: dict = {}
    for ag, resp in (market_result.get('agents') or {}).items():
        n = len(resp.get('asset_movement_commentary') or [])
        agent_amc_per_agent[ag] = n
        agent_amc_total += n

    # fund_draft 측
    cv = fund_draft.get('citation_validation') or {}
    fund_amc = fund_draft.get('asset_movement_commentary') or []
    raw_comment = fund_draft.get('draft_comment_raw') or ''
    customer_comment = fund_draft.get('draft_comment') or ''

    # fund prompt 안에 자산군 섹션이 들어갔는지 (간접 — output 에 자산군 키워드 등장 여부)
    asset_keywords = ['국내주식', '해외주식', '국내채권', '해외채권',
                       '환율', '금', '크레딧', '현금성', '원자재']
    asset_mentions = {k: customer_comment.count(k) for k in asset_keywords}
    asset_mention_total = sum(asset_mentions.values())

    report = {
        'period': PERIOD, 'fund_code': FUND,
        'market': {
            'debate_run_id': market_result.get('debate_run_id'),
            'asset_movement_anchors_present': bool(anchors),
            'anchors_schema_version': anchors.get('schema_version'),
            'anchors_coverage': coverage,
            'asset_movement_commentary_count': len(amc),
            'asset_movement_commentary_assets': [it.get('asset_class') for it in amc],
            'agent_amc_per_agent': agent_amc_per_agent,
            'agent_amc_total': agent_amc_total,
        },
        'fund': {
            'cost_usd': fund_draft.get('cost_usd'),
            'comment_chars': len(customer_comment),
            'raw_comment_chars': len(raw_comment),
            'asset_movement_commentary_in_fund': len(fund_amc),
            'asset_keyword_mentions': asset_mentions,
            'asset_keyword_mention_total': asset_mention_total,
            'citation_validation': cv,
            'data_warnings': fund_draft.get('data_warnings', [])[:5],
        },
        'r6a_pass': {
            'has_draft_comment_raw': bool(raw_comment),
            'has_draft_comment_sanitized': bool(customer_comment),
            'has_comment_citations': bool(fund_draft.get('comment_citations')),
            'has_citation_validation': bool(cv),
            'sanitized_lacks_ref_tags': '[ref:' not in customer_comment,
            'raw_has_ref_tags_or_warning': '[ref:' in raw_comment or
                cv.get('explicit_ref_count', 0) == 0,
        },
        'r8b_pass': {
            'anchors_in_market': bool(anchors),
            'anchors_in_fund': bool(fund_draft.get('asset_movement_anchors')),
            'amc_in_market': len(amc) > 0,
            'amc_in_fund': len(fund_amc) > 0,
            'agent_filled_amc': agent_amc_total > 0,
            'fund_comment_mentions_asset': asset_mention_total >= 5,
        },
    }

    fp = OUT_DIR / "_smoke_report.json"
    fp.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                  encoding="utf-8")
    print(f"    저장: {fp.relative_to(PROJECT_ROOT)}")

    # 콘솔 요약
    print()
    print("=" * 60)
    print("R8-B Live Smoke Verification")
    print("=" * 60)
    print(f"period={PERIOD} fund={FUND}")
    print()
    print("[market]")
    print(f"  anchors_present:       {report['market']['asset_movement_anchors_present']}")
    print(f"  anchors_coverage:      {coverage}")
    print(f"  agent_amc_per_agent:   {agent_amc_per_agent}")
    print(f"  agent_amc_total:       {agent_amc_total}")
    print(f"  amc_synth_count:       {len(amc)}")
    print(f"  amc_synth_assets:      {[it.get('asset_class') for it in amc]}")
    print()
    print("[fund]")
    print(f"  cost_usd:              ${report['fund']['cost_usd']}")
    print(f"  raw vs customer:       {len(raw_comment)} chars / {len(customer_comment)} chars")
    print(f"  citation_validation:   {cv}")
    print(f"  asset_keyword_total:   {asset_mention_total}")
    print(f"  per-keyword:           {asset_mentions}")
    print()
    print("[R6-A pass]")
    for k, v in report['r6a_pass'].items():
        print(f"  {'✅' if v else '❌'} {k}")
    print()
    print("[R8-B pass]")
    for k, v in report['r8b_pass'].items():
        print(f"  {'✅' if v else '❌'} {k}")

    return report


if __name__ == "__main__":
    market = step1_market_debate()
    fund = step2_fund_comment(market)
    step3_verify(market, fund)
