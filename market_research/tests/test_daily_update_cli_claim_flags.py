# -*- coding: utf-8 -*-
"""R9-A.4 Commit 4 — CLI argparse 3+1 flag 회귀 (H 카테고리).

`__main__` 블록의 argparse 분기를 시뮬레이션 — daily_update 함수 시그니처가
flag 를 모두 받는지 + step_claim_extract 호출 시 flag 가 전달되는지 검증.

실제 daily_update full pipeline 은 호출하지 않음 (DB / 네트워크 의존). 본
테스트는 argparse + 함수 시그니처 + 호출 위임 회귀만.
"""
from __future__ import annotations

import inspect

from market_research.pipeline import daily_update as du_module


def test_c4_H_daily_update_signature_has_new_kwargs():
    """daily_update 함수가 4개 신규 keyword param 을 모두 받는지."""
    sig = inspect.signature(du_module.daily_update)
    expected = {
        "enable_claim_extraction",
        "write_claims",
        "allow_out_of_band",
        "target_suffix",
    }
    assert expected <= set(sig.parameters.keys()), (
        f"daily_update missing kwargs: "
        f"{expected - set(sig.parameters.keys())}"
    )


def test_c4_H_daily_update_kwargs_default_off():
    """4개 flag 모두 default False / None — 운영 default OFF 보장."""
    sig = inspect.signature(du_module.daily_update)
    assert sig.parameters["enable_claim_extraction"].default is False
    assert sig.parameters["write_claims"].default is False
    assert sig.parameters["allow_out_of_band"].default is False
    assert sig.parameters["target_suffix"].default is None


def test_c4_H_argparse_source_has_all_flags():
    """daily_update.py 의 argparse block 에 4개 신규 flag 가 들어있음."""
    from pathlib import Path
    src = (Path(du_module.__file__)).read_text(encoding="utf-8")
    for flag in (
        "--enable-claim-extraction",
        "--write-claims",
        "--allow-out-of-band",
        "--target-suffix",
    ):
        assert flag in src, f"argparse 에 누락된 flag: {flag}"
    # 기존 flag 회귀 0
    assert "--dry-run" in src
    # daily_update() 호출에 flag 전달 회귀
    assert "enable_claim_extraction=args.enable_claim_extraction" in src
    assert "write_claims=args.write_claims" in src
    assert "allow_out_of_band=args.allow_out_of_band" in src
    assert "target_suffix=args.target_suffix" in src


def test_c4_H_step_27_call_passes_flags():
    """Step 2.7 호출 site 에서 step_claim_extract 에 flag 가 전달."""
    from pathlib import Path
    src = (Path(du_module.__file__)).read_text(encoding="utf-8")
    # 호출 부에서 step_claim_extract 가 모든 flag 를 인자로 받는지
    assert "step_claim_extract(" in src
    # 단순 문자열 substring 검사 — 호출 block 매칭 대신 전체 source 에서
    # 각 인자 forwarding pattern 확인 (paren counting 회피).
    assert "enabled=(True if enable_claim_extraction else None)" in src
    assert "write_canonical=bool(write_claims)" in src
    assert "write_wiki=bool(write_claims)" in src
    assert "write_ledger=bool(write_claims)" in src
    assert "allow_out_of_band=bool(allow_out_of_band)" in src
    assert "target_suffix=target_suffix" in src
