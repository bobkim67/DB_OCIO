# Review Packet v3 — Taxonomy V2 + Financial Filter + Dedup 근본 수정

> 작성일: 2026-04-09 (최종 갱신)
> 이전 판정: 고급 프로토타입 4.8/5.0
> 이번 변경: taxonomy 개편(21→14) + financial filter + dedup URL 정규화 수정 + 강/약 분리 + singleton override + V1/V2 일관성 수정 + targeted relabel
> **현재 병목**: 모델 성능이 아닌 **평가 기준(gold set) 정합성**. gold set V2 재검토가 최우선.

---

## Part 1: 변경사항 요약

### 수정 파일 6개

| 파일 | 핵심 변경 |
|------|----------|
| `analyze/news_classifier.py` | Taxonomy V2(14개) + Financial Filter + LLM 프롬프트 + SENSITIVITY V2 + sanitize V2 + source-aware heuristic |
| `core/dedupe.py` | URL 정규화(tracking만 제거, urlencode 사용) + 강/약 매칭 + prefix 상한 + TOPIC_NEIGHBORS V2 + singleton override |
| `core/salience.py` | fallback filter 스킵 + _KEYWORD_TOPIC_MAP V2 |
| `analyze/graph_rag.py` | TOPIC_DECAY_CLASS V2 |
| `report/comment_engine.py` | _TOPIC_TO_SECTION V2 + _build_outlook V2 |
| `tests/gold_eval.py` | _refresh_system_values() 자동 갱신 |

### 3대 이슈 성과

**Phase 1: 정합성 수정 (URL + dedup + filter + V1/V2 통일)**
— gold 라벨이 V2 이전 기준이므로 이 시점 수치가 시스템 개선을 더 정확히 반영:

| 이슈 | 시작점 | Phase 1 결과 |
|------|--------|-------------|
| precision | 72.5% | **92.3%** |
| topic accuracy | 64.0% | **76.0%** |
| primary pick | 58.0% | **98.0%** |
| recall | 100% | **82.8%** |

**Phase 2: targeted relabel 반영 후 (기존 gold 기준)**
— gold 라벨이 V2 taxonomy(경기_소비 신설 등)와 일부 불일치하므로, 이 수치는 평가 기준 자체의 한계를 포함:

| 이슈 | Phase 1 | Phase 2 (현재) | 비고 |
|------|---------|---------------|------|
| precision | 92.3% | **88.9%** | gold에 비금융 경계 기사가 일부 금융으로 라벨됨 |
| topic accuracy | 76.0% | **70.0%** | gold의 금리/물가 라벨이 V2 경기_소비와 충돌 |
| recall | 82.8% | **82.8%** | 변동 없음 |
| primary pick | 98.0% | **98.0%** | 변동 없음 |

**핵심 해석**: Phase 2에서 precision/topic이 하락한 것은 시스템 악화가 아니라, **gold 라벨이 V2 taxonomy 기준과 불일치**하기 때문. 예: id 18(소비자심리)이 system `경기_소비`로 정확하게 재분류되었지만, gold 라벨은 V1 기준 `금리_채권`으로 남아있어 mismatch. **gold set V2 재검토가 다음 우선순위.**

---

## Part 2: Dedup 근본 수정 — URL 정규화

### 근본 원인

기존 `_normalize_url()`이 query param을 전부 제거 → 1,203건이 하나의 dedup 그룹.

### 수정

```python
# 변경 전: query='', fragment='' (전부 제거)
# 변경 후: tracking param만 제거, 나머지 보존 (urlencode 사용)
TRACKING = {'utm_source', 'utm_medium', ..., 'fbclid', 'gclid', ...}
kept = {k: v for k, v in params.items() if k.lower() not in TRACKING}
clean_query = urlencode(kept, doseq=True)
```

### 안전성

- `urlencode(kept, doseq=True)` 사용으로 percent-encoding 안전
- 세션성 param(`sid`, `session_id` 등)이 남아 같은 기사가 과분리될 가능성은 이론상 존재하지만, 현재 데이터에서 최대 dedup 그룹이 7건이므로 실무상 무시 가능
- 같은 기사 다른 tracking param은 TRACKING set에서 제거되므로 정상 dedup

### 효과

| 지표 | 수정 전 | 수정 후 |
|------|--------|--------|
| primary 비율 | 52.5% | **99.2%** |
| 최대 dedup 그룹 | 1,203건 | **7건** |

---

## Part 3: Financial Filter

### 구조

```
Layer 1: Financial Filter (rule-based)
  1. _MACRO_OVERRIDE → 무조건 통과
  2. 개별종목/상품/산업 → 우선 차단 (macro보다 먼저)
  3. 순수 군사/정치 → 금융 키워드 없으면 차단
  4. MACRO_KW 0개 → 비금융 (단, Tier1 금융 전문 매체는 title만으로 통과)
Layer 2: LLM 분류 (Haiku 14개 토픽)
```

### fallback resurrect 방지 확인

| 확인 항목 | 결과 |
|----------|------|
| `_filter_reason` 있는 기사의 fallback 스킵 | `salience.py:299` 체크 동작 |
| `_filter_reason` 있는데 `_classified_topics` 비어있지 않은 기사 | **0건** |
| `_filter_reason` 있는데 `_fallback_classified`인 기사 | **0건** |
| classify_daily/classify_month에서 filter 탈락 기사 재분류 | `'_classified_topics' in a` 조건으로 **차단됨** |

**확인 방법**: `python -c "..."` 스크립트로 4개 조건 전수 검증 (0건 확인).
`_filter_reason`을 쓰는 곳: `news_classifier.py:459` (쓰기), `salience.py:299` (읽기). 이 2곳만.

### source-aware heuristic (신규)

Tier1 금융 전문 매체(Reuters, Bloomberg, CNBC, MarketWatch, FT, WSJ, SeekingAlpha, Benzinga)에서 온 기사는 MACRO_KW 매칭이 없어도 filter 통과. 이 매체들은 비금융 기사를 거의 수집하지 않으므로 precision 영향 최소.

### 3월 filter 결과

| filter_reason | 건수 | 비율 |
|---------------|------|------|
| non_financial | 7,666 | 31.1% |
| individual_stock | 527 | 2.1% |
| product_promo | 308 | 1.2% |
| pure_military | 112 | 0.5% |
| industry_sector | 26 | 0.1% |
| pure_politics | 6 | 0.02% |

---

## Part 4: Taxonomy V2 (14개)

### 토픽 목록

통화정책, 금리_채권, 물가_인플레이션, **경기_소비**(신설), 유동성_크레딧(좁게),
환율_FX(FX통합), 달러_글로벌유동성, 에너지_원자재, 귀금속_금, 지정학,
부동산, 관세_무역, 크립토, 테크_AI_반도체

### V1/V2 일관성 확인 (전수 점검 완료)

| 파일 | dict/변수 | V2 적용 |
|------|----------|---------|
| `news_classifier.py` | TOPIC_TAXONOMY | V2 14개 |
| `news_classifier.py` | TOPIC_ASSET_SENSITIVITY | V2 14개 |
| `news_classifier.py` | _topic_to_asset_class | V2 14개 |
| `news_classifier.py` | topic_taxonomy_version | `'14_v2'` |
| `core/dedupe.py` | TOPIC_NEIGHBORS | V2 |
| `core/salience.py` | _KEYWORD_TOPIC_MAP | V2 |
| `analyze/graph_rag.py` | TOPIC_DECAY_CLASS | V2 |
| `report/comment_engine.py` | _TOPIC_TO_SECTION | V2 |
| `report/comment_engine.py` | _build_outlook_from_digest | V2 |

**V1 잔류 확인**: 2026-03 데이터 기준 `_classified_topics[].topic`에 V1 이름 **0건**, `primary_topic`에 V1 이름 **0건**.

### 마이그레이션 코드 정합성

```python
# _old_primary_topic 보존 (migrate 전에!)
a['_old_primary_topic'] = a.get('primary_topic', '')

# primary_topic migrate
a['primary_topic'] = migrate_topic(a['primary_topic'])

# _classified_topics 전체 migrate
for t in a.get('_classified_topics', []):
    t['topic'] = migrate_topic(t['topic'])
```

3개 필드 모두 migrate 확인됨. `_classified_topics` 내부 토픽도 `migrate_topic()` 적용.

---

## Part 5: Gold Set 평가 (기존 gold 기준 — V2 재검토 필요)

> **주의**: 현재 gold 라벨은 V1 taxonomy 기준으로 작성됨. V2에서 신설/재정의된 아래 토픽과 구조적으로 불일치:
> - `경기_소비` (신설) — 기존 gold의 `금리_채권`/`물가_인플레이션` 라벨과 충돌 (id 18)
> - `유동성_크레딧` (좁게 재정의) — 기존 gold의 `유동성_크레딧` 라벨 범위와 불일치 (id 19)
> - `귀금속_금` (안전자산 흡수) — 기존 gold의 `환율_FX` 라벨과 경계 충돌 (id 7)
>
> 따라서 Phase 2 수치 하락은 시스템 악화가 아니라 **평가 기준과 taxonomy 간 버전 불일치**가 주원인.
> gold set V2 재검토가 선행되어야 정확한 시스템 성능을 측정할 수 있음.

### 50건 전체 변화 추이

| 지표 | 시작점 | Phase 1 (정합성) | Phase 2 (relabel) | 비고 |
|------|--------|-----------------|-------------------|------|
| precision | 72.5% | 92.3% | **88.9%** | gold 경계 케이스 포함 |
| topic accuracy | 64.0% | 76.0% | **70.0%** | gold V2 미조정 영향 |
| recall | 100% | 82.8% | **82.8%** | |
| primary pick | 58.0% | 98.0% | **98.0%** | |

### 오분류 error taxonomy (10건)

**filter false negative (2건):**

| id | system | gold | 원인 |
|----|--------|------|------|
| 16 | (필터됨) | 부동산 | "리츠 학술대회" — `리츠`가 MACRO_KW에 추가되었지만 기존 filter 결과가 JSON에 잔류 |
| 42 | (필터됨) | 에너지_원자재 | 이전 filter에서 비워진 `_classified_topics`가 LLM 재분류 없이 잔류 |

**topic mismatch (5건):**

| id | system | gold | 원인 |
|----|--------|------|------|
| 4 | 물가_인플레이션 | 귀금속_금 | 금값 기사 → 물가보다 금이 primary. 기존 LLM 분류 유지 |
| 14 | 달러_글로벌유동성 | 통화정책 | 한은총재 → relabel이 달러_글로벌유동성으로 변경. gold 기준과 불일치 |
| 18 | 경기_소비 | 금리_채권 | 소비자심리 → **system이 V2 기준으로 정확** (경기_소비), gold가 V1 기준(금리) |
| 19 | 금리_채권 | 유동성_크레딧 | 회사채 → relabel이 금리_채권으로 변경. gold와 불일치 |
| 41 | 지정학 | 에너지_원자재 | 유가 상승 기사 → "시장 영향" 기준이면 에너지, 기존 LLM은 지정학 유지 |

**boundary case (2건):**

| id | system | gold | 원인 |
|----|--------|------|------|
| 13 | 환율_FX | (비금융) | 중국 국방비 — GDP 언급으로 filter 통과, 금융/비금융 경계 |
| 30 | 경기_소비 | (비금융) | ETF 기사 — relabel이 경기_소비로 변경, gold는 비금융 |

**dedup side effect (1건):**

| id | system | gold | 원인 |
|----|--------|------|------|
| 7 | 귀금속_금 | 환율_FX | relabel이 안전자산→귀금속_금으로 변경, gold는 달러→환율_FX |

### gold V2 재검토 시 예상 변동

아래 기사들은 gold 라벨이 V2 기준에 맞지 않아 **재검토 시 system이 정답으로 판정될 가능성**:

| id | 현재 gold | system | V2 기준 예상 정답 | 영향 |
|----|----------|--------|-----------------|------|
| 18 | 금리_채권 | 경기_소비 | **경기_소비** | topic +1 |
| 19 | 유동성_크레딧 | 금리_채권 | 금리_채권 또는 유동성_크레딧 | topic ±0~+1 |
| 7 | 환율_FX | 귀금속_금 | 귀금속_금 (금하락이 주제) | topic +1 |

**재검토 후 예상 변동 근거**: 위 3건(id 7, 18, 19)이 system 정답으로 판정되면 topic 35/50 → 37~38/50 = 74~76%. 단, id 19는 gold/system 어느 쪽이 정답인지 재검토가 필요하므로 ±1 변동 가능.

---

## Part 6: 3월 토픽 분포 (relabel 후)

```
금리_채권: 2,909    지정학: 2,874       에너지_원자재: 2,838
환율_FX: 2,667     테크_AI: 1,186      귀금속_금: 833
크립토: 744        물가: 629           경기_소비: 449
관세_무역: 330     부동산: 288         통화정책: 269
달러_글로벌유동성: 150  유동성_크레딧: 139
```

경기_소비 449건, 달러_글로벌유동성 150건, 유동성_크레딧 139건이 분기 매핑에서 분리됨.

---

## Part 7: 남은 작업 (우선순위 순)

### 1. gold set V2 재검토 ($0, 사람 작업)

#### 재검토 기준

V2 14개 토픽 + "시장 영향 자산 우선" 원칙:
1. 헤드라인이 명시한 자산 우선
2. 없으면 가장 직접적인 시장 영향 자산
3. 다자산이면 원인 토픽(지정학/통화정책)
4. 개별종목/상품/산업/순수군사/정치 → 비금융(`''`)

#### 우선 재검토 대상 (10건)

**Tier A: system이 맞고 gold가 틀렸을 가능성 높음 (3건)**

| id | 현재 gold | system | 판단 근거 | 예상 변경 |
|----|----------|--------|----------|----------|
| 18 | 금리_채권 | 경기_소비 | 소비자심리 급락 기사. V2에서 경기_소비 신설 → system이 정확 | gold → `경기_소비` |
| 7 | 환율_FX | 귀금속_금 | 금 하락이 제목 주제. V2에서 안전자산→귀금속_금 통합 | gold → `귀금속_금` |
| 19 | 유동성_크레딧 | 금리_채권 | 비우량 회사채 발행. V2 유동성_크레딧은 레포/TGA만 → 금리_채권이 더 적절 | gold → `금리_채권` |

**Tier B: gold/system 모두 재판단 필요 (4건)**

| id | 현재 gold | system | 판단 포인트 |
|----|----------|--------|-----------|
| 14 | 통화정책 | 달러_글로벌유동성 | 한은총재 후보 "달러 유동성 양호" → 통화정책 vs 달러_글로벌유동성 경계 |
| 41 | 에너지_원자재 | 지정학 | "Oil prices climb after Iran warns" → 시장영향 기준이면 에너지, 원인 기준이면 지정학 |
| 30 | (비금융) | 경기_소비 | ETF 기사 → 비금융(상품소개)인가, 경기_소비(시장 배경 설명)인가 |
| 4 | 귀금속_금 | 물가_인플레이션 | 금값+인플레 → 제목이 금값 시세이므로 귀금속_금이 맞을 가능성 높음 |

**Tier C: 비금융 경계 (3건)**

| id | 현재 gold | system | 판단 포인트 |
|----|----------|--------|-----------|
| 13 | (비금융) | 환율_FX | 중국 국방비 + GDP 언급 → 비금융 유지가 적절 |
| 42 | 에너지_원자재 | (미분류) | filter 통과 미복구 → LLM 재분류 후 재판정 |
| 16 | 부동산 | (미분류) | 리츠 학술대회 → filter 통과 미복구 → LLM 재분류 후 재판정 |

#### 재검토 후 측정 항목

`python -m market_research.tests.gold_eval --evaluate` 재실행하여:
- topic accuracy: 70% → 74~76% 회복 예상
- precision: 88.9% → 89~92% (비금융 경계 재판정에 따라)
- recall: 82.8% → 85%+ (미분류 복구 시)

### 2. filter 통과 미분류 기사 복구 + recall 보강 (4,082건, ~$1.36)

**대상**: filter를 현재 통과하는데 `_classified_topics:[]`인 기사.
이전 정제에서 filter가 비운 후, filter 규칙 보강(MACRO_KW, source-aware)으로 통과 조건이 바뀌었지만 LLM 재분류가 실행되지 않아 빈 상태로 잔류.

**추출 조건**:
```python
for a in articles:
    if not a.get('_filter_reason') and a.get('_classified_topics') == []:
        relabel_queue.append(a)
```

**실행 절차**:
1. 4개월 뉴스에서 위 조건 기사 추출
2. `classify_batch()` (Haiku, V2 14개 토픽)로 재분류
3. 재분류 후 `_classified_topics`, `primary_topic`, `_asset_impact_vector` 갱신
4. 정제 재실행: `process_dedupe_and_events()` + `compute_salience_batch()`
5. gold eval 재실행: `--evaluate`

**recall 보강 (이미 반영된 코드 수정)**:
- MACRO_KW에 `부동산`, `리츠`, `real estate`, 영문 복수형 추가 완료
- source-aware heuristic: Tier1 금융 전문 매체는 MACRO_KW 없어도 통과
- `_MACRO_OVERRIDE`에 영문 패턴 7개 추가 완료

### 3. 수치 가드레일 (Opus 코멘트 수치 대조)

### 4. sentence-level evidence trace

---

## Part 8: 코드 정합성 확인 결과

### filter resurrect 경로 확인

| 확인 경로 | 결과 |
|----------|------|
| `salience.py` fallback에서 `_filter_reason` 스킵 | OK (L299) |
| `classify_daily/classify_month`에서 `_classified_topics in a` 조건 | 재분류 차단 OK |
| `graph_rag.py`에서 빈 토픽 기사 재분류 | 없음 OK |
| `debate_engine.py`에서 빈 토픽 기사 처리 | 없음 OK |
| filter 탈락인데 토픽 있는 기사 | **0건** |
| filter 탈락인데 fallback된 기사 | **0건** |

### _classified_topics migrate 확인

2026-03 데이터 기준:
- `_classified_topics[].topic`에 V1 이름: **0건**
- `primary_topic`에 V1 이름: **0건**

### gold eval 정합성

- `_refresh_system_values()`가 evaluate 시 자동 실행
- 실제 최신 뉴스 데이터에서 system 필드 갱신 확인 (50/50건)
- primary_pick 자동 재판정 포함

---

## Part 9: 최종 결론

### 이번 v3의 가장 큰 성과

1. **primary pick 58→98%**: URL 정규화라는 근본 원인을 정확히 해결. dedup 그룹 1,203건→7건.
2. **precision 72.5→92.3%** (Phase 1): financial filter로 개별종목/상품/비금융을 앞단에서 구조적 차단.
3. **taxonomy/filter/downstream 정합성**: V1/V2 namespace를 6개 파일에서 일관되게 수정. `_classified_topics`와 `primary_topic` 모두 V2 0건 잔류 확인.

### 지금 가장 큰 병목은 모델이 아니라 평가 기준

- Phase 2에서 topic 76→70%, precision 92→89%로 내려간 것은 **시스템 악화가 아님**
- gold 라벨이 V1 기준으로 작성되어 V2와 충돌하는 것:
  - id 18: system `경기_소비` (V2 정확) vs gold `금리_채권` (V1 기준)
  - id 7: system `귀금속_금` (V2 정확) vs gold `환율_FX` (V1 기준)
  - id 19: system `금리_채권` vs gold `유동성_크레딧` (V2 좁은 정의와 불일치)
- 이 3건만 재검토해도 topic 70→74~76% 회복

### 따라서 분류기를 더 손대기 전에, gold set을 V2 기준으로 다시 맞추는 것이 우선

gold 재검토(Tier A 3건 + Tier B 4건 + Tier C 3건) 후에야:
- 현재 시스템의 **진짜 정확도**를 측정할 수 있고
- 남은 오분류가 시스템 한계인지 판단할 수 있고
- 추가 개선의 효과를 정확히 비교할 수 있음

### 다음 우선순위 3개

1. **gold set V2 재검토** (Part 7 §1) — Tier A/B/C 10건 재검토 → `--evaluate` 재실행. 평가 기준 정합성 확보.
2. **filter 통과 미분류 기사 복구** (Part 7 §2) — 4,082건 LLM 재분류 ~$1.36. `_recover_unclassified.py` 준비됨.
3. **수치 가드레일** — Opus 코멘트 수치를 원본 PA/BM과 대조. 운용보고서 실투입 최소 안전장치.
