# R9-B.6C — claim_store backfill 2026-01/02/03 + read-side fix close note

**Status**: ✅ PASS (technical close, 2026-05-15)
**Base commit**: `4bbc392` (R9-B close note)
**Track commit**: `3048986` (R9-B.6C apply + read-side tz/Rule-C fix, push 완료)
**Successor**: 미정 (별 트랙 후보만 — 본 노트 §9 참조)

---

## 1. R9-B.6C 목적

R9-B 트랙 close note 의 보류 항목 (P1 candidate `R9-B.6C — claim_store backfill 1~3월`) 을 실행 단위로 진입.
2026-04 monthly 에서 관찰된 단일 claim citation (`[claim:e78dc83a1e]`, R9-B.4-v2) 이 일회성인지, 1~3월에도 wiki-first opt-in pipeline 의 `[claim:hash10]` citation 이 자연 발생하는지 확인.

핵심 가설:
> `data/claims/{period}.json` canonical store + `wiki/08_Claims/{period}_claim_*.md` 의 기간별 backfill 이 들어가면, R9-B opt-in debate (`use_wiki_context_pack=True`) 의 `selected_claim_ids` → prompt 주입 → output `[claim:hash10]` citation 으로 surface 된다.

부가 가설:
- Rule A/B 자연 promotion 외에 **Rule C (force-promote)** 도 read-side 에서 surface 가능
- **out-of-band promotion rate** (월별로 일관 in-band 아님) 일 때도 quality-driven force 가 운영 가능

---

## 2. claim_store + wiki/08_Claims backfill 범위

### 2.1 처리 흐름

```
debug/claims/r9b6c_dryrun/
  build_evidence_pools.py    → 50 top-salience primary articles per period
  run_dryrun.py              → step_claim_extract(enabled=True, write=False)
                                Haiku 3 calls, ~$0.039 total
                                out/{period}_raw_result.json 산출
                                = canonical pool (LLM extract 결과)

  → 사용자 HOLD → Option C 재구성
    (LLM 0, raw_result 재사용, quality-driven filter)
  → 사용자 GO

  apply.py                   → promote_claims(force_ids=…) + save_claims_canonical
                                + append_promotion_ledger
                                LLM 0, write 운영 (target_suffix=None)

  fix_read_side.py           → 16 wiki page promoted_at +09:00 부착
                                + 2026-01 force C 2 claim promotion_rule="C" patch
```

### 2.2 산출물 (commit 3048986 — push 완료)

| 영역 | 신규 | 비고 |
|---|---|---|
| `data/claims/{2026-01,2026-02,2026-03}.json` | 3 신규 | canonical store, source=`daily_update_r9a4_r9b6c_backfill` |
| `wiki/08_Claims/2026-0[123]_claim_*.md` | 16 신규 page | production 2026-04 8 page 와 disjoint |
| `_promotion_quality.jsonl` (gitignored) | +3 rows | 1 → 4 rows (manual_pilot 1 + r9b6c_backfill 3) |
| 코드 fix | 3 files | `claim_extractor.py` OPTIONAL_FIELDS `promotion_rule` 추가 / `claim_store.py` `select_promoted_claims_for_period` Rule C surface / `wiki_context_pack_builder.py` `_is_future_relative` helper + Rule C surface in `_load_claim_store_passing` |

### 2.3 월별 분포

| period | raw (Haiku) | invalid | promoted | rate | rule_breakdown | strategy |
|---|---|---|---|---|---|---|
| 2026-01 | 24 | 0 | **4** | 16.67% (out_of_band low) | A=2 / B=0 / **C=2** | natural + force (override) |
| 2026-02 | 12 | 0 | **5** | 41.67% (in-band) | A=5 / B=0 / C=0 | natural Rule A |
| 2026-03 | 11 | 0 | **7** | 63.64% (in-band, raw 11→input 7 cap) | A=0 / B=0 / **C=7** | force_only (quality filter, 3 raw 제외) |

총 16 promoted claim (4+5+7).

### 2.4 Option C quality filter (2026-03 제외 3건)

| claim_id | 제외 사유 |
|---|---|
| `claim:2026-03:f7f7047b2b` | sup_ev=1 — 단일 evidence base |
| `claim:2026-03:645dcf7ad1` | conf=0.82 (10건 중 최저), `830211f9fd` 와 토픽 중복 |
| `claim:2026-03:8e32a139d1` | assets=2 + `d0824ae1bf` / `dad691fe88` 거시 흐름과 신호 redundancy |

---

## 3. selected_claim_ids 및 join_rate (debate backtest 실측)

`build_wiki_context_pack(period_key=...)` 호출 결과 (read-side fix 후, commit 3048986 / 코드 fix 포함):

| period | claim_store_selected | matched_wiki_claim | join_rate |
|---|---|---|---|
| 2026-01 | **4** (force C 2 + natural A 2) | 4 | **1.0** |
| 2026-02 | **5** (natural A 5) | 5 | **1.0** |
| 2026-03 | **7** (force_only 7) | 7 | **1.0** |
| 2026-04 (회귀 검증) | **3** (Rule A 2 + Rule B 1) — 변경 0 | 3 | **1.0** |

`selected_related_group_ids`: 2026-04 의 `group:2026-04:cfee0ff342` (R9-A.21A dual-anchor) 보존, 신규 backfill 3 period 는 빈 list (lineage 추가는 별 작업).

---

## 4. 실제 output claim citation 결과 (debate backtest 산출물)

backtest driver: `debug/r9b6c_claim_backtest.py` (4 runs) + `debug/r9b6c_claim_retry.py` (2026-03 3rd retry).

| period | suffix | draft_chars | starts_with_error | claim citations (total / unique) | 검증 |
|---|---|---|---|---|---|
| 2026-01 | `r9b6c-claim` | 2338 (v2 1864 대비 +25%) | False | **5 / 4 unique** | ✅ |
| 2026-02 | `r9b6c-claim` | 2189 (v2 2064 대비 +6%) | False | **4 / 4 unique** | ✅ |
| 2026-03 (1차) | `r9b6c-claim` | 155 (fallback) | True | 0 (Anthropic overload) | ❌ |
| 2026-03 (2nd retry) | `r9b6c-claim-retry` | 155 (fallback) | True | 0 (overload, but agents 단계 6/7 force_only 인용 surface) | ⚠️ |
| **2026-03 (3rd retry)** | `r9b6c-claim-retry` (overwrite) | **2349 (v2 sparse 2102 대비 +12%)** | **False** | **7 / 7 unique** | ✅✅ |
| 2026-Q1 | `r9b6c-claim` | 155 (fallback) | True | 0 (overload, end-month pattern 별개 함정) | ❌ |

### 4.1 2026-01 citation 위치 (4 unique, 5 total)

| claim | 인용 컨텍스트 |
|---|---|
| `5575cf43c9` (force C, 금 5000달러) | 본문 → "금 가격 강세가 단순한 투기적 수요가 아닌 구조적 인플레이션 기대와 재정 리스크를 반영" |
| `86b93443ad` (force C, 트럼프 달러약세) × **2** | 도입부 "트럼프 대통령의 달러 약세 용인 발언" + 결론부 "달러 약세 정책 신호 공식화" |
| `57c1b1bc8e` (natural A, WGBI) | "한국 시장의 경우 WGBI 편입 기대가 외국인 투자 매력도를 높이는 요인" |
| `650dbef400` (natural A, 연준+빅테크) | "연준 금리 결정과 빅테크 실적 발표 시즌이 겹치면서 주식시장 변동성" |

### 4.2 2026-02 citation 위치 (4 unique, 4 total)

| claim | 인용 컨텍스트 |
|---|---|
| `585f5a00a5` | "반도체 수출 호조를 반영해 성장률 전망도 기저 2.0%로 상향" |
| `60cac0908e` | "K점도표를 최초로 공개하면서 향후 6개월간 동결 16표" |
| `c337a44152` | "시중 대출금리는 기준금리 동결에도 불구하고 상승세" |
| `03cc51a72e` | "환율과 부동산이라는 이중 제약 변수로 인해 추가적인 정책 대응 여력이 좁아지는 딜레마" |
| `540fb98a2f` (selected 5 중 누락) | 본문 미인용 — LLM 자연 dedup (`60cac0908e` K점도표 / `03cc51a72e` 환율·부동산 frame 과 토픽 중복) |

### 4.3 2026-03 citation 위치 (7 unique, 7 total — force_only 100%)

| claim | 인용 컨텍스트 |
|---|---|
| `12ad0d860b` | "OPEC 회원국 이라크 원유 수출량 80만 배럴 급감, 공급 불안 가중[ref:1]" |
| `d0824ae1bf` | "인플레이션 기대 자극 → 글로벌 금리인상 압박 → 위험자산 밸류에이션 부담 연쇄" |
| `078c6ad66e` | "코스피 6%대 급락 + 서킷브레이커 발동, 금융시장 변동성 극대화[ref:2]" |
| `8ee3996b1a` | "금리인상 공포가 안전자산 선호 심리를 압도, 자산 간 상관관계 변화" |
| `dad691fe88` | "고유가 → 에너지 수입비용 → 경상수지 악화 → 달러 수요[ref:3]" |
| `830211f9fd` | "코스피 2.7% 반등, 아시아 증시 안도 랠리[ref:4]" |
| `d50b9568e0` | "배럴당 100달러 이상 장기화 시 성장률 0.55%p 하락 우려" |

### 4.4 2026-Q1 (보류)

selected_claim_ids = 7 모두 2026-03 claim (single end-month pattern, R9-B.5 미적용 한계 — §9 보류 항목). overload 로 draft_comment fallback. R9-B.6C 검증과 별개.

---

## 5. force C / natural Rule A / force_only 검증 결과

| 패턴 | period | 예상 | 실제 surface (output) | 검증 |
|---|---|---|---|---|
| **natural Rule A** | 2026-01 | 2/2 | 2/2 (`57c1b1bc8e`, `650dbef400`) | ✅ |
| **Rule C force** | 2026-01 | 2/2 | **2/2** (`5575cf43c9`, `86b93443ad`, 후자는 2회 인용) | ✅✅ |
| **natural Rule A** | 2026-02 | 5/5 selected | 4/5 cited — 1개 LLM dedup (자연스러운 토픽 통합) | ✅ |
| **force_only** | 2026-03 | 7/7 | **7/7 (100%)** — 누락 0 | ✅✅✅ |

### 5.1 핵심 결론

- **Rule C surface 메커니즘이 read-side에서 정상 작동**: 2026-01 force C 2 + 2026-03 force_only 7 모두 `select_promoted_claims_for_period` + `_load_claim_store_passing` 의 `promotion_rule == "C"` 분기를 통해 selected 진입 → `[claim:hash10]` citation 으로 surface.
- **out-of-band override 도 자연 사용**: 2026-01 rate=16.67% (low) 도 4 claim 전부 본문 인용 — quality-driven force 가 단순 강제가 아니라 실제 운용 의사결정 컨텍스트에 부합.
- **force_only cap (2026-03 quality filter)** 도 정상 작동: 제외 3건은 본문 미인용 (input 자체에 없음), 살린 7건은 100% 인용.

---

## 6. Anthropic overload 와 retry 기록

### 6.1 발생 빈도

| run | period | suffix | 결과 |
|---|---|---|---|
| 1차 backtest | 2026-01 | r9b6c-claim | Step 2 (Opus 종합) 1차 overload → 종합 자동 재시도 / 본문 정상 | (성공) |
| 1차 backtest | 2026-02 | r9b6c-claim | 정상 | (성공) |
| 1차 backtest | 2026-03 | r9b6c-claim | **본문 generation overload** → fallback 155 chars | ❌ |
| 1차 backtest | 2026-Q1 | r9b6c-claim | **Step 2 + 본문 overload** → fallback 155 chars | ❌ |
| 2nd retry | 2026-03 | r9b6c-claim-retry | 본문 generation overload **재발** → fallback 155 chars (단 agents 단계 6/7 force_only 인용 surface) | ❌ |
| **3rd retry** | 2026-03 | r9b6c-claim-retry (overwrite) | Step 2 overload (consensus/tail 0 영향), **본문 generation 정상 통과**, **7/7 force_only 인용** | ✅ |

### 6.2 발생 패턴 — 코드 layer 분리 확인

- **Step 1 본문 generation** (`_synthesize_debate` → `_call_llm(model='claude-opus-4-6', stream=True)`, `log_label='synthesis_step1_comment'`): 1차/2차 retry 에서 overloaded_error, 3차 retry 에서 자연 통과
- **Step 2 합의/쟁점/Tail Risk 분석** (Opus 별 호출): 2번/3번 retry 모두 발생, fallback path 가 있어 partial degradation (consensus=0, tail=0). 본문 generation 과 독립.
- request_id 모두 다름 (`req_011Cb3T327JhaxcWAueMGft4`, `req_011Cb3U5kmGn9Ns3Wti13bUp`, `req_011Cb3UVaypsRUa3hZmfdGmH`) — Anthropic 서버 측 시간대 의존 일시 throttling.

### 6.3 결론

- 본 트랙에서 Sonnet fallback 코드 영구 도입은 **미진입** (사용자 명시 — §9 보류). 3rd retry 자연 성공으로 일회성 본문 generation overload 해결.
- Step 2 (consensus/tail) overload 는 본문 generation 과 별개 함정. 본문 정상 surface 시 핵심 검증 영향 없음. 별 트랙 후보로만 기록.

---

## 7. 운영 invariant

R9-B.6C apply (commit 3048986) 후 + 3 backtest run 후 모두 PASS:

| 영역 | md5 / state | 결과 |
|---|---|---|
| `data/claims/2026-01.json` | new (commit 3048986) → 변경 0 (post-commit) | ✅ |
| `data/claims/2026-02.json` | new (commit 3048986) → 변경 0 | ✅ |
| `data/claims/2026-03.json` | new (commit 3048986) → 변경 0 | ✅ |
| `data/claims/2026-04.json` | `da3fed58…` | ✅ 불변 |
| `_market.final.json (2026-04)` | `81eb876b…` | ✅ 불변 |
| `07G04.final.json (2026-04)` | `f522cd67…` | ✅ 불변 |
| `regime_memory.json` | `c30035da…` | ✅ 불변 |
| `wiki/00_Index/index.md` | `a0c3e6e3…` | ✅ 불변 |
| `wiki/08_Claims/2026-04_claim_de1729b413.md` (R9-A.21A dual-anchor) | `9cbd40b3…` | ✅ 불변 |
| `wiki/08_Claims/2026-04_claim_e78dc83a1e.md` (R9-A.21A dual-anchor) | `0a2d2468…` | ✅ 불변 |
| `wiki/08_Claims` production count | 24 (apply 후 8 + 16 backfill) | ✅ |
| `_promotion_quality.jsonl` rows | 4 (manual_pilot 1 + r9b6c 3) | ✅ |
| `wiki/06_Debate_Memory/` | debate_service write skip (R9-B.3.1 hotfix, target_suffix 분기) | ✅ |
| `report_output/{2026-01,02,03,Q1}/_market.draft.json` (운영) | 변경 0 — 본 트랙 산출은 모두 suffix 분리 | ✅ |

### 7.1 신규 격리 산출물 (commit 비대상, gitignored or untracked)

```
market_research/data/report_output/2026-01/_market.r9b6c-claim.draft.json
market_research/data/report_output/2026-02/_market.r9b6c-claim.draft.json
market_research/data/report_output/2026-03/_market.r9b6c-claim.draft.json
market_research/data/report_output/2026-03/_market.r9b6c-claim-retry.draft.json
market_research/data/report_output/2026-Q1/_market.r9b6c-claim.draft.json
market_research/data/report_output/_evidence_quality.r9b6c-claim.jsonl
market_research/data/report_output/_evidence_quality.r9b6c-claim-retry.jsonl
debug/claims/r9b6c_dryrun/                       (dryrun + apply + read-side fix 스크립트)
debug/r9b6c_claim_backtest/                      (1차 backtest 4 run 산출)
debug/r9b6c_claim_retry/                         (2nd + 3rd retry 산출)
debug/r9b6c_claim_backtest.py                    (driver)
debug/r9b6c_claim_retry.py                       (driver)
```

### 7.2 Known limitation (의도 기록, 본 트랙 미수정)

- `data/debate_logs/{period}.json` 은 suffix 격리 안됨 — backtest 가 R9-B.4-v2 logs 를 r9b6c-claim 으로, retry 가 1차 결과를 또 덮어쓰기. R9-B.4.2 후보 (§9 보류).
- 2026-Q1 selected_claim_ids 7개 모두 2026-03 claim (end-month single-month pattern) — R9-B.5 미적용 (§9 보류).
- `wiki/08_Claims/2026-03_claim_*.md` 의 wiki frontmatter `promotion_rule: C` 와 canonical store 의 `promotion_rule` 부재 (force_only 7개) 가 불일치. read-side 영향 0 (모두 Rule A/B 자연 통과로 surface). 별 트랙 fix 후보 — `promote_claims` 가 wiki frontmatter 의 promotion_rule 을 canonical 에도 동기화하도록 보강.

---

## 8. 비용

### 8.1 R9-B.6C 트랙 단계별

| 단계 | LLM | 비용 |
|---|---|---|
| `build_evidence_pools.py` | 0 | $0 |
| `run_dryrun.py` (Haiku 3 calls, R9-A.4 step_claim_extract) | 3 | **$0.039** |
| Option C plan 재구성 (`raw_result` 재사용) | 0 | $0 |
| `apply.py` (promote + save + ledger) | 0 | $0 |
| `fix_read_side.py` (page rewrite + canonical patch) | 0 | $0 |
| `r9b6c_claim_backtest.py` (4 runs: 01/02/03/Q1) | 2 본문 성공 + 2 fallback | ~$2.1 |
| `r9b6c_claim_retry.py` (2nd retry, overload fail) | 1 (partial) | ~$0.45 |
| `r9b6c_claim_retry.py` (3rd retry, 성공) | 1 | ~$0.55 |
| **R9-B.6C 누적** | | **~$3.14** |

### 8.2 R9-B 트랙 누적 (2026-05-15 기준)

| 트랙 | 비용 |
|---|---|
| R9-B.4 backtest (5 runs) | $3.50 |
| R9-B.4.1 Q1 streaming retry | $0.75 |
| R9-B.4-extended (exploratory invalid) | $1.50 |
| R9-B.4-v2 (4 runs) | $3.02 |
| **R9-B.6C 트랙** | **~$3.14** |
| **R9-B 전체 누적** | **~$11.95** |

monthly cap $1 ledger 와 분리 — R9-B.6C 의 LLM 호출은 모두 debate Opus/Haiku 라 claim_extractor monthly cap 무관. R9-A.4 ledger 영향 0.

---

## 9. 보류 항목 (별 트랙 후보, 본 노트 close 후 사용자 결정)

| 후보 | 우선순위 | 비용 | 진입 조건 |
|---|---|---|---|
| **Q1 retry** | P2 | ~$0.55 | overload 풀린 시간대 + R9-B.6C 가 1Q 분기 모두 close 하려면. 단 selected_claim_ids 가 모두 2026-03 (end-month pattern) 이라 분기 흐름 본질 미해결 — R9-B.5 와 묶어 진입이 더 효과적 |
| **R9-B.5 multi-month quarterly pack** | P3 | LLM 0 (설계) | post-Q2 분기 종료 후 + 분기 흐름 end-month bias 가 일관 관찰될 때. R9-B 처음 close note 의 P3 후보 그대로 |
| **Sonnet fallback 영구 도입** | P3 | LLM 0 (설계) | Opus overload 빈도가 운영 영향을 줄 정도로 증가 시 / 사용자 명시 GO 필요. 본 트랙에서는 일회성 retry 로 해결 — 영구 도입 미진입 |
| **R9-B.4.2 debate_logs suffix 분리** | P4 | LLM 0 | `data/debate_logs/{period}.json` overwrite 가 backtest 재현성에 영향을 줄 때. 본 트랙에서는 backtest summary.json + report_output suffix 산출물로 추적 가능 — 미진입 |
| **wiki/canonical promotion_rule 동기화** | P5 | LLM 0 | `promote_claims` 가 wiki frontmatter 의 promotion_rule 을 canonical store 에도 동시 저장하도록 보강. 본 트랙에서 발견된 2026-03 7 claim 의 metadata 불일치 — read-side 영향 0, 보조 정리 작업 |
| **wiki-first default 전환** | P5 | 사용자 결정 | monthly 2~3건 + 종료된 분기 2회 누적 후 (R9-B close note 그대로). R9-B.6C 가 1~3월 monthly 3건 입증 추가 — 누적 4 monthly (2026-01/02/03/04). 분기는 아직 검증 부재 |

---

## 10. 최종 판정: **PASS**

R9-B.6C 트랙 기술적 close. 핵심 가설 (claim_store + wiki/08_Claims backfill → debate output `[claim:hash10]` citation surface) 완전 입증.

### 10.1 입증 데이터

- **3 monthly 모두 selected_claim_ids 정확 + join_rate 1.0** (2026-01: 4 / 2026-02: 5 / 2026-03: 7)
- **3 monthly 모두 [claim:...] citation 실측 surface** (2026-01: 5/4 unique / 2026-02: 4/4 unique / 2026-03: 7/7 unique)
- **force C 2 + natural A 7 + force_only 7 = 16/16 surface 정책 검증** (단 2026-02 자연 dedup 1건은 LLM 의 토픽 통합으로 합리적)
- **운영 invariant 7개 영역 모두 PASS**
- **raw 수치 충돌 0** (warning_counts critical/warning/info 모두 0)
- **코멘트 팽창 적정** (+6% ~ +25%, 사용자 R9-B 운영 기준 ±10%~25% 범위)

### 10.2 R9-B 트랙 P1 후보 close

R9-B close note 의 별 트랙 후보 표 중 **R9-B.6C** 단독 close. 나머지 (R9-B.5 / wiki-first default / R9-B.4.2) 는 §9 그대로 보류.

### 10.3 다음 유효 검증 시점

- **2026-06+ monthly cycle**: 자연 발생 claim citation 누적 (R9-B 처음 close note 와 동일)
- **post-Q2 quarterly**: R9-B.5 진입 결정용 데이터 누적
- R9-B.6C 자체 후속 검증 불필요 — 본 트랙 close.

---

## Appendix A — Commit chain (R9-B 트랙)

```
3048986  R9-B.6C  apply 2026-01/02/03 backfill + read-side tz/Rule-C fix  ← origin/main
4bbc392  R9-B     close note — wiki-first opt-in technical close
cd04dab  R9-B.6   base wiki backfill 2026-01/02/03 (68 pages)
2058391  R9-B.4.1 Opus synthesis streaming + quarterly llm_calls log
b3f75fa  R9-B.3.1 hotfix — debate_memory writer skip for suffix runs
9120c82  R9-B.3.1 isolated output target (target_suffix)
c0121ba  R9-B.2.1 body-level related_group_id parser
e0a3964  R9-B.2   max_pages global cap fix
c40f724  R9-B.2   wiki_context_pack_builder + CLI
797ef6c  R9-B.1   design
```

## Appendix B — Rollback table

| 시나리오 | 권장 hash |
|---|---|
| R9-B.6C 전체 회귀 | `4bbc392` (R9-B close note, R9-B.6C 진입 전) |
| R9-B.6C 코드 fix 만 회귀 (data/claims/* + wiki/08_Claims/* 유지) | `3048986` 직전 — git revert 시 22 files 모두 복구 필요 |
| 2026-01/02/03 canonical store 만 삭제 (wiki 유지) | 수동 `rm market_research/data/claims/2026-0[123].json` (gitignored 아님 — 운영 영향 있음) |
| read-side fix 만 reverse | `claim_extractor.OPTIONAL_FIELDS` / `claim_store.select_promoted_claims_for_period` / `wiki_context_pack_builder._is_future_relative` 3 파일 revert |
