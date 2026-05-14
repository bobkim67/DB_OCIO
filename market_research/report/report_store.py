# -*- coding: utf-8 -*-
"""Report Store — draft/final JSON 저장·로딩·상태 관리.

IO Contract (docs/io_contract.md) 기준 경로:
  report_output/{period}/{fund_code}.input.json   ← 외부 배치
  report_output/{period}/{fund_code}.draft.json   ← admin debate
  report_output/{period}/{fund_code}.final.json   ← admin 승인

R9-B.3.1 — optional target_suffix isolation:
  target_suffix="r9b3-smoke" 일 때
    report_output/{period}/{fund_code}.r9b3-smoke.input.json
    report_output/{period}/{fund_code}.r9b3-smoke.draft.json
    report_output/{period}/{fund_code}.r9b3-smoke.final.json
  default (target_suffix=None) 경로/동작은 100% 불변. 운영 final/draft/input
  과 같은 디렉토리에 다른 파일명으로 공존. catalog list 기본 동작은
  suffix 파일을 제외한다 (list_funds_in_period 등). evidence ledger 도
  suffix 별 `_evidence_quality.{suffix}.jsonl` 로 분리.

debate_published/{period}.json (기존) → 하위호환 읽기 지원.
"""
from __future__ import annotations

import json
import re
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


# ── R9-B.3.1 target_suffix sanitizer ──
# 허용: 영문 대소문자 / 숫자 / 하이픈 / 언더스코어
# 금지: dot, slash, backslash, dot-dot 경로 traversal, 공백, 빈 문자열
# 시작: alphanumeric 강제 (`-suffix` 같이 hyphen 으로 시작하는 케이스 방어)
# 길이: 1 ~ 40
_VALID_SUFFIX_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$')


def sanitize_target_suffix(suffix: str | None) -> str | None:
    """target_suffix 검증·반환. None 은 통과 (legacy 경로).

    invalid 시 ValueError. path traversal / 점 / 분리자 모두 차단.
    """
    if suffix is None:
        return None
    if not isinstance(suffix, str):
        raise ValueError(
            f'target_suffix must be str|None, got {type(suffix).__name__}'
        )
    s = suffix.strip()
    if not s:
        raise ValueError('target_suffix must not be empty')
    if not _VALID_SUFFIX_RE.match(s):
        raise ValueError(
            f'invalid target_suffix {suffix!r}: must match '
            f'[A-Za-z0-9_-], start with alphanumeric, length 1-40. '
            f'(dot, slash, backslash, dot-dot, leading hyphen forbidden)'
        )
    return s


def _period_dir(period: str) -> Path:
    d = OUTPUT_DIR / period
    d.mkdir(parents=True, exist_ok=True)
    return d


def _artifact_path(period: str, fund_code: str, kind: str,
                   target_suffix: str | None = None) -> Path:
    """{period}/{fund_code}[.{suffix}].{kind}.json 경로. suffix 는 sanitize 통과 가정.

    R9-B.3.1 — caller 가 sanitize_target_suffix 결과를 그대로 전달해야 한다.
    """
    if target_suffix:
        name = f'{fund_code}.{target_suffix}.{kind}.json'
    else:
        name = f'{fund_code}.{kind}.json'
    return _period_dir(period) / name


def _evidence_tracker_path(target_suffix: str | None = None) -> Path:
    """suffix 별 evidence ledger. None 이면 운영 `_evidence_quality.jsonl`.

    R9-B.3.1: smoke run 의 evidence 통계가 운영 ledger 를 오염하지 않도록 분리.
    """
    if target_suffix:
        return OUTPUT_DIR / f'_evidence_quality.{target_suffix}.jsonl'
    return EVIDENCE_TRACKER


def _is_legacy_artifact_name(name: str, kind: str) -> bool:
    """legacy `{fund}.{kind}.json` 패턴 (정확히 dot 2개) 매칭.

    suffix 변형 `{fund}.{suffix}.{kind}.json` (dot 3개) 와 분리. catalog list
    helpers 가 기본 (suffix 미지정) 스캔 시 suffix 산출물을 제외하기 위한 가드.
    """
    tail = f'.{kind}.json'
    if not name.endswith(tail):
        return False
    stem = name[: -len(tail)]
    return '.' not in stem  # legacy fund_code 에는 dot 가 없다


def _matches_suffix_artifact(name: str, kind: str, target_suffix: str) -> bool:
    """suffix 명시 시 매칭. `{fund}.{suffix}.{kind}.json` 정확 일치."""
    needle = f'.{target_suffix}.{kind}.json'
    if not name.endswith(needle):
        return False
    stem = name[: -len(needle)]
    return bool(stem) and '.' not in stem


# ══════════════════════════════════════════
# Input package
# ══════════════════════════════════════════

def save_input_package(period: str, fund_code: str, data: dict,
                       *, target_suffix: str | None = None):
    suffix = sanitize_target_suffix(target_suffix)
    path = _artifact_path(period, fund_code, 'input', suffix)
    data.setdefault('fund_code', fund_code)
    data.setdefault('period', period)
    data.setdefault('prepared_at', time.strftime('%Y-%m-%dT%H:%M:%S'))
    if suffix:
        data['target_suffix'] = suffix
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def load_input_package(period: str, fund_code: str,
                       *, target_suffix: str | None = None) -> dict | None:
    suffix = sanitize_target_suffix(target_suffix)
    path = _artifact_path(period, fund_code, 'input', suffix)
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return None


# ══════════════════════════════════════════
# Draft
# ══════════════════════════════════════════

def save_draft(period: str, fund_code: str, data: dict,
               *, target_suffix: str | None = None) -> Path:
    suffix = sanitize_target_suffix(target_suffix)
    path = _artifact_path(period, fund_code, 'draft', suffix)
    data['fund_code'] = fund_code
    data['period'] = period
    data['status'] = data.get('status', STATUS_DRAFT)
    if suffix:
        data['target_suffix'] = suffix
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def load_draft(period: str, fund_code: str,
               *, target_suffix: str | None = None) -> dict | None:
    suffix = sanitize_target_suffix(target_suffix)
    path = _artifact_path(period, fund_code, 'draft', suffix)
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    # legacy fallback 제거 — report_output에 파일이 없으면 None 반환
    return None


def update_draft_comment(period: str, fund_code: str,
                         edited_comment: str, edited_by: str = 'admin',
                         *, target_suffix: str | None = None) -> dict | None:
    suffix = sanitize_target_suffix(target_suffix)
    draft = load_draft(period, fund_code, target_suffix=suffix)
    if not draft:
        return None
    draft['draft_comment'] = edited_comment
    draft['status'] = STATUS_EDITED
    draft.setdefault('edit_history', [])
    draft['edit_history'].append({
        'edited_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'edited_by': edited_by,
    })
    save_draft(period, fund_code, draft, target_suffix=suffix)
    return draft


# ══════════════════════════════════════════
# Final (approved)
# ══════════════════════════════════════════

def approve_and_save_final(period: str, fund_code: str,
                           approved_by: str = 'admin',
                           *, target_suffix: str | None = None) -> Path | None:
    suffix = sanitize_target_suffix(target_suffix)
    draft = load_draft(period, fund_code, target_suffix=suffix)
    if not draft:
        return None

    # P1-① lineage: 승인 대상 draft 의 debate_run_id 를 final 에 복사.
    # (디스크의 다른 draft 가 아닌, 방금 load_draft 로 읽은 payload 의 ID).
    # legacy draft (ID 부재) 는 None 으로 복사 — final 에도 None 기록.
    approved_debate_run_id = draft.get('debate_run_id')

    final = {
        'fund_code': fund_code,
        'period': period,
        'status': STATUS_APPROVED,
        'final_comment': draft.get('draft_comment', draft.get('customer_comment', '')),
        'approved': True,
        'approved_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'approved_by': approved_by,
        'approved_debate_run_id': approved_debate_run_id,
        'generated_at': draft.get('generated_at', ''),
        'model': draft.get('model', ''),
        'cost_usd': draft.get('cost_usd', 0),
        'consensus_points': draft.get('consensus_points', []),
        'tail_risks': draft.get('tail_risks', []),
        # R9-A.3.x (D-X-A) — canonical claims compact persistence (8 fields).
        # fund_comment_service 가 final 우선 로드 → market_payload['claims']
        # 가 비어있으면 fund prompt 의 Canonical Claims block 도 부재. 본
        # 보존이 wiring chain 최종 단계. evidence_annotations 는 이번
        # 트랙 범위 외 (별 트랙).
        'claims': draft.get('claims', []),
    }
    if suffix:
        # R9-B.3.1 — suffix 산출물은 운영 approved 가 아님을 명시. 다운스트림
        # client viewer 등이 approved=True 만 보고 운영 final 로 오인하지
        # 않도록 target_suffix 필드를 surface.
        final['target_suffix'] = suffix

    path = _artifact_path(period, fund_code, 'final', suffix)
    path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding='utf-8')

    # draft 상태도 approved로 갱신
    draft['status'] = STATUS_APPROVED
    save_draft(period, fund_code, draft, target_suffix=suffix)

    return path


def load_final(period: str, fund_code: str,
               *, target_suffix: str | None = None) -> dict | None:
    suffix = sanitize_target_suffix(target_suffix)
    path = _artifact_path(period, fund_code, 'final', suffix)
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


def get_latest_period_for_fund(fund_code: str,
                               *, target_suffix: str | None = None) -> str | None:
    """특정 펀드의 가장 최근 draft/final이 있는 기간 반환.

    target_suffix=None (default) → 운영 산출물만 검사. suffix 명시 시 해당
    suffix variant 중에서 검색.
    """
    suffix = sanitize_target_suffix(target_suffix)
    periods = list_periods()
    for p in periods:  # 이미 역순 정렬
        d = OUTPUT_DIR / p
        if not d.exists():
            continue
        draft = _artifact_path(p, fund_code, 'draft', suffix)
        final = _artifact_path(p, fund_code, 'final', suffix)
        if draft.exists() or final.exists():
            return p
    return None


def get_latest_market_period(*, target_suffix: str | None = None) -> str | None:
    """시장 debate(_market)의 가장 최근 기간 반환."""
    return get_latest_period_for_fund('_market', target_suffix=target_suffix)


def list_funds_in_period(period: str,
                         *, target_suffix: str | None = None) -> list[str]:
    """특정 기간의 펀드 목록 (draft 또는 final 존재).

    target_suffix=None → legacy `{fund}.{kind}.json` (dot 2개) 만. suffix
    산출물 (`{fund}.{suffix}.{kind}.json`, dot 3개) 은 자동 제외 → 운영
    catalog 격리.
    """
    suffix = sanitize_target_suffix(target_suffix)
    funds = set()
    d = OUTPUT_DIR / period
    if not d.exists():
        return []
    for f in d.glob('*.json'):
        name = f.name
        for kind in ('draft', 'final'):
            if suffix:
                if _matches_suffix_artifact(name, kind, suffix):
                    tail = f'.{suffix}.{kind}.json'
                    funds.add(name[: -len(tail)])
            else:
                if _is_legacy_artifact_name(name, kind):
                    tail = f'.{kind}.json'
                    funds.add(name[: -len(tail)])
    return sorted(funds)


def get_status(period: str, fund_code: str,
               *, target_suffix: str | None = None) -> str:
    suffix = sanitize_target_suffix(target_suffix)
    final = load_final(period, fund_code, target_suffix=suffix)
    if final and final.get('approved'):
        return STATUS_APPROVED
    draft = load_draft(period, fund_code, target_suffix=suffix)
    if draft:
        return draft.get('status', STATUS_DRAFT)
    return STATUS_NOT_GENERATED


def list_approved_periods(*, target_suffix: str | None = None) -> list[str]:
    """final.json이 존재하는 기간 목록 (client용).

    R9-B.3.1 — target_suffix=None 이면 legacy `{fund}.final.json` 만. suffix
    산출물은 자동 제외 (client 뷰가 smoke 결과를 운영 approved 로 보지
    않도록).
    """
    suffix = sanitize_target_suffix(target_suffix)
    periods = set()
    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir():
                for f in d.glob('*.final.json'):
                    if suffix:
                        if _matches_suffix_artifact(f.name, 'final', suffix):
                            periods.add(d.name)
                            break
                    else:
                        if _is_legacy_artifact_name(f.name, 'final'):
                            periods.add(d.name)
                            break
    return sorted(periods, reverse=True)


def list_approved_funds(period: str,
                        *, target_suffix: str | None = None) -> list[str]:
    suffix = sanitize_target_suffix(target_suffix)
    d = OUTPUT_DIR / period
    if not d.exists():
        return []
    out = []
    for f in d.glob('*.final.json'):
        name = f.name
        if suffix:
            if _matches_suffix_artifact(name, 'final', suffix):
                tail = f'.{suffix}.final.json'
                out.append(name[: -len(tail)])
        else:
            if _is_legacy_artifact_name(name, 'final'):
                tail = '.final.json'
                out.append(name[: -len(tail)])
    return sorted(out)


# ══════════════════════════════════════════
# Evidence quality 누적 추적
# ══════════════════════════════════════════

def append_evidence_quality(record: dict, *, target_suffix: str | None = None):
    """suffix 명시 시 `_evidence_quality.{suffix}.jsonl` 로 분리 저장.

    운영 ledger (`_evidence_quality.jsonl`) 가 R9-B.4 smoke run 의 통계로
    오염되지 않도록.
    """
    suffix = sanitize_target_suffix(target_suffix)
    path = _evidence_tracker_path(suffix)
    if suffix:
        record = dict(record)  # 원본 mutate 금지
        record.setdefault('target_suffix', suffix)
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception:
        pass


def load_evidence_quality_records(*, target_suffix: str | None = None) -> list[dict]:
    """suffix 별 ledger 만 로드. None 은 운영 ledger."""
    suffix = sanitize_target_suffix(target_suffix)
    path = _evidence_tracker_path(suffix)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding='utf-8').strip().split('\n'):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records
