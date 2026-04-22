# -*- coding: utf-8 -*-
"""Benchmark-Event Mapping Layer (2026-04-22)

목표:
  자산군별 BM 시계열의 변곡점/이상 구간 ↔ 리포트/뉴스 이벤트를 날짜축으로 정렬해
  graphify 같은 시각화에 바로 넘길 수 있는 정규화 mapping package 생성.

설계:
  - 중심 객체: Benchmark Event Window (date_from~date_to × asset_class × benchmark)
  - source-aware evidence: naver_research = primary, news = corroboration
  - graph subgraph seed: GraphRAG 전체 재계산 안 함 — 기존 월별 그래프에서 window별로
    관련 노드/엣지만 슬라이스해 설명용으로 제공
  - 기존 quota / vectorDB / GraphRAG 본체는 건드리지 않음 (read-only 소비자)

저장: market_research/data/benchmark_events/{YYYY-MM}.json

usage:
    python -m market_research.report.benchmark_event_mapper 2026-03
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date as _date
from datetime import datetime as _dt
from datetime import timedelta
from pathlib import Path

# ── 경로 ──
_BASE = Path(__file__).resolve().parent.parent
_OUT_DIR = _BASE / 'data' / 'benchmark_events'
_OUT_DIR.mkdir(parents=True, exist_ok=True)
_NEWS_DIR = _BASE / 'data' / 'news'
_NR_DIR = _BASE / 'data' / 'naver_research' / 'adapted'
_GRAPH_DIR = _BASE / 'data' / 'insight_graph'

# ── 탐지 파라미터 ──
CORE_BMS = ['S&P500', 'KOSPI', 'Gold', 'DXY', 'USDKRW', '미국종합채권']
Z_ANOMALY = 1.5            # |z| > 이값 → anomaly
Z_TREND_BREAK = 1.0        # |z| > 이값 + 단기 방향전환 → trend_break
DRAWDOWN_PCT = 0.03        # 5일 누적 수익률 < -3% → drawdown
REBOUND_PCT = 0.03         # 5일 누적 수익률 > +3% → rebound (이전 drawdown 이후)
WINDOW_GAP_DAYS = 2        # 같은 BM에서 이 일수 이내면 같은 window로 묶음
EVIDENCE_DATE_TOLERANCE = 2  # window 시작 ±이 일수 이내 evidence만 매핑
MAX_EVIDENCE_PER_WINDOW = 8
NR_QUOTA_PER_WINDOW = 5      # window당 nr 우선 슬롯 (나머지는 news, 부족 시 상호 흡수)


# ═══════════════════════════════════════════════════════════════
# A. BM 시계열 + window 탐지
# ═══════════════════════════════════════════════════════════════

def _load_bm_series(year: int, month: int) -> dict:
    """core BM별 일별 가격/수익률 시계열 (3개월 lookback).

    Returns: {bm_name: pd.DataFrame(date, price, ret, ret_5d, vol_20d, z)}
    """
    try:
        import pandas as pd
        from market_research.core.db import get_conn, parse_blob
        from market_research.core.benchmarks import BENCHMARK_MAP
    except ImportError:
        return {}

    configs = {n: BENCHMARK_MAP[n] for n in CORE_BMS if n in BENCHMARK_MAP}
    if not configs:
        return {}

    end_dt = _date(year, month, 28) + timedelta(days=10)
    start_dt = _date(year, month, 1) - timedelta(days=90)
    ds_ids = list({c['dataset_id'] for c in configs.values()})
    dser_ids = list({c['ds_id'] for c in configs.values()})

    try:
        conn = get_conn('SCIP')
        cur = conn.cursor()
        ph_ds = ','.join(['%s'] * len(ds_ids))
        ph_dser = ','.join(['%s'] * len(dser_ids))
        cur.execute(
            f"""SELECT dataset_id, dataseries_id,
                       DATE(timestamp_observation) AS dt, data
                FROM back_datapoint
                WHERE dataset_id IN ({ph_ds})
                  AND dataseries_id IN ({ph_dser})
                  AND timestamp_observation >= %s
                  AND timestamp_observation <= %s
                ORDER BY dataset_id, timestamp_observation""",
            ds_ids + dser_ids + [start_dt.isoformat(), end_dt.isoformat()])
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return {}

    out = {}
    for bm_name, cfg in configs.items():
        ds_id, dser_id = cfg['dataset_id'], cfg['ds_id']
        blob_key = cfg.get('blob_key')
        prices = []
        for r in rows:
            if r['dataset_id'] != ds_id or r['dataseries_id'] != dser_id:
                continue
            try:
                val = parse_blob(r['data'], blob_key)
                if val is not None and val > 0:
                    prices.append({'date': str(r['dt'])[:10], 'price': float(val)})
            except Exception:
                pass
        if len(prices) < 30:
            continue
        df = pd.DataFrame(prices).drop_duplicates('date').sort_values('date').reset_index(drop=True)
        df['ret'] = df['price'].pct_change()
        df['ret_5d'] = df['price'].pct_change(5)
        df['vol_20d'] = df['ret'].rolling(20).std()
        df['z'] = df['ret_5d'] / df['vol_20d']
        out[bm_name] = df
    return out


def _classify_signal(zval: float, ret_5d: float) -> str:
    """단일 일자 signal_type 분류."""
    if ret_5d <= -DRAWDOWN_PCT and zval <= -1.0:
        return 'drawdown'
    if ret_5d >= REBOUND_PCT and zval >= 1.0:
        return 'rebound'
    if abs(zval) > Z_ANOMALY:
        return 'anomaly'
    if abs(zval) > Z_TREND_BREAK:
        return 'trend_break'
    return ''


def _make_window_id(bm: str, date_from: str, signal: str) -> str:
    key = f'{bm}|{date_from}|{signal}'
    return hashlib.md5(key.encode('utf-8')).hexdigest()[:10]


def detect_benchmark_windows(year: int, month: int) -> list[dict]:
    """자산군별 BM 시계열의 변곡점/이상 구간 탐지.

    각 BM 시계열에서 signal 발생일을 찾고, WINDOW_GAP_DAYS 이내 인접일은 같은 window로 묶음.
    """
    try:
        from market_research.core.benchmarks import BM_ASSET_CLASS_MAP
    except ImportError:
        return []

    series = _load_bm_series(year, month)
    if not series:
        return []

    month_str = f'{year}-{month:02d}'
    windows: list[dict] = []

    for bm_name, df in series.items():
        df_month = df[df['date'].str.startswith(month_str)].copy()
        if df_month.empty:
            continue

        events = []
        for _, row in df_month.iterrows():
            zval = row['z']
            ret_5d = row['ret_5d']
            if zval is None or ret_5d is None:
                continue
            try:
                z = float(zval); r5 = float(ret_5d)
            except Exception:
                continue
            sig = _classify_signal(z, r5)
            if not sig:
                continue
            events.append({'date': row['date'], 'z': z, 'ret_5d': r5, 'signal': sig,
                           'price': float(row['price'])})

        if not events:
            continue

        # 인접일 묶기 (같은 signal_type 묶음 우선, 다른 signal은 새 window)
        events.sort(key=lambda e: e['date'])
        cur_group = [events[0]]
        for ev in events[1:]:
            prev = cur_group[-1]
            d_prev = _dt.strptime(prev['date'], '%Y-%m-%d').date()
            d_cur = _dt.strptime(ev['date'], '%Y-%m-%d').date()
            same_sig = (ev['signal'] == prev['signal'])
            if (d_cur - d_prev).days <= WINDOW_GAP_DAYS and same_sig:
                cur_group.append(ev)
            else:
                windows.append(_finalize_window(bm_name, cur_group, BM_ASSET_CLASS_MAP))
                cur_group = [ev]
        windows.append(_finalize_window(bm_name, cur_group, BM_ASSET_CLASS_MAP))

    # 정렬: date_from 오름차순, 같으면 |zscore| 내림차순
    windows.sort(key=lambda w: (w['date_from'], -abs(w['zscore'])))
    return windows


def _finalize_window(bm: str, events: list[dict], asset_map: dict) -> dict:
    """events 묶음 → 단일 window dict."""
    dates = [e['date'] for e in events]
    zs = [e['z'] for e in events]
    rs = [e['ret_5d'] for e in events]
    # 대표값: |z| 최대인 일자 기준
    pivot = max(events, key=lambda e: abs(e['z']))
    return {
        'window_id': _make_window_id(bm, dates[0], pivot['signal']),
        'asset_class': asset_map.get(bm, '미분류'),
        'benchmark': bm,
        'date_from': dates[0],
        'date_to': dates[-1],
        'signal_type': pivot['signal'],
        'benchmark_move_pct': round(pivot['ret_5d'] * 100, 4),
        'zscore': round(pivot['z'], 4),
        'pivot_date': pivot['date'],
        'event_count': len(events),
    }


# ═══════════════════════════════════════════════════════════════
# B. Evidence 로드 + window 매핑
# ═══════════════════════════════════════════════════════════════

# 토픽 → 자산군 매칭 (asset_class 매칭 우선순위 결정용)
_TOPIC_TO_ASSET_CLASSES = {
    '통화정책': ['해외채권', '해외주식', '국내채권', '국내주식', '통화'],
    '금리_채권': ['해외채권', '국내채권', '해외주식'],
    '물가_인플레이션': ['해외채권', '국내채권', '대체투자'],
    '경기_소비': ['국내주식', '해외주식'],
    '유동성_크레딧': ['해외채권', '국내채권'],
    '환율_FX': ['통화'],
    '달러_글로벌유동성': ['통화', '해외주식', '해외채권'],
    '에너지_원자재': ['대체투자'],
    '귀금속_금': ['대체투자'],
    '지정학': ['해외주식', '대체투자', '통화'],
    '관세_무역': ['해외주식', '국내주식', '통화'],
    '테크_AI_반도체': ['해외주식', '국내주식'],
    '부동산': ['대체투자'],
    '크립토': ['해외주식'],
}


def _date_in_window(d: str, w: dict, tol: int = EVIDENCE_DATE_TOLERANCE) -> bool:
    """기사 date(YYYY-MM-DD)가 window 범위 ±tol 일 안에 있는지."""
    if not d:
        return False
    try:
        ad = _dt.strptime(d[:10], '%Y-%m-%d').date()
    except Exception:
        return False
    df = _dt.strptime(w['date_from'], '%Y-%m-%d').date() - timedelta(days=tol)
    dt = _dt.strptime(w['date_to'], '%Y-%m-%d').date() + timedelta(days=tol)
    return df <= ad <= dt


def _topic_matches_asset_class(topic: str, asset_class: str) -> bool:
    return asset_class in _TOPIC_TO_ASSET_CLASSES.get(topic, [])


def _load_articles(year: int, month: int) -> tuple[list, list]:
    """(news_articles, nr_articles) — primary + classified만."""
    period = f'{year}-{month:02d}'
    news = []
    news_fp = _NEWS_DIR / f'{period}.json'
    if news_fp.exists():
        try:
            data = json.loads(news_fp.read_text(encoding='utf-8'))
            for a in data.get('articles', []):
                if a.get('_classified_topics') and a.get('is_primary', True):
                    a.setdefault('source_type', 'news')
                    news.append(a)
        except Exception:
            pass
    nr = []
    nr_fp = _NR_DIR / f'{period}.json'
    if nr_fp.exists():
        try:
            data = json.loads(nr_fp.read_text(encoding='utf-8'))
            for a in data.get('articles', []):
                if a.get('_classified_topics') and a.get('is_primary', True):
                    a.setdefault('source_type', 'naver_research')
                    nr.append(a)
        except Exception:
            pass
    return news, nr


def load_window_evidence(year: int, month: int, window: dict,
                         articles_cache: tuple = None) -> list[dict]:
    """window 기간/자산군에 맞는 source-aware evidence 로드.

    우선순위:
      1) date in window±tol AND topic matches asset_class
      2) date in window±tol AND asset_relevance[asset_class] >= 0.4
      3) date in window±tol (any topic, fallback)
    각 단계 안에서: source_type=naver_research 우선 → salience 내림차순.
    중복 article_id는 제거.
    """
    if articles_cache is None:
        articles_cache = _load_articles(year, month)
    news, nr = articles_cache
    asset_class = window.get('asset_class', '')

    def _candidates(level: int, source_pool: list[dict]) -> list[dict]:
        out = []
        for a in source_pool:
            if not _date_in_window(a.get('date', ''), window):
                continue
            topics = [t.get('topic', '') for t in (a.get('_classified_topics') or []) if isinstance(t, dict)]
            primary = a.get('primary_topic', '')
            ar = a.get('_asset_relevance') or {}
            if level == 1:
                if not any(_topic_matches_asset_class(t, asset_class) for t in (topics + [primary])):
                    continue
            elif level == 2:
                if float(ar.get(asset_class, 0) or 0) < 0.4:
                    continue
            # level 3: pass-through
            out.append(a)
        out.sort(key=lambda x: -float(x.get('_event_salience', 0) or 0))
        return out

    seen = set()
    picked = []

    def _take(source_pool: list[dict], cap: int):
        if cap <= 0:
            return
        for level in (1, 2, 3):
            if len([p for p in picked if p['source_type'] ==
                    ('naver_research' if source_pool is nr else 'news')]) >= cap:
                return
            for a in _candidates(level, source_pool):
                aid = a.get('_article_id', '')
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                picked.append(_pack_evidence(a, asset_class, level))
                taken_src = sum(1 for p in picked if p['source_type'] ==
                                ('naver_research' if source_pool is nr else 'news'))
                if taken_src >= cap or len(picked) >= MAX_EVIDENCE_PER_WINDOW:
                    return

    nr_quota = min(NR_QUOTA_PER_WINDOW, MAX_EVIDENCE_PER_WINDOW)
    news_quota = MAX_EVIDENCE_PER_WINDOW - nr_quota
    _take(nr, nr_quota)
    _take(news, news_quota)
    # 부족 시 상호 흡수
    if len(picked) < MAX_EVIDENCE_PER_WINDOW:
        _take(nr, MAX_EVIDENCE_PER_WINDOW)
    if len(picked) < MAX_EVIDENCE_PER_WINDOW:
        _take(news, MAX_EVIDENCE_PER_WINDOW)
    return picked


def _pack_evidence(a: dict, asset_class: str, match_level: int) -> dict:
    return {
        'evidence_id': a.get('_article_id', ''),
        'source_type': a.get('source_type', ''),
        'date': (a.get('date', '') or '')[:10],
        'asset_class': asset_class,
        'primary_topic': a.get('primary_topic', ''),
        'title': (a.get('title', '') or '')[:140],
        'source': a.get('source', ''),
        'salience': round(float(a.get('_event_salience', 0) or 0), 4),
        'asset_relevance': round(float((a.get('_asset_relevance') or {}).get(asset_class, 0) or 0), 4),
        'bm_overlap': bool(a.get('_bm_overlap', False)),
        'event_group_id': a.get('_event_group_id', ''),
        'broker': a.get('broker') or a.get('_raw_broker') or '',
        'category': a.get('_raw_category') or '',
        'match_level': match_level,
    }


def _compute_confidence(window: dict, evidence: list[dict]) -> float:
    """confidence = z-strength × evidence-strength × source-mix bonus.

    - z-strength: min(|zscore|/3, 1.0)
    - evidence-strength: min(len(ev)/4, 1.0)
    - nr ratio bonus: 1.0 + 0.2 × (nr_count / total) 캡 1.2
    """
    if not evidence:
        return 0.0
    z_str = min(abs(float(window.get('zscore', 0))) / 3.0, 1.0)
    ev_str = min(len(evidence) / 4.0, 1.0)
    nr = sum(1 for e in evidence if e['source_type'] == 'naver_research')
    nr_bonus = 1.0 + 0.2 * (nr / len(evidence))
    return round(z_str * ev_str * nr_bonus, 4)


# ═══════════════════════════════════════════════════════════════
# C. Window-Subgraph Seed (read-only 슬라이스)
# ═══════════════════════════════════════════════════════════════

def _load_graph(year: int, month: int) -> dict:
    fp = _GRAPH_DIR / f'{year}-{month:02d}.json'
    if not fp.exists():
        return {'nodes': {}, 'edges': []}
    try:
        return json.loads(fp.read_text(encoding='utf-8'))
    except Exception:
        return {'nodes': {}, 'edges': []}


def build_window_graph_seed(window_mapping: dict, graph: dict = None,
                            year: int = None, month: int = None) -> dict:
    """window별 설명용 subgraph seed.

    매칭 규칙:
      - 노드 라벨이 window의 asset_class 또는 primary_topic을 포함하면 채택
      - 노드 source_types에 evidence source_type이 포함되면 가중
      - 채택 노드 사이의 엣지만 추출
    """
    if graph is None and year is not None and month is not None:
        graph = _load_graph(year, month)
    if not graph:
        graph = {'nodes': {}, 'edges': []}
    nodes = graph.get('nodes', {})
    edges = graph.get('edges', [])

    win = window_mapping.get('window', {})
    asset_class = win.get('asset_class', '')
    evidence = window_mapping.get('evidence', [])
    topics = {e.get('primary_topic', '') for e in evidence if e.get('primary_topic')}
    if not topics:
        topics = set()

    # 키워드 후보: asset_class + 토픽 분해 (예: '금리_채권' → '금리', '채권')
    keywords = set()
    if asset_class:
        keywords.add(asset_class)
        # 한국어 자산군 → 일부 별칭
        for alias in {'해외주식': ['미국', '글로벌', 'S&P', 'Nasdaq'],
                      '해외채권': ['미국채', 'Treasury', 'IG', 'HY'],
                      '국내주식': ['코스피', 'KOSPI'],
                      '국내채권': ['국채', 'KAP'],
                      '대체투자': ['금', 'Gold', '원유', 'WTI'],
                      '통화': ['달러', '환율', 'DXY', 'KRW']}.get(asset_class, []):
            keywords.add(alias)
    for t in topics:
        for part in t.split('_'):
            if len(part) >= 2:
                keywords.add(part)

    picked_node_ids = set()
    picked_nodes = []
    for nid, n in nodes.items():
        label = n.get('label', '') or ''
        topic = n.get('topic', '') or ''
        if any(kw in label for kw in keywords) or any(kw in topic for kw in keywords):
            picked_node_ids.add(nid)
            picked_nodes.append({
                'node_id': nid,
                'label': label,
                'topic': topic,
                'severity': n.get('severity', ''),
                'source_types': list(n.get('source_types') or []),
            })
        if len(picked_nodes) >= 12:
            break

    picked_edges = []
    for e in edges:
        if e.get('from') in picked_node_ids and e.get('to') in picked_node_ids:
            picked_edges.append({
                'from': e.get('from'),
                'to': e.get('to'),
                'relation': e.get('relation', ''),
                'weight': float(e.get('weight', 0) or 0),
                'rule_name': e.get('rule_name', ''),
                'source_type': e.get('source_type', ''),
            })
        if len(picked_edges) >= 20:
            break

    return {'nodes': picked_nodes, 'edges': picked_edges}


# ═══════════════════════════════════════════════════════════════
# D. 통합 매핑 + 시각화 contract
# ═══════════════════════════════════════════════════════════════

def map_events_to_windows(year: int, month: int) -> list[dict]:
    """window ↔ evidence/event/topic 매핑 결과 생성."""
    windows = detect_benchmark_windows(year, month)
    if not windows:
        return []
    cache = _load_articles(year, month)
    graph = _load_graph(year, month)

    out = []
    for w in windows:
        ev = load_window_evidence(year, month, w, articles_cache=cache)
        topics = sorted({e['primary_topic'] for e in ev if e.get('primary_topic')})
        event_groups = sorted({e['event_group_id'] for e in ev if e.get('event_group_id')})
        mapping = {
            'window': w,
            'evidence': ev,
            'mapped_topics': topics,
            'mapped_event_groups': event_groups,
            'confidence': _compute_confidence(w, ev),
        }
        seed = build_window_graph_seed(mapping, graph=graph)
        mapping['graph_seed'] = seed
        out.append(mapping)
    return out


def build_visualization_contract(year: int, month: int) -> dict:
    """graphify/시각화로 넘길 JSON contract.

    contract:
      {
        month, generated_at,
        windows: [...],          # window 메타 + evidence 요약 + confidence
        timeline: [...],         # date 정렬된 (window event + evidence) 단순 배열
        graph: {nodes, edges},   # 모든 window 의 graph_seed 합집합 (dedupe)
        evidence_cards: [...],   # window별 evidence 풀어서 평탄화 (UI 카드용)
        debug: {...},
      }
    """
    mappings = map_events_to_windows(year, month)
    period = f'{year}-{month:02d}'

    windows_out = []
    timeline = []
    cards = []
    graph_node_seen = {}
    graph_edge_seen = set()
    graph_nodes = []
    graph_edges = []
    nr_total = 0
    news_total = 0
    unmapped_windows = 0

    for m in mappings:
        w = m['window']
        ev = m['evidence']
        nr_n = sum(1 for e in ev if e['source_type'] == 'naver_research')
        news_n = len(ev) - nr_n
        nr_total += nr_n
        news_total += news_n
        if not ev:
            unmapped_windows += 1

        windows_out.append({
            **w,
            'mapped_evidence_ids': [e['evidence_id'] for e in ev],
            'mapped_topics': m['mapped_topics'],
            'mapped_event_groups': m['mapped_event_groups'],
            'evidence_count': len(ev),
            'evidence_source_mix': {'naver_research': nr_n, 'news': news_n},
            'confidence': m['confidence'],
            'graph_seed_size': {'nodes': len(m['graph_seed']['nodes']),
                                'edges': len(m['graph_seed']['edges'])},
        })

        # timeline: window 시작/끝/pivot + evidence 일자
        timeline.append({'date': w['pivot_date'], 'kind': 'bm_pivot',
                         'window_id': w['window_id'], 'asset_class': w['asset_class'],
                         'benchmark': w['benchmark'], 'signal_type': w['signal_type'],
                         'zscore': w['zscore'], 'move_pct': w['benchmark_move_pct']})
        for e in ev:
            timeline.append({'date': e['date'], 'kind': 'evidence',
                             'window_id': w['window_id'], 'asset_class': e['asset_class'],
                             'evidence_id': e['evidence_id'],
                             'source_type': e['source_type'],
                             'primary_topic': e['primary_topic']})
            cards.append({
                'window_id': w['window_id'],
                'evidence_id': e['evidence_id'],
                'source_type': e['source_type'],
                'date': e['date'],
                'asset_class': e['asset_class'],
                'primary_topic': e['primary_topic'],
                'title': e['title'],
                'source': e['source'],
                'broker': e['broker'],
                'salience': e['salience'],
                'asset_relevance': e['asset_relevance'],
                'match_level': e['match_level'],
            })

        # graph union
        for n in m['graph_seed']['nodes']:
            if n['node_id'] in graph_node_seen:
                graph_node_seen[n['node_id']]['window_ids'].append(w['window_id'])
                continue
            n2 = dict(n); n2['window_ids'] = [w['window_id']]
            graph_node_seen[n['node_id']] = n2
            graph_nodes.append(n2)
        for e in m['graph_seed']['edges']:
            ek = (e['from'], e['to'], e.get('relation', ''))
            if ek in graph_edge_seen:
                continue
            graph_edge_seen.add(ek)
            graph_edges.append(e)

    timeline.sort(key=lambda x: (x['date'], 0 if x['kind'] == 'bm_pivot' else 1))

    contract = {
        'month': period,
        'generated_at': _dt.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'windows': windows_out,
        'timeline': timeline,
        'graph': {'nodes': graph_nodes, 'edges': graph_edges},
        'evidence_cards': cards,
        'debug': {
            'window_count': len(windows_out),
            'unmapped_windows': unmapped_windows,
            'evidence_total': len(cards),
            'source_mix': {'naver_research': nr_total, 'news': news_total},
            'graph_size': {'nodes': len(graph_nodes), 'edges': len(graph_edges)},
            'parameters': {
                'core_bms': CORE_BMS,
                'z_anomaly': Z_ANOMALY,
                'z_trend_break': Z_TREND_BREAK,
                'drawdown_pct': DRAWDOWN_PCT,
                'rebound_pct': REBOUND_PCT,
                'window_gap_days': WINDOW_GAP_DAYS,
                'evidence_date_tolerance': EVIDENCE_DATE_TOLERANCE,
                'max_evidence_per_window': MAX_EVIDENCE_PER_WINDOW,
            },
        },
    }
    return contract


def save_contract(year: int, month: int, contract: dict = None) -> Path:
    if contract is None:
        contract = build_visualization_contract(year, month)
    fp = _OUT_DIR / f'{year}-{month:02d}.json'
    fp.write_text(json.dumps(contract, ensure_ascii=False, indent=2, default=str),
                  encoding='utf-8')
    return fp


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Benchmark-Event Mapping Layer')
    ap.add_argument('months', nargs='+', help='YYYY-MM (1개 이상)')
    ap.add_argument('--no-save', action='store_true', help='파일 저장 안 함')
    args = ap.parse_args(argv)

    for m in args.months:
        try:
            y, mo = (int(x) for x in m.split('-'))
        except Exception:
            print(f'[{m}] 형식 오류, 스킵', file=sys.stderr); continue
        contract = build_visualization_contract(y, mo)
        d = contract['debug']
        print(f'[{m}] windows={d["window_count"]} '
              f'unmapped={d["unmapped_windows"]} '
              f'evidence={d["evidence_total"]} '
              f'(nr={d["source_mix"]["naver_research"]} news={d["source_mix"]["news"]}) '
              f'graph={d["graph_size"]["nodes"]}n/{d["graph_size"]["edges"]}e')
        if not args.no_save:
            fp = save_contract(y, mo, contract)
            print(f'  → {fp}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
