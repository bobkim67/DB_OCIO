# Taxonomy 개편 + Targeted Relabel + 분류/Primary 규칙 설계

> 작성일: 2026-04-09
> 목적: precision 72.5% → 85%+, topic accuracy 64% → 80%+, primary_pick 58% → 90%+

---

## 1. 신규 Taxonomy (14개 토픽 + 2-layer 구조)

### Layer 1: Financial Filter (분류 전 앞단)

기사가 분류 파이프라인에 들어가기 전에 **거시 금융 관련성**을 판정.
비금융 기사는 `_classified_topics: []`로 처리하되, `_filter_reason`을 기록.

| filter_reason | 설명 | 예시 |
|---------------|------|------|
| `individual_stock` | 개별 종목/ETF/IPO 분석 | 케이뱅크 IPO, LS 부회장 발언 |
| `product_promo` | 자산운용사 상품 소개/브리핑 | 대신자산운용 펀드 출시, 신한투자증권 브리핑 |
| `industry_sector` | 산업/섹터 뉴스 (비거시) | 배터리 시장점유율, 포스코 방위기술 |
| `pure_military` | 순수 군사/전쟁 속보 (금융 언급 없음) | 이란 지상전 경고, 이란 실시간 전황 |
| `pure_politics` | 순수 정치/외교 (시장 영향 없음) | 트럼프 협상 발언, 호주 여론조사 |
| `non_financial` | 스포츠/연예/과학/게임/요리 등 | UFC 도핑, 디스크골프, PyPI 패키지 |

**판정 기준 (순서대로 적용):**
```
1. 제목+설명에 금융 키워드 0개 → non_financial
2. 특정 종목명/ISIN/티커 중심이고 거시 맥락 없음 → individual_stock
3. "펀드 출시", "ETF 소개", "운용사 브리핑" 패턴 → product_promo
4. "시장점유율", "공장 건설", "생산 확대" + 거시 영향 없음 → industry_sector
5. 전쟁/군사 키워드만 있고 가격/시장/경제 키워드 없음 → pure_military
6. 정치/외교 키워드만 있고 가격/시장/경제 키워드 없음 → pure_politics
7. 위 모두 해당 안 됨 → 통과 (Layer 2로)
```

### Layer 2: Topic Classification (14개)

| # | 토픽 | 설명 | 기존 매핑원 |
|---|------|------|-----------|
| 1 | `통화정책` | Fed/ECB/BOJ/BOK 정책결정, 점도표, 기준금리, 중앙은행 발언 | 통화정책, 유럽_ECB |
| 2 | `금리_채권` | 국채 금리, 채권 수익률, 듀레이션, 크레딧 스프레드, 국채 입찰 | 금리, 미국채 |
| 3 | `물가_인플레이션` | CPI, PPI, PCE, 기대 인플레, 임금상승, 생산비 | 물가 |
| 4 | `경기_소비` | GDP, 고용, 실업, 소비자심리, PMI, 소매판매, 경기침체 | **신설** |
| 5 | `유동성_크레딧` | 레포, 크로스커런시 베이시스, TGA, SRF, 담보 가치, 회사채 발행 환경, 자금시장 경색 | 유동성_배관 (좁게 재정의) |
| 6 | `환율_FX` | 원달러, 엔달러, 위안, 루피, DXY, 환율 변동, FX 개입 | 한국_원화, 중국_위안화, 엔화_캐리 |
| 7 | `달러_글로벌유동성` | 유로달러 시스템, 달러 부족/과잉, 글로벌 유동성 사이클, Fed 스왑라인 | 유로달러, 달러 (글로벌 맥락) |
| 8 | `에너지_원자재` | 유가, WTI, Brent, OPEC, 천연가스, 원자재 지수, 에너지 공급망 | 유가_에너지 |
| 9 | `귀금속_금` | 금값, 은값, 귀금속 투자, 안전자산 수요 (금 중심) | 금, 안전자산 |
| 10 | `지정학` | 전쟁의 시장 영향, 제재의 경제 효과, 호르무즈 봉쇄, 에너지 안보 | 지정학 (금융 영향 있는 것만) |
| 11 | `부동산` | 주택가격, 전세, 리츠, 건설경기, 부동산 정책 | 부동산 |
| 12 | `관세_무역` | 관세율, 무역수지, 공급망 재편, 수출입 제한 | 관세 |
| 13 | `크립토` | 비트코인, 이더리움, 스테이블코인, DeFi, 규제 | 비트코인_크립토 |
| 14 | `테크_AI_반도체` | AI 투자, 반도체 수급, 빅테크 실적의 시장 영향 | AI_반도체 |

### 제거된 기존 토픽

| 기존 | 처리 | 이유 |
|------|------|------|
| `한국_원화` | → `환율_FX` | 국가별 분리 불필요, region 태그로 대체 |
| `중국_위안화` | → `환율_FX` | 동일 |
| `엔화_캐리` | → `환율_FX` | 동일 |
| `유럽_ECB` | → `통화정책` (region=EU) | 중앙은행별 분리 불필요 |
| `미국채` | → `금리_채권` | 금리와 통합 |
| `달러` | → `환율_FX` 또는 `달러_글로벌유동성` | 기사 성격별 분기 |
| `유동성_배관` | → `유동성_크레딧` (좁게) | 과용 방지 |
| `유로달러` | → `달러_글로벌유동성` | 통합 |
| `안전자산` | → `귀금속_금` | 금 중심으로 통합 |
| `이민_노동` | → `경기_소비` | 경기 버킷으로 흡수 |
| `저출산_인구` | → `경기_소비` | 동일 |

---

## 2. Old → New 매핑표

### 자동 매핑 (1:1, 코드로 즉시 변환 가능)

| 기존 토픽 | 신규 토픽 | 비고 |
|----------|----------|------|
| `금리` | `금리_채권` | |
| `미국채` | `금리_채권` | |
| `물가` | `물가_인플레이션` | 경기_소비 후보 기사는 relabel 대상 |
| `관세` | `관세_무역` | |
| `유가_에너지` | `에너지_원자재` | |
| `금` | `귀금속_금` | |
| `안전자산` | `귀금속_금` | |
| `비트코인_크립토` | `크립토` | |
| `AI_반도체` | `테크_AI_반도체` | |
| `지정학` | `지정학` | 유지 (금융 영향 있는 것만) |
| `부동산` | `부동산` | 유지 |
| `통화정책` | `통화정책` | 유지 |
| `이민_노동` | `경기_소비` | |
| `저출산_인구` | `경기_소비` | |

### 분기 매핑 (1:N, 기사별 판단 필요 → targeted relabel 대상)

| 기존 토픽 | 신규 후보 | 분기 기준 |
|----------|----------|----------|
| `한국_원화` | `환율_FX` | 환율/FX 기사면 |
| | (비금융) | 개별종목/IPO/운용사 브리핑이면 filter |
| `중국_위안화` | `환율_FX` | 위안/환율 기사면 |
| | (비금융) | 중국 산업/군사/비경제면 filter |
| `달러` | `환율_FX` | 원달러/DXY 등 환율 변동 기사 |
| | `달러_글로벌유동성` | 유로달러 시스템, 글로벌 유동성 기사 |
| `유럽_ECB` | `통화정책` | region=EU 태그 추가 |
| `유동성_배관` | `유동성_크레딧` | 레포/크레딧/자금시장 배관 |
| | `통화정책` | 중앙은행 발언/정책 |
| | `환율_FX` | 환율 관련 |
| | (비금융) | ETF 상품소개/운용사 브리핑 |
| `엔화_캐리` | `환율_FX` | |

---

## 3. Targeted Relabel 범위

### 전량 재라벨 불필요. 아래 조건의 기사만 재처리:

**Phase 1: Financial Filter 적용** (LLM 불필요, rule-based)
```
대상: 분류된 모든 기사 중 아래 패턴
조건:
  - system_primary_topic IN ('한국_원화', '중국_위안화', '유동성_배관')
  - AND 제목에 개별종목명/ETF명/운용사명/IPO 패턴 포함
추정 건수: ~2,000~3,000건 (3월 기준)
```

**Phase 2: 분기 토픽 재분류** (LLM 필요, Haiku)
```
대상:
  A. primary_topic = '한국_원화' → 환율_FX 또는 비금융 (추정 ~1,400건)
  B. primary_topic = '중국_위안화' → 환율_FX 또는 비금융 (추정 ~300건)
  C. primary_topic = '유동성_배관' → 유동성_크레딧/통화정책/환율_FX (추정 ~770건)
  D. primary_topic = '달러' → 환율_FX/달러_글로벌유동성 (추정 ~350건)
  E. primary_topic = '물가' AND 경기/소비 키워드 포함 → 경기_소비 (추정 ~100건)
합계: ~2,920건 × Haiku = ~$0.30
```

**Phase 3: 자동 매핑** (LLM 불필요, 코드 1:1 변환)
```
대상: Phase 2 이외의 나머지 분류 기사 전부
처리: old_topic → new_topic 자동 변환 (매핑표 기준)
비용: $0
```

### 재라벨 하지 않는 것
- 미분류 기사 (`_classified_topics: []`) — 이미 비금융으로 처리됨
- 2025년 데이터 — 분류 자체가 안 되어있으므로 향후 일괄 처리
- 자동 매핑으로 해결되는 토픽 (금리→금리_채권 등)

---

## 4. 분류 규칙

### 4.1 토픽 판정 기준: "시장 영향 자산" 우선

```
원칙: 기사의 primary_topic은 "이 기사가 가장 직접적으로 영향을 미치는 자산/시장"으로 판정한다.
     원인(trigger)이 아니라 결과(impact)를 기준으로 한다.

예시:
  "이란 공격으로 유가 급등" → 에너지_원자재 (지정학이 아님)
  "이란 전쟁이 걸프 페트로달러 체제를 흔든다" → 지정학 (금융 시스템 자체가 주제)
  "소비자심리 급락으로 경기 위축 우려" → 경기_소비 (물가/금리가 아님)
  "ECB 금리 동결 결정" → 통화정책 (금리_채권이 아님)
  "10년물 국채 금리 급등" → 금리_채권
  "원달러 1500원 돌파" → 환율_FX
```

### 4.2 Financial Filter 규칙

```python
# news_classifier.py에 추가할 함수
def is_macro_financial(article: dict) -> tuple[bool, str]:
    """거시 금융 관련성 판정. (True, '') 또는 (False, filter_reason)"""
    title = article.get('title', '').lower()
    desc = article.get('description', '')[:200].lower()
    text = f"{title} {desc}"

    # 금융 키워드 체크
    MACRO_KW = {'금리','환율','증시','채권','유가','인플레','gdp','고용','실업',
                'cpi','fed','ecb','boj','fomc','kospi','s&p','나스닥','원달러',
                'rate','yield','bond','stock market','oil price','inflation',
                'recession','tariff','관세','무역','금값','비트코인'}
    has_macro = any(kw in text for kw in MACRO_KW)

    # 개별종목 패턴 (한국어)
    STOCK_PATTERNS = ['주총','상장','ipo','공모','수주','분기 실적','영업이익',
                      '대표이사','인수합병','m&a','시가총액 돌파','목표가']
    is_stock = any(p in text for p in STOCK_PATTERNS) and not has_macro

    # 상품/운용사 패턴
    PRODUCT_PATTERNS = ['펀드 출시','펀드 선봬','etf 소개','운용사','자산운용',
                        '상품 출시','분배금','환매','수익률 기록']
    is_product = any(p in text for p in PRODUCT_PATTERNS) and not has_macro

    # 산업 패턴 (비거시)
    INDUSTRY_PATTERNS = ['시장점유율','공장 건설','생산라인','재건축','신제품',
                         '출하량','수주잔고']
    is_industry = any(p in text for p in INDUSTRY_PATTERNS) and not has_macro

    # 순수 군사 (금융 언급 없음)
    MILITARY_KW = {'지상전','공습','미사일','폭격','병력','작전','침공','군사'}
    FINANCIAL_KW = {'가격','시장','경제','투자','주가','환율','유가','채권'}
    is_military = any(kw in text for kw in MILITARY_KW) and not any(kw in text for kw in FINANCIAL_KW)

    # 순수 정치
    POLITICS_KW = {'여론조사','지지율','선거','정당','국회','청문회'}
    is_politics = any(kw in text for kw in POLITICS_KW) and not any(kw in text for kw in FINANCIAL_KW)

    if is_stock: return (False, 'individual_stock')
    if is_product: return (False, 'product_promo')
    if is_industry: return (False, 'industry_sector')
    if is_military: return (False, 'pure_military')
    if is_politics: return (False, 'pure_politics')
    if not has_macro: return (False, 'non_financial')
    return (True, '')
```

### 4.3 유동성_크레딧 좁은 정의

```
유동성_크레딧에 해당하는 것:
  - 레포 시장 경색/정상화
  - 크로스커런시 베이시스 변동
  - TGA 잔고 변동
  - SRF/상설 대출 창구 이용
  - 회사채 스프레드 확대/축소
  - CP/CD 금리 이상 변동
  - 자금시장 스트레스 지표 (SOFR-EFFR 스프레드 등)
  - 담보 가치 하락/유동성 위기

유동성_크레딧에 해당하지 않는 것:
  - 중앙은행 기준금리 결정 → 통화정책
  - 환율 변동 → 환율_FX
  - 펀드/ETF 상품 소개 → 비금융 (filter)
  - 한은 총재 발언 → 통화정책
  - 국채 입찰 결과 → 금리_채권
```

---

## 5. Primary Pick 규칙

### 5.1 구조적 원인

현재 문제: **dedup의 title_prefix 40자 매칭이 너무 느슨** → 완전히 다른 기사가 같은 그룹으로 묶임 → non-primary 과다.

증거:
```
dedup_30: "모티브링크, 현대모비스 차세대..." ↔ "씨이랩, GPU 클러스터..."
dedup_70: "이준석·이상일, 보 해체..." ↔ "[부동산 톺아보기] 충남 아파트..."
dedup_183: "키움히어로즈..." ↔ "4명 살리고 떠난 40살 영화감독..."
```

원인: `_title_prefix()` 정규화가 특수문자+공백 제거 후 앞 40자만 비교. 한국어 뉴스에서 `[기자명] ` 같은 prefix가 겹치면 무관한 기사도 매칭.

### 5.2 수정안

```python
# 수정 1: title_prefix 매칭 조건 강화
def dedupe_articles(articles):
    ...
    # 기존: prefix 40자 일치 + 같은 날짜
    # 수정: prefix 40자 일치 + 같은 날짜 + 같은 source
    for date_str, date_indices in by_date.items():
        # 추가: 같은 source 기사만 그룹핑 (다른 source면 event clustering에서 처리)
        by_source = defaultdict(list)
        for idx in date_indices:
            by_source[articles[idx].get('source', '')].append(idx)
        for source_indices in by_source.values():
            if len(source_indices) <= 1:
                continue
            # 이 안에서만 dedup 그룹핑
            ...

# 수정 2: singleton event → is_primary 강제
def cluster_events(articles):
    ...
    # 기존 코드 이후 추가:
    # event_group에 속한 기사가 1건뿐이면 is_primary=True 강제
    event_members = defaultdict(list)
    for i, a in enumerate(articles):
        egid = a.get('_event_group_id', '')
        if egid:
            event_members[egid].append(i)

    for egid, indices in event_members.items():
        if len(indices) == 1:
            articles[indices[0]]['is_primary'] = True
```

### 5.3 Primary 선정 원칙 (명문화)

```
1. dedup_group 내에서 1건만 primary
   - URL 일치 또는 (같은 source + 같은 날짜 + 제목 prefix 40자 일치)
   - primary 기준: wire copy 원본 > 가장 긴 description

2. event_group 내에서는 모든 primary가 유효
   - event_group은 "같은 사건의 다른 보도"이므로 각 보도가 primary
   - event_source_count = 그룹 내 고유 source 수

3. singleton event (event_source_count=1):
   - is_primary=True가 기본
   - dedup에서 False로 된 경우 → event 단계에서 override

4. dedup_group에 속하지만 제목이 실질적으로 다른 경우:
   - SequenceMatcher(제목 전체) < 0.7이면 별도 dedup_group으로 분리
```

---

## 6. 구현 순서 (최소 수정)

### Step 1: Financial Filter 추가 (news_classifier.py)

```python
# classify_batch() 시작 부분에 삽입
for a in articles:
    is_fin, reason = is_macro_financial(a)
    if not is_fin:
        a['_classified_topics'] = []
        a['_filter_reason'] = reason
        a['_is_macro_financial'] = False
    else:
        a['_is_macro_financial'] = True

# LLM 분류는 _is_macro_financial=True인 기사만 대상
to_classify = [a for a in articles if a.get('_is_macro_financial', True)]
```

### Step 2: Taxonomy 매핑 + LLM 프롬프트 변경 (news_classifier.py)

```python
# TOPIC_TAXONOMY 교체
TOPIC_TAXONOMY = [
    '통화정책', '금리_채권', '물가_인플레이션', '경기_소비',
    '유동성_크레딧', '환율_FX', '달러_글로벌유동성',
    '에너지_원자재', '귀금속_금', '지정학',
    '부동산', '관세_무역', '크립토', '테크_AI_반도체',
]

# 매핑 함수
OLD_TO_NEW = {
    '금리': '금리_채권', '미국채': '금리_채권',
    '물가': '물가_인플레이션',
    '관세': '관세_무역',
    '유가_에너지': '에너지_원자재',
    '금': '귀금속_금', '안전자산': '귀금속_금',
    '비트코인_크립토': '크립토',
    'AI_반도체': '테크_AI_반도체',
    '한국_원화': '환율_FX', '중국_위안화': '환율_FX', '엔화_캐리': '환율_FX',
    '유럽_ECB': '통화정책',
    '유로달러': '달러_글로벌유동성',
    '이민_노동': '경기_소비', '저출산_인구': '경기_소비',
    # 유지
    '통화정책': '통화정책', '지정학': '지정학', '부동산': '부동산',
}

def migrate_topic(old_topic: str) -> str:
    return OLD_TO_NEW.get(old_topic, old_topic)
```

### Step 3: Dedup 수정 (core/dedupe.py)

```python
# _title_prefix dedup에 같은 source 조건 추가
# + event 후처리에서 singleton override

# dedupe_articles() 수정:
# 2차 prefix 매칭 시 같은 source만 그룹핑
for prefix, indices in prefix_map.items():
    by_date_source = defaultdict(list)
    for idx in indices:
        key = (articles[idx].get('date', '')[:10], articles[idx].get('source', ''))
        by_date_source[key].append(idx)
    for (date_str, source), ds_indices in by_date_source.items():
        if len(ds_indices) <= 1:
            continue
        # 여기서만 그룹핑

# cluster_events() 끝에 추가:
# singleton event → primary override
for egid, indices in event_members.items():
    primary_count = sum(1 for i in indices if articles[i].get('is_primary'))
    if primary_count == 0 and len(indices) >= 1:
        # 가장 긴 description을 가진 기사를 primary로
        best = max(indices, key=lambda i: len(articles[i].get('description', '')))
        articles[best]['is_primary'] = True
```

### Step 4: 기존 데이터 마이그레이션

```python
# 1회 실행 스크립트
for month_file in NEWS_DIR.glob('2026-*.json'):
    articles = load(month_file)
    for a in articles:
        # Phase 1: Financial filter
        if not is_macro_financial(a):
            a['_classified_topics'] = []
            a['_filter_reason'] = reason

        # Phase 3: 자동 매핑
        for t in a.get('_classified_topics', []):
            t['topic'] = migrate_topic(t['topic'])
        if a.get('primary_topic'):
            a['primary_topic'] = migrate_topic(a['primary_topic'])

        # old_topic 보존
        a['_old_primary_topic'] = a.get('primary_topic', '')

    save(month_file, articles)
```

### Step 5: Phase 2 (분기 토픽) targeted relabel

```python
# 유동성_배관 → 재분류 필요한 기사만 LLM 호출
RELABEL_TARGETS = {'환율_FX'}  # 자동 매핑 후에도 판단이 필요한 것
# 달러: 환율_FX vs 달러_글로벌유동성
# 물가: 물가_인플레이션 vs 경기_소비

for a in articles:
    old = a.get('_old_primary_topic', '')
    new = a.get('primary_topic', '')
    if old in ('달러', '유동성_배관') or (old == '물가' and has_consumption_keywords(a)):
        # LLM 재분류 대상
        relabel_queue.append(a)
```

---

## 7. 전체 흐름 Pseudocode

```
daily_update():
    Step 1: 뉴스 수집
    Step 2: 분류
        for article in batch:
            # Layer 1: Financial Filter (rule-based, LLM 불필요)
            is_fin, reason = is_macro_financial(article)
            if not is_fin:
                article._classified_topics = []
                article._filter_reason = reason
                continue

            # Layer 2: Topic Classification (LLM)
            topics = classify_with_llm(article, TOPIC_TAXONOMY_V2)
            article._classified_topics = sanitize_topics(topics)

    Step 2.5: 정제
        assign_article_ids()
        dedupe_articles()    # 수정: 같은 source만 prefix 매칭
        cluster_events()     # TOPIC_NEIGHBORS 교차
        # singleton override
        for event_group with 0 primaries:
            force_best_as_primary()
        compute_salience_batch(bm_anomaly_dates)
        fallback_classify(keyword_required=True)

    Step 3: GraphRAG (stratified + primary)
    Step 4: MTD delta
    Step 5: regime check
```

---

## 8. TOPIC_ASSET_SENSITIVITY 매핑 변경

```python
TOPIC_ASSET_SENSITIVITY_V2 = {
    '통화정책':         {'국내주식': -0.3, '국내채권': -0.8, ...},  # 기존 금리 + 유럽_ECB 병합
    '금리_채권':        {'국내채권': -0.9, '해외채권': -0.9, ...},  # 기존 금리 + 미국채 병합
    '물가_인플레이션':   {'국내채권': -0.5, ...},                    # 기존 물가
    '경기_소비':        {'국내주식': -0.4, '해외주식': -0.3, ...},  # 신설 — 경기 민감
    '유동성_크레딧':     {'해외채권_USHY': -0.7, ...},              # 기존 유동성_배관 (좁게)
    '환율_FX':          {'환율_USDKRW': -0.8, ...},               # 기존 한국_원화+중국_위안화+엔화 병합
    '달러_글로벌유동성': {'환율_DXY': 0.9, ...},                    # 기존 유로달러+달러 병합
    '에너지_원자재':     {'원자재_원유': 0.8, ...},                 # 기존 유가_에너지
    '귀금속_금':        {'원자재_금': 0.8, ...},                   # 기존 금+안전자산 병합
    '지정학':           {'해외주식': -0.5, ...},                    # 유지
    '부동산':           {'국내주식': 0.2, ...},                    # 유지
    '관세_무역':        {'해외주식': -0.6, ...},                   # 기존 관세
    '크립토':           {},                                        # 자산 영향 약함
    '테크_AI_반도체':   {'미국주식_성장': 0.7, ...},               # 기존 AI_반도체
}
```

---

## 9. 구현 우선순위

| 순서 | 작업 | 비용 | 효과 |
|------|------|------|------|
| 1 | Financial Filter 추가 | $0 | precision 72.5% → ~85% |
| 2 | Dedup prefix 매칭 강화 (같은 source) | $0 | primary_pick 58% → ~85% |
| 3 | Singleton event primary override | $0 | primary_pick → ~90% |
| 4 | TOPIC_TAXONOMY 교체 + 자동 매핑 | $0 | topic accuracy +5~10pp |
| 5 | LLM 프롬프트 변경 (14개 토픽) | $0 | 향후 신규 분류 개선 |
| 6 | Targeted relabel (분기 토픽) | ~$0.30 | topic accuracy 64% → ~80% |
| 7 | TOPIC_ASSET_SENSITIVITY 업데이트 | $0 | salience/GraphRAG 일관성 |

**총 비용: ~$0.30, 총 작업시간: 코드 수정 ~2시간**
