# CLAUDE.md — market_research

## Project Purpose

DB형 퇴직연금 OCIO 운용보고서 자동생성 파이프라인.
외부 배치로 debate 이전 단계까지 수행 (수집→분류→정제→GraphRAG→input package).
Debate 실행과 검수/승인은 Streamlit Admin에서 수행. Client는 approved final만 조회.

### Runtime Boundary

```
[이 패키지가 담당]                        [Streamlit이 담당]
 뉴스 수집/분류/정제/GraphRAG               debate 실행 트리거
 timeseries narrative                       결과 검토/수정/승인
 debate input package 생성                  evidence/warning 표시
 report_cache 빌드                          approved final 조회
```

- `report/report_store.py` → draft/final 저장·로딩·상태 관리
- `docs/io_contract.md` → input/draft/final 스키마 정의

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
│   ├── engine.py                  ← 주제 태깅 + 진단 룰 + 패턴 DB
│   ├── news_classifier.py         ← TOPIC_TAXONOMY (14) + 자산영향도 벡터 (Haiku)
│   ├── graph_rag.py               ← 인과 그래프 + transmission path P0/P1
│   ├── graph_vocab.py             ← ★v12 DRIVER/ASSET taxonomy + alias dict
│   ├── blog_analyst.py            ← monygeek 관점 분석 (eurodollar school)
│   └── news_vectordb.py           ← ChromaDB + hybrid_score(cosine+salience) 검색
│
├── pipeline/                      ← 배치 파이프라인
│   ├── daily_update.py            ← Step 0~5 + Step 2.6 (base wiki) ★v10+
│   ├── digest_builder.py          ← 블로그 월별 구조화 요약 (18주제, LLM-free)
│   ├── enriched_digest_builder.py ← 블로그 digest ↔ 뉴스 벡터DB 교차검증
│   ├── news_content_pool_builder.py ← 뉴스 클러스터링 + Haiku 요약
│   └── report_cache_builder.py    ← Streamlit 캐시 빌드
│
├── report/                        ← 보고서 생성
│   ├── comment_engine.py          ← BM/PA/프롬프트 빌드 + LLM 코멘트 (Opus/Sonnet)
│   ├── cli.py                     ← 통합 CLI (build/list, 대화형/auto/edit/from-json)
│   ├── debate_engine.py           ← 4인 debate + regime READ-ONLY (★v10: write 제거)
│   ├── debate_service.py          ← draft 저장 + 06_Debate_Memory/ 페이지 생성
│   ├── fund_comment_service.py    ← 펀드 코멘트 생성 (시장 debate + PA + 보유/거래)
│   ├── timeseries_narrator.py     ← 시계열 내러티브 (z-score 세그먼트 + 뉴스 매칭)
│   ├── report_service.py          ← 팩터 추출 + UI 오케스트레이션
│   ├── report_store.py            ← draft/final 저장·로딩·상태 관리 (IO contract 구현)
│   ├── numeric_guard.py           ← 수치 대조 (키워드 1순위 + abs>50 fallback)
│   └── evidence_trace.py          ← [ref:N] 파싱 + article_id 매핑
│
├── wiki/                          ← ★v10+ canonical/draft wiki writer
│   ├── paths.py                   ← 디렉토리 상수 (market_research/data/wiki/)
│   ├── canonical.py               ← regime canonical writer + normalize (daily_update only)
│   ├── debate_memory.py           ← 06_Debate_Memory/ writer (debate_engine only)
│   ├── draft_pages.py             ← 01~04 base pages + entity graph linking
│   ├── graph_evidence.py          ← 07_Graph_Evidence/ draft + summary
│   └── taxonomy.py                ← ★v11 exact taxonomy contract + PHRASE_ALIAS + trace
│
├── tools/                         ← 운영 도구
│   └── migrate_regime_v11.py      ← regime_memory + wiki 페이지 taxonomy 재정규화
│
├── tests/                         ← 테스트
│   ├── ablation_test.py
│   ├── test_taxonomy_contract.py  ← ★v11 3 cases (exact / phrase reject / empty fallback)
│   ├── test_regime_decision_v12.py ← ★v12 4 cases (false positive/negative 방어)
│   └── test_graphrag_p0_vs_p1.py  ← ★v12 P0 vs P1 비교 리포트
│
├── docs/                          ← 설계 문서
│   ├── io_contract.md                  ← input/draft/final 스키마
│   ├── graphrag_transmission_paths_review.md  ← Phase 2/3 진단·설계
│   ├── entity_page_redesign.md         ← ★v11 entity page 전면 redesign 설계
│   ├── review_packet_v6~v12_1.md       ← 배치별 리뷰 패킷
│   ├── pilot_checklist.md              ← 파일럿 체크리스트 13항목
│   └── cold_assessment.md              ← 파이프라인 평가
│
├── data/                          ← .gitignore
│   ├── news/, monygeek/, insight_graph/, macro/, blog_insight/
│   ├── regime_memory.json          (★machine SSOT — daily_update만 write)
│   ├── report_output/
│   │   ├── {period}/{fund}.(input|draft|final).json
│   │   ├── _evidence_quality.jsonl
│   │   ├── _regime_quality.jsonl              ★v10+ regime 판정 품질
│   │   ├── _transmission_path_quality.jsonl   ★v11+ P0/P1 phase 기록
│   │   ├── _transmission_path_quality_monthly.json ★v12
│   │   ├── _taxonomy_remap_trace.jsonl        ★v12 alias/unresolved trace
│   │   └── _migration_v11_summary.json
│   └── wiki/                       ★v10+ canonical/draft 2-tier (paths.py 참조)
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

# ★v11+ taxonomy contract 테스트
python -m market_research.tests.test_taxonomy_contract

# ★v12 regime 판정식 테스트 (4 cases)
python -m market_research.tests.test_regime_decision_v12

# ★v12 GraphRAG P0 vs P1 비교 리포트
python -m market_research.tests.test_graphrag_p0_vs_p1 2026-04

# ★v11 regime migration (taxonomy 재정규화 + trace 수집)
python -m market_research.tools.migrate_regime_v11
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

# Wiki canonical/draft writers (v10+)
from market_research.wiki.canonical import (
    update_canonical_regime, normalize_regime_memory,
)
from market_research.wiki.debate_memory import write_debate_memory_page
from market_research.wiki.draft_pages import refresh_base_pages_after_refine
from market_research.wiki.graph_evidence import (
    write_transmission_paths_draft, write_transmission_paths_summary,
)

# Taxonomy contract (v11+)
from market_research.wiki.taxonomy import (
    TOPIC_TAXONOMY, TAXONOMY_SET, PHRASE_ALIAS,
    extract_taxonomy_tags, validate_tags, write_remap_trace,
)

# Graph P1 vocab (v12+)
from market_research.analyze.graph_vocab import (
    DRIVER_TAXONOMY, ASSET_TAXONOMY,
    TRIGGER_ALIAS, TARGET_ALIAS,
    aliases_for_trigger, aliases_for_target,
)
```

## Pipeline Flow (v12.1 최신)

```
[수집]  collect/macro_data.py → data/news/{YYYY-MM}.json, data/macro/indicators.csv
        collect/naver_blog.py → data/monygeek/posts.json

[분류]  analyze/news_classifier.py → TOPIC_TAXONOMY(14개) 태깅 + 자산영향도 (Haiku)

[정제]  core/dedupe.py → article_id + dedup_group + event_group (TOPIC_NEIGHBORS 교차)
        core/salience.py → event_salience(bm_anomaly+3단계source+corroboration)
                         → asset_relevance + fallback_classify (키워드 필수)
        ※ pipeline/daily_update.py Step 2.5 월별 전체 기사 대상

[base wiki]  wiki/draft_pages.py → 01_Events + 02_Entities(media + graph nodes)
                                  + 03_Assets + 04_Funds + index
             ※ Step 2.6, canonical regime/debate narrative 포함 금지

[분석]  analyze/graph_rag.py → stratified sample → 엔티티/인과 → Self-Regulating TKG
                              → precompute_transmission_paths(phase='P1')
                                 = dynamic trigger/target + alias dict + embed fallback
        analyze/news_vectordb.py → ChromaDB (hybrid_score)
        analyze/blog_analyst.py → 블로거 관점

[graph evidence] wiki/graph_evidence.py → 07_Graph_Evidence/
                     transmission_paths_{period}_draft.md + transmission_paths_summary.md
                     + _transmission_path_quality_monthly.json
                 ※ canonical 승격 금지 (Phase 4+)

[regime]  pipeline/daily_update.py Step 5: _step_regime_check (canonical writer 단일)
          → normalize_regime_memory() → exact taxonomy contract 강제
          → multi-rule 판정식 (coverage_current / coverage_today=core_top3 / sentiment_flip)
             중 ≥2 만족 + sparse fallback
          → consecutive 3일 + cooldown 14일 → shift_confirmed
          → update_canonical_regime() → 05_Regime_Canonical/*.md 재생성
          → _regime_quality.jsonl append

[보고]  report/debate_engine.py → primary필터 + diversity guardrail(토픽5/이벤트2)
                                → 4인 debate → Opus 종합 → evidence_ids 추적
                                → regime_memory.json READ-ONLY (write 제거, v10+)
        report/debate_service.py → sanitize + save_draft
                                → write_debate_memory_page() → 06_Debate_Memory/
        report/timeseries_narrator.py → BM 시계열 + 뉴스 매칭 내러티브
        report/comment_engine.py → 프롬프트 빌드 → LLM 코멘트
        report/cli.py → 대화형/자동/수정 모드 오케스트레이션
```

## daily_update Step 구조 (v12.1)

```
Step 0: 매크로 지표 수집 (SCIP/FRED/NYFed/ECOS)
Step 1: 뉴스 수집 (네이버 금융 + Finnhub + NewsAPI)
Step 1.5/1.6: 블로그 수집 + 인사이트 빌드 (Haiku 인과분석)
Step 2: 뉴스 분류 (Haiku, TOPIC_TAXONOMY 14주제)
Step 2.5: 정제 — _step_refine(month_str)
  └ load_bm_anomaly_dates(y, m) → z>1.5, 상위 7일 캡
  └ process_dedupe_and_events(articles) → article_id + dedup + event cluster
  └ compute_salience_batch(articles, bm_anomaly) → 3단계 source + bm_overlap
  └ fallback_classify_uncategorized(articles, bm_anomaly) → 키워드 필수
  └ safe_write_news_json() → 월별 JSON 덮어쓰기
Step 2.6: Base wiki pages (★v10+)
  └ refresh_base_pages_after_refine(month_str)
  └ 01_Events (top salience events) + 02_Entities (media + graph 상위 노드)
     + 03_Assets + 04_Funds + 00_Index
  └ regime/debate narrative / transmission path 포함 금지
Step 3: GraphRAG 증분 + transmission path P1 (★v12)
  └ add_incremental_edges → TKG decay/merge/recompute/prune
  └ precompute_transmission_paths(phase='P1')
     = _select_dynamic_triggers + _select_dynamic_targets + alias 루프 + embed fallback
  └ write_transmission_paths_draft + write_transmission_paths_summary
Step 4: MTD 델타 요약 (LLM 불필요, 토픽 카운트 집계)
Step 5: regime canonical writer (★v10+ 단일 writer)
  └ normalize_regime_memory → taxonomy contract 강제
  └ multi-rule 판정식 (coverage_current / coverage_today(core_top3) / sentiment_flip)
     + sparse fallback (0개 hold, 1개 flip 필수)
  └ consecutive 3일 + cooldown 14일 → shift_confirmed
  └ update_canonical_regime → 05_Regime_Canonical/*.md
  └ _regime_quality.jsonl append (decision_mode=multi_rule_v12, tag_match_mode=exact_taxonomy)
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
