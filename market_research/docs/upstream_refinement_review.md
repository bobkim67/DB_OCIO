# Upstream Refinement Layer — Technical Review Document

> 작성일: 2026-04-09
> 목적: 뉴스 수집 → 정제 → GraphRAG → Debate → 운용보고 코멘트 전체 파이프라인의 로직/프로세스 상세 기술
> 대상: 외부 LLM 또는 리뷰어

---

## 1. 전체 파이프라인 개요

```
[수집]          [분류]         [정제]              [분석]           [보고]
macro_data  → classifier  → dedupe+salience  → GraphRAG       → debate
(뉴스3소스)   (Haiku 21주제)  (ID/중복/점수/구제)   (엔티티+인과)     (4인 LLM)
                                              → vectorDB       → comment
                                                (hybrid검색)     (Opus 종합)
```

### 일일 배치 흐름 (`pipeline/daily_update.py`)

```
Step 0: 매크로 지표 수집 (SCIP/FRED/NYFed/ECOS)
Step 1: 뉴스 수집 (네이버 금융 + Finnhub)
Step 2: 뉴스 분류 (Haiku, 21주제 + 13키 자산영향도)
Step 2.5: 정제 (dedupe → salience → fallback) ← 이번 구현의 핵심
Step 3: GraphRAG 증분 (엔티티 추출 + 인과추론)
Step 4: MTD 델타 요약 (LLM 불필요, 토픽 카운트 집계)
Step 5: regime_memory 업데이트 (shift 감지)
```

---

## 2. Step 2.5 정제 레이어 상세

### 2.1 호출 구조

```python
# pipeline/daily_update.py :: _step_refine()
def _step_refine(month_str: str) -> dict:
    articles = raw_data.get('articles', [])
    articles = process_dedupe_and_events(articles)   # A+B+C
    articles = compute_salience_batch(articles)       # D
    fallback_count = fallback_classify_uncategorized(articles)  # E
    safe_write_news_json(news_file, raw_data)         # 저장
```

실행 범위: **월별 뉴스 JSON 전체** (일일 배치에서도 당월 전체를 재처리).
이유: dedupe/event clustering은 기사 간 비교이므로, 오늘 수집된 기사가 어제 기사의 중복일 수 있음.

### 2.2 Phase A: Article ID 부여

```python
# core/dedupe.py :: assign_article_ids()
def _make_article_id(article: dict) -> str:
    key = f"{title}|{date[:10]}|{source}"
    return hashlib.md5(key.encode('utf-8')).hexdigest()[:12]
```

| 항목 | 내용 |
|------|------|
| 입력 | `title`, `date`, `source` |
| 출력 | `_article_id`: 12자 hex (예: `b07523c195c0`) |
| 목적 | 파이프라인 전체에서 기사를 안정적으로 식별 (URL은 불안정) |
| 멱등성 | 이미 `_article_id` 존재하면 스킵 |
| 충돌 확률 | MD5 12자 = 48bit, 10만건 기준 충돌 확률 < 0.04% |

**리뷰 포인트**: MD5 12자(48bit)는 월 2~3만건 규모에서 충돌 가능성 매우 낮으나, 수십만건 이상 스케일에서는 16자(64bit) 이상 권장. 현재 규모에서는 적절.

### 2.3 Phase B: 중복 제거 (Dedup)

```python
# core/dedupe.py :: dedupe_articles()
```

**2단계 그룹핑:**

| 단계 | 기준 | 설명 |
|------|------|------|
| 1차 | URL 정규화 일치 | query param/fragment 제거 후 비교 |
| 2차 | 제목 prefix 40자 + 같은 날짜 | 소문자+공백+특수문자 정규화 후 앞 40자 |

**Primary 선정 규칙:**

| 우선순위 | 조건 |
|----------|------|
| 1 | Wire copy 원본 (Reuters, AP, AFP, 연합뉴스, Yonhap) |
| 2 | 가장 긴 `description`을 가진 기사 |
| 3 | 미할당 단독 기사 → 자동 primary |

**생성 필드:**

| 필드 | 형식 | 설명 |
|------|------|------|
| `_dedup_group_id` | `dedup_0`, `dedup_1`, ... | 중복 그룹 식별자 |
| `is_primary` | `True`/`False` | 그룹 대표 기사 여부 |

**실측 결과 (backfill):**

| 월 | 전체 | Primary | 중복 제거율 |
|----|------|---------|-----------|
| 2026-01 | 5,050 | 2,055 | 59% |
| 2026-02 | 8,460 | 3,793 | 55% |
| 2026-03 | 27,482 | 14,430 | 47% |
| 2026-04 | 20,931 | 11,145 | 47% |

**리뷰 포인트:**
- 제목 prefix 40자는 한국어 뉴스에서 충분한가? 한국어 뉴스 제목은 영문보다 짧은 경향 → 30자면 과도하게 매칭될 수 있으나, 40자는 적절한 편.
- 날짜 ±0일만 비교 (dedup은 같은 날짜만). event clustering에서 ±1일 교차 처리.
- Wire copy 판정이 `source` 또는 `title` 끝 패턴만 봄 → 본문 앞부분 비교는 미구현.

### 2.4 Phase C: 이벤트 클러스터링

```python
# core/dedupe.py :: cluster_events()
```

**같은 사건의 다른 보도를 그룹핑.** Dedup이 "같은 기사"를 묶는다면, Event Clustering은 "같은 사건에 대한 서로 다른 기사"를 묶음.

**알고리즘:**

```
1. primary 기사만 대상
2. (date, primary_topic) 버킷으로 비교 범위 축소
3. 인접일(±1일) 같은 topic 버킷 간 교차 비교
4. 비교 조건:
   a. Jaccard(제목 단어 집합) >= 0.15  (pre-filter, 빠름)
   b. SequenceMatcher(제목 전체) >= 0.3  (정밀, a 통과 시에만)
5. 조건 충족 → Union-Find merge (path compression)
6. 같은 source 기사 간은 비교 스킵 (dedup에서 이미 처리)
```

**최적화:**

| 기법 | 효과 |
|------|------|
| (date, topic) 버킷 | O(n²) → O(k²) (k = 버킷 크기) |
| topic='' 제외 | 미분류 기사 대량 버킷 방지 |
| Jaccard pre-filter | SequenceMatcher 호출 90% 절감 |
| Union-Find + path compression | 그룹 병합 O(α(n)) |

**성능**: 27K건(2026-03) → 0.7초

**생성 필드:**

| 필드 | 형식 | 설명 |
|------|------|------|
| `_event_group_id` | `event_0`, `event_1`, ... | 이벤트 그룹 식별자 |
| `_event_source_count` | int | 그룹 내 고유 소스(언론사) 수 |

**리뷰 포인트:**
- `primary_topic` 일치가 필수 조건 → 분류기가 같은 사건에 다른 topic을 부여하면 누락.
  예: "연준 금리 동결" 기사를 A언론은 `금리`, B언론은 `통화정책`으로 분류 → 매칭 실패.
  개선안: 같은 TOPIC_ASSET_SENSITIVITY 그룹(예: 금리+통화정책+미국채)이면 교차 허용.
- SequenceMatcher 0.3은 상당히 느슨한 임계치. 다른 사건이 유사 제목이면 오클러스터 가능.
- non-primary 기사의 event_group 상속: dedup_group primary의 event_group을 물려받음 — 합리적.

### 2.5 Phase D: Salience 이중 점수

```python
# core/salience.py :: compute_event_salience(), compute_asset_relevance()
```

#### Event Salience (사건 중요도, 0~1)

```
score = 0.30 × source_quality
      + 0.25 × intensity_norm
      + 0.25 × corroboration
      + 0.20 × bm_overlap
```

| 요소 | 계산 | 범위 |
|------|------|------|
| `source_quality` | TRUSTED_SOURCES 포함 → 1.0, 아니면 0.3 | 0.3~1.0 |
| `intensity_norm` | `min(intensity / 10, 1.0)` | 0~1.0 |
| `corroboration` | `min(_event_source_count / 5, 1.0)` | 0~1.0 |
| `bm_overlap` | BM z>1.5 날짜 해당 → 1.0, 아니면 0.0 | 0 or 1.0 |

**TRUSTED_SOURCES** (12개):
```
Reuters, Bloomberg, AP, Financial Times, WSJ, CNBC,
Yonhap, 연합뉴스, SeekingAlpha, Benzinga, The Times of India, MarketWatch
```

**현재 한계**: `bm_anomaly_dates`가 파이프라인에서 미연동 (항상 `None` → `bm_overlap = 0`).
따라서 현재 실효 공식은:

```
score = 0.30 × source_quality + 0.25 × intensity_norm + 0.25 × corroboration
```

**실측 평균 salience**: 0.276~0.321 (월별)

#### Asset Relevance (자산군 관련도)

```python
# 각 분류 토픽에 대해 TOPIC_ASSET_SENSITIVITY 룩업
for topic in _classified_topics:
    sensitivity = TOPIC_ASSET_SENSITIVITY[topic]  # 13키 dict
    score = abs(base_val) × (intensity / 10.0)
    relevance[asset_key] = max(기존, score)  # 토픽 간 max 취합
# score >= 0.1인 자산군만 반환
```

**TOPIC_ASSET_SENSITIVITY 구조** (21주제 × 13 자산군):
```
13키: 국내주식, 해외주식, 국내채권, 해외채권, 해외채권_USHY, 해외채권_USIG,
      해외채권_EM, 미국주식_성장, 미국주식_가치, 원자재_금, 원자재_원유,
      환율_USDKRW, 환율_DXY
```

각 값은 -1.0~+1.0 범위의 전문가 지정 민감도.
예: `금리` 토픽 → `해외채권: -0.9`, `원자재_금: 0.3`

**리뷰 포인트:**
- `bm_overlap` 미연동으로 salience 공식의 20% 가중치가 항상 0. 이로 인해 점수 분포가 압축됨 (최대 0.80 → 실질 최대 ~0.60).
- `source_quality`가 이진(0.3 or 1.0)이라 TRUSTED_SOURCES 미포함 소스의 점수가 일괄 하락. 네이버 금융 뉴스(네이버검색, 네이버금융)가 TRUSTED에 없어 국내 뉴스 전체가 0.3 처리됨.
- `corroboration` 계산이 `_event_source_count` 의존 → event clustering 품질에 종속. Phase C의 topic 일치 제약이 여기에 전파됨.

### 2.6 Phase E: Uncategorized Fallback

```python
# core/salience.py :: fallback_classify_uncategorized()
```

**대상**: `_classified_topics == []` (빈 배열) AND `_classify_error` 없음
**조건**: `is_market_relevant()` 통과 (5개 조건 중 2개 이상):

| # | 조건 | 설명 |
|---|------|------|
| 1 | `source` in TRUSTED_SOURCES | 신뢰 소스 |
| 2 | `date` in `bm_anomaly_dates` | BM 이상일 (현재 미연동) |
| 3 | title에 MACRO_KEYWORDS 포함 | 27개 거시 키워드 중 1개+ |
| 4 | `_event_source_count >= 2` | 교차보도 |
| 5 | `title_keyword_score >= 0.5` | 키워드 3개+ 매칭 |

**분류 로직**:
1. `_KEYWORD_TOPIC_MAP` (50개 키워드 → 10개 토픽) 으로 제목 매칭
2. 매칭된 키워드의 토픽별 최대값 취합, base intensity = 4
3. 키워드 매칭 없으면 범용 `'거시경제': intensity 3` 부여
4. `TOPIC_ASSET_SENSITIVITY` 룩업으로 `_asset_impact_vector` 생성

**생성 필드**: `_classified_topics`, `_fallback_classified: True`, `primary_topic`, `direction: 'neutral'`, `intensity`, `_asset_impact_vector`

**실측**: 월 9~22건 (전체 대비 0.1% 미만)

**리뷰 포인트:**
- fallback 건수가 매우 적음(월 ~20건). 이는 분류기(Haiku)의 커버리지가 높다는 의미이지만, `is_market_relevant()` 의 조건 2(bm_anomaly) 미연동 + 조건 4(event_source_count)가 미분류 기사에서는 거의 0 → 실질적으로 조건 1+3+5만 유효 → 통과 조건이 "신뢰소스 AND 키워드 3개+"로 매우 엄격.
- direction이 항상 `neutral` → asset_impact_vector가 절대값 기반이라 방향성 정보 손실.

---

## 3. GraphRAG 투입 (Step 3)

### 3.1 Stratified Sampling

```python
# analyze/graph_rag.py :: _stratified_sample()
```

**Dynamic Cap 공식:**
```python
cap = min(n, max(300, int(n * 0.05)))
cap = min(cap, 500)
```

| 후보 수 (n) | cap |
|-------------|-----|
| < 300 | n (전부) |
| 300~6,000 | 300 |
| 6,000~10,000 | n × 5% (300~500) |
| > 10,000 | 500 |

**2-Phase Sampling:**

```
Phase 1: 토픽별 최소 10건 quota
  - primary_topic별 그룹핑
  - 각 그룹 내 salience 내림차순 정렬
  - 토픽별 상위 10건 우선 선발
  - '_none' 토픽(미분류) 제외

Phase 2: 나머지 cap까지 salience 상위로 채움
  - 전체 candidates를 salience + intensity 내림차순 정렬
  - Phase 1에서 이미 선발된 기사 중복 방지 (_article_id 기반)
```

**검증 결과 (200 fixed vs stratified):**

| 지표 | 200 fixed (3월) | Stratified (3월) | 변화 |
|------|----------------|-----------------|------|
| 선택 건수 | 200 | 500 | +150% |
| 토픽 수 | 9 | 30 | **+233%** |
| Top1 비중 | 70.5% | 42.6% | **-28pp** |
| Top3 비중 | 95.0% | 61.8% | **-33pp** |

**리뷰 포인트:**
- Phase 2에서 salience 상위가 여전히 다수를 차지하므로, topic quota 10건이 소진된 뒤 나머지 ~300건은 다시 지정학/유가에 쏠림. 이는 의도된 설계 (quota로 최소 다양성 확보 + 나머지는 중요도 순).
- quota 10건이 모든 토픽에 동일 → 저출산_인구(2건 존재)도 10건 할당 시도하지만 2건만 선발. 이것은 올바른 동작.
- `_article_id` 기반 중복 방지는 Phase 1과 Phase 2 간에만 적용. Phase 1 내부에서 같은 기사가 여러 토픽에 중복 분류된 경우는? → `_classified_topics`가 리스트이지만 `primary_topic` 기준으로 그룹핑하므로 문제 없음.

### 3.2 엔티티 추출 + 인과추론

```
[stratified sample]
    ↓
[extract_entities_from_news(significant)]   ← Haiku 배치 (30건/배치)
    ↓ entity_map: {idx: [entity1, entity2, ...]}
    ↓
[엔티티→토픽 엣지 생성]
    weight = 0.3 + salience × 0.4   (범위: 0.3~0.7)
    ↓
[infer_causal_edges(entity_map, significant)]   ← Sonnet (공출현 3+, 상위 20쌍)
    ↓ inferred: [{from, to, relation, weight, source}]
    ↓
[_dedup_edges()]
    ↓
[precompute_transmission_paths()]   ← BFS, 시드노드 출발
```

**엣지 가중치 공식 (news_entity 엣지):**
```python
base_weight = 0.3 + art.get('_event_salience', 0.3) * 0.4
# salience=0 → weight=0.3, salience=0.75 → weight=0.6, salience=1.0 → weight=0.7
```

**Daily Incremental** (`add_incremental_edges()`):
- `_stratified_sample()` 미적용 (일일 기사수가 적으므로 primary 전량 투입)
- 투입 후 Self-Regulating TKG 실행: `decay → merge → recompute → prune`

**리빌드 결과 비교 (2026-03):**

| 지표 | 200 fixed | Stratified 500 | 변화 |
|------|-----------|---------------|------|
| 노드 | 381 | 503 | +32% |
| 엣지 | 444 | 625 | +41% |
| LLM 추론 엣지 | 84 | 126 | +50% |
| 뉴스 엔티티 엣지 | 254 | 393 | +55% |
| 전이경로 | 21 (19 유니크) | 24 (23 유니크) | +14% |
| Connected components | 49 | 58 | +18% |

**리뷰 포인트:**
- `infer_causal_edges()`는 "공출현 3회 이상, 상위 20쌍"만 Sonnet에 투입 → 입력 500건이어도 Sonnet 호출은 20회 내외로 제한됨.
- 엔티티→토픽 엣지의 가중치가 salience 기반이라, 낮은 salience 기사의 엔티티도 노드로는 생성되지만 엣지 가중치가 낮아 전이경로에서 자연스럽게 필터됨 — 좋은 설계.
- Connected components +18%는 새로운 독립 클러스터가 생겼다는 의미. 이는 보조 토픽(금리, AI, 환율 등)에서 기존에 없던 엔티티 클러스터가 형성된 것.

---

## 4. VectorDB (검색 레이어)

### 4.1 인덱싱

```python
# analyze/news_vectordb.py :: build_index()
```

| 항목 | 값 |
|------|---|
| 백엔드 | ChromaDB PersistentClient |
| 컬렉션 | `news_{month}` (월별 분리) |
| 거리 | cosine |
| 임베딩 모델 | `all-MiniLM-L6-v2` (sentence-transformers, CPU) |
| 임베딩 텍스트 | `"{title}. {description}"` (20자 미만 스킵) |
| doc_id | `_article_id` 우선, 없으면 `{month}_{index}` |
| 배치 | 임베딩 batch_size=64, chromadb add 5000건씩 |

**저장 메타데이터 (17 필드):**

| 필드 | 소스 | 용도 |
|------|------|------|
| `month`, `date`, `source` | 원본 | 기본 필터 |
| `asset_class`, `symbol` | 원본 | 자산군 필터 |
| `title`, `url`, `provider` | 원본 | 표시용 |
| `trusted` | 원본 | 소스 신뢰도 |
| `article_id` | dedupe | evidence 추적 |
| `primary_topic` | classifier | 주제 필터 |
| `intensity` | classifier | 강도 |
| `direction` | classifier | 방향성 |
| `event_salience` | salience | hybrid 검색 가중 |
| `is_primary` | dedupe | 중복 필터 |
| `fallback` | fallback | fallback 여부 |

### 4.2 Hybrid Score 검색

```python
# analyze/news_vectordb.py :: search()
hybrid_score = (1.0 - distance) + event_salience * 0.3
```

| 요소 | 범위 | 가중 |
|------|------|------|
| cosine similarity (`1-distance`) | 0~1.0 | 1.0× |
| event_salience | 0~1.0 | 0.3× |
| **hybrid_score** | **0~1.3** | |

결과는 `hybrid_score` 내림차순 정렬.

**`search_for_factors()`** (PA 기여도 원인 검색):
- 자산군별 방향성 포함 쿼리 자동 생성 (예: `Korean stock market KOSPI 상승 reason`)
- `is_primary == 'False'` 기사 필터 아웃
- 제목 앞 40자 기준 중복 제거

**리뷰 포인트:**
- hybrid_score에서 salience 가중치 0.3이 적절한지? cosine similarity 0.8 vs 0.6인 기사가 있을 때, salience 0.5인 0.6 기사(hybrid=0.75)가 salience 0인 0.8 기사(hybrid=0.8)보다 낮음. → salience가 semantic relevance를 뒤집지 않는 수준으로 적절.
- `is_primary` 필터가 string 비교 (`'False'`). chromadb 메타는 모두 string 저장이므로 `str(True)` → `'True'`. `is_primary` 필드가 없는 기존 데이터는 `''`이 되어 필터 통과 → 하위 호환 OK.
- 임베딩 모델이 영어 전용(`all-MiniLM-L6-v2`). 네이버 한국어 뉴스 검색 품질이 낮을 수 있음. multilingual 모델(`paraphrase-multilingual-MiniLM-L12-v2`) 고려 가능.

---

## 5. Debate Engine (보고 레이어)

### 5.1 컨텍스트 빌드

```python
# report/debate_engine.py :: _build_shared_context()
```

**뉴스 데이터 투입 흐름:**

```
월별 뉴스 JSON 로드
    ↓
_classified_topics 보유 기사만 필터
    ↓
is_primary=True만 필터 (dedup 중복 제거)
    ↓
[토픽 카운트] primary_classified 전체 → Counter → 상위 10건 표시
    ↓
[주요 뉴스] intensity >= 6 → salience 내림차순 정렬 → 상위 15건
    ↓ 각 기사의 _article_id → evidence_ids 수집
    ↓ _event_source_count >= 2 → "교차보도:N건" 표시
    ↓
[자산영향 집계] primary_classified 전체의 _asset_impact_vector 합산
    ↓ 상위 10개 자산군 표시 (MTD 누적)
    ↓
context['news_summary_text'] = 조립된 텍스트
context['_evidence_ids'] = [article_id, ...]
```

**프롬프트에 포함되는 뉴스 정보 구조:**

```
뉴스 분류 요약 (N건, 중복제거 후):
  지정학: 3,200건
  유가_에너지: 1,500건
  AI_반도체: 1,200건
  ...

주요 뉴스 (상위 15건, salience 순):
  [지정학] Iran conflict enters week 5... (Reuters, 2026-03-28) [sal:0.85, 교차보도:4건]
  [유가_에너지] WTI breaks $108 on supply fears (Bloomberg, 2026-03-27) [sal:0.80, 교차보도:3건]
  ...

자산군별 뉴스 영향 집계 (MTD):
  환율_USDKRW: -42.35
  해외채권: -38.21
  미국주식_성장: -35.10
  ...
```

### 5.2 4인 에이전트 + Opus 종합

```
[Bull] Haiku → bullish stance + key_points + asset_allocation_view
[Bear] Haiku → bearish stance + ...
[Quant] Haiku → data-driven stance + ... (Priority Anchor)
[monygeek] Haiku → eurodollar school stance + ... (블로그 컨텍스트 추가)
         ↓ 병렬 실행 (ThreadPoolExecutor, 4 workers)
         ↓
[Opus Step 1] 4인 의견 → 고객용 코멘트 (전문가 톤, 3-5문단)
[Opus Step 2] 4인 의견 → 합의점/쟁점/Tail Risk JSON
         ↓
result = {
    'agents': {bull, bear, quant, monygeek},
    'synthesis': {customer_comment, consensus_points, disagreements, tail_risks},
    'regime': regime_memory,
    '_evidence_ids': [기사ID 15건],
}
```

**규칙:**
- Quant의 수치가 다른 에이전트와 충돌 시 Quant 우선 (Priority Anchor)
- 제공된 수치 수정/반올림 금지
- monygeek: 지표 괴리 ±20% → 'Tail Risk' 라벨 필수

**evidence_ids 흐름:**
```
_build_shared_context()에서 주요 뉴스 15건의 _article_id 수집
    → context['_evidence_ids']
    → run_market_debate() 결과의 '_evidence_ids' 키로 반환
    → debate_logs/{YYYY-MM}.json에 저장
```

**리뷰 포인트:**
- evidence_ids가 debate 결과에 포함되지만, Opus 코멘트의 어떤 문장이 어떤 기사에 기반했는지는 추적 불가. 현재는 "이 debate에 이 기사들이 투입되었다" 수준의 추적.
- 4인 에이전트가 공유하는 뉴스 컨텍스트가 동일 → 4인 모두 같은 상위 15건만 참조. 에이전트별 다른 뉴스 풀 (Bull은 긍정 뉴스, Bear는 부정 뉴스)을 주는 것도 고려 가능.
- `intensity >= 6`으로 주요 뉴스를 필터하지만, fallback 분류 기사(intensity=3~4)는 포함 안 됨. fallback이 매우 적으므로(월 ~20건) 영향은 미미.

---

## 6. 데이터 흐름 요약 (기사 1건의 라이프사이클)

```
[수집] Finnhub API → {title, date, source, description, url}
                       ↓
[분류] Haiku → +{_classified_topics, _asset_impact_vector, primary_topic,
                  direction, intensity, asset_class}
                       ↓
[정제]
  assign_article_ids → +{_article_id}
  dedupe_articles    → +{_dedup_group_id, is_primary}
  cluster_events     → +{_event_group_id, _event_source_count}
  compute_salience   → +{_event_salience, _asset_relevance}
  fallback_classify  → (미분류만) +{_classified_topics, _fallback_classified, ...}
                       ↓
[저장] data/news/YYYY-MM.json (월별, 전체 필드 포함)
                       ↓
         ┌─────────────┼─────────────┐
         ↓             ↓             ↓
[vectorDB]        [GraphRAG]     [debate]
build_index()     _stratified    _build_shared
  메타 17필드       _sample()      _context()
  hybrid검색        엔티티추출      primary필터
                    인과추론        salience정렬
                    가중엣지        evidence추적
```

---

## 7. 비용 구조

| 단계 | 모델 | 비용/건 | 월간 추정 |
|------|------|---------|----------|
| 뉴스 분류 | Haiku | ~$0.01 | $80~110 (8~11K건) |
| GraphRAG 엔티티 추출 | Haiku | ~$0.01 | $3~5 (300~500건) |
| GraphRAG 인과추론 | Sonnet | ~$0.05 | $1~3 (20~60건) |
| Debate 4인 | Haiku×4 | ~$0.04/set | $0.04 |
| Debate 종합 | Opus×2 | ~$0.30/set | $0.30 |
| **월간 합계** | | | **$85~120** |

대부분의 비용은 뉴스 분류(Haiku)에 집중. GraphRAG stratified sampling으로 LLM 투입을 500건 이내로 제한하여 비용 관리.

---

## 8. 알려진 제약사항 및 개선 후보

| # | 항목 | 현재 상태 | 영향 | 개선안 |
|---|------|----------|------|--------|
| 1 | `bm_anomaly_dates` 미연동 | salience 공식의 20% 가중치 항상 0 | salience 분포 압축 | BM 시계열에서 z>1.5 날짜 추출 → salience에 연동 |
| 2 | TRUSTED_SOURCES에 네이버 미포함 | 국내 뉴스 source_quality 일괄 0.3 | 국내 뉴스 salience 하락 | 네이버금융, 매일경제, 한경 등 추가 |
| 3 | event clustering topic 일치 필수 | 같은 사건이라도 다른 topic이면 누락 | 교차보도 과소 집계 | 관련 토픽 그룹(금리+통화정책+미국채) 교차 허용 |
| 4 | 임베딩 모델 영어 전용 | 한국어 뉴스 검색 품질 저하 | vectorDB 검색 정밀도 | multilingual 모델 전환 |
| 5 | fallback direction 항상 neutral | 방향성 정보 손실 | asset_impact_vector 부호 무의미 | 키워드 주변 컨텍스트로 방향 추정 |
| 6 | evidence 추적이 건 수준 | 코멘트 문장↔기사 매핑 불가 | 출처 검증 불가 | LLM 출력에 [ref:article_id] 태그 요청 |
| 7 | 전이경로 중복 | 동일 경로가 여러 번 출현 | 경로 수 과장 | `precompute_transmission_paths()`에 dedup 추가 |
| 8 | daily_update에서 월 전체 재처리 | 월말에 3만건 처리 | 처리 시간 ~3초 (허용 범위) | 증분 dedupe 구현 (대규모 시 필요) |

---

## 9. Ablation Test 결과

4가지 조건에서 뉴스 풀 품질 비교 (LLM 호출 없이 메트릭만 측정):

| 조건 | 설명 | 풀크기(3월) | 토픽수 | 평균Sal | 교차보도% |
|------|------|-----------|--------|---------|----------|
| A_baseline | raw intensity>=7 | 12,565 | 30 | 0.342 | 1.4% |
| B_dedupe | +primary 필터 | 6,770 | 27 | 0.338 | 2.4% |
| C_salience | +salience정렬 상위15 | 15 | 2 | 0.752 | 100% |
| D_full | +fallback, 상위20 | 20 | 2 | 0.751 | 100% |

**해석:**
- B→A: dedupe로 46% 중복 제거 (토큰 절감)
- C/D: debate 프롬프트에 투입되는 15~20건은 교차보도 100%, 평균 salience 0.75
- C/D의 토픽 수 2는 debate 프롬프트 내 "주요 뉴스" 섹션만의 수치. "토픽 카운트" 섹션에서는 primary_classified 전체의 토픽 분포가 별도 제공됨
