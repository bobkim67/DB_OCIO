# -*- coding: utf-8 -*-
"""
수치 가드레일 — Opus 코멘트의 수치를 원본 데이터와 대조
================================================================

LLM이 코멘트에 포함한 수치(수익률, 금리, 환율 등)를 원본 PA/BM 데이터와 비교.
불일치 시 경고 또는 rewrite 요청.

사용법:
    from market_research.report.numeric_guard import check_comment_numbers
    issues = check_comment_numbers(comment_text, data_ctx)
    if issues:
        print(f"수치 불일치 {len(issues)}건 발견")
"""
from __future__ import annotations

import re
from typing import Optional


def extract_numbers_from_text(text: str) -> list[dict]:
    """코멘트 텍스트에서 수치 + 단위 추출.

    패턴:
    - "S&P500 -4.5%" → {'value': -4.5, 'unit': '%', 'context': 'S&P500'}
    - "WTI 108달러" → {'value': 108, 'unit': '달러', 'context': 'WTI'}
    - "USDKRW +4.4%" → {'value': 4.4, 'unit': '%', 'context': 'USDKRW'}
    - "금리 3.617%" → {'value': 3.617, 'unit': '%', 'context': '금리'}
    """
    patterns = [
        # 퍼센트: "-4.5%", "+3.2%", "4.5%"
        r'(?P<ctx>[\w&/]+)\s*(?P<sign>[+-]?)(?P<num>\d+\.?\d*)\s*%',
        # bp: "57.6bp", "+10bp"
        r'(?P<ctx>[\w]+)\s*(?P<sign>[+-]?)(?P<num>\d+\.?\d*)\s*bp',
        # 달러/원: "108달러", "1500원", "$108"
        r'(?P<ctx>[\w]+)\s+(?P<sign>[+-]?)(?P<num>\d{1,6}\.?\d*)\s*(?P<unit>달러|원|dollar)',
        r'\$(?P<num>\d+\.?\d*)',
    ]

    results = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            try:
                val = float(m.group('num'))
                sign = m.groupdict().get('sign', '')
                if sign == '-':
                    val = -val
                results.append({
                    'value': val,
                    'unit': m.group('unit') if 'unit' in m.groupdict() else '%',
                    'context': m.groupdict().get('ctx', ''),
                    'raw': m.group(0),
                    'pos': m.start(),
                })
            except (ValueError, IndexError):
                pass

    return results


def check_comment_numbers(comment: str, data_ctx: dict,
                          tolerance_pct: float = 0.5,
                          tolerance_abs: float = 0.1) -> list[dict]:
    """코멘트 수치를 원본 데이터와 대조.

    Parameters
    ----------
    comment : str — Opus 생성 코멘트
    data_ctx : dict — 원본 데이터 컨텍스트
        예: {'bm_returns': {'S&P500': -4.5, 'KOSPI': -5.1, ...},
             'pa_summary': {'해외주식': -3.2, ...},
             'fx': {'USDKRW': 1528, ...}}
    tolerance_pct : float — 수익률 허용 오차 (%p)
    tolerance_abs : float — 절대값 허용 오차

    Returns
    -------
    list[dict] — 불일치 항목. 빈 리스트면 통과.
    """
    numbers = extract_numbers_from_text(comment)
    issues = []

    bm = data_ctx.get('bm_returns', {})
    pa = data_ctx.get('pa_summary', {})
    fx = data_ctx.get('fx', {})

    # 수치별 매칭 시도
    for n in numbers:
        ctx = n['context'].upper()
        val = n['value']
        unit = n.get('unit', '%')

        # 수익률(%)은 BM 수익률과 비교, 레벨(달러/원)은 FX와 비교
        # %와 bp는 수익률, 달러/원은 레벨
        is_return = unit in ('%', 'bp')

        if is_return:
            # BM 수익률 매칭 (% 단위끼리만 비교)
            for bm_name, bm_val in bm.items():
                if bm_name.upper() in ctx or ctx in bm_name.upper():
                    # bm_val이 레벨(예: 98.999)이면 수익률과 비교 불가 → 스킵
                    if abs(bm_val) > 50:  # 수익률은 ±50% 이내
                        break
                    if abs(val - bm_val) > tolerance_pct:
                        issues.append({
                            'type': 'bm_return_mismatch',
                            'text': n['raw'],
                            'comment_value': val,
                            'source_value': bm_val,
                            'source': bm_name,
                            'diff': round(val - bm_val, 3),
                        })
                    break

            # PA 기여수익률 매칭
            for pa_name, pa_val in pa.items():
                if pa_name.upper() in ctx or ctx in pa_name.upper():
                    if abs(val - pa_val) > tolerance_pct:
                        issues.append({
                            'type': 'pa_mismatch',
                            'text': n['raw'],
                            'comment_value': val,
                            'source_value': pa_val,
                            'source': pa_name,
                            'diff': round(val - pa_val, 3),
                        })
                    break
        else:
            # FX 레벨 매칭 (달러/원 단위)
            for fx_name, fx_val in fx.items():
                if fx_name.upper() in ctx or ctx in fx_name.upper():
                    if abs(val - fx_val) > tolerance_abs * fx_val:
                        issues.append({
                            'type': 'fx_mismatch',
                            'text': n['raw'],
                            'comment_value': val,
                            'source_value': fx_val,
                            'source': fx_name,
                        })
                    break

    return issues


def format_guard_report(issues: list[dict]) -> str:
    """가드레일 결과를 사람 읽기 좋은 형태로."""
    if not issues:
        return "수치 가드레일 통과: 불일치 0건"

    lines = [f"수치 가드레일 경고: {len(issues)}건 불일치"]
    for i, iss in enumerate(issues, 1):
        lines.append(
            f"  [{i}] {iss['type']}: \"{iss['text']}\" "
            f"→ 코멘트={iss['comment_value']}, 원본={iss['source_value']} "
            f"(source: {iss['source']})")
    lines.append("")
    lines.append("권장 조치: 코멘트의 해당 수치를 원본 값으로 교체하거나, LLM rewrite 요청")
    return '\n'.join(lines)


if __name__ == '__main__':
    # 테스트
    test_comment = """
    3월 시장은 S&P500 -4.5%, KOSPI -5.1%의 낙폭을 기록했다.
    WTI 유가가 108달러를 돌파하고 원달러 환율은 1528원까지 상승했다.
    """
    test_ctx = {
        'bm_returns': {'S&P500': -4.5, 'KOSPI': -5.1},
        'fx': {'USDKRW': 1528},
    }
    issues = check_comment_numbers(test_comment, test_ctx)
    print(format_guard_report(issues))

    # 불일치 테스트
    test_comment_bad = "S&P500 -4.0%, KOSPI -6.0%"
    issues = check_comment_numbers(test_comment_bad, test_ctx)
    print(format_guard_report(issues))
