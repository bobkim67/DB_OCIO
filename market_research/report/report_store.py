# -*- coding: utf-8 -*-
"""Report Store — draft/final JSON 저장·로딩·상태 관리.

IO Contract (docs/io_contract.md) 기준 경로:
  report_output/{period}/{fund_code}.input.json   ← 외부 배치
  report_output/{period}/{fund_code}.draft.json   ← admin debate
  report_output/{period}/{fund_code}.final.json   ← admin 승인

debate_published/{period}.json (기존) → 하위호환 읽기 지원.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
OUTPUT_DIR = BASE_DIR / 'data' / 'report_output'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 기존 debate_published (하위호환)
LEGACY_DIR = BASE_DIR / 'data' / 'debate_published'

EVIDENCE_TRACKER = OUTPUT_DIR / '_evidence_quality.jsonl'

# ── 상태 ──
STATUS_NOT_GENERATED = 'not_generated'
STATUS_DRAFT = 'draft_generated'
STATUS_EDITED = 'edited'
STATUS_APPROVED = 'approved'


def _period_dir(period: str) -> Path:
    d = OUTPUT_DIR / period
    d.mkdir(parents=True, exist_ok=True)
    return d


# ══════════════════════════════════════════
# Input package
# ══════════════════════════════════════════

def save_input_package(period: str, fund_code: str, data: dict):
    path = _period_dir(period) / f'{fund_code}.input.json'
    data.setdefault('fund_code', fund_code)
    data.setdefault('period', period)
    data.setdefault('prepared_at', time.strftime('%Y-%m-%dT%H:%M:%S'))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def load_input_package(period: str, fund_code: str) -> dict | None:
    path = _period_dir(period) / f'{fund_code}.input.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return None


# ══════════════════════════════════════════
# Draft
# ══════════════════════════════════════════

def save_draft(period: str, fund_code: str, data: dict) -> Path:
    path = _period_dir(period) / f'{fund_code}.draft.json'
    data['fund_code'] = fund_code
    data['period'] = period
    data['status'] = data.get('status', STATUS_DRAFT)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def load_draft(period: str, fund_code: str) -> dict | None:
    path = _period_dir(period) / f'{fund_code}.draft.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    # legacy fallback 제거 — report_output에 파일이 없으면 None 반환
    return None


def update_draft_comment(period: str, fund_code: str,
                         edited_comment: str, edited_by: str = 'admin') -> dict | None:
    draft = load_draft(period, fund_code)
    if not draft:
        return None
    draft['draft_comment'] = edited_comment
    draft['status'] = STATUS_EDITED
    draft.setdefault('edit_history', [])
    draft['edit_history'].append({
        'edited_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'edited_by': edited_by,
    })
    save_draft(period, fund_code, draft)
    return draft


# ══════════════════════════════════════════
# Final (approved)
# ══════════════════════════════════════════

def approve_and_save_final(period: str, fund_code: str,
                           approved_by: str = 'admin') -> Path | None:
    draft = load_draft(period, fund_code)
    if not draft:
        return None

    final = {
        'fund_code': fund_code,
        'period': period,
        'status': STATUS_APPROVED,
        'final_comment': draft.get('draft_comment', draft.get('customer_comment', '')),
        'approved': True,
        'approved_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'approved_by': approved_by,
        'generated_at': draft.get('generated_at', ''),
        'model': draft.get('model', ''),
        'cost_usd': draft.get('cost_usd', 0),
        'consensus_points': draft.get('consensus_points', []),
        'tail_risks': draft.get('tail_risks', []),
    }

    path = _period_dir(period) / f'{fund_code}.final.json'
    path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding='utf-8')

    # draft 상태도 approved로 갱신
    draft['status'] = STATUS_APPROVED
    save_draft(period, fund_code, draft)

    return path


def load_final(period: str, fund_code: str) -> dict | None:
    path = _period_dir(period) / f'{fund_code}.final.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return None


# ══════════════════════════════════════════
# 목록 조회
# ══════════════════════════════════════════

def list_periods() -> list[str]:
    """report_output 하위 디렉토리 중 JSON 파일이 있는 기간만 반환."""
    periods = set()
    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and d.name != '__pycache__':
                if any(d.glob('*.json')):
                    periods.add(d.name)
    return sorted(periods, reverse=True)


def get_latest_period_for_fund(fund_code: str) -> str | None:
    """특정 펀드의 가장 최근 draft/final이 있는 기간 반환."""
    periods = list_periods()
    for p in periods:  # 이미 역순 정렬
        d = OUTPUT_DIR / p
        if d.exists():
            if (d / f'{fund_code}.draft.json').exists() or (d / f'{fund_code}.final.json').exists():
                return p
    return None


def get_latest_market_period() -> str | None:
    """시장 debate(_market)의 가장 최근 기간 반환."""
    return get_latest_period_for_fund('_market')


def list_funds_in_period(period: str) -> list[str]:
    """특정 기간의 펀드 목록 (draft 또는 final 존재)."""
    funds = set()
    d = OUTPUT_DIR / period
    if d.exists():
        for f in d.glob('*.draft.json'):
            funds.add(f.name.replace('.draft.json', ''))
        for f in d.glob('*.final.json'):
            funds.add(f.name.replace('.final.json', ''))
    return sorted(funds)


def get_status(period: str, fund_code: str) -> str:
    final = load_final(period, fund_code)
    if final and final.get('approved'):
        return STATUS_APPROVED
    draft = load_draft(period, fund_code)
    if draft:
        return draft.get('status', STATUS_DRAFT)
    return STATUS_NOT_GENERATED


def list_approved_periods() -> list[str]:
    """final.json이 존재하는 기간 목록 (client용)."""
    periods = set()
    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir():
                for f in d.glob('*.final.json'):
                    periods.add(d.name)
                    break
    return sorted(periods, reverse=True)


def list_approved_funds(period: str) -> list[str]:
    d = OUTPUT_DIR / period
    if not d.exists():
        return []
    return sorted(f.name.replace('.final.json', '') for f in d.glob('*.final.json'))


# ══════════════════════════════════════════
# Evidence quality 누적 추적
# ══════════════════════════════════════════

def append_evidence_quality(record: dict):
    try:
        with open(EVIDENCE_TRACKER, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception:
        pass


def load_evidence_quality_records() -> list[dict]:
    if not EVIDENCE_TRACKER.exists():
        return []
    records = []
    for line in EVIDENCE_TRACKER.read_text(encoding='utf-8').strip().split('\n'):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records
