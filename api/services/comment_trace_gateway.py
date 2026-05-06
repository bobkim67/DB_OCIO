r"""R4 backend gateway — comment trace JSON read-only loader.

`tools/comment_trace.py` 가 생성한 JSON 을 안전하게 list / load.
path traversal 방어. read-only.

운영 가정:
  - JSON 위치: PROJECT_ROOT/debug/comment_trace/{period}/{fund}.json
  - period regex: ^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$
  - fund regex:   ^[A-Za-z0-9_]+$
  - trace_id     = "{fund}@{period}"  (URL safe ASCII)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TRACE_DIR = PROJECT_ROOT / "debug" / "comment_trace"

PERIOD_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$")
FUND_RE = re.compile(r"^[A-Za-z0-9_]+$")
TRACE_ID_RE = re.compile(r"^([A-Za-z0-9_]+)@(\d{4}-(?:0[1-9]|1[0-2]|Q[1-4]))$")


def _validate_period(period: str) -> str:
    if not period or not PERIOD_RE.fullmatch(period):
        raise ValueError(f"invalid period {period!r}")
    return period


def _validate_fund(fund: str) -> str:
    if not fund or not FUND_RE.fullmatch(fund) or len(fund) > 32:
        raise ValueError(f"invalid fund {fund!r}")
    return fund


def _resolve_trace_path(period: str, fund: str) -> Path:
    p = _validate_period(period)
    f = _validate_fund(fund)
    candidate = (TRACE_DIR / p / f"{f}.json").resolve()
    try:
        candidate.relative_to(TRACE_DIR.resolve())
    except ValueError:
        raise ValueError(f"trace path escapes TRACE_DIR: {candidate}")
    return candidate


def parse_trace_id(trace_id: str) -> tuple[str, str]:
    """trace_id 'FUND@PERIOD' → (fund, period). 검증 포함."""
    m = TRACE_ID_RE.fullmatch(trace_id or "")
    if not m:
        raise ValueError(f"invalid trace_id {trace_id!r}")
    fund, period = m.group(1), m.group(2)
    _validate_fund(fund)
    _validate_period(period)
    return fund, period


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def list_traces(period: str | None = None,
                  fund: str | None = None) -> list[dict]:
    """trace 목록. period / fund 로 필터."""
    if not TRACE_DIR.exists():
        return []
    items: list[dict] = []
    for fp in TRACE_DIR.rglob("*.json"):
        if not fp.is_file():
            continue
        try:
            relparts = fp.relative_to(TRACE_DIR).parts
            if len(relparts) != 2:
                continue
            p, name = relparts
            if not name.endswith(".json"):
                continue
            f = name[:-5]
            if not PERIOD_RE.fullmatch(p) or not FUND_RE.fullmatch(f):
                continue
        except ValueError:
            continue
        if period and p != period:
            continue
        if fund and f != fund:
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        items.append({
            "trace_id": data.get("trace_id") or f"{f}@{p}",
            "fund_code": f,
            "period": p,
            "generated_at": data.get("generated_at"),
            "schema_version": data.get("schema_version"),
            "graph_node_count": len((data.get("graph_seed") or {}).get("nodes", [])),
            "graph_edge_count": len((data.get("graph_seed") or {}).get("edges", [])),
            "warning_count": len(data.get("warnings") or []),
            "error_count": len(data.get("errors") or []),
            "size_bytes": fp.stat().st_size,
            "mtime": fp.stat().st_mtime,
        })
    items.sort(key=lambda x: -x["mtime"])
    return items


def load_trace(period: str, fund: str) -> dict | None:
    """period + fund 로 trace load."""
    fp = _resolve_trace_path(period, fund)
    if not fp.exists() or not fp.is_file():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_trace_by_id(trace_id: str) -> dict | None:
    """trace_id ('FUND@PERIOD') 로 load."""
    fund, period = parse_trace_id(trace_id)
    return load_trace(period, fund)


def load_latest_trace(period: str | None = None,
                       fund: str | None = None) -> dict | None:
    """가장 최근 trace. period/fund 로 필터링 후 mtime 최대값."""
    items = list_traces(period=period, fund=fund)
    if not items:
        return None
    top = items[0]
    return load_trace(top["period"], top["fund_code"])
