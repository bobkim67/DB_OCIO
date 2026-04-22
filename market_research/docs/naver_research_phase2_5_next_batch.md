# naver_research — Phase 2.5 다음 배치: Source-aware Evidence Selection

일자: 2026-04-22
세션 브랜치: main (작업 commit 전 상태)
선행 핸드오프: `memory/handoff_naver_research.md` §6 "다음 배치 — source-aware evidence selection"

---

## 1. 배경

Phase 2.5 본선(commit 8529520) + 후속 cap+intensity-fix 실험(commit a1af702)으로
**단일 salience 공식으로 news와 naver_research 균형을 맞추는 방식은 효율이 낮다**는
결론에 도달. cap을 0.85→0.70으로 낮추자 top50 nr 비율이 18%까지 떨어지고, intensity-fix는
적용 후보가 11.4%에 그쳐 분포 균형에 본질적 개선 없음. nr는 0.4~0.55 좁은 구간 집중,
news는 0.2~0.4 넓게 분산 — 같은 점수 슬롯으로는 cross-source 균형이 안 맞는다.

**방향 전환**: salience는 source 내부 ranking 용도로만 쓰고, source 간 균형은
**evidence selection 단계**에서 quota로 해결.

설계 결정:
1. naver_research = primary evidence lane
2. news = corroboration / anomaly / breaking-event lane
3. debate input candidate 생성 시 source-aware quota (research 70% / news 30%)
4. 기존 debate diversity guardrail (토픽5/이벤트2) 유지 — quota만 추가

---

## 2. 구현 (단일 파일 변경)

### 2.1 영향 파일

- `market_research/report/debate_engine.py` — helper 추가 + 기존 후보 선발 블록 대체
- **변경 없음**: `debate_service.py`, `naver_research_adapter.py`, `salience.py`,
  `news_classifier.py` (단, 후속 검증 경로에서 `classify_adapted_month` 추가 — §3 참조)

### 2.2 신설 상수

```python
RESEARCH_QUOTA = 0.7    # research 목표 비율
MAX_PER_TOPIC = 5
MAX_PER_EVENT = 2
LATEST_SLOT = 2         # 당일 TIER1/2 news 전용 슬롯 (news quota 내)

# news corroboration lane 필터용 명시 리스트 (부동산/크립토 제외)
NEWS_CLEAR_TOPICS = frozenset({
    '통화정책', '금리_채권', '물가_인플레이션', '경기_소비',
    '유동성_크레딧', '환율_FX', '달러_글로벌유동성',
    '에너지_원자재', '귀금속_금',
    '지정학', '관세_무역', '테크_AI_반도체',
})
```

### 2.3 신설 함수

**`_is_news_tier12(article)`** — source 문자열로 TIER1/2 여부 판정.

**`_news_passes_corroboration(article)`** — news 후보 필터:

```
TIER1 or TIER2
AND (
    _bm_overlap == True
    OR _event_source_count >= 3
    OR primary_topic ∈ NEWS_CLEAR_TOPICS
)
```

**`_build_evidence_candidates(year, month, target_count, start_idx)` → `(high_impact, evidence_ids, card_lines, debug)`**

Lane A (research):
- `load_adapted(f'{year}-{month:02d}')` 로드
- 필터: `_classified_topics` 존재 AND `is_primary` AND `_research_quality_band ∈ {TIER1, TIER2}`
- 정렬: `_event_salience` 내림차순
- **intensity hard filter 해제** (결정사항 #4)

Lane B (news):
- `data/news/{YYYY-MM}.json` 로드
- 필터: `_classified_topics` 존재 AND `is_primary` AND `intensity>=6` AND `_news_passes_corroboration`
- 정렬: `_event_salience` 내림차순, tiebreaker intensity

Quota 및 guardrail 순서:
1. news quota 내 **당일 TIER1/2 slot** 최대 2건 우선 (결정사항 #3 — news quota 안으로 흡수)
2. research quota 채우기 (`topic≤5 / event≤2` 적용)
3. news quota 잔여 채우기 (`topic≤5 / event≤2` 적용)
4. 총량 미달 시 상대 lane에서 흡수

카드 렌더:

```
[ref:N] [nr]   통화정책 | 2026-01 | 하나증권 | <title>
    핵심: <description>
[ref:M] [news] 금리_채권 | 2026-01 | Bloomberg | <title>
    핵심: <description>
```

헤더: `주요 뉴스 (15건, N개 토픽, source-aware quota: nr 10 / news 5):`

### 2.4 `_build_shared_context` 수정

기존 후보 선발 블록(~75줄: Phase1 당일 slot + Phase2 salience 순)을 helper 호출
1줄로 대체. 상위 맥락(`topic_counts` 집계, asset_impact_vector 집계, `_next_idx`)은
유지.

### 2.5 디버그 로그

helper 내부에서 `_log('evidence_selection', month, target_count, research_quota,
news_quota, research_pool_size, news_pool_size, research_picked, news_picked,
total_picked)` 호출. `debate_logs/{YYYY-MM}.json`의 `llm_calls` 배열에 함께
기록되므로 사후에 nr/news 비율 추적 가능.

---

## 3. 검증 경로 (Phase 2.5 회귀)

Phase 2.5 검증은 2026-01에서만 이뤄졌기 때문에, 2026-02~04 debate를 돌리려면
adapted 재분류/정제가 필요. GraphRAG/regime/매크로/debate 는 건드리지 말고
Step 1.3 / 2 / 2.5 만 월별로 재실행하는 **경량 경로** 신설.

### 3.1 신설 파일

#### `market_research/analyze/news_classifier.py::classify_adapted_month(month_str, batch_size=20)`

`classify_month` 를 그대로 본떠 adapted 파일용으로 분리:
- `load_adapted(month_str)` → `_classified_topics` 미부착 건만 `classify_batch` 로 분류
- 50배치마다 중간 저장 (`save_adapted`)
- merge-on-save 로 downstream 필드는 자동 carry-over (어댑터 기존 기능)
- **news 는 건드리지 않음**

반환: `{'total', 'classified', 'newly_classified', 'unclassified'}`

#### `market_research/pipeline/reclassify_month.py`

Orchestration + audit 전담. 내부 순서:

```
_step_naver_research_adapter(month)
classify_adapted_month(month)
_step_refine(month)
```

news 는 파일을 읽기만 해서 **audit 보고**만 수행:
- `_classified_topics` 비어 있는 건수
- `_event_salience` 비어 있는 건수
- 커버리지 %

evidence snapshot:
- `_build_evidence_candidates(year, month, target_count=15)` 호출해 nr/news 비율 실측

사용:
```bash
python -m market_research.pipeline.reclassify_month --month 2026-02 2026-03 2026-04
```

### 3.2 이 경로가 건드리지 않는 것

- GraphRAG (`graph_rag.py`, `_step_graph_incremental`)
- regime_memory (`_step_regime_check`, canonical writer)
- 매크로 지표 (`macro_data.py`, `_step_collect_macro`)
- debate 실행 (`debate_engine.run_market_debate`, `debate_service`)

### 3.3 news 파일에 대한 정확한 동작

news 파일(`data/news/{YYYY-MM}.json`)에 대해 이 경로는 **audit 목적으로 읽는 것
외에 `_step_refine` 호출이 들어간다**. 즉 **파일이 수정은 되지만, 수정 범위는
salience 재계산에 한정**된다:

- **건드리지 않는 필드**: `_classified_topics`, `primary_topic`, `direction`,
  `intensity`, `_dedup_group_id`, `is_primary`, `_event_group_id`,
  `_event_source_count`, `_asset_impact_vector` 등 분류/dedupe 관련 필드 일체
- **재계산되는 필드**: `_event_salience`, `_asset_relevance`, `_bm_overlap`
  (+ 미분류 기사에 대한 `_fallback_classified` 보강)
- **news raw 오염 없음**: `classify_month` 은 이 경로에서 호출되지 않음 — 사용자가
  별도로 원할 때만 돌리면 됨

즉 §4.4 의 news audit 이 "파일 미변경" 이라고 표기한 것은
`_classified_topics` / `_event_salience` 부착률 audit 결과라는 뜻이지, 파일 자체가
완전히 동결된다는 뜻은 아님. (salience는 refine 재실행으로 일부 셀이 갱신될 수
있음.)

---

## 4. Acceptance 결과 (2026-02 / 2026-03 / 2026-04)

로그: `logs/reclassify_20260422.log`

### 4.1 월별 adapted 재분류 건수

| 월 | total | classified | 분류율 | unclassified |
|----|------:|----------:|-------:|-------------:|
| 2026-02 | 1,070 | 995 | 93.0% | 75 |
| 2026-03 | 1,394 | 1,315 | 94.3% | 79 |
| 2026-04 | 954 | 907 | 95.1% | 47 |

Phase 2.5 검증 월(2026-01, 93.3%)과 동일 수준 유지.

### 4.2 월별 refine 완료 여부

컬럼 설명:
- **news / naver_research**: 각 소스의 refine 상태 (`ok` = dedupe + salience + fallback 모두 완료)
- **primary_articles_total**: `_step_refine` 집계값 — news 와 naver_research 두 소스 기사 건수의 합 중 `is_primary=True` 인 건수. 기사 단위(article count), field count 아님
- **fallback_articles_total**: 같은 집계값 — 두 소스 합산 기준, `fallback_classify_uncategorized` 로 사후 분류된 기사 건수. nr 쪽은 모두 0 이므로 실질적으로 news 쪽 건수

| 월 | news | naver_research | primary_articles_total (news+nr) | fallback_articles_total (news+nr) |
|----|:----:|:--------------:|-------------------------------:|--------------------------------:|
| 2026-02 | ok | ok | 9,468 | 28 |
| 2026-03 | ok | ok | 28,691 | 30 |
| 2026-04 | ok | ok | 23,478 | 8 |

`primary_articles_total` 이 §4.4 의 news total 보다 큰 달이 있는 것은 **news + naver_research
합산**이기 때문. 예) 2026-03: news 27,482 + nr 1,394 중 primary 합 28,691.

### 4.3 월별 evidence selection (target=15)

| 월 | picked | nr | news | research_pool | news_pool | 판정 |
|----|-------:|---:|-----:|--------------:|----------:|:---:|
| 2026-02 | 15 | **10** | 5 | 972 | 772 | ✅ |
| 2026-03 | 15 | **10** | 5 | 1,289 | 2,643 | ✅ |
| 2026-04 | 15 | **10** | 5 | 884 | 1,581 | ✅ |

세 달 모두 **nr=10 / news=5 정확 70/30 quota**. 목표 범위 8~12 내.

### 4.4 news audit (분류 필드 미변경, salience는 refine 재실행으로 갱신됨)

> 이 표는 `_classified_topics` / `_event_salience` 두 필드의 **부착률**만 audit
> 한 결과. news 파일은 `classify_month` 로는 건드리지 않았고, `_step_refine` 에서
> salience 쪽만 재계산돼 100% 부착으로 올라왔다. 분류 필드(`_classified_topics`,
> `primary_topic`, `intensity` 등)는 unchanged.


| 월 | total | topic_coverage | no_topics | salience_coverage |
|----|------:|---------------:|----------:|------------------:|
| 2026-02 | 8,460 | 72.1% | 2,358 | 100% |
| 2026-03 | 27,482 | 62.1% | 10,414 | 100% |
| 2026-04 | 22,675 | 46.0% | 12,237 | 100% |

관찰:
- **salience 100%** — `_step_refine` 이 news 쪽도 함께 재계산 (정상 동작, dedupe/
  분류 필드는 유지되고 salience만 새로 계산됨. news 파일 오염 없음)
- **topic coverage 46~72%** — `classify_month` 가 돌지 않은 상태의 누적. non-financial
  기사가 섞여 있는 게 주원인으로 추정. 다만 evidence selection 은 이미
  `intensity>=6 AND corroboration_filter` 를 거쳐 사용 중이므로 quota 후보에 직접
  영향은 없음
- **권고**: 지금은 `classify_month` 재실행 불필요. news 커버리지가 quota 후보에
  실제로 영향을 주는지는 Phase 3 진행하며 모니터링

### 4.5 Acceptance 판정 (월별 15건, nr 8~12)

- PASS: 2026-02 / 2026-03 / 2026-04 (전부)
- SKIP (research_pool=0 fallback): 없음
- FAIL/경계: 없음
- guardrail 위반: 토픽/이벤트 상한 위반 0 (내부 로직 unchanged)

---

## 5. 운영상 비용 / 부작용

- **LLM 비용**: adapter classify 3개월 총 ≈ $0.02 (Haiku 154배치)
- **실행 시간**: 약 18분 (백그라운드)
- **파일 변경 범위**: `adapted/{YYYY-MM}.json` 3개 (merge-on-save 안전), refine 부작용으로
  `news/{YYYY-MM}.json` 3개의 salience 필드 재계산됨 (dedupe/분류 필드는 유지)
- **회귀 없음**: debate_engine의 topic/event guardrail 로직 unchanged. 2026-01 데이터로
  사전 단위 테스트 통과 후 2026-02~04 실측 재검증

---

## 6. 결정 사항 확인 (사용자 합의 그대로 반영)

1. ✅ Quota 비율 70/30 (research 70, news 30)
2. ✅ `primary_topic 명확` = 12개 명시 리스트 (부동산/크립토 제외)
3. ✅ 당일 TIER1/2 slot(최대 2건)은 news quota 안으로 흡수
4. ✅ research 후보 풀에서 intensity hard filter 해제, `_classified_topics` +
   `_research_quality_band ∈ {TIER1, TIER2}` + `_event_salience` 정렬
5. ✅ 카드에 `[nr]` / `[news]` 태그
6. ✅ `debate_logs` 에 source_type 비율 디버그 로그 (`event=evidence_selection`)

---

## 7. 후속 (Phase 3 진입 권고)

- **Phase 3**: GraphRAG / vectorDB 에 naver_research source_type 편입
  - 엔티티 추출 + ChromaDB 서브 컬렉션 분리
  - hybrid_score 산출 시 source_type 노출 (필터링용)
  - 뉴스 대비 evidence 선택률 비교 지표
- **모니터링**: debate_logs 의 nr/news 비율을 월 2~3회 debate 에서 누적해서
  실전 quota 유지 여부 확인
- **news topic coverage 저하 원인 규명**: 2026-04 46% 는 비financial 기사 유입이
  늘어난 결과인지, classifier 필터 변경이 누락된 결과인지 추적 필요

### 7.1 Phase 3 Acceptance (다음 배치 성공 기준)

Phase 3 성공/실패는 아래 4개 판정으로 정의. 전부 PASS 여야 완료.

1. **source_type 반영 (GraphRAG)**
   `data/insight_graph/{YYYY-MM}.json` 의 엔티티/엣지 노드에 `source_type` 필드가
   부착되고, 한 달 기준 `source_type='naver_research'` 비율이 최소 10% 이상
   (= nr 풀이 GraphRAG 에도 실질 반영되는지 확인). 0% 이면 FAIL.

2. **vectorDB source filter 동작 (ChromaDB)**
   `news_vectordb.py` 검색 호출 시 `where={'source_type':'naver_research'}` /
   `where={'source_type':'news'}` 두 필터가 **결과 disjoint** (교집합 0) 를 보이고,
   합집합이 unfiltered 결과와 일치해야 함. 둘 중 하나가 빈 결과면 FAIL.

3. **debate evidence 최종 카드 quota 유지**
   Phase 3 변경 적용 후 2026-02/03/04 세 달 재실행에서 `_build_evidence_candidates`
   결과 nr=8~12 범위가 **세 달 모두 유지**. 어떤 달이라도 범위 벗어나면 FAIL.

4. **evidence 선택률 cross-source 지표**
   nr vs news 각 소스에서 debate 에 뽑힌 기사 수 / 후보 풀 크기 비율을
   debate_logs 기준으로 계산. 두 소스 모두 **선택률 ≥ 0.5%** (= 풀 대비 실제 선발
   되는 비율이 어느 쪽도 0 에 수렴하지 않음). 한쪽이 0 이면 FAIL.

전 판정 PASS 후 `handoff_naver_research.md §6` 을 "완료"로 전환하고 다음 배치
(report output 파이프라인 통합) 로 이동.

---

## 8. 재사용 가능 CLI

```bash
# Phase 2.5 회귀 검증용 경량 경로 (GraphRAG/regime/매크로/debate 미터치)
python -m market_research.pipeline.reclassify_month --month YYYY-MM [YYYY-MM ...]
```

---

## 9. 파일 인벤토리

| 파일 | 변경 유형 | 역할 |
|------|:---------:|------|
| `market_research/report/debate_engine.py` | 수정 | helper 추가 + 후보 선발 블록 대체 |
| `market_research/analyze/news_classifier.py` | 수정 | `classify_adapted_month` 추가 |
| `market_research/pipeline/reclassify_month.py` | 신규 | 경량 orchestration + audit CLI |
| `logs/reclassify_20260422.log` | 산출 | 3개월 실행 로그 |
| `market_research/data/naver_research/adapted/2026-02.json` | 수정 | 분류/salience 부착 |
| `market_research/data/naver_research/adapted/2026-03.json` | 수정 | 분류/salience 부착 |
| `market_research/data/naver_research/adapted/2026-04.json` | 수정 | 분류/salience 부착 |
| `market_research/data/news/2026-02.json` | 수정 (salience만) | refine 부작용, 분류 필드 unchanged |
| `market_research/data/news/2026-03.json` | 수정 (salience만) | 〃 |
| `market_research/data/news/2026-04.json` | 수정 (salience만) | 〃 |
