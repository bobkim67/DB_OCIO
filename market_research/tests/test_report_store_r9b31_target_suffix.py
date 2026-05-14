# -*- coding: utf-8 -*-
"""R9-B.3.1 — Isolated output target (target_suffix) tests.

LLM 호출 0. 모든 IO 는 tmp_path 격리. 운영 report_output 미접근.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_research.report import report_store as rs


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_output(tmp_path, monkeypatch):
    out = tmp_path / "report_output"
    out.mkdir(parents=True)
    monkeypatch.setattr(rs, "OUTPUT_DIR", out)
    # EVIDENCE_TRACKER 도 새 OUTPUT_DIR 기준으로 재계산되도록 module 상수 갱신
    monkeypatch.setattr(rs, "EVIDENCE_TRACKER",
                         out / "_evidence_quality.jsonl")
    return out


def _draft(**kwargs):
    base = {
        "draft_comment": "ok.",
        "status": rs.STATUS_DRAFT,
        "debate_run_id": "test_run",
        "generated_at": "2026-05-14T00:00:00",
    }
    base.update(kwargs)
    return base


# ──────────────────────────────────────────────────────────────────
# 1. suffix sanitizer
# ──────────────────────────────────────────────────────────────────

def test_sanitize_none_passes_through():
    assert rs.sanitize_target_suffix(None) is None


def test_sanitize_valid_suffix_returned_as_is():
    assert rs.sanitize_target_suffix("r9b3-smoke") == "r9b3-smoke"
    assert rs.sanitize_target_suffix("wiki_test_01") == "wiki_test_01"
    assert rs.sanitize_target_suffix("A1") == "A1"
    assert rs.sanitize_target_suffix("0") == "0"


def test_sanitize_strips_whitespace_only_when_safe():
    assert rs.sanitize_target_suffix("  r9b3-smoke  ") == "r9b3-smoke"


@pytest.mark.parametrize("bad", [
    "",                       # empty
    "   ",                    # whitespace only
    "../x",                   # parent traversal
    "../../etc",              # deeper traversal
    "a/b",                    # forward slash
    "a\\b",                   # backslash
    "..",                     # dot-dot bare
    ".",                      # bare dot
    "x.y",                    # internal dot
    "x.y.z",                  # multi-dot
    "-suffix",                # leading hyphen
    "a" * 41,                 # length cap
    "foo bar",                # whitespace inside
    "한글",                    # non-ASCII
    "a:b",                    # colon
    "a;b",                    # semicolon
    "a?b",                    # query
    "a$",                     # dollar
])
def test_sanitize_rejects_invalid(bad):
    with pytest.raises(ValueError):
        rs.sanitize_target_suffix(bad)


def test_sanitize_rejects_non_string():
    with pytest.raises(ValueError):
        rs.sanitize_target_suffix(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        rs.sanitize_target_suffix(["x"])  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────
# 2. path builder default invariant
# ──────────────────────────────────────────────────────────────────

def test_path_builder_default_unchanged(tmp_output):
    """target_suffix=None → 기존 파일명과 완전 동일."""
    p = rs._artifact_path("2026-04", "_market", "final", None)
    assert p.name == "_market.final.json"
    assert p.parent.name == "2026-04"


def test_path_builder_suffix_applies(tmp_output):
    p = rs._artifact_path("2026-04", "_market", "final", "r9b3-smoke")
    assert p.name == "_market.r9b3-smoke.final.json"


def test_path_builder_all_kinds(tmp_output):
    for kind, expected in (
        ("input", "_market.r9b3-smoke.input.json"),
        ("draft", "_market.r9b3-smoke.draft.json"),
        ("final", "_market.r9b3-smoke.final.json"),
    ):
        p = rs._artifact_path("2026-04", "_market", kind, "r9b3-smoke")
        assert p.name == expected


# ──────────────────────────────────────────────────────────────────
# 3. save/load round-trip — default + suffix
# ──────────────────────────────────────────────────────────────────

def test_save_load_draft_default_unchanged(tmp_output):
    rs.save_draft("2026-04", "_market", _draft())
    expected = tmp_output / "2026-04" / "_market.draft.json"
    assert expected.exists()
    loaded = rs.load_draft("2026-04", "_market")
    assert loaded is not None
    assert loaded["status"] == rs.STATUS_DRAFT
    assert "target_suffix" not in loaded  # legacy shape preserved


def test_save_load_draft_suffix_round_trip(tmp_output):
    rs.save_draft("2026-04", "_market", _draft(),
                  target_suffix="r9b3-smoke")
    expected = tmp_output / "2026-04" / "_market.r9b3-smoke.draft.json"
    assert expected.exists()
    loaded = rs.load_draft("2026-04", "_market", target_suffix="r9b3-smoke")
    assert loaded is not None
    assert loaded["target_suffix"] == "r9b3-smoke"


def test_save_load_input_package_round_trip(tmp_output):
    rs.save_input_package("2026-04", "_market", {"foo": "bar"},
                          target_suffix="r9b3-smoke")
    expected = tmp_output / "2026-04" / "_market.r9b3-smoke.input.json"
    assert expected.exists()
    loaded = rs.load_input_package("2026-04", "_market",
                                    target_suffix="r9b3-smoke")
    assert loaded["foo"] == "bar"
    assert loaded["target_suffix"] == "r9b3-smoke"


def test_approve_and_save_final_suffix(tmp_output):
    rs.save_draft("2026-04", "_market", _draft(draft_comment="market draft."),
                  target_suffix="r9b3-smoke")
    final_path = rs.approve_and_save_final(
        "2026-04", "_market", approved_by="claude",
        target_suffix="r9b3-smoke",
    )
    assert final_path is not None
    assert final_path.name == "_market.r9b3-smoke.final.json"
    final = rs.load_final("2026-04", "_market", target_suffix="r9b3-smoke")
    assert final is not None
    assert final["approved"] is True
    assert final["target_suffix"] == "r9b3-smoke"
    assert final["final_comment"] == "market draft."


# ──────────────────────────────────────────────────────────────────
# 4. no overwrite — legacy and suffix coexist
# ──────────────────────────────────────────────────────────────────

def test_legacy_and_suffix_do_not_overwrite_each_other(tmp_output):
    """suffix run 이 운영 final/draft 를 덮어쓰지 않아야 한다 (R9-B.3.1 핵심)."""
    # 1) 운영 draft + final
    rs.save_draft("2026-04", "_market", _draft(draft_comment="legacy."))
    rs.approve_and_save_final("2026-04", "_market")
    legacy_final = rs.load_final("2026-04", "_market")
    legacy_text = legacy_final["final_comment"]
    legacy_path = tmp_output / "2026-04" / "_market.final.json"
    legacy_mtime = legacy_path.stat().st_mtime_ns

    # 2) suffix smoke run
    rs.save_draft("2026-04", "_market",
                  _draft(draft_comment="smoke run text."),
                  target_suffix="r9b3-smoke")
    rs.approve_and_save_final("2026-04", "_market",
                              target_suffix="r9b3-smoke")

    # 운영 final 은 변경 0
    legacy_final_after = rs.load_final("2026-04", "_market")
    assert legacy_final_after["final_comment"] == legacy_text
    assert legacy_path.stat().st_mtime_ns == legacy_mtime
    # suffix final 별도 존재
    suffix_final = rs.load_final("2026-04", "_market",
                                  target_suffix="r9b3-smoke")
    assert suffix_final["final_comment"] == "smoke run text."
    # 두 파일이 별도 path
    suffix_path = tmp_output / "2026-04" / "_market.r9b3-smoke.final.json"
    assert legacy_path != suffix_path
    assert suffix_path.exists()


def test_load_default_does_not_read_suffix_file(tmp_output):
    """suffix only 저장 후 default load → None."""
    rs.save_draft("2026-04", "_market", _draft(),
                  target_suffix="r9b3-smoke")
    rs.approve_and_save_final("2026-04", "_market",
                              target_suffix="r9b3-smoke")
    assert rs.load_draft("2026-04", "_market") is None
    assert rs.load_final("2026-04", "_market") is None


# ──────────────────────────────────────────────────────────────────
# 5. list helpers exclude suffix files in default mode
# ──────────────────────────────────────────────────────────────────

def test_list_funds_default_excludes_suffix(tmp_output):
    rs.save_draft("2026-04", "_market", _draft())
    rs.save_draft("2026-04", "_market", _draft(),
                  target_suffix="r9b3-smoke")
    rs.save_draft("2026-04", "07G04", _draft(),
                  target_suffix="r9b3-smoke")
    # default → _market 1개만
    assert rs.list_funds_in_period("2026-04") == ["_market"]
    # suffix → 둘 다
    assert sorted(rs.list_funds_in_period(
        "2026-04", target_suffix="r9b3-smoke"
    )) == ["07G04", "_market"]


def test_list_approved_funds_default_excludes_suffix(tmp_output):
    # legacy approved
    rs.save_draft("2026-04", "_market", _draft())
    rs.approve_and_save_final("2026-04", "_market")
    # suffix approved
    rs.save_draft("2026-04", "07G04", _draft(),
                  target_suffix="r9b3-smoke")
    rs.approve_and_save_final("2026-04", "07G04",
                              target_suffix="r9b3-smoke")

    assert rs.list_approved_funds("2026-04") == ["_market"]
    assert rs.list_approved_funds(
        "2026-04", target_suffix="r9b3-smoke"
    ) == ["07G04"]


def test_list_approved_periods_default_excludes_suffix_only(tmp_output):
    """suffix final 만 있는 period 는 default 운영 list 에 등장 X."""
    rs.save_draft("2026-04", "_market", _draft(),
                  target_suffix="r9b3-smoke")
    rs.approve_and_save_final("2026-04", "_market",
                              target_suffix="r9b3-smoke")
    # 운영 final 0건 → default list 빈 list
    assert rs.list_approved_periods() == []
    # suffix list 는 2026-04 surface
    assert rs.list_approved_periods(target_suffix="r9b3-smoke") == ["2026-04"]


def test_get_latest_period_for_fund_default_ignores_suffix(tmp_output):
    rs.save_draft("2026-04", "_market", _draft(),
                  target_suffix="r9b3-smoke")
    rs.approve_and_save_final("2026-04", "_market",
                               target_suffix="r9b3-smoke")
    # 운영 → None
    assert rs.get_latest_period_for_fund("_market") is None
    # suffix → 2026-04
    assert rs.get_latest_period_for_fund(
        "_market", target_suffix="r9b3-smoke"
    ) == "2026-04"


# ──────────────────────────────────────────────────────────────────
# 6. evidence ledger isolation
# ──────────────────────────────────────────────────────────────────

def test_evidence_ledger_default_path(tmp_output):
    rs.append_evidence_quality({"period": "2026-04", "fund": "_market"})
    legacy_path = tmp_output / "_evidence_quality.jsonl"
    assert legacy_path.exists()
    assert (tmp_output / "_evidence_quality.r9b3-smoke.jsonl").exists() is False


def test_evidence_ledger_suffix_isolated(tmp_output):
    rs.append_evidence_quality({"period": "2026-04", "fund": "_market"},
                                target_suffix="r9b3-smoke")
    legacy_path = tmp_output / "_evidence_quality.jsonl"
    suffix_path = tmp_output / "_evidence_quality.r9b3-smoke.jsonl"
    assert legacy_path.exists() is False
    assert suffix_path.exists()
    rows = rs.load_evidence_quality_records(target_suffix="r9b3-smoke")
    assert len(rows) == 1
    assert rows[0]["target_suffix"] == "r9b3-smoke"
    # 운영 ledger 는 빈 결과
    assert rs.load_evidence_quality_records() == []


def test_evidence_record_not_mutated(tmp_output):
    """caller 의 record dict 가 mutate 되면 안 됨."""
    rec = {"period": "2026-04", "fund": "_market"}
    rs.append_evidence_quality(rec, target_suffix="r9b3-smoke")
    assert "target_suffix" not in rec  # 원본 보존


# ──────────────────────────────────────────────────────────────────
# 7. update_draft_comment with suffix
# ──────────────────────────────────────────────────────────────────

def test_update_draft_comment_suffix(tmp_output):
    rs.save_draft("2026-04", "_market", _draft(),
                  target_suffix="r9b3-smoke")
    updated = rs.update_draft_comment(
        "2026-04", "_market", "edited.",
        target_suffix="r9b3-smoke",
    )
    assert updated is not None
    assert updated["draft_comment"] == "edited."
    assert updated["status"] == rs.STATUS_EDITED
    # 운영 draft 는 영향 X
    assert rs.load_draft("2026-04", "_market") is None


# ──────────────────────────────────────────────────────────────────
# 8. get_status with suffix
# ──────────────────────────────────────────────────────────────────

def test_get_status_suffix_isolated(tmp_output):
    rs.save_draft("2026-04", "_market", _draft())
    rs.save_draft("2026-04", "_market", _draft(),
                  target_suffix="r9b3-smoke")
    rs.approve_and_save_final("2026-04", "_market",
                              target_suffix="r9b3-smoke")
    # 운영: draft 만 → draft_generated
    assert rs.get_status("2026-04", "_market") == rs.STATUS_DRAFT
    # suffix: approved
    assert rs.get_status(
        "2026-04", "_market", target_suffix="r9b3-smoke"
    ) == rs.STATUS_APPROVED


# ──────────────────────────────────────────────────────────────────
# 9. Save raises on invalid suffix (early gate)
# ──────────────────────────────────────────────────────────────────

def test_save_draft_rejects_invalid_suffix(tmp_output):
    with pytest.raises(ValueError):
        rs.save_draft("2026-04", "_market", _draft(),
                      target_suffix="../etc/passwd")


def test_approve_and_save_final_rejects_invalid_suffix(tmp_output):
    rs.save_draft("2026-04", "_market", _draft(),
                  target_suffix="r9b3-smoke")
    with pytest.raises(ValueError):
        rs.approve_and_save_final("2026-04", "_market",
                                   target_suffix="a/b")


# ──────────────────────────────────────────────────────────────────
# 10. CLI flag presence
# ──────────────────────────────────────────────────────────────────

def test_cli_has_target_suffix_flag():
    cli_text = (
        Path(__file__).resolve().parent.parent / "report" / "cli.py"
    ).read_text(encoding="utf-8")
    assert "--target-suffix" in cli_text
    assert "target_suffix: str | None = None" in cli_text
    # CLI 의 sanitizer 호출
    assert "sanitize_target_suffix(target_suffix)" in cli_text


def test_cli_cache_path_suffix_kwarg():
    """_cache_path 가 target_suffix kwarg 를 받아들이는지 직접 검증."""
    from market_research.report import cli as _cli
    p_default = _cli._cache_path("2026Q1", "08K88")
    p_suffix = _cli._cache_path("2026Q1", "08K88", target_suffix="r9b3-smoke")
    assert p_default.name == "08K88.json"
    assert p_suffix.name == "08K88.r9b3-smoke.json"


# ──────────────────────────────────────────────────────────────────
# 11. opt-in compatibility — debate_service kwarg pass-through
# ──────────────────────────────────────────────────────────────────

def test_debate_service_accepts_target_suffix_with_wcp(monkeypatch, tmp_output):
    """run_debate_and_save 가 target_suffix + use_wiki_context_pack 양쪽 OK."""
    from market_research.report import debate_service, debate_engine

    fake_result = {
        "year": 2026, "month": 4,
        "debate_run_id": "fake_run_id",
        "debated_at": "2026-05-14T00:00:00",
        "agents": {"bull": {"stance": "bullish", "key_points": []}},
        "synthesis": {"customer_comment": "smoke.",
                       "consensus_points": [], "disagreements": [],
                       "tail_risks": [], "admin_summary": ""},
        "debate_narrative": {"debate_narrative": "n",
                              "canonical_snapshot": {},
                              "diverges_from_canonical": False},
        "_evidence_ids": [],
        "_debug_trace": {
            "prompt_context_mode": "wiki_context_pack_opt_in",
            "wiki_context_pack_enabled": True,
            "wiki_pages_selected": 12,
        },
    }
    seen: dict = {}

    def _fake_run_market_debate(year, month, **kw):
        seen.update(year=year, month=month, **kw)
        return fake_result

    monkeypatch.setattr(
        debate_engine, "run_market_debate", _fake_run_market_debate,
    )
    # debate_memory writer 차단 (외부 wiki write 0)
    monkeypatch.setattr(
        "market_research.wiki.debate_memory.write_debate_memory_page",
        lambda draft, regime_file: Path("/tmp/dummy.md"),
    )

    draft = debate_service.run_debate_and_save(
        mode="월별", year=2026, period_num=4,
        fund_code="_market", period_key="2026-04",
        target_suffix="r9b3-smoke",
        use_wiki_context_pack=True,
        wiki_context_max_pages=8,
    )
    assert draft["target_suffix"] == "r9b3-smoke"
    assert seen["use_wiki_context_pack"] is True
    assert seen["wiki_context_max_pages"] == 8
    # debug trace 가 draft 에 보존
    assert draft["_debug_trace"]["wiki_context_pack_enabled"] is True

    # suffix file 만 존재, 운영 draft 부재
    suffix_path = tmp_output / "2026-04" / "_market.r9b3-smoke.draft.json"
    legacy_path = tmp_output / "2026-04" / "_market.draft.json"
    assert suffix_path.exists()
    assert legacy_path.exists() is False

    # evidence ledger 도 suffix 격리
    suffix_eq = tmp_output / "_evidence_quality.r9b3-smoke.jsonl"
    legacy_eq = tmp_output / "_evidence_quality.jsonl"
    assert suffix_eq.exists()
    assert legacy_eq.exists() is False
