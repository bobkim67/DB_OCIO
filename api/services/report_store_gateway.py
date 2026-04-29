"""Read-only gateway for market_research.report.report_store.

목적:
  - API 서비스가 report_store 모듈에 강결합되지 않도록 얇은 어댑터 제공
  - write/save 계열 함수는 절대 expose하지 않음
  - report_store._period_dir가 mkdir 부작용을 가지므로, 비존재 period 조회 시
    빈 디렉토리가 생기지 않도록 read-only path 조립으로 우회

report_store 경로 규약 (확인 결과):
  BASE = market_research/data/report_output/
  input  : BASE/{period}/{fund}.input.json
  draft  : BASE/{period}/{fund}.draft.json
  final  : BASE/{period}/{fund}.final.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# report_store가 정의한 OUTPUT_DIR을 단일 출처로 사용 (lazy)
def _output_dir() -> Path:
    from market_research.report import report_store
    return report_store.OUTPUT_DIR


def _status_constants() -> tuple[str, str, str, str]:
    from market_research.report import report_store
    return (
        report_store.STATUS_NOT_GENERATED,
        report_store.STATUS_DRAFT,
        report_store.STATUS_EDITED,
        report_store.STATUS_APPROVED,
    )


_PERIOD_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$")


def is_valid_period(period: str) -> bool:
    return bool(_PERIOD_RE.match(period or ""))


def _safe_period_dir(period: str) -> Path | None:
    """report_output/{period} 디렉토리. 존재하지 않으면 None.

    report_store._period_dir와 달리 mkdir 부작용 없음.
    """
    if not is_valid_period(period):
        return None
    base = _output_dir()
    target = base / period
    # path traversal 방어: resolve 후 base 하위인지 검증
    try:
        resolved_base = base.resolve()
        resolved_target = target.resolve()
    except OSError:
        return None
    if resolved_base not in resolved_target.parents and resolved_target != resolved_base:
        return None
    if not target.is_dir():
        return None
    return target


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_input(period: str, fund_code: str) -> dict | None:
    d = _safe_period_dir(period)
    if d is None:
        return None
    return _read_json(d / f"{fund_code}.input.json")


def load_draft(period: str, fund_code: str) -> dict | None:
    d = _safe_period_dir(period)
    if d is None:
        return None
    return _read_json(d / f"{fund_code}.draft.json")


def load_final(period: str, fund_code: str) -> dict | None:
    d = _safe_period_dir(period)
    if d is None:
        return None
    return _read_json(d / f"{fund_code}.final.json")


def get_status(period: str, fund_code: str) -> str:
    """report_store.get_status 와 동일 규칙. 단 mkdir 부작용 없음."""
    not_gen, draft_st, _edited_st, approved_st = _status_constants()
    final = load_final(period, fund_code)
    if final and final.get("approved"):
        return approved_st
    draft = load_draft(period, fund_code)
    if draft:
        return draft.get("status", draft_st)
    return not_gen


def list_period_dirs() -> list[str]:
    """report_output 하위 디렉토리 중 형식이 맞는 것만 반환 (정렬: 내림차순)."""
    base = _output_dir()
    if not base.exists():
        return []
    out: list[str] = []
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith("_") or name.startswith("."):
            continue
        if not is_valid_period(name):
            continue
        out.append(name)
    return sorted(out, reverse=True)
