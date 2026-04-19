# -*- coding: utf-8 -*-
"""Canonical regime page writer.

**Sole writer of 05_Regime_Canonical/** pages. Only invoked from daily_update.Step 5.
regime_memory.json remains machine SSOT; this module renders a projection.

Schema (canonical regime page frontmatter):
    type: regime
    status: confirmed
    dominant_narrative: "<tag1> + <tag2> + <tag3>"   # tag form only
    topic_tags: ["<tag1>", "<tag2>", "<tag3>"]
    since: YYYY-MM-DD
    direction: bearish | bullish | neutral
    weeks: <int>
    source_of_truth: daily_update
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from market_research.wiki.paths import REGIME_CANONICAL_DIR
from market_research.wiki.taxonomy import (
    extract_taxonomy_tags, validate_tags, TAXONOMY_SET,
)

CURRENT_REGIME_PAGE = REGIME_CANONICAL_DIR / 'current_regime.md'
REGIME_HISTORY_PAGE = REGIME_CANONICAL_DIR / 'regime_history.md'


# ══════════════════════════════════════════
# Period / narrative 정규화
# ══════════════════════════════════════════

def normalize_period_date(s: str | None) -> str:
    """모든 regime 관련 날짜를 YYYY-MM-DD로 통일."""
    if not s or s == '?':
        return date.today().isoformat()
    s = str(s).strip()
    if len(s) == 10 and s[4] == '-' and s[7] == '-':
        return s                         # already YYYY-MM-DD
    if len(s) == 7 and s[4] == '-':
        return f'{s}-01'                 # YYYY-MM → YYYY-MM-01
    try:
        return datetime.fromisoformat(s).date().isoformat()
    except Exception:
        return date.today().isoformat()


def parse_narrative(narrative: str) -> tuple[list[str], list[str], str]:
    """narrative → (exact_taxonomy_tags, unresolved_phrases, original_description).

    topic_tags에는 taxonomy만 채우고, 서술형 원문은 description으로 보존.
    억지 매핑 금지 — 매핑 실패 구절은 unresolved로 노출.
    """
    if not narrative:
        return [], [], ''
    tags, unresolved = extract_taxonomy_tags(narrative)
    return tags, unresolved, str(narrative).strip()


def _dedupe_history(history: list[dict]) -> list[dict]:
    """연속 동일 narrative 병합 + 역순 period 수정 + taxonomy tag 추출."""
    out: list[dict] = []
    for entry in history:
        narr = (entry.get('narrative') or '').strip()
        period = entry.get('period', '')
        if ' ~ ' in period:
            start, end = period.split(' ~ ', 1)
            start = normalize_period_date(start)
            end = normalize_period_date(end)
            if start > end:
                start, end = end, start
            period = f'{start} ~ {end}'
        # taxonomy tag 추출 (없어도 narrative 원문은 보존)
        entry_tags, entry_unresolved = extract_taxonomy_tags(narr)
        new_entry = {
            'narrative': narr,
            'period': period,
            'topic_tags': entry_tags,
        }
        if entry_unresolved:
            new_entry['_unresolved_tags'] = entry_unresolved

        if out and out[-1]['narrative'] == narr:
            prev = out[-1]
            prev_end = prev['period'].split(' ~ ')[-1] if ' ~ ' in prev['period'] else prev['period']
            cur_end = period.split(' ~ ')[-1] if ' ~ ' in period else period
            start_prev = prev['period'].split(' ~ ')[0] if ' ~ ' in prev['period'] else prev['period']
            end_final = max(prev_end, cur_end)
            prev['period'] = f'{start_prev} ~ {end_final}'
            continue
        out.append(new_entry)
    return out


# ══════════════════════════════════════════
# regime_memory.json 정규화 (마이그레이션)
# ══════════════════════════════════════════

def normalize_regime_memory(regime: dict, strict: bool = True) -> dict:
    """Regime dict를 canonical schema에 맞춰 정규화 (순수 함수, 저장 안 함).

    Contract (strict=True, 기본):
      - topic_tags: exact taxonomy labels only (TOPIC_TAXONOMY 포함된 값)
      - narrative_description: 자연어 원문 보존
      - _unresolved_tags: 매핑 실패 phrase (기록용, shift 판정에 사용 금지)
      - dominant_narrative: topic_tags가 있으면 " + ".join(tags), 없으면 빈 문자열
      - 날짜: 전부 YYYY-MM-DD
      - history: 역순/중복 가드 + period 정규화
    """
    regime = dict(regime or {})
    current = dict(regime.get('current', {}))
    raw_narr = current.get('dominant_narrative', '') or ''
    existing_tags = current.get('topic_tags') or []

    # 1) 기존 topic_tags가 이미 taxonomy면 우선 채택
    pre_valid, pre_invalid = validate_tags(existing_tags)

    # 2) narrative에서 추가 태그 추출 (alias map)
    from_narr_tags, unresolved_from_narr = extract_taxonomy_tags(raw_narr)

    # 3) 병합: pre_valid 우선 + narrative 추출분
    merged: list[str] = []
    seen: set = set()
    for t in (*pre_valid, *from_narr_tags):
        if t not in seen:
            merged.append(t)
            seen.add(t)

    # 4) 미해결 phrase 집계
    unresolved = list(pre_invalid) + [p for p in unresolved_from_narr if p not in pre_invalid]

    current['topic_tags'] = merged
    current['_unresolved_tags'] = unresolved

    # description 우선순위:
    #   1) 이미 저장된 narrative_description (idempotent migration)
    #   2) raw_narr이 태그형이 아니면 raw_narr을 description으로 채택
    existing_desc = (current.get('narrative_description') or '').strip()
    is_tag_form = bool(raw_narr) and all(
        part.strip() in TAXONOMY_SET
        for part in (raw_narr.split(' + ') if ' + ' in raw_narr else [raw_narr])
    )
    if existing_desc:
        current['narrative_description'] = existing_desc          # 보존
    elif raw_narr and not is_tag_form:
        current['narrative_description'] = raw_narr               # 최초 마이그레이션
    else:
        current['narrative_description'] = current.get('narrative_description', '')

    # 태그형 narrative 재구성 — topic_tags 기반으로만
    if merged:
        current['dominant_narrative'] = ' + '.join(merged)
    else:
        current['dominant_narrative'] = ''

    current['since'] = normalize_period_date(current.get('since'))
    current.setdefault('direction', 'neutral')

    # weeks 자동 계산
    try:
        since_date = date.fromisoformat(current['since'])
        current['weeks'] = max(0, (date.today() - since_date).days // 7)
    except Exception:
        current['weeks'] = current.get('weeks', 0)

    regime['current'] = current

    # previous 정규화
    prev = dict(regime.get('previous', {}))
    if prev.get('ended'):
        prev['ended'] = normalize_period_date(prev['ended'])
    if prev.get('dominant_narrative'):
        prev_tags, _ = extract_taxonomy_tags(prev['dominant_narrative'])
        if prev_tags:
            prev['dominant_narrative_tags'] = prev_tags
            prev.setdefault('narrative_description', prev['dominant_narrative'])
            prev['dominant_narrative'] = ' + '.join(prev_tags)
    regime['previous'] = prev

    regime['history'] = _dedupe_history(regime.get('history', []))
    return regime


# ══════════════════════════════════════════
# Canonical page writer
# ══════════════════════════════════════════

def _render_current_regime_md(regime: dict) -> str:
    current = regime.get('current', {})
    prev = regime.get('previous', {})
    tags = current.get('topic_tags', [])
    unresolved = current.get('_unresolved_tags', [])
    tags_yaml = '[' + ', '.join(f'"{t}"' for t in tags) + ']'
    description = current.get('narrative_description', '')
    desc_yaml = description.replace('"', '\\"')

    lines = [
        '---',
        'type: regime',
        'status: confirmed',
        f'tag_match_mode: exact_taxonomy',
        f'dominant_narrative: "{current.get("dominant_narrative", "")}"',
        f'topic_tags: {tags_yaml}',
        f'narrative_description: "{desc_yaml}"',
        f'since: {current.get("since", "")}',
        f'direction: {current.get("direction", "neutral")}',
        f'weeks: {current.get("weeks", 0)}',
        'source_of_truth: daily_update',
        f'updated_at: {datetime.now().isoformat(timespec="seconds")}',
        '---',
        '',
        '# Current Regime',
        '',
        f'**Topic tags (exact taxonomy)**: `{", ".join(tags) if tags else "(없음)"}`',
        '',
    ]
    if description:
        lines += [f'**Narrative description (natural language)**: {description}', '']
    lines += [
        f'- Dominant narrative (tag form): `{current.get("dominant_narrative", "")}`',
        f'- Since: {current.get("since", "")}',
        f'- Direction: {current.get("direction", "neutral")}',
        f'- Weeks in regime: {current.get("weeks", 0)}',
        '',
    ]
    if unresolved:
        lines += [
            '## Unresolved phrases (매핑 실패 — 판정 미사용)',
            '',
        ] + [f'- `{p}`' for p in unresolved] + ['']
    if prev.get('dominant_narrative') or prev.get('narrative_description'):
        lines += [
            '## Previous regime',
            f'- Narrative (tags): `{prev.get("dominant_narrative", "")}`',
        ]
        if prev.get('narrative_description'):
            lines.append(f'- Description: {prev["narrative_description"]}')
        lines += [f'- Ended: {prev.get("ended", "")}', '']
    if regime.get('shift_detected'):
        lines += [
            '## Last shift',
            f'- {regime.get("shift_description", "")}',
            '',
        ]
    lines.append('> Written by `daily_update.Step 5`. Debate engine never writes to this page.')
    return '\n'.join(lines) + '\n'


def _render_history_md(regime: dict) -> str:
    history = regime.get('history', [])
    lines = [
        '---',
        'type: regime_history',
        'tag_match_mode: exact_taxonomy',
        'source_of_truth: daily_update',
        f'updated_at: {datetime.now().isoformat(timespec="seconds")}',
        '---',
        '',
        '# Regime History',
        '',
        f'총 {len(history)}개 entry',
        '',
        '| # | Topic tags | Narrative (description) | Period |',
        '|---|-----------|-------------------------|--------|',
    ]
    for i, entry in enumerate(history, 1):
        narr = (entry.get('narrative') or '').replace('|', '\\|')
        tags = entry.get('topic_tags') or []
        tags_str = ', '.join(f'`{t}`' for t in tags) if tags else '—'
        period = entry.get('period', '')
        lines.append(f'| {i} | {tags_str} | {narr} | {period} |')
    lines.append('')
    return '\n'.join(lines) + '\n'


def update_canonical_regime(regime_memory_path: Path | str) -> dict:
    """daily_update.Step 5 이후 호출. regime_memory.json을 읽어 canonical page 생성.

    Returns: normalized regime dict (caller가 필요 시 json 재저장).
    """
    path = Path(regime_memory_path)
    if not path.exists():
        return {}
    regime = json.loads(path.read_text(encoding='utf-8'))
    regime = normalize_regime_memory(regime)

    CURRENT_REGIME_PAGE.write_text(_render_current_regime_md(regime), encoding='utf-8')
    REGIME_HISTORY_PAGE.write_text(_render_history_md(regime), encoding='utf-8')
    return regime


def write_regime_history_page(regime: dict) -> None:
    REGIME_HISTORY_PAGE.write_text(_render_history_md(regime), encoding='utf-8')
