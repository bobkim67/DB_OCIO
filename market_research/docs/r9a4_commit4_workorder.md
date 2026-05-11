# R9-A.4 Commit 4 작업지시서 — CLI flag + write gate + out-of-band guard

작성일: 2026-05-11
선행: Commit 1 (`812aaa8`) + Commit 2 (`a0576d1`) + Commit 3 (`ccd69b3`) + 9.3a sub-smoke (`bcafdfd`) push 완료. 447 PASS. 보호 영역 6 md5 + 08_Claims 8 + ledger 1 row + Step 2.7 default OFF 모두 동일.
입력: mini-spec `r9a4_minispec.md` (D-1~D-8), Commit 3 작업지시서 `r9a4_commit3_workorder.md` §10 (Commit 3/4 경계), 9.3a 진단 (9.2 fixture 18-claim plan rate=100% / out_of_band=True / Rule B 전수 통과).

본 문서는 R9-A.4 Commit 4 코드 진입 전 작업지시서. **현재 단계 코드 변경 0 / LLM 호출 0 / file write 0**. 사용자 검토 후 별 트랙으로 구현 진입.

---

## 1. 목표 (Goals)

Commit 4 는 R9-A.4 의 **실 write 기능 구현이 아니라, 실 write 를 안전하게 열 수 있는 게이트 구현**.

구체적으로:

1. CLI flag 3종 추가 — opt-in 만으로 실행/저장 활성화
2. write gate 다단 검증 — flag + monthly cap + plan + failure matrix + out_of_band
3. out_of_band drift monitoring — block reason / monitoring fields 명시
4. Rule B / prompt 즉시 calibrate 보류 — drift 는 warning/monitoring 으로 남기고 후속 트랙 (9.3b / Commit 5)
5. 운영 default 영향 0 — flag 없이 실행하면 기존 동작과 동일

**핵심 invariant**: `--enable-claim-extraction` + `--write-claims` 가 명시되지 않으면 canonical/wiki/ledger 어디에도 안 씀. `--allow-out-of-band` 가 명시되지 않으면 out_of_band=True plan 의 실 write 도 차단.

## 2. Non-goals (Commit 4 미포함)

- **Rule B 임계 변경** (chain ≥ 2 → ≥ 3 등) — 9.3b 또는 Commit 5 후보
- **claim_extractor_prompt 본문 큰 변경** — 후속 prompt calibration 트랙
- **Haiku 모델 변경 / Sonnet 비교** — D-8 future option
- **9.2 결과 운영 `data/claims/2026-04.json` 으로 승급** — Commit 4 후 별 트랙 (9.3 controlled write smoke 에서 target_suffix 분리로 검증)
- **daily_update default ON 전환** — R9-A.6 끝까지 OFF
- **target_suffix 미지정 시 운영 file 덮어쓰기** — 9.3 controlled write smoke 통과 전 보류

## 3. 변경 예상 파일

| 파일 | 종류 | 변경 |
|---|---|---|
| `market_research/pipeline/daily_update.py` | modify | argparse +3 flag + Step 2.7 호출 시 flag 전달 (~+30 LOC) |
| `market_research/pipeline/claim_extract_step.py` | modify | write gate 분기 + write_block_reason + monitoring fields + 실 write 함수 호출 (write_canonical/wiki/ledger 가 모두 True 일 때만) (~+120 LOC) |
| `market_research/analyze/claim_store.py` | (선택) modify | `save_claims_canonical` 의 target_suffix 분리 path 지원 (~+15 LOC) — 또는 step 측에서 직접 처리 |
| `market_research/wiki/claim_pages.py` | (선택) modify | `promote_claims(write_canonical=True)` 호출 시 ledger row 인자 통일 (~+5 LOC) |
| `market_research/tests/test_claim_extract_step_commit4.py` | NEW | 7 카테고리 (A~G) 신규 tests (~+250 LOC) |
| `market_research/tests/test_daily_update_cli_claim_flags.py` | NEW | argparse 분기 + dry-run 분리 동작 (~+80 LOC) |

총 신규 2 file + 변경 2~4 file. LOC ~+500 (테스트 포함).

## 4. CLI flag 추가

기존 daily_update CLI 에 다음 3개 flag 를 추가.

| flag | default | 의미 |
|---|---|---|
| `--enable-claim-extraction` | False | Step 2.7 (claim extraction) 진입 opt-in. 이 flag 없으면 기존 `ENABLE_CLAIM_EXTRACTION=False` 그대로 따름. |
| `--write-claims` | False | canonical/wiki/ledger 실 write opt-in. flag 없으면 dry-run/plan/debug 까지만 실행. |
| `--allow-out-of-band` | False | out_of_band=True plan 의 실 write 허용 opt-in. flag 없으면 out_of_band=True 일 때 write abort. |

부가 — 추후 옵션 (Commit 4 또는 Commit 5):
- `--target-suffix=<str>` : `data/claims/{period}.{suffix}.json` 분리 저장. 9.3 controlled write smoke 용도 (운영 파일 보존).
- `--force-claim-extract` : per-run cost cap 무시 (admin 전용, Commit 5 후보).
- `--monthly-cap=<float>` : default $1.0 override.

### 4.1 기존 `--dry-run` 과의 관계

`--dry-run` (기존, daily_update 전체) : 수집/분류만 실행, GraphRAG / regime / claim extraction 모두 skip.
`--write-claims` 미지정 : Step 2.7 의 실 write 만 차단. Step 2.7 진입은 `--enable-claim-extraction` 으로 결정.

→ 기본 호출 `python -m market_research.pipeline.daily_update` 는 Step 2.7 skip (`ENABLE_CLAIM_EXTRACTION=False`).
→ `python -m market_research.pipeline.daily_update --enable-claim-extraction` 은 Step 2.7 실행하지만 write 0 (dry-run/plan only).
→ `python -m market_research.pipeline.daily_update --enable-claim-extraction --write-claims` 은 실 write 활성화 (단, out_of_band=True 면 차단).
→ `python -m market_research.pipeline.daily_update --enable-claim-extraction --write-claims --allow-out-of-band` 은 out_of_band=True 도 write 허용.

### 4.2 flag → `step_claim_extract` parameter mapping

```python
step_claim_extract(
    period=...,
    enabled=args.enable_claim_extraction or ENABLE_CLAIM_EXTRACTION,
    write_canonical=args.write_claims,
    write_wiki=args.write_claims,
    write_ledger=args.write_claims,
    allow_out_of_band=args.allow_out_of_band,   # NEW
    target_suffix=args.target_suffix,           # NEW (선택)
    ...
)
```

## 5. Write gate 조건표

`step_claim_extract` 내부에서 실 write 직전 다단 검증.

| 단계 | 조건 (allow) | 차단 시 처리 |
|---|---|---|
| G-1 | `enabled=True` (`--enable-claim-extraction` 또는 모듈 default) | STATUS_DISABLED 반환 — 호출 0 |
| G-2 | `evidence_items` non-empty | STATUS_SKELETON / no_input — 호출 0 |
| G-3 | `monthly_so_far + est_cost <= monthly_cap_usd` | STATUS_COST_CAP_MONTHLY_PRE_ABORT — LLM 0 / write 0 |
| G-4 | `cost_cap_pre_estimate <= cost_cap_usd` (runner 내부) | STATUS_COST_CAP_PRE_ABORT — LLM 0 / write 0 |
| G-5 | runner abort_reason ∉ {llm_api_failure, json_parse_failed} | STATUS_RUNNER_ABORTED — write 0 |
| G-6 | valid_count > 0 | STATUS_NO_VALID_CLAIMS — write 0 |
| G-7 | period_mismatch_ids == [] | STATUS_PERIOD_MISMATCH — write 0 |
| G-8 | `plan.promoted_count > 0` | STATUS_PROMOTION_ZERO — write 0 |
| G-9 | `plan.skip_reasons.duplicate_existing + supporting_diff_existing + merge_conflict == 0` | STATUS_MERGE_CONFLICT_PREVIEW — write 0 (Commit 4 단계, Commit 5 후속 merge 정책) |
| G-10 | invalid_count == 0 (overlay: STATUS_PARTIAL_EXTRACTION 가능) | partial_extraction 이면 plan 통과는 OK, write 시 `write_block_reason=invalid_present` 로 추가 차단 (안전망) |
| **G-11** | **`write_canonical` AND `write_wiki` AND `write_ledger` 모두 True (=`--write-claims`)** | flag 없으면 STATUS_OK_PLAN_READY 그대로 — plan/debug 만 반환 (Commit 3 동작과 동일) |
| **G-12** | **`plan.out_of_band == False` OR `allow_out_of_band == True`** | 차단 시: status overlay `STATUS_PROMOTION_OUT_OF_BAND` + `write_block_reason="out_of_band_default_block"` |

G-11/G-12 통과 시에만 실 write 진입:
- `save_claims_canonical(period, valid_claims, source, extractor_version, promotion_result=plan, target_suffix=target_suffix)`
- `promote_claims(valid_claims, rule=rule, force_ids=force_promote_ids, dry_run=False)` → wiki 페이지 생성
- `append_promotion_ledger(ledger_row)` → 24필드 row append

### 5.1 write_block_reason 표

| reason | 의미 |
|---|---|
| `default_dry_run` | `--write-claims` 미지정 — plan/debug only |
| `out_of_band_default_block` | out_of_band=True + `--allow-out-of-band` 미지정 |
| `monthly_cap_exceeded` | G-3 차단 |
| `cost_cap_pre_estimate` | G-4 차단 |
| `runner_aborted` | G-5 차단 |
| `no_valid_claims` | G-6 차단 |
| `period_mismatch` | G-7 차단 |
| `promotion_zero` | G-8 차단 |
| `merge_conflict_present` | G-9 차단 |
| `invalid_present` | G-10 차단 (overlay 안전망) |
| `None` | 통과 → 실 write 완료 |

## 6. out_of_band drift monitoring

`step_claim_extract` 반환 dict 에 monitoring 정보 일관 노출. ledger row preview 에도 동일 키 포함 (24 → 28~30 필드 확장 가능, 단 LEDGER_ROW_FIELDS schema 확장은 Commit 4 일관 처리).

### 6.1 신규 / 확장 필드

| 필드 | 출처 | 의미 |
|---|---|---|
| `write_allowed` | step | 최종 write 진입 여부 (bool) |
| `write_block_reason` | step | 차단 사유 (위 §5.1 표 또는 None) |
| `allow_out_of_band` | step | flag 값 echo |
| `write_claims` | step | flag 값 echo |
| `monthly_cost_before` | ledger | 호출 전 누적 cost |
| `monthly_cost_after_estimate` | step | before + est_cost |
| `candidate_count` | plan | input_count (valid claims) |
| `canonical_existing_conflict_count` | plan | merge_conflicts list 길이 |

기존 필드 (Commit 3) 유지:
- promoted_count / skipped_count / promotion_rate / rule_breakdown / out_of_band

### 6.2 9.2 같은 drift case 의 노출 문구

`out_of_band=True` 이고 `--allow-out-of-band` 미지정인 경우, `write_block_reason="out_of_band_default_block"` 와 함께 warning 에 다음 취지:

```
"promotion_rate=100.0% is out-of-band relative to R9-A.2 acceptance band
 [30.0, 70.0]; --allow-out-of-band 미지정 → canonical/wiki/ledger write 차단.
 R9-A.1 manual pilot rate=36.4% 대비 drift. Rule B (causal_chain≥2) 전수 통과
 가능성 — calibration 은 9.3b/Commit 5 트랙에서 결정."
```

문구는 코드 스타일에 맞게 조정 가능 (한 줄 ≤ 120자 권장).

## 7. Rule B / prompt drift 처리 (보류 정책)

Commit 4 에서:
- Rule B threshold `chain_len >= 2` 변경 **금지**
- claim_extractor_prompt.py 본문 실질 변경 **금지** (오타/타입 수정만 허용)

대신:
- `write_block_reason="out_of_band_default_block"` + warning 로 surface
- 매 호출의 ledger row 에 `promotion_rate` / `rule_breakdown` 누적 → 후속 calibration 데이터
- TODO 주석 (`# TODO(r9a.5-calibration): Rule B threshold review`) 명시
- handoff 메모리 + docs 에 추적 항목 명시

후속 트랙:
- **9.3b** : Haiku 재호출로 9.2 18-claim 재현성 검증. 동일 drift 인지 확인.
- **Commit 5 후보** : Rule B threshold calibration (chain≥3) 또는 ACCEPTANCE_BAND 조정 또는 prompt 가이드 강화. 각 옵션의 trade-off 분석 후 결정.

## 8. 변경되는 ledger row schema

§6.1 의 신규 필드 4개 (`write_allowed`, `write_block_reason`, `allow_out_of_band`, `write_claims`) 와 `monthly_cost_before`, `monthly_cost_after_estimate`, `candidate_count`, `canonical_existing_conflict_count` 까지 합쳐 ledger preview row 가 24 → 32 필드.

- `LEDGER_ROW_FIELDS` tuple 확장 — Commit 3 의 24필드 호환 (기존 row 의 missing 필드는 None / 0 로 graceful)
- `validate_ledger_row_preview` 동기 갱신
- 기존 R9-A.1 manual_pilot row 영향 0 (filter 그대로)
- Commit 3 신규 24필드 row 영향 0 (확장만, 기존 키 변경 없음)

## 9. 테스트 계획 (A~G)

### A. default off
- flag 없이 daily_update 실행 시 Step 2.7 진입 0 (`STATUS_DISABLED`)
- `ENABLE_CLAIM_EXTRACTION=False` invariant 유지
- LLM 호출 0 / canonical 등 write 0

### B. dry-run path
- `--enable-claim-extraction` 단독 (`--write-claims` 없음)
- → status=`STATUS_OK_PLAN_READY` / `STATUS_PROMOTION_OUT_OF_BAND` / ... 등 plan 결과 노출
- `write_allowed=False` / `write_block_reason="default_dry_run"`
- LLM 호출 1 (stub) / canonical 등 write 0

### C. write allowed path
- `--enable-claim-extraction --write-claims`
- Fixture: rate 40% in-band + 정상 plan
- canonical/wiki/ledger 실 write 함수 호출 검증 (mock / tmp_path 기반)
- `write_allowed=True` / `write_block_reason=None`
- 실제 repo 보호 파일 변경 0 (tmp_path 격리)

### D. out_of_band blocked path
- `--enable-claim-extraction --write-claims` (`--allow-out-of-band` 없음)
- Fixture: rate 100% / out_of_band=True (9.2 fixture mimic)
- canonical/wiki/ledger write 0
- `write_allowed=False` / `write_block_reason="out_of_band_default_block"`
- warning 에 acceptance band drift 메시지 포함

### E. out_of_band allowed path
- `--enable-claim-extraction --write-claims --allow-out-of-band`
- Fixture: 동일 out_of_band=True
- write 함수 호출 허용
- `write_allowed=True` / `allow_out_of_band=True`
- monitoring fields 그대로 노출 (rate, rule_breakdown, drift 정보)

### F. monthly cap pre-abort
- `--enable-claim-extraction --write-claims` + ledger override 로 monthly_so_far ≈ cap
- LLM 호출 0 / write 0
- `write_allowed=False` / `write_block_reason="monthly_cap_exceeded"`

### G. invalid dump / failure matrix
- F-3 (partial_extraction) 시 `--write-claims` 있어도 `write_block_reason="invalid_present"` overlay → write 0
- F-1 (llm_api_failure), F-7 (cost_cap_pre_estimate) 시에도 write 0
- invalid raw dump path 명시 / write_invalid_dump=True 시 `would_save` invalid_raw_dump entry 그대로

### H (보조). CLI argparse 회귀
- `--enable-claim-extraction` / `--write-claims` / `--allow-out-of-band` 각각 인식
- 기존 `--dry-run` 동작 회귀 0
- positional `date` 인자 회귀 0
- 기본 호출 (`python -m market_research.pipeline.daily_update`) 시 Step 2.7 skip

### 회귀
- 기존 447 PASS 모두 유지
- 보호 영역 6 md5 + 08_Claims 8 + ledger 1 row + Step 2.7 default OFF 변경 0

## 10. 9.3 controlled write smoke (Commit 4 close 후 별 트랙)

Commit 4 close 후, 사용자 GO 시:
- `python -m market_research.pipeline.daily_update <date> --enable-claim-extraction --write-claims --target-suffix=r9a4-replay`
- 운영 `data/claims/2026-04.json` 보존 검증 (md5 da3fed58... 그대로)
- `data/claims/2026-04.r9a4-replay.json` 신규 생성 검증
- `wiki/08_Claims/` 페이지는 idempotent — 동일 cid 면 skip / 신규 cid 면 추가
- `_promotion_quality.jsonl` row +1 (R9-A.4 row, source=daily_update_r9a4)

본 smoke 는 Commit 4 본체에 포함되지 않음. 사용자 별도 GO 시 진입.

## 11. Acceptance criteria (Commit 4 close)

- [ ] CLI flag 3종 추가 + argparse 회귀 0
- [ ] write gate G-1~G-12 모두 코드화
- [ ] write_block_reason 11종 정확히 매핑
- [ ] out_of_band drift monitoring fields 노출 (ledger row schema 확장 포함)
- [ ] Rule B threshold / prompt 본문 변경 0
- [ ] 9.3a smoke 18 cases 회귀 0
- [ ] 신규 tests A~H 카테고리 모두 PASS
- [ ] market_research/tests 전체 PASS (예상 447 + 신규 ~25)
- [ ] 보호 영역 변경 0:
  - `data/claims/2026-04.json` md5 da3fed58... 동일
  - `wiki/08_Claims/*.md` count 8 동일
  - `_promotion_quality.jsonl` row 1 (R9-A.1 manual_pilot) 동일
  - `_market.final.json` md5 81eb876b... 동일
  - `07G04.final.json` md5 f522cd67... 동일
  - `regime_memory.json` md5 1ee7151c... 동일
- [ ] daily_update 기본 호출 (flag 없음) → Step 2.7 skip 회귀 0

## 12. C4-Q1~Q6 — 구현 GO 전 결정 사항

| # | 항목 | 후보 | default 추천 |
|---|---|---|---|
| **C4-Q1** | `--write-claims` 기본값 | (A) False — 명시 opt-in (B) True — daily_update default 따라 | **(A)** — 안전 우선, 9.2 drift 노출 |
| **C4-Q2** | `--write-claims` 가 canonical/wiki/ledger 3종을 동시 토글 vs 분리 | (A) 단일 flag — 3종 한꺼번에 (B) 분리 flag 3개 | **(A)** — 운영 단순성 (Commit 5 에서 분리 가능) |
| **C4-Q3** | out_of_band block 시 plan/ledger preview 도 차단? | (A) preview 는 노출 — debugging 가치 (B) preview 도 차단 | **(A)** — plan/preview/debug 까지만 보존 |
| **C4-Q4** | target_suffix 미지정 시 운영 파일 덮어쓰기 허용? | (A) 허용 — Commit 3 동작 (B) 9.3 smoke 통과 전 차단 | **(B)** — 안전 우선. 9.3 controlled smoke 통과 후 (A) 로 결정 |
| **C4-Q5** | merge_conflict 발생 시 default 동작 | (A) write 차단 (Commit 4) — Commit 5 에서 정식 merge (B) prefer_higher_confidence 자동 merge | **(A)** — D-5 policy 확정 전까지 보수적 차단 |
| **C4-Q6** | Rule B threshold 즉시 변경? | (A) 변경 (chain≥3) — drift 즉시 차단 (B) 변경 0 — monitoring 만 | **(B)** — 본 docs §7 일관 |

6개 모두 default 명확. 사용자 다른 안 선호 시 fix 후 진입.

## 13. 구현 sub-commit split (Commit 4 본체)

| Sub-commit | 범위 |
|---|---|
| C4-α | `daily_update.py` argparse +3 flag + Step 2.7 호출 시 flag 전달 |
| C4-β | `claim_extract_step.py` write gate G-11/G-12 + write_block_reason + monitoring fields |
| C4-γ | `claim_extract_step.py` 실 write 분기 (write_canonical/wiki/ledger=True 시 `save_claims_canonical` / `promote_claims` / `append_promotion_ledger` 호출) + target_suffix 분리 |
| C4-δ | `claim_ledger_schema.py` 24 → 32 필드 확장 + validate 동기 |
| C4-ε | tests A~H 카테고리 |

α → β → δ → γ → ε 순 권장 (gate 먼저, write 마지막). 단일 Commit 4 으로 묶어도 OK (~500 LOC, 회귀 명확).

## 14. Rollback plan

- C4 회귀: `git revert <C4 commit>` (C1~C3 + 9.3a 보존)
- CLI flag 만 disable: argparse 항목 제거 → step 함수 default 값 (Commit 3 동작) 유지
- write gate 만 disable: G-11 가 항상 False → 실 write 0 (Commit 3 동작)
- 보호 영역 의심 시: `data/claims/2026-04.json` md5 재확인 + `git stash` + rollback

## 15. 보호 영역 invariant (Commit 4 진입 전)

| 영역 | 현재 |
|---|---|
| `regime_memory.json` md5 | `1ee7151c8c381217c7b34393b0054daf` |
| `data/claims/2026-04.json` md5 | `da3fed58512829099a624ddb5fc1c85f` |
| `_market.final.json` md5 | `81eb876ba8b82b23a2a3dcec3de2f5bc` |
| `07G04.final.json` md5 | `f522cd673c8df342c21459990e86eff1` |
| `wiki/08_Claims/*.md` 파일 수 | 8 |
| `_promotion_quality.jsonl` row | 1 (manual_pilot_r9a1) |
| daily_update Step 2.7 default | OFF |
| origin/main | `bcafdfd` (9.3a 직후) |

Commit 4 close 시점에도 위 invariant 모두 동일해야 함.

## 16. 다음 신호 옵션

| 신호 | 액션 |
|---|---|
| **"C4-Q1~6 default 그대로, Commit 4 구현 시작"** (1순위) | C4-α → β → δ → γ → ε 순 진입 |
| "Commit 4 작업지시서 commit + push 먼저" | docs/ 1 path staging → 그 후 구현 |
| "C4-Qx 결정값 변경 — {답변}" | 해당 항목 fix 후 구현 |
| "작업지시서 보강 — {섹션}" | 코드 0 으로 보강 |
| "Commit 4 보류, 9.3b 먼저" | Haiku 재호출 1회 ($0.014) + plan 재현성 검증 후 결정 |
| "Rule B threshold calibration 별 트랙" | Commit 4 보류 + Commit 5 후보로 즉시 진입 |

본 작업지시서 자체는 사용자 commit 결정 별로 처리.

## 17. 산출물 (Commit 4 close 시점)

- 변경 파일 목록
- 추가/수정 테스트 목록 (A~H 카테고리)
- CLI flag 동작표
- write gate 조건표 (G-1~G-12)
- write_block_reason 분포 (이번 PR 의 회귀 데이터 기준)
- out_of_band drift 대응 방식 (block + warning + monitoring)
- pytest 결과 (예상 447 + 신규 ~25)
- 보호 invariant 결과 (6 md5 + 08_Claims + ledger + Step 2.7 default)
- commit hash
- push 여부
- 후속 권장:
  1) **9.3b** : Haiku 재호출 1회로 18-claim 재현성 + Rule B drift 재확인 ($0.014)
  2) **9.3 controlled write smoke** : `--target-suffix=r9a4-replay` 로 분리 저장, 운영 파일 보존 검증
  3) **Commit 5** : 9.3b 결과 따라 Rule B threshold / prompt / ACCEPTANCE_BAND 중 하나를 calibrate

## 18. 결론

R9-A.4 Commit 4 의 핵심:
- CLI flag 3종 — `--enable-claim-extraction` / `--write-claims` / `--allow-out-of-band`
- write gate G-1~G-12 다단 검증
- out_of_band drift monitoring (block + warning)
- Rule B / prompt 즉시 변경 0 (drift 는 surface 만)
- 운영 default 영향 0

**Commit 4 는 "실 write 기능 구현"이 아니라 "실 write 를 안전하게 열 수 있는 게이트 구현".**

Commit 4 close 후 남은 단계:
- 9.3b (Haiku 재호출, 사용자 GO 시 $0.014)
- 9.3 controlled write smoke (target_suffix 분리, 사용자 GO 시)
- Commit 5 (Rule B/prompt/band calibration 결정)
- R9-A.6 운영 사이클 1회 (R9-A.4 close 후)
