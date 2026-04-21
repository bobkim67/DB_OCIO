# HANDOFF.md

## Snapshot

- Date: **2026-04-21 (마감 — 2차 업데이트)**
- Project: `DB_OCIO_Webview_news` (renamed from `DB_OCIO_Webview`)
- Branch: `feature/regime-replay` (PR #18 → main, open). HEAD 커밋은 `59b2cb2` (1차 HANDOFF 커밋).
- Uncommitted: naver_research Phase 1 + 2026-04-21 daily_update 실행 산출물
- Main focus (이번 세션): **Naver Research collector Phase 1 종료** — 뉴스 수집 로직 redesign의 구체화된 결과물
- 다음 세션 의도: **커밋 전략 결정 + YTD 전 카테고리 full backfill + Phase 2 adapter 설계 진입**
- 상세 핸드오프: `memory/handoff_naver_research.md` (신규) — 새 세션은 여기 먼저 읽기

---

## 이번 세션에서 한 일 (2026-04-21, 2차 업데이트)

### 1. daily_update 2026-04-21
Step 0~5 전 구간 완료(~20분). 매크로 62/62, 뉴스 142건, 블로그 571건, 분류 77/142,
GraphRAG 증분, MTD 델타, regime check. `.last_collect_date → 2026-04-21`,
`news/2026-04.json 23,783건 누적`. regime 상태 **유지**(지정학+물가_인플레이션, weeks 2).
shift_detected=false, multi_rule_v12 기준 충족 실패.

### 2. Naver Research Phase 1 — Collector v0.2.0 종료 판단
- **설계**: `market_research/docs/plan_naver_research.md` v0.5 (deprecated 표기 규약 포함)
  - 5 카테고리: 경제/시황/투자/산업/채권 (종목분석 제외). YTD 실측 4,771건, PDF 84%
  - Dedupe `(category, nid)`, 증분 cursor `state.json` 카테고리별
  - Quality tier는 Phase 2 adapter에서 heuristic (TIER1 고정 폐기)
  - broker persona debate는 Phase 4에서 기존 `debate_engine.py` evidence 확장으로만 흡수
- **구현**: `market_research/collect/naver_research.py` v0.2.0
  - 전역 SSL override 제거 (Session.verify 범위로만, 시작 시 경고 출력)
  - HTTP retry: 429(+Retry-After) / 5xx / 403(최대 2회) + jittered backoff
  - 최종 403 승격: `AccessBlockedError` → list/detail stage별 `stats.errors` 기록.
    detail 연속 3회 시 카테고리 조기 종료. **PDF 403은 별도 경로**(`pdf_http_error` +
    `pdf_failed` + `record.pdf_download_error`, errors 경로 아님)
  - detail selector 재배열 + 품질 gate (100자 / 숫자 60%), fallback warning
  - broker list → detail → regex 순 보강, `broker_source` 필드 기록
  - `data/naver_research/key_index/{category}.json` — O(1) dedupe
  - Warning codes 상수화 9개, dry-run observability 확대
- **검증**: smoke test 5종 누적 130건 기준 P1 Acceptance 전 항목 통과
  (P1-1 수집률 100% / P1-2 summary 98.5% / P1-3 PDF 100% / P1-4 warnings 4.6% /
  P1-5 dedupe 중복 0 / P1-6 `_warnings` 경로 정상 / P1-7 403 승격은 static 검증만 ⚠️)
- **운영 메모**: `market_research/docs/naver_research_phase1.md`
  - TEST 1~5 블록 (economy ×2, debenture, invest, market_info) — acceptance 표와 수치 1:1 일치
  - Observability 표에서 list/detail 403 (`errors`) vs PDF 403 (`warning_codes`+`pdf_failed`) 3경로 분리 명시
  - "경로가 다른 이유 (code truth)" 서브섹션 — `http_get` / `download_pdf` 흐름까지 코드 위치로 설명

### 3. 이전 세션 (2026-04-20) — 참조용
- v15 regime replay CLI (17일 실증), v10~v14 미커밋 잔재 7배치 정리 + filter-repo
  (news_vectordb 334MB 히스토리 제거), v13.x entity page redesign, PHRASE_ALIAS 2차 review.
  → 상세는 `memory/handoff_insight_engine.md` 참조.

---

## (이전 기록) 2026-04-20 ~ 04-21 초반 세션

### 1. v15 regime replay (CLI + 17일 실증)
- `tools/regime_replay.py` — as-of-date rolling 45일 replay
- `_judge_regime_state` / `_compute_delta_from_articles` pure function 분리
  (live `_step_regime_check`은 thin wrapper)
- `tests/test_regime_replay.py` 8 cases PASS
- 17일(2026-04-01~04-17) 실측: candidate=0 (initial state=neutral_empty 부작용, honest 보고)
- 산출물: `_regime_quality_replay.jsonl`, `regime_replay_summary.{json,md}`
- review packet: `docs/review_packet_replay.md`

### 2. 미커밋 v10~v14 잔재 일괄 정리 (7배치)
이전 세션들에서 컴미트 안 된 v10~v14 산출물을 batch별로 7개 commit으로 정리
+ git filter-repo로 news_vectordb (334MB) 히스토리 제거 → push 성공.
PR #18 생성 (`gh pr create`).

### 3. 3일 백필 (2026-04-18 / 19 / 20)
주말 포함 누락분 backfill. `.last_collect_date → 2026-04-20`.
regime: 지정학 + 물가_인플레이션 (since 2026-04-01, weeks 2). shift 0건.

### 4. PHRASE_ALIAS 2차 review (v15)
unresolved 10건 → keep_unresolved 4건 추가, approved 0건 (v11 contract 준수).

### 5. v13.1 entity page redesign — 본격 구현
**핵심 전환**: node metadata (severity) → graph structure (edge effective_score + path_role).
- `wiki/entity_builder.py` 신규: 5함수 (load/map/importance/articles/select)
- `wiki/draft_pages.py::write_entity_page` 단순 dict 시그니처
- 매체 entity (`source__*`) 생성 중단 + `_purge_stale_entity_pages`
- 본문에서 adjacency/path 상세 제거 (07_Graph_Evidence/만 소유)
- 신규 test 7 + 재작성 test 5
- 실측 4월: 101 노드 → taxonomy gate hit 4 → 4 entities
- 1차 review: revise/hold → format D evidence response로 재제출

### 6. v13.2 entity alias backfill — coverage 검증
- 16개 후보 검토 → APPROVE 4 / REJECT 8 / DEFER 4
- 추가 alias: `국제유가`, `호르무즈 해협`, `호르무즈 봉쇄`, `이란 협상` (모두 evidence 충분, risk=low)
- gate hit 4 → 8, entities 4 → 7 (이란 협상은 cap=3에서 drop)

### 7. v13.3 entity diversity controls
- `달러` audit 결과: defer 유지 (가격 단위 압도, funding 의미 1%만)
- `entity_builder.select_entity_candidates`에 옵션 2개 추가:
  - `per_taxonomy_floor` (default 0)
  - `suppress_near_duplicates` (default False)
- refresh에서 `suppress=True` 활성화 → `유가/국제유가` 중복 제거
- alias 1건 추가: `원/달러 → 환율_FX`
- after: 7 entities (지정학 3 / 에너지 1 / FX 2 / 테크 1)
- false positive 0, contract 위반 0
- 5 docs 작성 (diagnosis / dollar policy / options / alias review / result)

---

## 현재 상태

### Branch / PR
- `feature/regime-replay` (HEAD `f4e6b99`)
- PR #18 https://github.com/bobkim67/DB_OCIO/pull/18 (open, main 타겟)
- 백업 브랜치: `feature/regime-replay-backup` (filter-repo 전 SHA 보존)

### 02_Entities (2026-04, 7건)
| label | taxonomy | importance | arts |
|-------|----------|-----------:|-----:|
| 유가 | 에너지_원자재 | 4.088 | 2542 |
| 이란 | 지정학 | 2.805 | 3096 |
| 호르무즈 해협 | 지정학 | 1.852 | 553 |
| 환율 | 환율_FX | 1.686 | 2092 |
| 반도체 | 테크_AI_반도체 | 0.772 | 2234 |
| 호르무즈 봉쇄 | 지정학 | 0.517 | 78 |
| 원/달러 | 환율_FX | 0.282 | 183 |

### 회귀 테스트 (전체 PASS)
- test_taxonomy_contract 3/3
- test_alias_review 6/6
- test_entity_builder 9/9 (case 8/9 신규 — suppress + floor)
- test_entity_demo_render 5/5 (재작성)
- test_regime_replay 8/8
- test_regime_decision_v12 4/4
- test_regime_monitor 7/7

### 데이터 상태
- last_collect_date: 2026-04-20
- regime: 지정학 + 물가_인플레이션 (since 2026-04-01, weeks 2)
- 4월 articles: 23,495건 (2026-04-21 09:30 기준)
- 4월 graph: 101 nodes / 108 edges / 4 transmission paths

---

## Open Issues / TODO

### 다음 세션 P0 (우선순위)
1. **커밋/푸시 전략 결정** — uncommitted 상태인 naver_research 3개 파일 + daily_update 2026-04-21 실행 산출물
   - 선택지 A: 현재 `feature/regime-replay`에 단일 `chore:` 커밋
   - 선택지 B: 신규 브랜치 `feature/naver-research`로 분기 (권장 — PR #18 스코프 분리)
   - 선택지 C: PR #18 병합 후 main 위에서 새 브랜치 시작
2. **YTD 전 카테고리 full backfill** — Phase 1 공식 종료
   ```bash
   python -m market_research.collect.naver_research --backfill 2026-01-01
   ```
   - 예상: ~80분, ~4GB. 카테고리별 `--limit-pages 50` 분할 또는 야간 배치 권장
   - 실전 403 차단 이벤트 첫 관찰 기회 → `detail_blocked_hits >= 3` 임계치 재튜닝 근거 확보
3. **Phase 2 adapter 설계 진입**
   - `market_research/collect/naver_research_adapter.py` — naver_research record → article-like dict 변환
   - research-specific quality heuristic (plan §9 초안) 적용: 경제/채권 TIER1 후보, 시황/투자 TIER2 기본, summary <120자 TIER3 강등 등
   - `daily_update.py`에 `Step 1.3: 리서치 수집` 호출 wrapper 5~10라인
   - gold 50건 분류 precision 측정

### P1 (후순위)
- **regime 판정식 실전 모니터링 2주** (passive) — daily_update 매일 실행 → `_regime_quality.jsonl` 누적
- **broker_source 분포 관찰** — 현재 실측 130건 전부 `source=list`. full backfill 후 `detail`/`missing` 발동 빈도 확인
- **Phase 3 — GraphRAG / vectorDB 편입** — `source_type="naver_research"` 엔티티 경로 + ChromaDB 서브 컬렉션 + 뉴스 대비 엔티티 수 / evidence 선택률 비교
- **Entity layer 후속** — `달러` split rule, 종목명 entity 정책, `per_taxonomy_floor` 활성화 trigger

### 영구 deferred
- `달러` 단독 alias — audit 결과 다의어 폭증 위험
- 종목명 alias (`삼성전자`, `SK하이닉스`, `나스닥`) — 정책 미정
- 새 taxonomy 항목 (`국내주식`, `해외주식` 등) — 14 contract 유지
- media entity (`source__*`) 복구 금지

### 기존 issue (이전 세션부터 carry)
- Opus hallucination 잔여 (debate)
- 매매이력 분석 문단 자동 생성 (DWPM10520)
- GraphRAG 누적 폭발 (rolling window 리서치 필요)

---

## 집에서 작업 가능 vs 불가능

### 가능 (DB 불필요)
- 뉴스/블로그 수집 (`daily_update.py`)
- debate 실행 + 코멘트 생성 (Anthropic API)
- Streamlit 운용보고(전체) 탭 (로컬 JSON)
- entity / wiki 작업
- 후처리 / validator 개선

### 불가능
- SCIP/dt DB 접속 (192.168.195.55 내부망)
- Overview/편입종목/성과분석/매크로 탭
- VP/BM/PA 관련 작업

---

## GitHub

- 코드 + 데이터 모두 push 완료 (`f4e6b99`)
- vectorDB (334MB+)는 .gitignore + 히스토리 제거 (filter-repo 적용)
- 집에서 clone 후 vectorDB만 리빌드:
  ```bash
  python -m market_research.analyze.news_vectordb 2026-04
  ```

---

## Next Actions (다음 세션 시작 시)

새 세션 시작 시 권장 순서:
1. **`memory/handoff_naver_research.md` 먼저 읽기** (이번 세션 상세 핸드오프)
2. 본 HANDOFF.md로 전체 프로젝트 스냅샷 확인
3. `git log --oneline -5` + `git status --short | head` 으로 현 상태 확인
4. **커밋 전략 결정** — 사용자에게 A/B/C 중 선택 요청
5. 선택 후 naver_research YTD full backfill 또는 Phase 2 adapter 설계 중 하나로 진입

### 새 세션 시작 프롬프트 (권장)
```
memory/handoff_naver_research.md 확인하고 이어서 작업해.
```

---

## Revision

- **2026-04-21 (2차)** — Naver Research Phase 1 collector v0.2.0 종료 판단 + doc마감. daily_update 2026-04-21 완료. 다음은 커밋 전략 → YTD full backfill → Phase 2 adapter.
- 2026-04-21 (1차) — v15 replay + v13.x entity redesign 통합 정리. 다음 세션은 뉴스 수집 로직.
- 2026-04-10 (이전) — debate hallucination 방어 + 매크로 브리핑 UI.
