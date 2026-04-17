# -*- coding: utf-8 -*-
"""Propose/apply PHRASE_ALIAS candidates from _taxonomy_remap_trace.jsonl.

Propose mode (default)
----------------------
Aggregates unresolved phrases from trace, suggests taxonomy candidates via a
conservative substring heuristic, and emits:
  data/report_output/alias_candidates.json
  data/report_output/alias_candidates_report.md

Apply mode
----------
Reads config/phrase_alias_approved.yaml, validates every entry:
  - mapped value MUST be in TOPIC_TAXONOMY (else rejected)
  - phrase already in built-in PHRASE_ALIAS with same value → duplicate (skipped)
  - phrase already in built-in PHRASE_ALIAS with different value → rejected
  - phrase equals mapped value → skipped (already exact taxonomy tag)

**Does not mutate source code.** The runtime merge happens automatically via
``taxonomy._load_approved_alias()`` on the next import (setdefault semantics —
built-in PHRASE_ALIAS wins on conflict).

Usage
-----
  python -m market_research.tools.alias_review --propose
  python -m market_research.tools.alias_review --apply
  python -m market_research.tools.alias_review --apply --strict
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
TRACE_FILE = BASE_DIR / 'data' / 'report_output' / '_taxonomy_remap_trace.jsonl'
APPROVED_FILE = BASE_DIR / 'config' / 'phrase_alias_approved.yaml'
OUT_JSON = BASE_DIR / 'data' / 'report_output' / 'alias_candidates.json'
OUT_MD = BASE_DIR / 'data' / 'report_output' / 'alias_candidates_report.md'


def _load_trace(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _suggest_taxonomy(phrase: str,
                      taxonomy: list[str],
                      alias: dict[str, str]) -> list[dict]:
    """Conservative suggestion: substring + existing alias key substring.

    Returns ``[{tag, score, reason}, ...]`` sorted by score desc. Empty list
    if nothing plausible — that is the expected outcome for most descriptive
    phrases, and the caller should mark them `keep_unresolved`.
    """
    phrase_norm = phrase.replace(' ', '').lower()
    hits: dict[str, tuple[float, list[str]]] = {}
    for tag in taxonomy:
        tag_norm = tag.replace('_', '').lower()
        if tag_norm and tag_norm in phrase_norm:
            prev = hits.get(tag, (0.0, []))
            hits[tag] = (prev[0] + 0.4, prev[1] + [f'taxonomy `{tag}` substring'])
    for key, val in alias.items():
        if key and key in phrase and val in taxonomy:
            prev = hits.get(val, (0.0, []))
            hits[val] = (prev[0] + 0.3, prev[1] + [f'alias `{key}` → {val} substring'])
    suggestions: list[dict] = []
    for tag, (score, reasons) in hits.items():
        suggestions.append({
            'tag': tag,
            'score': min(1.0, round(score, 2)),
            'reason': '; '.join(reasons[:3]),
        })
    suggestions.sort(key=lambda x: -x['score'])
    return suggestions


def cmd_propose() -> int:
    from market_research.wiki.taxonomy import TOPIC_TAXONOMY, PHRASE_ALIAS

    rows = _load_trace(TRACE_FILE)
    payload: dict = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'source': str(TRACE_FILE.relative_to(BASE_DIR)),
        'total_trace_rows': len(rows),
        'match_type_counts': {'exact': 0, 'alias': 0, 'unresolved': 0},
        'alias_matches_sample': [],
        'unresolved_phrases': [],
    }

    if not rows:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding='utf-8')
        OUT_MD.write_text(
            '# Alias candidates report\n\n'
            f'- Generated: `{payload["generated_at"]}`\n'
            f'- Source: `{payload["source"]}` (empty or missing)\n'
            '- No trace rows to aggregate.\n',
            encoding='utf-8',
        )
        print(f'[propose] trace empty/missing → wrote stub reports to '
              f'{OUT_JSON.name} + {OUT_MD.name}')
        return 0

    unresolved: dict[str, dict] = {}
    alias_matched: Counter = Counter()
    exact_matched: Counter = Counter()
    for r in rows:
        mt = r.get('match_type')
        phrase = (r.get('original_phrase') or '').strip()
        source = r.get('source') or ''
        if not phrase:
            continue
        if mt == 'unresolved':
            cur = unresolved.setdefault(phrase, {
                'phrase': phrase,
                'normalized': phrase.replace('  ', ' ').strip(),
                'count': 0,
                'sources': [],
                'first_seen_source': source,
                'last_seen_source': source,
            })
            cur['count'] += 1
            cur['last_seen_source'] = source
            if source and source not in cur['sources']:
                cur['sources'].append(source)
        elif mt == 'alias':
            alias_matched[(phrase, r.get('mapped_tag'))] += 1
        elif mt == 'exact':
            exact_matched[phrase] += 1

    payload['match_type_counts'] = {
        'exact': int(sum(exact_matched.values())),
        'alias': int(sum(alias_matched.values())),
        'unresolved': int(sum(v['count'] for v in unresolved.values())),
    }
    payload['alias_matches_sample'] = [
        {'phrase': p, 'mapped_tag': t, 'count': c}
        for (p, t), c in alias_matched.most_common(20)
    ]

    built: list[dict] = []
    for phrase, entry in unresolved.items():
        sug = _suggest_taxonomy(phrase, TOPIC_TAXONOMY, PHRASE_ALIAS)
        entry['suggested_taxonomy'] = sug[:3]
        entry['confidence_proxy'] = sug[0]['score'] if sug else 0.0
        entry['sample_contexts'] = entry['sources'][:5]
        # Conservative: propose only when score >= 0.4 AND count >= 2
        if sug and sug[0]['score'] >= 0.4 and entry['count'] >= 2:
            entry['recommended_action'] = 'propose_alias'
        elif sug and sug[0]['score'] >= 0.4 and entry['count'] >= 1:
            entry['recommended_action'] = 'review_needed'
        else:
            entry['recommended_action'] = 'keep_unresolved'
        built.append(entry)
    built.sort(key=lambda e: (-e['count'], -e['confidence_proxy'], e['phrase']))
    payload['unresolved_phrases'] = built

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding='utf-8')

    mt = payload['match_type_counts']
    lines = [
        '# Alias candidates report',
        '',
        f'- Generated: `{payload["generated_at"]}`',
        f'- Source: `{payload["source"]}`',
        f'- Total trace rows: **{payload["total_trace_rows"]}**',
        f'- Match type counts: exact={mt["exact"]}, alias={mt["alias"]}, '
        f'unresolved={mt["unresolved"]}',
        '',
        '## Unresolved phrases (propose candidates)',
        '',
        '| phrase | count | sources | suggested tag | score | action |',
        '|---|---|---|---|---|---|',
    ]
    for e in built:
        top = e['suggested_taxonomy'][0] if e['suggested_taxonomy'] else None
        top_tag = top['tag'] if top else '—'
        top_score = f'{top["score"]:.2f}' if top else '—'
        src_preview = ', '.join(e['sources'][:3])
        lines.append(
            f'| `{e["phrase"]}` | {e["count"]} | {src_preview} | '
            f'{top_tag} | {top_score} | {e["recommended_action"]} |'
        )
    lines += [
        '',
        '## Action legend',
        '',
        '- `propose_alias` — high confidence (score ≥ 0.4, count ≥ 2).',
        '  Consider copying to `config/phrase_alias_approved.yaml::approved`.',
        '- `review_needed` — medium confidence (score ≥ 0.4, count 1). Human review.',
        '- `keep_unresolved` — no confident hit. Add to `keep_unresolved:` if it',
        '  is a known descriptive phrase that should stay out of topic_tags.',
        '',
        '## How to approve',
        '',
        '1. Edit `market_research/config/phrase_alias_approved.yaml`.',
        '2. Under `approved:`, add `"<phrase>": <taxonomy_tag>` entries.',
        '3. Run `python -m market_research.tools.alias_review --apply` to',
        '   validate and preview the runtime merge.',
        '',
        '> Force-mapping descriptive phrases is disallowed by the v11 taxonomy',
        '> contract. If the top suggestion is not accurate, prefer `keep_unresolved`.',
        '',
    ]
    OUT_MD.write_text('\n'.join(lines), encoding='utf-8')

    print(f'[propose] wrote {OUT_JSON.name} + {OUT_MD.name}')
    print(f'  total trace rows: {payload["total_trace_rows"]}')
    print(f'  unresolved unique phrases: {len(built)}')
    by_action = Counter(e['recommended_action'] for e in built)
    for k, v in by_action.most_common():
        print(f'    {k}: {v}')
    return 0


def cmd_apply(strict: bool = False) -> int:
    from market_research.wiki.taxonomy import TAXONOMY_SET, PHRASE_ALIAS

    if not APPROVED_FILE.exists():
        print(f'[apply] approved file not found: {APPROVED_FILE}')
        print('        PHRASE_ALIAS unchanged. Create the file and rerun.')
        return 0

    try:
        import yaml
    except ImportError:
        print('[apply] PyYAML is not installed.')
        return 2

    try:
        raw = APPROVED_FILE.read_text(encoding='utf-8')
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        print(f'[apply] YAML parse error: {exc}')
        return 2

    if not isinstance(data, dict):
        print('[apply] top-level document must be a mapping')
        return 2

    approved = data.get('approved') or {}
    keep_unresolved = data.get('keep_unresolved') or []
    if not isinstance(approved, dict):
        print('[apply] `approved:` must be a mapping')
        return 2
    if not isinstance(keep_unresolved, list):
        print('[apply] `keep_unresolved:` must be a list')
        return 2

    accepted: list[tuple[str, str]] = []
    rejected: list[tuple[str, str, str]] = []  # (phrase, tag, reason)
    duplicates: list[tuple[str, str]] = []
    self_map: list[str] = []

    for phrase, tag in approved.items():
        phrase_s = str(phrase).strip()
        tag_s = str(tag).strip()
        if not phrase_s or not tag_s:
            continue
        if tag_s not in TAXONOMY_SET:
            rejected.append((phrase_s, tag_s, 'non-taxonomy value'))
            continue
        if phrase_s == tag_s:
            self_map.append(phrase_s)
            continue
        if phrase_s in PHRASE_ALIAS:
            existing = PHRASE_ALIAS[phrase_s]
            if existing == tag_s:
                duplicates.append((phrase_s, tag_s))
            else:
                rejected.append((phrase_s, tag_s,
                                 f'conflicts with builtin → {existing}'))
            continue
        accepted.append((phrase_s, tag_s))

    print('=== alias_review --apply ===')
    print(f'approved file: {APPROVED_FILE}')
    print(f'accepted (new aliases): {len(accepted)}')
    for p, t in accepted:
        print(f'  + "{p}" -> {t}')
    if duplicates:
        print(f'duplicates (already in PHRASE_ALIAS, same target): {len(duplicates)}')
        for p, t in duplicates:
            print(f'  = "{p}" -> {t}')
    if self_map:
        print(f'self-map skipped (phrase == taxonomy tag): {len(self_map)}')
        for p in self_map:
            print(f'  - "{p}"')
    if rejected:
        print(f'REJECTED: {len(rejected)}')
        for p, t, reason in rejected:
            print(f'  x "{p}" -> {t}  ({reason})')

    print(f'keep_unresolved entries: {len(keep_unresolved)}')
    for p in keep_unresolved:
        print(f'  ~ "{p}"')

    print('')
    print('Runtime merge: taxonomy._load_approved_alias() picks up accepted')
    print('entries on next import (setdefault — builtin PHRASE_ALIAS wins on conflict).')
    if rejected and strict:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m market_research.tools.alias_review',
        description='Propose/apply PHRASE_ALIAS candidates from taxonomy remap trace.',
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--propose', action='store_true',
                       help='Generate candidate report from trace file')
    group.add_argument('--apply', action='store_true',
                       help='Validate approved yaml and preview merge')
    parser.add_argument('--strict', action='store_true',
                        help='With --apply, exit non-zero on any rejected entry')
    args = parser.parse_args(argv)

    if args.propose:
        return cmd_propose()
    if args.apply:
        return cmd_apply(strict=args.strict)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
