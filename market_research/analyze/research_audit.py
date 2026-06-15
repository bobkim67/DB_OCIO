# -*- coding: utf-8 -*-
"""D4 게이트 audit — 09_Research_Synthesis 품질 검증 도구 (P4→P5 전).

wiki_from_naver_research D4. research claim / 09 narrative 의 품질을 자동 검사:
  1. stratified sample (자산군 × stance × horizon, monygeek 별도)
  2. hard fact grounding — claim 수치가 source evidence 에 실재하는지
  3. narrative grounding — 09 §1 narrative 수치가 claim pool 에 실재하는지
  4. auto gate — strength<0.45 directional 금지 / n<10 insufficient /
     monygeek vote 미오염 / unsupported hard fact 카운트

manual 컬럼(manual_asset_class/manual_stance/pass_fail)은 사용자 검수용 공란.
LLM 0 — 순수 분석.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from market_research.analyze.research_aggregator import (
    load_research_claims, aggregate_by_asset,
)
from market_research.analyze.research_consensus import (
    run_research_synthesis, _ASSET_FILE_STEM,
)

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIT_DIR = BASE_DIR / 'debug' / 'research_audit'

# directional signal 로 쓰면 안 되는 conviction 임계 (D4 게이트)
LOW_CONVICTION_STRENGTH = 0.45
MIN_COVERAGE_CLAIMS = 10
MIN_SAMPLE_PER_ASSET = 8
KOSPI_SAMPLE_MIN = 20  # 국내주식 편중 → 더 많이

# hard fact 토큰: 퍼센트 / 지수·금액 레벨(콤마 천단위) / 소수 / bp
_FACT_RE = re.compile(
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"      # 7,981 / 1,234.5 (천단위 콤마)
    r"|\d+\.\d+%?"                          # 149.8 / 3.8%
    r"|\d+%"                                # 55%
    r"|\d+\s?(?:bp|bps|만|억|조|달러)"      # 50bp / 149억
)
# 무의미 토큰(연도·한자리 등) 제외용 — 길이/맥락 필터는 _norm 에서
_TRIVIAL = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "0"}


def extract_hard_facts(text: str) -> list[str]:
    """수치/레벨/퍼센트 hard fact 토큰 추출 (정규화 전 원형)."""
    if not text:
        return []
    out = []
    for m in _FACT_RE.findall(text):
        t = m.strip()
        if not t or t in _TRIVIAL:
            continue
        # 0~1 bare decimal(0.569 등)은 strength/confidence 메트릭 메아리 — 시장 fact 아님
        if re.fullmatch(r"0\.\d+", t):
            continue
        out.append(t)
    return out


def _norm_num(tok: str) -> str:
    """콤마/단위 제거 후 숫자 코어만 (grounding 매칭용)."""
    return re.sub(r"[,\s%]|bp|bps|만|억|조|달러", "", tok)


def _grounded(fact: str, evidence_text: str) -> bool:
    """fact 의 숫자 코어가 evidence 에 (콤마 무시) 존재하는지."""
    core = _norm_num(fact)
    if not core or len(core) < 2:
        return True  # 한 자리 등 trivial 은 통과 처리
    ev = re.sub(r"[,\s]", "", evidence_text or "")
    return core in ev


def _claim_text_blob(claim: dict) -> str:
    return " ".join(str(claim.get(k) or "") for k in
                    ("claim_text", "view", "rationale_text", "risk_factor", "evidence_text"))


def build_evidence_index(month: str) -> dict[str, str]:
    """supporting_evidence_id → source 원문(description) 매핑 (양 레인)."""
    idx: dict[str, str] = {}
    from market_research.collect.naver_research_adapter import load_adapted
    for a in load_adapted(month) or []:
        desc = a.get("description") or ""
        for k in (a.get("_article_id"), a.get("_raw_dedupe_key"), a.get("_raw_nid")):
            if k:
                idx[str(k)] = desc
    from market_research.collect.monygeek_research_adapter import build_monygeek_articles
    for a in build_monygeek_articles(month):
        if a.get("_article_id"):
            idx[a["_article_id"]] = a.get("description") or ""
    return idx


def check_claim_grounding(claim: dict, ev_index: dict[str, str]) -> dict[str, Any]:
    """claim hard fact 가 supporting evidence 에 실재하는지."""
    facts = extract_hard_facts(_claim_text_blob(claim))
    ev = " ".join(ev_index.get(str(e), "")
                  for e in (claim.get("supporting_evidence_ids") or []))
    unsupported = [f for f in facts if not _grounded(f, ev)]
    return {"n_facts": len(facts), "unsupported": unsupported,
            "supported": len(facts) - len(unsupported)}


# ──────────────────────────────────────────────────────────────────
# stratified sample
# ──────────────────────────────────────────────────────────────────

def stratified_sample(claims: list[dict], target: int) -> list[dict]:
    """(stance, horizon) cell round-robin 으로 다양성 보장 샘플."""
    cells: dict[tuple, list[dict]] = {}
    for c in claims:
        key = (c.get("stance"), c.get("horizon"))
        cells.setdefault(key, []).append(c)
    order = sorted(cells.keys(), key=lambda k: -len(cells[k]))
    picked: list[dict] = []
    seen = set()
    while len(picked) < target and any(cells[k] for k in order):
        for k in order:
            if cells[k]:
                c = cells[k].pop(0)
                if c.get("claim_id") not in seen:
                    picked.append(c)
                    seen.add(c.get("claim_id"))
                if len(picked) >= target:
                    break
    return picked


def narrative_grounding(month: str, agg: dict[str, dict]) -> dict[str, dict]:
    """09 §1 narrative 의 hard fact 가 해당 자산 claim pool 에 실재하는지."""
    res = run_research_synthesis(month, use_llm=False, dry_run=True)  # narrative 없는 결정적
    # use_llm=False 면 narrative 빈 문자열 → 페이지에서 직접 추출 불가.
    # 대신 디스크의 실제 09 페이지(LLM narrative 포함)를 읽어 검사.
    from market_research.wiki.paths import RESEARCH_SYNTHESIS_DIR
    out: dict[str, dict] = {}
    for asset, a in agg.items():
        stem = _ASSET_FILE_STEM.get(asset, asset.replace("/", "_"))
        p = RESEARCH_SYNTHESIS_DIR / f"{month}_{stem}.md"
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8")
        sec1_raw = body.split("## 1.")[-1].split("## 2.")[0] if "## 1." in body else ""
        # LLM narrative 산문만 — 헤더 줄(첫 줄, strength 포함)·vote 줄 제외
        sec1 = "\n".join(
            ln for ln in sec1_raw.splitlines()[1:]
            if not ln.strip().startswith("- vote"))
        pool = " ".join(_claim_text_blob(c) for c in
                        (a.get("broker_claims") or []) + (a.get("monygeek_claims") or []))
        pool_norm = re.sub(r"[,\s]", "", pool)
        facts = extract_hard_facts(sec1)
        unsupported = [f for f in facts
                       if len(_norm_num(f)) >= 2 and _norm_num(f) not in pool_norm]
        out[asset] = {"n_facts": len(facts), "unsupported": unsupported}
    return out


def build_audit(month: str) -> dict[str, Any]:
    """D4 audit 전체 — sample sheet + gate report."""
    claims = load_research_claims(month)
    agg = aggregate_by_asset(claims)
    ev_index = build_evidence_index(month)

    # sample sheet
    rows: list[dict] = []
    for asset, a in agg.items():
        cs = (a.get("broker_claims") or []) + (a.get("monygeek_claims") or [])
        target = KOSPI_SAMPLE_MIN if asset == "국내주식" else MIN_SAMPLE_PER_ASSET
        for c in stratified_sample(cs, min(target, len(cs))):
            g = check_claim_grounding(c, ev_index)
            rows.append({
                "claim_id": (c.get("claim_id") or "").split(":")[-1],
                "source_type": c.get("source_type"),
                "broker_author": c.get("broker_author"),
                "auto_asset_class": asset,
                "manual_asset_class": "",
                "auto_stance": c.get("stance"),
                "manual_stance": "",
                "horizon": c.get("horizon"),
                "theme": "|".join(c.get("sectors") or []),
                "evidence_text": (c.get("evidence_text") or "")[:120],
                "hard_fact_present": "Y" if g["n_facts"] else "N",
                "hard_fact_unsupported": "; ".join(g["unsupported"])[:120],
                "hard_fact_supported": "NA" if not g["n_facts"]
                    else ("Y" if not g["unsupported"] else "N"),
                "pass_fail": "" if not g["unsupported"] else "FLAG",
                "comment": "",
            })

    # gate report (auto)
    narr = narrative_grounding(month, agg)
    gate_rows = []
    for asset, a in sorted(agg.items(), key=lambda kv: -kv[1]["n_claims"]):
        nfacts_unsupported = narr.get(asset, {}).get("unsupported", [])
        gate_rows.append({
            "asset_class": asset, "n_claims": a["n_claims"],
            "broker": a["n_broker"], "monygeek": a["n_monygeek"],
            "consensus": a["consensus_stance"], "strength": a["consensus_strength"],
            "directional_ok": a["consensus_strength"] >= LOW_CONVICTION_STRENGTH,
            "coverage_ok": a["n_claims"] >= MIN_COVERAGE_CLAIMS,
            "narrative_unsupported_facts": nfacts_unsupported,
        })

    # claim-level grounding 전수 집계
    total_facts = total_unsup = 0
    for c in claims:
        g = check_claim_grounding(c, ev_index)
        total_facts += g["n_facts"]
        total_unsup += len(g["unsupported"])

    return {"month": month, "rows": rows, "gate_rows": gate_rows,
            "claim_fact_total": total_facts, "claim_fact_unsupported": total_unsup,
            "n_claims": len(claims), "n_assets": len(agg)}


_NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def _nearest_rel_dist(fact_core: str, evidence: str) -> float | None:
    """evidence 내 숫자 중 fact 와 가장 가까운 것의 상대거리. 없으면 None."""
    try:
        fv = float(fact_core)
    except ValueError:
        return None
    if fv == 0:
        return None
    best = None
    for m in _NUM_RE.findall(evidence or ""):
        try:
            ev = float(m.replace(",", ""))
        except ValueError:
            continue
        d = abs(ev - fv) / abs(fv)
        if best is None or d < best:
            best = d
    return best


def _fact_category(fact: str, sentence: str) -> str:
    s = sentence
    # 날짜(YYYY.M / YYYY년 등) 우선 — 지수 맥락에 섞여도 날짜로
    if re.fullmatch(r"20\d\d(?:\.\d+)?", fact) or any(u in fact for u in ("월", "일", "년")):
        return "5_날짜이벤트"
    if any(k in s for k in ("코스피", "코스닥", "지수", "포인트", "선 돌파", "최고치", "신고가", "나스닥", "S&P")) \
            and ("," in fact or len(_norm_num(fact)) >= 4):
        return "1_지수레벨"
    if "%" in fact and any(k in s for k in ("CPI", "물가", "인플레", "금리", "수익률", "국채")):
        return "2_금리물가"
    if "%" in fact and any(k in s for k in ("수출", "증가", "성장", "YoY")):
        return "3_수출성장"
    if any(k in s for k in ("법안", "법", "규제", "정책", "클래리티", "제도화")):
        return "4_정책법안"
    if any(u in fact for u in ("월", "일", "년")) or re.search(r"20\d\d", fact):
        return "5_날짜이벤트"
    return "9_기타수치"


def _search_pool(fact_core: str, pool_norm: dict[str, str]) -> list[str]:
    """source pool(월 전체 evidence) 에서 fact 숫자코어를 포함한 evidence_id 목록."""
    if not fact_core or len(fact_core) < 2:
        return []
    return [eid for eid, txt in pool_norm.items() if fact_core in txt]


def unsupported_fact_report(month: str) -> list[dict]:
    """unsupported hard fact triage (citation remap 우선, DROP 최소화).

    판정(사용자 2026-06-15 규칙):
    - FIX_CITATION       : fact 가 source pool 의 *다른* evidence 에 실재 → 올바른
                           evidence_id 로 재연결 (DROP 안 함).
    - NEED_SOURCE_ATTACH : fact 가 pool 어디에도 없음 → 운영 narrative 보류,
                           source 부착 후 사용 (확인 전 UNSUPPORTED 단정 안 함).
    - ROUND_UP_REVIEW    : 지수 'N,000선 돌파' 인데 pool 엔 그 레벨 없고 더 낮은
                           근접 레벨만 → round-up 금지, evidence 표현으로 낮춤.
    - OK_ROUNDING        : claim 자체 evidence 에 near(≤1%) — 미세 반올림(5.18 vs 5.198).
    """
    claims = load_research_claims(month)
    agg = aggregate_by_asset(claims)
    ev_index = build_evidence_index(month)
    # pool: 월 전체 evidence (콤마/공백 제거 normalized)
    pool_norm = {eid: re.sub(r"[,\s]", "", txt) for eid, txt in ev_index.items()}

    displayed: dict[str, set] = {}
    asset_of: dict[str, str] = {}
    for asset, a in agg.items():
        displayed[asset] = {c.get("claim_id")
                            for c in (a.get("broker_claims") or [])[:12]
                            + (a.get("dissent") or [])[:8]}
        for c in a.get("broker_claims", []) + a.get("monygeek_claims", []):
            asset_of[c.get("claim_id")] = asset

    rows: list[dict] = []
    for c in claims:
        g = check_claim_grounding(c, ev_index)
        if not g["unsupported"]:
            continue
        sentence = _claim_text_blob(c)
        own_ev = " ".join(ev_index.get(str(e), "")
                          for e in (c.get("supporting_evidence_ids") or []))
        cid = c.get("claim_id")
        asset = asset_of.get(cid, "(unrouted)")
        for fact in g["unsupported"]:
            core = _norm_num(fact)
            cat = _fact_category(fact, sentence)
            pool_hits = _search_pool(core, pool_norm)
            rel_own = _nearest_rel_dist(core, own_ev)
            from market_research.analyze.market_snapshot import is_market_metric_text
            # 시장 레벨(지수/환율/유가/금)은 DB source of truth → pool 검색·remap 대상 아님
            if cat == "1_지수레벨" or (is_market_metric_text(sentence)
                                       and ("," in fact or "%" not in fact)):
                verdict = "DB_LEVEL"
            elif rel_own is not None and rel_own <= 0.01:
                verdict = "OK_ROUNDING"
            elif pool_hits:
                verdict = "FIX_CITATION"
            else:
                verdict = "NEED_SOURCE_ATTACH"
            rows.append({
                "category": cat,
                "claim_id": (cid or "").split(":")[-1],
                "asset_class": asset,
                "fact": fact,
                "verdict": verdict,
                "in_pool": "Y" if pool_hits else "N",
                "candidate_evidence_ids": ";".join(pool_hits[:5]),
                "displayed": "Y" if cid in displayed.get(asset, set()) else "N",
                "sentence": sentence[:120],
                "own_evidence": own_ev[:140],
            })
    _vorder = {"FIX_CITATION": 0, "ROUND_UP_REVIEW": 1, "NEED_SOURCE_ATTACH": 2,
               "OK_ROUNDING": 3}
    rows.sort(key=lambda r: (r["displayed"] != "Y", r["category"],
                             _vorder.get(r["verdict"], 9)))
    return rows


def write_audit_csv(month: str, audit: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    p = AUDIT_DIR / f"{month}_audit_sheet.csv"
    cols = ["claim_id", "source_type", "broker_author", "auto_asset_class",
            "manual_asset_class", "auto_stance", "manual_stance", "horizon",
            "theme", "evidence_text", "hard_fact_present", "hard_fact_unsupported",
            "hard_fact_supported", "pass_fail", "comment"]
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(audit["rows"])
    return p


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="D4 research audit")
    ap.add_argument("month")
    args = ap.parse_args()
    a = build_audit(args.month)
    p = write_audit_csv(args.month, a)
    print(f"[D4 audit] {args.month} sample={len(a['rows'])} → {p}")
    print(f"  claim-level hard fact: {a['claim_fact_total']} 개 중 "
          f"unsupported {a['claim_fact_unsupported']} "
          f"({100*a['claim_fact_unsupported']/max(1,a['claim_fact_total']):.1f}%)")
    print("  --- 자산군 gate ---")
    for g in a["gate_rows"]:
        flags = []
        if not g["directional_ok"]:
            flags.append(f"LOW-CONVICTION(str={g['strength']})")
        if not g["coverage_ok"]:
            flags.append(f"INSUFFICIENT(n={g['n_claims']})")
        if g["narrative_unsupported_facts"]:
            flags.append(f"NARR-UNSUP={g['narrative_unsupported_facts'][:3]}")
        tag = "  ⚠ " + " ".join(flags) if flags else "  ok"
        print(f"  {g['asset_class']}: n={g['n_claims']} consensus={g['consensus']} "
              f"str={g['strength']}{tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
