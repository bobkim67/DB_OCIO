# -*- coding: utf-8 -*-
"""Migrate regime_memory.json + canonical wiki + debate memory pages to v11 taxonomy contract.

- topic_tags에서 non-taxonomy phrase 제거
- narrative_description 필드 분리
- history entry에 topic_tags 추출
- 06_Debate_Memory/*.md의 linked_regime_tags 갱신

Usage:
    python -m market_research.tools.migrate_regime_v11
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def main():
    from market_research.wiki.canonical import (
        normalize_regime_memory, update_canonical_regime,
    )
    from market_research.wiki.taxonomy import (
        extract_taxonomy_tags, validate_tags, write_remap_trace, TAXONOMY_SET,
    )
    from market_research.wiki.paths import DEBATE_MEMORY_DIR

    base = Path(__file__).resolve().parent.parent
    regime_file = base / 'data' / 'regime_memory.json'
    trace_file = base / 'data' / 'report_output' / '_taxonomy_remap_trace.jsonl'
    migration_trace: list[dict] = []

    # ── 1. regime_memory.json 재정규화 ──
    summary = {
        'current': {},
        'history_entries_normalized': 0,
        'history_with_tags': 0,
        'history_unresolved_only': 0,
        'debate_pages_updated': 0,
        'debate_pages_with_taxonomy_tags': 0,
        'debate_pages_unresolved_only': 0,
        'total_remapped_phrases': 0,
        'total_unresolved_phrases': 0,
    }

    before = json.loads(regime_file.read_text(encoding='utf-8'))
    before_tags = list(before.get('current', {}).get('topic_tags', []))
    before_non_taxonomy = [t for t in before_tags if t not in TAXONOMY_SET]
    summary['current']['before_topic_tags'] = before_tags
    summary['current']['before_non_taxonomy_count'] = len(before_non_taxonomy)

    # ── trace: current narrative + history narratives 매핑 ──
    cur_raw = before.get('current', {}).get('dominant_narrative', '')
    extract_taxonomy_tags(cur_raw, trace=migration_trace, source='regime_current')
    for i, h in enumerate(before.get('history', [])):
        h_narr = h.get('narrative', '')
        if h_narr:
            extract_taxonomy_tags(h_narr, trace=migration_trace, source=f'history[{i}]')

    # normalize
    normalized = normalize_regime_memory(before)
    current = normalized.get('current', {})
    summary['current']['after_topic_tags'] = current.get('topic_tags', [])
    summary['current']['unresolved'] = current.get('_unresolved_tags', [])
    summary['total_remapped_phrases'] += len(current.get('topic_tags', []))
    summary['total_unresolved_phrases'] += len(current.get('_unresolved_tags', []))

    for h in normalized.get('history', []):
        summary['history_entries_normalized'] += 1
        if h.get('topic_tags'):
            summary['history_with_tags'] += 1
            summary['total_remapped_phrases'] += len(h['topic_tags'])
        if h.get('_unresolved_tags'):
            if not h.get('topic_tags'):
                summary['history_unresolved_only'] += 1
            summary['total_unresolved_phrases'] += len(h['_unresolved_tags'])

    regime_file.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding='utf-8')
    update_canonical_regime(regime_file)

    # ── 2. debate memory pages의 linked_regime_tags 재정규화 ──
    # frontmatter만 부분 교체 (본문은 유지). linked_regime_tags를 canonical snapshot 기준으로 교정.
    canonical_tags = current.get('topic_tags', [])
    canonical_narr = current.get('dominant_narrative', '')
    canonical_desc = current.get('narrative_description', '')

    for md in sorted(DEBATE_MEMORY_DIR.glob('*.md')):
        text = md.read_text(encoding='utf-8')
        # frontmatter 추출
        m = re.match(r'^---\n(.*?)\n---\n(.*)$', text, re.DOTALL)
        if not m:
            continue
        fm_raw = m.group(1)
        body = m.group(2)

        fm_lines = fm_raw.split('\n')
        new_lines = []
        has_description = False
        for line in fm_lines:
            if line.startswith('linked_regime_tags:'):
                new_lines.append('linked_regime_tags: [' +
                                 ', '.join(f'"{t}"' for t in canonical_tags) + ']')
            elif line.startswith('linked_regime_narrative:'):
                new_lines.append(f'linked_regime_narrative: "{canonical_narr}"')
            elif line.startswith('linked_regime_description:'):
                has_description = True
                new_lines.append(f'linked_regime_description: "{canonical_desc}"')
            else:
                new_lines.append(line)
        if not has_description:
            # linked_regime_narrative 바로 뒤에 description 삽입
            out = []
            for line in new_lines:
                out.append(line)
                if line.startswith('linked_regime_narrative:'):
                    out.append(f'linked_regime_description: "{canonical_desc}"')
            new_lines = out

        # tag_match_mode 필드 추가 (없으면)
        if not any(l.startswith('tag_match_mode:') for l in new_lines):
            # type 바로 아래에 삽입
            out = []
            inserted = False
            for line in new_lines:
                out.append(line)
                if line.startswith('status:') and not inserted:
                    out.append('tag_match_mode: exact_taxonomy')
                    inserted = True
            new_lines = out

        new_fm = '\n'.join(new_lines)
        new_text = f'---\n{new_fm}\n---\n{body}'
        md.write_text(new_text, encoding='utf-8')
        summary['debate_pages_updated'] += 1
        if canonical_tags:
            summary['debate_pages_with_taxonomy_tags'] += 1
        elif current.get('_unresolved_tags'):
            summary['debate_pages_unresolved_only'] += 1

    # ── 3. trace 저장 (append mode, idempotent은 아님 — migration 재실행 시 복제됨) ──
    #    운영상은 migration 1회 + daily trace append이므로 축적 가치가 있음.
    written = write_remap_trace(migration_trace, trace_file)
    summary['remap_trace_rows_written'] = written
    summary['remap_trace_file'] = str(trace_file.relative_to(base))

    # ── 4. summary 저장 ──
    summary_file = base / 'data' / 'report_output' / '_migration_v11_summary.json'
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    # ── 4. 출력 ──
    print('═══ Migration v11 Summary ═══')
    print(f'Current regime:')
    print(f'  before topic_tags ({len(before_tags)}): {before_tags}')
    print(f'  after  topic_tags ({len(current.get("topic_tags", []))}): {current.get("topic_tags", [])}')
    print(f'  unresolved ({len(current.get("_unresolved_tags", []))}): {current.get("_unresolved_tags", [])}')
    print(f'  narrative_description: {current.get("narrative_description", "")[:80]}...')
    print(f'')
    print(f'History:')
    print(f'  entries normalized: {summary["history_entries_normalized"]}')
    print(f'  with taxonomy tags: {summary["history_with_tags"]}')
    print(f'  unresolved only: {summary["history_unresolved_only"]}')
    print(f'')
    print(f'Debate memory pages: {summary["debate_pages_updated"]}')
    print(f'')
    print(f'Totals:')
    print(f'  remapped phrases (taxonomy): {summary["total_remapped_phrases"]}')
    print(f'  unresolved phrases: {summary["total_unresolved_phrases"]}')
    print(f'')
    print(f'Trace rows written: {written} → {trace_file.name}')
    print(f'Summary file: {summary_file}')


if __name__ == '__main__':
    main()
