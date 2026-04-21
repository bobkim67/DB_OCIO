# -*- coding: utf-8 -*-
"""07_Graph_Evidence/ writer — transmission path DRAFT evidence only.

Phase 3 P0/P1 산출물. canonical 승격은 금지. Phase 4+에서 승격 검토.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from market_research.wiki.paths import GRAPH_EVIDENCE_DIR


def write_transmission_paths_draft(graph: dict, period: str) -> Path:
    """Graph의 transmission_paths를 07_Graph_Evidence/ draft 페이지로 렌더링."""
    paths = graph.get('transmission_paths', []) or []
    meta = graph.get('metadata', {})
    out = GRAPH_EVIDENCE_DIR / f'{period}_transmission_paths_draft.md'

    lines = [
        '---',
        'type: graph_evidence',
        'status: draft',
        'promoted_to_canonical: false',
        f'period: {period}',
        f'total_paths: {len(paths)}',
        f'node_count: {meta.get("node_count", "?")}',
        f'edge_count: {meta.get("edge_count", "?")}',
        'source_of_truth: graph_rag.precompute_transmission_paths',
        'phase: P0',
        f'updated_at: {datetime.now().isoformat(timespec="seconds")}',
        '---',
        '',
        f'# Transmission Paths (DRAFT) — {period}',
        '',
        '> Draft evidence only. **Do not reference from canonical asset/regime pages.**',
        '> Promotion to canonical is gated on Phase 4+.',
        '',
        f'## Summary',
        '',
        f'- Total paths: {len(paths)}',
        f'- Graph nodes: {meta.get("node_count", "?")} · edges: {meta.get("edge_count", "?")}',
        '',
        '## Paths',
        '',
        '| # | Trigger | Target | Confidence | Path |',
        '|---|---------|--------|------------|------|',
    ]
    for i, p in enumerate(paths, 1):
        path_repr = ' → '.join(p.get('path_labels') or p.get('path', []))
        lines.append(
            f'| {i} | `{p.get("trigger", "")}` | `{p.get("target", "")}` | '
            f'{p.get("confidence", 0):.3f} | {path_repr} |'
        )
    lines += [
        '',
        '## Usage guardrails',
        '',
        '- 이 페이지는 `07_Graph_Evidence/` 하위 draft. canonical 05/01~04 페이지가 직접 참조하면 안 된다.',
        '- P0 개선 (word-boundary 매칭 + self-loop 필터 + pair당 1경로) 적용 버전.',
        '- P1 (dynamic trigger/target + alias) 완료 시 별도 페이지 분기 예정.',
        '- P1까지 완료된 경로만 canonical asset page의 supporting evidence로 승격 검토 가능 (Phase 4+).',
        '',
    ]
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return out


# ══════════════════════════════════════════
# 월간 summary + quality aggregate
# ══════════════════════════════════════════

def write_transmission_paths_summary(graph: dict, period: str,
                                      phase: str = 'P1') -> tuple[Path, Path]:
    """사람이 한눈에 품질 점검할 수 있는 요약 페이지 + quality aggregate json.

    Returns: (summary_md, monthly_json)
    """
    paths = graph.get('transmission_paths', []) or []
    meta = graph.get('metadata', {})

    unique_triggers = sorted({p['trigger'] for p in paths if p.get('trigger')})
    unique_targets = sorted({p['target'] for p in paths if p.get('target')})
    avg_conf = round(sum(p.get('confidence', 0) for p in paths) / len(paths), 3) if paths else 0

    # trigger/target 후보는 graph_vocab에서 가져옴
    try:
        from market_research.analyze.graph_vocab import (
            DRIVER_TAXONOMY, ASSET_TAXONOMY,
        )
        if phase == 'P1':
            from market_research.analyze.graph_rag import (
                _select_dynamic_triggers, _select_dynamic_targets,
            )
            trigger_candidates = _select_dynamic_triggers(graph)
            target_candidates = _select_dynamic_targets(graph)
        else:
            trigger_candidates = DRIVER_TAXONOMY
            target_candidates = ASSET_TAXONOMY
    except Exception:
        trigger_candidates = unique_triggers
        target_candidates = unique_targets

    trigger_coverage = len(unique_triggers) / max(len(trigger_candidates), 1)
    target_coverage = len(unique_targets) / max(len(target_candidates), 1)
    unmatched_triggers = sorted(set(trigger_candidates) - set(unique_triggers))
    unmatched_targets = sorted(set(target_candidates) - set(unique_targets))

    monthly = {
        'month': period,
        'phase': phase,
        'promoted_to_canonical': False,
        'total_paths': len(paths),
        'unique_triggers': len(unique_triggers),
        'unique_targets': len(unique_targets),
        'trigger_coverage': round(trigger_coverage, 3),
        'target_coverage': round(target_coverage, 3),
        'unmatched_triggers': unmatched_triggers,
        'unmatched_targets': unmatched_targets,
        'avg_confidence': avg_conf,
        'node_count': meta.get('node_count'),
        'edge_count': meta.get('edge_count'),
        'generated_at': datetime.now().isoformat(timespec='seconds'),
    }

    # monthly json
    out_json = (Path(__file__).resolve().parent.parent /
                'data' / 'report_output' / '_transmission_path_quality_monthly.json')
    out_json.parent.mkdir(parents=True, exist_ok=True)
    # 누적 append 구조: list of monthly records
    existing: list[dict] = []
    if out_json.exists():
        try:
            existing = json.loads(out_json.read_text(encoding='utf-8'))
            if not isinstance(existing, list):
                existing = [existing]
        except Exception:
            existing = []
    # 같은 month + phase는 덮어쓰기
    existing = [r for r in existing
                if not (r.get('month') == period and r.get('phase') == phase)]
    existing.append(monthly)
    out_json.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')

    # summary md
    summary_md = GRAPH_EVIDENCE_DIR / 'transmission_paths_summary.md'
    lines = [
        '---',
        'type: graph_evidence_summary',
        'status: draft',
        'promoted_to_canonical: false',
        f'latest_period: {period}',
        f'latest_phase: {phase}',
        f'updated_at: {datetime.now().isoformat(timespec="seconds")}',
        '---',
        '',
        '# Transmission Paths — Summary',
        '',
        '> Monthly quality overview. 사람이 한눈에 drift / coverage 확인.',
        '> Canonical 승격은 Phase 4+ 이후에만 검토.',
        '',
        '## Latest snapshot',
        '',
        f'- **Period**: {period}',
        f'- **Phase**: {phase}',
        f'- **Total paths**: {len(paths)}',
        f'- **Unique triggers**: {len(unique_triggers)} / {len(trigger_candidates)} '
        f'(coverage {trigger_coverage:.0%})',
        f'- **Unique targets**: {len(unique_targets)} / {len(target_candidates)} '
        f'(coverage {target_coverage:.0%})',
        f'- **Avg confidence**: {avg_conf:.3f}',
        f'- **Graph size**: {meta.get("node_count", "?")} nodes / {meta.get("edge_count", "?")} edges',
        '',
        '## Active triggers',
        '',
    ] + [f'- `{t}`' for t in unique_triggers] + ['']
    lines += ['## Active targets', ''] + [f'- `{t}`' for t in unique_targets] + ['']
    if unmatched_triggers:
        lines += ['## Unmatched triggers (candidate에 있으나 path 없음)', '']
        lines += [f'- `{t}`' for t in unmatched_triggers] + ['']
    if unmatched_targets:
        lines += ['## Unmatched targets', '']
        lines += [f'- `{t}`' for t in unmatched_targets] + ['']
    # 최근 monthly 기록
    lines += ['## Historical records (누적)', '',
              '| Month | Phase | Paths | Triggers | Targets | Avg Conf |',
              '|-------|-------|-------|----------|---------|----------|']
    for r in existing[-12:]:
        lines.append(f'| {r["month"]} | {r["phase"]} | {r["total_paths"]} | '
                     f'{r["unique_triggers"]}/{len(trigger_candidates)} | '
                     f'{r["unique_targets"]}/{len(target_candidates)} | '
                     f'{r["avg_confidence"]:.3f} |')
    lines += ['', '## Guardrails', '',
              '- 이 페이지는 `07_Graph_Evidence/` 하위 draft 요약.',
              '- canonical asset/regime 페이지가 이 수치를 직접 참조하면 안 된다.',
              '- 수치 drift를 월간으로 관찰할 목적.', '']
    summary_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    return summary_md, out_json
