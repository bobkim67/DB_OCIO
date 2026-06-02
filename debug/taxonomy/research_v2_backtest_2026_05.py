# -*- coding: utf-8 -*-
"""research_v2 FULL backtest — 2026-05 research 전수 재분류 (region × affected_assets).

목적: keyword 샘플링 없이 2026-05 research 전체를 research_v2 prompt 로 재분류해
  ① 국내주식 비중 정상화 (v1 vs v2 asset 분포) ② KR-equity recovery ③ enum/fallback/region
  ④ multi_asset/consistency ⑤ spot-check CSV. acceptance 실측.

★ production write 0: adapted/2026-05.json 미수정. flag ON 0. consumer wiring 0.
  결과는 debug/taxonomy/ 에만. checkpoint 로 중단 복구.

재사용: research_v2_dry_classify 의 validator/resolve/prompt/remap (검증된 동일 로직).
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "debug" / "taxonomy"))

import research_v2_dry_classify as dry  # noqa: E402  (검증된 함수 재사용)
from market_research.core import constants  # noqa: E402
from market_research.core.asset_taxonomy import article_primary_asset  # noqa: E402
import anthropic  # noqa: E402

ADAPTED = REPO / "market_research/data/naver_research/adapted/2026-05.json"
CKPT = REPO / "debug/taxonomy/research_v2_backtest_ckpt.json"
OUT_JSON = REPO / "debug/taxonomy/research_v2_backtest_result.json"
OUT_MD = REPO / "debug/taxonomy/research_v2_backtest_report.md"
OUT_CSV = REPO / "debug/taxonomy/research_v2_backtest_spotcheck.csv"

ALLOWED_8 = dry.ALLOWED_ASSET_8
KR_EQ_KW = ("코스피", "코스닥", "삼성전자", "하이닉스", "sk하이닉스", "반도체",
            "국내 주식 마감", "국내주식 마감", "팔천피", "8천피", "밸류업")
BATCH = 20  # dry-proven (batch 20 → ~6000 out tokens < 8000 max). 30 은 JSON 잘림.


def _topics(a):
    return [t.get("topic") for t in (a.get("_classified_topics") or [])
            if isinstance(t, dict) and t.get("topic")]


def main():
    rd = json.loads(ADAPTED.read_text(encoding="utf-8"))
    arts = [a for a in (rd["articles"] if isinstance(rd, dict) else rd)
            if (a.get("description") or "").strip()]
    print(f"2026-05 research: {len(arts)}건 (desc 있음)")

    # checkpoint 복구
    done = {}
    if CKPT.exists():
        for row in json.loads(CKPT.read_text(encoding="utf-8")):
            done[row["article_id"]] = row
        print(f"  checkpoint: {len(done)}건 복구")

    cli = anthropic.Anthropic(api_key=constants.ANTHROPIC_API_KEY)

    def _classify_chunk(chunk):
        """LLM 분류 → {chunk_idx: raw_item}. 파싱 실패 시 반으로 쪼개 재시도."""
        try:
            items, tok = dry.call_llm(cli, chunk, 0)
            return {it.get("idx"): it for it in items}, tok
        except Exception as exc:
            if len(chunk) <= 2:
                print(f"    [chunk {len(chunk)}건 분류 실패: {type(exc).__name__} — 빈 처리]", flush=True)
                return {}, 0
            mid = len(chunk) // 2
            l_map, l_tok = _classify_chunk(chunk[:mid])
            r_map, r_tok = _classify_chunk(chunk[mid:])
            return ({**l_map, **{k + mid: v for k, v in r_map.items()}}, l_tok + r_tok)

    todo = [a for a in arts if a["_article_id"] not in done]
    t0, out_tok = time.time(), 0
    for b0 in range(0, len(todo), BATCH):
        chunk = todo[b0:b0 + BATCH]
        bymap, tok = _classify_chunk(chunk)
        out_tok += tok
        for j, a in enumerate(chunk):
            raw = bymap.get(j, {})
            clean = dry.validate_item(raw)
            r3 = dry.resolve_3way(clean, a)
            done[a["_article_id"]] = {
                "article_id": a["_article_id"], "title": a.get("title", ""),
                "category": a.get("_raw_category", ""), "source": a.get("source", ""),
                "v1_topics": _topics(a), "v1_primary_topic": a.get("primary_topic"),
                "region": clean["region"], "sector": clean["sector"],
                "affected_assets": clean["affected_assets"], "warnings": clean["warnings"],
                "rationale": clean.get("rationale"),
                "v1_asset": r3["v1_asset"], "rule_asset": r3["rule_asset"],
                "llm_primary_asset": r3["llm_primary_asset"],
                "hybrid_primary_asset": r3["hybrid_primary_asset"],
                "route_source": r3["route_source"],
                "consistency_warning": r3["consistency_warning"],
            }
        # checkpoint 매 batch
        CKPT.write_text(json.dumps(list(done.values()), ensure_ascii=False), encoding="utf-8")
        if (b0 // BATCH) % 5 == 0:
            print(f"  batch {b0//BATCH+1}/{(len(todo)+BATCH-1)//BATCH} "
                  f"({len(done)}/{len(arts)}) out={out_tok} {time.time()-t0:.0f}s", flush=True)

    rows = [done[a["_article_id"]] for a in arts if a["_article_id"] in done]
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"분류 완료 {len(rows)}건, out_tokens={out_tok}, {time.time()-t0:.0f}s")
    _report(rows)
    print(f"→ {OUT_MD.name} / {OUT_CSV.name} / {OUT_JSON.name}")
    return 0


def _dist(rows, key):
    c = Counter(r[key] for r in rows if r[key])
    return c


def _report(rows):
    n = len(rows)
    asset_valid = sum(1 for r in rows if all(c["asset"] in ALLOWED_8 for c in r["affected_assets"]))
    region_valid = sum(1 for r in rows if r["region"] in dry.REGION_SET)
    fallback = sum(1 for r in rows if r["route_source"] in ("rule", "v1", "none"))
    unknown = sum(1 for r in rows if r["hybrid_primary_asset"] is None)
    multi = sum(1 for r in rows if len(r["affected_assets"]) >= 2)
    conflict = sum(1 for r in rows if r["consistency_warning"])

    v1d = _dist(rows, "v1_asset")
    v2d = _dist(rows, "hybrid_primary_asset")
    v1_dom = sum(v1d.values()) or 1
    v2_dom = sum(v2d.values()) or 1

    # KR-equity recovery: KR 주식 reference set (title keyword) 중 국내주식 분류율
    kr_ref = [r for r in rows if any(k in (r["title"] or "").lower() for k in KR_EQ_KW)]
    kr_v1 = sum(1 for r in kr_ref if r["v1_asset"] == "국내주식")
    kr_v2 = sum(1 for r in kr_ref if r["hybrid_primary_asset"] == "국내주식")

    region_d = _dist(rows, "region")

    L = ["# research_v2 FULL backtest — 2026-05 (전수)", "",
         f"- 분류: {n}건 (keyword 샘플링 없음). LLM region v2 prompt + validator + hybrid.",
         "- production write 0 (adapted 미수정). flag OFF 유지.", "",
         "## 1. validator / 메커니즘", "",
         "| check | value |", "| --- | ---: |",
         f"| asset_enum_valid_rate | {asset_valid}/{n} ({asset_valid/n*100:.1f}%) |",
         f"| region_enum_valid_rate | {region_valid}/{n} ({region_valid/n*100:.1f}%) |",
         f"| fallback_rate | {fallback}/{n} ({fallback/n*100:.1f}%) |",
         f"| unknown_rate (hybrid None) | {unknown}/{n} ({unknown/n*100:.1f}%) |",
         f"| multi_asset_rate | {multi}/{n} ({multi/n*100:.1f}%) |",
         f"| consistency_violation_rate | {conflict}/{n} ({conflict/n*100:.1f}%) |",
         "", "## 2. 자산 분포 정상화 (v1 → v2 hybrid)", "",
         "| asset | v1 count | v1 % | v2 count | v2 % | Δ%p |",
         "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for a in sorted(set(v1d) | set(v2d), key=lambda x: -(v2d.get(x, 0))):
        v1p, v2p = v1d.get(a, 0) / v1_dom * 100, v2d.get(a, 0) / v2_dom * 100
        L.append(f"| {a} | {v1d.get(a,0)} | {v1p:.1f}% | {v2d.get(a,0)} | {v2p:.1f}% | {v2p-v1p:+.1f} |")
    L += ["", "## 3. KR-equity recovery (title KR주식 keyword reference)", "",
          f"- reference set (코스피/삼성/하이닉스/반도체/마감/팔천피 등): {len(kr_ref)}건",
          f"- v1 국내주식 분류: {kr_v1}/{len(kr_ref)} ({kr_v1/(len(kr_ref) or 1)*100:.1f}%)",
          f"- **v2 국내주식 분류: {kr_v2}/{len(kr_ref)} ({kr_v2/(len(kr_ref) or 1)*100:.1f}%)**",
          "", "## 4. region 분포", "",
          "| region | count | % |", "| --- | ---: | ---: |"]
    for r, c in region_d.most_common():
        L.append(f"| {r} | {c} | {c/n*100:.1f}% |")
    L += ["", "## 5. acceptance 판정 (자동 proxy)", "",
          "| 기준 | 목표 | 실측 | 판정 |", "| --- | --- | --- | --- |",
          f"| KR 주식 국내주식 정분류 | ≥90% | {kr_v2/(len(kr_ref) or 1)*100:.1f}% | {'PASS' if kr_v2/(len(kr_ref) or 1)>=0.9 else 'CHECK'} |",
          f"| 국내주식 비중 정상화 (v1→v2) | 상승 | {v1d.get('국내주식',0)/v1_dom*100:.1f}%→{v2d.get('국내주식',0)/v2_dom*100:.1f}% | {'PASS' if v2d.get('국내주식',0)/v2_dom>v1d.get('국내주식',0)/v1_dom else 'CHECK'} |",
          f"| asset enum valid | ≥95% | {asset_valid/n*100:.1f}% | {'PASS' if asset_valid/n>=0.95 else 'CHECK'} |",
          f"| fallback 과도 아님 | <30% | {fallback/n*100:.1f}% | {'PASS' if fallback/n<0.3 else 'CHECK'} |"]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    # spot-check CSV: KR equity ref + conflict + region UNKNOWN 우선 20건
    spot = []
    seen = set()
    for pool in (kr_ref, [r for r in rows if r["consistency_warning"]],
                 [r for r in rows if r["region"] == "UNKNOWN"]):
        for r in pool:
            if r["article_id"] not in seen and len(spot) < 30:
                spot.append(r); seen.add(r["article_id"])
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        wcsv = csv.writer(fh)
        wcsv.writerow(["article_id", "title", "category", "region", "sector",
                       "v1_asset", "rule_asset", "llm_primary_asset", "hybrid_primary_asset",
                       "affected_assets", "consistency_warning",
                       "MANUAL_region", "MANUAL_primary_asset", "result", "note"])
        for r in spot:
            aa = "; ".join(f"{c['asset']}:{c['impact']}:{c['role']}" for c in r["affected_assets"])
            wcsv.writerow([r["article_id"], r["title"], r["category"], r["region"], r["sector"],
                           r["v1_asset"], r["rule_asset"], r["llm_primary_asset"],
                           r["hybrid_primary_asset"], aa, r["consistency_warning"] or "",
                           "", "", "", ""])


if __name__ == "__main__":
    raise SystemExit(main())
