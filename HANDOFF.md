# HANDOFF.md

## Snapshot

- Date: 2026-04-21
- Project: `DB_OCIO_Webview_news` (renamed from `DB_OCIO_Webview`)
- Branch: `feature/regime-replay` (PR #18 → main, open)
- HEAD: `f4e6b99`
- Main focus 직전 세션: insight engine 정리 (v10~v15 + v13 entity redesign)
- 다음 세션 의도: **뉴스 수집(collect) 로직 redesign** — 별도 새 세션 + 새 브랜치 권장

---

## 이번 세션에서 한 일 (2026-04-20 ~ 04-21)

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

### 다음 세션 후보 (우선순위)
1. **뉴스 수집 로직 redesign** ← 사용자 명시 (별도 새 세션 권장)
   - 현재 위치: `collect/macro_data.py`, `collect/naver_blog.py`, `daily_update.py` Step 1
   - 검토 후보 dimension: source quality 재평가, dedupe 정책, salience 가중치, fallback 분류 등 (사용자 의도 확인 필요)
2. **regime 판정식 실전 모니터링 2주** (passive)
   - daily_update 매일 실행 → `_regime_quality.jsonl` 누적 → 분포 분석
3. **Entity layer 후속**
   - `달러` split rule (분류기 신뢰도 측정 후 재검토)
   - 종목명 entity 정책 (sector 외 layer 신설 여부)
   - `per_taxonomy_floor` 활성화 trigger (alias 풀 보강 후)

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
1. 본 HANDOFF.md 읽기
2. `git log --oneline -20` 으로 최근 commit 확인
3. 사용자 의도 파악 — "뉴스 수집 로직 redesign"의 구체적 방향성 질문
   - 어떤 부분을 바꾸고 싶은지 (수집 source / dedupe / salience / fallback / 다른 것)
   - 현 동작의 문제점 또는 새로 추가하고 싶은 기능
4. 새 브랜치 cut (예: `feature/news-collect-redesign`) 또는 main 직접 작업 결정
5. Spec-First 원칙대로 충분한 질문 후 구현 진입

---

## Revision

- **2026-04-21** — v15 replay + v13.x entity redesign 통합 정리. 다음 세션은 뉴스 수집 로직.
- 2026-04-10 (이전) — debate hallucination 방어 + 매크로 브리핑 UI.
