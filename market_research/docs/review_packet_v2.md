# Review Packet v2 — Upstream Refinement 재리뷰용

> 작성일: 2026-04-09
> 목적: 1차 리뷰 이후 변경사항 + 실제 코드 diff + 샘플 출력 기반 재평가 요청
> 1차 리뷰 판정: "고급 프로토타입 / 4.5점"
> 1차 P0: LLM 출력 validation, 정답 기반 eval, multilingual 임베딩

---

## Part 1: 변경사항 요약

### 이번 세션에서 수정된 파일 7개 + 신규 2개

| 파일 | +lines | -lines | 핵심 변경 |
|------|--------|--------|----------|
| `core/dedupe.py` | +195 | -84 | article_id 부여 + TOPIC_NEIGHBORS 8그룹 + 교차토픽 event clustering + 불용어 50개 필터 |
| `core/salience.py` | +235 | -13 | `load_bm_anomaly_dates()`(z>1.5, 7일캡) + 3단계 source(TIER1/2/3) + `fallback_classify()` |
| `pipeline/daily_update.py` | +84 | -0 | Step 2.5 `_step_refine()` 삽입 (정제 오케스트레이션) |
| `analyze/graph_rag.py` | +94 | -13 | `_stratified_sample()` + primary 필터 + salience 가중 엣지 + monthly TKG 추가 + daily transmission_paths 추가 |
| `analyze/news_vectordb.py` | +32 | -7 | 분류 메타 7필드 저장 + hybrid_score(cosine+sal×0.3) + primary 필터 |
| `analyze/news_classifier.py` | +78 | -31 | `_sanitize_topic()` whitelist 검증 + `_TOPIC_ALIAS` 수동 매핑 |
| `report/debate_engine.py` | +60 | -9 | primary 필터 + salience 정렬 + diversity guardrail(토픽5/이벤트2) + evidence_ids + 자산영향집계 |
| `tests/ablation_test.py` | 신규 | | 정제 효과 비교 프레임워크 (4조건 × 메트릭) |
| `docs/*.md` | 신규 | | 설계 리뷰 + 변경사항 + 냉정한 평가 3종 |

### 1차 리뷰 이후 추가 수정 (P0 반영)

| 이슈 | 수정 내용 | 검증 결과 |
|------|----------|----------|
| bm_anomaly 60% 과도 | 상위 7일 캡 | 60.5% → **32.9%** |
| 국내 source 저평가 | 3단계 TIER1(1.0)/TIER2(0.7)/TIER3(0.3), 국내 매체 18개 추가 | 매일경제 0.3→0.7 |
| topic-locked clustering | TOPIC_NEIGHBORS 8그룹 + 교차 Jaccard 0.20 상향 | 교차보도 0→252건 |
| debate 토픽 쏠림 | diversity guardrail (토픽5/이벤트2) | 토픽 2→4개 |
| 깨진 토픽명 방치 | `_sanitize_topic()` whitelist + alias + prefix 매칭 | **0건** (50건 정리 완료) |
| fallback precision 45% | `is_market_relevant()` 키워드 필수 조건 | FP 완전 차단 |
| GraphRAG monthly/daily 불일치 | monthly에 TKG decay/prune 추가, daily에 transmission_paths 추가 | 양쪽 일관 |

---

## Part 2: 실제 코드 Diff (핵심 부분)

### 2.1 `core/dedupe.py` — article_id + TOPIC_NEIGHBORS

```diff
+# 신규: 안정적 article ID
+def _make_article_id(article: dict) -> str:
+    key = f"{article.get('title', '')}|{article.get('date', '')[:10]}|{article.get('source', '')}"
+    return hashlib.md5(key.encode('utf-8')).hexdigest()[:12]
+
+def assign_article_ids(articles: list[dict]) -> list[dict]:
+    for a in articles:
+        if '_article_id' not in a:
+            a['_article_id'] = _make_article_id(a)
+    return articles
```

```diff
+# 신규: 불용어 필터 (cross-topic 오클러스터 방지)
+_STOPWORDS = {
+    'the', 'is', 'at', 'in', 'on', 'of', 'to', 'for', 'and', 'or', 'as',
+    'by', 'an', 'it', 'its', 'be', 'are', 'was', 'has', 'have', 'had',
+    'this', 'that', 'with', 'from', 'not', 'but', 'can', 'all', 'will',
+    'more', 'how', 'what', 'when', 'who', 'why', 'new', 'says', 'could',
+    'after', 'over', 'into', 'than', 'about', 'just', 'out', 'been', 'here',
+}
```

```diff
+# 신규: 인접 토픽 그룹
+TOPIC_NEIGHBORS = {}
+for _group in [
+    {'금리', '통화정책', '미국채'},
+    {'물가', '금리'},
+    {'달러', '한국_원화', '엔화_캐리', '중국_위안화'},
+    {'유가_에너지', '지정학'},
+    {'관세', '지정학'},
+    {'AI_반도체', '미국증시'},
+    {'안전자산', '금'},
+    {'유로달러', '유동성_배관'},
+]:
+    for _t in _group:
+        TOPIC_NEIGHBORS.setdefault(_t, set()).update(_group - {_t})
```

```diff
 # cluster_events() 핵심 변경
-    for topic in topics:
-        for d1 in dates_sorted:
-            indices_1 = bucket.get((d1, topic), [])
+    for topic in topics:
+        compare_topics = {topic} | TOPIC_NEIGHBORS.get(topic, set())
+        for d1 in dates_sorted:
+            indices_1 = bucket.get((d1, topic), [])
             ...
-                indices_2 = bucket.get((d2, topic), [])
+                for t2 in compare_topics:
+                    indices_2 = bucket.get((d2, t2), [])
+                    is_cross_topic = (topic != t2)
+                    ...
+                    _compare_and_merge(..., jaccard_threshold=0.20 if is_cross_topic else 0.15)
```

### 2.2 `core/salience.py` — bm_anomaly + 3단계 source + fallback

```diff
+def load_bm_anomaly_dates(year, month, threshold_z=1.5) -> set:
+    """핵심 6개 BM의 5일수익률/20일vol z-score > threshold인 날짜."""
+    core_bms = ['S&P500', 'KOSPI', 'Gold', 'DXY', 'USDKRW', '미국종합채권']
+    ...
+    # 상위 7일 캡 (고변동 월 signal 희석 방지)
+    MAX_ANOMALY_DAYS = 7
+    if len(date_max_z) > MAX_ANOMALY_DAYS:
+        top_dates = sorted(date_max_z.keys(), key=lambda d: -date_max_z[d])[:MAX_ANOMALY_DAYS]
+        return set(top_dates)
```

```diff
-# 이전: 이진 source_quality
-TRUSTED_SOURCES = {'Reuters', 'Bloomberg', ...}
-source_quality = 1.0 if source in TRUSTED_SOURCES else 0.3

+# 변경: 3단계
+TIER1_SOURCES = {'Reuters', 'Bloomberg', ..., '연합뉴스', '뉴시스', '뉴스1'}
+TIER2_SOURCES = {'SeekingAlpha', ..., '매일경제', '한국경제', ..., '조선비즈', ...}
+if source in TIER1_SOURCES:
+    source_quality = 1.0
+elif source in TIER2_SOURCES:
+    source_quality = 0.7
+else:
+    source_quality = 0.3
```

```diff
+def is_market_relevant(article, bm_anomaly_dates=None) -> bool:
+    """키워드 필수 + 다른 조건 1개 이상."""
+    has_keyword = any(kw.lower() in title_lower for kw in MACRO_KEYWORDS)
+    kw_score = title_keyword_score(article)
+    if not has_keyword and kw_score < 0.5:
+        return False  # 키워드 없으면 즉시 탈락 (Netflix/학자금 차단)
+    other_conditions = [Tier1|2 소스, BM anomaly일, event_source>=2]
+    return sum(other_conditions) >= 1
```

### 2.3 `analyze/news_classifier.py` — 토픽 whitelist 검증

```diff
+_TOPIC_ALIAS = {
+    '관제': '관세', '달Dollar': '달러', '달dollar': '달러',
+    '금융': '금리', '금융안정': '금리', '금융위기': '금리',
+    '재정': '통화정책', '에너지': '유가_에너지', '원자재': '금',
+    '위험선호': '안전자산',
+}
+
+def _sanitize_topic(raw_topic: str) -> str:
+    """정확일치 → alias → prefix 매칭 → '' (제거)"""
+    if raw_topic in _TOPIC_SET: return raw_topic
+    if raw_topic in _TOPIC_ALIAS: return _TOPIC_ALIAS[raw_topic]
+    # 가장 긴 공통 prefix 매칭 (한글 2자, 영문 3자 최소)
+    ...

 def classify_batch(articles):
     ...
-    topics = item.get('topics', [])
+    raw_topics = item.get('topics', [])
+    topics = []
+    for t in raw_topics:
+        sanitized = _sanitize_topic(t.get('topic', ''))
+        if sanitized:
+            t['topic'] = sanitized
+            topics.append(t)
```

### 2.4 `analyze/graph_rag.py` — stratified + monthly/daily 일관성

```diff
+def _stratified_sample(candidates):
+    """dynamic cap min(n, max(300, n*5%)), 상한500 + 토픽별 10건 quota"""
+    ...

 def build_insight_graph(year, month, include_news=True):
-    significant = [a for a in articles if a.get('intensity', 0) >= 5]
-    if not significant: significant = articles[:200]
+    primary_articles = [a for a in articles if a.get('is_primary', True)]
+    candidates = [a for a in primary_articles if a.get('intensity', 0) >= 5]
+    significant = _stratified_sample(candidates)

+    # 신규: monthly에도 TKG decay/prune 적용
+    decay_existing(graph, _date(year, month, 1).isoformat())
+    recompute_scores(graph)
+    prune_graph(graph)

 def add_incremental_edges(year, month, new_articles):
+    primary_new = [a for a in new_articles if a.get('is_primary', True)]
     ...
+    # 신규: daily에서도 transmission_paths 갱신
+    graph['transmission_paths'] = precompute_transmission_paths(graph)
```

### 2.5 `report/debate_engine.py` — diversity guardrail

```diff
-high_impact = [a for a in classified if a.get('intensity', 0) >= 7]
-high_impact = sorted(high_impact, key=lambda x: -x.get('intensity', 0))[:10]

+primary_classified = [a for a in classified if a.get('is_primary', True)]
+candidates = sorted(
+    [a for a in primary_classified if a.get('intensity', 0) >= 6],
+    key=lambda x: (-x.get('_event_salience', 0), -x.get('intensity', 0)))
+MAX_PER_TOPIC = 5
+MAX_PER_EVENT = 2
+TARGET = 15
+for a in candidates:
+    if len(high_impact) >= TARGET: break
+    if topic_count.get(topic, 0) >= MAX_PER_TOPIC: continue
+    if egid and event_count.get(egid, 0) >= MAX_PER_EVENT: continue
+    high_impact.append(a)
```

---

## Part 3: 샘플 출력

### 3.1 정제된 기사 1건 (전체 필드)

```json
{
  "title": "Oil prices extend gains as Trump threatens to escalate Mideast war, Iran targets Kuwaiti tanker",
  "date": "2026-03-31",
  "source": "CNBC",
  "_article_id": "b07523c195c0",
  "_dedup_group_id": "dedup_1294",
  "is_primary": true,
  "_event_group_id": "event_871",
  "_event_source_count": 57,
  "_event_salience": 0.775,
  "_classified_topics": [
    {"topic": "유가_에너지", "direction": "positive", "intensity": 8},
    {"topic": "지정학", "direction": "negative", "intensity": 9}
  ],
  "_asset_impact_vector": {
    "국내채권": -0.34, "해외주식": 0.3, "해외채권": -0.51,
    "해외채권_USIG": -0.35, "해외채권_EM": 0.39,
    "미국주식_성장": 0.3, "미국주식_가치": 0.52, "원자재_금": -0.55
  },
  "_asset_relevance": {
    "국내주식": 0.45, "해외주식": 0.54, "해외채권_EM": 0.63,
    "미국주식_성장": 0.54, "원자재_금": 0.63, "원자재_원유": 0.72,
    "환율_USDKRW": 0.45, "환율_DXY": 0.36
  },
  "primary_topic": "지정학",
  "direction": "negative",
  "intensity": 9
}
```

**해석**: CNBC 기사, Tier1 소스(1.0), 57개 소스에서 교차보도(event_871), BM anomaly일 해당 → salience 0.775. 지정학+유가 복합 토픽, 원유 관련도 0.72 최고.

### 3.2 Debate 출력 (2026-03)

```
에이전트 stance: bull=bullish, bear=bearish, quant=bearish, monygeek=bearish

evidence_ids: 15건 ['b07523c195c0', 'c2715118960e', '0ff41e6f0792', ...]

합의점:
- 중동 지정학 리스크(이란 분쟁 5주차)와 유가 $108 돌파가 최대 변동성 원천
- 금(Gold) -12.2% 급락은 전통적 안전자산 기능의 이례적 훼손
- 원화 약세(USDKRW +4.4%)와 달러 강세가 이중 부담

고객 코멘트 (앞 400자):
"3월 시장은 중동 지정학 리스크의 장기화와 유가 급등이 글로벌 자산 전반에 걸쳐
동시다발적 스트레스를 가한 한 달이었습니다. 이란 분쟁이 5주차에 접어들며 지정학
관련 뉴스가 전체의 32%를 차지하였고, WTI 유가가 108달러를 돌파하면서 에너지
공급망 교란이 광범위하게 확산되었습니다. ..."
```

### 3.3 정제 통계 (2026-03)

```
전체: 27,482건
분류완료: 24,736건 (90%)
Primary: 12,665건 (중복제거율 54%)
교차보도(source>=2): 252건
깨진 토픽: 0건

Salience 분포:
  mean=0.374, median=0.340, p90=0.540, max=0.975

BM anomaly: 7일 (상위 z-score 캡)
anomaly-hit: 32.9%

토픽 분포 (primary 기준):
  지정학: 17.8%  유가: 13.7%  AI: 13.4%  환율: 11.4%
  금리: 9.1%  유동성: 6.1%  크립토: 5.6%  물가: 4.5%

GraphRAG: 503 노드, 625 엣지, 24 전이경로
```

---

## Part 4: 1차 리뷰의 냉정한 평가 결과 (요약)

### 판정: 고급 프로토타입 / 4.5점

### 강점 3개
1. 정제 메타가 downstream 전체(GraphRAG/vectorDB/debate)에 실제 반영되는 배선 구조
2. GraphRAG stratified sampling — 토픽 다양성 233% 개선, 비용 $8/월 통제
3. 4인 debate + Priority Anchor + diversity guardrail

### 취약점 3개
1. ~~LLM 출력 validation 없음~~ → **`_sanitize_topic()` 구현 완료, 깨진 토픽 0건** (수치 대조는 미구현)
2. 네이버 89% SPOF + 영어 전용 임베딩 → **미해결**
3. ~~테스트 0건~~ → ablation_test.py 추가 (분포 비교), 정답 기반 regression test는 **미구현**

### Known Issues (여전히 남은 것)
- 수치 가드레일: Opus 코멘트 수치를 원본과 대조하는 post-processing 없음
- 임베딩 모델: 영어 전용 `all-MiniLM-L6-v2` (기사 89%가 한국어)
- 정답 기반 eval: 정확도 측정을 위한 라벨링된 테스트셋 없음
- evidence trace: 입력 수준(15건 article_id) 까지만, 문장↔기사 매핑 없음
- 비용 추적: comment_engine만 부분 구현, classifier/GraphRAG 미추적
- 2025년 12개월 데이터 미분류

---

## Part 5: 재리뷰 요청 포인트

1차 리뷰 이후 아래를 수정했습니다. 이 수정이 "문서상 개선"을 넘어 "실제 품질 개선"으로 인정될 수 있는지 평가해주세요:

1. **토픽 whitelist 검증** — `_sanitize_topic()`으로 깨진 토픽 50건 전부 복구, 향후 분류 시 자동 차단. 이것이 "LLM 출력 validation P0"의 토픽 부분을 닫는다고 볼 수 있는가?

2. **bm_anomaly 7일 캡** — 60.5%→32.9% 축소. 이것이 salience signal 희석 문제를 충분히 해소했는가, 아니면 여전히 과도한가?

3. **fallback 키워드 필수** — precision 45%→FP 0건. 3월은 fallback 0건(미분류가 순수 비금융), 4월은 55건. 이것이 적절한 precision/recall 균형인가?

4. **GraphRAG monthly/daily 일관성** — monthly에 TKG decay/prune 추가, daily에 transmission_paths 추가. 1차 리뷰에서 P1이었던 이 항목이 해소되었다고 볼 수 있는가?

5. **cross-topic event clustering** — 불용어 50개 필터 + Jaccard 0.20 상향. 오클러스터 1건(event_2479: CBA배당+IMF위안화)이 불용어 필터 후 재현되는지? (the/for/to 공통어가 필터됨)

6. **전체 성숙도** — 이 수정들 반영 후 "고급 프로토타입 4.5점"에서 변동이 있는가?
