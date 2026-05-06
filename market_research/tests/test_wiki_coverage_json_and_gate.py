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


# ──────────────────────────────────────────────────────────────────
# R3 small fix: fail-on-gate FAIL 케이스 fixture 검증
# ──────────────────────────────────────────────────────────────────

def _fake_inventory_with_dups(period: str) -> dict:
    """G1 + G2 FAIL 유도 — duplicate URL/headline 있음."""
    return {
        "period": period,
        "duplicate_url_groups": {"http://example.com/dup1": 2,
                                   "http://example.com/dup2": 3},
        "duplicate_headline_groups": {"fake headline": 2},
        "by_dir_counts": {"01_Events": 5},
        "total_pages": 5,
        "source_type_distribution": {"(none)": 5},
        "chars_min": 100, "chars_max": 1000, "chars_avg": 500,
        "events_with_sequential_id": 0,
        "events_with_hex_id": 5,
        "future_pages": 0,
    }


def _fake_retrieval(period: str, stage: str, fund_code: str | None = None,
                     keywords=None) -> dict:
    """G6 FAIL (market_debate dup URL) + G7 FAIL (fund_comment 04_Funds)."""
    base = {
        "stage": stage, "period": period, "fund_code": fund_code,
        "keywords": [], "keyword_count": 0,
        "candidate_count": 10, "selected_count": 1, "context_chars": 0,
        "skipped_short_pages": 0, "skipped_fund_mismatch": 0,
        "skipped_future_pages": 0, "skipped_cluster_cap": 0,
        "skipped_excluded": 0,
        "excluded_dirs": [], "excluded_dir_page_count": 0,
        "stage_used": stage, "cluster_cap_used": 2,
        "selected_url_duplicates": [],
        "selected_detail": [],
        "pinned": None,
    }
    if stage == "market_debate":
        base["selected_url_duplicates"] = [("http://example.com/dup1", 2)]
        base["selected_pages"] = [f"01_Events/{period}_event_a.md",
                                    f"01_Events/{period}_event_b.md"]
        return base
    # fund_comment — 04_Funds in selected (G7 FAIL)
    base["selected_pages"] = [f"04_Funds/{period}_{fund_code}.md"]
    base["selected_detail"] = [{
        "path": f"04_Funds/{period}_{fund_code}.md", "dir": "04_Funds",
        "hit_count": 50, "length_bucket": 1, "source_bonus": 1,
        "cluster_key": None, "source_type": "fund_wiki",
        "page_period": (2026, 4),
        "primary_url": None, "primary_headline": "",
    }]
    base["pinned"] = {"page_path": f"04_Funds/{period}_{fund_code}.md",
                       "chars": 1500, "reason": "matched",
                       "text": "fake pinned"}
    return base


def _fake_coverage(period: str, retrieval_market=None) -> list[dict]:
    """G3 FAIL — 1개 missing. G4 FAIL — 1개 base only."""
    rows = []
    for ac in ("국내주식", "국내채권", "환율", "금/대체", "크레딧", "현금성"):
        rows.append({"asset_class": ac, "exists": True,
                      "candidate_files": ["x"], "primary_file": "x",
                      "body_chars": 1500, "source_type": "asset_wiki",
                      "is_enriched": True, "in_market_selected": False})
    rows.append({"asset_class": "해외주식", "exists": False,
                  "candidate_files": [], "primary_file": None,
                  "body_chars": 0, "source_type": None,
                  "is_enriched": False, "in_market_selected": False})
    rows.append({"asset_class": "해외채권", "exists": True,
                  "candidate_files": ["y"], "primary_file": "y",
                  "body_chars": 200, "source_type": None,
                  "is_enriched": False, "in_market_selected": False})
    return rows


def _patch_fakes(monkeypatch):
    from tools import wiki_retrieval_coverage as wrc
    monkeypatch.setattr(wrc, "inventory_report", _fake_inventory_with_dups)
    monkeypatch.setattr(wrc, "retrieval_debug", _fake_retrieval)
    monkeypatch.setattr(wrc, "asset_coverage_report", _fake_coverage)
    return wrc


def test_evaluate_gates_with_fake_failures(monkeypatch):
    """fake fixtures → 5개 gate FAIL (G1, G2, G3, G4, G6) + 펀드별 G7 FAIL."""
    wrc = _patch_fakes(monkeypatch)
    failures, warnings, all_results = wrc.evaluate_gates(
        ["2026-04"], ["07G04"],
        skip_report_periods=set(),
        expected_enriched_periods={"2026-04"},
    )
    fail_gate_ids = {f["gate_id"] for f in failures}
    assert "G1_duplicate_url" in fail_gate_ids
    assert "G2_duplicate_headline" in fail_gate_ids
    assert "G3_missing_required_asset" in fail_gate_ids
    assert "G4_enrichment_expected_but_none" in fail_gate_ids
    assert "G6_market_debate_dup_url" in fail_gate_ids
    assert "G7_fund_comment_04_funds_in_retrieved" in fail_gate_ids

    # all_results 에는 PASS 도 포함됨 (G5: pinned 와 retrieved 의 path 가 같으므로
    # 사실상 G5 는 FAIL — 그러나 pinned 가 04_Funds path 인데 retrieved 도 같으므로
    # G5 도 FAIL 가능. 어쨌든 all_results 에 status 다양성)
    statuses = {r["status"] for r in all_results}
    assert "FAIL" in statuses


def test_evaluate_gates_skip_report_period_warning_only(monkeypatch):
    """skip_report_period 적용 시 G3 (missing asset) → WARNING_SKIP 강등."""
    wrc = _patch_fakes(monkeypatch)
    # G3 만 강등 — 다른 FAIL gate (G1/G2/G6/G7/G4) 는 그대로
    failures, warnings, all_results = wrc.evaluate_gates(
        ["2026-04"], ["07G04"],
        skip_report_periods={"2026-04"},
        expected_enriched_periods={"2026-04"},
    )
    fail_gate_ids = {f["gate_id"] for f in failures}
    warn_gate_ids = {w["gate_id"] for w in warnings}
    assert "G3_missing_required_asset" not in fail_gate_ids
    assert "G3_missing_required_asset" in warn_gate_ids
    # G1/G2/G6/G7/G4 는 여전히 FAIL
    assert "G1_duplicate_url" in fail_gate_ids
    assert "G7_fund_comment_04_funds_in_retrieved" in fail_gate_ids


def test_build_json_report_fail_on_gate_exit_code_1(monkeypatch):
    """fake FAIL + fail_on_gate=True → exit_code_expected=1, fail>0."""
    wrc = _patch_fakes(monkeypatch)
    json_data = wrc.build_json_report(
        ["2026-04"], ["07G04"],
        expected_enriched_periods={"2026-04"},
        fail_on_gate=True,
    )
    gs = json_data["gate_summary"]
    assert gs["fail"] >= 1, f"expected fail>=1, got {gs['fail']}"
    assert gs["exit_code_expected"] == 1, (
        f"expected exit_code_expected=1, got {gs['exit_code_expected']}"
    )
    # gate_results 에 status='FAIL' 항목 존재
    fail_results = [r for r in json_data["gate_results"] if r["status"] == "FAIL"]
    assert len(fail_results) >= 1, "no FAIL in gate_results"


def test_build_json_report_fail_without_flag_exit_0(monkeypatch):
    """fake FAIL 있어도 fail_on_gate=False → exit_code_expected=0."""
    wrc = _patch_fakes(monkeypatch)
    json_data = wrc.build_json_report(
        ["2026-04"], ["07G04"],
        expected_enriched_periods={"2026-04"},
        fail_on_gate=False,
    )
    gs = json_data["gate_summary"]
    # fail count > 0 일지라도 fail_on_gate=False 면 exit_code_expected=0
    assert gs["exit_code_expected"] == 0, (
        f"fail_on_gate=False expected exit_code_expected=0, got "
        f"{gs['exit_code_expected']}"
    )


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

    # R3 small fix: fail-on-gate FAIL fixture
    class FakeMonkey:
        def __init__(self):
            self._patches = []
        def setattr(self, target, name, value):
            p = _m.patch.object(target, name, value)
            p.start()
            self._patches.append(p)
        def stop_all(self):
            for p in self._patches:
                p.stop()

    for fn in [
        test_evaluate_gates_with_fake_failures,
        test_evaluate_gates_skip_report_period_warning_only,
        test_build_json_report_fail_on_gate_exit_code_1,
        test_build_json_report_fail_without_flag_exit_0,
    ]:
        mp = FakeMonkey()
        try:
            fn(mp)
            print(f"PASS {fn.__name__}")
        finally:
            mp.stop_all()
    print("ALL PASS")
