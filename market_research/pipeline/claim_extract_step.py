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
) -> dict[str, Any]:
    """daily_update Step 2.7 진입점 (Commit 1 skeleton).

    Parameters
    ----------
    period : "YYYY-MM" — daily_update 의 month_str 그대로
    enabled : feature flag override. None 이면 모듈 기본값 ENABLE_CLAIM_EXTRACTION
              사용. 테스트 / admin override 용도.
    target_suffix : D-2 결정값 — replay/smoke 산출물 분리용. 본 commit 에서는
                     status 에 echo 만 하고 file 분리는 Commit 2+ 에서 사용.

    Returns
    -------
    status dict:
      {
        "status": "disabled" | "skeleton_no_op",
        "period": str,
        "enabled": bool,
        "target_suffix": str | None,
        "ts": ISO8601,
        "llm_calls": 0,
        "writes": 0,
        "notes": str,
      }

    Invariants (Commit 1):
      - LLM 호출 0
      - file write 0 (canonical store / wiki / ledger 모두 미접근)
      - daily_update 전체 흐름에 영향 0 (status dict 반환만)
      - 어떤 입력에서도 raise 0 — daily_update 의 graceful 정책 (D-6) 보장
    """
    use_enabled = (
        bool(enabled) if enabled is not None
        else bool(ENABLE_CLAIM_EXTRACTION)
    )
    ts = datetime.now().isoformat(timespec="seconds")

    if not use_enabled:
        return {
            "status": STATUS_DISABLED,
            "period": period,
            "enabled": False,
            "target_suffix": target_suffix,
            "ts": ts,
            "llm_calls": 0,
            "writes": 0,
            "notes": (
                "R9-A.4 Commit 1 skeleton. ENABLE_CLAIM_EXTRACTION=False — "
                "Step 2.7 no-op. extractor / canonical write 는 Commit 2+ 에서."
            ),
        }

    # enabled=True 라도 Commit 1 단계에서는 실제 추출 0
    return {
        "status": STATUS_SKELETON,
        "period": period,
        "enabled": True,
        "target_suffix": target_suffix,
        "ts": ts,
        "llm_calls": 0,
        "writes": 0,
        "notes": (
            "R9-A.4 Commit 1 skeleton — flag 켜져 있으나 실제 extractor / "
            "canonical write 는 Commit 2+ 에서. 본 단계 status 만 반환."
        ),
    }
