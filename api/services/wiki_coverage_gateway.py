"""R3-c: Wiki coverage report read-only gateway.

`tools/wiki_retrieval_coverage.py --json-out` 로 생성된 JSON 파일을 안전하게
list / load. path traversal 방어. read-only — 파일 생성/수정 X.

운영 가정:
  - JSON 파일 위치: PROJECT_ROOT/debug/wiki_retrieval_coverage_*.json
  - 파일명 패턴: wiki_retrieval_coverage_{YYYYMMDD or 자유 stem}.json
  - report_id = stem (확장자 제외, 예: 'wiki_retrieval_coverage_20260506')
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

# ──────────────────────────────────────────────────────────────────
# 경로 / 보안
# ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COVERAGE_DIR = PROJECT_ROOT / "debug"
FILENAME_PATTERN = "wiki_retrieval_coverage_*.json"
REPORT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _validate_report_id(report_id: str) -> str:
    """report_id 검증 — alphanumeric + underscore + hyphen 만 허용.
    path traversal (.. / 절대경로 / 슬래시) 차단."""
    if not report_id:
        raise ValueError("report_id is empty")
    if not REPORT_ID_RE.fullmatch(report_id):
        raise ValueError(
            f"invalid report_id {report_id!r}: only [A-Za-z0-9_-]+ allowed"
        )
    return report_id


def _resolve_report_path(report_id: str) -> Path:
    """report_id → 안전한 파일 경로. 디렉토리 escape 방어."""
    rid = _validate_report_id(report_id)
    candidate = (COVERAGE_DIR / f"{rid}.json").resolve()
    # 부모가 COVERAGE_DIR 인지 다시 확인 (symlink / .. 우회 방어)
    try:
        candidate.relative_to(COVERAGE_DIR.resolve())
    except ValueError:
        raise ValueError(
            f"report path escapes COVERAGE_DIR: {candidate}"
        )
    return candidate


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def list_reports() -> list[dict]:
    """coverage report 목록 — 신규 mtime 순 desc.

    Returns: list of {id, generated_at, periods, gate_summary, mtime, size}
    """
    if not COVERAGE_DIR.exists():
        return []
    items: list[dict] = []
    for fp in COVERAGE_DIR.glob(FILENAME_PATTERN):
        if not fp.is_file():
            continue
        rid = fp.stem
        # report_id validation — 패턴 매칭 안 되면 skip (보안 + 노이즈)
        if not REPORT_ID_RE.fullmatch(rid):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        items.append({
            "id": rid,
            "generated_at": data.get("generated_at"),
            "periods": data.get("periods", []),
            "funds": data.get("funds", []),
            "gate_summary": data.get("gate_summary", {}),
            "mtime": fp.stat().st_mtime,
            "size_bytes": fp.stat().st_size,
        })
    # mtime desc
    items.sort(key=lambda x: -x["mtime"])
    return items


def load_latest_report() -> dict | None:
    """가장 최근 coverage report (full payload). 없으면 None."""
    items = list_reports()
    if not items:
        return None
    rid = items[0]["id"]
    return load_report(rid)


def load_report(report_id: str) -> dict | None:
    """report_id 로 full payload load. 없으면 None.

    Raises ValueError on invalid report_id (path traversal 시도 등).
    """
    fp = _resolve_report_path(report_id)
    if not fp.exists() or not fp.is_file():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None
