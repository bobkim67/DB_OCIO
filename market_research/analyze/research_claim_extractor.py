# -*- coding: utf-8 -*-
"""Research claim extractor — naver_research / monygeek → 원자 research claim (P2).

wiki_from_naver_research P2. 기존 claim_extractor 의 schema/normalize/validate/
serialize + runner 헬퍼(LLM 호출/파싱/비용추정)를 **재사용**하되, research 전용
prompt 로 자산군별 전망·논거·리스크를 분해한다. 운영 claim store 와 분리된
`data/claims/{month}.research.json` 에 저장 (target-suffix 격리).

- source_type 은 batch 레인에서 주입 (naver_research / monygeek).
- broker_author 는 supporting evidence 의 source 에서 해석.
- stance/view/rationale_text/risk_factor/evidence_text 는 LLM 출력.
- stance(전망 어조) ↔ direction(가격영향) 정의 분리 (일치강제 X).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from market_research.analyze.claim_extractor import (
    ALLOWED_ASSET_CLASSES,
    ALLOWED_CLAIM_TYPES,
    ALLOWED_DIRECTIONS,
    ALLOWED_HORIZONS,
    ALLOWED_RELATIONS,
    ALLOWED_STANCES,
    normalize_claim,
    validate_claim,
    serialize_claim,
)
import re as _re

from market_research.analyze.claim_extractor_runner import (
    _default_llm_call,
    _estimate_cost_usd,
    _estimate_tokens,
)
from market_research.core.asset_taxonomy import REGION_TAXONOMY
from market_research.wiki.taxonomy import TOPIC_TAXONOMY

BASE_DIR = Path(__file__).resolve().parent.parent
CLAIMS_DIR = BASE_DIR / 'data' / 'claims'

EXTRACTOR_VERSION = "research.0-haiku"
LLM_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 16384
# 리서치 evidence 는 뉴스보다 밀도가 높아 50건 batch 는 출력이 MAX_TOKENS 에서
# 잘린다(truncation → json_parse_failed). 25 로 축소 + salvage 파서로 견고화.
MAX_INPUT_EVIDENCE = 25

_OBJ_DECODER = json.JSONDecoder()
_FENCE_HEAD_RE = _re.compile(r"^\s*```(?:json)?\s*", _re.IGNORECASE)


def _robust_parse_claims(raw: str) -> list[dict] | None:
    """truncation 견고 파서 — ```json fence(닫힘 없어도) 제거 + 배열에서 완성된
    객체만 순차 salvage. 잘린 마지막 객체는 버리고 그 앞 완성분 보존."""
    if not raw:
        return None
    s = _FENCE_HEAD_RE.sub("", raw.strip())
    s = _re.sub(r"\s*```\s*$", "", s)
    i = s.find("[")
    if i < 0:
        # 단일 객체 fallback
        try:
            obj = json.loads(s)
            return [obj] if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    s = s[i + 1:]
    objs: list[dict] = []
    idx, n = 0, len(s)
    while idx < n:
        while idx < n and s[idx] in " \t\r\n,":
            idx += 1
        if idx >= n or s[idx] == "]":
            break
        try:
            obj, end = _OBJ_DECODER.raw_decode(s, idx)
        except json.JSONDecodeError:
            break  # 잘린/불완전 객체 → 중단 (앞 완성분 salvage)
        if isinstance(obj, dict):
            objs.append(obj)
        idx = end
    return objs or None

RESEARCH_SYSTEM_PROMPT = (
    "당신은 OCIO 운용 리서치 보조 모델입니다. 주어진 증권사 리서치 / 블로그 "
    "evidence 에서 **자산군별 전망·논거·리스크** 를 원자(atomic) research claim 으로 "
    "분해합니다. 출력은 마크다운/설명 없이 순수 JSON 배열만. 사실 나열이 아니라 "
    "운용 의사결정에 의미 있는 view/논거/리스크 단위로만 추출하세요."
)


def _format_evidence_lines(evidence_items: list[dict], max_items: int,
                           desc_chars: int = 300,
                           attach_desc_chars: int | None = None) -> str:
    """evidence → prompt 라인. attach_desc_chars 지정 시 첨부 파싱된 건만 창을 넓힌다.

    첨부 파싱본(리포트 PDF/docx 원문)은 메일 본문과 달리 앞부분에 실질 내용이 몰려
    있어 800자로는 요약 한 문단에서 잘린다.
    """
    lines: list[str] = []
    for i, e in enumerate(evidence_items[:max_items]):
        aid = e.get("_article_id") or e.get("article_id") or f"row_{i}"
        title = (e.get("title") or "").strip()[:120]
        source = e.get("source") or e.get("_raw_broker") or ""
        date = e.get("date") or ""
        n = desc_chars
        if attach_desc_chars and "attach_parsed" in (e.get("_adapter_flags") or []):
            n = attach_desc_chars
        desc = (e.get("description") or "").strip().replace("\n", " ")[:n]
        lines.append(f"- [{aid}] ({source} / {date}) {title} :: {desc}")
    return "\n".join(lines)


def build_research_extraction_prompt(
    period: str,
    evidence_items: list[dict],
    *,
    source_type: str,
    max_items: int = MAX_INPUT_EVIDENCE,
) -> dict[str, Any]:
    """Research 추출 prompt. claim_extractor schema + research 필드."""
    asset_list = ", ".join(sorted(ALLOWED_ASSET_CLASSES))
    type_list = ", ".join(sorted(ALLOWED_CLAIM_TYPES))
    dir_list = ", ".join(sorted(ALLOWED_DIRECTIONS))
    hor_list = ", ".join(sorted(ALLOWED_HORIZONS))
    rel_list = ", ".join(sorted(ALLOWED_RELATIONS))
    stance_list = ", ".join(sorted(ALLOWED_STANCES))
    region_list = ", ".join(REGION_TAXONOMY)
    sector_list = ", ".join(TOPIC_TAXONOMY)
    # broker_mail 은 요약문이 아닌 메일 본문이라 앞 300자만으로는 논거가 잘림 → 800자.
    # naver/monygeek 은 기존 300자 유지 (운영 claim md5 불변).
    _desc_chars = 800 if source_type == "broker_mail" else 300
    # 첨부 파싱본(리포트 원문)만 3000자 — 커버노트 메일의 실질 내용이 여기 있다.
    _attach_chars = 3000 if source_type == "broker_mail" else None
    evidence_block = _format_evidence_lines(evidence_items, max_items,
                                            desc_chars=_desc_chars,
                                            attach_desc_chars=_attach_chars)

    user_prompt = (
        f"## Period: {period}  (source_type={source_type})\n\n"
        "## 입력 리서치 evidence 목록\n"
        f"{evidence_block}\n\n"
        "## 추출 규칙\n"
        "1. 위 evidence 만 근거. 자산군별 전망/논거/리스크 unit 으로 분해.\n"
        "2. supporting_evidence_ids 는 해당 claim 의 사실·논거를 **직접 진술·뒷받침한 "
        "기사만** 포함한다(1개 이상). 같은 날·같은 증권사·인접 주제라는 이유로 함께 묶지 "
        "말 것 — 직접 근거가 1건이면 1건만 명시. 보조·배경 기사는 제외.\n"
        "3. 자산군 영향이 모호하면 추출 X. 단순 사실 나열 X.\n"
        "4. ★stance(전망 어조: 해당 자산 보유 관점)와 direction(가격영향 방향)을 분리. "
        "예: '금리 상승 전망' → 국내채권 stance=bearish 이지만 금리 자체 direction=positive.\n"
        "5. affected_assets 각 항목에 confidence(0~1)·role(primary/secondary), "
        "role=primary 정확히 1개, primary_asset 동일 명시. ★primary_asset·asset_class "
        "는 반드시 위 8종 중 하나만 — 괄호 세부업종(국내주식(반도체)) 금지, 세부업종은 "
        "sectors 에.\n"
        "6. regions(≤2)·sectors(≤3) = 영향받는 시장/주제.\n"
        "7. claim_id 출력 X (자동 부여).\n\n"
        "## 출력 schema (JSON 배열만)\n"
        "[\n"
        "  {\n"
        '    "claim_text": "한 줄 요약 (≤180자)",\n'
        '    "claim_type": "outlook_view|risk|macro_to_asset|...",\n'
        '    "stance": "bullish|neutral|bearish|mixed",\n'
        '    "view": "한 줄 view title (예: 반도체 비중확대)",\n'
        '    "rationale_text": "핵심 논거 (≤300자)",\n'
        '    "risk_factor": "리스크 요인 (없으면 \\"\\")",\n'
        '    "affected_assets": [{"asset_class": "...", "direction": "...", '
        '"confidence": 0.0~1.0, "role": "primary|secondary"}],\n'
        '    "primary_asset": "role=primary 자산",\n'
        '    "regions": ["..."], "sectors": ["..."],\n'
        '    "causal_chain": [{"source": "...", "target": "...", "relation": "..."}],\n'
        '    "direction": "...", "horizon": "short|medium|long",\n'
        '    "confidence": 0.0~1.0, "salience": 0.0~1.0,\n'
        '    "supporting_evidence_ids": ["article_id", ...],\n'
        '    "counter_evidence_ids": []\n'
        "  }\n"
        "]\n\n"
        "## Taxonomy 제약 (아래 값만)\n"
        f"- asset_class: {asset_list}\n"
        f"- claim_type:  {type_list}\n"
        f"- stance:      {stance_list}\n"
        f"- direction:   {dir_list}\n"
        f"- horizon:     {hor_list}\n"
        f"- relation:    {rel_list}\n"
        f"- region:      {region_list}\n"
        f"- sector:      {sector_list}\n"
    )
    return {
        "system": RESEARCH_SYSTEM_PROMPT,
        "user": user_prompt,
        "model": LLM_MODEL,
        "max_tokens": MAX_TOKENS,
    }


def _resolve_broker_author(claim: dict, evidence_index: dict[str, dict]) -> str:
    """supporting_evidence_ids → evidence source 들에서 broker_author 해석."""
    sources: list[str] = []
    for eid in claim.get("supporting_evidence_ids") or []:
        ev = evidence_index.get(eid)
        if ev:
            s = ev.get("source") or ev.get("_raw_broker")
            if s and s not in sources:
                sources.append(s)
    return " / ".join(sources[:3])


def extract_research_claims(
    period: str,
    evidence_items: list[dict],
    *,
    source_type: str,
    max_items: int = MAX_INPUT_EVIDENCE,
    cost_cap_usd: float = 1.0,
    llm_call: Callable[[dict], str] | None = None,
) -> dict[str, Any]:
    """단일 batch research 추출. claim_extractor normalize/validate/serialize 재사용."""
    base = {"extractor_version": EXTRACTOR_VERSION, "source_type": source_type}
    items = [e for e in evidence_items if isinstance(e, dict)][:max_items]
    if not items:
        return {"claims": [], "invalid_claims": [], "warnings": ["no_evidence"],
                "cost_usd": 0.0, "abort_reason": "no_evidence", **base}

    prompt = build_research_extraction_prompt(
        period, items, source_type=source_type, max_items=max_items)
    est = _estimate_cost_usd(prompt["user"], MAX_TOKENS)
    if est > cost_cap_usd:
        return {"claims": [], "invalid_claims": [],
                "warnings": [f"cost_cap_exceeded_estimate ${est:.4f}"],
                "cost_usd": est, "abort_reason": "cost_cap_exceeded_estimate", **base}

    call = llm_call if callable(llm_call) else _default_llm_call
    t0 = time.time()
    try:
        raw = call(prompt) or ""
    except Exception as exc:
        return {"claims": [], "invalid_claims": [], "warnings": [f"llm_api_failure: {exc}"],
                "cost_usd": 0.0, "abort_reason": "llm_api_failure", **base}
    elapsed = round(time.time() - t0, 3)

    parsed = _robust_parse_claims(raw)
    if parsed is None:
        return {"claims": [], "invalid_claims": [{"raw": raw[:500], "errors": ["json_parse_failed"]}],
                "warnings": ["json_parse_failed"], "cost_usd": _estimate_cost_usd(prompt["user"], raw),
                "abort_reason": "json_parse_failed", "raw_response": raw, **base}

    ev_index = {(e.get("_article_id") or e.get("article_id")): e for e in items}
    valid: list[dict] = []
    invalid: list[dict] = []
    for rc in parsed:
        try:
            normalized = normalize_claim({
                **rc,
                "period": period,
                "extractor_version": EXTRACTOR_VERSION,
                "extraction_method": "llm",
                "source_type": source_type,
            })
            normalized.setdefault("broker_author", _resolve_broker_author(normalized, ev_index))
            v = validate_claim(normalized)
            if v["valid"]:
                valid.append(serialize_claim(normalized))
            else:
                invalid.append({"raw": rc, "errors": v["errors"]})
        except Exception as exc:
            invalid.append({"raw": rc, "errors": [f"normalize_error: {exc}"]})

    return {
        "claims": valid,
        "invalid_claims": invalid,
        "warnings": [] if valid else ["no_claims_extracted"],
        "usage": {"approx_input_tokens": _estimate_tokens(prompt["user"]),
                  "approx_output_tokens": _estimate_tokens(raw),
                  "elapsed_seconds": elapsed},
        "cost_usd": _estimate_cost_usd(prompt["user"], raw),
        "abort_reason": None,
        **base,
    }


# ──────────────────────────────────────────────────────────────────
# 레인 입력 준비 + batch 드라이버 + 저장
# ──────────────────────────────────────────────────────────────────

def prep_research_evidence(month: str, source_type: str) -> list[dict]:
    """레인별 evidence 로드 + _article_id 보장."""
    if source_type == "naver_research":
        from market_research.collect.naver_research_adapter import load_adapted
        arts = load_adapted(month) or []
        for a in arts:
            if not a.get("_article_id"):
                a["_article_id"] = a.get("_raw_dedupe_key") or a.get("_raw_nid") or ""
        return [a for a in arts if a.get("_article_id")]
    if source_type == "monygeek":
        from market_research.collect.monygeek_research_adapter import build_monygeek_articles
        return build_monygeek_articles(month)
    if source_type == "broker_mail":
        from market_research.collect.outlook_report_adapter import load_broker_mail
        return [a for a in load_broker_mail(month) if a.get("_article_id")]
    raise ValueError(f"unknown source_type: {source_type}")


def research_claims_path(month: str) -> Path:
    return CLAIMS_DIR / f"{month}.research.json"


def run_research_extraction(
    month: str,
    *,
    source_types: tuple[str, ...] = ("naver_research", "monygeek", "broker_mail"),
    max_batches: int | None = None,
    cost_cap_usd: float = 3.0,
    dry_run: bool = False,
    llm_call: Callable[[dict], str] | None = None,
    incremental: bool = True,
) -> dict[str, Any]:
    """월별 research 추출 (레인별 batch). dry_run=True 면 파일 미저장.

    incremental=True (기본): 기존 {month}.research.json 의 processed_article_ids 에 없는
      신규 기사만 추출 → 기존 claims 에 병합(claim_id dedup). late-month 증분을 싸게 흡수해
      전월 전량 재추출(수십 분)을 회피한다. legacy 파일(processed_article_ids 부재)은
      claims 의 source_evidence_ids 로 처리済 set 을 best-effort seed(무클레임 기사만 1회 재시도).
    incremental=False: 전량 재추출(기존 동작) — force 전체 재빌드용.
    """
    # ── 기존 claims + 처리済 article_id (incremental) ──
    existing_claims: list[dict] = []
    processed: set[str] = set()
    if incremental:
        _rp = research_claims_path(month)
        if _rp.exists():
            try:
                _prev = json.loads(_rp.read_text(encoding="utf-8"))
                existing_claims = _prev.get("claims", []) or []
                _pids = _prev.get("processed_article_ids")
                if _pids is None:  # legacy: claims provenance 로 seed
                    for c in existing_claims:
                        for eid in (c.get("source_evidence_ids") or []):
                            if eid:
                                processed.add(str(eid))
                else:
                    processed = {str(x) for x in _pids if x}
            except Exception:
                existing_claims, processed = [], set()

    new_claims: list[dict] = []
    all_invalid: list[dict] = []
    total_cost = 0.0
    batch_log: list[dict] = []
    nb = 0
    new_ids: set[str] = set()
    for st in source_types:
        evid = prep_research_evidence(month, st)
        if incremental:
            evid = [a for a in evid if str(a.get("_article_id")) not in processed]
        for a in evid:
            if a.get("_article_id"):
                new_ids.add(str(a["_article_id"]))
        for start in range(0, len(evid), MAX_INPUT_EVIDENCE):
            if max_batches is not None and nb >= max_batches:
                break
            batch = evid[start:start + MAX_INPUT_EVIDENCE]
            r = extract_research_claims(
                month, batch, source_type=st, cost_cap_usd=cost_cap_usd,
                llm_call=llm_call)
            new_claims.extend(r.get("claims", []))
            all_invalid.extend(r.get("invalid_claims", []))
            total_cost += r.get("cost_usd", 0.0)
            batch_log.append({"source_type": st, "batch": nb, "n_in": len(batch),
                              "n_valid": len(r.get("claims", [])),
                              "abort": r.get("abort_reason")})
            nb += 1

    # ── 병합 (incremental) — claim_id dedup ──
    if incremental:
        _seen = {c.get("claim_id") for c in existing_claims if c.get("claim_id")}
        _added = [c for c in new_claims
                  if not (c.get("claim_id") and c.get("claim_id") in _seen)]
        final_claims = existing_claims + _added
        processed_out = sorted(processed | new_ids)
        n_new_claims = len(_added)
    else:
        final_claims = new_claims
        processed_out = sorted(new_ids)
        n_new_claims = len(new_claims)

    payload = {
        "schema_version": "1.0.0",
        "period": month,
        "saved_at": None,  # caller 가 stamp (Date.now 회피)
        "source": "research_claim_extractor",
        "extractor_version": EXTRACTOR_VERSION,
        "target_suffix": "research",
        "claims": final_claims,
        "processed_article_ids": processed_out,
        "stats": {"total": len(final_claims), "new_claims": n_new_claims,
                  "new_articles": len(new_ids), "invalid": len(all_invalid),
                  "incremental": incremental,
                  "cost_usd": round(total_cost, 4), "batches": batch_log},
    }
    if not dry_run:
        CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
        p = research_claims_path(month)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["_saved_path"] = str(p)
    return payload


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Research claim extractor (P2)")
    ap.add_argument("month", help="YYYY-MM")
    ap.add_argument("--source", action="append",
                    choices=["naver_research", "monygeek", "broker_mail"], default=None)
    ap.add_argument("--max-batches", type=int, default=None)
    ap.add_argument("--cost-cap", type=float, default=3.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--full", action="store_true",
                    help="전량 재추출(증분 아님). 기본은 증분(신규 기사만).")
    args = ap.parse_args()
    sts = tuple(args.source) if args.source else ("naver_research", "monygeek", "broker_mail")
    res = run_research_extraction(
        args.month, source_types=sts, max_batches=args.max_batches,
        cost_cap_usd=args.cost_cap, dry_run=args.dry_run,
        incremental=not args.full)
    print(f"[research_extract] {args.month} claims={res['stats']['total']} "
          f"(+{res['stats'].get('new_claims', 0)} new, "
          f"new_articles={res['stats'].get('new_articles', 0)}, "
          f"incremental={res['stats'].get('incremental')}) "
          f"invalid={res['stats']['invalid']} cost=${res['stats']['cost_usd']}")
    for b in res["stats"]["batches"]:
        print(f"  {b['source_type']} batch{b['batch']}: in={b['n_in']} "
              f"valid={b['n_valid']} abort={b['abort']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
