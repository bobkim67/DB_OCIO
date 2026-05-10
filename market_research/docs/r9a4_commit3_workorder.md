# R9-A.4 Commit 3 작업지시서 — failure handling + monthly cap + ledger preview + promotion plan

작성일: 2026-05-08
선행: Commit 1 (`812aaa8`) + Commit 2 (`a0576d1`) push 완료, 9.1 / 9.2 sub-smoke PASS
입력: mini-spec `r9a4_minispec.md` (D-1~D-8 fix), Commit 2 작업지시서 `r9a4_commit2_workorder.md`, 9.2 실 응답 형태 (`debug/claims/r9a4_92_dryrun_result.json`, gitignored)

본 문서는 R9-A.4 Commit 3 코드 진입 전 작업지시서. **현재 단계 코드 변경 0 / LLM 호출 0 / file write 0**. 사용자 검토 후 별 트랙 구현 진입.

---

## 1. 목표 (Goals)

R9-A.4 Commit 3 단계는 R9-A.4 의 **실 write 직전까지 운영 안전장치 완성**.
구체적으로:

1. failure handling matrix 의 10개 case 별 동작 코드화
2. monthly cost cap ($1) 정식 구현 (per-run cap $0.5 위에)
3. promotion plan 생성 (R9-A.2 promotion rule A3 재사용) — 단, **실 write 0**
4. ledger row preview schema — gitignored ledger 의 정식 schema 확정
5. dry-run debug dump 경로 정식화 (옵션)
6. would_save summary 강화 — Commit 4 실 write 시 사용할 구체적 path / count

**핵심 invariant**: Commit 3 도 **canonical store / wiki / ledger 실 write 0**. write 는 Commit 4 에서 활성화.

## 2. Non-goals (Commit 3 미포함)

- **canonical store / wiki / ledger 실 write** (Commit 4 → R9-A.6 트랙)
- 9.2 결과 운영 `data/claims/2026-04.json` 으로 승급 (별 트랙)
- daily_update default ON 전환 (R9-A.6 끝까지 OFF)
- CLI flag 노출 (Commit 4 — `--dry-run-claim` / `--target-suffix` / `--allow-out-of-band`)
- LLM 모델 변경 / Sonnet 비교 (D-8 future option)
- canonical store merge 정식 호출 (Commit 4)
- Out-of-band guard CLI 노출 (Commit 4)

## 3. 변경 예상 파일

| 파일 | 종류 | 변경 |
|---|---|---|
| `market_research/pipeline/claim_extract_step.py` | modify | failure matrix + monthly cap + promotion plan + would_save 강화 (~+150 LOC) |
| `market_research/analyze/claim_extractor_runner.py` | modify | monthly cap 인자 + 사후 cost cap warning 강화 (~+30 LOC) |
| `market_research/pipeline/claim_promotion_plan.py` | NEW | promotion rule A3 재사용 + plan dict 생성 (~+100 LOC) |
| `market_research/pipeline/claim_ledger_schema.py` | NEW | ledger row dataclass / preview builder (~+60 LOC) |
| `market_research/tests/test_claim_promotion_plan.py` | NEW | 5 cases — A3 rule + out-of-band detection |
| `market_research/tests/test_claim_ledger_schema.py` | NEW | 4 cases — row schema + preview 검증 |
| `market_research/tests/test_claim_extract_step_skeleton.py` | modify | +6 cases — failure matrix + monthly cap + would_save 강화 |

총 신규 4 file + 변경 3 file. LOC ~+400.

## 4. Failure handling matrix (10 case)

본 매트릭스는 Commit 3 의 핵심. 각 case 별로 `status` / `warning_code` / `daily_update_continue` / `write` / `ledger_row` / `abort` 동작을 코드화.

| # | Case | status | warning_code | daily_update | write | ledger row | abort |
|---|---|---|---|---|---|---|---|
| F-1 | LLM API failure | `runner_aborted` | `llm_api_failure` | continue (graceful) | 0 | preview only | runner internal |
| F-2 | malformed JSON | `runner_aborted` | `json_parse_failed` | continue | 0 | preview + raw_dump_path | runner internal |
| F-3 | validator invalid > 0 (일부) | `partial_extraction` | `validator_partial` | continue | 0 (Commit 3) | preview + invalid_count | no |
| F-4 | valid claims = 0 (Haiku 빈 응답) | `no_valid_claims` | `no_claims_extracted` | continue | 0 | preview + warning | no |
| F-5 | promotion 통과 0건 (D-6) | `promotion_zero` | `no_promotion_passed` | continue | 0 | preview + promoted=0 | no |
| F-6 | promotion out-of-band (rate > 70% / < 30%) | `promotion_out_of_band` | `promotion_rate_violation` | continue | 0 (Commit 3 plan only) | preview + rate | Commit 4 에서 abort 결정 (D-7) |
| F-7 | cost cap pre-estimate 초과 | `cost_cap_pre_abort` | `cost_cap_exceeded_estimate` | continue | 0 | preview + estimated_cost | runner internal |
| F-8 | cost cap post-actual 초과 (warning) | `partial_extraction` | `cost_cap_exceeded_actual` | continue | 0 | preview + actual_cost | no |
| F-9 | period mismatch (claim.period != input period) | `period_mismatch` | `period_inconsistent` | continue | 0 | preview + offending_claim_ids | no |
| F-10 | duplicate / conflict merge case (canonical 기존 hash 충돌) | `merge_conflict_preview` | `merge_skip_existing` | continue | 0 (Commit 4 에서 실 merge) | preview + duplicate_count + supporting_diff_count | no |

### 통합 분기 로직 (`step_claim_extract` 확장)

```
runner 호출 결과
  ├── abort_reason in {no_evidence, cost_cap_exceeded_estimate, llm_api_failure, json_parse_failed}
  │     → status=runner_aborted, warning_code from abort_reason
  └── claims/invalid 분리 결과
        ├── invalid > 0 → F-3
        ├── valid == 0 → F-4
        └── valid > 0
              ↓ promotion plan 생성 (Commit 3 신규)
              ├── promoted == 0 → F-5
              ├── promotion_rate out-of-band → F-6
              ├── period mismatch → F-9
              ├── existing canonical 충돌 (hash) → F-10
              └── 정상 → status=ok_plan_ready (Commit 4 에서 실 write)

post-call cost > cap_per_run → F-8 warning (status overlay)
post-month cost > cap_monthly → status=cost_cap_pre_abort (실 호출은 이미 됨, ledger 기록만)
```

모든 case 에서 daily_update raise 0 (D-6 graceful 정책).

## 5. Monthly cap 설계 (D-4)

### 5.1 데이터 source
**선택**: `_promotion_quality.jsonl` 의 row 확장 (별도 usage ledger 미신설).

이유:
- 기존 ledger schema 가 R9-A.2 manual smoke 부터 운영 중
- gitignored 유지로 운영 환경 영향 0
- period 별 cost_usd 누적 row 가 자연스럽게 monthly cap source

### 5.2 누적 계산

```python
def compute_monthly_cost(period: str) -> float:
    # period = "2026-04" 의 month 와 동일한 month 의 ledger row 들 합산
    # extractor_version='r9a.4-haiku' AND source='daily_update_r9a4' filter
    rows = load_ledger_rows()
    return sum(
        r.get("cost_usd", 0)
        for r in rows
        if r.get("period", "").startswith(period[:7])  # YYYY-MM
        and r.get("extractor_version") == "r9a.4-haiku"
        and r.get("source") == "daily_update_r9a4"
    )
```

### 5.3 cap 동작
```
estimated_run_cost = ...
monthly_so_far = compute_monthly_cost(period)
if monthly_so_far + estimated_run_cost > MONTHLY_CAP ($1):
    → status="cost_cap_monthly_pre_abort"
    → abort_reason="cost_cap_exceeded_monthly"
    → LLM 호출 0
    → ledger row preview (write 0, Commit 4 에서 actual append 결정)
```

### 5.4 Commit 3 에서 cap 검증만, 실 write 0
- monthly cap 위반 감지 시: runner 호출 차단
- ledger append 는 Commit 4 (write_ledger=True 활성화 시) 에서만

## 6. Ledger row schema (정식)

R9-A.2 `_promotion_quality.jsonl` 의 기존 schema 를 확장. **gitignored 유지** (D-7).

### 6.1 신규 필수 필드 + 기존 필드 통합

```json
{
  "ts": "2026-05-08T16:15:11+09:00",
  "period": "2026-04",
  "source": "daily_update_r9a4",
  "extractor_version": "r9a.4-haiku",

  "input_count": 50,
  "valid_claim_count": 18,
  "invalid_claim_count": 0,

  "promoted_count": 8,
  "skipped_count": 10,
  "promotion_rate": 44.4,
  "rule": "auto",
  "rule_breakdown": {"A": 2, "B": 6, "C": 0},
  "skip_reasons": {"rule_a_b_unmet": 10, "duplicate_existing": 0,
                    "supporting_diff_existing": 0, "validation_failed": 0,
                    "merge_conflict": 0},

  "cost_usd": 0.0138,
  "monthly_cost_usd_so_far": 0.0138,

  "dry_run": false,
  "write_canonical": false,
  "write_wiki": false,
  "write_ledger": false,

  "status": "ok_plan_ready",
  "abort_reason": null,
  "warnings": [],

  "out_of_band_override": false,
  "target_suffix": null
}
```

### 6.2 기존 R9-A.2 ledger row 와 호환성
- 기존 `manual_pilot_r9a1` row 는 보존
- 신규 필드는 R9-A.4 row 에만 채움 (기존 row 의 missing 필드 = None / 0)
- `compute_monthly_cost` 가 source/extractor_version filter 로 R9-A.4 row 만 합산 → R9-A.2 manual pilot row 영향 0

### 6.3 row 호출 빈도
- daily_update Step 2.7 호출 1회 = ledger row 1개
- 단 Commit 3 단계에서 **실 append 0**
- preview row 는 step result 의 `ledger_row_preview` 키로 반환만

## 7. Promotion plan (R9-A.2 rule 재사용)

### 7.1 신규 모듈 `claim_promotion_plan.py`

```python
def build_promotion_plan(
    claims: list[dict],
    *,
    rule: str = "auto",
    force_ids: list[str] = (),
    canonical_existing: dict | None = None,
) -> dict:
    """R9-A.2 promotion_rule A3 재사용 + merge 충돌 체크 + plan dict 반환.

    canonical_existing : load_claims_canonical(period) 결과 (이미 저장된 claims).
                          None 이면 신규 period 가정 (모두 신규).

    Returns:
        {
            "promoted_claim_ids": [...],
            "skipped_claim_ids": [...],
            "promoted_count": int,
            "skipped_count": int,
            "promotion_rate": float,
            "rule_breakdown": {"A", "B", "C"},
            "skip_reasons": {
                "rule_a_b_unmet": int,
                "duplicate_existing": int,
                "supporting_diff_existing": int,
                "validation_failed": int,
                "merge_conflict": int,
            },
            "out_of_band": bool,
            "would_write": [
                {"kind": "canonical_claim", "claim_id": ..., "wiki_page": ...},
                ...
            ],
            "merge_conflicts": [...],
        }
    """
```

### 7.2 R9-A.2 rule 재사용 — 변경 0
- `_meets_rule_a` (assets ≥ 3) / `_meets_rule_b` (causal_chain ≥ 2) / Rule C (force_ids)
- 임계 변경 0 (D-4 promotion threshold A3 유지)
- `ACCEPTANCE_BAND = (30.0, 70.0)` 재사용

### 7.3 out-of-band detection (write 0)
Commit 3 단계: out-of-band 감지 시 `out_of_band=True` 만 plan 에 표시. abort/proceed 는 Commit 4 에서 `--allow-out-of-band` flag 와 함께 결정.

### 7.4 merge conflict 감지
canonical_existing 의 claim_id 와 신규 claim_id 비교:
- 동일 + supporting_evidence_ids 동일 → `duplicate_existing` skip
- 동일 + supporting 다름 → `supporting_diff_existing` skip + warning
- canonical_existing 의 ledger source 가 `manual_pilot_r9a1` 이면 별 카테고리 (manual_pilot 보존 정책 명시)

## 8. Dry-run debug dump 정책

### 8.1 옵션 구조
```python
def step_claim_extract(
    period, *, ...,
    dry_run_debug_path: str | Path | None = None,  # NEW (Commit 3)
):
    """
    dry_run_debug_path:
        None (default)  → debug dump 0
        Path provided   → debug/claims/ 이하만 허용. 그 외 경로 → ValueError
                           dump 내용: 9.2 와 동일 형식 (raw_response 별도 분리)
    """
```

### 8.2 Path 검증
- `debug/claims/` 이하만 허용 (D-3 결정값)
- 다른 경로 → `ValueError` raise (graceful 정책 위반 — 명백한 호출 측 오류)
- gitignored 유지

### 8.3 9.2 vs Commit 3 비교
- 9.2: 즉석 Python 스크립트가 직접 dump
- Commit 3: `step_claim_extract` 가 `dry_run_debug_path` 옵션 받아 dump 위치 통일

## 9. would_save summary 강화

Commit 2 의 `would_save` 는 path 후보만. Commit 3 에서 실제 write 직전 정보까지 채움:

```python
{
    "kind": "canonical_store",
    "path": "market_research/data/claims/2026-04.json",  # 또는 suffix
    "enabled_in_this_commit": False,  # Commit 3 → False
    "merge_policy": "prefer_higher_confidence",
    "existing_claim_count": 22,           # canonical 이미 있을 때
    "would_add_count": 8,
    "would_skip_count": 10,
    "would_overwrite_count": 0,
},
{
    "kind": "wiki_08_claims",
    "path": "market_research/data/wiki/08_Claims/",
    "enabled_in_this_commit": False,
    "would_create_pages": [
        {"hash10": "e1c5ac2b57", "filename": "2026-04_claim_e1c5ac2b57.md"},
        ...
    ],
    "would_skip_pages_count": 0,
},
{
    "kind": "promotion_ledger",
    "path": "market_research/data/claims/_promotion_quality.jsonl",
    "enabled_in_this_commit": False,
    "would_append_row": <ledger_row_preview>,
}
```

## 10. Commit 3 / Commit 4 경계

| 단계 | 책임 |
|---|---|
| **Commit 3** | failure matrix + monthly cap + promotion plan + ledger preview + would_save 강화. **write 0** |
| **Commit 4** | CLI flag (`--dry-run-claim` / `--force-claim-extract` / `--target-suffix` / `--allow-out-of-band`) + canonical/wiki/ledger 실 write 활성화. write_canonical 등 flag 가 True 일 때만 실 호출 |

### Commit 4 진입 시 추가될 책임 (Commit 3 미포함)

- `target_suffix` 기반 file path 분리 실 적용
- `claim_store.save_claims_canonical` 실 호출
- `claim_pages.promote_claims` 실 호출 (out-of-band guard 포함)
- `_promotion_quality.jsonl` 실 append
- daily_update CLI argparse 확장
- 9.3 controlled write smoke (target_suffix 분리)
- R9-A.6 운영 사이클 1회

## 11. 테스트 계획

### 11.1 신규 — `test_claim_promotion_plan.py` (5 cases)

1. A3 rule pass — 18 claims 중 일부 promoted
2. out-of-band detection — promotion_rate 86% (R9-A.2 default A0 시뮬) → out_of_band=True
3. merge conflict — canonical_existing 에 동일 claim_id 존재 시 duplicate_existing 카운트
4. supporting_evidence_ids 다름 → supporting_diff_existing
5. force_ids 강제 promote → C breakdown +1

### 11.2 신규 — `test_claim_ledger_schema.py` (4 cases)

1. 정상 row schema — 필수 필드 모두 채움
2. R9-A.2 manual pilot row 와 호환 (extra 필드만 추가)
3. monthly_cost_usd_so_far 계산 — 동일 month + source filter
4. ledger row preview vs actual (Commit 3 단계 actual=None)

### 11.3 보강 — `test_claim_extract_step_skeleton.py` (+6 cases)

1. F-3 — invalid > 0 → status="partial_extraction"
2. F-4 — valid 0 → status="no_valid_claims"
3. F-6 — out-of-band → status="promotion_out_of_band"
4. F-7 — cost cap pre-estimate 초과 (이미 Commit 2)
5. monthly cap pre-abort — 누적 cost > $1
6. dry_run_debug_path 검증 — debug/claims/ 외 path 거부

### 11.4 회귀
- 기존 402 PASS 모두 유지
- R9-A.2 promotion_pages 21 PASS / R9-A.5 trace 18 PASS / R9-A.4 Commit 1+2 28 PASS 회귀 0

## 12. Smoke 계획

### 12.1 9.3a — LLM 0 promotion plan smoke
- 9.2 result fixture (`debug/claims/r9a4_92_dryrun_result.json`) 의 18 claims 입력
- `build_promotion_plan` + `step_claim_extract` (LLM 호출 0, evidence 미포함)
- 검증: would_save / promotion_rate / merge_conflict_count
- write 0

### 12.2 9.3b (옵션, 사용자 별도 GO) — Haiku 재호출 + plan
- 9.2 와 동일 evidence_items 로 Haiku 재호출 1회 (~$0.014)
- runner 결과 → promotion plan
- write 0 (Commit 3 invariant)

### 12.3 Commit 4 진입 후 — controlled write
- target_suffix="r9a4-replay" 로 `data/claims/2026-04.r9a4-replay.json` 분리 저장
- 운영 `data/claims/2026-04.json` md5 동일 보장

## 13. 구현 GO 전 결정 사항 (C3-Q1~6)

| # | 항목 | 후보 | default 추천 |
|---|---|---|---|
| **C3-Q1** | failure F-3 (invalid > 0) 시 valid 만으로 plan 생성 | (A) Yes — partial_extraction (B) No — abort | **(A)** — daily_update 영향 최소 |
| **C3-Q2** | F-6 out-of-band 시 plan 생성 여부 | (A) plan 생성 + flag (B) plan 생성 안 함 | **(A)** — Commit 4 에서 `--allow-out-of-band` 로 결정 |
| **C3-Q3** | monthly cap source | (A) `_promotion_quality.jsonl` 확장 (B) 별도 usage 파일 | **(A)** — gitignore 유지, 운영 영향 0 |
| **C3-Q4** | dry_run_debug_path default | (A) None (dump 0) (B) `debug/claims/{period}.dryrun.{ts}.json` 자동 | **(A)** — 명시 호출자만 dump |
| **C3-Q5** | merge_policy in plan | (A) prefer_higher_confidence (mini-spec D-5) (B) prefer_existing | **(A)** — D-5 결정값 유지 |
| **C3-Q6** | invalid raw 의 dump 시점 | (A) Commit 3 에서 step 호출 시 (write_* 와 무관) (B) write_invalid_dump=True flag 따로 | **(B)** — explicit flag, 일관성 |

6개 모두 default 명확. 사용자 다른 안 선호 시 fix 후 진입.

## 14. 구현 sub-commit split (Commit 3 본체)

| Sub-commit | 범위 |
|---|---|
| C3-α | `claim_promotion_plan.py` 신설 — A3 rule 재사용 + plan dict |
| C3-β | `claim_ledger_schema.py` 신설 — row schema + preview builder + monthly cost compute |
| C3-γ | `claim_extract_step.py` 확장 — failure matrix + monthly cap + plan 통합 + would_save 강화 |
| C3-δ | runner 의 monthly cap 호출 시그니처 보강 (필요 시) |
| C3-ε | tests (3 신규/보강) |

α → β → γ → δ → ε 순. 사용자 단계별 검토 게이트.
혹은 단일 Commit 3 으로 묶어도 OK (~400 LOC, 회귀 명확 + LLM 0).

## 15. Acceptance criteria (Commit 3 close)

- [ ] failure matrix 10 case 모두 코드화 + 테스트
- [ ] monthly cap pre-abort 정상 (cost > $1 시 LLM 호출 0)
- [ ] promotion plan 생성 — R9-A.2 rule A3 재사용
- [ ] ledger row preview schema 안정 (필수 21 필드)
- [ ] would_save 강화 — canonical/wiki/ledger 별 detail
- [ ] 9.3a (LLM 0 plan smoke) PASS
- [ ] 보호 영역 변경 0:
  - `data/claims/2026-04.json` md5 da3fed58... 동일
  - `wiki/08_Claims/*.md` mtime 동일
  - `_promotion_quality.jsonl` row 1 그대로
  - `_market.final.json` md5 81eb876b... 동일
  - `regime_memory.json` md5 1ee7151c... 동일
- [ ] Commit 1 + 2 회귀 0 (기존 402 PASS 유지)
- [ ] R9-A.4 Commit 4+ 선반영 0 (CLI flag / 실 write 미진입)

## 16. Rollback plan

- Commit 3 회귀: `git revert <C3 commits>` (Commit 1+2 보존)
- promotion_plan 모듈 disable: `step_claim_extract` 의 plan 호출 try/except 내부 → fallback "plan_unavailable"
- monthly cap 미작동: per-run cap 만 사용 (Commit 2 동작 유지)
- 운영 default 영향 0 — `ENABLE_CLAIM_EXTRACTION=False` 그대로

## 17. 보호 영역 invariant (Commit 3 진입 전)

| 영역 | 현재 |
|---|---|
| `regime_memory.json` md5 | `1ee7151c8c381217c7b34393b0054daf` |
| `data/claims/2026-04.json` md5 | `da3fed58512829099a624ddb5fc1c85f` |
| `_market.final.json` md5 | `81eb876ba8b82b23a2a3dcec3de2f5bc` |
| `07G04.final.json` md5 | `f522cd673c8df342c21459990e86eff1` |
| `wiki/08_Claims/*.md` 파일 수 | 8 |
| `_promotion_quality.jsonl` row | 1 |
| daily_update Step 2.7 default | OFF |
| origin/main | `a0576d1` (Commit 2 push 직후) |

Commit 3 close 시점에도 위 invariant 모두 동일해야 함.

## 18. 다음 신호 옵션

| 신호 | 액션 |
|---|---|
| **"C3-Q1~6 default 그대로, Commit 3 구현 시작"** (1순위 추천) | C3-α → β → γ → δ → ε 순 진입 |
| "Commit 3 작업지시서 commit + push 먼저" | docs/ 1 path staging → 그 후 구현 |
| "C3-Qx 결정값 변경 — {답변}" | 해당 항목 fix 후 구현 |
| "작업지시서 보강 — {섹션}" | 코드 0 으로 보강 |
| "Commit 3 보류, 9.3a smoke 먼저" | 9.2 fixture 로 promotion plan dry-run 만 (코드 0, sub-smoke) |
| "Commit 3 이후 직접 Commit 4 작업지시서" | Commit 3 마무리 후 진입 |

본 작업지시서 자체는 untracked 상태 — 사용자 commit 결정 별로 처리.

---

## 19. 결론

R9-A.4 Commit 3 의 핵심:
- failure handling 10 case 코드화
- monthly cap $1 (D-4)
- promotion plan dict (R9-A.2 rule 재사용)
- ledger row preview schema (~21 fields)
- would_save 강화 (canonical/wiki/ledger 별 detail)
- **실 write 0 — Commit 4 까지 보류**

Commit 3 close 후:
- 9.3a (LLM 0 plan smoke) — 사용자 별도 GO
- 9.3b (Haiku 재호출 + plan, 옵션) — 사용자 별도 GO
- Commit 4 진입 — CLI flag + 실 write 활성화 + target_suffix 분리

R9-A.4 전체 close 까지 남은 단계: **Commit 3 / Commit 4 / 9.3a / 9.3b (옵션) / R9-A.6 운영 사이클**.
