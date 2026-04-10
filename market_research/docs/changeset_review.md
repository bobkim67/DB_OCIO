# Upstream Refinement — 파일별 변경사항 (리뷰용)

> 작성일: 2026-04-09
> 대상 파일 6개 + 신규 파일 2개

---

## 변경 요약

| 파일 | 변경 유형 | 핵심 변경 |
|------|----------|----------|
| `core/dedupe.py` | 기존 수정 + 함수 추가 | article_id 부여, topic-neighbor event clustering |
| `core/salience.py` | 기존 수정 + 함수 추가 | bm_anomaly_dates, 3단계 source_quality, fallback 분류 |
| `pipeline/daily_update.py` | 기존 수정 | Step 2.5 삽입 (정제 레이어) |
| `report/debate_engine.py` | 기존 수정 | primary 필터, salience 정렬, diversity guardrail, evidence 추적 |
| `analyze/graph_rag.py` | 기존 수정 + 함수 추가 | stratified sampling, primary 필터, salience 가중 엣지 |
| `analyze/news_vectordb.py` | 기존 수정 | 분류 메타 저장, hybrid_score 검색 |
| `tests/ablation_test.py` | **신규** | 정제 효과 비교 프레임워크 |
| `docs/upstream_refinement_review.md` | **신규** | 전체 설계 리뷰 문서 |

---

## 1. `core/dedupe.py` — 중복 제거 + 이벤트 클러스터링

### 신규 추가

#### `_make_article_id()` / `assign_article_ids()` (L22-33)
```python
def _make_article_id(article: dict) -> str:
    key = f"{article.get('title', '')}|{article.get('date', '')[:10]}|{article.get('source', '')}"
    return hashlib.md5(key.encode('utf-8')).hexdigest()[:12]

def assign_article_ids(articles: list[dict]) -> list[dict]:
    for a in articles:
        if '_article_id' not in a:
            a['_article_id'] = _make_article_id(a)
    return articles
```
- **목적**: 파이프라인 전체에서 기사를 안정적으로 식별. URL은 불안정(query param 변동)하므로 title+date+source 기반 해시.
- **생성 필드**: `_article_id` (12자 hex)
- **멱등성**: 이미 존재하면 스킵

#### `TOPIC_NEIGHBORS` (L196-209)
```python
TOPIC_NEIGHBORS = {}
for _group in [
    {'금리', '통화정책', '미국채'},
    {'물가', '금리'},
    {'달러', '한국_원화', '엔화_캐리', '중국_위안화'},
    {'유가_에너지', '지정학'},
    {'관세', '지정학'},
    {'AI_반도체', '미국증시'},
    {'안전자산', '금'},
    {'유로달러', '유동성_배관'},
]:
    for _t in _group:
        TOPIC_NEIGHBORS.setdefault(_t, set()).update(_group - {_t})
```
- **목적**: 같은 사건이 분류기에 의해 다른 topic으로 태깅될 때 event clustering에서 누락되는 문제 해결.
- **설계 근거**: "연준 금리 동결" 기사가 A언론은 `금리`, B언론은 `통화정책`으로 분류되어도 같은 이벤트로 매칭.
- **리뷰 포인트**: 그룹이 지나치게 넓으면 무관한 기사가 오클러스터될 수 있음. 현재 8개 그룹으로 보수적 설정.

### 기존 수정

#### `cluster_events()` (L212-301)
**변경 전**: `(date, primary_topic)` 버킷 → 같은 topic 내에서만 비교
**변경 후**: `compare_topics = {topic} | TOPIC_NEIGHBORS.get(topic, set())` → 인접 토픽 간 교차 비교

```python
for topic in topics:
    compare_topics = {topic} | TOPIC_NEIGHBORS.get(topic, set())
    for d1 in dates_sorted:
        indices_1 = bucket.get((d1, topic), [])
        for d2 in adjacent[d1]:
            for t2 in compare_topics:           # ← 인접 토픽 포함
                indices_2 = bucket.get((d2, t2), [])
                is_cross_topic = (topic != t2)
                # 교차 토픽 시 Jaccard 임계치 상향 (0.15 → 0.20)
                _compare_and_merge(..., jaccard_threshold=0.20 if is_cross_topic else 0.15)
```
- **precision 통제**: 교차 토픽 비교 시 Jaccard 임계치를 0.15→0.20으로 상향하여 오매칭 방지.
- **성능 영향**: 27K건 기준 1.1초→1.6초 (50% 증가, 여전히 2초 미만)
- **효과**: 3월 교차보도 기사 0건→282건

#### `_compare_and_merge()` (L340-369)
**변경**: `jaccard_threshold` 파라미터 추가 (기존 하드코딩 0.15)
```python
def _compare_and_merge(idx_a, idx_b, articles, title_word_cache, uf, compared,
                       jaccard_threshold=0.15):       # ← 파라미터화
    ...
    if _jaccard(words_a, words_b) < jaccard_threshold:  # ← 가변 임계치
        return
```

#### `process_dedupe_and_events()` (L376-381)
**변경**: `assign_article_ids()` 호출 추가
```python
def process_dedupe_and_events(articles: list[dict]) -> list[dict]:
    articles = assign_article_ids(articles)   # ← 신규
    articles = dedupe_articles(articles)
    articles = cluster_events(articles)
    return articles
```

---

## 2. `core/salience.py` — Salience 이중 점수 + Fallback 분류

### 신규 추가

#### `load_bm_anomaly_dates()` (L16-97)
```python
def load_bm_anomaly_dates(year: int, month: int, threshold_z: float = 1.5) -> set:
```
- **목적**: SCIP BM 시계열에서 z-score > 1.5인 날짜를 추출하여 salience 공식의 `bm_overlap` 20% 가중치를 활성화.
- **대상 BM**: S&P500, KOSPI, Gold, DXY, USDKRW, 미국종합채권 (6개)
- **계산**: 5일 수익률 / 20일 vol → z-score, 3개월 lookback으로 vol 안정성 확보
- **반환**: `set[str]` — `{'2026-03-02', '2026-03-04', ...}` 형태
- **실측**: 3월 15일, 4월 3일 (시장 변동성에 비례)
- **리뷰 포인트**: `_date(year, month, 28)` 은 월말 근사. 2월 28일 이후 데이터 누락 가능성 없음 (3개월 lookback이므로). DB 접속 실패 시 빈 set 반환 (graceful degradation).

#### `TIER1_SOURCES` / `TIER2_SOURCES` (L99-121)
**변경 전**: `TRUSTED_SOURCES` 이진 (1.0 / 0.3)
**변경 후**: 3단계
```python
# Tier 1 (1.0): 글로벌 통신사 + 국내 통신사
TIER1_SOURCES = {
    'Reuters', 'Bloomberg', 'AP', 'Financial Times', 'WSJ', 'CNBC', 'MarketWatch',
    'Yonhap', '연합뉴스', '연합뉴스TV', '뉴시스', '뉴스1',
}
# Tier 2 (0.7): 경제지 + 준전문
TIER2_SOURCES = {
    'SeekingAlpha', 'Benzinga', 'The Times of India', 'Business Insider',
    'Forbes', 'Fortune', 'NPR', 'BBC News', 'CoinDesk',
    '매일경제', '한국경제', '서울경제', '머니투데이', '이데일리',
    '파이낸셜뉴스', '아시아경제', '헤럴드경제', '더벨', '비즈니스포스트',
    '조선일보', '조선비즈', '동아일보', '중앙일보', '한겨레',
    '네이버금융',
}
# Tier 3 (0.3): 나머지
```
- **설계 근거**: 국내 뉴스 `source` 필드가 `_extract_source()` 로 파싱되어 실제 언론사명이 들어옴. 파싱 실패 시 `네이버검색`으로 남으므로 Tier3(0.3).
- **리뷰 포인트**: `네이버금융`은 네이버 금융 섹션 크롤링 뉴스. 실제 출처는 경제지이지만 source 파싱이 안 된 경우이므로 Tier2로 배치. `인포스탁`(종목 찌라시)이 Tier2에 포함되지 않은 것은 의도적.

#### `fallback_classify_uncategorized()` (L266-323)
```python
def fallback_classify_uncategorized(articles, bm_anomaly_dates=None) -> int:
```
- **목적**: LLM 분류에서 `_classified_topics: []`(빈 배열)로 나온 기사 중, 시장과 관련있는 기사를 키워드 기반으로 구제.
- **조건**: `is_market_relevant()` 통과 (5개 조건 중 2개+)
- **분류 로직**: `_KEYWORD_TOPIC_MAP` (50개 키워드 → 10개 토픽) 매칭, base intensity=4
- **생성 필드**: `_classified_topics`, `_fallback_classified: True`, `primary_topic`, `direction: 'neutral'`, `intensity`, `_asset_impact_vector`
- **리뷰 포인트**: direction이 항상 neutral. 키워드 주변 컨텍스트("하락", "급등")로 방향 추정하는 로직은 P2로 분류됨.

### 기존 수정

#### `compute_event_salience()` (L135-171)
**변경**: source_quality를 3단계로
```python
# 변경 전
source_quality = 1.0 if source in TRUSTED_SOURCES else 0.3

# 변경 후
if source in TIER1_SOURCES:
    source_quality = 1.0
elif source in TIER2_SOURCES:
    source_quality = 0.7
else:
    source_quality = 0.3
```
- **효과**: 매일경제(국내 1위 경제지) 기사의 source_quality가 0.3→0.7. salience 공식에서 +0.12 상승.

#### `compute_salience_batch()` (L202-208)
**변경**: bm_anomaly_dates 로그 출력 추가
```python
def compute_salience_batch(articles, bm_anomaly_dates=None):
    if bm_anomaly_dates:
        print(f'  salience: bm_anomaly {len(bm_anomaly_dates)}일 연동')
    ...
```

#### `is_market_relevant()` (L218-231)
**변경**: `TRUSTED_SOURCES` → `TIER1_SOURCES | TIER2_SOURCES`
```python
# 변경 전
article.get('source', '') in TRUSTED_SOURCES,

# 변경 후
source in TIER1_SOURCES or source in TIER2_SOURCES,
```

---

## 3. `pipeline/daily_update.py` — 일일 배치

### 기존 수정

#### Step 2.5 삽입 (L90-96)
Step 2(분류)와 Step 3(GraphRAG) 사이에 정제 레이어 삽입:
```python
# ── Step 2.5: Dedupe + Salience + Uncategorized Fallback ──
print(f'\n[Step 2.5] Dedupe + Salience + Fallback...')
refine_result = _step_refine(month_str)
result['steps']['refine'] = refine_result
```

#### `_step_refine()` 신규 함수 (L185-242)
```python
def _step_refine(month_str: str) -> dict:
```
- **호출 순서**: `load_bm_anomaly_dates()` → `process_dedupe_and_events()` → `compute_salience_batch(bm_anomaly)` → `fallback_classify_uncategorized(bm_anomaly)` → `safe_write_news_json()`
- **범위**: 월별 뉴스 JSON **전체** (당일 기사만이 아님 — dedupe는 기사 간 비교이므로)
- **bm_anomaly 연동**: `load_bm_anomaly_dates(y, m)` 호출 → 실패 시 빈 set으로 graceful degradation
- **리뷰 포인트**: 월 전체 재처리는 월말에 3만건 처리(~2초). 대규모 시 증분 dedupe 필요하지만 현재 규모에서는 허용.

---

## 4. `report/debate_engine.py` — 4인 Debate 컨텍스트

### 기존 수정

#### `_build_shared_context()` 뉴스 로딩 부분 (L177-251)

**변경 1**: primary 필터 추가
```python
# 변경 전
classified = [a for a in articles if a.get('_classified_topics')]

# 변경 후
classified = [a for a in articles if a.get('_classified_topics')]
primary_classified = [a for a in classified if a.get('is_primary', True)]
```
- `is_primary`가 없는 기사(정제 전 데이터)는 `True`로 default → 하위 호환.

**변경 2**: intensity≥7 → intensity≥6 + salience 정렬
```python
# 변경 전
high_impact = [a for a in classified if a.get('intensity', 0) >= 7]
high_impact = sorted(high_impact, key=lambda x: -x.get('intensity', 0))[:10]

# 변경 후
candidates = sorted(
    [a for a in primary_classified if a.get('intensity', 0) >= 6],
    key=lambda x: (-x.get('_event_salience', 0), -x.get('intensity', 0)),
)
```
- intensity 임계치를 7→6으로 낮추되 salience로 품질 필터링. 풀이 넓어지고 순서가 정확해짐.

**변경 3**: diversity guardrail (L199-222)
```python
MAX_PER_TOPIC = 5    # 토픽별 상한
MAX_PER_EVENT = 2    # event_group별 상한
TARGET = 15          # 목표 건수

for a in candidates:
    if len(high_impact) >= TARGET:
        break
    topic = a.get('primary_topic', '')
    egid = a.get('_event_group_id', '')
    if topic_count.get(topic, 0) >= MAX_PER_TOPIC:
        continue
    if egid and event_count.get(egid, 0) >= MAX_PER_EVENT:
        continue
    high_impact.append(a)
```
- **효과**: 3월 기준 토픽 2개→4개 (유가+지정학만 → +AI_반도체+금리)
- **리뷰 포인트**: MAX_PER_TOPIC=5, MAX_PER_EVENT=2가 적절한지? 5건이면 3개 토픽으로 15건 채울 수 있으므로 최소 3개 토픽 보장. event_group 상한 2건은 같은 사건의 중복 보도 방지.

**변경 4**: 교차보도 표시 + 자산영향 집계 (L224-248)
```python
# 교차보도 표시
src_cnt = a.get('_event_source_count', 1)
corr = f', 교차보도:{src_cnt}건' if src_cnt >= 2 else ''
lines.append(f'  [...] ... [sal:{sal}{corr}]')

# 자산영향 집계
asset_agg = defaultdict(float)
for a in primary_classified:
    for k, v in a.get('_asset_impact_vector', {}).items():
        asset_agg[k] += v
```

**변경 5**: evidence_ids 수집 (L178, 236, 251)
```python
evidence_ids = []                       # L178: 초기화
    if aid: evidence_ids.append(aid)    # L236: 주요 뉴스 15건의 ID 수집
context['_evidence_ids'] = evidence_ids  # L251: 컨텍스트에 저장
```

#### `run_market_debate()` 결과에 evidence 포함 (별도 위치)
```python
result = {
    ...
    '_evidence_ids': context.get('_evidence_ids', []),   # ← 신규
}
```

---

## 5. `analyze/graph_rag.py` — GraphRAG 인과 그래프

### 신규 추가

#### `_stratified_sample()` (L434-489)
```python
def _stratified_sample(candidates: list[dict]) -> list[dict]:
```
- **Dynamic cap**: `min(n, max(300, int(n * 0.05)))`, 상한 500
- **Phase 1**: 토픽별 최소 10건 quota (salience 내림차순)
- **Phase 2**: 나머지를 전체 salience 상위로 채움
- **중복 방지**: `_article_id` 기반 set

### 기존 수정

#### `build_insight_graph()` Step 2 (L530 부근)
**변경 전**:
```python
significant = [a for a in articles if a.get('intensity', 0) >= 5]
if not significant:
    significant = articles[:200]
```

**변경 후**:
```python
primary_articles = [a for a in articles if a.get('is_primary', True)]
candidates = [a for a in primary_articles if a.get('intensity', 0) >= 5]
if not candidates:
    candidates = primary_articles[:200]
significant = _stratified_sample(candidates)
```

**변경: salience 가중 엣지** (L493-500)
```python
# 변경 전
weight = 0.3  # 고정

# 변경 후
salience = art.get('_event_salience', 0.3)
base_weight = 0.3 + salience * 0.4   # 범위: 0.3~0.7
```

#### `add_incremental_edges()` (L553 부근)
**변경**: primary 필터 추가
```python
# 변경 전
entity_map = extract_entities_from_news(new_articles)

# 변경 후
primary_new = [a for a in new_articles if a.get('is_primary', True)]
if not primary_new:
    return graph
entity_map = extract_entities_from_news(primary_new)
```
- daily incremental에서는 `_stratified_sample()` 미적용 (일일 기사수가 적으므로 primary 전량 투입).

---

## 6. `analyze/news_vectordb.py` — ChromaDB 벡터 검색

### 기존 수정

#### `build_index()` 메타데이터 확장 (L100-125)
**추가된 메타 필드 7개:**
```python
meta = {
    # 기존 9개 필드...
    # 신규 7개:
    'article_id': a.get('_article_id', ''),
    'primary_topic': primary_topic,
    'intensity': str(a.get('intensity', 0)),
    'direction': a.get('direction', ''),
    'event_salience': str(a.get('_event_salience', 0)),
    'is_primary': str(a.get('is_primary', True)),
    'fallback': str(a.get('_fallback_classified', False)),
}
```
- chromadb 메타는 string만 허용 → `str()` 래핑. 검색 시 `float()` 역변환.
- doc_id를 `_article_id` 우선 사용 (기존 `{month}_{index}` fallback).

#### `search()` hybrid_score (L170-193)
**변경 전**: cosine distance만 반환
**변경 후**: hybrid_score 계산 + 정렬
```python
salience = float(meta.get('event_salience', 0))
hybrid_score = (1.0 - distance) + salience * 0.3

# 반환 필드에 추가:
'article_id': meta.get('article_id', ...),
'primary_topic': meta.get('primary_topic', ''),
'event_salience': salience,
'hybrid_score': round(hybrid_score, 4),

# hybrid_score 내림차순 정렬
articles.sort(key=lambda x: -x['hybrid_score'])
```

#### `search_for_factors()` primary 필터 (L196-227)
**변경 전**: 제목 dedup만
**변경 후**: `is_primary == 'False'` 기사 필터 아웃 + 검색 범위 `top_k*2` → `top_k*3`
```python
for r in results:
    if r.get('is_primary') == 'False':    # ← 신규
        continue
    prefix = r['title'][:40]
    ...
```

---

## 7. `tests/ablation_test.py` — 신규 파일

정제 효과를 LLM 호출 없이 메트릭으로 비교하는 프레임워크.

```bash
python -m market_research.tests.ablation_test --month 2026-03 2026-04
```

4가지 조건 비교:
- `A_baseline`: raw intensity≥7 (정제 전 debate 로직)
- `B_dedupe`: +primary 필터
- `C_salience`: +salience 정렬 상위 15건
- `D_full`: +fallback, 상위 20건

메트릭: pool_size, unique_topics, unique_sources, avg_intensity, avg_salience, corroborated_pct, fallback_count

---

## 검증 결과 (P0 반영 후 2026-03)

| 지표 | 수정 전 | 수정 후 |
|------|--------|--------|
| 평균 salience | 0.293 | **0.410** (+40%) |
| bm_overlap 활성 기사 | 0건 | **7,975건** |
| 교차보도 기사 | ~0건 | **282건** |
| fallback 구제 | 21건 | **216건** |
| debate 토픽 다양성 | 2개 | **4개** |
| source_quality (국내) | 0.3 | **0.7** |
