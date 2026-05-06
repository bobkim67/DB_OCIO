"""Regression: R3 wiki_retrieval_coverage JSON output + gate exit code +
gateway path traversal 방어.

LLM 호출 0. mock data 또는 가벼운 실 호출만.
"""
from __future__ import annotations

import json
import sys
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VENV_PY = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PY.exists():
    VENV_PY = Path("python")  # fallback


def _run_tool(args: list[str]) -> tuple[int, str, str]:
    """tools/wiki_retrieval_coverage.py 실행. (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [str(VENV_PY), str(PROJECT_ROOT / "tools" / "wiki_retrieval_coverage.py"),
         *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


# ──────────────────────────────────────────────────────────────────
# JSON schema
# ──────────────────────────────────────────────────────────────────

REQUIRED_TOP_KEYS = {
    "schema_version", "tool_version", "generated_at",
    "periods", "funds", "skip_report_periods", "expected_enriched_periods",
    "fail_on_gate", "inventory_summary", "retrieval_debug",
    "fund_comment_debug", "asset_coverage", "gate_summary", "gate_results",
    "warnings", "errors",
}

REQUIRED_GATE_SUMMARY_KEYS = {
    "total", "pass", "fail", "warning",
    "exit_code_expected", "fail_on_gate",
}

REQUIRED_GATE_RESULT_KEYS = {
    "gate_id", "severity", "status", "period", "fund_code",
    "message", "details",
}


def test_json_output_schema(tmp_path):
    json_path = tmp_path / "test.json"
    md_path = tmp_path / "test.md"
    rc, out, err = _run_tool([
        "--period", "2026-04", "--period", "2026-05",
        "--fund", "07G04", "--fund", "08K88",
        "--fail-on-gate",
        "--skip-report-period", "2026-05",
        "--expected-enriched-period", "2026-04",
        "--expected-enriched-period", "2026-05",
        "--output", str(md_path),
        "--json-out", str(json_path),
    ])
    assert rc == 0, f"rc={rc} stderr={err[-300:]}"
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))

    # top-level keys
    missing = REQUIRED_TOP_KEYS - set(data.keys())
    assert not missing, f"missing top keys: {missing}"

    # gate_summary
    gs = data["gate_summary"]
    missing_gs = REQUIRED_GATE_SUMMARY_KEYS - set(gs.keys())
    assert not missing_gs, f"missing gate_summary keys: {missing_gs}"

    # gate_results 각 항목 schema
    assert isinstance(data["gate_results"], list)
    assert len(data["gate_results"]) >= 1
    for r in data["gate_results"]:
        missing_r = REQUIRED_GATE_RESULT_KEYS - set(r.keys())
        assert not missing_r, f"gate_result missing: {missing_r}"
        assert r["status"] in ("PASS", "FAIL", "WARNING", "WARNING_SKIP")

    # schema_version 존재
    assert data["schema_version"]


def test_md_json_gate_count_consistency(tmp_path):
    """markdown 의 'FAIL: N / WARNING: M' 와 JSON gate_summary 가 일치."""
    json_path = tmp_path / "c.json"
    md_path = tmp_path / "c.md"
    rc, _, _ = _run_tool([
        "--period", "2026-04", "--period", "2026-05",
        "--fund", "07G04", "--fund", "08K88",
        "--fail-on-gate",
        "--skip-report-period", "2026-05",
        "--expected-enriched-period", "2026-04",
        "--expected-enriched-period", "2026-05",
        "--output", str(md_path),
        "--json-out", str(json_path),
    ])
    assert rc == 0
    data = json.loads(json_path.read_text(encoding="utf-8"))
    md = md_path.read_text(encoding="utf-8")
    gs = data["gate_summary"]

    # markdown 에 'FAIL: N' / 'WARNING: M' 패턴
    import re
    m = re.search(r"\*\*FAIL:\s*(\d+)\s*/\s*WARNING:\s*(\d+)\*\*", md)
    assert m, f"FAIL/WARNING line not found in markdown"
    md_fail = int(m.group(1))
    md_warn = int(m.group(2))
    assert md_fail == gs["fail"], f"md fail={md_fail} vs json={gs['fail']}"
    assert md_warn == gs["warning"], f"md warn={md_warn} vs json={gs['warning']}"


def test_warning_only_exit_zero(tmp_path):
    """현재 운영 (FAIL 0 + WARNING 가능) → exit 0."""
    json_path = tmp_path / "w.json"
    md_path = tmp_path / "w.md"
    rc, _, _ = _run_tool([
        "--period", "2026-04", "--period", "2026-05",
        "--fund", "07G04", "--fund", "08K88",
        "--fail-on-gate",
        "--skip-report-period", "2026-05",
        "--output", str(md_path),
        "--json-out", str(json_path),
    ])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if data["gate_summary"]["fail"] == 0:
        assert rc == 0, f"FAIL=0 expected exit 0, got {rc}"


def test_no_fail_on_gate_exit_zero(tmp_path):
    """--fail-on-gate 없으면 무조건 exit 0."""
    json_path = tmp_path / "n.json"
    md_path = tmp_path / "n.md"
    rc, _, _ = _run_tool([
        "--period", "2026-04",
        "--fund", "07G04",
        "--output", str(md_path),
        "--json-out", str(json_path),
    ])
    assert rc == 0


# ──────────────────────────────────────────────────────────────────
# Gateway path traversal 방어
# ──────────────────────────────────────────────────────────────────

def test_gateway_invalid_report_id():
    from api.services import wiki_coverage_gateway as wcg
    # path traversal 시도
    for bad in ("../etc/passwd", "wiki/../../secret", "with space",
                "abs/../path", "..", "/etc/passwd", "C:\\Windows"):
        try:
            wcg.load_report(bad)
            assert False, f"should reject: {bad!r}"
        except ValueError:
            pass  # expected


def test_gateway_valid_report_id_returns_none_for_missing():
    from api.services import wiki_coverage_gateway as wcg
    # 정상 ID 형태지만 파일 없음
    res = wcg.load_report("nonexistent_report_id_xyz_99999")
    assert res is None


def test_gateway_list_reports_returns_list():
    from api.services import wiki_coverage_gateway as wcg
    items = wcg.list_reports()
    assert isinstance(items, list)
    # 위에서 생성한 report (debug/wiki_retrieval_coverage_*.json) 가 적어도 1개
    if items:
        first = items[0]
        for k in ("id", "generated_at", "periods", "gate_summary", "size_bytes"):
            assert k in first, f"missing key {k}"


def test_gateway_load_latest_real():
    """실제 debug/ 의 latest report 로드 (최소 1개 존재 가정)."""
    from api.services import wiki_coverage_gateway as wcg
    payload = wcg.load_latest_report()
    if payload is None:
        return  # report 없음 — skip
    assert "schema_version" in payload
    assert "gate_summary" in payload


if __name__ == "__main__":
    import unittest.mock as _m
    # tmp_path fixture 흉내
    with tempfile.TemporaryDirectory(prefix="r3test_") as td:
        tmp_path = Path(td)
        for fn in [
            test_json_output_schema,
            test_md_json_gate_count_consistency,
            test_warning_only_exit_zero,
            test_no_fail_on_gate_exit_zero,
        ]:
            fn(tmp_path)
            print(f"PASS {fn.__name__}")
    # gateway tests (no tmp_path)
    test_gateway_invalid_report_id()
    print("PASS test_gateway_invalid_report_id")
    test_gateway_valid_report_id_returns_none_for_missing()
    print("PASS test_gateway_valid_report_id_returns_none_for_missing")
    test_gateway_list_reports_returns_list()
    print("PASS test_gateway_list_reports_returns_list")
    test_gateway_load_latest_real()
    print("PASS test_gateway_load_latest_real")
    print("ALL PASS")
