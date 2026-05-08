# R9-A.4 mini-spec — daily_update Step 2.7 claim extractor 정기 batch

작성일: 2026-05-08
상태: design only (구현 0)
선행: R9-A.5-UI Option A close (`6c2df90`), Review Packet (`81537b0`)
입력: Review Packet `r9a_review_packet_pre_a4.md` §6 (TBD 8개) 의 사용자 기본 결정값

본 문서는 R9-A.4 코드 구현 진입 전 최소 설계. **코드 변경 0 / LLM 호출 0 / daily_update 수정 0**.
사용자 mini-spec 검토 + 미결정 항목 (TBD) 결정 후 별 트랙으로 구현 진입.

---

## 1. 목표 (Goals)

R9-A.1 manual pilot (Haiku 1회) 으로 검증된 claim extractor 를 daily_update 의 정기 batch 로 통합한다. 매 월 1회 자동 실행으로:

- 신규 period 의 evidence pool 에서 canonical claim 자동 추출
- promotion rule (A3) 적용 후 `data/claims/{YYYY-MM}.json` canonical store + `wiki/08_Claims/{YYYY-MM}_claim_*.md` 자동 생성
- 기존 R9-A.3/R9-A.5 read-side chain (debate inline / fund_comment persist / Admin UI) 을 신규 period 에서도 자동으로 활성화

R9-A.5-UI 까지 read-side 가 완성된 상태 → R9-A.4 는 **데이터 공급 자동화** 만 추가. 표시/매핑은 변경 0.

## 2. Non-goals (이번 트랙 미포함)

- 운영 final / approved 직접 수정 (read-only 정책 유지)
- 기존 `data/claims/2026-04.json` 직접 overwrite (merge 정책으로 보호)
- promotion threshold 재조정 (A3 유지)
- ReportFinalView client viewer 노출 (Option B 별 트랙)
- claim wiki page 의 admin 검수/승인 워크플로 (8_Claims write 만, 검수는 별 트랙)
- daily_update Step 0~5 (기존) 의 다른 step 변경
- backwards backfill (과거 period 일괄 추출 — 별 트랙)

## 3. daily_update 삽입 위치

### 결정값 (사용자 6.1)
**Step 2.7 — Refine 직후 / GraphRAG 직전**

```
Step 0: 매크로 지표 수집
Step 1: 뉴스 수집
Step 1.5/1.6: 블로그 수집 + 인사이트
Step 2: 뉴스 분류 (Haiku, TOPIC_TAXONOMY)
Step 2.5: 정제 (_step_refine — dedupe / salience / fallback classify)
Step 2.6: Base wiki pages (01_Events / 02_Entities / 03_Assets / 04_Funds)

★ Step 2.7 (NEW): Claim extractor batch
  - input: refined evidence pool (Step 2.5 결과)
  - output: data/claims/{period}.json + wiki/08_Claims/*.md (promoted 만)
  - LLM: Haiku 1 call (~$0.05)
  - frequency: monthly (월말 또는 새 month 의 첫 daily_update 1회만)

Step 3: GraphRAG 증분 + transmission path
Step 4: MTD 델타 요약
Step 5: regime canonical writer
```

### 진입점
`market_research/pipeline/daily_update.py` — Step 2.6 직후 신규 함수 호출 (예: `_step_claim_extract(month_str)`).

### Step 2.7 실행 조건 (frequency control)
**결정값 (사용자 6.2): monthly 1회**

- 매 daily 실행 시 호출되지만, 신규 추출은 **해당 month 에 처음 호출되는 daily_update 만**.
- 마커: `data/claims/{period}.json` 의 `saved_at` 또는 `_promotion_quality.jsonl` 의 마지막 row 기준.
- 이미 해당 period 가 존재하면 skip (no-op + log).
- override 옵션: `--force-claim-extract` flag (admin 검수용).

## 4. Input source

- **evidence pool**: Step 2.5 의 정제 결과 (`data/news/{period}.json` 의 refined articles)
- **샘플링**: R9-A.1 pilot 과 동일 — 상위 salience N 건 (default 50, R9-A.1 기준)
- **prompt template**: 기존 R9-A.1 manual pilot 의 Haiku prompt 재사용 (debug 디렉토리 또는 `market_research/analyze/claim_extractor_prompt.py` 신설)
- **deterministic ID**: R9-A.0 `compute_claim_id` 그대로 사용 → R9-A.1 pilot 과 동일 evidence + 동일 claim_text 입력 시 동일 claim_id

## 5. Output target

### 결정값 (사용자 6.3, 6.7)

| 출력 | 정책 |
|---|---|
| `market_research/data/claims/{period}.json` | merge (§6 참조) — 기존 file 있으면 보존, 신규 claim_id 만 append/update |
| `market_research/data/wiki/08_Claims/{period}_claim_{hash10}.md` | promotion 통과 (Rule A3 또는 B) 만 신규 page 생성. 기존 page 는 `_is_claim_wiki` guard 로 protect |
| `market_research/data/claims/_promotion_quality.jsonl` | append 1 row (R9-A.2 ledger 패턴 그대로). gitignore 유지 |

### Source / version 메타
- `source = "daily_update_r9a4"` (R9-A.1 manual pilot `manual_pilot_r9a1` 와 분리)
- `extractor_version = "r9a.4-haiku"` (R9-A.0 `r9a.0` / R9-A.1 `r9a.1-haiku` 와 분리)
- canonical store payload 의 `source` / `extractor_version` 키 사용 → 추후 추적

## 6. Overwrite / merge 정책

### 결정값 (사용자 6.5)
**`prefer_higher_confidence` merge** (이미 `claim_store.merge_claims` 에 구현됨)

```
existing canonical (기존 file)
  + new extraction (Step 2.7 결과)
  ↓ merge_claims(existing, new, policy="prefer_higher_confidence")
  → 동일 claim_id: confidence 높은 쪽 유지
  → 신규 claim_id: append
  → existing claim_id 가 new 에 없으면: 보존 (drop 안 함)
```

### 충돌 처리
- 동일 `claim_id` + 동일 `supporting_evidence_ids` → silent skip (duplicate_existing)
- 동일 `claim_id` + 다른 `supporting_evidence_ids` → conservative skip + warning ledger row
- destructive overwrite **금지** — `save_claims_canonical` 의 validate-then-save 정책 그대로

### 기존 R9-A.2 산출물 보호
- `data/claims/2026-04.json` (md5 `da3fed58…`) 는 **이번 R9-A.4 dry-run / replay 단계에서 직접 변경 0**.
- replay 시 별도 suffix path (`data/claims/2026-04.r9a4-replay.json`) 또는 `--target-suffix` flag.
- 운영 사이클 진입 후 (R9-A.6) 부터 정상 path 로 통합.

## 7. LLM 호출 조건

| 조건 | 동작 |
|---|---|
| 해당 period 의 canonical 이미 존재 + force flag 없음 | LLM 호출 0 (skip) |
| 신규 period | Haiku 1 call, max_tokens 16384 (R9-A.1 와 동일) |
| `--dry-run` flag | LLM 호출 0, prompt 빌드만 + log |
| `--force-claim-extract` | force-promote 와 동일하게 기존 무시하고 재실행 (admin 전용) |
| API key 부재 / quota 초과 | warning + skip (Step 2.7 실패해도 daily_update 전체 계속, §8) |

### 비용 cap
- 단일 호출 > **$0.5** → abort (defensive)
- 월 누적 > **$1.0** → warning + skip (hard cap)

## 8. Failure handling

### 결정값 (사용자 6.6)
**모든 실패는 warning만 남기고 daily_update 전체 계속 진행**.

| 실패 유형 | 동작 |
|---|---|
| LLM API 실패 (rate limit, network) | warning ledger row + skip (다음 daily_update 에서 재시도) |
| LLM 응답 파싱 실패 (invalid JSON) | warning + raw response 별도 dump (gitignored) + skip |
| extracted claim 0건 | warning + skip (extraction quality 이슈로 별 트랙) |
| validate_claim 실패 (1건이라도 invalid) | invalid 분리 dump + valid 만 promote 진행 |
| promotion out-of-band (band [30%, 70%] 위반) | R9-A.2 의 `_check_band_or_abort` 와 동일 — abort 또는 `--allow-out-of-band` |
| canonical save 실패 (path 충돌) | abort + 기존 file md5 hash 비교 + 사용자 보고 |

read-side (debate / fund_comment) 는 `select_promoted_claims_for_period` 의 graceful 동작 (이미 구현) 으로 store 부재 시 빈 list 반환 → 보고서 build 영향 0.

## 9. Smoke plan (R9-A.6 까지 3 단계)

### 9.1 LLM 0 dry-run (구현 후 1차 — 사용자 별도 GO)
- 명령: `python -m market_research.pipeline.daily_update 2026-05 --dry-run-claim`
- 검증:
  - daily_update Step 순서 진입 확인 (Step 2.6 → 2.7 → 3)
  - LLM 호출 0
  - canonical store / 08_Claims / ledger 변경 0
  - prompt 빌드 + 길이만 log
- 예상 결과: prompt 빌드 결과 stdout, write 0

### 9.2 LLM 1회 single period replay (2차 — 사용자 별도 GO)
- 명령: `python -m market_research.pipeline.daily_update 2026-05 --force-claim-extract --target-suffix=r9a4-replay`
- 검증:
  - LLM 1 call (~$0.05)
  - `data/claims/2026-05.r9a4-replay.json` 신규 생성 (suffix 분리)
  - `_promotion_quality.jsonl` 별도 ledger row append
  - 08_Claims 신규 page (replay 표시 가능 — `_market.replay` prefix 등 검토)
  - 기존 `data/claims/2026-04.json` md5 동일 (변경 0)
- 예상 결과: claim count 신규 period (가변), promoted count A3 적용 후 30~70% band 내

### 9.3 운영 사이클 1회 smoke = R9-A.6 (3차 — 사용자 별도 GO)
- 명령: `python -m market_research.pipeline.daily_update` (정상 운영 path, suffix 0)
- 검증:
  - daily_update 전체 정상 종료
  - claim extractor 단계 LLM 1 call
  - canonical store 정상 path 로 생성/merge
  - read-side chain 자동 활성화 — 신규 period 의 fund_comment 가 `[claim:X]` 인용
  - 비용 < $1/월

## 10. Rollback plan

### 즉시 rollback (R9-A.4 진입 직후)
- target hash: `81537b0` (Review Packet commit) 또는 `6c2df90` (UI 직후)
- `git revert <r9a.4_commits>` — daily_update.py + 신규 모듈 모두 reset
- canonical store / 08_Claims smoke 산출물은 별도 cleanup (gitignored 라 파일 삭제)

### 운영 사이클 진입 후 rollback
- daily_update Step 2.7 호출 위치만 `if False:` guard 로 즉시 비활성화
- 코드는 보존, 추출만 정지
- 기존 canonical store 보존 (delete 0)

### Rollback 검증
- `_market.final.json` md5 / `data/claims/2026-04.json` md5 변경 0 확인
- read-side chain 은 R9-A.4 무관하게 작동 (graceful)

## 11. 테스트 계획

### LLM 0 unit tests (필수, 구현과 함께)
| 테스트 | 검증 |
|---|---|
| `_step_claim_extract` 가 daily_update step 순서 진입 | dry-run path |
| frequency control (monthly already-exists skip) | 동일 month 두 번 실행 시 LLM 1회만 |
| failure handling (LLM mock 실패) | warning 만, daily_update 계속 |
| merge policy (prefer_higher_confidence) | 기존 store 보존 + 신규 append |
| out-of-band guard (R9-A.2 재사용) | promotion rate band 외시 abort |
| invalid claim 분리 dump | invalid 1건 + valid 21건 시 valid 만 save |
| API key 부재 graceful | env 미설정 시 skip + warning |
| `--target-suffix` 분리 | 정상 path 와 replay path 동시 존재 가능 |
| canonical save validate-then-save | invalid 입력 시 ValueError, partial save 0 |

### Integration smoke (LLM 1회, 별 트랙)
- 9.2 single period replay (사용자 GO)

### 회귀 보호
- `market_research/tests` 전체 374 PASS 유지
- `claim_pages` 21 PASS / `claim_store` 8 PASS / R9-A.5 18 PASS / R9-A.3.x 19 PASS 모두 유지

## 12. 구현 commit split 제안

### Commit 1 — `_step_claim_extract` 본체 + frequency control
- `market_research/pipeline/daily_update.py` (+30~50 LOC, Step 2.7 진입점)
- `market_research/pipeline/claim_extract_step.py` (NEW, 핵심 로직)
- frequency check: `data/claims/{period}.json` 존재 + saved_at 비교
- LLM 0 path 우선 (mock 가능)

### Commit 2 — Haiku prompt + 실 LLM 호출
- `market_research/analyze/claim_extractor_runner.py` (NEW)
- prompt template (R9-A.1 manual pilot 동일)
- `_call_llm` 호출 + invalid 분리 + cost tracking

### Commit 3 — failure handling + warning ledger row
- 각 실패 케이스 분리 ledger row schema
- daily_update 전체 영향 0 보장

### Commit 4 — `--dry-run-claim` / `--force-claim-extract` / `--target-suffix` CLI flag
- `daily_update.py` argparse 확장
- 9.1 dry-run 검증 가능

### Commit 5 — 테스트 (`test_claim_extract_step.py`)
- 9.1~9.2 smoke 전 LLM 0 unit test 전부

(각 commit 사용자 검토 게이트. 최소 5 commit 으로 분리 — bisect 용이성 확보)

---

## 13. Decisions (Fixed) — 사용자 확정

| # | 항목 | Decision (Fixed) | 사유 |
|---|---|---|---|
| **D-1** | Step 2.7 frequency 마커 위치 | **A — `data/claims/{period}.json::saved_at` 사용** | 단순 / 별도 lockfile 관리 부담 0 |
| **D-2** | `--target-suffix` flag 의미 | **A — `{period}.{suffix}.json` 분리 file** | replay / smoke 산출물을 운영 canonical 과 물리 분리 |
| **D-3** | invalid claim raw response dump 위치 | **B — `debug/claims/{period}.invalid.{ts}.json` (gitignored)** | invalid raw 는 디버그 로그 성격, 재현성 산출물 X |
| **D-4** | 비용 cap 위반 시 동작 | **A — abort + warning ledger row** | 월 1회 batch 에서 throttle 보다 명시적 abort 가 안전 / 추적 가능 |
| **D-5** | claim_extractor_prompt 위치 | **A — `market_research/analyze/claim_extractor_prompt.py` 신규** | manual pilot 코드와 운영 batch prompt 분리 / version 관리 용이 |
| **D-6** | promotion 통과 0건 시 동작 | **A — wiki 0 page 생성 + warning** | promoted 0 건은 시장 이벤트 부재 / threshold 결과 가능. daily_update 전체 중단 금지 |
| **D-7** | `--allow-out-of-band` flag | **A — admin 전용 노출 (default 미사용)** | 운영자 명시 override 가능 + 일반 batch / default 에서는 숨김 |
| **D-8** | LLM 모델 변경 가능성 | **A — Haiku 고정 (R9-A.1 와 동일)** | R9-A.4 초기 운영 안정화 전까지 extractor_version + 비용 / 품질 고정 |

### Future options (R9-A.4 close 후 별 트랙 결정)

- D-1 후행: lockfile 도입 (운영 환경에서 race 발생 시)
- D-3 후행: invalid raw 의 운영 가시성 향상 필요 시 별도 trace endpoint
- D-4 후행: throttle 모드 (다중 period batch 도입 시)
- D-8 후행: `extractor_version` 동적 — Sonnet/Opus 비교 검증 단계에서

## 14. 결정값 요약 (전체 fix 완료)

### Review Packet §6 (사용자 사전 fix)
- (6.1) Step 2.7 위치 ✓
- (6.2) monthly 주기 ✓
- (6.3) source / version 분리 (`daily_update_r9a4` / `r9a.4-haiku`) ✓
- (6.4) A3 threshold 유지 ✓
- (6.5) prefer_higher_confidence merge ✓
- (6.6) failure 시 graceful 계속 ✓
- (6.7) ledger gitignore ✓
- (6.8) period sync (monthly only) ✓

### Mini-spec §13 (D-1 ~ D-8 사용자 확정)
- D-1 saved_at 마커 ✓
- D-2 suffix 분리 file ✓
- D-3 debug/claims 디버그 dump ✓
- D-4 cap 위반 abort ✓
- D-5 prompt 신규 모듈 ✓
- D-6 통과 0건 graceful ✓
- D-7 admin override flag ✓
- D-8 Haiku 고정 ✓

**모든 결정값 fix 완료** — mini-spec 단계 종료. 다음은 코드 commit 1 진입.

---

## 15. 추정 비용 (R9-A.4 진입 후)

| 단계 | 비용 |
|---|---|
| 9.1 dry-run | $0 |
| 9.2 single period replay | ~$0.05 |
| 9.3 R9-A.6 운영 사이클 1회 | ~$0.05 |
| **R9-A.4 검증 누적** | **~$0.10** |
| 운영 정기 batch (월별) | $0.05 ~ $0.15 |
| hard cap (월) | < $1 |

R9-A.1 pilot $0.031 와 유사 — extractor 의 input/prompt 가 동일하기 때문. 운영 정기 batch 부터는 매월 1회 ≈ $0.05.

---

## 16. R9-A.4 진입 acceptance criteria

코드 commit 1~5 완료 + 9.1~9.3 smoke 통과 시 다음을 모두 충족해야 close:

- [ ] daily_update Step 2.7 진입점 확인
- [ ] LLM 호출 0 dry-run PASS (`--dry-run-claim`)
- [ ] LLM 1회 replay (suffix 분리) — claim count > 0 + promotion rate ∈ [30%, 70%]
- [ ] 운영 사이클 1회 smoke (R9-A.6) — 정상 path canonical 생성
- [ ] 기존 374 tests + 신규 unit tests 모두 PASS
- [ ] `_market.final.json` / `data/claims/2026-04.json` (R9-A.2 산출물) md5 변경 0
- [ ] read-side chain 회귀 0 — 기존 R9-A.5 fund_comment 결과 hash 동일하면 PASS
- [ ] 비용 단일 < $0.5 / 월 누적 < $1
- [ ] failure handling — LLM mock 실패 시 daily_update 전체 계속 진행 검증
- [ ] rollback plan 동작 검증 (1회)

---

## 17. 진행 단계 (모든 결정값 fix 완료 후)

| 단계 | 액션 | 상태 |
|---|---|---|
| Mini-spec D-1 ~ D-8 결정 | §13 fix | ✅ 완료 |
| Mini-spec docs commit | docs/ 1 path 만 staging | ☐ 다음 |
| **Code Commit 1** — Step 2.7 guard / skeleton | daily_update.py + claim_extract_step.py skeleton + tests, **LLM 0 / write 0** | ☐ |
| Code Commit 2 — claim_extractor_prompt + LLM 호출 | analyze/claim_extractor_prompt.py + extractor runner | ☐ |
| Code Commit 3 — failure handling + ledger row | 6 실패 유형 처리 + warning row schema | ☐ |
| Code Commit 4 — CLI flag (`--dry-run-claim` / `--force-claim-extract` / `--target-suffix` / `--allow-out-of-band`) | argparse 확장 | ☐ |
| Code Commit 5 — tests | LLM 0 unit test 9건 | ☐ |
| Smoke 9.1 — LLM 0 dry-run | 사용자 별도 GO | ☐ |
| Smoke 9.2 — LLM 1회 single period replay (suffix 분리) | 사용자 별도 GO, ~$0.05 | ☐ |
| Smoke 9.3 = R9-A.6 | 운영 사이클 1회, 사용자 별도 GO, ~$0.05 | ☐ |

본 mini-spec 자체는 docs commit 후 lock. 구현 commit 1 부터 사용자 검토 게이트 별 commit 단위 진입.
