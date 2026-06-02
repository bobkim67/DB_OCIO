# -*- coding: utf-8 -*-
"""마감시황 leak 6건만 재분류 (rule 7 region-pinning patch 효과 확인).

full backtest 재실행 0. leak = 제목 "국내…마감 시황"인데 hybrid_primary != 국내주식 (region US/GLOBAL 샘).
adapted read-only. patched dry.USER_TMPL 사용. 결과 debug/taxonomy/research_v2_leak6_recheck.{md,json}.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "debug" / "taxonomy"))

import research_v2_dry_classify as dry  # noqa: E402 (rule 7 patched USER_TMPL)
from market_research.core import constants  # noqa: E402
import anthropic  # noqa: E402

ADAPTED = REPO / "market_research/data/naver_research/adapted/2026-05.json"
RESULT = REPO / "debug/taxonomy/research_v2_backtest_result.json"
OUT_MD = REPO / "debug/taxonomy/research_v2_leak6_recheck.md"
OUT_JSON = REPO / "debug/taxonomy/research_v2_leak6_recheck.json"
ALLOWED_8 = dry.ALLOWED_ASSET_8


def _is_kr_wrap(title: str) -> bool:
    t = (title or "")
    return ("국내" in t) and (("마감 시황" in t) or ("마감시황" in t) or ("장마감" in t) or ("마감" in t))


def main():
    back = json.loads(RESULT.read_text(encoding="utf-8"))
    leak = [r for r in back if _is_kr_wrap(r["title"]) and r["hybrid_primary_asset"] != "국내주식"]
    print(f"leak 식별: {len(leak)}건")
    for r in leak:
        print(f"  [{r['region']}→{r['hybrid_primary_asset']}] {r['title'][:48]}")

    # adapted 에서 원본 article 매칭 (v1 routing + 재전송 텍스트)
    rd = json.loads(ADAPTED.read_text(encoding="utf-8"))
    arts = {a["_article_id"]: a for a in (rd["articles"] if isinstance(rd, dict) else rd)}
    chunk = [arts[r["article_id"]] for r in leak if r["article_id"] in arts]

    cli = anthropic.Anthropic(api_key=constants.ANTHROPIC_API_KEY)
    items, tok = dry.call_llm(cli, chunk, 0)
    bymap = {it.get("idx"): it for it in items}
    print(f"재분류 완료 (out={tok})")

    bbyid = {r["article_id"]: r for r in leak}
    rows = []
    for j, a in enumerate(chunk):
        raw = bymap.get(j, {})
        clean = dry.validate_item(raw)
        r3 = dry.resolve_3way(clean, a)
        before = bbyid[a["_article_id"]]
        aa = [{"asset": c["asset"], "impact": c["impact"], "role": c["role"]} for c in clean["affected_assets"]]
        rows.append({
            "article_id": a["_article_id"], "title": a.get("title", ""),
            "before_region": before["region"], "after_region": clean["region"],
            "before_primary": before["hybrid_primary_asset"],
            "after_primary": r3["hybrid_primary_asset"],
            "affected_assets_after": aa,
            "after_route_source": r3["route_source"],
            "after_consistency_warning": r3["consistency_warning"],
            "warnings": clean["warnings"],
            "pass": r3["hybrid_primary_asset"] == "국내주식",
        })

    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    n = len(rows)
    enum_ok = sum(1 for r in rows if all(c["asset"] in ALLOWED_8 for c in r["affected_assets_after"]))
    region_ok = sum(1 for r in rows if r["after_region"] in dry.REGION_SET)
    fixed = sum(1 for r in rows if r["pass"])
    driver_sec = sum(1 for r in rows if r["pass"] and len(r["affected_assets_after"]) >= 2)

    L = ["# 마감시황 leak 6건 recheck (rule 7 region-pinning patch)", "",
         f"- leak {n}건 재분류 (full backtest 재실행 X). adapted read-only.", "",
         "## 결과", "",
         "| id | title | before_primary | after_primary | affected_assets_after | pass |",
         "| --- | --- | --- | --- | --- | --- |"]
    for i, r in enumerate(rows):
        aa = ", ".join(f"{c['asset']}({c['role'][:4]})" for c in r["affected_assets_after"]) or "(없음)"
        L.append(f"| {i} | {r['title'][:34]} | {r['before_region']}/{r['before_primary']} | "
                 f"{r['after_region']}/{r['after_primary']} | {aa} | {'✅' if r['pass'] else '❌'} |")
    L += ["", "## 회귀 체크", "",
          "| 항목 | 결과 |", "| --- | --- |",
          f"| primary 국내주식 교정 | {fixed}/{n} |",
          f"| 교정건 driver secondary 유지 (affected≥2) | {driver_sec}/{fixed} |",
          f"| asset enum valid 100% | {enum_ok}/{n} |",
          f"| region enum valid 100% | {region_ok}/{n} |",
          f"| fallback (route_source!=llm) | {sum(1 for r in rows if r['after_route_source']!='llm')}/{n} |"]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"교정 {fixed}/{n}, enum {enum_ok}/{n}, region {region_ok}/{n}")
    print(f"→ {OUT_MD.name} / {OUT_JSON.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
