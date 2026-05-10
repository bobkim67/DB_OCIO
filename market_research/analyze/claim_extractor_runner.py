# -*- coding: utf-8 -*-
"""R9-A.4 Commit 2 (C2-β) — claim extractor runner.

Haiku LLM call wrapper + R9-A.0 validate + invalid 분리 + cost cap.

Commit 2 invariant (mini-spec D-1~D-8):
  - LLM 모델: Haiku 고정 (D-8) — 모듈 상수 LLM_MODEL
  - retry 0 (C2-Q7) — 단일 호출
  - blocking (C2-Q8) — streaming 미사용
  - llm_call 인자로 _call_llm 재사용 가능 (C2-Q2 default)
  - dry_run=True 가 default — Commit 2 에서는 file write 0 보장 (호출자 책임)
  - per-run cost cap 사전 추정 + 사후 actual 검증 (C2-Q4)
  - failure 6 유형 모두 graceful (raise 0, abort_reason 으로 surface)

Commit 3+ 책임:
  - canonical store / wiki / ledger 실 write
  - monthly cost cap (ledger 기반)
  - invalid raw response 의 정식 dump (현재는 raw_response 키로 반환만)
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from market_research.analyze.claim_extractor import (
    normalize_claim,
    serialize_claim,
    validate_claim,
)
from market_research.analyze.claim_extractor_prompt import (
    EXTRACTOR_VERSION,
    LLM_MODEL,
    MAX_INPUT_EVIDENCE,
    MAX_TOKENS,
    SOURCE,
    build_extraction_prompt,
)


# ──────────────────────────────────────────────────────────────────
# Cost estimation (Haiku 기준)
# ──────────────────────────────────────────────────────────────────

# 가격 (대략, 모델 변경 시 갱신 필요).
_HAIKU_INPUT_USD_PER_M = 0.80
_HAIKU_OUTPUT_USD_PER_M = 4.00

# Korean+English 혼용 토큰 추정 비율 (chars/token). 보수적 1 char ≈ 1/3.5 token.
_CHARS_PER_TOKEN = 3.5


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text or "") / _CHARS_PER_TOKEN))


def _estimate_cost_usd(input_text: str, output_text_or_max: str | int) -> float:
    in_tokens = _estimate_tokens(input_text)
    if isinstance(output_text_or_max, str):
        out_tokens = _estimate_tokens(output_text_or_max)
    else:
        out_tokens = max(1, int(output_text_or_max))
    return round(
        in_tokens / 1_000_000 * _HAIKU_INPUT_USD_PER_M
        + out_tokens / 1_000_000 * _HAIKU_OUTPUT_USD_PER_M,
        6,
    )


# ──────────────────────────────────────────────────────────────────
# Pre-call cost estimator (C3-δ — monthly cap 사전 추정용 public helper)
# ──────────────────────────────────────────────────────────────────

def estimate_pre_call_cost_usd(
    period: str,
    evidence_items: list[dict] | None,
    *,
    max_items: int = MAX_INPUT_EVIDENCE,
) -> float:
    """LLM 호출 0 으로 본 runner 가 호출 시 소요할 추정 비용 (USD).

    `extract_claims` 의 §6.2~6.3 와 동일한 prompt build + token 추정 path 를
    재사용. 호출 측은 (monthly_so_far + estimated) 와 monthly cap 비교를
    사전 분기에 사용한다.

    invariant:
        - LLM 호출 0 / file write 0 / network 0
        - evidence 가 비어 있으면 0.0 반환
    """
    if not evidence_items:
        return 0.0
    items = [e for e in evidence_items if isinstance(e, dict)][:max_items]
    if not items:
        return 0.0
    prompt_dict = build_extraction_prompt(period, items, max_items=max_items)
    return _estimate_cost_usd(prompt_dict["user"], MAX_TOKENS)


# ──────────────────────────────────────────────────────────────────
# Default LLM call — debate_engine._call_llm 재사용 (C2-Q2)
# ──────────────────────────────────────────────────────────────────

def _default_llm_call(prompt_dict: dict[str, Any]) -> str:
    """C2-Q2 default: debate_engine._call_llm 재사용. 실 LLM 호출."""
    from market_research.report.debate_engine import _call_llm
    return _call_llm(
        model=prompt_dict["model"],
        system=prompt_dict["system"],
        prompt=prompt_dict["user"],
        max_tokens=prompt_dict["max_tokens"],
        log_label="r9a4_claim_extractor",
    )


# ──────────────────────────────────────────────────────────────────
# Response parsing
# ──────────────────────────────────────────────────────────────────

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _strip_json_fence(text: str) -> str:
    """LLM 출력이 ```json ... ``` 로 감싸져 있으면 제거."""
    if not text:
        return ""
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _parse_response_to_list(raw: str) -> list[dict] | None:
    """raw 응답 → list[dict]. 실패 시 None.

    JSON 배열 (R9-A.1 schema) 만 허용. 단일 dict 도 list 로 wrap.
    """
    if not raw:
        return None
    candidate = _strip_json_fence(raw)
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        # 일부 LLM 이 trailing text 포함 → 첫 [ 부터 마지막 ] 까지 시도
        s = candidate.find("[")
        e = candidate.rfind("]")
        if s >= 0 and e > s:
            try:
                obj = json.loads(candidate[s:e + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None
    if isinstance(obj, dict):
        return [obj]
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    return None


# ──────────────────────────────────────────────────────────────────
# Public API — extract_claims
# ──────────────────────────────────────────────────────────────────

def extract_claims(
    period: str,
    evidence_items: list[dict] | None,
    *,
    max_items: int = MAX_INPUT_EVIDENCE,
    dry_run: bool = True,
    cost_cap_usd: float = 0.5,
    llm_call: Callable[[dict], str] | None = None,
) -> dict[str, Any]:
    """Claim extraction runner.

    Parameters
    ----------
    period : "YYYY-MM"
    evidence_items : refined evidence (memory dict — C2-Q1)
    max_items : 최대 입력 evidence 수 (default 50, R9-A.1 동일)
    dry_run : Commit 2 에서는 file write 0 (caller 책임). flag 자체는 metadata
              로만 surface — 실제 write 는 step_claim_extract / Commit 3+.
    cost_cap_usd : per-run cap (D-4)
    llm_call : LLM 호출 callable. None 이면 _default_llm_call (C2-Q2 default).
                테스트 monkeypatch 용도.

    Returns
    -------
    dict with keys:
      claims               : list[dict] — validate 통과 (deterministic ID 부여)
      invalid_claims       : list[{"raw": dict, "errors": list[str]}]
      warnings             : list[str]
      usage                : {"approx_input_tokens", "approx_output_tokens",
                              "elapsed_seconds"}
      cost_usd             : 추정 비용
      extractor_version    : "r9a.4-haiku"
      source               : "daily_update_r9a4"
      dry_run              : bool
      abort_reason         : None 또는 'no_evidence' / 'cost_cap_exceeded_estimate'
                              / 'llm_api_failure' / 'json_parse_failed'
      raw_response         : LLM 원본 (debug 용)

    Failure 6 유형 모두 graceful — raise 0 (D-6).
    """
    base_meta = {
        "extractor_version": EXTRACTOR_VERSION,
        "source": SOURCE,
        "dry_run": bool(dry_run),
    }

    # 6.1 — evidence 빈 case
    if not evidence_items:
        return {
            "claims": [],
            "invalid_claims": [],
            "warnings": ["evidence_empty"],
            "usage": {},
            "cost_usd": 0.0,
            "abort_reason": "no_evidence",
            "raw_response": "",
            **base_meta,
        }

    # 6.2 — prompt build
    items = [e for e in evidence_items if isinstance(e, dict)][:max_items]
    if not items:
        return {
            "claims": [],
            "invalid_claims": [],
            "warnings": ["evidence_empty_after_filter"],
            "usage": {},
            "cost_usd": 0.0,
            "abort_reason": "no_evidence",
            "raw_response": "",
            **base_meta,
        }
    prompt_dict = build_extraction_prompt(period, items, max_items=max_items)

    # 6.3 — pre-call cost estimate (C2-Q4 사전 추정)
    est_cost = _estimate_cost_usd(prompt_dict["user"], MAX_TOKENS)
    if est_cost > cost_cap_usd:
        return {
            "claims": [],
            "invalid_claims": [],
            "warnings": [
                f"cost_cap_exceeded_estimate: ${est_cost:.4f} > ${cost_cap_usd}"
            ],
            "usage": {"approx_input_tokens": _estimate_tokens(prompt_dict["user"]),
                       "approx_output_tokens_max": MAX_TOKENS},
            "cost_usd": est_cost,
            "abort_reason": "cost_cap_exceeded_estimate",
            "raw_response": "",
            **base_meta,
        }

    # 6.4 — LLM call (C2-Q7 retry 0, C2-Q8 blocking)
    call = llm_call if callable(llm_call) else _default_llm_call
    t0 = time.time()
    try:
        raw = call(prompt_dict)
    except Exception as exc:
        return {
            "claims": [],
            "invalid_claims": [],
            "warnings": [f"llm_api_failure: {exc}"],
            "usage": {"elapsed_seconds": round(time.time() - t0, 3)},
            "cost_usd": 0.0,
            "abort_reason": "llm_api_failure",
            "raw_response": "",
            **base_meta,
        }
    elapsed = round(time.time() - t0, 3)
    raw = raw or ""

    # 6.5 — parse
    parsed = _parse_response_to_list(raw)
    if parsed is None:
        return {
            "claims": [],
            "invalid_claims": [{"raw": raw[:1000], "errors": ["json_parse_failed"]}],
            "warnings": ["json_parse_failed"],
            "usage": {"approx_input_tokens": _estimate_tokens(prompt_dict["user"]),
                       "approx_output_tokens": _estimate_tokens(raw),
                       "elapsed_seconds": elapsed},
            "cost_usd": _estimate_cost_usd(prompt_dict["user"], raw),
            "abort_reason": "json_parse_failed",
            "raw_response": raw,
            **base_meta,
        }

    # 6.6 — validate + 분리 (R9-A.0 재사용)
    valid: list[dict] = []
    invalid: list[dict] = []
    for raw_claim in parsed:
        try:
            normalized = normalize_claim({
                **raw_claim,
                "period": period,
                "extractor_version": EXTRACTOR_VERSION,
                "extraction_method": "llm",
            })
            v = validate_claim(normalized)
            if v["valid"]:
                valid.append(serialize_claim(normalized))
            else:
                invalid.append({"raw": raw_claim, "errors": v["errors"]})
        except Exception as exc:
            invalid.append({"raw": raw_claim, "errors": [f"normalize_error: {exc}"]})

    # 6.7 — post-call actual cost (C2-Q4 사후 검증)
    actual_cost = _estimate_cost_usd(prompt_dict["user"], raw)
    warnings: list[str] = []
    if actual_cost > cost_cap_usd:
        warnings.append(
            f"cost_cap_exceeded_actual: ${actual_cost:.4f} > ${cost_cap_usd}"
        )
    if not valid:
        warnings.append("no_claims_extracted")

    return {
        "claims": valid,
        "invalid_claims": invalid,
        "warnings": warnings,
        "usage": {
            "approx_input_tokens": _estimate_tokens(prompt_dict["user"]),
            "approx_output_tokens": _estimate_tokens(raw),
            "elapsed_seconds": elapsed,
        },
        "cost_usd": actual_cost,
        "abort_reason": None,
        "raw_response": raw,
        **base_meta,
    }
