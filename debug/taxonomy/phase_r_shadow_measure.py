# -*- coding: utf-8 -*-
"""Phase R-3 — flag ON shadow 측정 (no-overwrite harness, dry 100건).

R-1(§8 route_by_region 보정) + R-2(production research_v2 prompt/validator/hybrid
resolver) 가 들어간 **production 코드 경로**를 flag ON 으로 실측한다. 운영 산출물
0 overwrite — 출력은 debug/taxonomy/phase_r_shadow/ 에만.

production 함수 사용 (dry 카피 아님):
  news_classifier._build_research_classification_prompt_v2  (R-2 prompt)
  news_classifier._apply_classification_results            (R-2 passthrough+validator)
  asset_taxonomy.article_primary_asset / _v2               (v1 / R-2 hybrid resolver)

측정(설계 §5.2): v1 vs v2 asset 분포 / KR-equity recovery / enum valid / route_source
(llm/rule/v1/none) / §8 효과(지정학 오라우팅) / multi-asset / unknown.

flag(MR_RESEARCH_REGION_V2)는 이 프로세스 환경변수로만 ON — 운영 배치 미설정.

usage:  python -m debug.taxonomy.phase_r_shadow_measure
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# flag ON — import 전에 설정 (resolver/prompt 분기). 프로세스 국소.
os.environ["MR_RESEARCH_REGION_V2"] = "1"

from market_research.core import constants  # noqa: E402
from market_research.analyze.news_classifier import (  # noqa: E402
    _build_research_classification_prompt_v2, _apply_classification_results,
)
from market_research.core.asset_taxonomy import (  # noqa: E402
    article_primary_asset, article_primary_asset_v2, route_by_region,
    _remap_to_8class,
)
import anthropic  # noqa: E402

ADAPTED = REPO / "market_research/data/naver_research/adapted/2026-05.json"
OUTDIR = REPO / "debug/taxonomy/phase_r_shadow"
SAMPLE_N = 100
BATCH = 20
MODEL = "claude-haiku-4-5-20251001"

# KR-equity reference set 키워드 (backtest report 기준)
_KR_EQ_REF = ("코스피", "코스닥", "kospi", "kosdaq", "삼성전자", "하이닉스",
              "반도체", "팔천피", "8천피", "국내증시", "국내 주식")


def _has_desc(a):
    return bool((a.get("description") or "").strip())


def _is_kr_eq_ref(a):
    t = ((a.get("title") or "") + " " + (a.get("description") or "")).lower()
    return any(k in t for k in _KR_EQ_REF)


def _route_source(a):
    """production resolver priority 추적 (article_primary_asset_v2 와 동일 순서)."""
    if a.get("_primary_asset_v2"):
        return "llm"
    # rule: per-topic route_by_region 가 뭔가 내면 rule
    for t in a.get("_classified_topics") or []:
        if isinstance(t, dict) and route_by_region(t.get("region") or "UNKNOWN", t.get("topic")):
            return "rule"
    if article_primary_asset(a):
        return "v1"
    return "none"


def _call_llm(cli, chunk):
    """production v2 prompt 로 LLM 분류 → results list. 실패 시 halving-retry."""
    try:
        prompt = _build_research_classification_prompt_v2(chunk)
        resp = cli.messages.create(model=MODEL, max_tokens=8000,
                                   messages=[{"role": "user", "content": prompt}])
        txt = resp.content[0].text.strip()
        if txt.startswith("```"):
            txt = txt.split("```")[1]
            if txt.startswith("json"):
                txt = txt[4:]
            txt = txt.strip()
        obj = json.loads(txt)
        results = obj if isinstance(obj, list) else obj.get("items", [])
        return results, resp.usage.output_tokens
    except Exception as exc:
        if len(chunk) <= 2:
            print(f"    [chunk {len(chunk)}건 실패 {type(exc).__name__} — 빈 처리]", flush=True)
            return [], 0
        mid = len(chunk) // 2
        l, lt = _call_llm(cli, chunk[:mid])
        r, rt = _call_llm(cli, chunk[mid:])
        # id 재정렬 (각 호출은 1-based id 를 chunk 기준으로 부여)
        for it in r:
            if isinstance(it, dict) and isinstance(it.get("id"), int):
                it["id"] += mid
        return l + r, lt + rt


def main():
    rd = json.loads(ADAPTED.read_text(encoding="utf-8"))
    arts_all = [a for a in (rd["articles"] if isinstance(rd, dict) else rd) if _has_desc(a)]
    # 결정적 strided sample (시간/순서 편향 완화, 재현 가능)
    stride = max(1, len(arts_all) // SAMPLE_N)
    sample = arts_all[::stride][:SAMPLE_N]
    print(f"2026-05 research {len(arts_all)}건 → strided sample {len(sample)}건 (stride={stride})")

    cli = anthropic.Anthropic(api_key=constants.ANTHROPIC_API_KEY)
    out_tok = 0
    t0 = time.time()
    for b0 in range(0, len(sample), BATCH):
        chunk = sample[b0:b0 + BATCH]
        results, tok = _call_llm(cli, chunk)
        out_tok += tok
        # production passthrough (id 1-based → chunk 위치)
        _apply_classification_results(chunk, results)
        print(f"  batch {b0//BATCH+1}/{(len(sample)+BATCH-1)//BATCH} "
              f"out={out_tok} {time.time()-t0:.0f}s", flush=True)

    rows = []
    for a in sample:
        v1 = article_primary_asset(a)
        v2 = article_primary_asset_v2(a)
        rows.append({
            "article_id": a.get("_article_id"),
            "title": (a.get("title") or "")[:80],
            "category": a.get("_raw_category", ""),
            "broker": a.get("_raw_broker", ""),
            "topics": [t.get("topic") for t in (a.get("_classified_topics") or [])
                       if isinstance(t, dict)],
            "regions_v2": a.get("_regions_v2"),
            "v1_asset": v1,
            "v2_asset": v2,
            "llm_primary_v2": a.get("_primary_asset_v2"),
            "affected_v2": [c.get("asset_class") for c in (a.get("_affected_assets_v2") or [])],
            "route_source": _route_source(a),
            "is_kr_eq_ref": _is_kr_eq_ref(a),
        })

    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _report(rows, out_tok, time.time() - t0)
    _write_spotcheck(rows)
    print(f"분류 {len(rows)}건, out_tokens={out_tok}, {time.time()-t0:.0f}s → {OUTDIR}")
    return 0


def _report(rows, out_tok, secs):
    n = len(rows)
    def dist(key):
        c = Counter(r[key] for r in rows if r.get(key))
        return c

    v1d, v2d = dist("v1_asset"), dist("v2_asset")
    src = Counter(r["route_source"] for r in rows)
    kr_ref = [r for r in rows if r["is_kr_eq_ref"]]
    kr_v1 = sum(1 for r in kr_ref if r["v1_asset"] == "국내주식")
    kr_v2 = sum(1 for r in kr_ref if r["v2_asset"] == "국내주식")
    multi = sum(1 for r in rows if len(r["affected_v2"]) >= 2)
    unknown = sum(1 for r in rows if not r["v2_asset"])
    # §8 효과 — 지정학 topic 보유 기사가 v2 에서 원자재(금/에너지)로 가는지
    geo = [r for r in rows if "지정학" in (r["topics"] or [])]
    geo_to_commodity = sum(1 for r in geo if r["v2_asset"] in ("원자재에너지", "금대체", "원자재금"))
    asset_classes = sorted(set(v1d) | set(v2d))

    L = ["# Phase R-3 — flag ON shadow 측정 (production 경로, dry 100건)", "",
         f"- sample={n}건, out_tokens={out_tok}, {secs:.0f}s, model={MODEL}",
         f"- flag MR_RESEARCH_REGION_V2=1 (프로세스 국소), 운영 산출물 0 overwrite", "",
         "## route_source 분포 (hybrid resolver)",
         "| source | n | % |", "|---|--:|--:|"]
    for k in ("llm", "rule", "v1", "none"):
        L.append(f"| {k} | {src.get(k,0)} | {100*src.get(k,0)/n:.1f}% |")
    L += ["", "## asset 분포 (v1 → v2)", "| asset | v1 | v2 |", "|---|--:|--:|"]
    for a in asset_classes:
        L.append(f"| {a} | {v1d.get(a,0)} | {v2d.get(a,0)} |")
    L += ["", "## 게이트 metric",
          f"- KR-equity reference set: {len(kr_ref)}건. 국내주식 정분류 v1={kr_v1} "
          f"({100*kr_v1/max(len(kr_ref),1):.1f}%) → v2={kr_v2} "
          f"({100*kr_v2/max(len(kr_ref),1):.1f}%)",
          f"- multi-asset (affected≥2): {multi} ({100*multi/n:.1f}%)",
          f"- unknown (v2 primary 없음): {unknown} ({100*unknown/n:.1f}%)",
          f"- enum: v2 asset 은 resolver 가 selector label 만 반환 (enum 위반 0 보장)",
          "",
          "## §8 효과 (지정학 오라우팅)",
          f"- 지정학 topic 보유 기사: {len(geo)}건. 그중 v2 가 원자재(금/에너지)로 간 건수: "
          f"{geo_to_commodity} (낮을수록 §8 None화 효과 — LLM affected/보고대상 우선)",
          ""]
    (OUTDIR / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def _write_spotcheck(rows):
    """30건 spot-check CSV — expected_* 는 Claude 가 별도 단계에서 초안 라벨 작성."""
    import csv
    stride = max(1, len(rows) // 30)
    pick = rows[::stride][:30]
    with (OUTDIR / "spotcheck.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["article_id", "title", "category", "topics", "regions_v2",
                    "v1_asset", "v2_asset", "route_source",
                    "expected_asset", "expected_region", "expected_reason", "verdict"])
        for r in pick:
            w.writerow([r["article_id"], r["title"], r["category"],
                        "|".join(r["topics"] or []), "|".join(r["regions_v2"] or []),
                        r["v1_asset"], r["v2_asset"], r["route_source"],
                        "", "", "", ""])  # expected_* = Claude 초안 단계에서 채움


if __name__ == "__main__":
    raise SystemExit(main())
