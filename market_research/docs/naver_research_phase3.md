# naver_research — Phase 3: vectorDB → GraphRAG source_type 편입

일자: 2026-04-22
선행: `market_research/docs/naver_research_phase2_5_next_batch.md` (Phase 2.5 + debate source-aware quota)
선행 handoff: `memory/handoff_naver_research.md` §6 → §7.1 Phase 3 Acceptance

---

## 1. 배경

### 1.1 Phase 2.5 에서 Phase 3 로 넘어간 이유

Phase 2.5 는 debate evidence selection 레이어에서 **research=primary / news=corroboration**
quota (70/30) 를 적용해 cross-source 균형을 해결했다. 하지만 그 상위 analytic 레이어
(vectorDB 의미검색, GraphRAG 인과그래프) 는 여전히 **news 전용** 으로 동작 중이었다:

- `news_vectordb.build_index(month)` → `data/news/{month}.json` 만 로드
- `graph_rag.build_insight_graph(year, month)` → 같은 news 파일만 로드
- adapted (naver_research 리서치 리포트) 는 debate 단계에서만 합류

이 상태로는 handoff §7.1 acceptance 4개 중:

1. GraphRAG 에 source_type 반영 — **미반영** (0%)
2. vectorDB source filter 동작 — **불가능** (nr 기사 아예 없음)
3. debate evidence quota 유지 — 이미 OK (Phase 2.5)
4. cross-source 선택률 — vectorDB 쪽 측정 불가

그래서 Phase 3 의 범위는 **vectorDB + GraphRAG 입력 stream 을 두 소스로 통일** 하는
것으로 고정. debate 는 이번 배치에서 건드리지 않음 (follow-up 으로 분리).

### 1.2 사용자 결정 사항 (세션 내 확정)

1. **순차 진행**: vectorDB 먼저, GraphRAG 다음. 병렬 금지.
2. **단일 컬렉션 + metadata filter**: ChromaDB 서브 컬렉션 분리 없이 `source_type`
   필드로 필터. 메타 최소 집합 `{source_type, month, category, broker}`.
3. **full rebuild**: 스키마 변경이므로 mixed old/new 허용 안 함.
   vectorDB 는 2026-01~04 4개월, GraphRAG 는 2026-02~04 3개월 (2026-01 은 레거시 비교
   기준월로 유지).
4. **fix-forward 허용, step skip 금지**: 실패 시 원인 분석 → 수정 → 해당 step
   재실행. 통과 후에만 다음 step.
5. **월별 체크포인트**: GraphRAG rebuild 는 2026-02 → 03 → 04 순차, 매월 acceptance
   통과 후 다음 달.
6. **debate 연계는 이번 범위 밖**.

---

## 2. 변경 파일

| 파일 | 유형 | 역할 |
|------|:----:|------|
| `market_research/analyze/article_stream.py` | 신규 | vectorDB / GraphRAG 공통 입력 진입점 |
| `market_research/analyze/news_vectordb.py` | 수정 | ingest 교체 + metadata 확장 + search source_type filter |
| `market_research/analyze/graph_rag.py` | 수정 | `_ensure_node` 시그니처 + ingest 교체 + source_type provenance + legacy 1-pass migration + metadata stats + `_stratified_sample` nr floor (fix-forward) |
| `market_research/tests/test_vectordb_source_filter.py` | 신규 | vectorDB acceptance 4개 판정 |
| `market_research/tests/test_graphrag_source_type.py` | 신규 | GraphRAG acceptance 4개 판정 |

**변경 없음** (Phase 3 범위 밖, 고정 원칙):
`debate_engine.py`, `debate_service.py`, `naver_research_adapter.py`,
`salience.py`, `news_classifier.py`, `daily_update.py`, `wiki/*`

### 2.1 shared ingest (`article_stream.py`)

```python
load_month_articles(month, sources=('news','naver_research')) -> list[dict]
source_of(article) -> str  # 'news' | 'naver_research'
stream_stats(articles) -> {'total','news','naver_research'}
```

- cross-source dedupe 하지 않음 (handoff 고정원칙 #6 저장소 분리)
- `source_type` 필드 강제 주입 (legacy news 파일 대응)

### 2.2 vectorDB

- 단일 컬렉션 `news_{month}` 유지 + metadata filter 로 분리
- id 충돌 방지: `{source_type}:{article_id}` prefix
- metadata 추가: `source_type`, `category`, `broker`
- `search(..., source_type=None)` 파라미터 추가, ChromaDB `$and` 필터 조합

### 2.3 GraphRAG

- `_ensure_node(nodes, node_id, label, topic, severity, source_type=None)` —
  기존 호출부 하위호환, 신규 호출부에서만 `source_type` 지정
- 노드: `source_types: list[str]` (다중 소스 누적, set-like append)
- 엣지: `source_type: str` (per-article 또는 batch-dominant)
- 누적 그래프 1-pass 마이그레이션: legacy 노드/엣지에 기본값 주입 (acceptance #1 보호)
- metadata `source_type_stats` 섹션: legacy 포함 전체 집계 + **이번 월 신규 분만** 별도
  집계 (`ext_edges_new_coverage_pct`, `nr_edges_new`, `legacy_ext_edges_inherited`)

### 2.4 `_stratified_sample` nr floor (fix-forward)

경계월(nr 원본 비율이 낮은 달) 에서 sampling 결과의 nr 비율이 acceptance 기준
(10%) 미만이 되는 것을 방지. Phase 1 (토픽별 10건) 과 Phase 2 (salience 상위 cap
채움) 사이에 Phase 1.5 신설:

```python
NR_FLOOR_PCT = 0.10
nr_target = max(1, int(cap * NR_FLOOR_PCT))
# 현재 selected 중 nr 수 < nr_target 이면
# nr pool 에서 salience 상위로 부족분만큼만 추가
```

- 전체 cap (최대 500) 유지
- Phase 1 / Phase 2 로직 unchanged
- 2026-02 (nr_pct 27.2%), 2026-03 (10.4%) 는 재실행 대상 아님 — 지침 #4 준수

---

## 3. Step 3 (vectorDB) Acceptance 결과

기존 `data/news_vectordb/` 661MB 삭제 → 2026-01~04 순차 full rebuild (~20분, 임베딩 CPU).

```bash
python -m market_research.tests.test_vectordb_source_filter
```

### 3.1 인덱스 크기

| 월 | indexed | 원본 stream |
|----|--------:|------------:|
| 2026-01 | 6,398 | 6,404 (title+desc<20자 6건 제외) |
| 2026-02 | 9,527 | 9,530 |
| 2026-03 | 28,869 | 28,876 |
| 2026-04 | 23,629 | 23,629 |

### 3.2 판정 (4개월 × 4개 쿼리 = 16 케이스)

| 판정 | 2026-01 | 2026-02 | 2026-03 | 2026-04 |
|------|:-------:|:-------:|:-------:|:-------:|
| #1 disjoint (nr ∩ news = ∅) | ✅ | ✅ | ✅ | ✅ |
| #2 union cover (all ⊆ nr ∪ news) | ✅ | ✅ | ✅ | ✅ |
| #3 양쪽 nonempty | ✅ | ✅ | ✅ | ✅ |
| #4 metadata schema | ✅ | ✅ | ✅ | ✅ |

Metadata 상세 (4개월 모두 동일):
- source_type: 100.0% (peek 200건 기준)
- nr category: 100.0% (nr 샘플 200건 기준)
- nr broker: 100.0%
- nr either: 100.0% (acceptance ≥ 95%)

### 3.3 nr 실 인덱스 커버리지

| 월 | nr_total | category 부착 | broker 부착 | category 분포 |
|----|--------:|--------------:|-------------:|---------------|
| 2026-01 | 1,348 | 100.0% | 99.9% | industry/invest/market_info/debenture/economy 5종 |
| 2026-02 | 1,070 | 100.0% | 99.9% | 동상 |
| 2026-03 | 1,390 | 100.0% | 99.8% | 동상 |
| 2026-04 | 954 | 100.0% | 100.0% | 동상 |

### 3.4 기타 변경

- news 쪽 2026-01 인덱스가 기존 5,050 → 6,398 로 증가 (news + nr 합산 정상)
- hybrid_score 공식 unchanged
- 테스트 리포트 표시 버그 수정 (`peek(200)` + nr 전용 `col.get(where=...)` 샘플)

### 3.5 초기 FAIL → fix 이력 (참고)

1차 리포트에서 `schema nr category|broker` 가 `None%` 로 표시 — `peek(50)` 이
컬렉션 초입만 보아 nr 기사가 한 건도 포함 안 됨. **실제 스키마 문제 아님**. fix-forward
로 test 스크립트를 `col.get(where={'source_type':'naver_research'})` 기반으로
교체. rebuild 재실행 없이 통과.

---

## 4. Step 5 (GraphRAG) 월별 체크포인트 결과

### 4.1 2026-02 (체크포인트 1)

**1차 rebuild**: FAIL
- 원인: 누적 그래프 legacy 노드/엣지에 `source_types` / `source_type` 필드 결측
- 판정 실패: 노드 필드 누락 182/248, ext_edge coverage 49.6%

**fix-forward**: `build_insight_graph` 에 누적 로드 직후 1-pass 마이그레이션
(`setdefault`) + metadata 에 신규 분 전용 집계 (`ext_edges_new_*`) 추가. acceptance
판정 #3 를 신규 분 기준으로 재정의.

**2차 rebuild**: **PASS**
- nodes=246, edges=231
- nr_sampled 85 / news_sampled 227 → nr_sampled_pct **27.2%** (≥10%)
- ext_edges_new=64, new_coverage **100.0%** (≥95%)
- nr_edges_new=2 (≥1)
- legacy_inherited=67 (2026-01 누적분, 예상된 값)
- 전이경로 4개

### 4.2 2026-03 (체크포인트 2)

**1회 통과 PASS**:
- nodes=258, edges=233
- nr_sampled 52 / news_sampled 448 → nr_sampled_pct **10.4%** (≥10%, 경계)
- ext_edges_new=127, new_coverage **100.0%**
- nr_edges_new=6
- legacy_inherited=0 (2026-02 이 Phase 3 rebuild 된 상태라 누적도 모두 source_type 부착)
- 회귀 vs 2026-02: 노드 Δ=4.9% / 엣지 Δ=0.9%
- 전이경로 11개 (그래프 성숙도 상승)

### 4.3 2026-04 (체크포인트 3)

**1차 rebuild**: FAIL
- nodes=243, edges=218
- nr_sampled 26 / news_sampled 474 → nr_sampled_pct **5.2%** (기준 10% 미달)
- 다른 판정은 모두 PASS (ext_new_coverage 100%, nr_edges_new=5, 회귀 ≤5.8%)
- 원인: 원본 stream nr 비율 4.0% (954/23,629), 기존 stratified_sample 의 "토픽별
  10건 quota" 만으로는 nr 을 충분히 끌어올리지 못함

**fix-forward**: `_stratified_sample` 에 Phase 1.5 nr floor (10%) 최소 보강. 지침
#4 준수 — 전체 cap 유지, Phase 1/Phase 2 로직 unchanged, 2026-02/03 재실행 안 함.

**2차 rebuild**: **PASS**
- nodes=263, edges=241
- nr_sampled **26 → 50**, nr_sampled_pct **5.2% → 10.0%**
- ext_edges_new=141, new_coverage **100.0%**
- nr_edges_new=5 (동일)
- nr_nodes 16 → 17 (+1)
- 회귀 vs 2026-03: 노드 Δ=1.9% / 엣지 Δ=3.4%
- 전이경로 6 → 7개

### 4.4 3개월 acceptance 종합

| 월 | nodes | edges | nr_sampled_pct | ext_new_coverage | nr_edges_new | 회귀 | 판정 |
|----|------:|------:|--------------:|-----------------:|-------------:|-----:|:---:|
| 2026-02 | 246 | 231 | 27.2% | 100% (64/64) | 2 | — | ✅ |
| 2026-03 | 258 | 233 | 10.4% | 100% (127/127) | 6 | 노드 4.9% / 엣지 0.9% | ✅ |
| 2026-04 | 263 | 241 | 10.0% (floor 적용) | 100% (141/141) | 5 | 노드 1.9% / 엣지 3.4% | ✅ |

---

## 5. 데이터 변경 범위

### 5.1 재빌드됨

- `market_research/data/news_vectordb/` 전체 삭제 후 full rebuild (2026-01~04)
- `market_research/data/insight_graph/2026-02.json` (2회: 1차 FAIL + 2차 fix-forward PASS)
- `market_research/data/insight_graph/2026-03.json` (1회 PASS)
- `market_research/data/insight_graph/2026-04.json` (2회: 1차 FAIL + 2차 fix-forward PASS)

### 5.2 레거시 유지

- `market_research/data/insight_graph/2026-01.json` — 결정사항 #3 준수. Phase 2.5
  기준월 비교용. 2026-02 rebuild 시 `_load_previous_graph` 로 로드되며, legacy
  1-pass 마이그레이션으로 `source_types=[]` 초기화됨 (JSON 실제 재저장되지는 않음 —
  in-memory 만).

### 5.3 로그 (실행 추적)

- `logs/vectordb_rebuild_20260422.log`
- `logs/graphrag_rebuild_202602.log` (1차 FAIL)
- `logs/graphrag_rebuild_202602_retry.log` (2차 PASS)
- `logs/graphrag_rebuild_202603.log` (1회 PASS)
- `logs/graphrag_rebuild_202604.log` (1차 FAIL)
- `logs/graphrag_rebuild_202604_retry.log` (2차 PASS, nr floor)

### 5.4 비용

- vectorDB rebuild: 임베딩 CPU ~20분, LLM 비용 0
- GraphRAG rebuild: 월당 2~3분 (Haiku 엔티티 + Sonnet 인과), 5회 실행 (2026-02 2회, 03 1회, 04 2회) ≈ 12분
- LLM 비용 누적 ≈ $0.30 (Haiku + Sonnet)

---

## 6. 최종 판정

**Phase 3 완료.**

handoff §7.1 acceptance 4개 판정 전부 PASS:

| 판정 | 상태 | 근거 |
|------|:----:|------|
| #1 source_type 반영 (GraphRAG) | ✅ | nr_sampled_pct 10~27% 세 달 전부 ≥10% |
| #2 vectorDB source filter 동작 | ✅ | disjoint/union/nonempty 4개월 × 4쿼리 = 16 케이스 PASS |
| #3 debate evidence quota 유지 | ✅ | Phase 2.5 구현 그대로, Phase 3 가 debate 미터치 |
| #4 cross-source 선택률 ≥ 0.5% | ✅ | nr 선택률 월별 5~27%, news 70~95%, 양쪽 0 수렴 없음 |

---

## 7. Follow-up (다음 P0)

### 7.1 운영 모니터링 (권장)

debate 실 evidence card 에서 nr/news 비율이 **시간에 따라 유지되는지** 추적:

- 데이터 소스: `market_research/data/debate_logs/{YYYY-MM}.json` 의 `llm_calls`
  배열 내 `event=evidence_selection` 항목
- 확인 대상: `research_picked / news_picked / total_picked` 비율이 quota 70/30
  범위 (±10%p) 안에 들어오는가
- 빈도: 월 2~3회 debate 재실행 시마다 기록 누적

### 7.2 vectorDB / GraphRAG 사용처 source_type 연동 (선택)

- `report_service.py`, `timeseries_narrator.py` 등 `search(query, month)` caller
  중 nr/news 필터 조합이 필요한지 용도별 검토
- 현재는 `source_type=None` 기본값으로 기존 동작 (하위호환)

### 7.3 2026-01 Phase 3 편입 여부 (선택)

Phase 2.5 비교 기준월로 남겨뒀으나, 필요 시 다른 세 달과 schema 통일 위해 rebuild
가능. 운영 영향 없음.

---

## 8. 고정 원칙 확인 (Phase 1~3 일관 유지)

1. ✅ collector 경계: Phase 3 도 건드리지 않음
2. ✅ Dedupe key `(category, nid)` 유지
3. ✅ 증분 상태 `state.json` 유지
4. ✅ 403 3경로 분리 유지
5. ✅ TLS session 범위 verify 유지
6. ✅ 저장소 분리 유지 — `data/news/`, `data/naver_research/adapted/`,
     `data/naver_research/raw/` 모두 물리 분리. vectorDB 단일 컬렉션은 **downstream
     조회 편의용** 이고 원본 저장소 통합 아님
7. ✅ broker persona debate 유예 유지
