"""market_research 측 debate_run_id 부착 + final 승인 시 ID 복사 smoke test.

debate_engine / fund_comment_service 의 LLM 호출은 mock 으로 우회.
report_store 의 OUTPUT_DIR 은 tmp_path 로 격리.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ────────────────────────────────────────────────────────────────────
# fixture: report_store OUTPUT_DIR 격리
# ────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_report_root(tmp_path: Path, monkeypatch) -> Path:
    from market_research.report import report_store
    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)
    monkeypatch.setattr(
        report_store, "EVIDENCE_TRACKER", root / "_evidence_quality.jsonl",
    )

    # debate_service 가 호출하는 wiki write 도 tmp 로 격리하여
    # 실제 market_research/data/wiki 디렉토리에 부산물이 생기는 것을 방지.
    # debate_memory 모듈은 import 시점에 DEBATE_MEMORY_DIR 을 흡수하므로
    # 모듈 자체의 심볼을 패치해야 함.
    try:
        from market_research.wiki import debate_memory as wiki_debate_memory
        wiki_tmp = tmp_path / "wiki" / "06_Debate_Memory"
        wiki_tmp.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(wiki_debate_memory, "DEBATE_MEMORY_DIR", wiki_tmp)
    except ImportError:
        pass

    return root


# ────────────────────────────────────────────────────────────────────
# debate_engine.run_market_debate() — debate_run_id 부착
# ────────────────────────────────────────────────────────────────────

def test_market_debate_result_has_debate_run_id(monkeypatch, tmp_report_root):
    """run_market_debate 결과 dict 에 32-char hex debate_run_id 가 박힌다."""
    from market_research.report import debate_engine

    # 무거운 의존성 stub
    monkeypatch.setattr(
        debate_engine, "_build_shared_context",
        lambda *a, **kw: {"_evidence_ids": [], "indicators_text": "",
                          "news_summary_text": "", "graph_paths_text": "",
                          "blog_context_text": ""},
    )
    monkeypatch.setattr(
        debate_engine, "_run_agent",
        lambda agent, ctx: {"agent": agent, "stance": "neutral", "key_points": []},
    )
    monkeypatch.setattr(
        debate_engine, "_summarize_debate_narrative",
        lambda r: {"debate_narrative": "", "diverges_from_canonical": False,
                   "canonical_snapshot": {}},
    )
    monkeypatch.setattr(
        debate_engine, "_synthesize_debate",
        lambda *a, **kw: {"customer_comment": "test", "consensus_points": [],
                          "disagreements": [], "tail_risks": [],
                          "admin_summary": ""},
    )
    # debate_logs 디렉토리도 tmp 로 격리
    monkeypatch.setattr(
        debate_engine, "DEBATE_LOG_DIR", tmp_report_root / "debate_logs",
    )
    (tmp_report_root / "debate_logs").mkdir(exist_ok=True)

    result = debate_engine.run_market_debate(2026, 4)
    assert "debate_run_id" in result
    rid = result["debate_run_id"]
    assert isinstance(rid, str)
    assert len(rid) == 32  # uuid4().hex
    int(rid, 16)  # hex 검증


def test_two_debate_runs_have_different_ids(monkeypatch, tmp_report_root):
    """run 마다 debate_run_id 가 새로 발급된다 (덮어쓰기/공유 방지)."""
    from market_research.report import debate_engine

    monkeypatch.setattr(
        debate_engine, "_build_shared_context",
        lambda *a, **kw: {"_evidence_ids": [], "indicators_text": "",
                          "news_summary_text": "", "graph_paths_text": "",
                          "blog_context_text": ""},
    )
    monkeypatch.setattr(
        debate_engine, "_run_agent",
        lambda agent, ctx: {"agent": agent, "stance": "neutral", "key_points": []},
    )
    monkeypatch.setattr(
        debate_engine, "_summarize_debate_narrative",
        lambda r: {"debate_narrative": "", "diverges_from_canonical": False,
                   "canonical_snapshot": {}},
    )
    monkeypatch.setattr(
        debate_engine, "_synthesize_debate",
        lambda *a, **kw: {"customer_comment": "test"},
    )
    monkeypatch.setattr(
        debate_engine, "DEBATE_LOG_DIR", tmp_report_root / "debate_logs",
    )
    (tmp_report_root / "debate_logs").mkdir(exist_ok=True)

    r1 = debate_engine.run_market_debate(2026, 4)
    r2 = debate_engine.run_market_debate(2026, 4)
    assert r1["debate_run_id"] != r2["debate_run_id"]


# ────────────────────────────────────────────────────────────────────
# report_store.approve_and_save_final() — ID 복사
# ────────────────────────────────────────────────────────────────────

def test_approve_copies_debate_run_id_to_final(tmp_report_root):
    """draft.debate_run_id → final.approved_debate_run_id 로 복사된다."""
    from market_research.report import report_store

    period, fund = "2026-04", "_market"
    run_id = "c" * 32
    draft = {
        "fund_code": fund,
        "period": period,
        "status": report_store.STATUS_DRAFT,
        "debate_run_id": run_id,
        "draft_comment": "test comment",
        "generated_at": "2026-04-20T10:00:00",
        "model": "claude-opus-4-7",
    }
    report_store.save_draft(period, fund, draft)
    path = report_store.approve_and_save_final(period, fund, approved_by="admin")
    assert path is not None
    final = json.loads(path.read_text(encoding="utf-8"))
    assert final["approved_debate_run_id"] == run_id
    assert final["approved"] is True
    assert final["final_comment"] == "test comment"


def test_approve_legacy_draft_without_id_results_in_none(tmp_report_root):
    """legacy draft (debate_run_id 부재) 승인 시 final.approved_debate_run_id=None."""
    from market_research.report import report_store

    period, fund = "2026-04", "_market"
    draft = {
        "fund_code": fund,
        "period": period,
        "status": report_store.STATUS_DRAFT,
        # debate_run_id 부재 (legacy)
        "draft_comment": "legacy comment",
        "generated_at": "2026-04-20T10:00:00",
    }
    report_store.save_draft(period, fund, draft)
    path = report_store.approve_and_save_final(period, fund, approved_by="admin")
    assert path is not None
    final = json.loads(path.read_text(encoding="utf-8"))
    assert "approved_debate_run_id" in final
    assert final["approved_debate_run_id"] is None


def test_approve_uses_payload_id_not_disk_reread(tmp_report_root, monkeypatch):
    """approve 직전에 디스크의 다른 draft 로 덮어써져도, approve 가 자체 load_draft 로
    읽어온 payload 의 ID 를 복사하는 것이 명세. (현 구현은 load_draft 1회 호출이라
    그 결과의 ID 가 final 에 반영됨을 확인.)
    """
    from market_research.report import report_store

    period, fund = "2026-04", "_market"
    original_id = "d" * 32
    other_id = "e" * 32

    # 정상 flow: save_draft → approve
    report_store.save_draft(period, fund, {
        "fund_code": fund, "period": period,
        "debate_run_id": original_id,
        "draft_comment": "v1",
    })
    # approve 가 load_draft 한 시점의 debate_run_id 를 사용함을 검증
    path = report_store.approve_and_save_final(period, fund)
    final = json.loads(path.read_text(encoding="utf-8"))
    assert final["approved_debate_run_id"] == original_id

    # 이후 draft 가 수정되어도 final 은 이미 승인 시점 ID 를 보존
    report_store.save_draft(period, fund, {
        "fund_code": fund, "period": period,
        "debate_run_id": other_id,
        "draft_comment": "v2",
    })
    final_after = json.loads(path.read_text(encoding="utf-8"))
    assert final_after["approved_debate_run_id"] == original_id  # 변경 없음


# ────────────────────────────────────────────────────────────────────
# debate_service.run_debate_and_save() — draft + jsonl 양쪽 ID 부착
# ────────────────────────────────────────────────────────────────────

def test_run_debate_and_save_propagates_id_to_draft_and_jsonl(
    monkeypatch, tmp_report_root,
):
    """debate_engine 결과의 debate_run_id 가 draft.json 과 jsonl row 에 동일하게 박힌다.

    중복 발급 / 덮어쓰기 방지 검증.
    """
    from market_research.report import debate_service, debate_engine, report_store

    fixed_run_id = "f" * 32

    def _stub_run_market_debate(year, month, **kw):
        return {
            "year": year, "month": month,
            "debate_run_id": fixed_run_id,
            "debated_at": "2026-04-20T10:00:00",
            "agents": {},
            "synthesis": {
                "customer_comment": "test", "consensus_points": [],
                "disagreements": [], "tail_risks": [], "admin_summary": "",
            },
            "debate_narrative": {
                "debate_narrative": "", "canonical_snapshot": {},
                "diverges_from_canonical": False,
            },
            "_evidence_ids": [],
        }

    monkeypatch.setattr(debate_engine, "run_market_debate", _stub_run_market_debate)
    # debate_service 가 import 시점에 끌어올린 심볼도 동일하게 패치
    monkeypatch.setattr(
        "market_research.report.debate_engine.run_market_debate",
        _stub_run_market_debate,
    )
    # 06_Debate_Memory wiki 쓰기는 try/except 로 감싸져 있어 무시됨

    period, fund = "2026-04", "_market"
    draft = debate_service.run_debate_and_save(
        "월별", 2026, 4, fund, period,
    )
    assert draft["debate_run_id"] == fixed_run_id

    # draft.json 디스크 검증
    on_disk = report_store.load_draft(period, fund)
    assert on_disk["debate_run_id"] == fixed_run_id

    # jsonl row 검증
    rows = report_store.load_evidence_quality_records()
    matching = [r for r in rows
                if r.get("period") == period and r.get("fund_code") == fund]
    assert len(matching) >= 1
    assert matching[-1]["debate_run_id"] == fixed_run_id
