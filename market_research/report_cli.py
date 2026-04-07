# -*- coding: utf-8 -*-
"""
운용보고 코멘트 통합 CLI

사용법:
    python -m market_research.report_cli build                        # 대화형
    python -m market_research.report_cli build 07G04 -q 1 -y 2026    # 자동
    python -m market_research.report_cli build 07G04 -q 1 --edit     # 수정 모드
    python -m market_research.report_cli build 07G04 -q 1 --from-json # JSON 재생성
    python -m market_research.report_cli build --all -q 1 -y 2026    # 일괄
    python -m market_research.report_cli list                         # 캐시 목록
"""

import argparse
import importlib.util
import json
import sys
import os
from datetime import datetime
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from datetime import date
from dateutil.relativedelta import relativedelta

from market_research.comment_engine import (
    FUND_CONFIGS,
    ANTHROPIC_API_KEY,
    _quarter_dates,
    _load_bm_returns_for_range,
    _prev_business_day,
    load_benchmark_returns_quarter,
    load_fund_return_quarter,
    load_all_pa_attributions_quarter,
    load_fund_holdings_summary,
    load_bm_price_patterns,
    load_digest,
    build_report_prompt,
    generate_report_from_inputs,
)
from modules.data_loader import compute_single_port_pa

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / 'data' / 'report_cache'
COMMENTS_DIR = BASE_DIR.parent / 'comments'
OUTPUT_DIR = BASE_DIR / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

# insight-engine 워크트리 경로 (debate_engine 임포트용)
_INSIGHT_DIR = BASE_DIR.parent.parent / 'DB_OCIO_Webview_insight'

# 관련 펀드 코드 매핑 (과거 코멘트 로드용)
_RELATED_FUNDS = {
    '07G04': ['07G07'],
    '07G07': ['07G04'],
}

# ═══════════════════════════════════════════════════════
# 유틸리티
# ═══════════════════════════════════════════════════════

def _cache_path(period_label, fund_code):
    """캐시 JSON 경로. period_label 예: '2026Q1', '202603-202603', 'YTD2026'"""
    d = CACHE_DIR / period_label
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{fund_code}.json'


def _to_jsonable(obj):
    """JSON 직렬화 헬퍼."""
    import numpy as np
    from decimal import Decimal
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    raise TypeError(f'JSON 직렬화 불가: {type(obj)}')


# ═══════════════════════════════════════════════════════
# 데이터 로딩
# ═══════════════════════════════════════════════════════

def _compute_holdings_diff(start, end, threshold=2.0):
    """분기초/분기말 비중 비교."""
    all_classes = set(list(start.keys()) + list(end.keys()))
    diffs = []
    for ac in sorted(all_classes):
        prev = start.get(ac, 0)
        cur = end.get(ac, 0)
        change = cur - prev
        if abs(change) >= threshold:
            diffs.append({
                'asset_class': ac,
                'prev': round(prev, 1),
                'cur': round(cur, 1),
                'change': round(change, 1),
                'direction': '확대' if change > 0 else '축소',
            })
    diffs.sort(key=lambda x: -abs(x['change']))
    return diffs


def _resolve_period(period_info):
    """기간 정보 → (start_date, end_date, period_label, quarter_for_prompt).

    period_info dict keys:
      type: '1M' | '1Q' | 'YTD' | 'custom'
      end_date: date (전월말 기준)
      start_date: date (custom일 때만)
      year, quarter: int (1Q일 때만)
    """
    ptype = period_info['type']
    today = date.today()
    # 전월말 = 이번달 1일 - 1일
    prev_month_end = today.replace(day=1) - relativedelta(days=1)

    if ptype == '1M':
        end_dt = prev_month_end
        start_dt = end_dt.replace(day=1)
        label = f'{end_dt.strftime("%Y%m")}'
        quarter = (end_dt.month - 1) // 3 + 1
    elif ptype == '1Q':
        year = period_info.get('year', prev_month_end.year)
        quarter = period_info.get('quarter')
        if not quarter:
            quarter = (prev_month_end.month - 1) // 3
            if quarter == 0:
                quarter = 4
                year -= 1
        start_month, end_month = _quarter_dates(year, quarter)
        start_dt = date(year, start_month, 1)
        end_dt = date(year, end_month, 1) + relativedelta(months=1) - relativedelta(days=1)
        label = f'{year}Q{quarter}'
    elif ptype == 'YTD':
        year = period_info.get('year', prev_month_end.year)
        start_dt = date(year, 1, 1)
        end_dt = prev_month_end
        label = f'YTD{year}'
        quarter = (end_dt.month - 1) // 3 + 1
    elif ptype == 'custom':
        start_dt = period_info['start_date']
        end_dt = period_info['end_date']
        label = f'{start_dt.strftime("%Y%m%d")}-{end_dt.strftime("%Y%m%d")}'
        quarter = (end_dt.month - 1) // 3 + 1
    else:
        raise ValueError(f'알 수 없는 기간 유형: {ptype}')

    return start_dt, end_dt, label, quarter


def _load_data(fund_code, start_dt, end_dt, label='', fx_split=False):
    """날짜 범위 기반 데이터 로딩 → data_ctx dict.

    compute_single_port_pa (R 동일 로직)를 사용:
    - T-1 비중 기반 기여수익률
    - 유동성잔차 (포트수익률 - 종목합)
    - fx_split 옵션
    """
    start_str = start_dt.strftime('%Y%m%d')
    end_str = end_dt.strftime('%Y%m%d')
    start_int = int(start_str)
    end_int = int(end_str)
    prev_bday = _prev_business_day(start_int)

    print(f'\n{"═" * 56}')
    print(f'  {label} ({start_dt} ~ {end_dt}) | {fund_code} | FX split={fx_split}')
    print(f'{"═" * 56}')

    print('\n  데이터 로딩 중...', end='', flush=True)

    # BM: 날짜 범위 기반
    bm = _load_bm_returns_for_range(prev_bday, end_int)
    print(' BM', end='', flush=True)

    # PA: compute_single_port_pa (R 동일 로직)
    pa_result = compute_single_port_pa(fund_code, start_str, end_str, fx_split=fx_split)
    print(' PA', end='', flush=True)

    # asset_summary → pa dict + fund_ret + holdings
    asset_summary = pa_result.get('asset_summary')
    pa = {}
    fund_ret = None
    holdings_end = {}
    holdings_start = {}
    holdings_diff = []

    if asset_summary is not None and not asset_summary.empty:
        for _, row in asset_summary.iterrows():
            ac = row['자산군']
            if ac == '포트폴리오':
                fund_ret = {'return': round(row['기여수익률'] * 100, 4)}
                continue
            contrib_pct = round(row['기여수익률'] * 100, 4)
            pa[ac] = contrib_pct
            wt_end = round(row.get('순자산비중', 0) * 100, 2)
            holdings_end[ac] = wt_end
            # 비중변화
            wt_change = row.get('순비중변화', 0) * 100
            if abs(wt_change) >= 1.0:
                wt_start = wt_end - wt_change
                holdings_start[ac] = round(wt_start, 1)
                holdings_diff.append({
                    'asset_class': ac,
                    'prev': round(wt_start, 1),
                    'cur': round(wt_end, 1),
                    'change': round(wt_change, 1),
                    'direction': '확대' if wt_change > 0 else '축소',
                })
        holdings_diff.sort(key=lambda x: -abs(x['change']))

    # 기간 내 가격 패턴 (저점/고점/MDD/반등)
    price_patterns = load_bm_price_patterns(prev_bday, end_int)
    print(' 패턴', end='', flush=True)

    print(' 완료\n')

    # 콘솔 요약
    _print_data_summary(bm, fund_ret, pa, holdings_diff)

    # 주요 패턴 출력
    notable = {k: v for k, v in price_patterns.items()
               if v.get('pattern') in ('V자반등', '고점후하락', '하락') or abs(v.get('mdd', 0)) > 5}
    if notable:
        print('\n── 기간 내 주요 패턴 ──')
        for name, p in notable.items():
            print(f'  {name:16s} {p["pattern"]:6s} | 저점 {p["low_date"]} ({p["low_return"]:+.1f}%) '
                  f'→ 종료 {p["end_return"]:+.1f}% | MDD {p["mdd"]:.1f}% | 반등 {p["rebound"]:+.1f}%')

    return {
        'bm': bm, 'fund_ret': fund_ret, 'pa': pa,
        'holdings_start': holdings_start, 'holdings_end': holdings_end,
        'holdings_diff': holdings_diff,
        'price_patterns': price_patterns,
        'pa_result': pa_result,  # sec_summary 등 상세 데이터 보존
    }


def _print_data_summary(bm, fund_ret, pa, holdings_diff):
    """콘솔 데이터 요약 출력."""
    print('── 벤치마크 ──')
    for name in ['S&P500', 'KOSPI', '미국성장주', '미국가치주', '미국외선진국', '신흥국주식',
                  '미국종합채권', 'KAP종합채권', 'Gold', 'WTI', 'DXY', 'USDKRW']:
        info = bm.get(name, {})
        ret = info.get('return')
        if ret is not None:
            lv = f'  ({info.get("level", 0):,.1f})' if info.get('level') else ''
            print(f'  {name:16s} {ret:+7.2f}%{lv}')

    print('\n── 펀드 성과 ──')
    if fund_ret:
        print(f'  수익률: {fund_ret["return"]:+.2f}%')
        if fund_ret.get('sub_returns'):
            parts = [f'{k}: {v:+.2f}%' for k, v in fund_ret['sub_returns'].items()]
            print(f'  서브: {", ".join(parts)}')

    print('\n── PA 기여도 ──')
    for cls in ['국내주식', '해외주식', '국내채권', '해외채권', '대체투자', '유동성', '보수비용']:
        if cls in pa and abs(pa[cls]) >= 0.01:
            print(f'  {cls:8s} {pa[cls]:+6.2f}%')

    if holdings_diff:
        print('\n── 비중 변화 (2%p 이상) ──')
        for d in holdings_diff:
            arrow = '▲' if d['change'] > 0 else '▼'
            print(f'  {d["asset_class"]:8s} {d["prev"]:5.1f}% → {d["cur"]:5.1f}% ({d["change"]:+.1f}%p {arrow})')


# ═══════════════════════════════════════════════════════
# 과거 코멘트 로드
# ═══════════════════════════════════════════════════════

def _load_past_comments(fund_code):
    """과거 코멘트 로드 — 해당 펀드 + 관련 펀드."""
    codes = [fund_code] + _RELATED_FUNDS.get(fund_code, [])
    comments = []
    if not COMMENTS_DIR.exists():
        return comments
    for code in codes:
        for f in sorted(COMMENTS_DIR.glob(f'{code}_*')):
            try:
                text = f.read_text(encoding='utf-8')
                comments.append({'file': f.name, 'code': code, 'text': text})
            except Exception:
                pass
    return comments


# ═══════════════════════════════════════════════════════
# Debate 연동
# ═══════════════════════════════════════════════════════

def _run_debate(year, quarter):
    """debate 엔진 실행 → 분기 마지막 월 기준."""
    _, end_month = _quarter_dates(year, quarter)
    try:
        debate_path = _INSIGHT_DIR / 'market_research' / 'debate_engine.py'
        if not debate_path.exists():
            print(f'  [경고] debate_engine.py 없음: {debate_path}')
            return None
        spec = importlib.util.spec_from_file_location('debate_engine', debate_path)
        mod = importlib.util.module_from_spec(spec)
        # insight 워크트리의 market_research를 sys.path 최상단에 추가
        # (main 워크트리의 market_research보다 먼저 검색되도록)
        insight_mr = str(_INSIGHT_DIR / 'market_research')
        if insight_mr not in sys.path:
            sys.path.insert(0, insight_mr)
        if str(_INSIGHT_DIR) not in sys.path:
            sys.path.insert(0, str(_INSIGHT_DIR))
        spec.loader.exec_module(mod)
        print(f'\n  debate 실행 중 ({year}-{end_month:02d})...', flush=True)
        result = mod.run_market_debate(year, end_month)
        print(f'  debate 완료')
        return result
    except Exception as e:
        print(f'  [경고] debate 실행 실패: {e}')
        return None


def _debate_to_inputs(debate_result):
    """debate 결과 → inputs dict 변환."""
    if not debate_result:
        return {}

    syn = debate_result.get('synthesis', {})
    agents = debate_result.get('agents', {})
    inputs = {'source': 'debate'}

    # 시장판단: customer_comment (전문 보존)
    comment = syn.get('customer_comment', '')
    if comment:
        inputs['market_view'] = comment

    # 전망: 합의점
    consensus = syn.get('consensus_points', [])
    if consensus:
        inputs['outlook'] = ' '.join(consensus[:3])

    # 리스크: 쟁점 + Bear 관점
    disagreements = syn.get('disagreements', [])
    if disagreements:
        risk_parts = []
        for d in disagreements[:3]:
            if isinstance(d, dict):
                topic = d.get('topic', '')
                bear = d.get('bear', '')
                risk_parts.append(f'{topic}: {bear}')
            else:
                risk_parts.append(str(d))
        inputs['risk'] = ' '.join(risk_parts)

    # 추가: monygeek 관점
    monygeek = agents.get('monygeek', {})
    key_points = monygeek.get('key_points', [])
    if key_points:
        inputs['additional'] = ' '.join(key_points[:2])

    return inputs


# ═══════════════════════════════════════════════════════
# JSON 저장/로드
# ═══════════════════════════════════════════════════════

def _save_report_json(fund_code, period_label, start_dt, end_dt, quarter,
                      data_ctx, inputs, output=None):
    """보고서 JSON 저장."""
    path = _cache_path(period_label, fund_code)

    payload = {
        'version': 4,
        'fund_code': fund_code,
        'period': period_label,
        'start_date': str(start_dt),
        'end_date': str(end_dt),
        'quarter': quarter,
        'generated_at': datetime.now().isoformat(),
        'fund_config': FUND_CONFIGS.get(fund_code, {}),
        'inputs': inputs,
        'data': {
            'bm': data_ctx.get('bm', {}),
            'pa': data_ctx.get('pa', {}),
            'fund_ret': data_ctx.get('fund_ret'),
            'holdings_start': data_ctx.get('holdings_start', {}),
            'holdings_end': data_ctx.get('holdings_end', {}),
            'holdings_diff': data_ctx.get('holdings_diff', []),
        },
    }

    if output:
        payload['output'] = {
            'comment': output.get('comment', ''),
            'model': output.get('model', ''),
            'cost': output.get('cost', 0),
            'token_usage': output.get('token_usage', {}),
            'generated_at': datetime.now().isoformat(),
        }

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_to_jsonable)

    return path


def _load_report_json(period_label, fund_code):
    """기존 보고서 JSON 로드."""
    path = _cache_path(period_label, fund_code)
    if not path.exists():
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════
# 대화형 입력 (인자 미지정 시)
# ═══════════════════════════════════════════════════════

def _interactive_select():
    """펀드/기간/모드 대화형 선택 → (fund_codes, period_info, mode).

    각 단계에서 'b' 입력 시 이전 단계로 복귀.
    """
    fund_list = list(FUND_CONFIGS.keys())

    while True:
        # ── Step 1: 펀드 선택 ──
        selected_funds = _step_select_fund(fund_list)
        if selected_funds is None:
            return None, None, None

        # ── Step 2: 기간 선택 ──
        period_info = _step_select_period()
        if period_info is None:  # back
            continue

        # ── Step 3: 모드 + FX split 선택 ──
        result = _step_select_mode()
        if result is None:  # back → 기간 선택으로
            continue
        mode, fx_split = result

        # resolved 값 저장
        start_dt, end_dt, label, quarter = _resolve_period(period_info)
        period_info['_start_dt'] = start_dt
        period_info['_end_dt'] = end_dt
        period_info['_label'] = label
        period_info['_quarter'] = quarter
        period_info['_fx_split'] = fx_split

        fx_tag = ' | FX분리' if fx_split else ''
        print(f'\n→ {", ".join(selected_funds)} | {label} ({start_dt} ~ {end_dt}) | {mode}{fx_tag}')
        return selected_funds, period_info, mode


def _step_select_fund(fund_list):
    """Step 1: 펀드 선택. None이면 종료."""
    print('\n=== 운용보고 코멘트 생성 ===\n')
    print('사용 가능 펀드:')
    for i, code in enumerate(fund_list, 1):
        cfg = FUND_CONFIGS[code]
        fmt = cfg.get('format', '?')
        target = f', 목표 {cfg["target_return"]:.0f}%' if cfg.get('target_return') else ''
        sub = ' (모펀드)' if cfg.get('sub_portfolios') else ''
        print(f'  {i}. {code} ({fmt}포맷{target}{sub})')
    n = len(fund_list)
    print(f'  {n+1}. 전체')

    choice = input(f'\n펀드 선택 (1~{n+1}, 쉼표로 다중): ').strip()
    if choice == str(n + 1):
        return fund_list
    selected = []
    for part in choice.split(','):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= n:
            selected.append(fund_list[int(part) - 1])
        elif part in FUND_CONFIGS:
            selected.append(part)
    if not selected:
        print('선택된 펀드 없음. 종료.')
        return None
    return selected


def _step_select_period():
    """Step 2: 기간 선택. None이면 back."""
    today = date.today()
    prev_month_end = today.replace(day=1) - relativedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)

    # 직전 완료 분기: 오늘 기준 현재 분기 - 1
    current_q = (today.month - 1) // 3 + 1  # 4월 → Q2
    prev_q = current_q - 1                   # Q2 - 1 = Q1
    prev_q_year = today.year
    if prev_q == 0:
        prev_q = 4
        prev_q_year = today.year - 1
    q_start_month, q_end_month = _quarter_dates(prev_q_year, prev_q)
    q_start = date(prev_q_year, q_start_month, 1)
    q_end = date(prev_q_year, q_end_month, 1) + relativedelta(months=1) - relativedelta(days=1)
    ytd_start = date(prev_month_end.year, 1, 1)

    while True:
        print(f'\n기간 선택 (전월말 기준: {prev_month_end}, b=뒤로):')
        print(f'  1) 직전 1개월  ({prev_month_start} ~ {prev_month_end})')
        print(f'  2) 직전 1분기  ({q_start} ~ {q_end})  [{prev_q_year}Q{prev_q}]')
        print(f'  3) YTD         ({ytd_start} ~ {prev_month_end})')
        print(f'  4) 직접입력')

        choice = input('\n기간 [1]: ').strip().lower()
        if choice == 'b':
            return None

        if not choice or choice == '1':
            return {'type': '1M'}
        elif choice == '2':
            return {'type': '1Q', 'year': prev_q_year, 'quarter': prev_q}
        elif choice == '3':
            return {'type': 'YTD', 'year': prev_month_end.year}
        elif choice == '4':
            print(f'\n  시작일 (YYYYMMDD, b=뒤로):')
            s_str = input(f'  시작일: ').strip()
            if s_str.lower() == 'b':
                return None
            print(f'  종료일 (YYYYMMDD, b=뒤로):')
            e_str = input(f'  종료일: ').strip()
            if e_str.lower() == 'b':
                return None
            try:
                s_str = s_str.replace('-', '')
                e_str = e_str.replace('-', '')
                start_dt = date(int(s_str[:4]), int(s_str[4:6]), int(s_str[6:8]))
                end_dt = date(int(e_str[:4]), int(e_str[4:6]), int(e_str[6:8]))
                return {'type': 'custom', 'start_date': start_dt, 'end_date': end_dt}
            except (ValueError, IndexError):
                print('  날짜 형식 오류. 다시 입력하세요.')
                continue
        else:
            print(f'  "{choice}" → 1~4만 가능합니다.')


def _step_select_mode():
    """Step 3: 모드 + FX split 선택. None이면 back. Returns (mode, fx_split)."""
    while True:
        print('\n모드 선택 (b=뒤로):')
        print('  1. auto  (debate → 자동 생성)')
        print('  2. edit  (draft → VS Code 수정 → 생성)')
        choice = input('\n모드 [1]: ').strip()
        if choice.lower() == 'b':
            return None
        if choice in ('', '1'):
            mode = 'auto'
            break
        elif choice == '2':
            mode = 'edit'
            break
        else:
            print(f'  "{choice}" → 1 또는 2만 가능합니다.')

    while True:
        print('\nFX 분리:')
        print('  1. No   (FX 미분리, 기본)')
        print('  2. Yes  (증권/환효과 분리)')
        fx_choice = input('FX 분리 [1]: ').strip()
        if fx_choice in ('', '1'):
            fx_split = False
            break
        elif fx_choice == '2':
            fx_split = True
            break
        else:
            print(f'  "{fx_choice}" → 1 또는 2만 가능합니다.')

    return mode, fx_split


# ═══════════════════════════════════════════════════════
# build 커맨드
# ═══════════════════════════════════════════════════════

def build_report(fund_code, period_info, mode='auto', detail=False,
                 model=None, fx_split=False):
    """단일 펀드 보고서 생성 → JSON 저장.

    period_info: dict with _start_dt, _end_dt, _label, _quarter
    mode: 'auto' | 'edit' | 'from-json'
    fx_split: True면 증권/FX 분리 (R FX_split=TRUE 동일)
    """
    start_dt = period_info['_start_dt']
    end_dt = period_info['_end_dt']
    label = period_info['_label']
    quarter = period_info['_quarter']

    # ── from-json: 기존 JSON에서 inputs 읽고 코멘트만 재생성 ──
    if mode == 'from-json':
        existing = _load_report_json(label, fund_code)
        if not existing:
            print(f'  [오류] 캐시 없음: {_cache_path(label, fund_code)}')
            return None
        data_ctx = existing.get('data', {})
        inputs = existing.get('inputs', {})
        past_comments = _load_past_comments(fund_code)

        print(f'\n  기존 JSON에서 재생성 ({fund_code} {label})...')
        output = generate_report_from_inputs(
            fund_code, end_dt.year, quarter, data_ctx, inputs,
            past_comments=past_comments, detail=detail, model=model,
        )
        path = _save_report_json(fund_code, label, start_dt, end_dt, quarter,
                                 data_ctx, inputs, output)
        _print_result(output, path)
        return output

    # ── 데이터 로딩 ──
    data_ctx = _load_data(fund_code, start_dt, end_dt, label, fx_split=fx_split)

    # ── debate 실행 → inputs 생성 ──
    print('\n  debate 엔진 실행 중...')
    debate_result = _run_debate(end_dt.year, quarter)
    inputs = _debate_to_inputs(debate_result)
    if not inputs:
        inputs = {'source': 'auto'}

    # ── edit 모드: draft 저장 → 사용자 수정 → 재읽기 ──
    if mode == 'edit':
        draft_path = _save_report_json(fund_code, label, start_dt, end_dt, quarter,
                                       data_ctx, inputs)
        print(f'\n  {"─" * 50}')
        print(f'  Draft 저장: {draft_path}')
        print(f'  VS Code에서 "inputs" 섹션을 수정한 후 저장(Ctrl+S) → 여기서 Enter')
        print(f'  (market_view, position_rationale, outlook, risk, additional)')
        print(f'  {"─" * 50}')
        os.system(f'code "{draft_path}"')
        input('  수정 완료 후 Enter...')

        # 수정된 JSON 재읽기
        edited = _load_report_json(label, fund_code)
        if edited:
            inputs = edited.get('inputs', inputs)
            inputs['source'] = 'user'
            print(f'  inputs 업데이트 완료 (source=user)')

    # ── 코멘트 생성 ──
    past_comments = _load_past_comments(fund_code)
    print(f'\n  코멘트 생성 중...')
    output = generate_report_from_inputs(
        fund_code, end_dt.year, quarter, data_ctx, inputs,
        past_comments=past_comments, detail=detail, model=model,
    )

    # ── 저장 ──
    path = _save_report_json(fund_code, label, start_dt, end_dt, quarter,
                             data_ctx, inputs, output)
    _print_result(output, path)
    return output


def _print_result(output, path):
    """결과 출력."""
    print(f'\n{"═" * 56}')
    print(output.get('comment', '(코멘트 없음)'))
    print(f'{"═" * 56}')
    usage = output.get('token_usage', {})
    print(f'  모델: {output.get("model", "?")}')
    print(f'  토큰: {usage.get("input_tokens", 0)} in + {usage.get("output_tokens", 0)} out')
    print(f'  비용: ${output.get("cost", 0):.4f}')
    print(f'  저장: {path}')


# ═══════════════════════════════════════════════════════
# list 커맨드
# ═══════════════════════════════════════════════════════

def list_reports():
    """캐시된 보고서 목록."""
    if not CACHE_DIR.exists():
        print('캐시 디렉토리 없음.')
        return

    # 분기별 캐시 (YYYYQN 디렉토리)
    quarter_dirs = sorted(CACHE_DIR.glob('*Q*'))
    # 월별 캐시 (YYYY-MM 디렉토리)
    month_dirs = sorted(CACHE_DIR.glob('????-??'))

    all_dirs = quarter_dirs + month_dirs
    if not all_dirs:
        print('캐시된 보고서 없음.')
        return

    print(f'\n=== 캐시된 보고서 ===\n')
    for d in all_dirs:
        if not d.is_dir():
            continue
        json_files = sorted(d.glob('*.json'))
        fund_files = [f for f in json_files if f.stem not in ('catalog', 'enriched_digest', 'news_content_pool')]
        if not fund_files:
            continue

        print(f'[{d.name}]')
        for f in fund_files:
            try:
                payload = json.loads(f.read_text(encoding='utf-8'))
                version = payload.get('version', '?')
                has_comment = bool(payload.get('output', {}).get('comment'))
                source = payload.get('inputs', {}).get('source', '?')
                gen_at = payload.get('output', {}).get('generated_at', '')[:16]
                status = '✓ 코멘트' if has_comment else '  데이터만'
                print(f'  {f.stem:8s} v{version} {status} (source={source}) {gen_at}')
            except Exception:
                print(f'  {f.stem:8s} (읽기 실패)')
        print()


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='운용보고 코멘트 통합 CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""예시:
  %(prog)s build                          # 대화형
  %(prog)s build 07G04 -q 1 -y 2026      # 자동
  %(prog)s build 07G04 -q 1 --edit       # 수정 모드
  %(prog)s build 07G04 -q 1 --from-json  # JSON 재생성
  %(prog)s build --all -q 1 -y 2026      # 일괄
  %(prog)s list                           # 캐시 목록""",
    )

    sub = parser.add_subparsers(dest='command', help='명령')

    # build
    build_p = sub.add_parser('build', help='코멘트 생성')
    build_p.add_argument('fund_code', nargs='?', help='펀드코드 (예: 07G04)')
    build_p.add_argument('--quarter', '-q', type=int, help='분기 (1~4)')
    build_p.add_argument('--year', '-y', type=int, default=datetime.now().year, help='연도')
    build_p.add_argument('--all', action='store_true', help='전체 펀드 일괄')
    build_p.add_argument('--edit', action='store_true', help='수정 모드 (draft → 에디터 → 재생성)')
    build_p.add_argument('--from-json', action='store_true', help='기존 JSON inputs로 코멘트 재생성')
    build_p.add_argument('--detail', action='store_true', help='상세 양식 (과거 코멘트 few-shot)')
    build_p.add_argument('--fx-split', action='store_true', help='FX 분리 (증권/환효과 분리)')
    build_p.add_argument('--model', type=str, default=None, help='LLM 모델 (기본: claude-sonnet-4-6)')

    # list
    sub.add_parser('list', help='캐시된 보고서 목록')

    args = parser.parse_args()

    if args.command == 'list':
        list_reports()
        return

    if args.command == 'build':
        # 모드 결정
        if args.from_json:
            mode = 'from-json'
        elif args.edit:
            mode = 'edit'
        else:
            mode = 'auto'

        # fx_split: CLI 인자 또는 대화형에서 결정
        fx_split = args.fx_split

        # 대화형: fund_code/quarter 미지정 시
        if not args.fund_code and not args.all:
            fund_codes, period_info, interactive_mode = _interactive_select()
            if not fund_codes:
                return
            if interactive_mode:
                mode = interactive_mode
            fx_split = period_info.get('_fx_split', fx_split)
        elif args.all:
            fund_codes = list(FUND_CONFIGS.keys())
            if not args.quarter:
                print('--all 사용 시 -q (분기) 필수.')
                return
            period_info = {'type': '1Q', 'year': args.year, 'quarter': args.quarter}
            s, e, lbl, q = _resolve_period(period_info)
            period_info.update({'_start_dt': s, '_end_dt': e, '_label': lbl, '_quarter': q})
        else:
            if args.fund_code not in FUND_CONFIGS:
                print(f'미지원 펀드: {args.fund_code}')
                print(f'가능: {", ".join(FUND_CONFIGS.keys())}')
                return
            fund_codes = [args.fund_code]
            if not args.quarter:
                print('-q (분기) 필수. 예: -q 1')
                return
            period_info = {'type': '1Q', 'year': args.year, 'quarter': args.quarter}
            s, e, lbl, q = _resolve_period(period_info)
            period_info.update({'_start_dt': s, '_end_dt': e, '_label': lbl, '_quarter': q})

        # 실행
        total_cost = 0
        for fc in fund_codes:
            print(f'\n{"▓" * 56}')
            print(f'  {fc} 처리 중...')
            result = build_report(fc, period_info, mode=mode,
                                  detail=args.detail, model=args.model,
                                  fx_split=fx_split)
            if result:
                total_cost += result.get('cost', 0)

        if len(fund_codes) > 1:
            print(f'\n  === 총 {len(fund_codes)}개 펀드, 비용 ${total_cost:.4f} ===')

        return

    # 기본: 도움말
    parser.print_help()


if __name__ == '__main__':
    main()
