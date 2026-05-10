# -*- coding: utf-8 -*-
"""R9-A.4 Commit 3 (C3-β) — promotion ledger row preview schema.

R9-A.2 의 `_promotion_quality.jsonl` 을 확장한 정식 schema (24 필드).
**gitignored 유지** — Commit 3 단계에서는 실 append 0 (preview row 만 반환).

기존 R9-A.1 row 는 11 필드 (cost_usd / write_* / status 미포함). 본 schema 의
신규 필드는 R9-A.4 row 에만 채움 — `compute_monthly_cost_usd` filter 가
source/extractor_version 기준이라 R9-A.1 row 영향 0.

invariant:
  - file write 0
  - ledger read 는 `_promotion_quality.jsonl` 만 (없으면 graceful → cost 0)
  - import 시점 비용 0 (JSONL 은 호출 시점에 한 번만 읽음)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from market_research.analyze.claim_store import PROMOTION_LEDGER_PATH


# 24 fields — workorder §6.1 schema. dict 순서가 row JSON 출력 순서.
LEDGER_ROW_FIELDS: tuple[str, ...] = (
    "ts",
    "period",
    "source",
    "extractor_version",
    "input_count",
    "valid_claim_count",
    "invalid_claim_count",
    "promoted_count",
    "skipped_count",
    "promotion_rate",
    "rule",
    "rule_breakdown",
    "skip_reasons",
    "cost_usd",
    "monthly_cost_usd_so_far",
    "dry_run",
    "write_canonical",
    "write_wiki",
    "write_ledger",
    "status",
    "abort_reason",
    "warnings",
    "out_of_band_override",
    "target_suffix",
)

# Monthly cap — workorder §5 D-4. Commit 4 에서 CLI override 가능 예정.
MONTHLY_CAP_USD: float = 1.0


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _to_str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


def compute_monthly_cost_usd(
    period: str,
    *,
    source: str = "daily_update_r9a4",
    extractor_version: str = "r9a.4-haiku",
    ledger_path: str | Path | None = None,
) -> float:
    """동일 month + source + extractor_version filter row 들의 cost_usd 합산.

    Parameters
    ----------
    period : "YYYY-MM" 또는 "YYYY-MM-DD" — 앞 7자가 month key 로 사용됨.
    source : 합산 대상 source tag (default 'daily_update_r9a4'). manual_pilot
              계열은 자연 제외 (R9-A.1 row 영향 0).
    extractor_version : default 'r9a.4-haiku'.
    ledger_path : test override. None 이면 PROMOTION_LEDGER_PATH.

    파일 결손 / parse 실패 / period 비정상 모두 graceful → 0.0 반환.
    """
    if not isinstance(period, str) or not period:
        return 0.0
    month_key = period[:7]

    p = Path(ledger_path) if ledger_path else PROMOTION_LEDGER_PATH
    if not p.exists():
        return 0.0

    total = 0.0
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                row_period = str(row.get("period", ""))
                if not row_period.startswith(month_key):
                    continue
                if str(row.get("source", "")) != source:
                    continue
                if str(row.get("extractor_version", "")) != extractor_version:
                    continue
                total += _to_float(row.get("cost_usd"), 0.0)
    except OSError:
        return 0.0
    return round(total, 6)


def build_ledger_row_preview(
    *,
    period: str,
    source: str = "daily_update_r9a4",
    extractor_version: str = "r9a.4-haiku",
    input_count: int = 0,
    valid_claim_count: int = 0,
    invalid_claim_count: int = 0,
    promoted_count: int = 0,
    skipped_count: int = 0,
    promotion_rate: float = 0.0,
    rule: str = "auto",
    rule_breakdown: dict | None = None,
    skip_reasons: dict | None = None,
    cost_usd: float = 0.0,
    monthly_cost_usd_so_far: float = 0.0,
    dry_run: bool = True,
    write_canonical: bool = False,
    write_wiki: bool = False,
    write_ledger: bool = False,
    status: str = "ok_plan_ready",
    abort_reason: str | None = None,
    warnings: list | None = None,
    out_of_band_override: bool = False,
    target_suffix: str | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    """Commit 3 단계의 ledger row preview.

    실 append 0 — 호출 측은 `step_claim_extract` 의 `would_save` 안에서
    이 row 를 metadata 로 reference 만. Commit 4 에서 `append_promotion_ledger`
    가 본 row 를 그대로 받아 write.

    type coercion 은 보수적으로 — int/float/str 타입 안정성 보장 (jsonl
    serialization 회귀 방지).
    """
    if ts is None:
        ts = datetime.now().isoformat(timespec="seconds")

    return {
        "ts": ts,
        "period": str(period or ""),
        "source": str(source or ""),
        "extractor_version": str(extractor_version or ""),
        "input_count": _to_int(input_count),
        "valid_claim_count": _to_int(valid_claim_count),
        "invalid_claim_count": _to_int(invalid_claim_count),
        "promoted_count": _to_int(promoted_count),
        "skipped_count": _to_int(skipped_count),
        "promotion_rate": round(_to_float(promotion_rate), 2),
        "rule": str(rule or "auto"),
        "rule_breakdown": dict(rule_breakdown or {}),
        "skip_reasons": dict(skip_reasons or {}),
        "cost_usd": round(_to_float(cost_usd), 6),
        "monthly_cost_usd_so_far": round(_to_float(monthly_cost_usd_so_far), 6),
        "dry_run": bool(dry_run),
        "write_canonical": bool(write_canonical),
        "write_wiki": bool(write_wiki),
        "write_ledger": bool(write_ledger),
        "status": str(status or ""),
        "abort_reason": _to_str_or_none(abort_reason),
        "warnings": list(warnings or []),
        "out_of_band_override": bool(out_of_band_override),
        "target_suffix": _to_str_or_none(target_suffix),
    }


def validate_ledger_row_preview(row: dict) -> list[str]:
    """필수 필드 누락 / 타입 오류 → 오류 메시지 list 반환 (빈 list = 정상).

    Commit 4 에서 실 append 직전 마지막 검증으로 재사용 가능.
    """
    errors: list[str] = []
    if not isinstance(row, dict):
        return ["row_not_dict"]
    for field in LEDGER_ROW_FIELDS:
        if field not in row:
            errors.append(f"missing_field:{field}")
    # type sanity (대표 필드)
    for f in ("input_count", "valid_claim_count", "invalid_claim_count",
              "promoted_count", "skipped_count"):
        if f in row and not isinstance(row[f], int):
            errors.append(f"type_error:{f}_not_int")
    for f in ("cost_usd", "monthly_cost_usd_so_far", "promotion_rate"):
        if f in row and not isinstance(row[f], (int, float)):
            errors.append(f"type_error:{f}_not_number")
    for f in ("dry_run", "write_canonical", "write_wiki", "write_ledger",
              "out_of_band_override"):
        if f in row and not isinstance(row[f], bool):
            errors.append(f"type_error:{f}_not_bool")
    return errors
