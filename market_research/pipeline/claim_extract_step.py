# -*- coding: utf-8 -*-
"""R9-A.4 Step 2.7 — claim extractor 정기 batch (skeleton).

본 모듈은 R9-A.4 mini-spec (`docs/r9a4_minispec.md`) 의 Commit 1 단계
(skeleton only). 실제 LLM 호출 / canonical store write / wiki page
write 는 모두 후속 commit 에서 추가.

현 단계 (Commit 1) 의 책임:
  - daily_update Step 2.7 진입점 placeholder
  - feature flag (default OFF) 로 운영 default 무영향 보장
  - status dict 반환 (LLM 0 / write 0)
  - 테스트 가능한 함수 분리 — daily_update_test 가 monkey-patch 하지 않고도
    skeleton 동작 검증 가능

다음 commit 범위 (본 모듈 미포함):
  - Commit 2: claim_extractor_prompt 모듈 + Haiku 호출
  - Commit 3: failure handling + warning ledger row
  - Commit 4: CLI flag (--dry-run-claim / --force-claim-extract /
              --target-suffix / --allow-out-of-band)
  - Commit 5: 9건 unit test

설계 invariant (R9-A.4 mini-spec 결정값):
  - D-1 frequency 마커 = data/claims/{period}.json 의 saved_at
  - D-2 target suffix = {period}.{suffix}.json 분리 file
  - D-3 invalid raw dump = debug/claims/ (gitignored)
  - D-4 cost cap 위반 → abort + warning
  - D-5 prompt 위치 = market_research/analyze/claim_extractor_prompt.py
        (Commit 2 에서 신설)
  - D-6 promotion 0건 → graceful warning, 중단 X
  - D-7 --allow-out-of-band = admin 전용 노출
  - D-8 LLM = Haiku 고정 (claude-haiku-4-5-*)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


# ──────────────────────────────────────────────────────────────────
# Feature flag (default OFF)
# ──────────────────────────────────────────────────────────────────
# Commit 1 단계 — daily_update 운영 default 에서 Step 2.7 가 no-op 임을 보장.
# True 로 켜도 본 skeleton 은 LLM 호출 0 / file write 0.
# Commit 2+ 에서 실제 extractor 가 연결되면 이 flag 가 운영 활성화 토글이 됨.
ENABLE_CLAIM_EXTRACTION: bool = False

# Status enum-like 상수
STATUS_DISABLED = "disabled"
STATUS_SKELETON = "skeleton_no_op"


def step_claim_extract(
    period: str,
    *,
    enabled: bool | None = None,
    target_suffix: str | None = None,
    evidence_items: list[dict] | None = None,
    dry_run: bool = True,
    cost_cap_usd: float = 0.5,
    write_canonical: bool = False,
    write_wiki: bool = False,
    write_ledger: bool = False,
    llm_call=None,
) -> dict[str, Any]:
    """daily_update Step 2.7 진입점.

    Commit 1: skeleton no-op (LLM 0 / write 0).
    Commit 2: enabled=True + evidence_items 주어지면 runner 호출 (LLM 1회 가능).
              write_* flag 모두 default False → file write 0 (dry-run path).
    Commit 3+: write_* flag 활성화 시 canonical / wiki / ledger 실 write.

    Parameters
    ----------
    period : "YYYY-MM"
    enabled : feature flag override. None 이면 ENABLE_CLAIM_EXTRACTION.
    target_suffix : D-2 — replay/smoke 산출물 분리. Commit 2 단계 echo 만.
    evidence_items : refined evidence (memory dict, C2-Q1). None / [] 이면
                      runner 호출 0.
    dry_run : Commit 2 default True — runner 결과를 metadata 로만 반환.
    cost_cap_usd : per-run cap (D-4)
    write_canonical / write_wiki / write_ledger : Commit 2 단계 default 모두
                      False → 호출 측이 명시 True 해도 본 commit 에선 차단
                      (Commit 3+ 에서 활성화).
    llm_call : 테스트 / admin override 용도. None 이면 runner default
                (debate_engine._call_llm 재사용).

    Returns
    -------
    status dict (확장):
      기존: status / period / enabled / target_suffix / ts / llm_calls /
            writes / notes
      신규 (Commit 2):
        + extraction : runner 결과 dict 또는 None
        + would_save : [{"path", "kind"}, ...] (write_* flag 가 True 였을 때
                        예정 path. 본 commit 에선 항상 빈 list 또는 후보만)
        + actually_saved : []  (Commit 2 단계 항상 빈 list 보장)

    Invariants (Commit 2):
      - daily_update 운영 default 영향 0 (ENABLE_CLAIM_EXTRACTION=False)
      - file write 0 — write_* 모두 무시 (Commit 3+ 에서 정식 활성화)
      - failure 6 유형 graceful (raise 0)
      - extraction 결과는 metadata only — caller 가 검토 후 후행 commit 에서
        canonical/wiki/ledger 쓰기 결정
    """
    use_enabled = (
        bool(enabled) if enabled is not None
        else bool(ENABLE_CLAIM_EXTRACTION)
    )
    ts = datetime.now().isoformat(timespec="seconds")

    base = {
        "period": period,
        "enabled": use_enabled,
        "target_suffix": target_suffix,
        "ts": ts,
        "llm_calls": 0,
        "writes": 0,
        "extraction": None,
        "would_save": [],
        "actually_saved": [],
    }

    if not use_enabled:
        return {
            **base,
            "status": STATUS_DISABLED,
            "notes": (
                "R9-A.4 Step 2.7 disabled. ENABLE_CLAIM_EXTRACTION=False — "
                "extractor / canonical write 미실행."
            ),
        }

    # enabled=True — Commit 2 분기
    if not evidence_items:
        return {
            **base,
            "status": STATUS_SKELETON,
            "notes": (
                "Step 2.7 enabled 이나 evidence_items=None/[] — runner 호출 0. "
                "no_input."
            ),
        }

    # Commit 2 — runner 호출 가능. file write 는 차단 (write_* flag 무시).
    try:
        from market_research.analyze.claim_extractor_runner import (
            extract_claims,
        )
        result = extract_claims(
            period=period,
            evidence_items=evidence_items,
            dry_run=True,         # Commit 2: 항상 dry-run (write 0)
            cost_cap_usd=cost_cap_usd,
            llm_call=llm_call,
        )
    except Exception as exc:
        # Runner import 실패 또는 unforeseen — graceful (D-6)
        return {
            **base,
            "status": STATUS_SKELETON,
            "notes": f"runner 호출 실패 (graceful): {exc}",
        }

    llm_calls = (
        0 if result.get("abort_reason") in
        ("no_evidence", "cost_cap_exceeded_estimate") else 1
    )

    # would_save: Commit 3+ 에서 활성화될 path 후보. 본 commit 에선 metadata
    # 만 — write_* 가 True 여도 actually_saved 는 빈 list.
    would_save: list[dict] = []
    if write_canonical or write_wiki or write_ledger:
        would_save.append({
            "kind": "canonical_store",
            "path": (
                f"market_research/data/claims/{period}"
                + (f".{target_suffix}" if target_suffix else "")
                + ".json"
            ),
            "enabled_in_this_commit": False,
        })
        would_save.append({
            "kind": "wiki_08_claims",
            "path": "market_research/data/wiki/08_Claims/",
            "enabled_in_this_commit": False,
        })
        would_save.append({
            "kind": "promotion_ledger",
            "path": "market_research/data/claims/_promotion_quality.jsonl",
            "enabled_in_this_commit": False,
        })

    return {
        **base,
        "status": STATUS_SKELETON,
        "llm_calls": llm_calls,
        "writes": 0,  # invariant — Commit 2 file write 0
        "extraction": result,
        "would_save": would_save,
        "actually_saved": [],
        "notes": (
            f"Step 2.7 enabled. runner 호출 {llm_calls}회. "
            f"abort_reason={result.get('abort_reason')}. "
            f"claims={len(result.get('claims', []))} / "
            f"invalid={len(result.get('invalid_claims', []))}. "
            "file write 0 (Commit 2 invariant — write 는 Commit 3+ 에서)."
        ),
    }
