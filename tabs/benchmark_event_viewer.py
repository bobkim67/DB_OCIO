# -*- coding: utf-8 -*-
"""Benchmark-Event Viewer — BEW visualization contract 1차 파일럿.

read-only 소비자: market_research/data/benchmark_events/{YYYY-MM}.json 만 읽음.
contract 재계산 / mapper schema 변경 / GraphRAG 호출 모두 안 함.

화면:
  [상단] month / asset_class / source_type / signal_type / confidence_min 필터
  [메인] timeline (window scatter on date axis)
  [우측] graph (선택 window 의 seed subgraph; 없으면 전체 union)
  [하단] evidence cards (선택 window 의 cards)
  [하단 expander] debug
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_BEW_DIR = (Path(__file__).resolve().parent.parent
            / 'market_research' / 'data' / 'benchmark_events')

DEFAULT_MONTH = '2026-03'
SIGNAL_COLORS = {
    'drawdown': '#EF553B',
    'rebound': '#00CC96',
    'anomaly': '#AB63FA',
    'trend_break': '#FFA15A',
}
SOURCE_TAG_COLORS = {
    'naver_research': '#1f77b4',  # nr 파랑
    'news': '#7f7f7f',             # news 회색
}


# ───────────────────────────────────────────────────
# 1. contract 로드
# ───────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _load_contract(month: str) -> dict | None:
    fp = _BEW_DIR / f'{month}.json'
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding='utf-8'))
    except Exception:
        return None


def _list_available_months() -> list[str]:
    if not _BEW_DIR.exists():
        return []
    return sorted([fp.stem for fp in _BEW_DIR.glob('*.json')])


# ───────────────────────────────────────────────────
# 2. 필터 / 파생
# ───────────────────────────────────────────────────

def _apply_filters(contract: dict, asset_class: str, source_type: str,
                   signal_type: str, conf_min: float) -> tuple[list, list, dict]:
    """contract 에서 (windows, evidence_cards, source_mix_by_window) 필터링."""
    windows = contract.get('windows', []) or []
    cards = contract.get('evidence_cards', []) or []

    # window-level 필터: asset_class / signal_type / confidence
    fw = []
    for w in windows:
        if asset_class != '(전체)' and w.get('asset_class') != asset_class:
            continue
        if signal_type != '(전체)' and w.get('signal_type') != signal_type:
            continue
        if float(w.get('confidence', 0) or 0) < conf_min:
            continue
        fw.append(w)
    valid_wids = {w.get('window_id') for w in fw}

    # card-level 필터: 부모 window 가 살아있어야 + source_type 매칭
    fc = []
    for c in cards:
        if c.get('window_id') not in valid_wids:
            continue
        if source_type != '(전체)' and c.get('source_type') != source_type:
            continue
        fc.append(c)

    # window별 source mix 재계산 (filtered cards 기준)
    mix = {}
    for c in fc:
        wid = c.get('window_id')
        m = mix.setdefault(wid, {'naver_research': 0, 'news': 0})
        st_ = c.get('source_type')
        if st_ in m:
            m[st_] += 1
    return fw, fc, mix


# ───────────────────────────────────────────────────
# 3. timeline plot
# ───────────────────────────────────────────────────

def _render_timeline(windows: list, cards: list, source_mix: dict,
                     selected_wid: str | None):
    if not windows:
        st.info('표시할 window 가 없습니다 (필터 결과 0건).')
        return
    rows = []
    for w in windows:
        wid = w.get('window_id', '')
        nr = source_mix.get(wid, {}).get('naver_research', 0)
        nw = source_mix.get(wid, {}).get('news', 0)
        rows.append({
            'window_id': wid,
            'date_from': pd.Timestamp(w['date_from']),
            'date_to': pd.Timestamp(w['date_to']),
            'pivot': pd.Timestamp(w['pivot_date']),
            'asset_class': w.get('asset_class', ''),
            'benchmark': w.get('benchmark', ''),
            'signal_type': w.get('signal_type', ''),
            'zscore': float(w.get('zscore', 0) or 0),
            'move_pct': float(w.get('benchmark_move_pct', 0) or 0),
            'confidence': float(w.get('confidence', 0) or 0),
            'evidence_count': int(w.get('evidence_count', 0) or 0),
            'nr': nr, 'news': nw,
            'selected': (wid == selected_wid),
        })
    df = pd.DataFrame(rows).sort_values('date_from').reset_index(drop=True)

    # asset_class 별 y축 (자산군 묶음 탐색용)
    y_cats = list(df['asset_class'].unique())
    y_pos = {ac: i for i, ac in enumerate(y_cats)}
    df['y'] = df['asset_class'].map(y_pos)

    fig = go.Figure()
    # window 가로 막대 (date_from~date_to)
    for _, r in df.iterrows():
        size = 12 + min(20, abs(r['zscore']) * 4)
        outline = '#000000' if r['selected'] else '#ffffff'
        outline_w = 3 if r['selected'] else 1
        color = SIGNAL_COLORS.get(r['signal_type'], '#888888')
        # 막대(범위)
        fig.add_trace(go.Scatter(
            x=[r['date_from'], r['date_to']], y=[r['y'], r['y']],
            mode='lines',
            line=dict(color=color, width=4),
            opacity=0.8 if r['selected'] else 0.3,
            showlegend=False, hoverinfo='skip',
        ))
        # 피벗 점
        hover = (
            f"<b>{r['benchmark']} ({r['asset_class']})</b><br>"
            f"signal: {r['signal_type']} | conf: {r['confidence']:.2f}<br>"
            f"{r['date_from'].strftime('%m/%d')} ~ {r['date_to'].strftime('%m/%d')}<br>"
            f"move: {r['move_pct']:+.2f}% | z: {r['zscore']:+.2f}<br>"
            f"evidence: {r['evidence_count']} (nr {r['nr']} / news {r['news']})<br>"
            f"<i>id: {r['window_id']}</i>"
        )
        fig.add_trace(go.Scatter(
            x=[r['pivot']], y=[r['y']],
            mode='markers',
            marker=dict(size=size, color=color,
                        line=dict(color=outline, width=outline_w)),
            customdata=[[r['window_id']]],
            hovertemplate=hover + '<extra></extra>',
            showlegend=False,
        ))

    fig.update_layout(
        height=max(280, 50 + 40 * len(y_cats)),
        margin=dict(l=10, r=10, t=20, b=20),
        yaxis=dict(
            tickmode='array',
            tickvals=list(y_pos.values()),
            ticktext=list(y_pos.keys()),
            showgrid=True, zeroline=False,
        ),
        xaxis=dict(showgrid=True, type='date'),
        plot_bgcolor='white',
    )
    st.plotly_chart(fig, use_container_width=True, key='bew_timeline')

    # signal 범례
    st.caption(' '.join(
        [f'<span style="color:{c};font-weight:600">●</span> {s}'
         for s, c in SIGNAL_COLORS.items()]
    ), unsafe_allow_html=True)


# ───────────────────────────────────────────────────
# 4. graph plot
# ───────────────────────────────────────────────────

def _render_graph(contract: dict, selected_wid: str | None):
    g = contract.get('graph', {}) or {}
    nodes = g.get('nodes', []) or []
    edges = g.get('edges', []) or []
    if not nodes:
        st.info('graph seed 가 비어 있습니다.')
        return

    # 선택 window 가 있으면 그 window 가 끌어온 node 만 강조 (window_ids 사용)
    if selected_wid:
        focus_nodes = [n for n in nodes if selected_wid in (n.get('window_ids') or [])]
        focus_ids = {n['node_id'] for n in focus_nodes}
        if not focus_ids:
            st.caption(f'선택 window({selected_wid}) 와 직접 연결된 graph 노드가 없습니다 — 전체 그래프 표시')
            focus_ids = {n['node_id'] for n in nodes}
    else:
        focus_ids = {n['node_id'] for n in nodes}

    # circular layout (의존성 없는 단순 배치)
    import math
    n_focus = len(focus_ids)
    all_ids = list({n['node_id'] for n in nodes})
    pos = {}
    R_focus = 1.0
    R_outer = 1.8
    focus_list = sorted(focus_ids)
    others = [nid for nid in all_ids if nid not in focus_ids]
    for i, nid in enumerate(focus_list):
        ang = 2 * math.pi * i / max(1, n_focus)
        pos[nid] = (R_focus * math.cos(ang), R_focus * math.sin(ang))
    for i, nid in enumerate(others):
        ang = 2 * math.pi * i / max(1, len(others))
        pos[nid] = (R_outer * math.cos(ang), R_outer * math.sin(ang))

    fig = go.Figure()
    # edges
    for e in edges:
        f, t = e.get('from'), e.get('to')
        if f not in pos or t not in pos:
            continue
        fx, fy = pos[f]; tx, ty = pos[t]
        in_focus = (f in focus_ids and t in focus_ids)
        fig.add_trace(go.Scatter(
            x=[fx, tx, None], y=[fy, ty, None],
            mode='lines',
            line=dict(color='#bbbbbb' if not in_focus else '#444444',
                      width=1 if not in_focus else 2),
            opacity=0.4 if not in_focus else 0.9,
            hoverinfo='skip', showlegend=False,
        ))
    # nodes
    for n in nodes:
        nid = n['node_id']
        if nid not in pos:
            continue
        x, y = pos[nid]
        in_focus = nid in focus_ids
        srcs = n.get('source_types') or []
        if 'naver_research' in srcs:
            color = '#1f77b4'
        elif 'news' in srcs:
            color = '#7f7f7f'
        else:
            color = '#cccccc'
        sev = n.get('severity', '')
        size = 18 if in_focus else 10
        hover = (
            f"<b>{n.get('label','')}</b><br>"
            f"topic: {n.get('topic','')}<br>"
            f"severity: {sev}<br>"
            f"source_types: {', '.join(srcs) or '-'}<br>"
            f"window_ids: {', '.join(n.get('window_ids',[])) or '-'}"
        )
        fig.add_trace(go.Scatter(
            x=[x], y=[y], mode='markers+text',
            marker=dict(size=size, color=color,
                        line=dict(color='#000000' if in_focus else '#ffffff', width=2)),
            text=[n.get('label','')[:20]] if in_focus else [''],
            textposition='top center',
            textfont=dict(size=10),
            hovertemplate=hover + '<extra></extra>',
            showlegend=False,
        ))
    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        plot_bgcolor='white',
    )
    st.plotly_chart(fig, use_container_width=True, key='bew_graph')
    st.caption(
        f'노드 {len(nodes)} / 엣지 {len(edges)} | '
        f'<span style="color:#1f77b4">●</span> nr provenance &nbsp; '
        f'<span style="color:#7f7f7f">●</span> news provenance &nbsp; '
        f'<span style="color:#cccccc">●</span> 미표시',
        unsafe_allow_html=True,
    )


# ───────────────────────────────────────────────────
# 5. evidence cards
# ───────────────────────────────────────────────────

def _render_evidence_cards(cards: list, selected_wid: str | None):
    if selected_wid:
        cards = [c for c in cards if c.get('window_id') == selected_wid]
    if not cards:
        st.info('evidence card 가 없습니다 (필터 결과 또는 선택 window 매핑 0건).')
        return
    # 정렬: salience 내림차순
    cards = sorted(cards, key=lambda c: -float(c.get('salience', 0) or 0))
    for c in cards[:30]:
        st_ = c.get('source_type', '')
        tag = '[nr]' if st_ == 'naver_research' else '[news]'
        tag_color = SOURCE_TAG_COLORS.get(st_, '#888')
        broker = c.get('broker') or ''
        broker_str = f' / {broker}' if broker else ''
        st.markdown(
            f"<div style='padding:6px 8px; margin-bottom:4px; "
            f"border-left:3px solid {tag_color}; background:#fafafa;'>"
            f"<span style='color:{tag_color}; font-weight:700'>{tag}</span> "
            f"<span style='color:#888'>{c.get('date','')}</span> &nbsp; "
            f"<b>{c.get('asset_class','')}</b> · {c.get('primary_topic','')} &nbsp; "
            f"<span style='color:#888'>sal {float(c.get('salience',0)):.2f} · "
            f"L{c.get('match_level','?')}</span><br>"
            f"<span style='font-size:14px'>{c.get('title','')}</span><br>"
            f"<span style='color:#666; font-size:12px'>{c.get('source','')}{broker_str}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    if len(cards) > 30:
        st.caption(f'... 외 {len(cards)-30}건 (상위 30건만 표시)')


# ───────────────────────────────────────────────────
# 6. main render
# ───────────────────────────────────────────────────

def render(ctx: dict | None = None):
    st.subheader('Benchmark-Event Viewer')
    st.caption('BEW contract (`data/benchmark_events/{YYYY-MM}.json`) read-only 시각화')

    months = _list_available_months()
    if not months:
        st.error(f'BEW contract 가 없습니다: {_BEW_DIR}')
        st.code('python -m market_research.report.benchmark_event_mapper 2026-03')
        return

    # ── 컨트롤 바 ──
    c1, c2, c3, c4, c5 = st.columns([1.2, 1.4, 1.4, 1.4, 1.2])
    with c1:
        default_idx = months.index(DEFAULT_MONTH) if DEFAULT_MONTH in months else len(months) - 1
        sel_month = st.selectbox('Month', months, index=default_idx, key='bew_month')

    contract = _load_contract(sel_month)
    if contract is None:
        st.warning(f'{sel_month} contract 로드 실패. 다른 월을 선택하세요.')
        return

    windows_all = contract.get('windows', []) or []
    if not windows_all:
        st.warning(f'{sel_month} contract 에 window 0건. 빈 contract 입니다.')
        with st.expander('contract debug'):
            st.json(contract.get('debug', {}))
        return

    asset_classes = ['(전체)'] + sorted({w.get('asset_class', '') for w in windows_all if w.get('asset_class')})
    signal_types = ['(전체)'] + sorted({w.get('signal_type', '') for w in windows_all if w.get('signal_type')})
    with c2:
        sel_ac = st.selectbox('자산군', asset_classes, key='bew_ac')
    with c3:
        sel_st = st.selectbox('Source', ['(전체)', 'naver_research', 'news'], key='bew_st')
    with c4:
        sel_sig = st.selectbox('Signal', signal_types, key='bew_sig')
    with c5:
        conf_min = st.slider('confidence ≥', 0.0, 1.5, 0.0, 0.05, key='bew_conf')

    fw, fc, mix = _apply_filters(contract, sel_ac, sel_st, sel_sig, conf_min)

    # ── window 선택 ──
    wid_options = ['(자동: 전체)'] + [
        f"{w['window_id']}  |  {w['benchmark']} {w['signal_type']} "
        f"({w['date_from']}~{w['date_to']}, conf {w.get('confidence',0):.2f})"
        for w in fw
    ]
    sel_wid_label = st.selectbox(
        f'Window 선택 ({len(fw)}건 필터링됨)',
        wid_options, index=0, key='bew_wid',
    )
    selected_wid = None if sel_wid_label.startswith('(자동') else sel_wid_label.split('  |')[0]

    st.markdown('---')

    # ── 메인 영역 ──
    left, right = st.columns([1.4, 1.0])
    with left:
        st.markdown('##### Timeline')
        _render_timeline(fw, fc, mix, selected_wid)

        # 선택 window 메타
        if selected_wid:
            sel_w = next((w for w in fw if w['window_id'] == selected_wid), None)
            if sel_w:
                st.markdown(
                    f"**선택 window**: `{sel_w['window_id']}` &nbsp; "
                    f"**{sel_w['benchmark']}** ({sel_w['asset_class']}) &nbsp; "
                    f"{sel_w['signal_type']} &nbsp; | &nbsp; "
                    f"{sel_w['date_from']} ~ {sel_w['date_to']} &nbsp; | &nbsp; "
                    f"move {sel_w['benchmark_move_pct']:+.2f}% &nbsp; "
                    f"z {sel_w['zscore']:+.2f} &nbsp; "
                    f"conf {sel_w.get('confidence',0):.2f} &nbsp; "
                    f"evidence {sel_w.get('evidence_count',0)} "
                    f"(nr {mix.get(selected_wid,{}).get('naver_research',0)} / "
                    f"news {mix.get(selected_wid,{}).get('news',0)}) &nbsp; "
                    f"topics: {', '.join(sel_w.get('mapped_topics',[]) or []) or '-'}"
                )

    with right:
        st.markdown('##### Graph seed')
        _render_graph(contract, selected_wid)

    st.markdown('---')
    st.markdown('##### Evidence cards')
    _render_evidence_cards(fc, selected_wid)

    # ── debug ──
    with st.expander('debug / contract metadata'):
        dbg = contract.get('debug', {}) or {}
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric('windows (raw)', dbg.get('window_count', len(windows_all)))
            st.metric('unmapped windows', dbg.get('unmapped_windows', 0))
        with m2:
            sm = dbg.get('source_mix', {})
            st.metric('evidence total', dbg.get('evidence_total', 0))
            st.metric('source mix (nr/news)',
                      f"{sm.get('naver_research', 0)} / {sm.get('news', 0)}")
        with m3:
            gs = dbg.get('graph_size', {})
            st.metric('graph nodes', gs.get('nodes', 0))
            st.metric('graph edges', gs.get('edges', 0))
        st.write('**filter 결과**: ',
                 f"windows {len(fw)} / cards {len(fc)} / 선택 wid `{selected_wid or '-'}`")
        st.write('**parameters (mapper 임계치)**:')
        st.json(dbg.get('parameters', {}))
