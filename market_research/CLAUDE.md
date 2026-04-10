# CLAUDE.md — market_research

## Project Purpose

DB형 퇴직연금 OCIO 운용보고서 자동생성 파이프라인.
블로그/뉴스 수집 → 분류 → 정제(dedupe/salience) → 인과분석(GraphRAG) → 4인 LLM debate → 시계열+뉴스 교차 분석 → 펀드별 코멘트 생성.

## Architecture

```
market_research/
├── core/                          ← 공유 인프라 (단일 소스)
│   ├── db.py                      ← DB_CONFIG, get_conn(), parse_blob()
│   ├── benchmarks.py              ← BENCHMARK_MAP(33개), BM_ASSET_CLASS_MAP, BM_SEARCH_QUERIES
│   ├── constants.py               ← FUND_CONFIGS(9개), ANTHROPIC_API_KEY, LLM_MODEL
│   ├── json_utils.py              ← LLM JSON 파싱 유틸 + safe_read/write_news_json
│   ├── dedupe.py                  ← article_id + 중복제거 + event clustering (TOPIC_NEIGHBORS)
│   └── salience.py                ← event_salience + asset_relevance + fallback 분류 + bm_anomaly
│
├── collect/                       ← 데이터 수집
│   ├── naver_blog.py              ← monygeek 블로그 크롤러 (Selenium)
│   ├── macro_data.py              ← SCIP/FRED/NY Fed 지표 + Finnhub/NewsAPI/네이버 뉴스
│   └── collect_news.bat           ← 월별 배치 (8단계 파이프라인)
│
├── analyze/                       ← 분석 엔진
│   ├── engine.py                  ← 21개 주제 태깅 + 진단 룰 + 패턴 DB
│   ├── news_classifier.py         ← 21주제 + 13키 자산영향도 벡터 (Haiku)
│   ├── graph_rag.py               ← 인과관계 그래프 (stratified sampling + Self-Regulating TKG)
│   ├── blog_analyst.py            ← monygeek 관점 분석 (eurodollar school)
│   └── news_vectordb.py           ← ChromaDB + hybrid_score(cosine+salience) 검색
│
├── pipeline/                      ← 배치 파이프라인
│   ├── daily_update.py            ← 일일 증분 (수집→분류→정제→GraphRAG→regime)
│   ├── digest_builder.py          ← 블로그 월별 구조화 요약 (18주제, LLM-free)
│   ├── enriched_digest_builder.py ← 블로그 digest ↔ 뉴스 벡터DB 교차검증
│   ├── news_content_pool_builder.py ← 뉴스 클러스터링 + Haiku 요약
│   └── report_cache_builder.py    ← Streamlit 캐시 빌드
│
├── report/                        ← 보고서 생성
│   ├── comment_engine.py          ← BM/PA/프롬프트 빌드 + LLM 코멘트 (Opus/Sonnet)
│   ├── cli.py                     ← 통합 CLI (build/list, 대화형/auto/edit/from-json)
│   ├── debate_engine.py           ← 4인 debate + diversity guardrail + evidence 추적
│   ├── timeseries_narrator.py     ← 시계열 내러티브 (z-score 세그먼트 + 뉴스 매칭)
│   └── report_service.py          ← 팩터 추출 + UI 오케스트레이션
│
├── tests/                         ← 테스트
│   └── ablation_test.py           ← 정제 효과 비교 (4조건 × 메트릭)
│
├── docs/                          ← 설계 문서
│   ├── upstream_refinement_review.md  ← 전체 정제 레이어 설계 리뷰
│   ├── changeset_review.md            ← 파일별 변경사항 (리뷰용)
│   └── cold_assessment.md             ← 냉정한 파이프라인 평가
│
├── data/                          ← .gitignore (뉴스, 벡터DB, 캐시 등)
└── CLAUDE.md
```

## Running

```bash
# 일일 배치 (매크로+뉴스+분류+정제+GraphRAG+regime)
python -m market_research.pipeline.daily_update
python -m market_research.pipeline.daily_update 2026-04-09
python -m market_research.pipeline.daily_update --dry-run  # 수집/분류/정제만

# 통합 CLI (대화형)
python -m market_research.report.cli build

# 자동 모드
python -m market_research.report.cli build 07G04 -q 1 -y 2026

# FX 분리 + 수정 모드
python -m market_research.report.cli build 07G04 -q 1 --fx-split --edit

# 캐시 목록
python -m market_research.report.cli list

# 시계열 내러티브 단독 테스트
python -m market_research.report.timeseries_narrator debate -y 2026 -m 3

# 월별 분류 단독
python -m market_research.analyze.news_classifier 2026-04

# vectorDB 리빌드
python -m market_research.analyze.news_vectordb 2026-04

# GraphRAG 리빌드
python -m market_research.analyze.graph_rag 2026-04

# ablation test
python -m market_research.tests.ablation_test --month 2026-03 2026-04

# 월별 배치
market_research/collect/collect_news.bat
```

## Core Imports

```python
# DB 접속
from market_research.core.db import get_conn, parse_blob

# BM 매핑
from market_research.core.benchmarks import BENCHMARK_MAP, BM_ASSET_CLASS_MAP

# 펀드 설정
from market_research.core.constants import FUND_CONFIGS, ANTHROPIC_API_KEY

# 정제 레이어
from market_research.core.dedupe import process_dedupe_and_events, TOPIC_NEIGHBORS
from market_research.core.salience import (
    compute_salience_batch, fallback_classify_uncategorized,
    load_bm_anomaly_dates, TIER1_SOURCES, TIER2_SOURCES)

# 보고서 생성
from market_research.report.comment_engine import build_report_prompt, load_bm_price_patterns
from market_research.report.timeseries_narrator import build_report_narrative, build_debate_narrative
from market_research.report.debate_engine import run_market_debate
```

## Pipeline Flow

```
[수집]  collect/macro_data.py → data/news/{YYYY-MM}.json, data/macro/indicators.csv
        collect/naver_blog.py → data/monygeek/posts.json

[분류]  analyze/news_classifier.py → 21주제 태깅 + 13키 자산영향도 (Haiku)

[정제]  core/dedupe.py → article_id + dedup_group + event_group (TOPIC_NEIGHBORS 교차)
        core/salience.py → event_salience(bm_anomaly+3단계source+corroboration)
                         → asset_relevance + fallback_classify (키워드 필수)
        ※ pipeline/daily_update.py Step 2.5에서 월별 전체 기사 대상 실행

[분석]  analyze/graph_rag.py → stratified sample(300~500건) → 엔티티 추출(Haiku)
                              → 인과추론(Sonnet) → salience 가중 엣지 → Self-Regulating TKG
        analyze/news_vectordb.py → ChromaDB (hybrid_score = cosine + salience*0.3)
        analyze/blog_analyst.py → 블로거 관점 (eurodollar school)

[보고]  report/debate_engine.py → primary필터 + diversity guardrail(토픽5/이벤트2)
                                → 4인 debate → Opus 종합 → evidence_ids 추적
        report/timeseries_narrator.py → BM 시계열 + 뉴스 매칭 내러티브
        report/comment_engine.py → 프롬프트 빌드 → LLM 코멘트
        report/cli.py → 대화형/자동/수정 모드 오케스트레이션
```

## daily_update Step 구조

```
Step 0: 매크로 지표 수집 (SCIP/FRED/NYFed/ECOS)
Step 1: 뉴스 수집 (네이버 금융 + Finnhub)
Step 2: 뉴스 분류 (Haiku, 21개 주제)
Step 2.5: 정제 — _step_refine(month_str)
  └ load_bm_anomaly_dates(y, m) → z>1.5, 상위 7일 캡
  └ process_dedupe_and_events(articles) → article_id + dedup + event cluster
  └ compute_salience_batch(articles, bm_anomaly) → 3단계 source + bm_overlap
  └ fallback_classify_uncategorized(articles, bm_anomaly) → 키워드 필수
  └ safe_write_news_json() → 월별 JSON 덮어쓰기
Step 3: GraphRAG 증분 (primary 기사 → 엔티티/인과 → TKG decay/merge/prune)
Step 4: MTD 델타 요약 (LLM 불필요, 토픽 카운트 집계)
Step 5: regime_memory 업데이트 (shift 감지 3일 연속)
```

## Upstream Refinement Layer (2026-04-09, V2 taxonomy)

### 성능 (gold 50건 기준, 기존 gold V1 라벨 기준)

| 지표 | 시작 | 최종 |
|------|------|------|
| precision | 72.5% | **90.3%** |
| topic accuracy | 64% | **84.0%** |
| recall | 100% | **96.6%** |
| primary pick | 58% | **98.0%** |

> gold V2 재검토 + 미분류 복구 + 가드레일 연동 + evidence trace + 리빌드 완료.
> **다음: evidence [ref:N] 재검증 → 2025 분류.**

### 기사 1건의 라이프사이클 (생성 필드)

```
[수집] → {title, date, source, description, url}
[분류] → +{_classified_topics, _asset_impact_vector, primary_topic, direction, intensity}
[정제]
  assign_article_ids  → +{_article_id} (MD5 12자 hex, title+date+source)
  dedupe_articles     → +{_dedup_group_id, is_primary}
  cluster_events      → +{_event_group_id, _event_source_count}
  compute_salience    → +{_event_salience, _asset_relevance}
  fallback_classify   → (미분류만) +{_classified_topics, _fallback_classified, ...}
```

### Salience 공식

```
score = 0.30 × source_quality   (TIER1=1.0 / TIER2=0.7 / TIER3=0.3)
      + 0.25 × intensity_norm   (intensity/10, 0~1)
      + 0.25 × corroboration    (event_source_count/5, cap 1.0)
      + 0.20 × bm_overlap       (BM z>1.5 상위 7일 해당이면 1.0)
```

### Source Quality 3단계

| Tier | Score | 매체 |
|------|-------|------|
| TIER1 | 1.0 | Reuters, Bloomberg, AP, FT, WSJ, CNBC, MarketWatch, 연합뉴스, 뉴시스, 뉴스1 |
| TIER2 | 0.7 | SeekingAlpha, Benzinga, 매일경제, 한경, 서울경제, 머니투데이, 이데일리, 조선비즈 등 25개 |
| TIER3 | 0.3 | 네이버검색(미파싱), 블로그, 기타 |

### TOPIC_NEIGHBORS (V2 교차 토픽 event clustering)

```
금리_채권 ↔ 통화정책
물가_인플레이션 ↔ 금리_채권 ↔ 경기_소비
환율_FX ↔ 달러_글로벌유동성
에너지_원자재 ↔ 지정학
관세_무역 ↔ 지정학
테크_AI_반도체 ↔ 경기_소비
귀금속_금 ↔ 지정학
달러_글로벌유동성 ↔ 유동성_크레딧
```

### GraphRAG Stratified Sampling

```python
# dynamic cap
cap = min(n, max(300, int(n * 0.05)))  # 상한 500
# Phase 1: 토픽별 최소 10건 quota
# Phase 2: 나머지 salience 상위로 채움
```

### Debate Diversity Guardrail

```
MAX_PER_TOPIC = 5    # 토픽별 상한
MAX_PER_EVENT = 2    # event_group별 상한
TARGET = 15          # 주요 뉴스 목표 건수
```

## LLM 비용

| 단계 | 모델 | 비용/건 | 월간 추정 |
|------|------|---------|----------|
| 뉴스 분류 | Haiku | ~$0.01 | $80~110 |
| GraphRAG 엔티티 추출 | Haiku | ~$0.01 | $3~5 |
| GraphRAG 인과추론 | Sonnet | ~$0.05 | $1~3 |
| Debate (4인) | Haiku×4 | ~$0.04/set | $0.04 |
| Debate 종합 | Opus×2 | ~$0.30/set | $0.30 |
| 코멘트 생성 | Sonnet | ~$0.22 | $0.22 |
| **월간 합계** | | | **$85~120** |

## 9개 운용 펀드

| 펀드 | BM | 채권전략 | 금 | 특징 |
|------|-----|---------|-----|------|
| 08P22 | 목표 5% | 불렛 | O | 종합채권+은행채 |
| 08N81 | 목표 8% | 듀레이션확대 | O | 10년+30년스트립, HY |
| 08N33 | 목표 6% | 불렛 | O | 10년국고 중심, TMF+HY |
| 07G04 | 복합 | 바벨 | X | 모펀드(07G02+07G03), 미국채→국내채 전환 |
| 07G02 | DT BM1 | 바벨 | X | 인컴추구 서브, 미국채→국내채 전환 |
| 07G03 | DT BM1 | 바벨 | X | 수익추구 서브, 미국채→국내채 전환 |
| 2JM23 | 절대수익 | 불렛 | O | 글로벌자산배분, 나스닥+S&P Growth |
| 4JM12 | 복합 | 바벨 | O | 금광주, 달러선물 |
| 08K88 | 복합 | 바벨(최소) | X | 공격적, 채권~8%, BM초과 목표 |
