"""R4: Comment Trace / Graph Seed generator.

운용보고 코멘트의 source attribution + graph_seed 생성. LLM 호출 0,
report_output 무수정. machine-readable JSON 으로 코멘트가 어떤 근거 묶음으로
작성됐는지 추적.

Use:
    python tools/comment_trace.py --period 2026-Q1 --fund 08N81
    python tools/comment_trace.py --period 2026-Q1 --fund 08N81 \
        --market-source debug_incidents
    python tools/comment_trace.py --period 2026-Q1 --fund 08N81 \
        --market-source path \
        --market-source-path debug/incidents/_market.2026-Q1.fresh-xxx.json

출력: debug/comment_trace/{period}/{fund}.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ──────────────────────────────────────────────────────────────────
# Schema 상수
# ──────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0.0"
TOOL_VERSION = "comment_trace v1 (R4, 2026-05-06)"

NODE_TYPES = (
    "comment", "comment_section", "market_source", "evidence",
    "wiki_page", "asset_class", "fund", "metric", "warning",
)
EDGE_TYPES = (
    "comment_has_section", "section_uses_market_source",
    "section_uses_evidence", "section_uses_wiki",
    "section_mentions_asset", "section_uses_metric",
    "fund_has_metric", "warning_applies_to_section",
)

ASSET_CLASSES = (
    "국내주식", "해외주식", "국내채권", "해외채권",
    "환율", "FX", "금/대체", "대체", "크레딧", "현금성",
)

REPORT_OUTPUT_DIR = PROJECT_ROOT / "market_research" / "data" / "report_output"
INCIDENTS_DIR = PROJECT_ROOT / "debug" / "incidents"
TRACE_OUT_DIR = PROJECT_ROOT / "debug" / "comment_trace"

SECTION_HEADER_RE = re.compile(r"^■\s+(.+)$", re.MULTILINE)
REF_RE = re.compile(r"\[ref:(\d+)\]")
SLUG_NONWORD_RE = re.compile(r"\W+")


# ──────────────────────────────────────────────────────────────────
# 1. Source 검색
# ──────────────────────────────────────────────────────────────────

def load_fund_draft(period: str, fund_code: str) -> tuple[dict | None, dict]:
    """fund draft 로드. report_source meta 함께."""
    fp = REPORT_OUTPUT_DIR / period / f"{fund_code}.draft.json"
    meta = {
        "path": str(fp.relative_to(PROJECT_ROOT)) if fp.exists() else str(fp),
        "exists": fp.exists(),
        "mtime": None,
        "schema_detected": None,
    }
    if not fp.exists():
        return None, meta
    meta["mtime"] = datetime.fromtimestamp(fp.stat().st_mtime,
                                              tz=timezone.utc).isoformat()
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except Exception as e:
        meta["schema_detected"] = f"parse_error: {e}"
        return None, meta
    # schema 감지
    if "draft_comment" in data and "data_snapshot" in data:
        meta["schema_detected"] = "fund_draft"
    elif "synthesis" in data:
        meta["schema_detected"] = "market_debate"
    else:
        meta["schema_detected"] = "unknown"
    return data, meta


def find_market_source(period: str, fund_draft: dict | None,
                        mode: str = "auto",
                        explicit_path: str | None = None) -> tuple[dict | None, dict]:
    """market source 파일 검색.

    Returns: (loaded_data, meta)
    meta: {kind, path, matched_by, confidence, exists}

    매칭 우선순위:
      1. mode='path' + explicit_path → 직접 사용
      2. mode in ('auto','debug_incidents') →
         debug/incidents/_market.{period}.fresh-*.json 중
         debate_run_id 매칭(high) → period 매칭(medium)
      3. mode in ('auto','report_output') →
         report_output/{period}/_market.draft.json (low — P1.5 이전 stale 가능)
      4. 없음 → kind='none'
    """
    debate_run_id = (fund_draft or {}).get("debate_run_id")

    # 1. explicit path
    if mode == "path" and explicit_path:
        p = Path(explicit_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        meta = {
            "kind": "explicit_path",
            "path": str(p.relative_to(PROJECT_ROOT))
                    if p.is_relative_to(PROJECT_ROOT) else str(p),
            "matched_by": "explicit_path",
            "confidence": "high" if p.exists() else "none",
            "exists": p.exists(),
        }
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")), meta
            except Exception:
                pass
        return None, meta

    # 2. debug/incidents
    if mode in ("auto", "debug_incidents") and INCIDENTS_DIR.exists():
        candidates = sorted(INCIDENTS_DIR.glob(f"_market.{period}.fresh-*.json"))
        # 2a. debate_run_id high match
        for fp in candidates:
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if debate_run_id and data.get("debate_run_id") == debate_run_id:
                return data, {
                    "kind": "debug_incidents",
                    "path": str(fp.relative_to(PROJECT_ROOT)),
                    "matched_by": "debate_run_id",
                    "confidence": "high",
                    "exists": True,
                }
        # 2b. period match medium
        if candidates:
            fp = candidates[-1]  # 최신
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                data = None
            if data is not None:
                return data, {
                    "kind": "debug_incidents",
                    "path": str(fp.relative_to(PROJECT_ROOT)),
                    "matched_by": "period_fallback",
                    "confidence": "medium",
                    "exists": True,
                }

    # 3. report_output
    if mode in ("auto", "report_output"):
        fp = REPORT_OUTPUT_DIR / period / "_market.draft.json"
        if fp.exists():
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                return data, {
                    "kind": "report_output",
                    "path": str(fp.relative_to(PROJECT_ROOT)),
                    "matched_by": "period_fallback",
                    "confidence": "low",
                    "exists": True,
                }
            except Exception:
                pass

    # 4. none
    return None, {
        "kind": "none",
        "path": None,
        "matched_by": "none",
        "confidence": "none",
        "exists": False,
    }


# ──────────────────────────────────────────────────────────────────
# 2. Section split + attribution
# ──────────────────────────────────────────────────────────────────

def split_sections(comment_text: str) -> list[dict]:
    """■ 헤더 기준 분할. 헤더 없으면 single section."""
    matches = list(SECTION_HEADER_RE.finditer(comment_text))
    if not matches:
        return [{
            "section_id": "00_main",
            "section_title": "본문",
            "char_range": [0, len(comment_text)],
            "text": comment_text,
        }]
    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(comment_text)
        title = m.group(1).strip()
        slug = SLUG_NONWORD_RE.sub("_", title)[:40].strip("_")
        if not slug:
            slug = f"section_{i}"
        sections.append({
            "section_id": f"{i:02d}_{slug}",
            "section_title": title,
            "char_range": [start, end],
            "text": comment_text[start:end],
        })
    return sections


def attribute_section(section: dict,
                       evidence_annotations: list[dict],
                       market_source_data: dict | None,
                       fund_draft: dict) -> dict:
    """section 내용 분석 → ref_ids / evidence_ids / asset / metric / warnings."""
    text = section["text"]
    ref_ids = sorted({int(m.group(1)) for m in REF_RE.finditer(text)})
    asset_classes = [ac for ac in ASSET_CLASSES if ac in text]
    warnings: list[str] = []

    # evidence_ids 매핑
    evidence_ids: list[str] = []
    if ref_ids:
        method = "explicit_ref"
        ann_map = {a.get("ref"): a for a in (evidence_annotations or [])
                   if a.get("ref") is not None}
        for r in ref_ids:
            ann = ann_map.get(r)
            if ann and ann.get("article_id"):
                evidence_ids.append(ann["article_id"])
            else:
                warnings.append(f"ref:{r} not in evidence_annotations")
    else:
        method = "section_default"
        warnings.append("No explicit [ref:N] tokens found; "
                        "used section-level attribution (not sentence-level)")
        # section_default — 모든 evidence 를 section-level 로 attribute
        # over-attribution 위험: 가이드 명시 — sentence 단정 X
        if evidence_annotations:
            evidence_ids = [a.get("article_id") for a in evidence_annotations
                            if a.get("article_id")]

    # fund_data_keys (data_snapshot 에 채워진 항목)
    data_snapshot = fund_draft.get("data_snapshot") or {}
    fund_data_keys: list[str] = []
    if data_snapshot.get("fund_return") is not None:
        fund_data_keys.append("fund_return")
    if data_snapshot.get("pa_classes") or data_snapshot.get("pa_by_class"):
        fund_data_keys.append("pa_by_class")
    if data_snapshot.get("holdings_top3"):
        fund_data_keys.append("holdings_top3")
    if data_snapshot.get("trades"):
        fund_data_keys.append("trades")
    if data_snapshot.get("bm_count"):
        fund_data_keys.append("bm")

    # wiki_pages (market_source 의 _debug_trace 에서)
    wiki_pages: list[str] = []
    if market_source_data:
        ms_trace = market_source_data.get("_debug_trace") or {}
        wiki_pages = list(ms_trace.get("wiki_context_pages") or [])

    return {
        "section_id": section["section_id"],
        "section_title": section["section_title"],
        "char_range": section["char_range"],
        "attribution_method": method,
        "ref_ids": ref_ids,
        "evidence_ids": evidence_ids,
        "wiki_pages": wiki_pages,
        "asset_classes_mentioned": asset_classes,
        "fund_data_keys": fund_data_keys,
        "warnings": warnings,
    }


# ──────────────────────────────────────────────────────────────────
# 3. Graph seed
# ──────────────────────────────────────────────────────────────────

def build_graph_seed(fund_code: str, period: str, attributions: list[dict],
                      evidence_annotations: list[dict],
                      market_source_meta: dict, fund_draft: dict) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    node_index: set[str] = set()

    def _add_node(node: dict) -> None:
        nid = node["id"]
        if nid in node_index:
            return
        node_index.add(nid)
        nodes.append(node)

    # comment 노드
    comment_id = f"comment:{fund_code}@{period}"
    _add_node({"id": comment_id, "type": "comment",
               "fund_code": fund_code, "period": period,
               "label": f"{fund_code} {period}"})

    # fund 노드
    fund_node_id = f"fund:{fund_code}"
    _add_node({"id": fund_node_id, "type": "fund",
               "fund_code": fund_code, "label": fund_code})

    # market_source 노드
    ms_id: str | None = None
    if market_source_meta.get("kind") != "none":
        ms_id = f"market_source:{market_source_meta['kind']}"
        _add_node({
            "id": ms_id, "type": "market_source",
            "kind": market_source_meta.get("kind"),
            "path": market_source_meta.get("path"),
            "matched_by": market_source_meta.get("matched_by"),
            "confidence": market_source_meta.get("confidence"),
            "label": f"market:{market_source_meta.get('kind')}",
        })

    # evidence_annotations 의 ref → article_id 매핑 (sample 메타 우선)
    ann_by_aid = {a.get("article_id"): a for a in (evidence_annotations or [])
                  if a.get("article_id")}

    for attr in attributions:
        sid = f"section:{fund_code}@{period}:{attr['section_id']}"
        _add_node({
            "id": sid, "type": "comment_section",
            "section_id": attr["section_id"],
            "title": attr["section_title"],
            "attribution_method": attr["attribution_method"],
            "label": attr["section_title"],
        })
        edges.append({"from": comment_id, "to": sid,
                      "type": "comment_has_section"})
        if ms_id:
            edges.append({"from": sid, "to": ms_id,
                          "type": "section_uses_market_source"})
        # evidence
        for eid in attr["evidence_ids"]:
            ev_id = f"evidence:{eid}"
            ann = ann_by_aid.get(eid) or {}
            _add_node({
                "id": ev_id, "type": "evidence",
                "article_id": eid,
                "title": (ann.get("title") or "")[:80],
                "date": ann.get("date") or "",
                "source": ann.get("source") or "",
                "label": (ann.get("title") or eid)[:50],
            })
            edges.append({"from": sid, "to": ev_id,
                          "type": "section_uses_evidence"})
        # wiki
        for wp in attr["wiki_pages"]:
            wp_id = f"wiki:{wp}"
            _add_node({"id": wp_id, "type": "wiki_page",
                       "path": wp,
                       "label": wp.split("/")[-1] if "/" in wp else wp})
            edges.append({"from": sid, "to": wp_id,
                          "type": "section_uses_wiki"})
        # asset
        for ac in attr["asset_classes_mentioned"]:
            ac_id = f"asset:{ac}"
            _add_node({"id": ac_id, "type": "asset_class", "label": ac})
            edges.append({"from": sid, "to": ac_id,
                          "type": "section_mentions_asset"})
        # metric
        for fk in attr["fund_data_keys"]:
            mt_id = f"metric:{fund_code}:{fk}"
            if mt_id not in node_index:
                _add_node({"id": mt_id, "type": "metric",
                           "fund_code": fund_code, "metric_key": fk,
                           "label": f"{fund_code}.{fk}"})
                edges.append({"from": fund_node_id, "to": mt_id,
                              "type": "fund_has_metric"})
            edges.append({"from": sid, "to": mt_id,
                          "type": "section_uses_metric"})
        # warnings
        for i, w in enumerate(attr["warnings"]):
            w_id = f"warning:{sid}:{i}"
            _add_node({"id": w_id, "type": "warning",
                       "message": w, "label": "warning"})
            edges.append({"from": w_id, "to": sid,
                          "type": "warning_applies_to_section"})

    return {"nodes": nodes, "edges": edges}


# ──────────────────────────────────────────────────────────────────
# 4. trace 빌드
# ──────────────────────────────────────────────────────────────────

def build_trace(period: str, fund_code: str,
                 market_source_mode: str = "auto",
                 market_source_path: str | None = None) -> dict:
    fund_draft, report_source_meta = load_fund_draft(period, fund_code)

    top_warnings: list[str] = []
    top_errors: list[str] = []

    if not fund_draft:
        top_errors.append(
            f"fund draft not found at {report_source_meta.get('path')}"
        )
        # 빈 trace 라도 생성
        fund_draft = {}

    market_source_data, market_source_meta = find_market_source(
        period, fund_draft, mode=market_source_mode,
        explicit_path=market_source_path,
    )

    if market_source_meta["kind"] == "none":
        top_warnings.append("no market source found — graph_seed without market_source")

    # 08N81 한계 감지 (Q-FIX-2 이전 draft)
    data_snapshot = fund_draft.get("data_snapshot") or {}
    if data_snapshot.get("fund_return") is None:
        top_warnings.append("data_snapshot.fund_return is None "
                            "(Q-FIX-2 이전 draft 또는 PA 빈 dict)")
    if not (data_snapshot.get("pa_by_class") or data_snapshot.get("pa_classes")):
        top_warnings.append("data_snapshot.pa_by_class / pa_classes 비어있음")
    if not data_snapshot.get("holdings_top3"):
        top_warnings.append("data_snapshot.holdings_top3 비어있음")

    # evidence_annotations 결정 — fund draft 우선, 없으면 market_source 보강
    evidence_annotations = fund_draft.get("evidence_annotations") or []
    if not evidence_annotations and market_source_data:
        evidence_annotations = market_source_data.get("evidence_annotations") or []
        if evidence_annotations:
            top_warnings.append(
                "evidence_annotations sourced from market_source "
                "(fund draft 에는 없음)"
            )
        else:
            # Q-FIX-1 이전 quarterly debate 산출물은 _evidence_ids 만 있고
            # evidence_annotations 가 없을 수 있음. build_evidence_annotations 로
            # 합성 시도 (LLM 호출 0, 디스크 read 만).
            raw_eids = market_source_data.get("_evidence_ids") or []
            if raw_eids:
                try:
                    from market_research.report.debate_service import (
                        build_evidence_annotations,
                    )
                    yr = market_source_data.get("year")
                    months_in = market_source_data.get("months")
                    if yr is None:
                        yr = int(period[:4])
                    if not months_in:
                        if "Q" in period:
                            q = int(period[-1])
                            months_in = [(q - 1) * 3 + i for i in (1, 2, 3)]
                        else:
                            months_in = [int(period.split("-")[1])]
                    evidence_annotations = build_evidence_annotations(
                        raw_eids, yr, months_in,
                    )
                    if evidence_annotations:
                        top_warnings.append(
                            f"evidence_annotations synthesized from "
                            f"market_source._evidence_ids ({len(raw_eids)} ids, "
                            f"{len(evidence_annotations)} annotations)"
                        )
                except Exception as exc:
                    top_warnings.append(
                        f"failed to synthesize evidence_annotations: {exc}"
                    )
    if not evidence_annotations:
        top_warnings.append("evidence_annotations 부재 (fund + market_source 모두)")

    # comment 본문 — R6-A: draft_comment_raw 우선 ([ref:N] 보존),
    # 없으면 legacy draft_comment (이미 sanitized 일 수도 / 원문일 수도)
    comment_text = (fund_draft.get("draft_comment_raw")
                    or fund_draft.get("draft_comment") or "")

    # section split + attribution
    sections = split_sections(comment_text)
    attributions = [
        attribute_section(s, evidence_annotations,
                          market_source_data, fund_draft)
        for s in sections
    ]

    method_summary: dict[str, int] = {"explicit_ref": 0, "section_default": 0}
    for a in attributions:
        method_summary[a["attribution_method"]] = (
            method_summary.get(a["attribution_method"], 0) + 1
        )

    # R6-A: draft 에 citation_validation 이 있으면 trace 에 surface (관측용)
    citation_validation = fund_draft.get("citation_validation") or None

    graph_seed = build_graph_seed(
        fund_code, period, attributions, evidence_annotations,
        market_source_meta, fund_draft,
    )

    trace_id = f"comment_trace:{fund_code}@{period}"
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "trace_id": trace_id,
        "report_id": f"{fund_code}@{period}",
        "fund_code": fund_code,
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_source": report_source_meta,
        "market_source": market_source_meta,
        "attribution_level": "section",
        "attribution_method_summary": method_summary,
        "citation_validation": citation_validation,
        "sources": {
            "evidence_annotations": evidence_annotations,
            "pinned_fund_context": (fund_draft.get("inputs_used") or {}).get(
                "pinned_fund_context") if isinstance(fund_draft.get("inputs_used"),
                                                       dict) else None,
            "data_snapshot": data_snapshot,
            "wiki_pages_selected": (
                (market_source_data or {}).get("_debug_trace", {}) or {}
            ).get("wiki_context_pages", []),
            "pa_classes": (data_snapshot.get("pa_classes") or
                            list((data_snapshot.get("pa_by_class") or {}).keys())),
            "holdings_top3": data_snapshot.get("holdings_top3") or [],
        },
        "section_attribution": attributions,
        "graph_seed": graph_seed,
        "warnings": top_warnings,
        "errors": top_errors,
    }


# ──────────────────────────────────────────────────────────────────
# 5. CLI
# ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Comment trace / graph seed generator (R4)"
    )
    ap.add_argument("--period", required=True, help="2026-Q1 or 2026-04")
    ap.add_argument("--fund", required=True, help="08N81")
    ap.add_argument("--market-source",
                     choices=("auto", "report_output", "debug_incidents", "path"),
                     default="auto")
    ap.add_argument("--market-source-path", default=None)
    ap.add_argument("--output", "-o", default=None,
                     help="출력 path. 기본 debug/comment_trace/{period}/{fund}.json")
    args = ap.parse_args()

    trace = build_trace(
        args.period, args.fund,
        market_source_mode=args.market_source,
        market_source_path=args.market_source_path,
    )

    out_path = (Path(args.output) if args.output
                else TRACE_OUT_DIR / args.period / f"{args.fund}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(trace, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"[ok] trace written to {out_path}")
    g = trace["graph_seed"]
    print(f"     trace_id={trace['trace_id']}")
    print(f"     market_source: kind={trace['market_source']['kind']} "
          f"matched_by={trace['market_source']['matched_by']} "
          f"confidence={trace['market_source']['confidence']}")
    print(f"     sections={len(trace['section_attribution'])} "
          f"method_summary={trace['attribution_method_summary']}")
    print(f"     graph: nodes={len(g['nodes'])} edges={len(g['edges'])}")
    print(f"     warnings={len(trace['warnings'])} errors={len(trace['errors'])}")


if __name__ == "__main__":
    main()
