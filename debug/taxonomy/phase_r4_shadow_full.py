# -*- coding: utf-8 -*-
"""Phase R-4 — flag ON shadow 측정 (no-overwrite harness, **full scale**).

R-3(dry 100건 strided)의 일반화 버전. R-1(§8 route_by_region 보정) + R-2(production
research_v2 prompt/validator/hybrid resolver) 가 들어간 production 코드 경로를 flag ON
으로 **2026-05 전수**(1,142건 규모) 실측한다. 운영 산출물 0 overwrite — 출력은
debug/taxonomy/phase_r_shadow_full/ 에만 (R-3 의 phase_r_shadow/ 와 분리, 재현성 보존).

production 함수 사용 (dry 카피 아님):
  news_classifier._build_research_classification_prompt_v2  (R-2 prompt)
  news_classifier._apply_classification_results            (R-2 passthrough+validator)
  asset_taxonomy.article_primary_asset / _v2               (v1 / R-2 hybrid resolver)

측정(설계 §5.2): v1 vs v2 asset 분포 / KR-equity recovery / enum valid / route_source
(llm/rule/v1/none = fallback rate) / consistency violation(LLM≠rule) / §8 효과(지정학
오라우팅) / multi-asset / unknown. + 카테고리별 자산 분포 breakdown.

※ 설계 §5.2 의 'selected events drift'(base wiki Gate2) / 'context pack drift' 두 메트릭은
  base-wiki Gate2 선택 + context pack dry harness 가 추가로 필요해 이 run 의 범위에서 제외
  한다. 운영 적용(§5.4) acceptance 게이트는 asset enum/KR-equity/fallback/국내주식 비중/§8
  으로만 정의되어 있어 본 run 으로 판정 가능. events/pack drift 는 별 sub-step.

flag(MR_RESEARCH_REGION_V2)는 이 프로세스 환경변수로만 ON — 운영 배치 미설정.

usage:
  python -m debug.taxonomy.phase_r4_shadow_full              # 전수
  python -m debug.taxonomy.phase_r4_shadow_full --sample 100 # 재검증용 strided 샘플
  python -m debug.taxonomy.phase_r4_shadow_full --estimate   # LLM 호출 없이 건수/예상비용만
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
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
)

ADAPTED = REPO / "market_research/data/naver_research/adapted/2026-05.json"
OUTDIR = REPO / "debug/taxonomy/phase_r_shadow_full"
BATCH = 20
MODEL = "claude-haiku-4-5-20251001"

# KR-equity reference set 키워드 (R-3 backtest report 기준 동일)
_KR_EQ_REF = ("코스피", "코스닥", "kospi", "kosdaq", "삼성전자", "하이닉스",
              "반도체", "팔천피", "8천피", "국내증시", "국내 주식")


def _has_desc(a):
    return bool((a.get("description") or "").strip())


def _is_kr_eq_ref(a):
    t = ((a.get("title") or "") + " " + (a.get("description") or "")).lower()
    return any(k in t for k in _KR_EQ_REF)


def _rule_asset(a):
    """per-topic route_by_region argmax (intensity 가중) — consistency 비교용 rule 결과."""
    agg = defaultdict(float)
    for t in a.get("_classified_topics") or []:
        if not isinstance(t, dict):
            continue
        asset = route_by_region(t.get("region") or "UNKNOWN", t.get("topic"))
        if asset is None:
            continue
        try:
            w = abs(float(t.get("intensity", 5))) / 10.0
        except (ValueError, TypeError):
            w = 0.5
        agg[asset] += w
    return max(agg, key=agg.get) if agg else None


def _route_source(a):
    """production resolver priority 추적 (article_primary_asset_v2 와 동일 순서)."""
    if a.get("_primary_asset_v2"):
        return "llm"
    if _rule_asset(a):
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
        return results, resp.usage.output_tokens, resp.usage.input_tokens
    except Exception as exc:
        if len(chunk) <= 2:
            print(f"    [chunk {len(chunk)}건 실패 {type(exc).__name__} — 빈 처리]", flush=True)
            return [], 0, 0
        mid = len(chunk) // 2
        l, lt, li = _call_llm(cli, chunk[:mid])
        r, rt, ri = _call_llm(cli, chunk[mid:])
        for it in r:
            if isinstance(it, dict) and isinstance(it.get("id"), int):
                it["id"] += mid
        return l + r, lt + rt, li + ri


def _load_sample(sample_n):
    rd = json.loads(ADAPTED.read_text(encoding="utf-8"))
    arts_all = [a for a in (rd["articles"] if isinstance(rd, dict) else rd) if _has_desc(a)]
    if sample_n and sample_n < len(arts_all):
        stride = max(1, len(arts_all) // sample_n)
        sample = arts_all[::stride][:sample_n]
        print(f"2026-05 research {len(arts_all)}건 → strided sample {len(sample)}건 (stride={stride})")
    else:
        sample = arts_all
        print(f"2026-05 research {len(arts_all)}건 → 전수 측정")
    return sample, len(arts_all)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="phase_r4_shadow_full")
    ap.add_argument("--sample", type=int, default=None,
                    help="strided 샘플 N (생략 시 전수)")
    ap.add_argument("--estimate", action="store_true",
                    help="LLM 호출 없이 건수/예상 토큰·비용만 출력")
    args = ap.parse_args(argv)

    if not ADAPTED.exists():
        print(f"[ERROR] 입력 없음: {ADAPTED}\n  먼저 스크래핑+adapter 실행 필요.")
        return 1

    sample, total = _load_sample(args.sample)

    if args.estimate:
        # R-3 실측 비율: 100건 → out 16,022 tok (~160 tok/건). input 은 batch prompt 규모.
        est_out = int(len(sample) * 160)
        print(f"  배치 수: {(len(sample)+BATCH-1)//BATCH} (BATCH={BATCH})")
        print(f"  예상 output tokens ≈ {est_out:,} (R-3 ~160 tok/건 기준)")
        print(f"  ※ Haiku 4.5 가격은 실행 후 usage 로 실제 비용 산정. R-3 100건 ≈ $0.1.")
        return 0

    cli = constants and __import__("anthropic").Anthropic(api_key=constants.ANTHROPIC_API_KEY)
    out_tok = in_tok = 0
    t0 = time.time()
    nb = (len(sample) + BATCH - 1) // BATCH
    for bi, b0 in enumerate(range(0, len(sample), BATCH), 1):
        chunk = sample[b0:b0 + BATCH]
        results, ot, it = _call_llm(cli, chunk)
        out_tok += ot
        in_tok += it
        _apply_classification_results(chunk, results)
        print(f"  batch {bi}/{nb} in={in_tok} out={out_tok} {time.time()-t0:.0f}s", flush=True)

    rows = []
    for a in sample:
        v1 = article_primary_asset(a)
        v2 = article_primary_asset_v2(a)
        rule = _rule_asset(a)
        rows.append({
            "article_id": a.get("_article_id") or a.get("_raw_dedupe_key"),
            "title": (a.get("title") or "")[:80],
            "category": a.get("_raw_category", ""),
            "broker": a.get("_raw_broker", ""),
            "topics": [t.get("topic") for t in (a.get("_classified_topics") or [])
                       if isinstance(t, dict)],
            "regions_v2": a.get("_regions_v2"),
            "v1_asset": v1,
            "v2_asset": v2,
            "rule_asset": rule,
            "llm_primary_v2": a.get("_primary_asset_v2"),
            "affected_v2": [c.get("asset_class") for c in (a.get("_affected_assets_v2") or [])],
            "route_source": _route_source(a),
            "is_kr_eq_ref": _is_kr_eq_ref(a),
        })

    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _report(rows, out_tok, in_tok, time.time() - t0, total)
    _write_spotcheck(rows)
    print(f"분류 {len(rows)}건, in={in_tok} out={out_tok}, {time.time()-t0:.0f}s → {OUTDIR}")
    return 0


def _report(rows, out_tok, in_tok, secs, total):
    n = len(rows)

    def dist(key):
        return Counter(r[key] for r in rows if r.get(key))

    v1d, v2d = dist("v1_asset"), dist("v2_asset")
    src = Counter(r["route_source"] for r in rows)
    kr_ref = [r for r in rows if r["is_kr_eq_ref"]]
    kr_v1 = sum(1 for r in kr_ref if r["v1_asset"] == "국내주식")
    kr_v2 = sum(1 for r in kr_ref if r["v2_asset"] == "국내주식")
    multi = sum(1 for r in rows if len(r["affected_v2"]) >= 2)
    unknown = sum(1 for r in rows if not r["v2_asset"])
    # consistency violation: LLM 경로(llm)인데 rule 결과와 다른 건
    llm_rows = [r for r in rows if r["route_source"] == "llm" and r["rule_asset"]]
    conflict = sum(1 for r in llm_rows if r["v2_asset"] != r["rule_asset"])
    # §8 효과
    geo = [r for r in rows if "지정학" in (r["topics"] or [])]
    geo_to_commodity = sum(1 for r in geo if r["v2_asset"] in ("원자재에너지", "금대체", "원자재금"))
    asset_classes = sorted(set(v1d) | set(v2d))
    cats = sorted({r["category"] for r in rows if r["category"]})

    L = ["# Phase R-4 — flag ON shadow 측정 (production 경로, **full scale**)", "",
         f"- sample={n}건 (2026-05 전수 후보 {total}건), in_tokens={in_tok}, "
         f"out_tokens={out_tok}, {secs:.0f}s, model={MODEL}",
         f"- flag MR_RESEARCH_REGION_V2=1 (프로세스 국소), 운영 산출물 0 overwrite",
         f"- 재스크래핑 코퍼스 (R-3 와 코퍼스 동일 보장 아님 — drift 해석 시 유의)", "",
         "## route_source 분포 (hybrid resolver, fallback rate)",
         "| source | n | % |", "|---|--:|--:|"]
    for k in ("llm", "rule", "v1", "none"):
        L.append(f"| {k} | {src.get(k,0)} | {100*src.get(k,0)/n:.1f}% |")
    L += [f"", f"- fallback(rule+v1+none) = {100*(n-src.get('llm',0))/n:.1f}% "
          f"(게이트 <30%)", ""]
    L += ["## asset 분포 (v1 → v2)", "| asset | v1 | v1% | v2 | v2% |", "|---|--:|--:|--:|--:|"]
    for a in asset_classes:
        L.append(f"| {a} | {v1d.get(a,0)} | {100*v1d.get(a,0)/n:.1f}% "
                 f"| {v2d.get(a,0)} | {100*v2d.get(a,0)/n:.1f}% |")
    L += ["", "## 게이트 metric",
          f"- KR-equity reference set: {len(kr_ref)}건. 국내주식 정분류 v1={kr_v1} "
          f"({100*kr_v1/max(len(kr_ref),1):.1f}%) → v2={kr_v2} "
          f"({100*kr_v2/max(len(kr_ref),1):.1f}%) (게이트 ≥90%, keyword ref 라 실제 더 높음)",
          f"- multi-asset (affected≥2): {multi} ({100*multi/n:.1f}%)",
          f"- unknown (v2 primary 없음): {unknown} ({100*unknown/n:.1f}%)",
          f"- consistency violation (LLM≠rule, llm 경로 {len(llm_rows)}건 중): "
          f"{conflict} ({100*conflict/max(len(llm_rows),1):.1f}%) — trace only(차단 X)",
          f"- enum: v2 asset 은 resolver 가 selector label 만 반환 (enum 위반 0 보장)",
          "",
          "## §8 효과 (지정학 오라우팅)",
          f"- 지정학 topic 보유 기사: {len(geo)}건. 그중 v2 가 원자재(금/에너지)로 간 건수: "
          f"{geo_to_commodity} ({100*geo_to_commodity/max(len(geo),1):.1f}%, "
          f"낮을수록 §8 None화 효과)",
          "",
          "## 카테고리별 v2 자산 분포 (상위)"]
    for cat in cats:
        cr = [r for r in rows if r["category"] == cat]
        cd = Counter(r["v2_asset"] for r in cr if r["v2_asset"])
        top = ", ".join(f"{a}={c}" for a, c in cd.most_common(4))
        L.append(f"- **{cat}** ({len(cr)}건): {top}")
    L += ["",
          "## 범위 제외 (별 sub-step)",
          "- selected events drift (base wiki Gate2) / context pack drift: 본 run 미포함.",
          "  acceptance 게이트(§5.4)는 위 metric 으로 판정 가능. events/pack drift 는 별도.",
          ""]
    (OUTDIR / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def _write_spotcheck(rows):
    """spot-check CSV — expected_* 는 Claude 가 별도 단계에서 초안 라벨 작성. 전수면 40건."""
    import csv
    target = 40
    stride = max(1, len(rows) // target)
    pick = rows[::stride][:target]
    with (OUTDIR / "spotcheck.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["article_id", "title", "category", "topics", "regions_v2",
                    "v1_asset", "v2_asset", "rule_asset", "route_source",
                    "expected_asset", "expected_region", "expected_reason", "verdict"])
        for r in pick:
            w.writerow([r["article_id"], r["title"], r["category"],
                        "|".join(r["topics"] or []), "|".join(r["regions_v2"] or []),
                        r["v1_asset"], r["v2_asset"], r["rule_asset"], r["route_source"],
                        "", "", "", ""])


if __name__ == "__main__":
    raise SystemExit(main())
