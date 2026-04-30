"""P3: WikiTree retrieval + graph_paths formatter tests.

LLM 미호출. retrieval helper 와 prompt 보강 로직만 단위 테스트.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────
# wiki_retriever
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def wiki_root(tmp_path: Path, monkeypatch):
    from market_research.report import wiki_retriever as wr
    root = tmp_path / "wiki"
    for d in wr.TARGET_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(wr, "WIKI_ROOT", root)
    return root


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_wiki_retrieval_picks_relevant_pages(wiki_root):
    from market_research.report import wiki_retriever as wr
    big = "ABC " * 200  # ~800 chars
    _write(wiki_root / "01_Events" / "ev_oil.md",
           f"# Event oil\n\n유가 급등 이란 호르무즈 source: 뉴스1 [ref:1]\n\n{big}")
    _write(wiki_root / "01_Events" / "ev_other.md",
           f"# Event other\n\nKOSPI 반등 source: 뉴시스\n\n{big}")
    _write(wiki_root / "02_Entities" / "entity_iran.md",
           f"# Iran\n\n이란 호르무즈 해협 source: Reuters\n\n{big}")

    r = wr.retrieve_wiki_context(["이란", "호르무즈"], max_pages=5)
    assert r["selected_count"] >= 2
    pages = " ".join(r["selected_pages"])
    assert "ev_oil.md" in pages or "entity_iran.md" in pages
    assert r["context_chars"] > 0


def test_wiki_retrieval_short_pages_low_priority(wiki_root):
    """500자 미만 page 는 우선순위 강등 (skipped_short 카운트)."""
    from market_research.report import wiki_retriever as wr
    _write(wiki_root / "01_Events" / "short.md", "이란 호르무즈\n\n짧은 페이지")
    big = "ABC " * 200
    _write(wiki_root / "01_Events" / "long.md",
           f"# Long\n\n이란 호르무즈 source: AP\n\n{big}")
    r = wr.retrieve_wiki_context(["이란", "호르무즈"])
    assert "long.md" in " ".join(r["selected_pages"])
    assert "short.md" not in " ".join(r["selected_pages"])
    assert r["skipped_short_pages"] >= 1


def test_wiki_retrieval_respects_max_context_chars(wiki_root):
    from market_research.report import wiki_retriever as wr
    big = "X" * 1000
    for i in range(5):
        _write(wiki_root / "01_Events" / f"ev_{i}.md",
               f"# Event {i}\n\n키워드 매칭 source: AP\n\n{big}")
    r = wr.retrieve_wiki_context(["키워드"], max_context_chars=600)
    assert r["context_chars"] <= 600


def test_wiki_retrieval_empty_keywords(wiki_root):
    from market_research.report import wiki_retriever as wr
    big = "X" * 1000
    _write(wiki_root / "01_Events" / "ev.md", f"# Event\n\n본문\n\n{big}")
    r = wr.retrieve_wiki_context([])
    assert r["text"] == ""
    assert r["selected_count"] == 0


def test_wiki_retrieval_no_candidates(wiki_root):
    from market_research.report import wiki_retriever as wr
    r = wr.retrieve_wiki_context(["존재하지않는토큰"])
    assert r["text"] == ""
    assert r["selected_count"] == 0


def test_format_wiki_context_for_prompt_empty():
    from market_research.report import wiki_retriever as wr
    assert wr.format_wiki_context_for_prompt({}) == ""
    assert wr.format_wiki_context_for_prompt({"text": ""}) == ""


def test_format_wiki_context_for_prompt_has_section_header():
    from market_research.report import wiki_retriever as wr
    out = wr.format_wiki_context_for_prompt({"text": "BODY"})
    assert "## 관련 WikiTree 메모" in out
    assert "BODY" in out


# ─────────────────────────────────────────────────────────────────────
# debate_engine — graph paths formatter (read-only, LLM 미호출)
# ─────────────────────────────────────────────────────────────────────

def _make_graph(tmp_path: Path, paths: list[dict]) -> Path:
    """tmp insight_graph file under <root>/data/insight_graph/."""
    import json
    gd = tmp_path / "data" / "insight_graph"
    gd.mkdir(parents=True, exist_ok=True)
    fp = gd / "2026-04.json"
    fp.write_text(json.dumps({
        "nodes": [], "edges": [], "transmission_paths": paths,
        "metadata": {"month": "2026-04"},
    }, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _patch_paths(monkeypatch, project_root: Path):
    from market_research.report import debate_engine as DE
    monkeypatch.setattr(DE, "BASE_DIR", project_root)


def test_graph_paths_text_with_six_paths(tmp_path, monkeypatch):
    """6개 이상 path 있으면 prompt 에 포함 + 새 포맷."""
    from market_research.report import debate_engine as DE
    paths = [
        {"path_labels": [f"A{i}", f"B{i}"], "path": [f"A{i}", f"B{i}"],
         "confidence": 0.5 + i * 0.05, "target": f"asset{i}"}
        for i in range(8)
    ]
    proot = _make_graph(tmp_path, paths)
    _patch_paths(monkeypatch, proot)
    # news/macro 파일 없음 → 해당 블록 skip 됨. graph 만 검증.
    monkeypatch.setattr(DE, "_build_evidence_candidates",
                        lambda *a, **k: ([], [], [], {}))
    ctx = DE._build_shared_context(2026, 4)
    text = ctx.get("graph_paths_text") or ""
    assert "## 주요 인과 경로" in text
    assert "[인과경로 1" in text
    # 6개 이상 포함
    assert text.count("[인과경로") >= 6
    trace = ctx.get("_graph_trace") or {}
    assert trace["selected_path_count"] >= 6
    assert trace["candidate_path_count"] == 8


def test_graph_paths_text_low_confidence_filled_to_min(tmp_path, monkeypatch):
    """confident path 적으면 약한 path 로 보충 (TARGET_MIN=6)."""
    from market_research.report import debate_engine as DE
    paths = [
        {"path_labels": ["A0", "B0"], "confidence": 0.9, "target": "T"},
        # 나머지 7개 약한 path
        *[{"path_labels": [f"A{i}", f"B{i}"], "confidence": 0.1, "target": "T"}
          for i in range(1, 8)],
    ]
    proot = _make_graph(tmp_path, paths)
    _patch_paths(monkeypatch, proot)
    monkeypatch.setattr(DE, "_build_evidence_candidates",
                        lambda *a, **k: ([], [], [], {}))
    ctx = DE._build_shared_context(2026, 4)
    trace = ctx.get("_graph_trace") or {}
    assert trace["selected_path_count"] >= 6
    # 약한 path 가 dropped 로 카운트되었는지
    assert trace["dropped_low_confidence_count"] == 7


def test_graph_paths_text_empty_when_no_graph(tmp_path, monkeypatch):
    """graph 파일 없으면 graceful 처리 (text 빈 + trace 0)."""
    from market_research.report import debate_engine as DE
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(DE, "_build_evidence_candidates",
                        lambda *a, **k: ([], [], [], {}))
    ctx = DE._build_shared_context(2026, 4)
    assert (ctx.get("graph_paths_text") or "") == ""
    trace = ctx.get("_graph_trace") or {}
    assert trace["selected_path_count"] == 0


# ─────────────────────────────────────────────────────────────────────
# Agent prompt 강제 문구 포함 + Synthesis prompt 강제 문구 포함
# ─────────────────────────────────────────────────────────────────────

def test_agent_prompt_contains_p3_directives():
    from market_research.report import debate_engine as DE
    ctx = {
        "year": 2026, "month": 4,
        "news_summary_text": "(뉴스 데이터 없음)",
        "indicators_text": "",
        "timeseries_narrative_text": "",
        "graph_paths_text": "## 주요 인과 경로\n[인과경로 1] A → B",
        "wiki_context_text": "## 관련 WikiTree 메모\n### [01_Events/x.md]\n본문",
    }
    p = DE._build_agent_prompt("bull", ctx)
    assert "## 주요 인과 경로" in p
    assert "## 관련 WikiTree 메모" in p
    assert "분석 지시 (필수)" in p
    assert "전파경로" in p


def test_synthesis_prompt_includes_graph_block_and_directive():
    """synthesis Step1 prompt 내부 점검 — _synthesize_debate 함수 소스에 강제 문구 존재."""
    import inspect
    from market_research.report import debate_engine as DE
    src = inspect.getsource(DE._synthesize_debate)
    # 인과경로 활용 강제 문구 존재
    assert "이벤트 → 지표 → 자산군 연결" in src
    # graph_block / wiki_block 주입
    assert "graph_paths_text" in src
    assert "wiki_context_text" in src


# ─────────────────────────────────────────────────────────────────────
# Client endpoint 누출 회귀 (P3 추가 — _debug_trace 미노출)
# ─────────────────────────────────────────────────────────────────────

def test_client_no_debug_trace_leak(client, tmp_path, monkeypatch):
    """_debug_trace 또는 graph/wiki internal 키가 client 응답에 노출되지 않는지."""
    from market_research.report import report_store
    from api.services import report_service
    import json as _json

    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)

    def _empty_macro(keys=None, start_date=None):
        from api.schemas.macro import MacroTimeseriesResponseDTO
        from api.schemas.meta import BaseMeta
        from datetime import datetime, timezone
        return MacroTimeseriesResponseDTO(
            meta=BaseMeta(as_of_date=None, source="mock", sources=[],
                          is_fallback=True, warnings=["test stub"],
                          generated_at=datetime.now(timezone.utc)),
            series=[],
        )
    monkeypatch.setattr(report_service.macro_service,
                        "build_macro_timeseries", _empty_macro)

    # Synthetic final + draft with _debug_trace + graph/wiki internal keys
    final_payload = {
        "fund_code": "_market", "period": "2026-04",
        "status": "approved", "approved": True,
        "approved_at": "2026-04-30T14:00:45",
        "approved_debate_run_id": "RID-P3-1",
        "generated_at": "2026-04-30T13:56:04",
        "final_comment": "comment",
        "evidence_annotations": [], "related_news": [],
    }
    draft_payload = {
        "fund_code": "_market", "period": "2026-04",
        "status": "approved",
        "draft_comment": "draft",
        "debate_run_id": "RID-P3-1",
        "generated_at": "2026-04-30T13:56:04",
        # P3: 이런 키들이 draft 에 들어와도 client 에는 절대 노출 금지
        "_debug_trace": {"graph_paths_used_count": 8},
        "_graph_trace": {"selected_path_count": 8},
        "_wiki_trace": {"wiki_context_chars": 1234},
    }
    fp = root / "2026-04"
    fp.mkdir(parents=True, exist_ok=True)
    (fp / "_market.final.json").write_text(
        _json.dumps(final_payload, ensure_ascii=False), encoding="utf-8")
    (fp / "_market.draft.json").write_text(
        _json.dumps(draft_payload, ensure_ascii=False), encoding="utf-8")

    r = client.get("/api/market-report", params={"period": "2026-04"})
    assert r.status_code == 200
    raw = r.text
    forbidden = (
        "_debug_trace", "_graph_trace", "_wiki_trace",
        "graph_paths_used", "wiki_context_pages",
        "wiki_retrieval_keywords", "selected_path_labels",
    )
    leaks = [k for k in forbidden if k in raw]
    assert leaks == [], f"forbidden keys leaked: {leaks}"
