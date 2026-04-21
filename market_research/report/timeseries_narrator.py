# -*- coding: utf-8 -*-
"""
시계열 내러티브 빌더 — 교차 분석 레이어

BM/PA 일별 시계열에서 유의미한 변동 구간을 식별하고,
뉴스 벡터DB와 매칭하여 구조화된 텍스트 블록을 생성한다.

debate_engine (월별)과 report_cli (가변 기간) 양쪽에서 사용.

벤치마킹: MSCI z-score 스코어링 + JP Morgan 비정상수익률→뉴스매칭
"""

import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from market_research.core.db import get_conn as _get_conn, parse_blob as _parse_blob
from market_research.core.benchmarks import BENCHMARK_MAP, BM_ASSET_CLASS_MAP, BM_SEARCH_QUERIES

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/


# ═══════════════════════════════════════════════════════
# 1. 설정
# ═══════════════════════════════════════════════════════

# 핵심 6개 BM — 항상 포함
CORE_BENCHMARKS = ['S&P500', 'KOSPI', 'Gold', 'DXY', 'USDKRW', '미국종합채권']

# 세그먼트 감지 설정
SEGMENT_THRESHOLD_Z = 1.5    # z-score 임계값
SEGMENT_MERGE_GAP = 3        # 동방향 세그먼트 병합 간격 (영업일)
MAX_SEGMENTS_PER_BM = 4      # BM당 최대 세그먼트 수
MAX_NEWS_PER_SEGMENT = 2     # 세그먼트당 최대 뉴스 매칭 수


# ═══════════════════════════════════════════════════════
# 2. 데이터 로딩 — core/ 사용
# ═══════════════════════════════════════════════════════


def _int_to_date(d):
    return f'{d // 10000}-{(d % 10000) // 100:02d}-{d % 100:02d}'


def _load_daily_series(start_int, end_int, targets=None):
    """BM별 일별 시계열 로드 → dict[bm_name: DataFrame(date, price, return)]

    comment_engine.load_bm_price_patterns()와 동일한 SCIP 쿼리 패턴 사용.
    """
    if targets is None:
        targets = list(BENCHMARK_MAP.keys())

    target_configs = {n: BENCHMARK_MAP[n] for n in targets if n in BENCHMARK_MAP}
    if not target_configs:
        raise ValueError(f"유효한 BM 없음: {targets}")

    ds_ids = list(set(c['dataset_id'] for c in target_configs.values()))
    dser_ids = list(set(c['ds_id'] for c in target_configs.values()))

    start_dt = _int_to_date(start_int)
    end_dt = _int_to_date(end_int)

    conn = _get_conn('SCIP')
    cur = conn.cursor()
    ds_ph = ','.join(str(d) for d in ds_ids)
    dser_ph = ','.join(str(d) for d in dser_ids)
    cur.execute(f"""SELECT dataset_id, dataseries_id, data, timestamp_observation
                    FROM back_datapoint
                    WHERE dataset_id IN ({ds_ph})
                    AND dataseries_id IN ({dser_ph})
                    AND timestamp_observation BETWEEN DATE_SUB(%s, INTERVAL 25 DAY) AND DATE_ADD(%s, INTERVAL 1 DAY)
                    ORDER BY dataset_id, dataseries_id, timestamp_observation""",
                (start_dt, end_dt))
    all_rows = cur.fetchall()
    conn.close()

    # 시계열 구축
    ts_data = {}
    for r in all_rows:
        key = (r['dataset_id'], r['dataseries_id'])
        dt_str = str(r['timestamp_observation'])[:10]
        val = _parse_blob(r['data'])
        if isinstance(val, dict):
            for ccy, v in val.items():
                ts_data.setdefault((*key, ccy), []).append((dt_str, v))
            default_val = val.get('USD', val.get('KRW', list(val.values())[0]))
            ts_data.setdefault((*key, None), []).append((dt_str, default_val))
        elif val is not None:
            ts_data.setdefault((*key, None), []).append((dt_str, val))

    results = {}
    for name, cfg in target_configs.items():
        blob_key = cfg.get('blob_key')
        key = (cfg['dataset_id'], cfg['ds_id'], blob_key)
        series = ts_data.get(key, [])
        if not series:
            key_fallback = (cfg['dataset_id'], cfg['ds_id'], None)
            series = ts_data.get(key_fallback, [])
        if len(series) < 5:
            continue

        series_sorted = sorted(series, key=lambda x: x[0])
        df = pd.DataFrame(series_sorted, columns=['date', 'price'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.drop_duplicates(subset='date', keep='last').sort_values('date').reset_index(drop=True)

        # 기간 내만 필터 (앞쪽 20일은 trailing vol 계산용)
        period_start = pd.Timestamp(_int_to_date(start_int))
        df['in_period'] = df['date'] >= period_start

        # 일별 로그수익률
        df['log_ret'] = np.log(df['price'] / df['price'].shift(1))
        df = df.dropna(subset=['log_ret'])

        if len(df) < 5:
            continue

        # 기간 시작 기준 누적수익률
        base_price = df.loc[df['date'] >= period_start, 'price'].iloc[0] if df['in_period'].any() else df['price'].iloc[0]
        df['cum_return'] = (df['price'] / base_price - 1) * 100

        results[name] = df

    return results


# ═══════════════════════════════════════════════════════
# 3. 세그먼트 감지 (z-score 기반)
# ═══════════════════════════════════════════════════════

def _detect_segments(df, threshold_z=SEGMENT_THRESHOLD_Z):
    """일별 시계열 DataFrame에서 유의미한 변동 구간 식별.

    알고리즘:
    1. 5영업일 누적수익률 = rolling(5).sum() of log returns
    2. trailing 20영업일 일별수익률 std → 5일 환산 vol = std × √5
    3. z_score = |5일 수익률| / 5일 vol
    4. z > threshold 시작 → z < 1.0이 2일 연속 시 종료
    5. 동방향 세그먼트 gap < merge_gap → 병합
    6. BM당 최대 max_segments 개 (최고 z-score 순)
    """
    # 기간 내 데이터만
    period_df = df[df['in_period']].copy()
    if len(period_df) < 10:
        return []

    # 5일 누적수익률
    period_df['ret_5d'] = period_df['log_ret'].rolling(5, min_periods=3).sum() * 100

    # trailing 20일 vol → 5일 환산
    period_df['vol_20d'] = period_df['log_ret'].rolling(20, min_periods=10).std() * math.sqrt(5) * 100
    # vol이 너무 작으면 0.5%로 바닥
    period_df['vol_20d'] = period_df['vol_20d'].clip(lower=0.5)

    # z-score
    period_df['z_score'] = period_df['ret_5d'].abs() / period_df['vol_20d']
    period_df = period_df.dropna(subset=['z_score'])

    if period_df.empty:
        return []

    # 세그먼트 감지: z > threshold 시작, z < 1.0이 2일 연속 시 종료
    segments = []
    in_segment = False
    seg_start = None
    below_count = 0

    for idx, row in period_df.iterrows():
        if not in_segment:
            if row['z_score'] >= threshold_z:
                in_segment = True
                seg_start = idx
                below_count = 0
        else:
            if row['z_score'] < 1.0:
                below_count += 1
                if below_count >= 2:
                    seg_end = idx - 1 if idx - 1 >= seg_start else idx
                    segments.append((seg_start, seg_end))
                    in_segment = False
                    below_count = 0
            else:
                below_count = 0

    # 마지막 열린 세그먼트 닫기
    if in_segment:
        segments.append((seg_start, period_df.index[-1]))

    if not segments:
        return []

    # 세그먼트 통계 계산
    result = []
    for seg_s, seg_e in segments:
        seg_data = period_df.loc[seg_s:seg_e]
        if seg_data.empty:
            continue

        start_date = seg_data['date'].iloc[0]
        end_date = seg_data['date'].iloc[-1]

        # 구간 수익률: 구간 시작 전일 대비 구간 끝
        start_idx_pos = period_df.index.get_loc(seg_s)
        if start_idx_pos > 0:
            prev_price = period_df.iloc[start_idx_pos - 1]['price']
        else:
            prev_price = seg_data['price'].iloc[0]
        seg_return = (seg_data['price'].iloc[-1] / prev_price - 1) * 100

        max_z = seg_data['z_score'].max()
        direction = 'up' if seg_return > 0 else 'down'

        result.append({
            'start_date': start_date,
            'end_date': end_date,
            'return_pct': round(seg_return, 2),
            'zscore': round(max_z, 2),
            'direction': direction,
            'days': len(seg_data),
        })

    # 동방향 세그먼트 병합 (gap < SEGMENT_MERGE_GAP)
    result.sort(key=lambda s: s['start_date'])
    merged = [result[0]]
    for seg in result[1:]:
        prev = merged[-1]
        gap_days = (seg['start_date'] - prev['end_date']).days
        if gap_days <= SEGMENT_MERGE_GAP and seg['direction'] == prev['direction']:
            # 병합
            merged[-1] = {
                'start_date': prev['start_date'],
                'end_date': seg['end_date'],
                'return_pct': round(prev['return_pct'] + seg['return_pct'], 2),
                'zscore': max(prev['zscore'], seg['zscore']),
                'direction': prev['direction'],
                'days': prev['days'] + seg['days'] + gap_days,
            }
        else:
            merged.append(seg)

    # 최고 z-score 순 정렬, 최대 N개
    merged.sort(key=lambda s: -s['zscore'])
    return merged[:MAX_SEGMENTS_PER_BM]


# ═══════════════════════════════════════════════════════
# 4. 벤치마크 랭킹
# ═══════════════════════════════════════════════════════

def _rank_benchmarks(all_segments, max_bm=8):
    """BM별 최대 z-score 기준 정렬. CORE_BENCHMARKS 항상 포함."""
    bm_max_z = {}
    for name, segs in all_segments.items():
        if segs:
            bm_max_z[name] = max(s['zscore'] for s in segs)
        else:
            bm_max_z[name] = 0

    # CORE 보장
    ranked = sorted(bm_max_z.keys(), key=lambda n: -bm_max_z[n])
    selected = []
    for name in ranked:
        if name in CORE_BENCHMARKS or len(selected) < max_bm:
            selected.append(name)
        if len(selected) >= max_bm:
            break

    # CORE가 빠졌으면 추가
    for core in CORE_BENCHMARKS:
        if core not in selected and core in all_segments:
            selected.append(core)

    return selected


# ═══════════════════════════════════════════════════════
# 5. 뉴스 매칭
# ═══════════════════════════════════════════════════════

def _match_news(segment, bm_name, news_months):
    """세그먼트 기간에 해당하는 뉴스를 벡터DB에서 검색.

    2단계: asset_class 태그 필터(1차) → 임베딩 유사도(2차) → 날짜 필터 T-3~T+0
    """
    try:
        from market_research.analyze.news_vectordb import search
    except ImportError as e:
        print(f"[timeseries_narrator] news_vectordb import 실패: {e}")
        return []

    asset_class = BM_ASSET_CLASS_MAP.get(bm_name)
    query = BM_SEARCH_QUERIES.get(bm_name, bm_name)

    # 방향에 따라 쿼리 보강
    if segment['direction'] == 'down':
        query += ' decline drop fall selloff 하락 급락'
    else:
        query += ' rally rebound surge gain 상승 반등'

    all_results = []
    for month in news_months:
        try:
            results = search(query, month, top_k=10, asset_class=asset_class)
            all_results.extend(results)
        except Exception:
            # asset_class 필터 없이 재시도
            try:
                results = search(query, month, top_k=10)
                all_results.extend(results)
            except Exception:
                continue

    if not all_results:
        return []

    # 날짜 필터: 세그먼트 T-3 ~ T+0
    seg_start = segment['start_date']
    seg_end = segment['end_date']
    window_start = seg_start - timedelta(days=5)  # 3영업일 ≈ 5캘린더일
    window_end = seg_end + timedelta(days=1)

    filtered = []
    for r in all_results:
        date_str = r.get('date', '')
        if not date_str:
            continue
        try:
            news_date = pd.Timestamp(date_str)
            if window_start <= news_date <= window_end:
                filtered.append(r)
        except Exception:
            continue

    # 중복 제거 (제목 앞 40자 기준)
    seen = set()
    unique = []
    for r in filtered:
        title_key = r.get('title', '')[:40]
        if title_key not in seen:
            seen.add(title_key)
            unique.append(r)

    # distance 기준 정렬 (낮을수록 관련도 높음)
    unique.sort(key=lambda r: r.get('distance', 1.0))

    return unique[:MAX_NEWS_PER_SEGMENT]


# ═══════════════════════════════════════════════════════
# 6. 텍스트 포맷팅
# ═══════════════════════════════════════════════════════

def _format_date_range(start, end):
    """날짜 범위를 간결하게 포맷."""
    s = start.strftime('%m/%d') if hasattr(start, 'strftime') else str(start)[5:10]
    e = end.strftime('%m/%d') if hasattr(end, 'strftime') else str(end)[5:10]
    return f'{s}~{e}'


def _format_segment_block(bm_name, period_return, segments, news_by_seg):
    """BM 하나의 세그먼트 블록 포맷.

    Tier 1 (z>2.0): headline + stats + 2 news
    Tier 2 (z>1.5): headline + stats + 1 news
    Tier 3 (z>1.2): one-liner
    """
    lines = [f'▶ {bm_name}: 기간수익률 {period_return:+.1f}%']

    for i, seg in enumerate(segments):
        date_range = _format_date_range(seg['start_date'], seg['end_date'])
        z = seg['zscore']
        ret = seg['return_pct']
        direction_kr = '하락' if seg['direction'] == 'down' else '상승'

        news = news_by_seg.get(i, [])

        if z >= 2.0:
            # Tier 1: full block
            news_desc = ''
            if news:
                news_desc = f' — {news[0].get("title", "")[:60]}'
            lines.append(f'  [{date_range}] {ret:+.1f}% (z={z:.1f}){news_desc}')
            for n in news[:2]:
                lines.append(f'    · "{n.get("title", "")[:70]}" ({n.get("source", "")}, {n.get("date", "")[:10]})')
        elif z >= 1.5:
            # Tier 2: compact
            news_desc = ''
            if news:
                news_desc = f' — {news[0].get("title", "")[:50]}'
            lines.append(f'  [{date_range}] {ret:+.1f}% (z={z:.1f}){news_desc}')
            if news:
                lines.append(f'    · "{news[0].get("title", "")[:70]}" ({news[0].get("source", "")}, {news[0].get("date", "")[:10]})')
        else:
            # Tier 3: one-liner
            lines.append(f'  [{date_range}] {ret:+.1f}% ({direction_kr})')

    return '\n'.join(lines)


def _format_pa_overlay(pa_result, bm_segments):
    """PA 자산군 기여도와 BM 세그먼트 시기 매칭.

    pa_result의 asset_daily DataFrame에서 주간 합산 기여도를 계산하고,
    BM 세그먼트와 시기가 겹치는 자산군을 연결한다.
    """
    asset_daily = pa_result.get('asset_daily')
    asset_summary = pa_result.get('asset_summary')

    if asset_daily is None or asset_summary is None:
        return ''

    # 자산군별 기간 기여도 (상위 3개)
    top_contributors = []
    if not asset_summary.empty:
        for _, row in asset_summary.iterrows():
            ac = row.get('자산군', '')
            if ac in ('포트폴리오', '유동성잔차'):
                continue
            contrib = row.get('기여수익률', 0)
            if abs(contrib) >= 0.001:  # 0.1% 이상
                top_contributors.append((ac, round(contrib * 100, 2)))

    if not top_contributors:
        return ''

    top_contributors.sort(key=lambda x: -abs(x[1]))

    lines = ['[PA 연계]']
    for ac, contrib in top_contributors[:4]:
        # 해당 자산군과 관련된 BM 세그먼트 찾기
        related_bm = []
        asset_class_lower = ac.lower()
        for bm_name, segs in bm_segments.items():
            bm_ac = BM_ASSET_CLASS_MAP.get(bm_name, '')
            # 자산군 매칭 (해외주식↔해외주식 등)
            if bm_ac and (bm_ac in ac or ac in bm_ac):
                for seg in segs:
                    if seg['zscore'] >= 1.5:
                        date_range = _format_date_range(seg['start_date'], seg['end_date'])
                        related_bm.append(f'{bm_name} {date_range} {seg["direction"]}')

        bm_ref = ''
        if related_bm:
            bm_ref = f': {related_bm[0]}과 시기 일치'

        direction = '기여' if contrib > 0 else '손실'
        lines.append(f'  {ac} {contrib:+.2f}%{bm_ref}')

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════
# 7. 오케스트레이터
# ═══════════════════════════════════════════════════════

def build_narrative_blocks(start_int, end_int, news_months=None,
                           pa_result=None, max_tokens=2500):
    """핵심 함수: BM+PA 시계열 → 세그먼트 감지 → 뉴스 매칭 → 텍스트 블록.

    Parameters
    ----------
    start_int, end_int : int (YYYYMMDD)
    news_months : list[str] — 뉴스 검색 대상 월 (예: ['2026-01', '2026-02', '2026-03'])
    pa_result : dict | None — compute_single_port_pa() 결과 (report 모드)
    max_tokens : int — 출력 토큰 한도 (1 token ≈ 3.5 chars)

    Returns
    -------
    str — 구조화된 내러티브 텍스트
    """
    # 뉴스 월 자동 결정
    if news_months is None:
        start_date = datetime.strptime(str(start_int), '%Y%m%d')
        end_date = datetime.strptime(str(end_int), '%Y%m%d')
        months = set()
        current = start_date.replace(day=1)
        while current <= end_date:
            months.add(current.strftime('%Y-%m'))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        news_months = sorted(months)

    # 1. 일별 시계열 로드
    daily_series = _load_daily_series(start_int, end_int)
    if not daily_series:
        raise ValueError(f"BM 시계열 데이터 없음 ({start_int}~{end_int})")

    # 2. BM별 세그먼트 감지
    all_segments = {}
    for name, df in daily_series.items():
        segs = _detect_segments(df)
        all_segments[name] = segs

    # 3. BM 랭킹
    selected = _rank_benchmarks(all_segments)

    # 4. 기간수익률 계산
    period_returns = {}
    for name in selected:
        df = daily_series.get(name)
        if df is not None and df['in_period'].any():
            period_data = df[df['in_period']]
            if not period_data.empty:
                period_returns[name] = period_data['cum_return'].iloc[-1]

    # 5. 뉴스 매칭 (유의미 세그먼트만)
    news_matches = {}  # {bm_name: {seg_idx: [news]}}
    for name in selected:
        news_matches[name] = {}
        for i, seg in enumerate(all_segments.get(name, [])):
            if seg['zscore'] >= 1.5:
                matched = _match_news(seg, name, news_months)
                if matched:
                    news_matches[name][i] = matched

    # 6. 텍스트 포맷
    start_str = _int_to_date(start_int)
    end_str = _int_to_date(end_int)
    header = f'## 기간 내 주요 시계열 변동 ({start_str} ~ {end_str})\n'

    blocks = []
    # z-score 높은 BM부터 (lost-in-middle 대응)
    bm_order = sorted(selected, key=lambda n: max((s['zscore'] for s in all_segments.get(n, [])), default=0), reverse=True)

    for name in bm_order:
        segs = all_segments.get(name, [])
        period_ret = period_returns.get(name, 0)
        news = news_matches.get(name, {})
        if segs or name in CORE_BENCHMARKS:
            block = _format_segment_block(name, period_ret, segs, news)
            blocks.append(block)

    narrative = header + '\n'.join(blocks)

    # 7. PA 오버레이 (report 모드)
    if pa_result:
        pa_text = _format_pa_overlay(pa_result, all_segments)
        if pa_text:
            narrative += '\n\n' + pa_text

    # 8. 토큰 체크 — 초과 시 하위 BM부터 제거
    max_chars = int(max_tokens * 3.5)
    while len(narrative) > max_chars and blocks:
        blocks.pop()
        narrative = header + '\n'.join(blocks)
        if pa_result:
            pa_text = _format_pa_overlay(pa_result, all_segments)
            if pa_text:
                narrative += '\n\n' + pa_text

    # 유의미 세그먼트 없으면 간단 요약
    total_segs = sum(len(s) for s in all_segments.values())
    if total_segs == 0:
        top_movers = sorted(period_returns.items(), key=lambda x: -abs(x[1]))[:3]
        lines = [header.strip(), '기간 중 z-score 1.5σ 초과하는 급변동 구간 없음.']
        for name, ret in top_movers:
            lines.append(f'  {name}: {ret:+.1f}%')
        narrative = '\n'.join(lines)

    return narrative


# ═══════════════════════════════════════════════════════
# 8. 엔트리포인트
# ═══════════════════════════════════════════════════════

def build_debate_narrative(year, month):
    """debate_engine용: 월간 시계열 내러티브 생성 + JSON 캐시.

    Returns
    -------
    str — 시계열 내러티브 텍스트
    """
    # 기간: 전월 말일 ~ 당월 말일
    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    end_int = year * 10000 + month * 100 + last_day

    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    prev_last_day = monthrange(prev_year, prev_month)[1]
    start_int = prev_year * 10000 + prev_month * 100 + prev_last_day

    news_months = [f'{year}-{month:02d}']

    # 캐시 확인
    cache_dir = BASE_DIR / 'data' / 'timeseries_narratives'
    cache_file = cache_dir / f'{year}-{month:02d}.json'
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding='utf-8'))
        if cached.get('narrative'):
            print(f'[timeseries_narrator] 캐시 사용: {cache_file.name}')
            return cached['narrative']

    # 생성
    narrative = build_narrative_blocks(start_int, end_int, news_months)

    # 캐시 저장
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_data = {
        'year': year,
        'month': month,
        'generated_at': datetime.now().isoformat(),
        'narrative': narrative,
    }
    cache_file.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2),
                          encoding='utf-8')
    print(f'[timeseries_narrator] 캐시 저장: {cache_file.name}')

    return narrative


def build_report_narrative(start_dt, end_dt, pa_result=None):
    """report_cli용: 가변 기간 시계열 내러티브 생성.

    Parameters
    ----------
    start_dt, end_dt : int (YYYYMMDD) 또는 datetime.date
    pa_result : dict | None — compute_single_port_pa() 결과
    """
    # int 또는 date 둘 다 처리
    if hasattr(start_dt, 'strftime'):
        start_int = int(start_dt.strftime('%Y%m%d'))
        end_int = int(end_dt.strftime('%Y%m%d'))
    else:
        start_int = int(start_dt)
        end_int = int(end_dt)

    return build_narrative_blocks(start_int, end_int, pa_result=pa_result)


# ═══════════════════════════════════════════════════════
# 9. CLI 테스트
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    import argparse
    parser = argparse.ArgumentParser(description='시계열 내러티브 빌더')
    parser.add_argument('mode', choices=['debate', 'report'], help='실행 모드')
    parser.add_argument('-y', '--year', type=int, default=2026)
    parser.add_argument('-m', '--month', type=int, default=3)
    parser.add_argument('--start', type=int, help='시작일 (YYYYMMDD)')
    parser.add_argument('--end', type=int, help='종료일 (YYYYMMDD)')
    parser.add_argument('--no-cache', action='store_true', help='캐시 무시')
    args = parser.parse_args()

    if args.mode == 'debate':
        if args.no_cache:
            cache_file = BASE_DIR / 'data' / 'timeseries_narratives' / f'{args.year}-{args.month:02d}.json'
            if cache_file.exists():
                cache_file.unlink()
        result = build_debate_narrative(args.year, args.month)
    else:
        if not args.start or not args.end:
            print("report 모드: --start, --end 필수")
            sys.exit(1)
        result = build_report_narrative(args.start, args.end)

    print('\n' + '=' * 60)
    print(result)
    print('=' * 60)
    print(f'\n길이: {len(result)} chars (~{len(result) // 4} tokens)')
