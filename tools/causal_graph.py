"""R7: Evidence Causal Graph / Narrative Decomposition.

LLM 호출 0. 디스크 read 만 (외부 news json 옵션). report_output 무수정.

기존 R4 graph_seed (provenance: section→evidence) 와는 별개로
evidence 내용을 claim/event/macro/asset 단위로 분해하고 인과 path 를 합성한다.

build_causal_layer(evidence_annotations, attributions, fund_code, period) →
{
    "evidence_contents": [...],   # R7-a
    "causal_claims":     [...],   # R7-b
    "causal_paths":      [...],   # R7-d
    "graph_seed_causal": {        # R7-c
        "nodes": [...],
        "edges": [...],
    },
    "warnings": [...],
}

comment_trace.build_trace 가 호출하여 trace JSON 에 attach.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────────────────────────
# Schema 상수
# ──────────────────────────────────────────────────────────────────

CAUSAL_SCHEMA_VERSION = "r7-1.0.0"

NODE_TYPES = (
    "event", "macro_factor", "asset_class", "fund",
    "evidence", "comment_section", "claim", "path", "risk", "view",
)
EDGE_TYPES = (
    "evidence_supports_claim",
    "claim_mentions_event",
    "claim_mentions_macro",
    "claim_mentions_asset",
    "event_raises_macro",
    "event_lowers_macro",
    "macro_pressures_asset",
    "macro_supports_asset",
    "asset_affects_fund",
    "section_uses_claim",
    "section_uses_causal_path",
    "path_includes_node",
    "path_supported_by_evidence",
)

# ──────────────────────────────────────────────────────────────────
# Topic taxonomy (rule-based)
# ──────────────────────────────────────────────────────────────────

# topic_id → (kind, label)
TOPIC_DEFS: dict[str, tuple[str, str]] = {
    "event:geopolitical":          ("event", "지정학 리스크"),
    "event:wgbi":                  ("event", "WGBI 편입"),
    "macro:oil_price":             ("macro", "유가"),
    "macro:inflation":             ("macro", "인플레이션"),
    "macro:interest_rate":         ("macro", "금리"),
    "macro:fx_usdkrw":             ("macro", "환율(USDKRW)"),
    "asset:us_growth_stock":       ("asset", "미국 성장주"),
    "asset:domestic_bond":         ("asset", "국내채권"),
    "asset:gold":                  ("asset", "금"),
    "asset:overseas_translation":  ("asset", "해외자산 환산"),
}

# 키워드 → topic. 한국어는 단어 ≥ 2자 phrase, 영문은 \b 경계 (re.ASCII).
# evidence_annotations 의 topic / all_topics 한국어 코드도 매칭에 활용.
TOPIC_RULES: list[tuple[str, list[str]]] = [
    ("event:geopolitical",
     ["이란", "중동", "전쟁", "지정학", "분쟁", "휴전", "Iran", "Middle East",
      "geopolitical", "war"]),
    ("event:wgbi",
     ["WGBI", "외국인 수급", "국채 편입", "FTSE Russell", "지수 편입",
      "외국인 채권"]),
    ("macro:oil_price",
     ["유가", "WTI", "원유", "브렌트", "Brent", "crude oil"]),
    ("macro:inflation",
     ["인플레이션", "물가", "CPI", "inflation", "디스인플레이션"]),
    ("macro:interest_rate",
     ["금리", "국채", "듀레이션", "Fed", "FOMC", "기준금리", "yield",
      "rate hike", "rate cut", "통화정책"]),
    ("macro:fx_usdkrw",
     ["환율", "원달러", "달러원", "USDKRW", "환율_FX"]),
    ("asset:us_growth_stock",
     ["성장주", "AI", "빅테크", "나스닥", "Nasdaq", "growth stock",
      "엔비디아", "Nvidia", "M7", "테크주"]),
    ("asset:domestic_bond",
     ["국내채권", "한국 국채", "한국채권", "한국 채권", "국고채",
      "domestic bond"]),
    ("asset:gold",
     ["금 가격", "금 시세", "안전자산", "Gold", "gold", "금값", "골드"]),
    ("asset:overseas_translation",
     ["환산손익", "환차손", "환산", "translation"]),
]

# ──────────────────────────────────────────────────────────────────
# Causal templates (topic → topic 인과 edge)
# ──────────────────────────────────────────────────────────────────

CAUSAL_TEMPLATES: list[tuple[str, str, str]] = [
    ("event:geopolitical",   "macro:oil_price",       "event_raises_macro"),
    ("macro:oil_price",      "macro:inflation",       "event_raises_macro"),
    ("macro:inflation",      "macro:interest_rate",   "event_raises_macro"),
    ("macro:interest_rate",  "asset:us_growth_stock", "macro_pressures_asset"),
    ("macro:interest_rate",  "asset:domestic_bond",   "macro_pressures_asset"),
    ("event:wgbi",           "asset:domestic_bond",   "macro_supports_asset"),
    ("macro:fx_usdkrw",      "asset:overseas_translation",
                                                       "macro_pressures_asset"),
]

# ──────────────────────────────────────────────────────────────────
# Path templates (chain — 합성 후 supporting evidence 매칭)
# ──────────────────────────────────────────────────────────────────

PATH_TEMPLATES: list[dict[str, Any]] = [
    {
        "path_id": "geopolitical_oil_inflation_rates_growth",
        "label": "지정학 → 유가 → 인플레이션 → 금리 → 성장주",
        "chain": ["event:geopolitical", "macro:oil_price",
                  "macro:inflation", "macro:interest_rate",
                  "asset:us_growth_stock"],
    },
    {
        "path_id": "wgbi_domestic_bond_inflow",
        "label": "WGBI → 외국인 수급 → 국내채권",
        "chain": ["event:wgbi", "asset:domestic_bond"],
    },
    {
        "path_id": "fx_translation_overseas_assets",
        "label": "환율 → 해외자산 환산",
        "chain": ["macro:fx_usdkrw", "asset:overseas_translation"],
    },
    {
        "path_id": "gold_hedge_volatility",
        "label": "금 → 안전자산 헤지",
        "chain": ["asset:gold"],
    },
    {
        "path_id": "rates_domestic_bond",
        "label": "금리 → 국내채권",
        "chain": ["macro:interest_rate", "asset:domestic_bond"],
    },
]


# ──────────────────────────────────────────────────────────────────
# R7-a: Evidence content loader
# ──────────────────────────────────────────────────────────────────

def _is_korean(s: str) -> bool:
    return bool(re.search(r"[가-힣]", s))


def _kw_in_text(kw: str, text: str) -> bool:
    """Korean phrase: substring 매칭 (≥ 2자만 허용 — 외부 호출자가 보장).
    영문: \\b 경계 + re.ASCII (한국어 조사 결합 방지)."""
    if _is_korean(kw):
        return kw in text
    pat = r"\b" + re.escape(kw) + r"\b"
    return bool(re.search(pat, text, flags=re.IGNORECASE | re.ASCII))


def load_evidence_content(
    evidence_annotations: list[dict],
    linked_section_map: dict[str, list[str]] | None = None,
    news_dir: Path | None = None,
) -> tuple[list[dict], list[str]]:
    """evidence_annotations → 정규화 content list + warnings.

    Priority:
      1. annotation 의 title / source / date / topic 사용 (충분한 경우 대부분)
      2. (옵션) news_dir 의 월별 json 에서 article_id 매칭 → description 보강
      3. body/summary 부재 시 warning 1건

    Parameters
    ----------
    evidence_annotations : list[{ref, article_id, title, source, date, topic, all_topics, salience, ...}]
    linked_section_map   : article_id → [section_id, ...]
    news_dir             : Optional[Path]  market_research/data/news/  (월별 json)

    Returns
    -------
    (contents, warnings)
        contents = [{evidence_id, ref, title, source, date, month, topic, all_topics,
                     summary, has_body, linked_sections, salience}, ...]
    """
    contents: list[dict] = []
    warnings: list[str] = []
    linked_section_map = linked_section_map or {}

    # 월별 news json lazy 로드 캐시
    news_cache: dict[str, dict[str, dict]] = {}  # month → {article_id: article}

    def _load_news_month(month: str) -> dict[str, dict]:
        if news_dir is None:
            return {}
        if month in news_cache:
            return news_cache[month]
        idx: dict[str, dict] = {}
        fp = news_dir / f"{month}.json"
        if fp.exists():
            try:
                d = json.loads(fp.read_text(encoding="utf-8"))
                arts = d.get("articles") if isinstance(d, dict) else d
                if isinstance(arts, list):
                    for a in arts:
                        aid = a.get("_article_id") or a.get("article_id")
                        if aid:
                            idx[aid] = a
            except Exception:
                pass
        news_cache[month] = idx
        return idx

    for ea in evidence_annotations or []:
        aid = ea.get("article_id")
        if not aid:
            warnings.append(f"evidence ref={ea.get('ref')} missing article_id")
            continue
        title = (ea.get("title") or "").strip()
        source = ea.get("source") or ""
        date = ea.get("date") or ""
        month = date[:7] if isinstance(date, str) and len(date) >= 7 else ""
        topic = ea.get("topic") or ""
        all_topics = ea.get("all_topics") or ([topic] if topic else [])

        # body/summary 보강 시도
        summary = ""
        has_body = False
        if month and news_dir is not None:
            idx = _load_news_month(month)
            art = idx.get(aid)
            if art:
                desc = (art.get("description") or "").strip()
                if desc:
                    summary = desc[:600]
                    has_body = True
        if not has_body and not title:
            warnings.append(f"evidence {aid} has neither title nor body")

        contents.append({
            "evidence_id": aid,
            "ref": ea.get("ref"),
            "title": title,
            "source": source,
            "date": date,
            "month": month,
            "topic": topic,
            "all_topics": all_topics,
            "summary": summary,
            "has_body": has_body,
            "linked_sections": list(linked_section_map.get(aid, [])),
            "salience": ea.get("salience"),
        })

    return contents, warnings


# ──────────────────────────────────────────────────────────────────
# R7-b: Claim extraction (rule-based)
# ──────────────────────────────────────────────────────────────────

def _hit_topics(text: str) -> list[str]:
    """text 에서 hit 되는 topic_id 수집 (중복 제거, 등장 순)."""
    if not text:
        return []
    hits: list[str] = []
    seen: set[str] = set()
    for topic_id, kws in TOPIC_RULES:
        for kw in kws:
            if _kw_in_text(kw, text):
                if topic_id not in seen:
                    hits.append(topic_id)
                    seen.add(topic_id)
                break
    return hits


def _classify_claim_type(topics: list[str]) -> str:
    has_event = any(t.startswith("event:") for t in topics)
    has_macro = any(t.startswith("macro:") for t in topics)
    has_asset = any(t.startswith("asset:") for t in topics)
    if has_event and has_macro:
        return "event_to_macro"
    if has_macro and has_asset:
        return "macro_to_asset"
    if has_asset and not has_macro:
        return "asset_to_fund"
    if has_macro and not has_asset:
        return "outlook_view"
    if has_event and not has_macro:
        return "risk"
    return "outlook_view"


def extract_claims(
    contents: list[dict],
    fund_code: str,
    period: str,
) -> tuple[list[dict], list[str]]:
    """contents → list[claim] + warnings.

    rule-based: title + topic + all_topics + summary 를 매칭 텍스트로 사용.
    """
    claims: list[dict] = []
    warnings: list[str] = []
    for idx, c in enumerate(contents):
        match_text = " ".join([
            c.get("title") or "",
            c.get("topic") or "",
            " ".join(c.get("all_topics") or []),
            c.get("summary") or "",
        ])
        topics = _hit_topics(match_text)
        if not topics:
            warnings.append(
                f"evidence {c['evidence_id']} no topic matched "
                f"(title={c['title'][:40]!r})"
            )
            continue
        macro = [t for t in topics if t.startswith("macro:")]
        asset = [t for t in topics if t.startswith("asset:")]
        events = [t for t in topics if t.startswith("event:")]
        claim_type = _classify_claim_type(topics)
        # confidence heuristic: hit topic 수에 비례, 0.5~0.9 범위
        conf = min(0.5 + 0.1 * len(topics), 0.9)
        claims.append({
            "claim_id": f"claim:{fund_code}@{period}:{idx}",
            "source_evidence_id": c["evidence_id"],
            "claim_text": c.get("title") or c.get("summary") or "",
            "claim_type": claim_type,
            "entities": events,
            "macro_factors": macro,
            "asset_classes": asset,
            "fund_codes": [],
            "direction": "neutral",
            "confidence": round(conf, 2),
            "extraction_method": "rule_based",
            "linked_sections": list(c.get("linked_sections") or []),
        })
    return claims, warnings


# ──────────────────────────────────────────────────────────────────
# R7-c: Causal edge builder
# ──────────────────────────────────────────────────────────────────

def build_causal_edges(claims: list[dict]) -> list[dict]:
    """claims 의 topic 등장 기반으로 template edge 활성화.

    한 template (src, dst, type) 이 활성화되려면 claims 전체에서 src 와 dst
    각각 ≥ 1 회 mention 되어야 함.
    """
    seen: set[str] = set()
    for c in claims:
        for t in (list(c.get("entities") or []) + list(c.get("macro_factors") or [])
                   + list(c.get("asset_classes") or [])):
            seen.add(t)
    edges: list[dict] = []
    for src, dst, etype in CAUSAL_TEMPLATES:
        if src in seen and dst in seen:
            edges.append({"from": src, "to": dst, "type": etype,
                          "source": "template"})
    return edges


# ──────────────────────────────────────────────────────────────────
# R7-d: Path aggregation
# ──────────────────────────────────────────────────────────────────

def _topics_of_claim(c: dict) -> set[str]:
    return set((c.get("entities") or []) + (c.get("macro_factors") or [])
                + (c.get("asset_classes") or []))


def aggregate_paths(claims: list[dict]) -> list[dict]:
    """PATH_TEMPLATES 와 claims 매칭 → 활성 path 합성.

    한 template path 에 대해 chain 의 어느 노드라도 cover 하는 claim 이
    있으면 path 활성. confidence = covered / chain_length.
    supporting_evidence_ids = chain 의 어느 노드라도 cover 한 claim 의
    source_evidence_id. linked_sections = 그런 claim 의 linked_sections union.
    """
    out: list[dict] = []
    for tpl in PATH_TEMPLATES:
        chain = tpl["chain"]
        covered: set[str] = set()
        supports: list[str] = []
        seen_ev: set[str] = set()
        sections: set[str] = set()
        for c in claims:
            ts = _topics_of_claim(c)
            chain_hits = ts & set(chain)
            if not chain_hits:
                continue
            covered |= chain_hits
            ev = c.get("source_evidence_id")
            if ev and ev not in seen_ev:
                supports.append(ev)
                seen_ev.add(ev)
            for s in c.get("linked_sections") or []:
                sections.add(s)
        if not covered:
            continue
        conf = round(len(covered) / max(1, len(chain)), 2)
        out.append({
            "path_id": tpl["path_id"],
            "label": tpl["label"],
            "chain": list(chain),
            "covered_chain_nodes": sorted(covered),
            "supporting_evidence_ids": supports,
            "linked_sections": sorted(sections),
            "confidence": conf,
        })
    return out


# ──────────────────────────────────────────────────────────────────
# R7-c (graph): graph_seed_causal builder
# ──────────────────────────────────────────────────────────────────

def build_graph_seed_causal(
    claims: list[dict],
    causal_edges: list[dict],
    paths: list[dict],
    fund_code: str,
    period: str,
) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()

    def _add(node: dict) -> None:
        nid = node["id"]
        if nid in seen:
            return
        seen.add(nid)
        nodes.append(node)

    # fund 노드
    fund_id = f"fund:{fund_code}"
    _add({"id": fund_id, "type": "fund", "label": fund_code,
          "fund_code": fund_code, "period": period})

    # claim + evidence + topic mention edges
    for c in claims:
        _add({"id": c["claim_id"], "type": "claim",
              "label": (c["claim_text"] or "claim")[:40],
              "claim_type": c["claim_type"],
              "confidence": c["confidence"]})
        ev_id = f"evidence:{c['source_evidence_id']}"
        _add({"id": ev_id, "type": "evidence",
              "article_id": c["source_evidence_id"],
              "label": c["source_evidence_id"][:12]})
        edges.append({"from": ev_id, "to": c["claim_id"],
                      "type": "evidence_supports_claim"})
        for ent in c.get("entities") or []:
            kind, label = TOPIC_DEFS.get(ent, ("event", ent))
            _add({"id": ent, "type": "event", "label": label,
                  "topic_id": ent})
            edges.append({"from": c["claim_id"], "to": ent,
                          "type": "claim_mentions_event"})
        for m in c.get("macro_factors") or []:
            kind, label = TOPIC_DEFS.get(m, ("macro", m))
            _add({"id": m, "type": "macro_factor", "label": label,
                  "topic_id": m})
            edges.append({"from": c["claim_id"], "to": m,
                          "type": "claim_mentions_macro"})
        for a in c.get("asset_classes") or []:
            kind, label = TOPIC_DEFS.get(a, ("asset", a))
            _add({"id": a, "type": "asset_class", "label": label,
                  "topic_id": a})
            edges.append({"from": c["claim_id"], "to": a,
                          "type": "claim_mentions_asset"})
        # section 연결
        for s in c.get("linked_sections") or []:
            sid = f"section:{fund_code}@{period}:{s}"
            _add({"id": sid, "type": "comment_section", "label": s,
                  "section_id": s})
            edges.append({"from": sid, "to": c["claim_id"],
                          "type": "section_uses_claim"})

    # template causal edges (topic → topic)
    for e in causal_edges:
        edges.append({"from": e["from"], "to": e["to"], "type": e["type"]})

    # asset → fund 연결 (활성 asset 만)
    for n in list(nodes):
        if n.get("type") == "asset_class":
            edges.append({"from": n["id"], "to": fund_id,
                          "type": "asset_affects_fund"})

    # path 노드 + path_includes_node + path_supported_by_evidence + section_uses_causal_path
    for p in paths:
        pid = f"path:{p['path_id']}"
        _add({"id": pid, "type": "path", "label": p["label"],
              "confidence": p["confidence"]})
        for ch in p["chain"]:
            if ch in seen:
                edges.append({"from": pid, "to": ch,
                              "type": "path_includes_node"})
        for ev in p["supporting_evidence_ids"]:
            ev_id = f"evidence:{ev}"
            if ev_id in seen:
                edges.append({"from": pid, "to": ev_id,
                              "type": "path_supported_by_evidence"})
        for s in p["linked_sections"]:
            sid = f"section:{fund_code}@{period}:{s}"
            if sid in seen:
                edges.append({"from": sid, "to": pid,
                              "type": "section_uses_causal_path"})

    return {"nodes": nodes, "edges": edges}


# ──────────────────────────────────────────────────────────────────
# Top-level: build_causal_layer
# ──────────────────────────────────────────────────────────────────

def build_causal_layer(
    evidence_annotations: list[dict],
    section_attribution: list[dict],
    fund_code: str,
    period: str,
    news_dir: Path | None = None,
) -> dict:
    """comment_trace.build_trace 가 호출하는 단일 entry.

    Returns:
        {
            "schema_version": "r7-1.0.0",
            "evidence_contents": [...],
            "causal_claims":     [...],
            "causal_paths":      [...],
            "graph_seed_causal": {nodes, edges},
            "warnings":          [...],
        }
    """
    # section_attribution 에서 article_id → [section_id] 매핑
    linked_section_map: dict[str, list[str]] = {}
    for a in section_attribution or []:
        sid = a.get("section_id")
        if not sid:
            continue
        for ev in a.get("evidence_ids") or []:
            linked_section_map.setdefault(ev, []).append(sid)

    contents, w_load = load_evidence_content(
        evidence_annotations or [], linked_section_map, news_dir,
    )
    claims, w_extr = extract_claims(contents, fund_code, period)
    causal_edges = build_causal_edges(claims)
    paths = aggregate_paths(claims)
    graph = build_graph_seed_causal(claims, causal_edges, paths,
                                     fund_code, period)
    warnings = list(w_load) + list(w_extr)
    return {
        "schema_version": CAUSAL_SCHEMA_VERSION,
        "evidence_contents": contents,
        "causal_claims": claims,
        "causal_paths": paths,
        "graph_seed_causal": graph,
        "warnings": warnings,
    }
