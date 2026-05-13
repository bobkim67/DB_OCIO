# -*- coding: utf-8 -*-
"""R9-A.18 — daily_update Step 2.8 (claim group monitoring) opt-in tests.

워크오더 §테스트:
    1. 기본 실행 불변 — flag 없으면 group monitoring 실행 안 됨
    2. flag ON + claims 있음 — summary 생성
    3. flag ON + claims 없음 — no-op warning
    4. R9-A.11 fixture 재현 — 57/12/4/0

LLM 호출 0. daily_update 전체 호출은 운영 영역 변경 위험이 있어 직접 invoke
하지 않고, `_step_group_monitoring` helper 와 argparse signature 만 단위
검증. R9-A.17 fixture 재현은 별도 entrypoint smoke (이미 commit 된 동작
확인) 로 위임.
"""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path

import pytest

from market_research.pipeline.daily_update import (
    _step_group_monitoring,
    daily_update,
)


# ──────────────────────────────────────────────────────────────────
# Helper: synthetic claim payload
# ──────────────────────────────────────────────────────────────────

def _make_claim(
    *,
    cid: str,
    gid: str,
    text: str = "sample text",
    assets=None,
    evset: str = "evset_hash_x",
    direction: str = "positive",
    horizon: str = "short",
    claim_type: str = "outlook_view",
    promotion_rule: str | None = None,
    promoted: bool = False,
) -> dict:
    return {
        "claim_id": cid,
        "canonical_group_id": gid,
        "claim_text": text,
        "affected_assets": assets if assets is not None else ["국내주식"],
        "evidence_set_hash": evset,
        "direction": direction,
        "horizon": horizon,
        "claim_type": claim_type,
        "promotion_rule": promotion_rule,
        "promoted": promoted,
    }


# ──────────────────────────────────────────────────────────────────
# 1. daily_update signature default OFF (워크오더 §1)
# ──────────────────────────────────────────────────────────────────

def test_daily_update_enable_group_monitoring_default_false():
    """daily_update() 의 enable_group_monitoring 매개변수 default == False."""
    sig = inspect.signature(daily_update)
    p = sig.parameters.get("enable_group_monitoring")
    assert p is not None, "enable_group_monitoring 매개변수 부재"
    assert p.default is False, (
        f"default 가 False 가 아님: {p.default!r}"
    )


def test_daily_update_other_claim_flags_default_false():
    """R9-A.4 claim 관련 flag default 도 회귀 확인."""
    sig = inspect.signature(daily_update)
    for name in (
        "enable_claim_extraction", "write_claims", "allow_out_of_band",
        "dry_run",
    ):
        p = sig.parameters.get(name)
        assert p is not None
        assert p.default is False
    p = sig.parameters.get("target_suffix")
    assert p is not None
    assert p.default is None


# ──────────────────────────────────────────────────────────────────
# 2. argparse store_true default False (워크오더 §1)
# ──────────────────────────────────────────────────────────────────

def test_daily_update_source_has_enable_group_monitoring_flag():
    """daily_update.py 의 argparse 에 `--enable-group-monitoring` flag."""
    src = inspect.getsource(daily_update.__module__ and
                             __import__(daily_update.__module__,
                                        fromlist=["__source__"]))
    # 직접 file source 가져오기
    mod = __import__("market_research.pipeline.daily_update",
                     fromlist=["__file__"])
    text = Path(mod.__file__).read_text(encoding="utf-8")
    assert "--enable-group-monitoring" in text
    assert "args.enable_group_monitoring" in text
    # daily_update() 호출에 enable_group_monitoring kwarg 전달
    assert "enable_group_monitoring=args.enable_group_monitoring" in text


# ──────────────────────────────────────────────────────────────────
# 3. _step_group_monitoring — no claim_step (워크오더 §2 no-op)
# ──────────────────────────────────────────────────────────────────

def test_step28_no_claim_extract_skipped():
    """claim_step 이 비었거나 extraction 없으면 status='skipped'."""
    out = _step_group_monitoring("2026-04", {})
    assert out["status"] == "skipped"
    assert out["total_groups"] == 0
    assert out["stable_candidates"] == 0
    assert "no claim extraction" in out["reason"]


def test_step28_empty_extraction_claims_skipped():
    """claim_step.extraction.claims 가 [] 이면 skipped."""
    out = _step_group_monitoring("2026-04", {
        "extraction": {"claims": []},
    })
    assert out["status"] == "skipped"
    assert out["total_groups"] == 0


def test_step28_claim_step_missing_extraction_skipped():
    """claim_step 에 extraction 키 자체가 없어도 graceful skip."""
    out = _step_group_monitoring("2026-04", {
        "status": "disabled", "llm_calls": 0,
    })
    assert out["status"] == "skipped"
    assert out["total_groups"] == 0


def test_step28_none_claim_step_skipped():
    """claim_step=None 도 안전하게 skipped (TypeError 없이)."""
    out = _step_group_monitoring("2026-04", None)
    assert out["status"] == "skipped"


# ──────────────────────────────────────────────────────────────────
# 4. _step_group_monitoring — claims 있음 (워크오더 §1 flag ON + claims)
# ──────────────────────────────────────────────────────────────────

def test_step28_with_claims_writes_artifacts(tmp_path, monkeypatch):
    """raw claims 있으면 summary 반환 + diagnostics 파일 생성.

    BASE_DIR.parent 가 다른 곳을 가리키도록 monkeypatch — 실제 운영 경로
    오염 방지. 본 test 는 tmp_path 영역만 사용.
    """
    import market_research.pipeline.daily_update as du_mod
    monkeypatch.setattr(du_mod, "BASE_DIR", tmp_path / "market_research")

    claims = [
        _make_claim(cid=f"claim:2026-04:c{i:04d}",
                    gid=f"group:2026-04:g{i}",
                    text=f"sample {i}")
        for i in range(3)
    ]
    claim_step = {
        "status": "ok_plan_ready",
        "extraction": {"claims": claims},
    }
    out = _step_group_monitoring("2026-04", claim_step)
    assert out["status"] == "ok"
    assert out["total_groups"] == 3   # 3 distinct group_id
    assert out["total_claims"] == 3
    assert out["within_run_duplicate_count"] == 0
    # diagnostics 파일 생성됨
    assert out["summary_json_path"] is not None
    assert out["summary_md_path"] is not None
    json_p = Path(out["summary_json_path"])
    md_p = Path(out["summary_md_path"])
    assert json_p.exists()
    assert md_p.exists()
    # JSON 파일 내용 sanity
    data = json.loads(json_p.read_text(encoding="utf-8"))
    assert data["total_groups"] == 3
    assert data["total_claims"] == 3


def test_step28_repeated_claims_form_stable_group(tmp_path, monkeypatch):
    """같은 group_id 의 claim 이 single batch 내 2개 이상이면 overmerge.

    daily batch 는 run_id 가 month_str 단일 → 같은 group_id 2번 등장 시
    workorder §6 overmerge warning trigger.
    """
    import market_research.pipeline.daily_update as du_mod
    monkeypatch.setattr(du_mod, "BASE_DIR", tmp_path / "market_research")

    same_gid = "group:2026-04:abcdef0001"
    claims = [
        _make_claim(cid="claim:2026-04:c0001", gid=same_gid, text="a"),
        _make_claim(cid="claim:2026-04:c0002", gid=same_gid, text="b"),
    ]
    out = _step_group_monitoring("2026-04", {
        "extraction": {"claims": claims},
    })
    assert out["status"] == "ok"
    # 같은 group_id 가 같은 run (=month_str) 안에서 2번 → overmerge warning
    assert out["within_run_duplicate_count"] == 1


def test_step28_summary_metric_keys_complete(tmp_path, monkeypatch):
    """반환 dict 의 monitoring metric key 완비 확인."""
    import market_research.pipeline.daily_update as du_mod
    monkeypatch.setattr(du_mod, "BASE_DIR", tmp_path / "market_research")

    claims = [_make_claim(cid="claim:2026-04:cX",
                          gid="group:2026-04:gX")]
    out = _step_group_monitoring("2026-04", {
        "extraction": {"claims": claims},
    })
    for key in (
        "status", "total_groups", "stable_candidates",
        "strong_stable_candidates", "within_run_duplicate_count",
        "promoted_groups", "total_claims",
        "summary_json_path", "summary_md_path",
    ):
        assert key in out, f"missing key: {key}"


# ──────────────────────────────────────────────────────────────────
# 5. R9-A.11 fixture 재현 (워크오더 §4)
# ──────────────────────────────────────────────────────────────────

R9A11_RAW = (
    Path(__file__).resolve().parents[2]
    / "debug/claims/out/r9a11_raw_claims_20260513_105537.jsonl"
)


@pytest.mark.skipif(not R9A11_RAW.exists(),
                    reason="R9-A.11 raw fixture 부재")
def test_step28_r9a11_fixture_reproduction(tmp_path, monkeypatch):
    """R9-A.11 raw 73 rows 를 단일 batch claim list 처럼 inject —
    multi-run claim 들이 single run_id 로 들어가므로 overmerge 발생 기대.
    그러나 utility 자체의 동작은 deterministic — total_groups 가 57 (R9-A.16
    의 group 분포) 와 같아야 함.
    """
    import market_research.pipeline.daily_update as du_mod
    monkeypatch.setattr(du_mod, "BASE_DIR", tmp_path / "market_research")

    # raw jsonl 로딩
    rows = []
    with R9A11_RAW.open(encoding="utf-8") as fh:
        for line in fh:
            rows.append(json.loads(line))
    # raw jsonl 의 stored canonical_group_id 는 R9-A.11 시점 (R9-A.8/A.12)
    # 정의. daily_update 의 Step 2.8 은 normalize_claim 통과 후 claims 가
    # 들어온다고 가정 — fixture 도 R9-A.14 G1 정의로 재계산해 inject.
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    for r in rows:
        r["canonical_group_id"] = compute_canonical_group_id(
            "2026-04",
            r.get("claim_text") or "",
            r.get("affected_assets") or [],
            source_evidence_ids=r.get("source_evidence_ids") or [],
            direction=r.get("direction") or "unknown",
            horizon=r.get("horizon") or "unknown",
            claim_type=r.get("claim_type") or "outlook_view",
        )

    out = _step_group_monitoring("2026-04", {
        "extraction": {"claims": rows},
    })
    assert out["status"] == "ok"
    # R9-A.16 fixture 의 group 수 재현 (57)
    assert out["total_groups"] == 57
    assert out["total_claims"] == 73
    # 그러나 단일 run_id 로 inject 했으므로 multi-run repeat 은 잡히지 않음
    # → stable_candidates 는 0 (run_count ≥ 2 가 1 개 batch 안에서는 불가).
    # 대신 within_run_duplicate_count 가 R9-A.16 의 cross-run repeat≥2 = 12
    # 와 동일 — 단일 run 안에 같은 group_id 12 번 중복 카운트.
    assert out["within_run_duplicate_count"] == 12   # R9-A.16 repeat≥2
