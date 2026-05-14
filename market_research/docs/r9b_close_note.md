# R9-B Close Note — Wiki-first Debate Input + Opt-in Injection

**Status**: 트랙 구조 PASS. wiki-first default 전환은 아직 보류.
**Closed at**: 2026-05-15
**Closing commit**: TBD (close note 자체)
**Origin/main at close**: `cd04dab` (R9-B.6 base wiki backfill 직후)

본 문서는 R9-B 트랙의 기술적 close 기록. 구현/배포는 모두 완료, 추가 코드 변경은 별 트랙 (R9-B.5 / R9-B.6C / R9-B.4.2) 후보로만 남김.

---

## 1. 최종 결론 (사용자 명시 8 항목)

1. **R9-B 구조 구현은 PASS** — opt-in injection / target_suffix isolation / streaming hotfix / base wiki backfill 모든 단계 commit + 운영 검증 완료.
2. **2026-04 에서 claim citation positive signal 확인** — `[claim:e78dc83a1e]` 가 LLM 의 customer_comment 에 자연 등장. operational LLM output 에서 canonical claim citation 이 발생한 첫 사례.
3. **2026-01~03 은 base wiki backfill 후 event/entity/asset 효과 확인** — R9-B.6 commit `cd04dab` 으로 wiki_pages_selected 2~3 → 12 로 증가. backtest 재실행 (R9-B.4-v2) 에서 entity wiki 자연 등장 (Fed/FOMC/통화정책/유가/중동/이란 등) + 정량 detail 강화 (DXY, S&P GSCI 에너지, 이라크 원유 출하 등).
4. **수치 충돌과 장황화는 관찰되지 않음** — 4 sample 전부 numeric_guard warning 0, 코멘트 길이 변화 ±10% 이내 (2026-01 -2.6%, 2026-02 +8.6%, 2026-03 -4.7%, 2026-Q1 +1.4%).
5. **wiki-first default 전환은 아직 보류** — claim citation 은 1~3월 모두 0 (claim_store 부재). monthly 표본 6개 중 강한 positive 1건 (2026-04). 추가 표본 누적 후 결정.
6. **claim_store coverage 확대는 별도 후보** — R9-B.6C 로 분리. R9-A.1 manual pilot 1~3월 재실행 (~$0.10/월 = ~$0.30 예상).
7. **multi-month quarterly pack 은 아직 보류** — R9-B.5 진입 조건은 종료된 다른 분기 (Q2 등) 에서 동일 sparse → full pack 비교 시 분기 흐름이 end_month 에 과도하게 치우치는 패턴이 일관 재현될 때.
8. **다음 유효 검증은 2026-05 월말 이후 monthly / Q2 종료 이후 quarterly** — 월중 / 분기 진행중 sample 은 exploratory invalid (R9-B.4-extended 2026-05/Q2 결과 판단 근거 제외 원칙 유지).

---

## 2. Commit Chain (origin/main 기준)

| Commit | 단계 | 한 줄 설명 |
|---|---|---|
| `797ef6c` | R9-B.1 | wiki-first debate input architecture design review (558 LOC docs) |
| `c40f724` | R9-B.2 | wiki_context_pack_builder (read-only, debug-only) + CLI |
| `e0a3964` | R9-B.2 fix | max_pages as global cap (not per-dir) |
| `c0121ba` | R9-B.2.1 | parse body-level `related_group_id` in 08_Claims |
| `b2dffe2` | R9-B.3 | wiki context pack debate prompt opt-in injection |
| `9120c82` | R9-B.3.1 | isolated output target (`target_suffix`) |
| `b3f75fa` | R9-B.3.1 hotfix | skip debate memory wiki write for target-suffix runs |
| `2058391` | R9-B.4.1 | opus synthesis streaming + quarterly llm_calls log |
| `cd04dab` | R9-B.6 | base wiki backfill 2026-01/02/03 (68 wiki pages) |
| (TBD) | R9-B close | 본 close note |

(R9-B.4 / R9-B.4-extended / R9-B.4-v2 는 backtest 실행만, commit 산출물 없음 — 운영 분리)

---

## 3. Track 단계별 핵심 산출

### R9-B.1 — Design
- 558 LOC 설계 문서 (`r9b_wiki_first_debate_architecture.md`)
- 22 sections: 3-layer separation / D1~D7 결정 / 9 wiki dir × page_type frontmatter contract / wiki_context_pack schema / B2~B7 migration plan / R1~R11 risks / 4 acceptance metrics

### R9-B.2 — Builder
- `build_wiki_context_pack(period_key, stage, fund_code, max_pages, ...)` (Python public API)
- CLI `python -m market_research.tools.build_wiki_context_pack --period 2026-04 --stage market_debate`
- stage policy: market_debate / fund_comment / quarterly_debate / admin_preview
- date-window aware (monthly default, frontmatter 우선, filename YYYY-MM fallback)
- claim_store ↔ 08_Claims join (local Rule A/B)
- global `max_pages` cap + priority reservation + round-robin
- Dry-run on real 2026-04: considered=63, selected=12, claim_store_to_wiki_join_rate=1.0, cutoff_violations=0
- Tests: 23 (test_wiki_context_pack_builder.py)

### R9-B.2.1 — Body parser hotfix
- R9-A.21A dual-anchor lineage convention: `## Related Stable Lineage` 블록의 `- related_group_id: group:YYYY-MM:hash10` 파싱 (frontmatter fallback)
- 2026-04 backtest 시 `group:2026-04:cfee0ff342` surface 복구
- Tests: +10 (33 total)

### R9-B.3 — Debate prompt opt-in injection
- `run_market_debate(..., use_wiki_context_pack=False, wiki_context_pack=None, wiki_context_max_pages=12)` keyword-only
- Default OFF — legacy raw-source-first behavior byte-identical
- Opt-in 시 prompt 구조: `## A. Wiki Primary Context` (sub-section A.0 fund / A.1 claims / A.2 graph / A.3 regime / A.4 events / A.5 entities / A.6 assets + 위계 안내 note) → `## B. Raw Validation / Fallback Context`
- Raw blocks 그대로 (제거 0, 라벨만 추가)
- `_debug_trace` 신규 필드: prompt_context_mode / wiki_context_pack_enabled / wiki_pages_selected / selected_wiki_paths / wiki_source_type_counts / selected_claim_ids / selected_related_group_ids / claim_store_to_wiki_join_rate / source_cutoff_violations / wiki_primary_context_chars / raw_validation_context_chars
- CLI: `--use-wiki-context-pack` / `--wiki-context-pack-path` / `--wiki-context-max-pages`
- Preview tool: `python -m market_research.tools.preview_debate_prompt` (LLM-free dry-run)
- Tests: 22

### R9-B.3.1 — Isolated output target
- `target_suffix: str | None = None` opt-in 도입 (8 IO 함수 + 5 catalog helpers + evidence ledger)
- Path 명명: `{period}/{fund}.{suffix}.{kind}.json` (legacy 2-dot vs suffix 3-dot 구분)
- 자동 격리: catalog list default scan 이 suffix 파일 자동 제외
- `_evidence_quality.{suffix}.jsonl` 분리
- CLI `--target-suffix`, sanitize 규칙 `[A-Za-z0-9_-]{1,40}` (dot/slash/dot-dot/leading hyphen 금지)
- Tests: 45

### R9-B.3.1 hotfix — debate_memory writer skip
- `target_suffix` 모드에서 `write_debate_memory_page` 호출 자체를 skip
- `debate_memory_write_skipped=True` + `debate_memory_write_skip_reason="target_suffix_isolated_run"` 메타데이터
- legacy `target_suffix=None` 동작 보존
- Tests: +4 (49 total)

### R9-B.4.1 — Opus synthesis streaming
- `_call_llm(..., *, stream: bool = False)` 추가 — default OFF (legacy create() 경로 byte-identical)
- stream=True 시 `messages.stream()` 사용 + 청크 누적 + final usage 로깅 (`stream` 필드 추가)
- `_synthesize_debate` Step 1/2 양쪽 Opus call 에 `stream=True`
- Quarterly log schema 통일 — `run_quarterly_debate` 도 `log_payload = {'debated_at', 'result', 'llm_calls'}` 사용
- 2026-Q1 backtest 회귀 해결 (이전 171-char "Streaming required" 에러 → 2843 chars 정상, 152.6s)
- Tests: 9

### R9-B.6 — Base wiki backfill 2026-01/02/03
- 68 신규 wiki pages: 01_Events 15 / 02_Entities 35 / 03_Assets 18
- `refresh_base_pages_after_refine(month_str)` 단순 재호출 (full daily_update 미실행)
- 입력: 기존 `data/news/{month}.json` (refined) + `data/insight_graph/{month}.json` (snapshot, 재계산 0)
- 04_Funds 생략 (`--no-funds`, market_debate stage 무관)
- 00_Index/index.md 백업+복원 (md5 동일)
- 운영 invariant 5 md5 + 4 protected dirs 보존
- LLM 0 / GraphRAG 0 / regime mutation 0

---

## 4. Backtest Sample Aggregate

### R9-B.4 1차 (sparse pack)

| period | wiki_pages | claim_cite | comment_chars | starts_with_error |
|---|---|---|---|---|
| 2026-01 monthly | 2 | 0 | 1913 | False |
| 2026-02 monthly | 3 | 0 | 1901 | False |
| 2026-03 monthly | 3 | 0 | 2205 | False |
| **2026-04 monthly** | **12** | **`[claim:e78dc83a1e]` 1건** | 2200 | False |
| 2026-Q1 quarterly (R9-B.4.1 retry 후) | 3 | 0 | 2843 | False |

cost: ~$4.25 (R9-B.4 backtest $3.50 + Q1 streaming retry $0.75)

### R9-B.4-extended (exploratory invalid — 표본 제외)

| period | 사유 |
|---|---|
| 2026-05 monthly | 월중 (today=2026-05-15) — 월 종료 후 재실행 필요 |
| 2026-Q2 quarterly | 분기 미종료 (Q2 종료 = 2026-06-30) |

cost: $1.50 (판정 근거에서 제외)

### R9-B.4-v2 (backfill 후 sparse vs full base wiki 비교)

| period | wiki_pages | sparse chars | v2 chars | Δ | refs | wiki_entity_mentions | warning_counts |
|---|---|---|---|---|---|---|---|
| 2026-01 | 2 → **12** | 1913 | 1864 | -2.6% | 13 → 14 | 6 → 7 | all 0 |
| 2026-02 | 3 → **12** | 1901 | 2064 | +8.6% | 11 → 10 | 7 → 7 | all 0 |
| 2026-03 | 3 → **12** | 2205 | 2102 | -4.7% | 12 → 11 | 9 → 8 | all 0 |
| 2026-Q1 | 3 → **12** | 2843 | 2883 | +1.4% | 14 → 16 | 9 → 8 | all 0 |

cost: ~$3.02

### Cumulative LLM Cost (R9-B 트랙 전체)

- R9-B.4 1차 monthly+Q1: $3.50
- R9-B.4.1 Q1 retry: $0.75
- R9-B.4-extended (invalid): $1.50
- R9-B.4-v2 backfill 후: $3.02
- **누적 ≈ $8.77**

---

## 5. Acceptance Criteria 검증 (R9-B.1 design 기준)

| Criterion | Target | Achieved |
|---|---|---|
| opt-in default 보존 | legacy behavior byte-identical | ✅ (R9-B.3 stream=False default + R9-B.3.1 target_suffix=None default + R9-B.4.1 stream=False default) |
| 운영 wiki / regime / claims / report_output 변경 0 | 0 | ✅ (모든 단계 후 5 md5 + 4 dir count 보존) |
| LLM call (구조 변경 외) | trace + backtest 만 | ✅ (구조 변경 commit 자체는 LLM 0) |
| claim citation surface | operational LLM output 에서 1건 이상 자연 발생 | ✅ (`[claim:e78dc83a1e]` 2026-04 monthly) |
| source_cutoff_violations | 0 | ✅ (모든 backtest run) |
| wiki_pages_selected | ≥ max_pages threshold (12) | ✅ (backfill 후 4 sample 모두 12) |
| numeric guard regression | 0 critical | ✅ (R9-B.4-v2 4 run 모두 critical=0) |

---

## 6. Protected Region Invariants (최종)

| 영역 | md5 / state |
|---|---|
| `data/regime_memory.json` | `c30035da36e326a0412260496c94e9db` (pre-existing baseline, R9-B 트랙 무변경) |
| `data/claims/2026-04.json` | `da3fed58512829099a624ddb5fc1c85f` |
| `data/report_output/2026-04/_market.final.json` | `81eb876ba8b82b23a2a3dcec3de2f5bc` |
| `data/report_output/2026-04/07G04.final.json` | `f522cd673c8df342c21459990e86eff1` |
| `wiki/00_Index/index.md` | `a0c3e6e39cc93197fff458a1ac718452` (R9-B.6 backup+복원 후 동일) |
| `wiki/05_Regime_Canonical/` 파일 수 | 2 |
| `wiki/06_Debate_Memory/` 파일 수 | 15 (skip guard 정상 작동, 모든 backtest 후 무증가) |
| `wiki/07_Graph_Evidence/` 파일 수 | 5 |
| `wiki/08_Claims/` production count | 8 (R9-A.21A lineage de1729b413 + e78dc83a1e 보존) |
| `data/claims/_promotion_quality.jsonl` rows | 1 |
| `data/report_output/_evidence_quality.jsonl` (운영) | rows 추가 0 |

**Suffix output** (모두 gitignored / 운영 catalog 미진입):
- `report_output/**/*.r9b4-backtest.*.json` (R9-B.4 1차 산출물 5 files)
- `report_output/**/*.r9b4-extended.*.json` (exploratory invalid, 2 files)
- `report_output/**/*.r9b4-v2.*.json` (R9-B.4-v2 산출물 4 files)
- `_evidence_quality.r9b4-{backtest,extended,v2}.jsonl` (3 ledger files)
- `debug/r9b4_*` / `debug/r9b6_wiki_backfill/` / `debug/r9b4_v2/` (debug artifacts)

---

## 7. Out-of-scope Follow-ups (별 트랙 후보)

| 후보 | 우선순위 | 비용 | 진입 조건 |
|---|---|---|---|
| **R9-B.6C** — claim_store backfill 1~3월 (R9-A.1 pilot 재실행) | P1 | ~$0.30 (~$0.10/월 × 3) | 사용자 GO. 진입 시 R9-B.4-v2 의 claim citation 0 한계 해소 가능. |
| **R9-B.5** — multi-month quarterly pack | P3 | 설계+구현 LLM 0 | 종료된 분기 (Q2 / Q3) backtest 에서 end-month 치우침이 일관 관찰될 때만. 현 데이터로 결정 불가. |
| **R9-B.4.2** — `data/debate_logs/{period}.json` target_suffix 분리 | P4 | LLM 0 | 운영 영향 0 (다운스트림 미사용). suffix run 의 cost trail 보존 필요 시. |
| **wiki-first default 전환** | P5 | 사용자 결정 | 추가 monthly 표본 2~3건 + 종료된 분기 2회 누적 후 결정. |

본 close note 시점에서 **위 후보 모두 미진입**. 사용자 GO 후 별 commit.

---

## 8. Multi-period Validation Plan (다음 유효 표본 누적 절차)

| 시점 | 대상 | 비용 추정 |
|---|---|---|
| 2026-06-01 이후 | 2026-05 monthly 재실행 (target_suffix=r9b4-vN) | ~$0.75 |
| 2026-07-01 이후 | 2026-06 monthly + 2026-Q2 quarterly | ~$1.50 |
| 2026-Q3 이후 | 2026-Q3 quarterly (R9-B.5 보류 후 multi-month 판단) | ~$0.75 |

각 진입 전: pre-LLM preview + operational md5 baseline. 진입 후: legacy approved final 과 비교 + R9-B 이전 sparse 결과와 비교.

---

## 9. Rollback Reference

| 시나리오 | 권장 hash |
|---|---|
| R9-B.6 wiki backfill 회귀 (68 wiki pages 제거) | `2058391` (R9-B.4.1 직후) |
| R9-B.4.1 streaming 회귀 | `b3f75fa` (R9-B.3.1 hotfix 직후) |
| R9-B.3.1 isolated output 회귀 | `b2dffe2` (R9-B.3 직후) |
| R9-B.3 opt-in injection 회귀 | `c0121ba` (R9-B.2.1 직후) |
| R9-B.2.1 body parser 회귀 | `e0a3964` (R9-B.2 fix 직후) |
| R9-B 트랙 전체 회귀 | `57dc052` (R9-B 진입 직전, R9-A.22 close note + dashboard launcher 직후) |

각 hash 에서 `git revert <hash>` 또는 `git reset --hard <hash>` 가능. 운영 wiki / claims / report_output / regime_memory 는 R9-B 트랙 무변경이므로 rollback 영향 없음.

---

## 10. 관련 문서

- `market_research/docs/r9b_wiki_first_debate_architecture.md` — R9-B.1 design (558 LOC)
- `market_research/docs/r9a4_close_note.md` — R9-A.4 close note (R9-B 트랙 직전 단계 기록)
- `market_research/docs/r9a_claim_identity_and_monitoring_close_note.md` — R9-A.22 close note (R9-A 전체 close, R9-B 트랙의 claim 인용 layer 기반)

---

## 11. 최종 상태

R9-B 트랙은 본 close note 로 **기술적 close**. 추가 측정/구현은 사용자 GO 시 별 트랙으로만 진입. wiki-first default 전환 결정은 sample 누적 후 사용자 판단.
