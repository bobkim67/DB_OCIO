# -*- coding: utf-8 -*-
"""research_v2 LLM asset-mapping DRY classification (40-sample).

설계: docs/research_taxonomy_v2_llm_asset_mapping.md / debug/taxonomy/research_v2_*.md
- 2026-05 adapted research read-only 로드 → 40건 sample (테마 9 + 복합 + 팔천피)
- research_v2 prompt (region × sector × affected_assets[] × primary) Haiku dry 분류
- validator prototype (enum / floor / remap→8class / primary∈affected / role=1 / consistency)
- rule-only / LLM-only / hybrid 3-way 비교
- 산출: research_v2_sample_result.{json,md} / research_v2_manual_review.csv / research_v2_validator_report.md

production write 0. consumer wiring 0. route_by_region/v1 미수정 (read-only import).
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

from market_research.core import constants  # noqa: E402
from market_research.core.asset_taxonomy import (  # noqa: E402  (read-only)
    route_by_region, article_primary_asset, REGION_SET,
)
from market_research.analyze.news_classifier import TOPIC_TAXONOMY  # noqa: E402
import anthropic  # noqa: E402

ADAPTED = REPO / "market_research/data/naver_research/adapted/2026-05.json"
OUT_JSON = REPO / "debug/taxonomy/research_v2_sample_result.json"
OUT_MD = REPO / "debug/taxonomy/research_v2_sample_result.md"
OUT_CSV = REPO / "debug/taxonomy/research_v2_manual_review.csv"
OUT_VAL = REPO / "debug/taxonomy/research_v2_validator_report.md"

# ── enum (8-class = claim 다운스트림 계약 source of truth) ──
ALLOWED_ASSET_8 = {"국내주식", "해외주식", "국내채권", "해외채권",
                   "크레딧", "현금성", "환율(FX)", "원자재금"}
SECTOR_SET = set(TOPIC_TAXONOMY)
DIRECTIONS = {"positive", "negative", "neutral", "mixed", "unknown"}

# selector 편의 라벨 → 8-class collapse (design §1.A / §5)
REMAP_8 = {
    "환율": "환율(FX)", "환율(FX)": "환율(FX)",
    "금대체": "원자재금", "원자재에너지": "원자재금", "원자재금": "원자재금",
    "크립토": None, "기타": None, "UNKNOWN": None, "현금성": "현금성",
    "크레딧": "크레딧",
    "국내주식": "국내주식", "해외주식": "해외주식",
    "국내채권": "국내채권", "해외채권": "해외채권",
}
FLOOR = {"asset": 0.60, "primary": 0.70, "region": 0.60, "sector": 0.60}


def remap_to_8class(a):
    """8-class 안이면 그대로, selector 편의 라벨이면 collapse, 그 외 None."""
    if a is None:
        return None
    if a in ALLOWED_ASSET_8:
        return a
    return REMAP_8.get(a, None)


# ══════════════════════════════════════════
# validator prototype (design §4.3)
# ══════════════════════════════════════════

def validate_item(item: dict) -> dict:
    """LLM 출력 1건 검증 → clean dict + warnings. (차단 hard / 경고 soft 구분)."""
    w: list[str] = []

    # region (hard enum + floor)
    region = item.get("region")
    rc = item.get("region_confidence")
    if region not in REGION_SET:
        w.append(f"region_enum_invalid:{region}")
        region = "UNKNOWN"
    elif rc is not None and rc < FLOOR["region"]:
        w.append(f"region_low_conf:{rc}")
        region = "UNKNOWN"

    # sectors (hard enum; sector + sectors[] 합집합)
    raw_sectors = list(item.get("sectors") or [])
    sec0 = item.get("sector")
    if isinstance(sec0, str) and sec0 and sec0 not in raw_sectors:
        raw_sectors.insert(0, sec0)
    sectors = []
    for s in raw_sectors:
        if not isinstance(s, str):
            w.append(f"sector_not_str:{type(s).__name__}")
            continue
        if s in SECTOR_SET:
            if s not in sectors:
                sectors.append(s)
        else:
            w.append(f"sector_enum_invalid:{s}")
    sector_primary = sec0 if (isinstance(sec0, str) and sec0 in SECTOR_SET) else (sectors[0] if sectors else None)

    # affected_assets (remap → 8class, floor, direction)
    clean = []
    for a in item.get("affected_assets") or []:
        if not isinstance(a, dict):
            w.append("affected_not_dict")
            continue
        raw = a.get("asset")
        asset = remap_to_8class(raw)
        if asset is None:
            w.append(f"asset_reject:{raw}")
            continue
        conf = a.get("confidence")
        if conf is not None and conf < FLOOR["asset"]:
            w.append(f"asset_low_conf:{asset}:{conf}")
            continue
        impact = a.get("impact")
        if impact not in DIRECTIONS:
            w.append(f"impact_invalid:{impact}")
            impact = "unknown"
        # 동일 asset 중복 → confidence max 유지
        clean.append({"asset": asset, "impact": impact,
                      "confidence": conf if conf is not None else 1.0,
                      "role": a.get("role", "secondary")})
    # dedupe asset keep-max-conf
    by_asset = {}
    for c in clean:
        if c["asset"] not in by_asset or (c["confidence"] or 0) > (by_asset[c["asset"]]["confidence"] or 0):
            by_asset[c["asset"]] = c
    clean = list(by_asset.values())
    # cap 3 (confidence desc)
    if len(clean) > 3:
        clean = sorted(clean, key=lambda c: -(c["confidence"] or 0))[:3]
        w.append("affected_trim_to_3")

    # primary (∈ affected, floor, role=1)
    primary = remap_to_8class(item.get("primary_asset"))
    assets_set = {c["asset"] for c in clean}
    if primary not in assets_set:
        if clean:
            primary = max(clean, key=lambda c: c["confidence"] or 0)["asset"]
            w.append("primary_reassigned")
        else:
            primary = None
    # primary floor
    if primary is not None:
        pconf = next((c["confidence"] for c in clean if c["asset"] == primary), None)
        if pconf is not None and pconf < FLOOR["primary"]:
            w.append(f"primary_low_conf:{pconf}")
    # role normalize → exactly 1 primary
    for c in clean:
        c["role"] = "primary" if c["asset"] == primary else "secondary"

    return {
        "region": region, "sector": sector_primary, "sectors": sectors,
        "direction": item.get("direction"), "intensity": item.get("intensity"),
        "affected_assets": clean, "primary_asset": primary,
        "rationale": item.get("rationale"), "evidence_span": item.get("evidence_span"),
        "warnings": w,
    }


def resolve_3way(clean: dict, orig_article: dict) -> dict:
    """rule-only / LLM-only / hybrid primary + conflict trace (design §5)."""
    region = clean["region"]
    sector = clean["sector"]
    rule_asset = remap_to_8class(route_by_region(region, sector)) if sector else None
    llm_primary = clean["primary_asset"]
    # v1 (벡터 argmax + KR 키워드) → remap
    v1 = remap_to_8class(article_primary_asset(orig_article))
    # hybrid: LLM valid → rule → v1 → None
    if llm_primary and clean["affected_assets"]:
        hybrid, src = llm_primary, "llm"
    elif rule_asset:
        hybrid, src = rule_asset, "rule"
    elif v1:
        hybrid, src = v1, "v1"
    else:
        hybrid, src = None, "none"
    warn = "rule_conflict" if (src == "llm" and rule_asset and rule_asset != hybrid) else None
    return {"rule_asset": rule_asset, "llm_primary_asset": llm_primary,
            "v1_asset": v1, "hybrid_primary_asset": hybrid,
            "route_source": src, "consistency_warning": warn}


# ══════════════════════════════════════════
# prompt (research_v2_llm_asset_prompt.md §2)
# ══════════════════════════════════════════

SYSTEM = (
    "당신은 DB형 퇴직연금 OCIO 운용보고용 리서치 분류기다. 증권사 리서치 리포트(제목+요약)를 "
    "'실제로 영향을 받는 시장·자산군' 관점에서 구조화한다. 발행 매체·언어가 아니라 영향받는 시장의 "
    "지역으로 region을 판정한다. 허용 enum 값만 사용하고 모호하면 confidence를 낮춘다. "
    "여러 자산군에 영향이면 affected_assets에 복수로, 가장 중심을 primary_asset(role=primary 1개)로 지정. "
    "추측을 단정으로 적지 말 것."
)

USER_TMPL = """다음 리서치 항목을 각각 분류하라.

## region (영향받는 시장의 지역 — 발행 매체 아님)
- KR: 한국 (삼성전자·SK하이닉스·코스피·한은·국고채·원화)
- US: 미국 (Fed·UST·나스닥·S&P·엔비디아)
- NON_US_OVERSEAS: 미국 외 해외 (유럽·일본·중국·신흥국)
- GLOBAL: 지역무관 글로벌·매크로 (유가·금·달러지수·원자재·환율·지정학)
- UNKNOWN: 판단 불가

## sector (14개 중): {sectors}

## asset (8개 중에서만 — 다운스트림 자산군 계약)
국내주식, 해외주식, 국내채권, 해외채권, 크레딧, 현금성, 환율(FX), 원자재금
- 에너지·원자재·금은 전부 "원자재금" 하나로. 비트코인/크립토는 자산군 부여 금지(affected_assets 비움).

## 규칙
1. 리서치는 대부분 거시 해석 → affected_assets 빈 배열은 예외(순수 종목 실적만).
2. region: 한국 반도체/코스피/수출 → KR (테크라고 무조건 US 아님). 환율·유가·금·달러·지정학 → GLOBAL.
3. affected_assets 최대 3개. 각 {{asset, impact, confidence, role}}. role=primary 정확히 1개.
   primary_asset은 affected_assets의 primary asset과 동일.
4. confidence 0.0~1.0 (모호하면 0.5 이하). regions 최대 2, sectors 최대 3.
5. rationale 한 줄, evidence_span 핵심 표현.
6. 시황/마감/데일리/전략 리포트처럼 특정 시장의 흐름을 설명하는 자료는, 글로벌 driver(지정학·유가·환율 등)
   또는 원인 자산보다 **보고 대상 시장/자산군**을 primary_asset으로 우선한다. driver는 affected_assets의
   secondary로 남긴다. 예) "국내주식 마감 — 미·이란 협상에 코스피 급등" → primary=국내주식,
   원자재금/환율(FX)는 secondary. "미국 증시 마감 — 유가 부담" → primary=해외주식, 원자재금 secondary.
7. 제목/리포트 유형이 "국내주식 마감", "국내증시 마감", "KOSPI/KOSDAQ 마감", "국내 주식시장 데일리"처럼
   특정 시장의 시황을 설명하면, 본문에 미국 증시·유가·지정학·달러 등 글로벌 driver가 많이 등장해도
   **region 과 primary_asset 을 보고 대상 시장으로 고정**한다. 예) 제목 "국내주식 마감 시황 — 미 증시 영향
   코스피 상승" → region=KR, primary=국내주식; 미 증시·글로벌 driver는 affected_regions/affected_assets 의
   secondary 로만 둔다. 반대로 제목이 "미 증시 마감"이면 region=US, primary=해외주식.

## 항목 목록
{items}

## 출력 (JSON 객체만, 그 외 텍스트 금지)
{{"items": [
  {{"idx": 0, "region": "KR", "region_confidence": 0.92, "affected_regions": ["KR"],
    "sector": "테크_AI_반도체", "sector_confidence": 0.91, "direction": "positive", "intensity": 8,
    "affected_assets": [{{"asset": "국내주식", "impact": "positive", "confidence": 0.93, "role": "primary"}}],
    "primary_asset": "국내주식", "regions": ["KR"], "sectors": ["테크_AI_반도체"],
    "rationale": "...", "evidence_span": "..."}}
]}}"""


def _topics_of(a):
    return [t.get("topic") for t in (a.get("_classified_topics") or []) if isinstance(t, dict) and t.get("topic")]


def build_sample(res):
    """40건: 테마 8 + 복합 + 팔천피. deterministic (salience desc)."""
    themes = {
        "한국주식반도체": (["코스피", "삼성전자", "하이닉스", "반도체", "팔천피", "8천피", "국내 주식 마감", "국내증시"], 5),
        "미국주식Fed":    (["s&p", "나스닥", "엔비디아", "미국 증시", "미국증시", "ai"], 4),
        "한은국내채권":   (["한국은행", "한은", "금통위", "국고채", "기준금리", "통안"], 4),
        "FedUS금리":      (["fed", "연준", "미국채", "ust", "인플레", "cpi", "fomc"], 4),
        "환율달러":       (["환율", "원/달러", "원달러", "달러", "dxy", " fx"], 4),
        "원자재유가금":   (["유가", "원유", "에너지", " 금 ", "금값", "원자재", "wti"], 4),
        "관세무역":       (["관세", "무역", "공급망", "수출"], 3),
        "크레딧스프레드": (["크레딧", "스프레드", "위험선호", "하이일드", " hy"], 3),
    }
    sample, seen = [], set()
    for theme, (kws, cap) in themes.items():
        cnt = 0
        for a in sorted(res, key=lambda x: -(x.get("_event_salience") or 0)):
            if cnt >= cap:
                break
            t = (a.get("title", "") + " " + (a.get("description") or "")).lower()
            if any(k in t for k in kws) and a["_article_id"] not in seen:
                a["_theme"] = theme
                sample.append(a); seen.add(a["_article_id"]); cnt += 1
    # 복합: v1 토픽 ≥2 (성격 상이) 우선, 고salience
    def _nature(top):
        if top in ("테크_AI_반도체", "경기_소비", "부동산"):
            return "EQ"
        if top in ("금리_채권", "통화정책", "물가_인플레이션"):
            return "RATE"
        return "X"
    cnt = 0
    for a in sorted(res, key=lambda x: -(x.get("_event_salience") or 0)):
        if cnt >= 9:
            break
        if a["_article_id"] in seen:
            continue
        natures = {_nature(t) for t in _topics_of(a)}
        if len(_topics_of(a)) >= 2 and len(natures) >= 2:
            a["_theme"] = "복합"
            sample.append(a); seen.add(a["_article_id"]); cnt += 1
    # 팔천피 강제
    for a in res:
        if "팔천피" in a.get("title", "") and a["_article_id"] not in seen:
            a["_theme"] = "한국주식반도체"; sample.append(a); seen.add(a["_article_id"])
    return sample


def call_llm(cli, chunk, base_idx):
    items = "\n".join(
        f'{base_idx+j}. [{a.get("_raw_category","")}/{a.get("source","")}] '
        f'{a.get("title","")} — {(a.get("description") or "")[:160]}'
        for j, a in enumerate(chunk))
    resp = cli.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=8000, system=SYSTEM,
        messages=[{"role": "user", "content": USER_TMPL.format(
            sectors=", ".join(TOPIC_TAXONOMY), items=items)}],
    )
    txt = resp.content[0].text.strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1]
        if txt.startswith("json"):
            txt = txt[4:]
        txt = txt.strip()
    obj = json.loads(txt)
    return obj.get("items", obj if isinstance(obj, list) else []), resp.usage.output_tokens


# theme → 기대 primary (자동 proxy; 수동 라벨로 교정 대상). 복합/관세는 multi → None.
THEME_EXPECT = {
    "한국주식반도체": "국내주식", "미국주식Fed": "해외주식",
    "한은국내채권": "국내채권", "FedUS금리": "해외채권",
    "환율달러": "환율(FX)", "원자재유가금": "원자재금",
    "관세무역": None, "크레딧스프레드": "크레딧", "복합": None,
}


def main():
    rd = json.loads(ADAPTED.read_text(encoding="utf-8"))
    res = [a for a in (rd["articles"] if isinstance(rd, dict) else rd)
           if (a.get("description") or "").strip()]
    sample = build_sample(res)
    print(f"sample: {len(sample)}건  buckets={dict(Counter(a['_theme'] for a in sample))}")

    cli = anthropic.Anthropic(api_key=constants.ANTHROPIC_API_KEY)
    raw_items, out_tok, BATCH = {}, 0, 20
    t0 = time.time()
    for b0 in range(0, len(sample), BATCH):
        chunk = sample[b0:b0 + BATCH]
        items, tok = call_llm(cli, chunk, b0)
        out_tok += tok
        for it in items:
            raw_items[it.get("idx")] = it
        print(f"  batch {b0//BATCH+1}: {len(chunk)}건 (out={tok})")
    print(f"LLM {time.time()-t0:.0f}s, out_tokens={out_tok}")

    rows = []
    for i, a in enumerate(sample):
        raw = raw_items.get(i, {})
        clean = validate_item(raw)
        r3 = resolve_3way(clean, a)
        rows.append({
            "idx": i, "article_id": a["_article_id"], "theme": a["_theme"],
            "title": a.get("title", ""), "category": a.get("_raw_category", ""),
            "v1_topics": _topics_of(a), "v1_primary_topic": a.get("primary_topic"),
            "expect_hint": THEME_EXPECT.get(a["_theme"]),
            "raw_llm": raw, "clean": clean, **r3,
        })
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    _write_reports(rows)
    print(f"→ {OUT_JSON.name} / {OUT_MD.name} / {OUT_CSV.name} / {OUT_VAL.name}")
    return 0


def _acc(rows, theme, expect):
    sub = [r for r in rows if r["theme"] == theme]
    if not sub:
        return None
    hit = sum(1 for r in sub if r["hybrid_primary_asset"] == expect)
    return hit, len(sub), (hit / len(sub) if sub else 0)


def _write_reports(rows):
    n = len(rows)
    # validator aggregate
    wc = Counter()
    for r in rows:
        for w in r["clean"]["warnings"]:
            wc[w.split(":")[0]] += 1
    asset_valid = sum(1 for r in rows if all(c["asset"] in ALLOWED_ASSET_8 for c in r["clean"]["affected_assets"]))
    region_valid = sum(1 for r in rows if r["clean"]["region"] in REGION_SET)
    fallback = sum(1 for r in rows if r["route_source"] in ("rule", "v1", "none"))
    unknown = sum(1 for r in rows if r["hybrid_primary_asset"] is None)
    multi = sum(1 for r in rows if len(r["clean"]["affected_assets"]) >= 2)
    conflict = sum(1 for r in rows if r["consistency_warning"])
    cx = [r for r in rows if r["theme"] == "복합"]
    cx_multi = sum(1 for r in cx if len(r["clean"]["affected_assets"]) >= 2)

    # ── sample_result.md ──
    L = ["# research_v2 Dry Sample 결과", "",
         f"- sample: {n}건  / LLM 응답: {sum(1 for r in rows if r['raw_llm'])}건", "",
         "## 1. sample 구성", "", "| bucket | count |", "| --- | ---: |"]
    for t, c in Counter(r["theme"] for r in rows).items():
        L.append(f"| {t} | {c} |")
    L += ["", "## 2. validator 결과", "",
          "| check | value | note |", "| --- | ---: | --- |",
          f"| asset_enum_valid_rate | {asset_valid}/{n} ({asset_valid/n*100:.0f}%) | validation 후 8-class only |",
          f"| region_enum_valid_rate | {region_valid}/{n} ({region_valid/n*100:.0f}%) | |",
          f"| fallback_rate | {fallback}/{n} ({fallback/n*100:.0f}%) | LLM 실패→rule/v1/none |",
          f"| unknown_rate | {unknown}/{n} ({unknown/n*100:.0f}%) | hybrid primary None |",
          f"| multi_asset_rate (전체) | {multi}/{n} ({multi/n*100:.0f}%) | affected_assets≥2 |",
          f"| multi_asset_rate (복합) | {cx_multi}/{len(cx) or 1} ({(cx_multi/len(cx)*100) if cx else 0:.0f}%) | 복합 테마만 |",
          f"| consistency_violation | {conflict}/{n} ({conflict/n*100:.0f}%) | rule_conflict trace |",
          "", "## 3. recovery (자동 proxy — theme membership 기준, 수동 CSV로 교정 대상)", "",
          "| metric | hit/total | rate |", "| --- | --- | ---: |"]
    for theme, label in [("한국주식반도체", "KR_equity_recovery"),
                         ("한은국내채권", "KR_rates_recovery"),
                         ("FedUS금리", "US_rates_accuracy"),
                         ("미국주식Fed", "US_equity_accuracy"),
                         ("환율달러", "FX_accuracy"),
                         ("원자재유가금", "commodity_accuracy"),
                         ("크레딧스프레드", "credit_accuracy")]:
        a = _acc(rows, theme, THEME_EXPECT[theme])
        if a:
            L.append(f"| {label} | {a[0]}/{a[1]} | {a[2]*100:.0f}% |")
    L += ["", "## 4. 3-way 비교 (전체 sample)", "",
          "| sample_id | theme | expect_hint | rule | llm | v1 | hybrid | route_src | conflict |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        L.append(f"| {r['idx']} | {r['theme']} | {r['expect_hint'] or '-'} | "
                 f"{r['rule_asset'] or '-'} | {r['llm_primary_asset'] or '-'} | "
                 f"{r['v1_asset'] or '-'} | {r['hybrid_primary_asset'] or '-'} | "
                 f"{r['route_source']} | {r['consistency_warning'] or ''} |")
    L += ["", "## 5. multi-asset 검증 (복합 테마)", ""]
    for r in cx:
        aa = ", ".join(f"{c['asset']}({c['impact'][:3]},{c['confidence']:.2f},{c['role'][:4]})"
                       for c in r["clean"]["affected_assets"]) or "(없음)"
        L.append(f"- [{r['idx']}] {r['title'][:40]} → primary={r['hybrid_primary_asset']} | {aa}")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    # ── validator_report.md ──
    V = ["# research_v2 Validator Report", "",
         f"sample {n}건. warning 유형별 집계 (차단 hard / 경고 soft).", "",
         "| warning_type | count | 종류 |", "| --- | ---: | --- |"]
    HARD = {"region_enum_invalid", "sector_enum_invalid", "asset_reject", "asset_low_conf",
            "region_low_conf", "primary_reassigned", "impact_invalid", "affected_trim_to_3"}
    for k, c in wc.most_common():
        V.append(f"| {k} | {c} | {'hard' if k in HARD else 'soft'} |")
    V += ["", "## remap 발생 (selector명 → 8-class)", ""]
    remaps = Counter()
    for r in rows:
        for c in r["raw_llm"].get("affected_assets", []) or []:
            raw = c.get("asset") if isinstance(c, dict) else None
            if raw and raw not in ALLOWED_ASSET_8:
                remaps[f"{raw}→{remap_to_8class(raw)}"] += 1
    if remaps:
        for k, c in remaps.most_common():
            V.append(f"- {k}: {c}건")
    else:
        V.append("- (LLM이 8-class 외 라벨을 출력하지 않음 — collapse 불필요)")
    OUT_VAL.write_text("\n".join(V), encoding="utf-8")

    # ── manual_review.csv ──
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        wcsv = csv.writer(fh)
        wcsv.writerow(["sample_id", "theme", "title", "category", "v1_primary_topic",
                       "llm_region", "llm_sector", "llm_primary_asset", "rule_asset",
                       "v1_asset", "hybrid_primary_asset", "affected_assets",
                       "expect_hint", "MANUAL_region", "MANUAL_primary_asset",
                       "MANUAL_affected_assets", "result", "note"])
        for r in rows:
            aa = "; ".join(f"{c['asset']}:{c['impact']}:{c['confidence']:.2f}:{c['role']}"
                           for c in r["clean"]["affected_assets"])
            wcsv.writerow([r["idx"], r["theme"], r["title"], r["category"],
                           r["v1_primary_topic"], r["clean"]["region"], r["clean"]["sector"],
                           r["llm_primary_asset"], r["rule_asset"], r["v1_asset"],
                           r["hybrid_primary_asset"], aa, r["expect_hint"],
                           "", "", "", "", ""])


if __name__ == "__main__":
    raise SystemExit(main())
