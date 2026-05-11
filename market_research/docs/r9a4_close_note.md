# R9-A.4 Close Note — daily_update Step 2.7 claim extraction 트랙

작성일: 2026-05-11
origin/main close 직전 hash: `ab33b21`
설계 packet: `r9a_wiki_first_claim_normalization.md`
mini-spec: `r9a4_minispec.md`
선행 workorders: `r9a4_commit2_workorder.md`, `r9a4_commit3_workorder.md`, `r9a4_commit4_workorder.md`
종합 PR / commit chain: 본 close note §2

본 문서는 R9-A.4 트랙의 **기술적 close 판정** 을 정식 기록한다. 운영 wiki/
canonical/ledger 실 적용은 본 close note 시점에 **하지 않으며**, 후속 R9-A.5
/ Commit 6+ 트랙에서 prompt 보강 / merge dedup / multi-snapshot calibration
검증 후 결정한다.

---

## 1. Close 판정 요약

| 항목 | 상태 |
|---|---|
| write path 안전성 (Commit 1~4 + C4.1) | ✅ 통과 |
| Rule B calibration (Commit 5) | ✅ chain≥3 + sup_ev_count≥2 |
| 실 write 경로 회귀 (9.3 controlled write smoke) | ✅ 20/20 PASS |
| 실 Haiku drift 재현 검증 (9.3b) | ✅ REPRODUCED ($0.01655) |
| Rule B 분포 분석 (chain analysis) | ✅ chain={2:1, 3:16, 4:1}, asset≥3 = 0 |
| Calibrated replay smoke (9.4) | ✅ 26/26 PASS — `--allow-out-of-band` 없이 in-band write |
| 12 replay wiki claim 품질 sanity | ✅ KEEP 8 / REVIEW 3 / MERGE 1 / DROP 0 |
| 보호 영역 invariant (6 md5 + 08_Claims 8 + ledger 1 row + Step 2.7 default OFF) | ✅ 변경 0 |
| pytest market_research/tests 전체 | ✅ 499 PASS |
| R9-A.4 안에서 추가로 해야 할 코드 작업 | ❌ 없음 — close 가능 |

**판정: R9-A.4 기술적 close**. 운영 반영은 별 트랙으로 분리.

## 2. Commit chain (총 5+1 commit)

| commit | 설명 | LOC | 누적 PASS |
|---|---|---|---|
| `812aaa8` | Commit 1 — Step 2.7 skeleton + flag default OFF | +small | C1 PASS |
| `a0576d1` | Commit 2 — extractor prompt + Haiku runner + dry-run | — | C2 PASS |
| `ccd69b3` | Commit 3 — failure matrix + monthly cap + plan + ledger preview | +1726/-107 | 427 |
| `bcafdfd` | 9.3a sub-smoke — LLM 0 / write 0 plan smoke (18 cases) | +471 | 447 |
| `065d782` | Commit 4 — CLI flag + write gate + 실 write 분기 | +999/-31 | 469 |
| `26f0a65` | Commit 4.1 — target_suffix isolation for wiki + ledger | +438/-22 | 481 |
| `ab33b21` | Commit 5 — Rule B calibration (chain≥3 + sup_ev≥2) | +464/-13 | **499** |

부속 docs commit: `eccdaff` (C3 workorder), `54c6e64` (C4 workorder), 81537b0 (pre-A4 review packet), `db1cdf4` (mini-spec).

## 3. Acceptance — workorder 항목별 통과

mini-spec D-1~D-8 결정값:
- ✅ D-1 frequency 마커 = `data/claims/{period}.json` 의 `saved_at`
- ✅ D-2 target suffix = `{period}.{suffix}.json` 분리 file (C4.1 에서 wiki+ledger 도 확장)
- ✅ D-3 invalid raw dump = `debug/claims/` (gitignored) 만 허용
- ✅ D-4 cost cap 위반 → abort + warning (per-run + monthly)
- ✅ D-5 prompt 위치 = `analyze/claim_extractor_prompt.py`
- ✅ D-6 promotion 0건 → graceful warning, 중단 X
- ✅ D-7 `--allow-out-of-band` = admin 전용 노출 (CLI flag)
- ✅ D-8 LLM = Haiku 고정 (`claude-haiku-4-5-*`)

Commit 3 acceptance (workorder §15):
- ✅ failure matrix 10 case + 테스트
- ✅ monthly cap pre-abort
- ✅ promotion plan
- ✅ ledger row preview schema
- ✅ would_save 강화
- ✅ 9.3a smoke
- ✅ 보호 영역 변경 0
- ✅ Commit 1+2 회귀 0
- ✅ R9-A.4 Commit 4+ 선반영 0

Commit 4 acceptance (workorder §11):
- ✅ CLI flag 3+1종 + argparse 회귀 0
- ✅ write gate G-1~G-13 (C4.1 에서 G-13 missing_target_suffix 추가)
- ✅ write_block_reason 11종 매핑
- ✅ out_of_band drift monitoring fields
- ✅ Rule B threshold / prompt 본문 변경 0
- ✅ 9.3a smoke 18 회귀 0
- ✅ 신규 tests A~H PASS
- ✅ 보호 영역 변경 0
- ✅ daily_update 기본 호출 회귀 0

Commit 5 acceptance:
- ✅ Rule B chain≥3 + sup_ev_count≥2 — 9.3b 12/18 (66.67%) in-band
- ✅ 분포 분석 산출물 보존 (`debug/claims/r9a4_chain_analysis.{py,md}`)
- ✅ Rule A / prompt / acceptance band 변경 0
- ✅ ledger schema 33필드 backward compat (C3 24 / C4 32 / C4.1 33)
- ✅ 회귀 0 (기존 R9-A.2/A.3 fixture 갱신 — 의도 보존)

## 4. 보호 영역 invariant (close 시점)

| 영역 | hash / state |
|---|---|
| `regime_memory.json` md5 | `1ee7151c8c381217c7b34393b0054daf` |
| `data/claims/2026-04.json` md5 | `da3fed58512829099a624ddb5fc1c85f` |
| `_market.final.json` md5 | `81eb876ba8b82b23a2a3dcec3de2f5bc` |
| `07G04.final.json` md5 | `f522cd673c8df342c21459990e86eff1` |
| 운영 `wiki/08_Claims/*.md` count (suffix 없는 .md) | 8 |
| 운영 `_promotion_quality.jsonl` row | 1 (R9-A.1 manual_pilot 단독) |
| `daily_update.py` Step 2.7 default | OFF (`ENABLE_CLAIM_EXTRACTION=False`) |

5 commits 진행 동안 위 7개 invariant **변경 0** — write path / replay 분리 / monitoring 모두 운영 영역을 우회.

## 5. 9.3 / 9.3a / 9.3b / 9.4 smoke 산출물 (untracked, 검토용 보존)

| smoke | 산출물 | 결과 |
|---|---|---|
| 9.3a (pytest) | `test_r9a4_93a_smoke.py` (18 cases, tracked) | 18/18 PASS |
| 9.3 controlled write | `debug/claims/r9a4_93_controlled_smoke.py` + replay artifacts (r9a4-replay) | 20/20 PASS |
| 9.3b real Haiku | `debug/claims/r9a4_93b_haiku_smoke.py` + `r9a4_93b_haiku_result.json` ($0.01655) | REPRODUCED |
| chain analysis | `debug/claims/r9a4_chain_analysis.{py,md}` | 분포 분석 |
| 9.4 calibrated replay | `debug/claims/r9a4_94_c5replay_smoke.py` + replay artifacts (r9a4-c5replay) | 26/26 PASS |
| 12 claim quality review | `debug/claims/r9a4_94_quality_review.md` | KEEP 8 / DROP 0 |

모든 산출물은 `debug/claims/` (gitignored) 또는 운영 영역 외 untracked 보존. 운영 영역 변경 0.

## 6. 12 replay wiki claim sanity 결과

| verdict | count | claim ids (hash10) |
|---|---|---|
| **KEEP** | **8** | 03ad985eaf, 086099523f, 4f00a27903, 59eeaac624, 83109bd954, 947d99ecc3, e065e56406, ef96729ca6 |
| REVIEW | 3 | 42b5d07299 (direction 일관성), 94fddcf622 (asset 매핑), ce3a2ce3e0 (cluster 통합 검토) |
| MERGE | 1 | af03960da2 (with 42b5d07299, evidence 100% dup) |
| DROP | 0 | — |

**운영 반영 가능 ≈ 10/12 = 83%**:
- 즉시 반영: 8 (KEEP)
- minor 수정 후 반영: 2 (42b5d direction 보강, 94fdd asset 보강)
- merge 후 반영: 1 (af03 → 42b5d 통합)

대표 좋은 claim: 83109bd954 (브렌트유 141달러, counter_evidence 까지 양질), 086099523f (삼성 슈퍼 어닝, supporting 6건), e065e56406 (이란-미국 휴전, 정량성).

상세는 `debug/claims/r9a4_94_quality_review.md`.

## 7. 누적 비용

| 단계 | 비용 |
|---|---|
| R9-A.1 manual pilot | $0.031 |
| R9-A.2 manual smoke (live write) | $0 |
| D-3-A debate 검증 | $0.34 |
| Step 3 D-X-A debate 재실행 | $0.34 |
| Step 4 fund_comment 07G04 | $0.072 |
| 9.2 stub seed (real Haiku 1회) | $0.014 |
| 9.3b real Haiku 재호출 | $0.01655 |
| **R9-A 누적** | **~$0.83** |
| Commit 1~5 + C4.1 + smoke 코드 작업 | $0 (코드 LLM 0) |
| 운영 default 월 추정 | $0.05 ~ $0.15 |
| hard cap | < $1/월 ✓ |

## 8. 후속 트랙 (R9-A.5 / Commit 6+ 후보)

### 8.1 1순위 — prompt 보강 (`affected_assets ≥ 3` 유도)

근거 (12 claim sanity 분석):
- 12/12 모두 `affected_assets ≤ 2` → Rule A 영원히 0건 (dead code)
- promotion 이 Rule B 에 100% 의존 — 단일 rule 의존성 위험
- claim 별 분석: 여러 자산군 영향이 명백한데 Haiku 가 1~2개로 conservative 한 경우 존재
  (예: 86099523f 코스피 vs 반도체 산업 → 국내주식 단일로만 매핑)

작업:
- `analyze/claim_extractor_prompt.py` 의 SYSTEM_PROMPT 또는 user_prompt 추출 규칙에 한 줄 추가:
  *"여러 자산군에 의미 있는 영향이 있으면 affected_assets 에 3개 이상 명시할 것"*
- 9.5 sub-smoke 로 Haiku 재호출 1회 ($0.014~$0.016)
- Rule A 활성화율 측정 (목표 ≥ 30%)

비용: $0.014~0.016 (1회 LLM)

### 8.2 2순위 — claim merge/dedup 자동화

근거:
- af03960da2 ↔ 42b5d07299 supporting_evidence 100% 동일 (Fed 정책+고용 동일 cluster)
- 향후 운영에서 동일 패턴 자동 탐지 + 통합 후보 surface 필요

작업:
- `pipeline/claim_promotion_plan.py` 에 evidence-overlap detection (Jaccard similarity > 0.8 등 임계)
- merge 후보를 plan 의 새 키 `merge_candidates` 로 surface (실 merge 는 admin)

비용: LLM 0 (deterministic)

### 8.3 3순위 — multi-snapshot calibration

근거 (9.2 vs 9.3b variance):
- 9.2 (5/8): chain={2:14, 3:4} → 새 Rule B 적용 1/18 (5.6%, low oob)
- 9.3b (5/11): chain={2:1, 3:16, 4:1} → 12/18 (66.67%, in-band)
- 단일 호출 분포 기반 임계의 fragility 노출

작업:
- N=3 회 Haiku 호출 → 분포 평균 + 임계 재calibrate
- 또는 `ACCEPTANCE_BAND` 확장 (예: [25%, 75%]) 으로 variance tolerance

비용: N × $0.016

### 8.4 4순위 — R9-A.6 운영 사이클 1회 smoke

근거:
- daily_update 풀 파이프라인 (Step 0~5 + 2.7) 1회 실 호출로 회귀 검증
- Step 2.7 default OFF 회귀
- 운영 monitoring 시작점

작업:
- `python -m market_research.pipeline.daily_update <date>` (flag 없이)
- Step 2.7 skip 확인 + 다른 step 정상 동작 확인
- 별도 commit 없이 운영 cycle log 만 기록

비용: 풀 파이프라인 LLM (~$0.10 추정, 분류+GraphRAG+regime 포함)

## 9. R9-A.4 에서 의도적으로 하지 않은 작업 (out of scope)

- ❌ Rule A 임계 완화 또는 변경 (Haiku conservative tagging 의 dead code 문제는 prompt 측 해결)
- ❌ prompt 본문 수정 (Commit 6 후보로 분리)
- ❌ ACCEPTANCE_BAND 조정
- ❌ daily_update default ON 전환 (R9-A.6 끝까지 OFF)
- ❌ 운영 `data/claims/2026-04.json` 으로 9.3b/9.4 결과 승급
- ❌ 운영 `wiki/08_Claims/` 에 r9a4-c5replay 12 claim 정식 promote
- ❌ R9-A.1 manual_pilot 22 claim 와 R9-A.4 12 claim 의 cross-period merge
- ❌ Option B (ReportFinalView client viewer 노출)

위 항목들은 R9-A.5 / Commit 6+ 또는 별 트랙에서 사용자 GO 별로 진입.

## 10. Rollback 후보

| 시나리오 | 권장 hash |
|---|---|
| Commit 5 회귀 → C4.1 보존 | `26f0a65` |
| Commit 4.1 회귀 → C4 보존 | `065d782` |
| Commit 4 회귀 → C3 보존 | `ccd69b3` |
| 9.3a 만 회귀 → C3 직후 | `ccd69b3` |
| Commit 3 회귀 → C2 보존 | `a0576d1` |
| R9-A.4 트랙 전체 회귀 | `6c2df90` (R9-A.5-UI 직후) |
| canonical store 의심 시 | `5a3ed46` (R9-A.2 manual smoke) |

## 11. 다음 신호 옵션 (사용자 결정)

| 신호 | 액션 |
|---|---|
| **"R9-A.5 / Commit 6 진입 — prompt 보강"** (1순위) | `affected_assets ≥ 3` 유도 + 9.5 sub-smoke ($0.016) |
| "R9-A.5 / Commit 6 진입 — claim merge/dedup 먼저" (2순위) | LLM 0, evidence-overlap detection 자동화 |
| "Commit 6+ — multi-snapshot calibration" | Haiku variance 강건성 ($0.048 = 3 × $0.016) |
| "R9-A.6 운영 사이클 1회 smoke 먼저" | daily_update 풀 회귀 검증 |
| "운영 wiki 8 KEEP claim 직접 promote" | 9.4 replay 8 claim → 운영 `08_Claims/` 정식 반영 (별 트랙) |
| "R9-A.4 close 만 기록, 후속 보류" | 현 상태로 동결 |

## 12. 결론

R9-A.4 트랙은 **5 commit + 4 smoke + 12 claim sanity** 까지 모두 통과해 **기술적 close**.

운영 default 영향 0 / 보호 영역 변경 0 / pytest 499 PASS / LLM 누적 ~$0.83.

후속 트랙 1순위는 **prompt 보강 (affected_assets ≥ 3 유도)** — Rule A dead code 문제 해결로 promotion 이 Rule B 단독 의존에서 벗어남.
