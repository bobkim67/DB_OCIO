# R9-A read-side trace surface — Review Packet (pre R9-A.4)

생성일: 2026-05-08
대상 트랙: R9-A read-side close 직후, R9-A.4 (daily_update Step 2.7) 진입 전
작성 목적: 누적된 R9-A 변경분의 운영 안전망 정리. R9-A.4 가 정기 LLM batch
와 운영 사이클에 영향을 주기 전에 close된 chain / 금지 영역 / rollback / 위험 / 결정사항 / smoke 계획을 한 자리에 잠그기.

본 문서 자체는 설계/관측 정리물 — 코드 변경 0, LLM 호출 0, 운영 산출물 변경 0.

---

## 1. 현재 HEAD / Rollback hash

| 항목 | 값 |
|---|---|
| origin/main | `6c2df90` |
| local HEAD | `6c2df90` |
| ahead/behind | 0/0 |

### 주요 close commit chain (가장 오래된 → 최신)

| commit | 트랙 | 핵심 |
|---|---|---|
| `ce06bb6` | R9-A design packet | `docs/r9a_wiki_first_claim_normalization.md` 558 LOC |
| `0d3f9d7` | R9-A.0 | claim schema + validator + 43 tests |
| `169c102` | R9-A.1 pilot | gitignore (debug/claims/) |
| `a9dcebf` | R9-A.2 | 08_Claims dir + `_is_enrichment_page` guard |
| `0de047f` | R9-A.2 | `claim_store.py` save/load/merge + ledger |
| `6670bb6` | R9-A.2 | `claim_pages.py` writer + CLI + out-of-band guard + 20 tests |
| `ce2972d` | R9-A.2 | threshold A3 (assets≥3) |
| `5a3ed46` | R9-A.2 | manual smoke commit (canonical 22 claims + 8 wiki) |
| `bac91e6` | R9-A.3 | `select_promoted_claims_for_period` helper |
| `9bc768b` | R9-A.3 | anchor.linked_claims + debate context claims block |
| `9d105da` | R9-A.3 | fund_comment pass-through + comment_engine claim_block + evidence_trace [claim:X] |
| `7f1b290` | R9-A.3.x | require explicit [claim:hash10] citation |
| `1693870` | R9-A.5 | `validate_claim_citations` |
| `cfc42fa` | R9-A.5 | comment_trace claim surface |
| `94dbe3a` | R9-A.5 | fund draft claim_citations persistence |
| `6423c7e` | R9-A.3.x D-X-A | debate result+draft+final 'claims' wiring |
| `179cdaf` | R9-A.5.x | wiki_path preset preferred over period reconstruction |
| `6c2df90` | R9-A.5-UI Option A | Admin trace viewer 신규 카드 (현재 HEAD) |

### Rollback 기준점 후보

| 시나리오 | 권장 rollback | 사유 |
|---|---|---|
| R9-A.4 진입 후 prompt/cost 회귀 → UI까지 보존 | `6c2df90` (현 HEAD) | UI surface 까지 안전, R9-A.4 만 reset |
| R9-A.4 + UI surface 동시 회귀 → wiring chain 보존 | `179cdaf` | D-X-A wiring chain 그대로 |
| canonical store 데이터 의심 시 | `5a3ed46` | 22 claim canonical commit 직후 |
| 전체 R9-A 무효화 (드물게) | `169c102` | R9-A.1 직후 (R9-A.2~ 모두 reset) |

---

## 2. Close 된 read-side chain 요약

```
[데이터]
  R9-A.1 manual pilot (Haiku 1회, $0.031)
    → debug/claims/2026-04_r9a1_valid_claims.jsonl (gitignored, 22 claims)

  R9-A.2 promotion (LLM 0)
    → 22 claims → A3 promotion → 8 claims
    → market_research/data/claims/2026-04.json     (canonical store)
       md5 da3fed58... (R9-A.2 5a3ed46 이후 read-only)
    → market_research/data/wiki/08_Claims/*.md     (8 pages)
       mtime 1778199664~5 (5a3ed46 이후 변경 0)
    → _promotion_quality.jsonl (gitignored, 1 row)

[입력 → prompt]
  claim_store.select_promoted_claims_for_period(period, asset_class?, max_claims=8)
    → debate_engine._build_shared_context['_canonical_claims']
    → ctx['claims_text'] (max 8, 180자 truncate, [claim:hash10] anchor)
    → asset_movement_anchor.build_asset_movement_anchors(claims=...)
       → 자산군별 linked_claims attach (compact 8필드)
    → _build_agent_prompt: anchor → claims → news 순서 + _CLAIM_CITATION_INSTRUCTION
    → _synthesize_debate: comment_prompt 에도 claims_text + citation rule (R9-A.3.x)

[debate persistence] (D-X-A)
  run_market_debate result['claims'] = _compact_claims_for_persistence(8필드)
    → debate_service.run_debate_and_save preserve list 'claims'
    → save_draft → _market.draft.json 'claims' key (length 8)
    → approve_and_save_final → _market.final.json 'claims' key (compact 보존)

[fund_comment 흐름]
  market_payload (final 우선 → draft fallback) 의 'claims'
    → fund_comment_service._market_comment_to_inputs → inputs['claims']
    → comment_engine.build_report_prompt → claim_block 렌더링
    → LLM Sonnet 출력에 [claim:hash10] 인용 (Step 4 검증: 2건)

[trace surface]
  fund draft.draft_comment_raw → evidence_trace.validate_claim_citations
    → fund draft.claim_citations + claim_citation_validation 저장
  tools/comment_trace.py
    → 본문 [claim:hash10] 추출 + canonical 매핑
    → trace JSON.claim_citation_summary + section_attribution.claim_*

[API surface]
  api/services/comment_trace_gateway.py → load_trace (free-form payload)
  api/routers/admin.py → /admin/comment-trace/{list,latest,by-id}
  api/schemas/comment_trace.py → CommentTraceFullResponseDTO.payload: dict[str, Any]

[UI surface] (R9-A.5-UI Option A)
  web/src/tabs/AdminCommentTracePanel.tsx::TraceDetail
    → ClaimCitationSummaryCard / Section Attribution claims 컬럼 / LinkedClaimsCard
```

---

## 3. 검증된 end-to-end smoke 결과

| Smoke | 비용 | 결과 | commit 또는 시점 |
|---|---|---|---|
| R9-A.1 pilot | $0.031 | 50 evidence pool → 22 claims (validator 100%), 자산군 8/8 | 169c102 직전 |
| R9-A.2 manual smoke (live write) | $0 | 22 → 8 promoted (36.4%, in-band A3) / canonical + 8 wiki + 1 ledger 생성 | 5a3ed46 |
| D-3-A debate (R9-A.3.x patch 후) | $0.34 | draft 7 [claim:X] / agents 39 / matched 7/7 | (smoke artifact, 미커밋) |
| Step 3 D-X-A debate | $0.34 | _market.draft.json 'claims' length 8 보존 / draft 6 [claim:X] / matched 6/6 | (smoke artifact, 미커밋) |
| Step 4 fund_comment Option A | $0.072 | 07G04 draft 2 [claim:X] / matched 2/0 / [ref:N] 13 동시 | (smoke artifact, 미커밋) |
| R9-A.5-UI Option A 시각 검수 | $0 | 3 신규 카드 / claims 컬럼 / Linked Claims 모두 PASS | 6c2df90 |
| **R9-A 검증 누적 비용** | **~$0.78** | | |

핵심 수치 (사용자 시각 PASS 기준):
- canonical_pool_size: **8**
- total_claim_refs (07G04): **2**
- matched_count / unmatched_count: **2 / 0**
- unique_matched_claims: `e679b00e10` ("美 철강…"), `e78dc83a1e` ("중동 휴전…")
- wiki_path 정확 매핑 (08_Claims/2026-04_claim_*.md)

---

## 4. 금지 영역 (R9-A read-side close 시점 invariant)

| 영역 | 정책 | 현재 상태 |
|---|---|---|
| `daily_update.py` 트리거 | R9-A.4 진입 전까지 미수정 | 0 변경 |
| `claim extractor` 정기 batch | R9-A.4 진입 전까지 미실행 | R9-A.1 manual pilot 1회 외 0 |
| `final / approved` 운영 산출물 | smoke 모두 hash 보존 | `_market.final.json` md5 81eb876b…, `07G04.final.json` md5 f522cd67… |
| `data/claims/2026-04.json` 직접 수정 | R9-A.2 commit 5a3ed46 이후 read-only | md5 da3fed58… 동일 |
| `wiki/08_Claims/*.md` 수동 수정 | R9-A.2 manual smoke 이후 read-only | 8 file mtime 1778199664~5 동일 |
| `_promotion_quality.jsonl` append | R9-A.2 manual smoke 1회 이후 추가 X | 1 row, gitignored |
| smoke 산출물 commit | 모두 미커밋 (gitignored 또는 untracked) | `_market.draft.json`, `_evidence_quality.jsonl`, `06_Debate_Memory/2026-04__market_*.md`, `07G04.draft.json`, `debug/comment_trace/2026-04/07G04.json`, `data/debate_logs/2026-04.json` |
| weekly batch wiki (01_Events~07_Graph_Evidence) 커밋 | R9-A 외 별 트랙 | working tree 에 누적, R9-A 변경분 0 |
| `regime_memory.json` | debate 가 read-only 만 접근 | md5 1ee7151c… 동일 |

---

## 5. 운영 위험 (R9-A.4 진입 전 인지)

### 5.1 final 우선 로드 시 claim_block 부재 (운영 환경 제약)

- `fund_comment_service` 가 `load_final or load_draft` 순서 → final 우선
- 기존 `_market.final.json` (D-X-A 이전 승급분) 에는 `claims` 키 없음
- D-X-A 적용 후 새로 승급한 final 만 claims 보존
- 영향: 현재 운영 final 들 (2026 이전 분 등) 로 fund_comment 실행 시 `[claim:X]` 0건
- 완화: Option A (Step 4 처럼 draft 직접 주입) / 운영 final 재승급 / R9-A.6 운영 사이클 smoke 단계에서 결정

### 5.2 wiki_pages_selected=0 별도 지표

- `wiki_retrieval` 시스템의 page count, R9-A.5 의 claim wiki path 와 별개
- claim trace 의 wiki_path 는 정확히 채워짐 (Linked Claims 카드 검증됨)
- UI 에서 `wiki_pages_selected` 와 `Linked Claims wiki_path` 가 별개 지표라는 점 운영 인지 필요

### 5.3 Client-facing 본문의 [claim:X] 노출 정책 미정

- 현재 `sanitize_customer_comment` 는 `strip_refs` (=`[ref:N]` 만 제거)
- `strip_claim_refs` 는 함수만 존재, 적용 위치 미결정
- Admin viewer (R9-A.5-UI) 에서는 노출 OK (기존 결정)
- Client viewer (ReportFinalView, Option B 별 트랙) 결정 필요

### 5.4 R9-A.4 LLM batch 위험 (예상)

| 위험 | 완화 후보 |
|---|---|
| LLM 비용 증가 | hard cap < $1/월, dry-run 우선, monthly batch 1회 |
| 추출 품질 변동 | extractor_version 명시, R9-A.1 pilot 결과와 비교 검증 |
| 중복 생성 | claim_id deterministic + canonical store merge_claims policy |
| daily_update 실패 시 보고서 build 차단 | `select_promoted_claims_for_period` 의 graceful 동작 (이미 구현) — extractor 실패해도 read-side 영향 0 |
| canonical store overwrite 사고 | merge 정책 명시, ledger 보존, period 별 분리 |

---

## 6. R9-A.4 진입 전 결정 필요 사항 (TBD, 사용자 결정)

| # | 결정 항목 | 후보 (default 굵게) |
|---|---|---|
| 6.1 | daily_update Step 위치 | Step 2.7 (Refine 직후, 분류 결과 기반) **vs** Step 5 (regime canonical 직후) — **Step 2.7** 권장 (refine 결과의 evidence pool 활용 가능) |
| 6.2 | extractor 실행 주기 | **monthly 1회** (월말 batch) vs daily incremental |
| 6.3 | source / extractor_version 구분 | `manual_pilot_r9a1` (기존) vs **`scheduled_r9a4`** (신규) — version 명시로 ledger 추적 |
| 6.4 | promotion threshold | **A3 유지** (assets≥3, pilot 36.4%) vs 후행 재검토 |
| 6.5 | 기존 `data/claims/{period}.json` overwrite/merge | **`prefer_higher_confidence` merge** (기존 유지 + 신규 confidence 높은 것만 갱신) vs full overwrite |
| 6.6 | failed extraction 시 보고서 build | **계속 진행** (read-side graceful, claim trace 만 dormant) vs abort |
| 6.7 | ledger commit policy | **gitignore 유지** (R9-A.2 정책 그대로) vs commit |
| 6.8 | period boundary | claim period 와 보고서 period 동기화 — **monthly = 보고서 monthly**, quarterly 시 union (이미 R9-A.5 comment_trace 에서 지원) |

---

## 7. R9-A.4 smoke 계획 (단계별, LLM 0 → 통제 write → 운영)

### 7.1 LLM 0 dry-run (1차)

- 목적: daily_update 의 Step 2.7 진입점 / extractor 호출 경로 / canonical save 호출 검증
- 방법: `_call_llm` monkey-patch 또는 `--dry-run` 플래그 (기존 R9-A.2 CLI 패턴 재사용)
- write target: 0 (모든 file write 차단)
- 검증:
  - daily_update Step 순서에 2.7 진입 확인
  - 실 LLM 호출 0
  - canonical store / 08_Claims / ledger 변경 0

### 7.2 LLM 1회 single period replay (2차, 사용자 GO)

- 대상: 2026-04 (R9-A.1 pilot 과 동일 period 로 결과 비교)
- 호출: Haiku 1회 (~$0.05)
- write target:
  - `data/claims/2026-04.r9a4-replay.json` (기존 `2026-04.json` 미수정, suffix 분리)
  - `_promotion_quality.jsonl` 별도 ledger 또는 동일 ledger row append
  - 08_Claims 신규 page 0 (read-only, R9-A.2 manual smoke 결과 그대로)
- 검증:
  - claim count 22 (R9-A.1 과 동일, deterministic ID 일치)
  - promoted count A3 기준 8 (변동 시 분석)
  - 비용 < $0.1

### 7.3 운영 사이클 1회 smoke (3차, R9-A.6)

- daily_update 실 운영 path + 신규 month (2026-05 등) 로 실행
- write target: 정상 운영 path
- 검증: 비용 / 추출 품질 / promotion rate / UI 표시

### 7.4 abort 조건

- LLM 비용 단일 호출 > $0.5 → abort
- claim count = 0 (extractor 결과 비어있음) → abort + log
- canonical store 기존 hash 와 충돌 (period overwrite 의도치 않음) → abort + diff 보고
- ledger row append 외 운영 산출물 변경 감지 → abort + rollback

---

## 8. 추천 다음 순서

```
[현재] R9-A.5-UI Option A close (6c2df90)
   ↓
[Step 0] Review Packet 확인 (본 문서)
   ↓
[Step 1] R9-A.4 design mini-spec
   - 6.1~6.8 결정 사항 픽스
   - daily_update 의 정확한 진입점 코드 위치
   - 신규 extractor 모듈 / CLI flag
   ↓
[Step 2] R9-A.4 code implementation
   - 변경 파일 list
   - 테스트 (LLM 0 monkey-patch)
   ↓
[Step 3] R9-A.4 LLM 0 dry-run smoke (7.1)
   ↓
[Step 4] R9-A.4 LLM 1회 single period replay (7.2)
   ↓
[Step 5] R9-A.6 운영 사이클 1회 smoke (7.3)
   ↓
[Step 6] (선택) Option B — ReportFinalView client viewer 노출
```

R9-A.4 를 직접 구현 진입하기 전에 **Step 1 (mini-spec)** 으로 6.1~6.8 결정 사항을 사용자와 합의한 후 코딩 시작하는 것이 안전.

---

## 9. 미해결 / 후행 트랙

| # | 항목 | 우선순위 |
|---|---|---|
| A | R9-A.4 daily_update Step 2.7 통합 | 1순위 |
| B | R9-A.6 운영 사이클 1회 smoke | A 직후 |
| C | Option B ReportFinalView client viewer | 별 트랙 (정책 결정 필요) |
| D | claim wiki_path → 실제 라우팅 (UI 클릭 시 wiki page open) | 후행, UI 디자인 트랙 |
| E | Causal layer no_topic_matched 경고 (R7 rule 미매칭 evidence) | 별 트랙 (R9-A 와 무관) |
| F | wiki/01_Events~07_Graph_Evidence weekly batch commit 정리 | 별 트랙 (운영 관리) |

---

## 10. 결론 / Sign-off

R9-A read-side trace surface + Admin UI surface = **풀 close**.

`origin/main = 6c2df90` 시점 invariant:
- LLM 호출 0 (manual pilot 외)
- 운영 final / approved / regime / canonical store / 08_Claims / ledger 변경 0
- daily_update 미수정
- end-to-end 검증 비용 ~$0.78
- 사용자 시각 검수 PASS

R9-A.4 진입은 **Step 1 mini-spec** 부터. 사용자 GO 신호로 시작.
