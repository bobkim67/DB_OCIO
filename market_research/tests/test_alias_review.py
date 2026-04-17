# -*- coding: utf-8 -*-
"""Tests for the PHRASE_ALIAS propose/apply workflow (v13).

Cases:
  1. Missing approved yaml → built-in PHRASE_ALIAS unchanged at load time.
  2. Approved yaml with non-taxonomy value → silently dropped by loader,
     surfaced as REJECTED by --apply.
  3. Approved yaml with exact taxonomy value → merged at runtime via
     _load_approved_alias(), reachable from extract_taxonomy_tags().
  4. keep_unresolved phrase stays unresolved (no force mapping).
  5. --propose on the current trace file produces a valid JSON report whose
     unresolved set matches the trace's unresolved set.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
APPROVED_FILE = BASE / 'config' / 'phrase_alias_approved.yaml'
OUT_JSON = BASE / 'data' / 'report_output' / 'alias_candidates.json'


def _pass(name: str):
    print(f'  PASS — {name}')


def _fail(name: str, msg: str):
    print(f'  FAIL — {name}: {msg}')
    raise AssertionError(f'{name}: {msg}')


def _write_approved(yaml_text: str):
    APPROVED_FILE.parent.mkdir(parents=True, exist_ok=True)
    APPROVED_FILE.write_text(yaml_text, encoding='utf-8')


def _reload_taxonomy():
    """Force re-import of taxonomy module so loader runs again."""
    import importlib
    import market_research.wiki.taxonomy as tax_mod
    importlib.reload(tax_mod)
    return tax_mod


def test_case_1_missing_yaml_unchanged():
    backup = APPROVED_FILE.read_bytes() if APPROVED_FILE.exists() else None
    try:
        if APPROVED_FILE.exists():
            APPROVED_FILE.unlink()
        tax_mod = _reload_taxonomy()
        if '지정학' not in tax_mod.PHRASE_ALIAS:
            _fail('case1.builtin_preserved',
                  'built-in entry 지정학 missing after reload w/o yaml')
        # arbitrary non-builtin phrase should NOT be present
        if '완전히 새로운 표현' in tax_mod.PHRASE_ALIAS:
            _fail('case1.no_phantom_entry',
                  'phantom entry present without yaml')
        _pass('case1: approved yaml 없음 → PHRASE_ALIAS 불변')
    finally:
        if backup is not None:
            APPROVED_FILE.write_bytes(backup)
        _reload_taxonomy()


def test_case_2_non_taxonomy_rejected():
    backup = APPROVED_FILE.read_bytes() if APPROVED_FILE.exists() else None
    try:
        _write_approved(
            'approved:\n'
            '  "잘못된매핑": 지정학완화_아닌_태그\n'
            '  "또다른매핑": not_a_taxonomy\n'
            'keep_unresolved: []\n'
        )
        tax_mod = _reload_taxonomy()
        if '잘못된매핑' in tax_mod.PHRASE_ALIAS:
            _fail('case2.non_taxonomy_dropped',
                  'non-taxonomy entry leaked into PHRASE_ALIAS')
        if '또다른매핑' in tax_mod.PHRASE_ALIAS:
            _fail('case2.non_taxonomy_dropped_2',
                  'second non-taxonomy entry leaked')
        # --apply should REJECT both
        from market_research.tools.alias_review import cmd_apply
        rc = cmd_apply(strict=True)
        if rc != 1:
            _fail('case2.strict_exit',
                  f'cmd_apply --strict should exit 1 on reject, got {rc}')
        _pass('case2: non-taxonomy value → loader drop + apply reject')
    finally:
        if backup is not None:
            APPROVED_FILE.write_bytes(backup)
        else:
            APPROVED_FILE.unlink(missing_ok=True)
        _reload_taxonomy()


def test_case_3_valid_alias_merged():
    backup = APPROVED_FILE.read_bytes() if APPROVED_FILE.exists() else None
    try:
        _write_approved(
            'approved:\n'
            '  "가상의 정책 프레이즈": 통화정책\n'
            'keep_unresolved: []\n'
        )
        tax_mod = _reload_taxonomy()
        if tax_mod.PHRASE_ALIAS.get('가상의 정책 프레이즈') != '통화정책':
            _fail('case3.merged',
                  f'expected alias merged, got {tax_mod.PHRASE_ALIAS.get("가상의 정책 프레이즈")}')
        tags, unresolved = tax_mod.extract_taxonomy_tags('가상의 정책 프레이즈')
        if '통화정책' not in tags:
            _fail('case3.extract_resolves',
                  f'extract_taxonomy_tags failed: tags={tags}, unresolved={unresolved}')
        _pass('case3: 승인된 alias → 런타임 머지 + extract 매핑')
    finally:
        if backup is not None:
            APPROVED_FILE.write_bytes(backup)
        else:
            APPROVED_FILE.unlink(missing_ok=True)
        _reload_taxonomy()


def test_case_4_keep_unresolved_stays_unresolved():
    """keep_unresolved entries MUST NOT force-map to any taxonomy tag."""
    backup = APPROVED_FILE.read_bytes() if APPROVED_FILE.exists() else None
    try:
        _write_approved(
            'approved: {}\n'
            'keep_unresolved:\n'
            '  - "단기 랠리와 장기 리스크의 불일치"\n'
        )
        tax_mod = _reload_taxonomy()
        tags, unresolved = tax_mod.extract_taxonomy_tags(
            '단기 랠리와 장기 리스크의 불일치')
        if tags:
            _fail('case4.no_force_map',
                  f'keep_unresolved phrase was mapped: {tags}')
        if '단기 랠리와 장기 리스크의 불일치' not in unresolved:
            _fail('case4.unresolved_recorded',
                  f'phrase missing from unresolved: {unresolved}')
        _pass('case4: keep_unresolved → force 매핑 없음')
    finally:
        if backup is not None:
            APPROVED_FILE.write_bytes(backup)
        else:
            APPROVED_FILE.unlink(missing_ok=True)
        _reload_taxonomy()


def test_case_5_propose_output_matches_trace():
    """--propose output's unresolved set ≡ trace file's unresolved set."""
    from market_research.tools.alias_review import cmd_propose, TRACE_FILE

    if not TRACE_FILE.exists():
        _pass('case5: skipped (no trace file)')
        return

    rc = cmd_propose()
    if rc != 0:
        _fail('case5.exit', f'cmd_propose returned {rc}')
    if not OUT_JSON.exists():
        _fail('case5.output_exists', f'{OUT_JSON} not written')

    payload = json.loads(OUT_JSON.read_text(encoding='utf-8'))
    report_unresolved = {e['phrase'] for e in payload['unresolved_phrases']}

    trace_unresolved: set[str] = set()
    with open(TRACE_FILE, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get('match_type') == 'unresolved':
                ph = (row.get('original_phrase') or '').strip()
                if ph:
                    trace_unresolved.add(ph)

    if report_unresolved != trace_unresolved:
        missing = trace_unresolved - report_unresolved
        extra = report_unresolved - trace_unresolved
        _fail('case5.set_equal',
              f'missing={missing}, extra={extra}')

    _pass(f'case5: propose unresolved set matches trace '
          f'({len(report_unresolved)} phrases)')


def test_case_6_builtin_snapshot_vs_overlay():
    """--apply uses BUILTIN_PHRASE_ALIAS snapshot, not runtime-merged dict.

    Without this, an approved overlay would be mis-classified as 'builtin
    duplicate' on the second run (self-fulfilling duplicate). The snapshot
    separates "hand-curated" from "yaml-overlay".
    """
    backup = APPROVED_FILE.read_bytes() if APPROVED_FILE.exists() else None
    try:
        _write_approved(
            'approved:\n'
            '  "v14_case6_new_phrase": 통화정책\n'
            'keep_unresolved: []\n'
        )
        tax_mod = _reload_taxonomy()
        # Builtin snapshot must not contain the new phrase
        if 'v14_case6_new_phrase' in tax_mod.BUILTIN_PHRASE_ALIAS:
            _fail('case6.builtin_snapshot_clean',
                  'yaml entry leaked into BUILTIN_PHRASE_ALIAS snapshot')
        # But runtime PHRASE_ALIAS must contain it after overlay
        if tax_mod.PHRASE_ALIAS.get('v14_case6_new_phrase') != '통화정책':
            _fail('case6.runtime_overlay',
                  f'overlay missing at runtime: '
                  f'{tax_mod.PHRASE_ALIAS.get("v14_case6_new_phrase")}')
        # --apply should count this as accepted (not duplicate)
        from market_research.tools.alias_review import cmd_apply
        rc = cmd_apply(strict=True)
        if rc != 0:
            _fail('case6.apply_exit',
                  f'cmd_apply returned {rc} for valid overlay entry')
        _pass('case6: BUILTIN snapshot keeps apply classification correct '
              '(accepted, not mis-labelled duplicate)')
    finally:
        if backup is not None:
            APPROVED_FILE.write_bytes(backup)
        else:
            APPROVED_FILE.unlink(missing_ok=True)
        _reload_taxonomy()


def main():
    print('\n=== alias_review tests ===')
    cases = [
        test_case_1_missing_yaml_unchanged,
        test_case_2_non_taxonomy_rejected,
        test_case_3_valid_alias_merged,
        test_case_4_keep_unresolved_stays_unresolved,
        test_case_5_propose_output_matches_trace,
        test_case_6_builtin_snapshot_vs_overlay,
    ]
    results = []
    for fn in cases:
        try:
            fn()
            results.append((fn.__name__, 'PASS'))
        except AssertionError as exc:
            results.append((fn.__name__, f'FAIL: {exc}'))
        except Exception:
            traceback.print_exc()
            results.append((fn.__name__, 'ERROR'))

    print('\n=== Summary ===')
    for name, status in results:
        print(f'  {status:8s} {name}')
    failed = [n for n, s in results if not s.startswith('PASS')]
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
