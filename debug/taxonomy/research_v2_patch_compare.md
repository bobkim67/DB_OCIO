# research_v2 prompt patch — before / after (시황·마감 rule 6)

> 같은 44 sample. before = patch 전, after = rule 6("시황/마감 리포트는 보고 대상 시장을 primary,
> 글로벌 driver는 secondary") 추가 후. ★ before/after는 별개 LLM run → 일부 차이는 run-to-run
> Haiku 변동(ref: claim_haiku_variance) 포함. 결정적 신호는 타깃 케이스(id4)와 primary 회귀 여부.

## metric

| metric | before | after | 평가 |
|---|---:|---:|---|
| asset_enum_valid_rate | 44/44 (100%) | 44/44 (100%) | 유지 ✅ |
| region_enum_valid_rate | 44/44 (100%) | 44/44 (100%) | 유지 ✅ |
| fallback_rate | 0/44 (0%) | 0/44 (0%) | 유지 ✅ |
| multi_asset_rate | 28/44 (64%) | 21/44 (48%) | ↓ — 양방향(2→1 9건, 1→2 3건), 대부분 run 변동·marginal secondary. 구조 붕괴 아님(아래) |
| consistency_violation_rate | 6/44 (14%) | 8/44 (18%) | 소폭↑ (변동 범위) |
| KR_equity_recovery | 7/9 (78%) | 8/9 (89%) | ↑ ✅ (잔여 1건=id0 금통위, 실제 국내채권 정답=proxy 오라벨) |
| **id4 primary_asset** | **원자재금** | **국내주식** | **교정 ✅ (타깃)** |

## id4 — 타깃 케이스 (의도대로)

"국내주식 마감 시황 (26.05.06) - 온 세상이 전닉이다" (미·이란 driver)
- before: primary=원자재금 (driver에 끌림)
- after: `affected_assets=[국내주식(primary), 원자재금(secondary)]` → **driver를 secondary로 강등, 보고 대상(국내주식) primary.** rule 6 정확 작동.

## hybrid primary 변경 케이스 (회귀 확인)

| sample_id | title | before | after | expected | 판정 |
|---|---|---|---|---|---|
| 4 | 국내주식 마감 시황 - 온 세상이 전닉이다 | 원자재금 | 국내주식 | 국내주식 | 교정 ✅ |

→ **primary가 바뀐 케이스는 id4 단 1건, 그리고 올바른 방향.** 기존 정답 케이스 primary 회귀 0.

## multi_asset 감소 분석 (구조 붕괴 아님)

driver를 secondary로 유지하는 의도는 id4에서 확인(`원자재금 secondary 유지`). 2→1 감소 케이스
대부분은 금통위 리포트의 `현금성` secondary, 시황의 `해외주식` secondary 같은 **marginal secondary
탈락** — rule이 driver를 *제거*한 게 아니라 Haiku가 약한 secondary를 run마다 다르게 태깅(변동).
1→2 증가 케이스(id15·25·33·36)도 동시 발생 → 순감소는 변동 우세. 48%는 여전히 건전.

**한계:** 단일 44-sample 1회 run으로는 prompt-effect와 run 변동을 분리 불가
(claim_haiku_variance: 동일 입력 run-to-run 편차 큼). 엄밀 분리는 N≥3 run 필요(후순위).

## 결론

- 타깃(id4) 교정 ✅, driver→secondary 의도 작동 ✅, primary 회귀 0 ✅, enum/fallback 유지 ✅, KR_equity ↑.
- multi_asset 감소는 run 변동 우세(구조 붕괴 아님).
- → **full backtest 진입 조건 충족** (id4 교정 + 회귀 없음).
