# CLAUDE.md — market_research

## Project Purpose

DB형 퇴직연금 OCIO 운용보고서 자동생성 파이프라인.
블로그/뉴스 수집 → 분류/인과분석 → 4인 LLM debate → 시계열+뉴스 교차 분석 → 펀드별 코멘트 생성.

## Architecture

```
market_research/
├── core/                          ← 공유 인프라 (단일 소스)
│   ├── db.py                      ← DB_CONFIG, get_conn(), parse_blob()
│   ├── benchmarks.py              ← BENCHMARK_MAP(33개), BM_ASSET_CLASS_MAP, BM_SEARCH_QUERIES
│   ├── constants.py               ← FUND_CONFIGS(9개), ANTHROPIC_API_KEY, LLM_MODEL
│   └── json_utils.py              ← LLM JSON 파싱 유틸 (trailing comma, 잘린 JSON 복구)
│
├── collect/                       ← 데이터 수집
│   ├── naver_blog.py              ← monygeek 블로그 크롤러 (Selenium)
│   ├── macro_data.py              ← SCIP/FRED/NY Fed 지표 + Finnhub/NewsAPI 뉴스
│   └── collect_news.bat           ← 월별 배치 (8단계 파이프라인)
│
├── analyze/                       ← 분석 엔진
│   ├── engine.py                  ← 21개 주제 태깅 + 진단 룰 + 패턴 DB
│   ├── news_classifier.py         ← 21주제 + 13키 자산영향도 벡터 (Haiku)
│   ├── graph_rag.py               ← 인과관계 그래프 (시드→Sonnet 추론→BFS 전파)
│   ├── blog_analyst.py            ← monygeek 관점 분석 (eurodollar school)
│   └── news_vectordb.py           ← ChromaDB + sentence-transformers 벡터 검색
│
├── pipeline/                      ← 배치 파이프라인
│   ├── daily_update.py            ← 일일 증분 (뉴스수집→분류→GraphRAG delta→regime)
│   ├── digest_builder.py          ← 블로그 월별 구조화 요약 (18주제, LLM-free)
│   ├── enriched_digest_builder.py ← 블로그 digest ↔ 뉴스 벡터DB 교차검증
│   ├── news_content_pool_builder.py ← 뉴스 클러스터링 + Haiku 요약
│   └── report_cache_builder.py    ← Streamlit 캐시 빌드
│
├── report/                        ← 보고서 생성
│   ├── comment_engine.py          ← BM/PA/프롬프트 빌드 + LLM 코멘트 (Opus/Sonnet)
│   ├── cli.py                     ← 통합 CLI (build/list, 대화형/auto/edit/from-json)
│   ├── debate_engine.py           ← 4인 debate (Bull/Bear/Quant/monygeek → Opus 종합)
│   ├── timeseries_narrator.py     ← 시계열 내러티브 (z-score 세그먼트 + 뉴스 매칭)
│   └── report_service.py          ← 팩터 추출 + UI 오케스트레이션
│
├── data/                          ← .gitignore (뉴스, 벡터DB, 캐시 등)
└── CLAUDE.md
```

## Running

```bash
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

# 일일 업데이트
python -m market_research.pipeline.daily_update

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

# 보고서 생성
from market_research.report.comment_engine import build_report_prompt, load_bm_price_patterns
from market_research.report.timeseries_narrator import build_report_narrative, build_debate_narrative
from market_research.report.debate_engine import run_market_debate
```

## Pipeline Flow

```
[수집] collect/macro_data.py → data/news/{YYYY-MM}.json, data/macro/indicators.csv
       collect/naver_blog.py → data/monygeek/posts.json

[분류] analyze/news_classifier.py → 21주제 태깅 + 13키 자산영향도
       analyze/news_vectordb.py → ChromaDB 인덱스

[분석] analyze/engine.py → 패턴 DB + 진단 룰
       analyze/graph_rag.py → 인과 그래프 (data/insight_graph/)
       analyze/blog_analyst.py → 블로거 관점 (data/blog_insight/)
       pipeline/enriched_digest_builder.py → 교차검증 digest

[보고] report/debate_engine.py → 4인 debate → customer_comment
       report/timeseries_narrator.py → BM 시계열 + 뉴스 매칭 내러티브
       report/comment_engine.py → 프롬프트 빌드 → LLM 코멘트
       report/cli.py → 대화형/자동/수정 모드 오케스트레이션
```

## LLM 비용

| 단계 | 모델 | 비용/건 |
|------|------|---------|
| 뉴스 분류 | Haiku | ~$0.01 |
| 뉴스 요약 | Haiku | ~$0.01 |
| 인과추론 | Sonnet | ~$0.05 |
| Debate (4인) | Haiku×4 | ~$0.04 |
| Debate 종합 | Opus | ~$0.15 |
| 코멘트 생성 | Sonnet | ~$0.22 |

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
