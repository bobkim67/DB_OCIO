"""경기국면 데이터 — SCIP Dash 콜백 API (스크린샷/브라우저 불필요).

POST /_dash-update-component 로 economic-regime-raw 원천 데이터 직수신.
행: LOCATION x 월별 {TIME_PERIOD, value, displacement, velocity, phase(1회복/2팽창/
3침체/4둔화), X_spiral, Y_spiral}. 보고서 스파이럴 = 기본값 G7.
"""
import json

import requests

from .common import OUT

SCIP_URL = 'http://192.168.195.55/_dash-update-component'
PHASE_NAME = {1: '회복', 2: '팽창', 3: '침체', 4: '둔화'}


def _month_kr(ym: str) -> str:
    y, m = ym.split('-')
    return f'{y}년 {int(m)}월'


def _next_month(ym: str) -> str:
    y, m = map(int, ym.split('-'))
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f'{y:04d}-{m:02d}'


def fetch_regime(end_date: str, location: str = 'G7') -> dict:
    """end_date(YYYY-MM-DD) 기준 G7 경기국면 시계열 + 국면 전환 이력."""
    ym = end_date[:7]
    payload = {
        'output': ('..economic-regime-raw.data...economic-regime-location-table.data...'
                   'economic-regime-location-graph.figure...economic-regime-time-table.data...'
                   'economic-regime-time-graph.figure..'),
        'outputs': [
            {'id': 'economic-regime-raw', 'property': 'data'},
            {'id': 'economic-regime-location-table', 'property': 'data'},
            {'id': 'economic-regime-location-graph', 'property': 'figure'},
            {'id': 'economic-regime-time-table', 'property': 'data'},
            {'id': 'economic-regime-time-graph', 'property': 'figure'},
        ],
        'inputs': [
            {'id': 'economic-regime-date', 'property': 'value', 'value': end_date},
            {'id': 'economic-regime-location-select', 'property': 'value', 'value': location},
            {'id': 'economic-regime-time-select', 'property': 'value', 'value': ym},
            {'id': 'app-lang', 'property': 'data', 'value': 'ko'},
            {'id': 'app-theme', 'property': 'data', 'value': 'dark'},
        ],
        'changedPropIds': ['economic-regime-date.value'],
    }
    # 콜백 실패 대비 디스크 캐시 (SCIP 서버 500 관측 2026-07-14)
    cache = OUT / f'regime_cache_{end_date.replace("-", "")}.json'
    raw = None
    try:
        r = requests.post(SCIP_URL, json=payload, timeout=60)
        r.raise_for_status()
        raw = r.json()['response']['economic-regime-raw']['data']
        OUT.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw), encoding='utf-8')
    except Exception as e:                # noqa: BLE001
        if cache.exists():
            print(f'[regime] API 실패 → 캐시 사용 ({cache.name}): {e}')
            raw = json.loads(cache.read_text(encoding='utf-8'))
        else:
            raise
    rows = sorted((x for x in raw if x['LOCATION'] == location),
                  key=lambda x: x['TIME_PERIOD'])
    if not rows:
        raise ValueError(f'regime: {location} 데이터 없음')

    # 국면 전환 이력 (전환 발생 월만; 관측월 = 기준월 +1M — 발송본 관행)
    transitions = []
    prev = None
    for row in rows:
        if row['phase'] != prev:
            transitions.append({
                'base_ym': row['TIME_PERIOD'],
                'base_kr': _month_kr(row['TIME_PERIOD']),
                'obs_kr': _month_kr(_next_month(row['TIME_PERIOD'])),
                'phase': PHASE_NAME[row['phase']],
            })
            prev = row['phase']

    latest = rows[-1]
    return {
        'location': location,
        'rows': rows,
        'transitions': transitions,
        'latest_ym': latest['TIME_PERIOD'],
        'latest_phase': PHASE_NAME[latest['phase']],
        'report_ym': ym,
    }
