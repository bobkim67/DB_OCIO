"""R8-B-impl: Asset Movement Anchor Builder.

LLM 호출 0. report_output / approved 무수정.

자산군 8종 (국내주식 / 해외주식 / 국내채권 / 해외채권 / 크레딧 / 현금성 /
환율(FX) / 원자재금) 을 anchor 로 하여, 각 자산군에 BM 등락률 + 펀드 노출 +
causal path + supporting evidence + wiki page 를 nested 로 묶어 반환.

debate input prompt 의 1차 unit 으로 사용 (raw evidence 직접 listing 보조화).

API:
    anchors = build_asset_movement_anchors(
        period, year, fund_code=None,
        causal_paths=[], evidence_annotations=[],
        pa_asset_summary=None, indicators_csv_path=None,
    )

Returns dict:
    {
        "schema_version": "r8b-asset-movement-anchor-1.0.0",
        "period": "2026-04", "fund_code": None,
        "asset_movements": [
            {asset_class, bm:{name,return_pct,...}, fund_exposure,
             causal_paths:[...], supporting_evidence_ids:[...],
             wiki_pages:[...], topic_tags:[...], importance_score, ...},
            ...
        ],
        "unattached_evidence": [...],
        "coverage_summary": {covered_asset_count, ...},
        "warnings": [...],
    }
"""
from __future__ import annotations

import csv
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "r8b-asset-movement-anchor-1.0.0"

# ──────────────────────────────────────────────────────────────────
# 자산군 (8종 + '포트폴리오' 별도)
# ──────────────────────────────────────────────────────────────────

ASSET_CLASSES_R8B: tuple[str, ...] = (
    "국내주식", "해외주식", "국내채권", "해외채권",
    "크레딧", "현금성", "환율(FX)", "원자재금",
)

# PA asset_summary 의 한국어 키 → 우리 8종으로 alias
# data_loader.compute_single_port_pa 의 자산군은 mapping_method 별 다양
# (방법3 기본: 국내주식/해외주식/국내채권/해외채권/대체/FX/유동성)
_PA_ALIAS: dict[str, str] = {
    "국내주식": "국내주식",
    "해외주식": "해외주식",
    "국내채권": "국내채권",
    "해외채권": "해외채권",
    "대체": "원자재금",
    "대체투자": "원자재금",
    "금/대체": "원자재금",
    "FX": "환율(FX)",
    "환율": "환율(FX)",
    "유동성": "현금성",
    "유동성및기타": "현금성",
    "현금성": "현금성",
    "주식": "국내주식",  # 방법1/2 병합 시 fallback (alias 후보)
    "채권": "국내채권",
}


# ──────────────────────────────────────────────────────────────────
# Indicators.csv 컬럼 → 자산군 매핑
# ──────────────────────────────────────────────────────────────────

# (column_name, kind) — kind: "level_pct" 또는 "bp_diff"
_ASSET_TO_INDICATOR: dict[str, tuple[str, str, str]] = {
    "국내주식": ("MSCI_KOREA", "level_pct", "MSCI Korea Index"),
    "해외주식": ("SP500_TR", "level_pct", "S&P 500 Total Return"),
    "국내채권": ("KAP_BOND_TR", "level_pct", "KAP종합채권 (KIS)"),
    "해외채권": ("UST_7_10Y_TR", "level_pct", "UST 7-10Y Total Return"),
    "크레딧":   ("HY_TR", "level_pct", "Bloomberg US HY TR (LF98TRUU)"),
    "현금성":   ("FED_UPPER", "bp_diff", "Fed Funds Upper Bound (bp)"),
    "환율(FX)": ("USDKRW", "level_pct", "USD/KRW"),
    "원자재금": ("GOLD", "level_pct", "Gold Spot"),
}


# ──────────────────────────────────────────────────────────────────
# Topic (R7/news classifier) → asset_class
# ──────────────────────────────────────────────────────────────────

_TOPIC_TO_ASSET_CLASS: dict[str, list[str]] = {
    # R7 TOPIC_DEFS (rule-based id)
    "event:geopolitical":          [],  # cross-asset → unattached
    "event:wgbi":                  ["국내채권"],
    "macro:oil_price":              ["원자재금"],
    "macro:inflation":              ["국내채권", "해외채권"],
    "macro:interest_rate":          ["국내채권", "해외채권"],
    "macro:fx_usdkrw":              ["환율(FX)"],
    "asset:us_growth_stock":        ["해외주식"],
    "asset:domestic_bond":          ["국내채권"],
    "asset:gold":                   ["원자재금"],
    "asset:overseas_translation":   ["환율(FX)"],
    # 한국어 토픽 (news classifier — evidence_annotations.topic / all_topics)
    "지정학":                        [],
    "금리_채권":                     ["국내채권", "해외채권"],
    "통화정책":                      ["국내채권", "해외채권"],
    "물가_인플레이션":               ["국내채권", "해외채권"],
    "환율_FX":                       ["환율(FX)"],
    "달러_글로벌유동성":             ["환율(FX)", "크레딧"],
    "유동성_크레딧":                 ["크레딧"],
    "에너지_원자재":                 ["원자재금"],
    "귀금속_금":                     ["원자재금"],
    "테크_AI_반도체":                ["해외주식"],
    "관세_무역":                     [],   # cross-asset → unattached
    "경기_소비":                     [],
    "주식_시장":                     ["국내주식", "해외주식"],
    "채권_시장":                     ["국내채권", "해외채권"],
}

# R7 path_id → asset_classes (path 단위 직접 매핑)
_PATH_ID_TO_ASSETS: dict[str, list[str]] = {
    "geopolitical_oil_inflation_rates_growth": ["해외주식", "원자재금", "국내채권"],
    "wgbi_domestic_bond_inflow":                ["국내채권"],
    "fx_translation_overseas_assets":           ["환율(FX)", "해외주식", "해외채권"],
    "gold_hedge_volatility":                    ["원자재금"],
    "rates_domestic_bond":                      ["국내채권"],
}


# ──────────────────────────────────────────────────────────────────
# Period parsing
# ──────────────────────────────────────────────────────────────────

PERIOD_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
PERIOD_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def _period_dates(period: str) -> tuple[date, date] | tuple[None, None]:
    """period → (start_date, end_date).

    월간 수익률 표준 정의에 맞춰 start = 전월 마지막 calendar day,
    end = 당월 마지막 calendar day. 분기도 동일 (직전 분기말).
    이는 comment_engine._load_bm_returns_for_range 의 prev_last/cur_last 패턴
    (전월말 → 당월말) 과 정합성 유지하기 위함.
    csv 에 해당 calendar day row 가 없으면 (휴일/주말) 기존 in-range filter 가
    가까운 영업일로 자연 fallback.
    """
    m = PERIOD_QUARTER_RE.match(period)
    if m:
        yr, q = int(m.group(1)), int(m.group(2))
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        # start = 직전 분기 마지막 calendar day (분기 첫달 1일 - 1일)
        start = date(yr, start_month, 1) - timedelta(days=1)
        if end_month == 12:
            end = date(yr, 12, 31)
        else:
            end = date(yr, end_month + 1, 1) - timedelta(days=1)
        return start, end
    m = PERIOD_MONTH_RE.match(period)
    if m:
        yr, mo = int(m.group(1)), int(m.group(2))
        # start = 전월 마지막 calendar day (당월 1일 - 1일)
        start = date(yr, mo, 1) - timedelta(days=1)
        if mo == 12:
            end = date(yr, 12, 31)
        else:
            end = date(yr, mo + 1, 1) - timedelta(days=1)
        return start, end
    return None, None


# ──────────────────────────────────────────────────────────────────
# Indicators.csv 로드 + 기간 등락 계산
# ──────────────────────────────────────────────────────────────────

def _parse_csv_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def load_indicator_changes(
    period: str,
    indicators_csv_path: Path | None,
) -> tuple[dict[str, dict], list[str]]:
    """indicators.csv 의 첫/마지막 in-range 행 → 자산군별 BM 변동.

    Returns (asset_to_bm, warnings).
        asset_to_bm[asset_class] = {
            "name", "source", "fund_aligned",
            "return_pct" (level_pct 일 때) or "diff_bp" (bp_diff 일 때),
            "level_start", "level_end",
            "kind": "level_pct" | "bp_diff",
        }
    """
    out: dict[str, dict] = {}
    warnings: list[str] = []
    if not indicators_csv_path or not Path(indicators_csv_path).exists():
        warnings.append(f"indicators.csv not found: {indicators_csv_path}")
        return out, warnings
    start, end = _period_dates(period)
    if not start:
        warnings.append(f"period parse failed: {period}")
        return out, warnings

    rows: list[dict] = []
    try:
        with open(indicators_csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = _parse_csv_date(row.get("date", ""))
                if d and start <= d <= end:
                    rows.append({"date": d, **row})
    except Exception as exc:
        warnings.append(f"indicators.csv read failed: {exc}")
        return out, warnings

    if not rows:
        warnings.append(f"indicators.csv has no row in {period}")
        return out, warnings

    rows.sort(key=lambda r: r["date"])
    first, last = rows[0], rows[-1]

    for ac, (col, kind, label) in _ASSET_TO_INDICATOR.items():
        try:
            v0 = float(first.get(col, "") or "nan")
            v1 = float(last.get(col, "") or "nan")
        except (ValueError, TypeError):
            warnings.append(f"{ac} ({col}) invalid values")
            continue
        if not _isnum(v0) or not _isnum(v1):
            warnings.append(f"{ac} ({col}) missing in {period}")
            continue
        item: dict[str, Any] = {
            "name": label, "source": f"indicators.csv:{col}",
            "fund_aligned": False, "kind": kind,
            "level_start": v0, "level_end": v1,
        }
        if kind == "level_pct":
            if v0 != 0:
                item["return_pct"] = round((v1 - v0) / v0 * 100, 4)
            else:
                item["return_pct"] = None
                warnings.append(f"{ac} level_start=0, return_pct undefined")
        else:  # bp_diff
            item["diff_bp"] = round((v1 - v0) * 100, 2) if abs(v1 - v0) < 50 \
                              else round(v1 - v0, 2)  # OAS 가 bp 단위면 100 곱하지 않음
            # 단순화: HY_OAS 는 이미 bp, FED_UPPER 는 % → bp 변환 (×100)
            if col in ("FED_UPPER", "FED_LOWER", "ECB_RATE", "BOJ_RATE",
                        "BOK_RATE", "SOFR", "EFFR"):
                item["diff_bp"] = round((v1 - v0) * 100, 2)
            else:
                item["diff_bp"] = round(v1 - v0, 2)
        out[ac] = item
    return out, warnings


def _isnum(x: Any) -> bool:
    try:
        return x == x and abs(x) < 1e15  # NaN check
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────
# PA → fund_exposure
# ──────────────────────────────────────────────────────────────────

def extract_fund_exposure(
    pa_asset_summary: Any,
) -> dict[str, dict]:
    """compute_single_port_pa.asset_summary DataFrame → 자산군별 노출.

    DataFrame 미포함 시 빈 dict.
    Returns {
        asset_class_r8b: {
            "weight_pct": float,
            "individual_return_pct": float,
            "contribution_pct": float,
        }
    }
    """
    out: dict[str, dict] = {}
    if pa_asset_summary is None:
        return out
    if not hasattr(pa_asset_summary, "iterrows"):
        return out
    for _, row in pa_asset_summary.iterrows():
        try:
            ac_pa = row.get("자산군") if hasattr(row, "get") else row["자산군"]
        except Exception:
            continue
        if not ac_pa or ac_pa == "포트폴리오":
            continue
        ac_r8b = _PA_ALIAS.get(ac_pa, ac_pa)
        if ac_r8b not in ASSET_CLASSES_R8B:
            continue
        try:
            indiv = row.get("개별수익률") if hasattr(row, "get") else row["개별수익률"]
            contrib = row.get("기여수익률") if hasattr(row, "get") else row["기여수익률"]
            wgh = row.get("순자산비중") if hasattr(row, "get") else row["순자산비중"]
        except Exception:
            continue
        out[ac_r8b] = {
            "weight_pct": round(float(wgh) * 100, 3) if wgh is not None else None,
            "individual_return_pct": round(float(indiv) * 100, 3) if indiv is not None else None,
            "contribution_pct": round(float(contrib) * 100, 3) if contrib is not None else None,
        }
    return out


# ──────────────────────────────────────────────────────────────────
# Topic → asset matching
# ──────────────────────────────────────────────────────────────────

def map_topic_to_assets(topic: str, all_topics: list[str] | None = None) -> list[str]:
    """topic 단일 또는 all_topics list → asset_class list (중복 제거, 등장순)."""
    out: list[str] = []
    seen: set[str] = set()
    for t in [topic, *(all_topics or [])]:
        if not t:
            continue
        for ac in _TOPIC_TO_ASSET_CLASS.get(t, []):
            if ac not in seen:
                out.append(ac)
                seen.add(ac)
    return out


def map_path_to_assets(path: dict) -> list[str]:
    """R7 causal_path → asset_class list. path_id direct mapping 우선."""
    pid = path.get("path_id", "")
    direct = _PATH_ID_TO_ASSETS.get(pid, [])
    if direct:
        return list(direct)
    # fallback: chain 의 노드 traversal
    out: list[str] = []
    seen: set[str] = set()
    for node in path.get("chain") or []:
        for ac in _TOPIC_TO_ASSET_CLASS.get(node, []):
            if ac not in seen:
                out.append(ac)
                seen.add(ac)
    return out


# ──────────────────────────────────────────────────────────────────
# Importance score
# ──────────────────────────────────────────────────────────────────

def importance_score(
    bm: dict | None, fund_exposure: dict | None,
    evidence_count: int, path_count: int,
) -> float:
    """0~1 normalized importance heuristic."""
    score = 0.0
    if bm:
        ret = bm.get("return_pct")
        if ret is not None:
            score += 0.4 * min(abs(ret) / 5.0, 1.0)
        diff = bm.get("diff_bp")
        if diff is not None:
            score += 0.4 * min(abs(diff) / 50.0, 1.0)
    if fund_exposure:
        contrib = fund_exposure.get("contribution_pct") or 0
        score += 0.3 * min(abs(contrib) / 1.0, 1.0)
        wgh = fund_exposure.get("weight_pct") or 0
        score += 0.1 * min(wgh / 30.0, 1.0)
    score += 0.1 * min(evidence_count / 5.0, 1.0)
    score += 0.1 * min(path_count / 3.0, 1.0)
    return round(min(score, 1.0), 3)


# ──────────────────────────────────────────────────────────────────
# Main: build_asset_movement_anchors
# ──────────────────────────────────────────────────────────────────

def _filter_claims_for_asset(
    claims: list[dict] | None, asset_class: str,
) -> list[dict]:
    """R9-A.3: claim → 자산군별 linked_claims 추출 (read-only).

    affected_assets 의 asset_class 와 매칭되는 claim 만 슬림 dict 로 변환.
    LLM 호출 0, file write 0.
    """
    if not isinstance(claims, list) or not claims:
        return []
    out: list[dict] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        matched = False
        for a in c.get("affected_assets", []) or []:
            ac = a.get("asset_class") if isinstance(a, dict) else a
            if ac == asset_class:
                matched = True
                break
        if not matched:
            continue
        cid = c.get("claim_id") or ""
        h10 = cid.rsplit(":", 1)[-1] if cid.startswith("claim:") else ""
        period = c.get("period") or ""
        wiki_filename = (
            f"{period}_claim_{h10}.md"
            if period and h10 else None
        )
        wiki_path = (
            f"08_Claims/{wiki_filename}" if wiki_filename else None
        )
        out.append({
            "claim_id": cid,
            "claim_text": c.get("claim_text") or "",
            "claim_type": c.get("claim_type") or "",
            "affected_assets": list(c.get("affected_assets") or []),
            "confidence": c.get("confidence"),
            "salience": c.get("salience"),
            "supporting_evidence_ids": list(
                c.get("supporting_evidence_ids") or []),
            "wiki_filename": wiki_filename,
            "wiki_path": wiki_path,
        })
    return out


def build_asset_movement_anchors(
    period: str,
    fund_code: str | None = None,
    causal_paths: list[dict] | None = None,
    evidence_annotations: list[dict] | None = None,
    pa_asset_summary: Any = None,
    indicators_csv_path: Path | None = None,
    claims: list[dict] | None = None,
) -> dict:
    """8 자산군 anchor list + unattached_evidence + coverage_summary.

    causal_paths : R7 build_causal_layer 의 causal_paths
    evidence_annotations : R8-A resolver 의 결과 (title/topic 채워짐)
    pa_asset_summary : compute_single_port_pa.asset_summary (fund_code 일 때)
    claims : R9-A.3 — canonical store 에서 select_promoted_claims_for_period
             로 미리 필터링된 promotion 통과 claim 들. None / [] 이면 각
             asset_movement.linked_claims = [] 로 설정 (기존 schema/behavior
             일체 변경 없음).
    """
    causal_paths = causal_paths or []
    evidence_annotations = evidence_annotations or []
    warnings: list[str] = []

    # 1) BM 변동
    asset_bm, w_ind = load_indicator_changes(period, indicators_csv_path)
    warnings.extend(w_ind)

    # 2) 펀드 노출
    fund_exposure = extract_fund_exposure(pa_asset_summary)

    # 3) evidence → asset (multi-attach 가능)
    evidence_by_asset: dict[str, list[str]] = {ac: [] for ac in ASSET_CLASSES_R8B}
    evidence_topic: dict[str, set[str]] = {ac: set() for ac in ASSET_CLASSES_R8B}
    unattached: list[dict] = []
    for ea in evidence_annotations:
        # R8-A unresolved 는 unattached 로 빠름 (causal extraction 처럼)
        if ea.get("_resolved") is False:
            continue
        aid = ea.get("article_id")
        if not aid:
            continue
        topic = ea.get("topic") or ""
        all_topics = ea.get("all_topics") or []
        matched = map_topic_to_assets(topic, all_topics)
        if matched:
            for ac in matched:
                evidence_by_asset[ac].append(aid)
                if topic:
                    evidence_topic[ac].add(topic)
        else:
            unattached.append({
                "article_id": aid,
                "ref": ea.get("ref"),
                "title_short": (ea.get("title") or "")[:80],
                "topic": topic,
                "all_topics": list(all_topics),
                "reason": "topic not in _TOPIC_TO_ASSET_CLASS or empty",
            })

    # 4) path → asset (multi-attach)
    paths_by_asset: dict[str, list[dict]] = {ac: [] for ac in ASSET_CLASSES_R8B}
    for p in causal_paths:
        for ac in map_path_to_assets(p):
            paths_by_asset[ac].append({
                "path_id": p.get("path_id"),
                "label": p.get("label"),
                "confidence": p.get("confidence"),
                "covered_chain_nodes": p.get("covered_chain_nodes") or [],
                "supporting_evidence_ids": p.get("supporting_evidence_ids") or [],
            })

    # 5) anchor 합성
    asset_movements: list[dict] = []
    for ac in ASSET_CLASSES_R8B:
        bm = asset_bm.get(ac)
        fx = fund_exposure.get(ac)
        ev_ids = evidence_by_asset.get(ac, [])
        # path supporting evidence 도 union
        path_evs: set[str] = set(ev_ids)
        for p in paths_by_asset.get(ac, []):
            for e in p.get("supporting_evidence_ids") or []:
                path_evs.add(e)
        supporting = list(path_evs)
        score = importance_score(
            bm, fx,
            evidence_count=len(supporting),
            path_count=len(paths_by_asset.get(ac, [])),
        )
        # direction
        direction = "flat"
        if bm:
            if bm.get("kind") == "level_pct" and bm.get("return_pct") is not None:
                r = bm["return_pct"]
                direction = "up" if r > 0.1 else ("down" if r < -0.1 else "flat")
            elif bm.get("kind") == "bp_diff" and bm.get("diff_bp") is not None:
                d = bm["diff_bp"]
                direction = "up" if d > 1 else ("down" if d < -1 else "flat")
        asset_movements.append({
            "asset_class": ac,
            "bm": bm or {"name": None, "kind": None, "return_pct": None,
                          "fund_aligned": False},
            "movement_direction": direction,
            "fund_exposure": fx,
            "causal_paths": paths_by_asset.get(ac, []),
            "supporting_evidence_ids": supporting,
            "wiki_pages": [],  # 외부에서 wiki retriever 로 채움 (현재 단계 외)
            "topic_tags": sorted(evidence_topic.get(ac, set())),
            "importance_score": score,
            # R9-A.3 read-only claim attach. claims=None/[] 이면 [].
            "linked_claims": _filter_claims_for_asset(claims, ac),
        })

    # 6) movement_rank — importance 기준 desc
    asset_movements.sort(key=lambda a: -a["importance_score"])
    for i, a in enumerate(asset_movements, 1):
        a["movement_rank"] = i

    # 7) 정렬은 importance 로, 출력은 ASSET_CLASSES_R8B 순서로 다시
    by_ac = {a["asset_class"]: a for a in asset_movements}
    asset_movements_sorted = [by_ac[ac] for ac in ASSET_CLASSES_R8B if ac in by_ac]

    # 8) coverage summary
    covered = sum(1 for a in asset_movements_sorted if a["importance_score"] > 0)
    with_evidence = sum(1 for a in asset_movements_sorted if a["supporting_evidence_ids"])
    with_paths = sum(1 for a in asset_movements_sorted if a["causal_paths"])
    with_bm = sum(1 for a in asset_movements_sorted if a["bm"].get("return_pct") is not None
                   or a["bm"].get("diff_bp") is not None)
    coverage_summary = {
        "covered_asset_count": covered,
        "with_evidence": with_evidence,
        "with_causal_paths": with_paths,
        "with_bm_value": with_bm,
        "total": len(ASSET_CLASSES_R8B),
        "unattached_evidence_count": len(unattached),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "period": period,
        "fund_code": fund_code,
        "asset_movements": asset_movements_sorted,
        "unattached_evidence": unattached,
        "coverage_summary": coverage_summary,
        "warnings": warnings,
    }


# ──────────────────────────────────────────────────────────────────
# Prompt formatter — debate / fund_comment 용
# ──────────────────────────────────────────────────────────────────

def build_amc_fallback(anchors: dict | None, top_n: int = 3) -> list[dict]:
    """R8-B-2: anchors → deterministic asset_movement_commentary stub (LLM 미사용).

    importance rank 상위 top_n 자산군에 대해 anchor 의 BM/path/topic 만 합성.
    drivers / outlook / portfolio_implication 은 정성 stub (admin 검수 필요 명시).

    agent 가 amc 를 비워둔 경우 admin 이 fallback 을 참고하여 수동 보정 가능.
    `result['asset_movement_commentary']` 자체를 덮어쓰지 않고 별도 field 로 surface.
    """
    if not anchors:
        return []
    out: list[dict] = []
    movements = (anchors.get("asset_movements") or [])
    # importance rank 정렬 (이미 movement_rank 채워져 있으므로 그 기준으로)
    sorted_mv = sorted(movements, key=lambda a: a.get("movement_rank", 99))
    for a in sorted_mv[:top_n]:
        bm = a.get("bm") or {}
        ret = bm.get("return_pct")
        diff = bm.get("diff_bp")
        if ret is not None:
            past = f"{bm.get('name', '?')} {ret:+.2f}%"
        elif diff is not None:
            past = f"{bm.get('name', '?')} {diff:+.0f}bp"
        else:
            past = "수익률 미확인 — 정성 평가"
        causal = [(p.get("path_id") or "?")
                   for p in (a.get("causal_paths") or [])][:2]
        drivers = list(a.get("topic_tags") or [])[:3]
        out.append({
            "asset_class": a.get("asset_class"),
            "past_movement": past,
            "drivers": drivers,
            "causal_paths": causal,
            "outlook": "(deterministic fallback — agent 미생성, admin 검수 필요)",
            "portfolio_implication": "(deterministic fallback — agent 미생성, admin 검수 필요)",
            "_source": "fallback",
        })
    return out


def validate_amc_response(amc: list | None) -> list[str]:
    """R8-B-2: agent 의 asset_movement_commentary 반환을 검증.

    Returns warning 메시지 list. 빈 list 면 valid.
    agent output 자체는 변경하지 않음 (caller 가 warnings 별도 field 로 보존).
    """
    warnings: list[str] = []
    if amc is None:
        warnings.append("asset_movement_commentary missing (key absent)")
        return warnings
    if not isinstance(amc, list):
        warnings.append(f"asset_movement_commentary not a list "
                        f"(type={type(amc).__name__})")
        return warnings
    if len(amc) == 0:
        warnings.append("asset_movement_commentary is empty (R8-B-2 require ≥3)")
        return warnings
    if len(amc) < 3:
        warnings.append(
            f"asset_movement_commentary has only {len(amc)} item(s); "
            f"R8-B-2 requires ≥3"
        )
    REQUIRED = ("asset_class", "past_movement", "drivers", "causal_paths",
                "outlook", "portfolio_implication")
    for i, item in enumerate(amc):
        if not isinstance(item, dict):
            warnings.append(f"amc[{i}] is not a dict (type={type(item).__name__})")
            continue
        for f in REQUIRED:
            v = item.get(f)
            if v is None or v == "" or v == []:
                warnings.append(f"amc[{i}].{f} missing or empty")
    return warnings


def format_anchors_for_prompt(anchors: dict, max_per_anchor: int = 5) -> str:
    """anchor list 를 prompt-friendly text 로 직렬화.

    한 anchor 당 5 줄 이내 (asset_class / bm / fund_exposure / paths / evidence)
    """
    if not anchors or not anchors.get("asset_movements"):
        return ""
    lines: list[str] = ["## Asset Movement Anchors (R8-B)"]
    period = anchors.get("period", "")
    fund_code = anchors.get("fund_code")
    if fund_code:
        lines.append(f"기간 {period} · 펀드 {fund_code} (fund-aligned PA 포함)")
    else:
        lines.append(f"기간 {period} · 시장 universe BM 기준")
    lines.append("")

    for a in anchors["asset_movements"]:
        ac = a["asset_class"]
        bm = a.get("bm") or {}
        ret = bm.get("return_pct")
        diff = bm.get("diff_bp")
        if ret is not None:
            bm_str = f"{bm.get('name','?')} {ret:+.2f}%"
        elif diff is not None:
            bm_str = f"{bm.get('name','?')} {diff:+.0f}bp"
        else:
            bm_str = f"{bm.get('name') or 'BM 미설정'} (값 없음)"
        score = a["importance_score"]
        rank = a.get("movement_rank", "-")
        lines.append(f"[{ac}] rank={rank} importance={score:.2f}")
        lines.append(f"  BM: {bm_str}  (방향={a['movement_direction']})")
        fx = a.get("fund_exposure")
        if fx:
            wgh = fx.get("weight_pct")
            contrib = fx.get("contribution_pct")
            indiv = fx.get("individual_return_pct")
            lines.append(
                f"  펀드: 비중 {wgh:.1f}% / 자체수익률 {indiv:+.2f}% / "
                f"기여 {contrib:+.2f}%"
                if wgh is not None and contrib is not None and indiv is not None
                else f"  펀드: (PA 부분 missing)"
            )
        ps = a.get("causal_paths") or []
        if ps:
            for p in ps[:max_per_anchor]:
                evs = p.get("supporting_evidence_ids") or []
                ev_refs = ", ".join(f"[{e[:10]}]" for e in evs[:3])
                lines.append(
                    f"  path: {p.get('label') or p.get('path_id')} "
                    f"(conf={p.get('confidence')}) ← {ev_refs or '(no ev)'}"
                )
        sup = a.get("supporting_evidence_ids") or []
        if sup:
            sup_short = ", ".join(f"[{e[:10]}]" for e in sup[:6])
            extra = f" (+{len(sup) - 6} more)" if len(sup) > 6 else ""
            lines.append(f"  evidence: {sup_short}{extra}")
        if not ps and not sup:
            lines.append("  (no path / evidence — 자산군 movement 미감지 또는 매칭 실패)")
        lines.append("")

    unatt = anchors.get("unattached_evidence") or []
    if unatt:
        lines.append(f"## Unattached evidence ({len(unatt)}건 — 자산군 매칭 실패)")
        for u in unatt[:10]:
            lines.append(
                f"  [{u.get('article_id', '?')[:10]}] "
                f"{u.get('title_short','')} (topic={u.get('topic','?')})"
            )
        if len(unatt) > 10:
            lines.append(f"  ... +{len(unatt) - 10} more")
        lines.append("")

    cov = anchors.get("coverage_summary") or {}
    lines.append(
        f"## coverage: bm={cov.get('with_bm_value', 0)}/{cov.get('total', 8)} · "
        f"path={cov.get('with_causal_paths', 0)}/{cov.get('total', 8)} · "
        f"evidence={cov.get('with_evidence', 0)}/{cov.get('total', 8)} · "
        f"unattached_ev={cov.get('unattached_evidence_count', 0)}"
    )
    return "\n".join(lines)
