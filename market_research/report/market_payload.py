# -*- coding: utf-8 -*-
"""시장 코멘트(_market) payload 해석 — 기간 키 ↔ 날짜창 공용 계층.

★ 왜 여기 있나 (2026-09-02): 이 로직은 `api/routers/admin_funds.py` 안에 있었고
  **펀드 코멘트 생성 경로에서만** 쓰였다. 그래서 운용보고 PPT 는 같은 스킴을 못 쓰고
  `report_output/{YYYY-MM}/_market.final.json` 을 직접 읽었다 — 종료일만 같으면
  설정이후 PPT 와 하반기 PPT 가 **같은 시장 코멘트**를 인용했고(08N33 실측),
  Admin 에서 HTD·YTD 코멘트를 승인해도 PPT 는 그 키를 쳐다보지도 않았다.
  `reporting/builder/*` 가 `api.routers` 를 import 할 수는 없으므로 공용 계층으로 뺀다.
  **admin_funds 는 이 모듈을 alias 로 재노출**하므로 기존 동작·테스트는 불변이다.

핵심 진입점:
  resolve_market_payload(period, mode, year, num)  — 기간 키 기준 (Admin 경로, 기존)
  resolve_market_for_window(start_iso, end_iso)    — 날짜창 기준 (PPT 경로, 신규)
"""
from __future__ import annotations

import json


def market_source_periods(mode: str, year: int, num: int) -> tuple[str | None, list[str]]:
    """TD 기간의 시장 코멘트 소스 — (기간 전체를 덮는 상위 키, 기간 내 월간 키들).

    TD 기간 자체로는 시장 debate 를 돌리지 않으므로(사용자 확정, 2026-07-31)
    이미 승인된 시장 코멘트를 재사용한다. 상위 키(분기/반기) 승인본이 있으면
    그것 단독, 없으면 기간 내 월간 승인본을 시간순으로 묶는다.
    """
    if mode == 'QTD':
        return f'{year}-Q{num}', [f'{year}-{(num - 1) * 3 + 1 + i:02d}' for i in range(3)]
    if mode == 'HTD':
        base = 1 if num == 1 else 7
        return f'{year}-H{num}', [f'{year}-{base + i:02d}' for i in range(6)]
    if mode == 'YTD':
        return None, [f'{year}-{m:02d}' for m in range(1, 13)]
    return None, []


def merge_market_payloads(items: list[tuple[str, dict]]) -> dict | None:
    """여러 기간 시장 코멘트 → 단일 payload.

    본문은 기간 라벨을 붙여 시간순으로 잇는다. [ref:N] 은 기간마다 독립 번호라
    합치면 충돌하고 병합본 기준 evidence 도 없어 복원이 불가능하므로 제거한다.
    전망성 항목(합의/쟁점/테일리스크/자산군 코멘트)은 가장 최근 기간 것을 쓴다.
    """
    if not items:
        return None
    if len(items) == 1:
        return items[0][1]

    from market_research.report.evidence_trace import strip_refs
    parts, claims, seen = [], [], set()
    for label, p in items:
        body = (p.get('final_comment') or p.get('draft_comment')
                or p.get('customer_comment') or '').strip()
        if body:
            parts.append(f'[{label}]\n{strip_refs(body)}')
        for cl in (p.get('claims') or []):
            try:
                key = json.dumps(cl, sort_keys=True, ensure_ascii=False)
            except TypeError:
                key = str(cl)
            if key not in seen:
                seen.add(key)
                claims.append(cl)

    last = items[-1][1]
    merged = {
        'final_comment': '\n\n'.join(parts),
        'claims': claims,
        'merged_from': [label for label, _ in items],
    }
    for k in ('consensus_points', 'tail_risks', 'disagreements',
              'asset_movement_commentary', 'asset_movement_anchors'):
        if last.get(k):
            merged[k] = last[k]
    return merged


def resolve_market_payload(period: str, mode: str, year: int, num: int) -> dict | None:
    """생성에 쓸 시장 코멘트 payload — 같은 기간 승인본 우선, TD 는 재사용 병합."""
    from market_research.report.report_store import load_final
    exact = load_final(period, '_market')
    if exact:
        return exact
    if mode not in ('QTD', 'HTD', 'YTD'):
        return None
    umbrella, months = market_source_periods(mode, year, num)
    if umbrella:
        up = load_final(umbrella, '_market')
        if up:
            return up
    items = [(mp, load_final(mp, '_market')) for mp in months]
    merged = merge_market_payloads([(mp, p) for mp, p in items if p])
    return compact_market_payload(merged)


def compact_market_payload(merged: dict | None) -> dict | None:
    """병합 본문이 길면 기간 내러티브 1본으로 압축 (2026-07-31 사용자 지시).

    월별 나열을 그대로 넘기면 6~12개월치가 1.3~2.6만자라 펀드 코멘트 프롬프트를
    압도한다. 임계 미만이거나 압축 실패면 원문 병합본을 그대로 쓴다(기능 무중단).
    """
    if not merged or not merged.get('merged_from'):
        return merged
    from market_research.report.market_digest import build_market_digest
    body = merged.get('final_comment') or ''
    digest = build_market_digest(body, merged['merged_from'])
    if not digest:
        return merged
    out = dict(merged)
    out['final_comment'] = digest['text']
    out['market_digest'] = {
        'model': digest['model'],
        'source_chars': digest['source_chars'],
        'digest_chars': len(digest['text']),
        'source_periods': digest.get('source_periods') or merged['merged_from'],
        'cached': digest.get('cached', False),
    }
    return out


# ══════════════════════════════════════════
# 날짜창 → 기간 키 (PPT 경로, 2026-09-02)
# ══════════════════════════════════════════

def months_covering(start_iso: str, end_iso: str) -> list[str]:
    """구간이 걸치는 `YYYY-MM` 키 목록.

    ★ **시작이 그 달의 말일이면 그 달은 뺀다** — 시작일은 수익률 기초일이라
      그 달의 시장을 설명할 필요가 없다. PA 창 규약 `(기초일, 기간말]` 과 같다
      (예: 2025-09-30 시작 → 2025-09 제외, 2025-10 부터).
    """
    import datetime as _dt
    from calendar import monthrange

    def _d(s):
        return _dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))

    s, e = _d(start_iso), _d(end_iso)
    out, y, m = [], s.year, s.month
    while (y, m) <= (e.year, e.month):
        eom = _dt.date(y, m, monthrange(y, m)[1])
        if eom > s:
            out.append(f'{y}-{m:02d}')
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def window_to_period(start_iso: str, end_iso: str):
    """날짜창이 **달력 기간과 정확히 일치**하면 (period, mode, year, num) 반환.

    일치하지 않으면 None — 롤링 3M/6M, 설정후처럼 달력 기간이 아닌 창이 여기 해당한다
    (그 경우 호출부가 `months_covering` 병합으로 폴백한다).
    기준: **시작 = 직전 기간의 마지막 날**(기초일 규약), 종료 = 해당 기간의 마지막 날
    또는 진행 중(=to-date).
    """
    import datetime as _dt
    from calendar import monthrange

    def _d(s):
        return _dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))

    try:
        s, e = _d(start_iso), _d(end_iso)
    except Exception:
        return None
    if s >= e:
        return None

    def eom(y, m):
        return _dt.date(y, m, monthrange(y, m)[1])

    # 월간 — 시작이 전월 말일이고 종료가 같은 달 안
    prev = eom(e.year - 1, 12) if e.month == 1 else eom(e.year, e.month - 1)
    if s == prev:
        return (f'{e.year}-{e.month:02d}', '월별', e.year, e.month)

    q = (e.month - 1) // 3 + 1
    q_prev = eom(e.year - 1, 12) if q == 1 else eom(e.year, (q - 1) * 3)
    if s == q_prev:
        # 분기말이면 마감 분기, 아니면 QTD
        if e == eom(e.year, q * 3):
            return (f'{e.year}-Q{q}', '분기', e.year, q)
        return (f'{e.year}-Q{q}.QTD', 'QTD', e.year, q)

    h = 1 if e.month <= 6 else 2
    h_prev = eom(e.year - 1, 12) if h == 1 else eom(e.year, 6)
    if s == h_prev:
        return (f'{e.year}-H{h}.HTD', 'HTD', e.year, h)

    if s == eom(e.year - 1, 12):
        return (f'{e.year}-YTD', 'YTD', e.year, 0)
    return None


def resolve_market_for_window(start_iso: str, end_iso: str) -> dict | None:
    """날짜창에 맞는 시장 코멘트 payload.

    ① 창이 달력 기간과 일치하면 `resolve_market_payload` 그대로 (Admin 승인본 우선 →
       상위 키 → 기간 내 월간 병합 → 압축)
    ② 아니면(롤링 3M/6M·설정후) 창이 덮는 월간 승인본을 병합·압축
    ③ 아무것도 없으면 None — 호출부가 종료월 단독으로 폴백한다(기능 무중단)
    """
    from market_research.report.report_store import load_final

    hit = window_to_period(start_iso, end_iso)
    if hit:
        payload = resolve_market_payload(*hit)
        if payload:
            return payload
    months = months_covering(start_iso, end_iso)
    items = [(mp, load_final(mp, '_market')) for mp in months]
    merged = merge_market_payloads([(mp, p) for mp, p in items if p])
    return compact_market_payload(merged)
