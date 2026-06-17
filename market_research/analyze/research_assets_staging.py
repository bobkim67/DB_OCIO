# -*- coding: utf-8 -*-
"""P5 — 03_Assets 재배선 staging (운영 미반영, diff/dry 검증 전용).

wiki_from_naver_research P5. 재생성된 09 conviction + market_snapshot(DB) + claims 를
03_Assets 소비 규칙대로 결합해 **staging 경로에만** 생성한다. 운영 wiki overwrite/
commit/debate 일절 없음. provenance 4분리:
  stance/conviction ← 09 / market level ← market_db / rationale ← claims /
  secondary driver ← driver_region·us_driven_kr (+ credit_sleeve subsection 분리).

소비 규칙:
- directional stance: 국내주식/해외주식/국내채권/해외채권
- non-directional: 원자재금/환율(FX)  (bull/bear 강제 금지)
- 미공급: 기타/현금성
- 크레딧 흡수분: credit_sleeve subsection (채권 main stance vote 미오염)
- us_driven_kr: secondary driver (국내 main rationale 과 분리)
- 시장 레벨: market_snapshot 주입 (09 conviction 근거로 쓰지 않음)
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from market_research.analyze.research_aggregator import (
    load_research_claims, aggregate_by_asset, _base_primary,
)
from market_research.analyze.research_audit import LOW_CONVICTION_STRENGTH
from market_research.analyze.market_snapshot import market_snapshot
from market_research.wiki.paths import RESEARCH_SYNTHESIS_DIR

BASE_DIR = Path(__file__).resolve().parent.parent
STAGING_DIR = BASE_DIR / 'debug' / 'wiki' / 'p5_assets_staging'

DIRECTIONAL = ("국내주식", "해외주식", "국내채권", "해외채권")
NON_DIRECTIONAL = ("대체", "환율(FX)")
NOT_SUPPLIED = ("기타", "유동성")

# 자산군 → market_snapshot metric (등록된 것만; 나머지는 주입 보류)
ASSET_METRIC = {
    "국내주식": "KOSPI",
    "해외주식": "SP500",   # S&P500 광범위 벤치마크 (NASDAQ100도 등록됨, 테크 집중이라 보조)
    "대체": "Gold",
    "환율(FX)": "USDKRW",
    # 국내채권/해외채권(금리 yield): metric 미등록 → 보류 (yield bp 처리 별 트랙)
}

_ASSET_STEM = {
    "국내주식": "국내주식", "해외주식": "해외주식", "국내채권": "국내채권",
    "해외채권": "해외채권", "대체": "대체", "환율(FX)": "환율FX",
}


def _is_credit(claim: dict) -> bool:
    return _base_primary(claim) == "크레딧"


def _claim_line(c: dict) -> str:
    st = c.get("stance") or "-"
    hz = c.get("horizon") or "-"
    br = c.get("broker_author") or c.get("source_type") or ""
    v = c.get("view") or c.get("claim_text") or ""
    cid = (c.get("claim_id") or "").split(":")[-1]
    return f"- [claim:{cid}] ({st}, {hz}, {br}) {v}".rstrip()


def _read_09_consensus(period: str, asset: str) -> str:
    """09 §1 consensus narrative 산문(헤더/vote 줄 제외)."""
    stem = _ASSET_STEM.get(asset, asset.replace("/", "_"))
    p = RESEARCH_SYNTHESIS_DIR / f"{period}_{stem}.md"
    if not p.exists():
        return ""
    body = p.read_text(encoding="utf-8")
    if "## 1." not in body:
        return ""
    sec = body.split("## 1.")[-1].split("## 2.")[0]
    lines = [ln for ln in sec.splitlines()[1:] if not ln.strip().startswith("- vote")]
    return "\n".join(ln for ln in lines if ln.strip())


def _market_section(asset: str, period: str) -> tuple[str, dict | None]:
    metric = ASSET_METRIC.get(asset)
    if not metric:
        return ("## 1. 시장 레벨 (출처: market_db)\n"
                "- DB metric 미등록 — 시장 레벨 주입 보류 (채권 금리 yield series 확정 후)\n", None)
    snap = market_snapshot(metric, period)
    if not snap:
        return (f"## 1. 시장 레벨 (출처: market_db / {metric})\n- 데이터 없음\n", None)
    ms, me = snap["month_start"], snap["month_end"]
    hi, lo = snap["month_high"], snap["month_low"]
    txt = (f"## 1. 시장 레벨 (출처: market_db / {metric})\n"
           f"- {metric} 월말 {me['level']:,} (월초 {ms['level']:,}, "
           f"고 {hi['level']:,}/저 {lo['level']:,}, {snap['month_return_pct']:+.2f}%) "
           f"[{snap['source']}]\n")
    return txt, snap


def build_staging_asset_page(period: str, asset: str,
                             a: dict[str, Any]) -> tuple[str, dict]:
    """단일 staging 03_Assets 페이지 + trace row."""
    directional = asset in DIRECTIONAL
    strength = a.get("consensus_strength") or 0.0
    stance = a.get("consensus_stance")
    broker = a.get("broker_claims") or []
    credit = [c for c in broker if _is_credit(c)]
    non_credit = [c for c in broker if not _is_credit(c)]
    us_driven = [c for c in broker if asset in ("국내주식", "국내채권")
                 and c.get("_driver_region") in ("US", "overseas")]

    market_txt, snap = _market_section(asset, period)

    front = (
        "---\n"
        f"period: {period}\nasset_class: {asset}\n"
        "source_type: asset_staging\ngenerated_by: research_assets_staging\n"
        "stance_source: research_claims_09\n"
        f"market_level_source: {'market_db' if snap else 'none'}\n"
        f"directional: {str(directional).lower()}\n"
        f"consensus_stance: {stance}\nconsensus_strength: {strength}\n"
        f"credit_sleeve_claims: {len(credit)}\nus_driven_kr: {len(us_driven)}\n"
        "---\n\n"
    )
    b = [f"# {period} {asset} — 운용보고 자산군 (P5 staging)", "", market_txt]

    # 2. conviction (09)
    if directional:
        b.append(f"## 2. 컨센서스 / conviction (출처: research_claims 09)")
        b.append(f"- **stance: {stance}** (strength {strength}, directional)")
    else:
        b.append("## 2. 컨센서스 / conviction (출처: research_claims 09, **non-directional**)")
        b.append(f"- 의견 분산 (strength {strength} < {LOW_CONVICTION_STRENGTH}) — "
                 "방향성 미제시, 요약만 사용")
    nar = _read_09_consensus(period, asset)
    if nar:
        b.append(nar)
    b.append("")

    # 3. rationale (claims, credit 제외)
    b.append("## 3. 핵심 논거 (출처: research claims)")
    for c in non_credit[:8]:
        b.append(_claim_line(c))
    b.append("")

    # 4. credit_sleeve (채권만, main stance 미합산)
    if asset in ("국내채권", "해외채권"):
        b.append("## 4. credit_sleeve (출처: 크레딧 claims — 채권 main stance 미합산)")
        if credit:
            for c in credit[:6]:
                b.append(_claim_line(c))
        else:
            b.append("- (해당 월 크레딧 흡수분 없음)")
        b.append("")

    # 5. secondary driver (us_driven_kr)
    if asset in ("국내주식", "국내채권"):
        b.append("## 5. secondary driver (출처: driver_region=US/overseas — primary 아님)")
        if us_driven:
            for c in us_driven[:5]:
                b.append(_claim_line(c))
        else:
            b.append("- (US driver 인 국내자산 claim 없음)")
        b.append("")

    trace = {
        "asset": asset, "stance_source": "research_claims_09",
        "stance": stance if directional else "(non-directional)",
        "directional": directional,
        "market_snapshot_used": bool(snap),
        "market_metric": ASSET_METRIC.get(asset),
        "market_level_month_end": (snap["month_end"]["level"] if snap else None),
        "credit_sleeve": len(credit),
        "us_driven_kr": len(us_driven),
        "n_broker": len(broker),
    }
    return front + "\n".join(b), trace


def run_p5_staging(period: str) -> dict[str, Any]:
    """전체 staging 생성 + diff + trace. 운영 미반영."""
    from market_research.wiki.asset_fund_enrichment_builder import build_asset_page

    agg = aggregate_by_asset(load_research_claims(period))
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    (STAGING_DIR / "03_Assets").mkdir(parents=True, exist_ok=True)

    traces: list[dict] = []
    diffs: list[str] = []
    supplied = DIRECTIONAL + NON_DIRECTIONAL
    for asset in supplied:
        a = agg.get(asset)
        if not a:
            traces.append({"asset": asset, "note": "no claims (skip)"})
            continue
        staging, tr = build_staging_asset_page(period, asset, a)
        stem = _ASSET_STEM.get(asset, asset)
        (STAGING_DIR / "03_Assets" / f"{period}_{stem}.md").write_text(
            staging, encoding="utf-8")
        traces.append(tr)
        # diff vs 운영 03_Assets (build_asset_page, news 기반)
        try:
            before = build_asset_page(asset, period)
        except Exception as exc:
            before = f"(build_asset_page 실패: {exc})"
        d = difflib.unified_diff(
            before.splitlines(), staging.splitlines(),
            fromfile=f"BEFORE(운영)/{asset}", tofile=f"AFTER(staging)/{asset}",
            lineterm="", n=1)
        diffs.append("\n".join(d))

    # 미공급 자산 trace
    for asset in NOT_SUPPLIED:
        if asset in agg:
            traces.append({"asset": asset, "supplied": False,
                           "note": "정책상 미공급 (09 stance 미주입)",
                           "n_broker": agg[asset].get("n_broker", 0)})

    # 산출물 저장
    (STAGING_DIR / "p5_assets_trace.json").write_text(
        json.dumps({"period": period, "traces": traces}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (STAGING_DIR / "p5_assets_diff.md").write_text(
        f"# P5 03_Assets staging diff ({period})\n\n"
        "> 운영 wiki 미반영. staging 전용.\n\n"
        + "\n\n---\n\n".join(f"```diff\n{d}\n```" for d in diffs if d.strip()),
        encoding="utf-8")

    return {"period": period, "traces": traces,
            "staging_dir": str(STAGING_DIR), "n_pages": len(supplied)}


# ══════════════════════════════════════════════════════════════════
# P5.1 cleanup — conviction 재작성(시장수치 제거/방향성 정규화/톤완화) + 섹션 정리
# ══════════════════════════════════════════════════════════════════

import re as _re

STAGING_CLEAN_DIR = BASE_DIR / 'debug' / 'wiki' / 'p5_assets_staging_clean'
SYNTH_MODEL = "claude-haiku-4-5-20251001"

# §2 conviction 잔존 시장수치 검출(검증용): 천단위 콤마 레벨 / N달러 / 지수 등락 등
_MARKET_NUM_RE = _re.compile(
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?\s?달러|\d+(?:\.\d+)?\s?원")


def _clean_conviction(asset: str, a: dict, directional: bool,
                      llm_call) -> str:
    """§2 conviction 재작성: 시장 레벨 수치 제거 + 방향성/톤 정규화."""
    broker = a.get("broker_claims") or []
    if not broker or llm_call is None:
        return ""
    claim_lines = "\n".join(
        f"- ({c.get('stance')},{c.get('horizon')}) {c.get('view') or c.get('claim_text')}"
        f" :: {(c.get('rationale_text') or '')}"[:240] for c in broker[:14])
    stance = a.get("consensus_stance")
    vote = a.get("vote_distribution", {})
    strength = a.get("consensus_strength")

    if directional:
        nonbull = sum(v for k, v in vote.items() if k != stance)
        weak = (strength or 0) < 0.6 or nonbull >= sum(vote.values()) * 0.45
        tone = ("단정적 강세/약세 대신 '완만한 우위 / 조건부' 톤"
                if (asset == "해외주식" or weak) else f"{stance} 방향 명확히")
        bond = ("채권: '긴축 본격화 임박' 등 강한 표현 금지 → "
                "'금리 상방 압력/인하 기대 후퇴/듀레이션 부담' 류로 완화"
                if asset in ("국내채권", "해외채권") else "")
        dir_rule = (f"- 방향성: stance={stance}. {tone}. {bond}\n")
    else:
        dir_rule = ("- ★non-directional: bullish/bearish/강세/약세/컨센서스 강세·약세 표현 "
                    "절대 금지. '상승 요인은 …, 하락 요인은 …, 방향성 판단 유보' 구조로.\n")

    user = (
        f"자산군: {asset} (directional={directional})\n"
        f"broker claims:\n{claim_lines}\n\n"
        "위 claim 근거로 운용보고 conviction 2~3문장 작성. 규칙:\n"
        "- ★시장 레벨/가격 수치 절대 금지: 지수레벨(코스피 7,981 등)·가격·등락률·월말값"
        "·금리레벨·환율수치·유가달러 등 숫자 레벨 쓰지 말 것(별도 DB에서 주입).\n"
        f"{dir_rule}"
        "- 근거 불명확한 고유명사/정치인물(예: 특정 인물 체제) 금지 — claim 명시분만.\n"
        "- 방향성과 논리만. 순수 텍스트(JSON/마크다운 금지)."
    )
    prompt = {"system": "OCIO 운용보고 자산군 코멘트 보조. 시장 레벨/가격 수치는 절대 "
                        "쓰지 않는다(DB 주입). 방향성과 논리만 간결히. 제목/헤더 없이 본문만.",
              "user": user, "model": SYNTH_MODEL, "max_tokens": 600}
    try:
        raw = (llm_call(prompt) or "").strip()
    except Exception:
        return ""
    # LLM 이 붙인 markdown 제목/헤더/fence 제거 (본문 산문만)
    lines = [ln for ln in raw.splitlines()
             if not ln.lstrip().startswith("#") and not ln.strip().startswith("```")]
    return "\n".join(lines).strip()


def _number_sections(sections: list[tuple[str, str]]) -> str:
    """(title, body) 리스트 → ## N. 순차 번호 (빈 섹션 제외)."""
    out = []
    n = 0
    for title, body in sections:
        if not body.strip():
            continue
        n += 1
        out.append(f"## {n}. {title}\n{body}".rstrip())
    return "\n\n".join(out)


def build_clean_asset_page(period: str, asset: str, a: dict, llm_call) -> tuple[str, dict]:
    directional = asset in DIRECTIONAL
    strength = a.get("consensus_strength") or 0.0
    stance = a.get("consensus_stance")
    broker = a.get("broker_claims") or []
    credit = [c for c in broker if _is_credit(c)]
    non_credit = [c for c in broker if not _is_credit(c)]
    us_driven = [c for c in broker if asset in ("국내주식", "국내채권")
                 and c.get("_driver_region") in ("US", "overseas")]
    market_txt, snap = _market_section(asset, period)
    conviction = _clean_conviction(asset, a, directional, llm_call)
    leak = _MARKET_NUM_RE.findall(conviction)

    # 섹션 동적 구성 (빈 섹션 미출력 → 번호 정상화)
    s_market = market_txt.split("\n", 1)[1] if "\n" in market_txt else market_txt
    if directional:
        s_conv = f"- stance: **{stance}** (strength {strength}, directional)\n{conviction}"
    else:
        s_conv = (f"- 방향성 판단 유보 (strength {strength} < {LOW_CONVICTION_STRENGTH}, "
                  f"non-directional)\n{conviction}")
    s_rat = "\n".join(_claim_line(c) for c in non_credit[:8])
    s_credit = ("\n".join(_claim_line(c) for c in credit[:6])
                if asset in ("국내채권", "해외채권") and credit else "")
    s_sec = ("\n".join(_claim_line(c) for c in us_driven[:5])
             if asset in ("국내주식", "국내채권") and us_driven else "")

    body = _number_sections([
        ("시장 레벨 (출처: market_db)", s_market),
        ("컨센서스 / conviction (출처: research_claims 09)", s_conv),
        ("핵심 논거 (출처: research claims)", s_rat),
        ("credit_sleeve (출처: 크레딧 claims — 채권 main stance 미합산)", s_credit),
        ("secondary driver (출처: driver_region=US/overseas)", s_sec),
    ])
    front = (
        "---\n"
        f"period: {period}\nasset_class: {asset}\n"
        "source_type: asset_staging_clean\ngenerated_by: research_assets_staging(P5.1)\n"
        "stance_source: research_claims_09\n"
        f"market_level_source: {'market_db' if snap else 'none'}\n"
        f"directional: {str(directional).lower()}\n"
        f"consensus_stance: {stance if directional else '(non-directional)'}\n"
        f"consensus_strength: {strength}\n"
        f"conviction_market_num_leak: {len(leak)}\n"
        "---\n\n"
    )
    page = front + f"# {period} {asset} — 운용보고 자산군 (P5.1 clean staging)\n\n" + body
    trace = {"asset": asset, "directional": directional,
             "stance": stance if directional else "(non-directional)",
             "market_snapshot_used": bool(snap), "credit_sleeve": len(credit),
             "us_driven_kr": len(us_driven), "conviction_market_num_leak": len(leak),
             "leaked": leak[:5]}
    return page, trace


def run_p5_1_cleanup(period: str, *, llm_call=None) -> dict[str, Any]:
    from market_research.analyze.research_consensus import _default_llm_call
    call = llm_call or _default_llm_call
    agg = aggregate_by_asset(load_research_claims(period))
    (STAGING_CLEAN_DIR / "03_Assets").mkdir(parents=True, exist_ok=True)
    traces, diffs = [], []
    for asset in DIRECTIONAL + NON_DIRECTIONAL:
        a = agg.get(asset)
        if not a:
            continue
        clean, tr = build_clean_asset_page(period, asset, a, call)
        stem = _ASSET_STEM.get(asset, asset)
        (STAGING_CLEAN_DIR / "03_Assets" / f"{period}_{stem}.md").write_text(
            clean, encoding="utf-8")
        traces.append(tr)
        # diff: P5(원본 staging) → P5.1(clean)
        before_p = STAGING_DIR / "03_Assets" / f"{period}_{stem}.md"
        before = before_p.read_text(encoding="utf-8") if before_p.exists() else ""
        d = difflib.unified_diff(before.splitlines(), clean.splitlines(),
                                 fromfile=f"P5/{asset}", tofile=f"P5.1clean/{asset}",
                                 lineterm="", n=1)
        diffs.append("\n".join(d))
    (STAGING_CLEAN_DIR / "p5_assets_clean_trace.json").write_text(
        json.dumps({"period": period, "traces": traces}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (STAGING_CLEAN_DIR / "p5_assets_clean_diff.md").write_text(
        f"# P5.1 clean diff ({period}) — 운영 미반영\n\n"
        + "\n\n---\n\n".join(f"```diff\n{d}\n```" for d in diffs if d.strip()),
        encoding="utf-8")
    return {"period": period, "traces": traces, "dir": str(STAGING_CLEAN_DIR)}


# ══════════════════════════════════════════════════════════════════
# P5.2 deterministic final cleanup — 문자열 치환만(LLM 0, variance 0)
# ══════════════════════════════════════════════════════════════════

STAGING_FINAL_DIR = BASE_DIR / 'debug' / 'wiki' / 'p5_assets_staging_final'

# (find, replace) — 순서 중요(구체 → 일반). LLM 재작성 없이 deterministic.
P52_REPLACEMENTS: list[tuple[str, str]] = [
    # 오타
    ("포지셍", "포지셔닝"),
    ("포지셀링", "포지셔닝"),
    ("프리미염", "프리미엄"),
    # research-only 표현 정리
    ("지정학 뉴스 플로우", "지정학 리스크 변화"),
    ("뉴스 플로우", "리스크 변화"),
    # §2 수치성 표현 일반화 (국내주식)
    ("핵심 수출품목의 이중자릿수 증가율 지속", "핵심 수출품목의 개선세 지속"),
    ("이중자릿수 증가율 지속", "개선세 지속"),
    ("이중자릿수 증가율", "개선세"),
    # josa-aware: '유지'(모음 받침없음→는) → '흐름'(받침 ㅁ→은) 조사 일치
    ("무역수지 200억 달러 이상 유지는", "무역수지 개선 흐름은"),
    ("무역수지 200억 달러 이상 유지", "무역수지 개선 흐름"),
    ("200억 달러 이상 유지는", "개선 흐름은"),
    ("200억 달러 이상 유지", "개선 흐름"),
]


def run_p5_2_final(period: str) -> dict[str, Any]:
    """clean staging → deterministic 치환 → final staging. LLM 0, 운영 미반영."""
    src = STAGING_CLEAN_DIR / "03_Assets"
    (STAGING_FINAL_DIR / "03_Assets").mkdir(parents=True, exist_ok=True)
    traces, diffs = [], []
    for p in sorted(src.glob(f"{period}_*.md")):
        before = p.read_text(encoding="utf-8")
        after = before
        applied = []
        for find, repl in P52_REPLACEMENTS:
            n = after.count(find)
            if n:
                after = after.replace(find, repl)
                applied.append({"find": find, "repl": repl, "n": n})
        # §2 conviction market-num leak 재검증
        sec2 = (after.split("## 2.")[-1].split("## 3.")[0]
                if "## 2." in after else "")
        leak = _MARKET_NUM_RE.findall(sec2)
        (STAGING_FINAL_DIR / "03_Assets" / p.name).write_text(after, encoding="utf-8")
        traces.append({"file": p.name, "replacements": applied,
                       "conviction_market_num_leak": len(leak)})
        if before != after:
            d = difflib.unified_diff(before.splitlines(), after.splitlines(),
                                     fromfile=f"clean/{p.name}", tofile=f"final/{p.name}",
                                     lineterm="", n=1)
            diffs.append("\n".join(d))
    (STAGING_FINAL_DIR / "p5_assets_final_trace.json").write_text(
        json.dumps({"period": period, "replacements": P52_REPLACEMENTS, "traces": traces},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (STAGING_FINAL_DIR / "p5_assets_final_diff.md").write_text(
        f"# P5.2 final deterministic cleanup diff ({period}) — 운영 미반영\n\n"
        + "\n\n---\n\n".join(f"```diff\n{d}\n```" for d in diffs if d.strip()),
        encoding="utf-8")
    return {"period": period, "traces": traces, "dir": str(STAGING_FINAL_DIR)}


# ══════════════════════════════════════════════════════════════════
# P5 운영 반영(promote) — final staging → 운영 03_Assets (5개만, 원자재금 skip)
# ══════════════════════════════════════════════════════════════════

OPERATIONAL_ASSETS_DIR = BASE_DIR / 'data' / 'wiki' / '03_Assets'

# (staging_stem, staging_asset_class, 운영 stem, 운영 asset_class)
# 원자재금 의도적 제외 — 운영 taxonomy 는 금/원유/기타 원자재 (P5.3 별도 정렬).
PROMOTE_MAP = [
    ("국내주식", "국내주식", "국내주식", "국내주식"),
    ("해외주식", "해외주식", "해외주식", "해외주식"),
    ("국내채권", "국내채권", "국내채권", "국내채권"),
    ("해외채권", "해외채권", "해외채권", "해외채권"),
    ("환율FX", "환율(FX)", "환율", "환율"),   # 환율FX → 환율.md overwrite, asset_class=환율
]


def _to_operational(text: str, period: str, st_asset: str, op_asset: str) -> str:
    """staging 본문 → 운영용 metadata/제목 정리 (provenance 필드는 유지)."""
    out = text
    out = out.replace("source_type: asset_staging_clean", "source_type: asset_wiki")
    out = out.replace("generated_by: research_assets_staging(P5.1)",
                      "generated_by: research_assets_builder")
    out = out.replace(" (P5.1 clean staging)", "")
    if st_asset != op_asset:
        out = out.replace(f"asset_class: {st_asset}", f"asset_class: {op_asset}")
        out = out.replace(f"# {period} {st_asset} —", f"# {period} {op_asset} —")
    return out


def run_p5_promote(period: str) -> dict[str, Any]:
    """final staging 5개 → 운영 03_Assets overwrite. 원자재금 skip. diff 반환."""
    OPERATIONAL_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    rows, diffs = [], []
    for st_stem, st_asset, op_stem, op_asset in PROMOTE_MAP:
        src = STAGING_FINAL_DIR / "03_Assets" / f"{period}_{st_stem}.md"
        if not src.exists():
            rows.append({"asset": op_asset, "overwritten": False, "note": "staging 없음"})
            continue
        new = _to_operational(src.read_text(encoding="utf-8"), period, st_asset, op_asset)
        dst = OPERATIONAL_ASSETS_DIR / f"{period}_{op_stem}.md"
        before = dst.read_text(encoding="utf-8") if dst.exists() else ""
        dst.write_text(new, encoding="utf-8")
        sec2 = new.split("## 2.")[-1].split("## 3.")[0] if "## 2." in new else ""
        leak = _MARKET_NUM_RE.findall(sec2)
        rows.append({"asset": op_asset, "file": dst.name, "overwritten": True,
                     "source": "p5_assets_staging_final",
                     "market_num_leak": len(leak)})
        d = difflib.unified_diff(before.splitlines(), new.splitlines(),
                                 fromfile=f"BEFORE/{dst.name}", tofile=f"AFTER/{dst.name}",
                                 lineterm="", n=1)
        diffs.append((op_asset, "\n".join(d)))
    return {"period": period, "rows": rows, "diffs": diffs}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="P5 03_Assets staging (no operational write)")
    ap.add_argument("period")
    ap.add_argument("--clean", action="store_true", help="P5.1 cleanup staging")
    ap.add_argument("--final", action="store_true", help="P5.2 deterministic final cleanup")
    args = ap.parse_args()
    if args.final:
        r = run_p5_2_final(args.period)
        print(f"[P5.2 final] {args.period} → {r['dir']}")
        for t in r["traces"]:
            reps = ", ".join(f"{x['find']}→{x['repl']}({x['n']})" for x in t["replacements"])
            print(f"  {t['file']}: leak={t['conviction_market_num_leak']} | {reps or '(변경없음)'}")
        return 0
    if args.clean:
        r = run_p5_1_cleanup(args.period)
        print(f"[P5.1 clean] {args.period} → {r['dir']}")
        print(f"{'asset':10} {'stance':18} {'mkt':4} {'credit':6} {'us_kr':5} {'num_leak':8}")
        for t in r["traces"]:
            print(f"  {t['asset']:10} {str(t['stance'])[:16]:18} "
                  f"{'Y' if t['market_snapshot_used'] else '-':4} "
                  f"{t['credit_sleeve']:<6} {t['us_driven_kr']:<5} "
                  f"{t['conviction_market_num_leak']:<8} {t['leaked'] if t['leaked'] else ''}")
        return 0
    r = run_p5_staging(args.period)
    print(f"[P5 staging] {args.period} → {r['staging_dir']}")
    print(f"{'asset':10} {'src':16} {'stance':16} {'mkt':5} {'credit':6} {'us_kr':5}")
    for t in r["traces"]:
        if t.get("note") and "supplied" not in t and "stance" not in t:
            print(f"  {t['asset']:10} (skip: {t['note']})")
            continue
        if t.get("supplied") is False:
            print(f"  {t['asset']:10} 미공급 ({t.get('note','')})")
            continue
        print(f"  {t['asset']:10} {t['stance_source']:16} {str(t['stance'])[:14]:16} "
              f"{'Y' if t['market_snapshot_used'] else '-':5} "
              f"{t['credit_sleeve']:<6} {t['us_driven_kr']:<5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
