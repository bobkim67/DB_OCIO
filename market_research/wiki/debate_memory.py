# -*- coding: utf-8 -*-
"""Debate memory writer — 06_Debate_Memory/ pages.

Writes debate narrative, disagreement summary, watchpoints to draft-tier wiki.
Never modifies regime_memory.json or 05_Regime_Canonical/ pages.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from market_research.wiki.paths import DEBATE_MEMORY_DIR


def _fmt_list(items, prefix='- '):
    if not items:
        return '- (없음)\n'
    out = []
    for it in items:
        if isinstance(it, dict):
            out.append(f'{prefix}{json.dumps(it, ensure_ascii=False)}')
        else:
            out.append(f'{prefix}{it}')
    return '\n'.join(out) + '\n'


def _render_debate_memory_md(draft: dict, canonical_regime_snapshot: dict) -> str:
    fund = draft.get('fund_code', '_market')
    period = draft.get('period', '')
    generated = draft.get('generated_at', datetime.now().isoformat(timespec='seconds'))
    debate_narrative = draft.get('debate_narrative', '')
    consensus = draft.get('consensus_points', [])
    disagree = draft.get('disagreements', [])
    tails = draft.get('tail_risks', [])

    current = canonical_regime_snapshot.get('current', {}) if canonical_regime_snapshot else {}
    linked_since = current.get('since', '')
    canonical_narr = current.get('dominant_narrative', '')
    canonical_desc = current.get('narrative_description', '')
    # exact taxonomy only (이중 방어)
    from market_research.wiki.taxonomy import TAXONOMY_SET
    canonical_tags = [t for t in current.get('topic_tags', []) if t in TAXONOMY_SET]

    lines = [
        '---',
        'type: debate_memory',
        'status: provisional',
        'tag_match_mode: exact_taxonomy',
        f'fund_code: {fund}',
        f'period: {period}',
        f'debate_date: {generated}',
        f'linked_regime_since: {linked_since}',
        f'linked_regime_narrative: "{canonical_narr}"',
        f'linked_regime_description: "{canonical_desc}"',
        f'linked_regime_tags: [{", ".join(chr(34)+t+chr(34) for t in canonical_tags)}]',
        'source_of_truth: debate_engine',
        '---',
        '',
        f'# Debate Memory — {fund} / {period}',
        '',
        '## Debate narrative (interpretation only, NOT canonical regime)',
        '',
        debate_narrative or '(없음)',
        '',
        '## Consensus points',
        _fmt_list(consensus),
        '## Competing interpretations / disagreements',
        _fmt_list(disagree),
        '## Tail risks / Watchpoints',
        _fmt_list(tails),
    ]

    if canonical_narr and debate_narrative and canonical_narr not in debate_narrative:
        lines += [
            '## Divergence from canonical regime',
            '',
            f'- Canonical regime: `{canonical_narr}` (since {linked_since})',
            f'- Debate interpretation differs — flagged for review.',
            '',
        ]

    lines.append('> Written by debate engine. Canonical regime page is unaffected.')
    return '\n'.join(lines) + '\n'


def write_debate_memory_page(draft_data: dict, regime_memory_path: Path | str) -> Path:
    """draft_data (debate_service.run_debate_and_save의 반환값) → debate memory 페이지.

    Parameters
    ----------
    draft_data : dict
        debate_service가 save_draft에 넘기는 dict. 최소한 아래 키 포함:
          - fund_code, period, generated_at
          - debate_narrative (optional — _summarize_debate_narrative 결과)
          - consensus_points, disagreements, tail_risks
    regime_memory_path : Path
        현재 canonical regime의 snapshot을 읽기 위한 json 경로.
    """
    snapshot = {}
    path = Path(regime_memory_path)
    if path.exists():
        try:
            snapshot = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            snapshot = {}

    fund = draft_data.get('fund_code', '_market')
    period = draft_data.get('period', datetime.now().strftime('%Y-%m'))
    generated_at = draft_data.get('generated_at', datetime.now().isoformat(timespec='seconds'))
    # timestamp suffix로 같은 날 여러 debate 보존
    ts = generated_at.replace(':', '').replace('-', '')[:15]  # YYYYMMDDTHHMMSS
    out_file = DEBATE_MEMORY_DIR / f'{period}_{fund}_{ts}.md'
    out_file.write_text(_render_debate_memory_md(draft_data, snapshot), encoding='utf-8')
    return out_file
