# market_research

> 최종 갱신: 2026-04-10

## Purpose

`market_research/` — DB형 퇴직연금 OCIO 운용보고서 자동생성 파이프라인.
뉴스/블로그 수집 → 분류 → 정제(dedupe/salience) → GraphRAG → vectorDB → 4인 debate → 코멘트 생성.

6개 레이어:

1. 데이터 수집 (뉴스 3소스 + 블로그 + 매크로 지표)
2. LLM 분류 (Haiku, 14개 토픽)
3. 정제 (dedupe + event clustering + salience + fallback)
4. 분석 (GraphRAG TKG + vectorDB hybrid search)
5. 보고서 생성 (4인 debate + 코멘트 엔진)
6. Streamlit 캐시 연동 (JSON 읽기 전용)

## Directory Layout

```text
market_research/
├── CLAUDE.md                          ← 파이프라인 상세 스펙
├── __init__.py
├── core/                              ← 공유 인프라
│   ├── db.py                          ← DB_CONFIG, get_conn(), parse_blob()
│   ├── benchmarks.py                  ← BENCHMARK_MAP(33개), BM_ASSET_CLASS_MAP
│   ├── constants.py                   ← FUND_CONFIGS(9개), ANTHROPIC_API_KEY
│   ├── json_utils.py                  ← LLM JSON 파싱 + safe_read/write_news_json
│   ├── dedupe.py                      ← article_id + 중복제거 + event clustering
│   └── salience.py                    ← salience 점수 + fallback 분류
├── collect/                           ← 데이터 수집
│   ├── macro_data.py                  ← SCIP/FRED/NYFed/ECOS 지표 + Finnhub/네이버 뉴스
│   ├── naver_blog.py                  ← monygeek 블로그 크롤러 (Selenium)
│   └── collect_news.bat               ← 월별 배치
├── analyze/                           ← 분석 엔진
│   ├── engine.py                      ← 21개 주제 태깅 + 진단 룰
│   ├── news_classifier.py             ← 14토픽 + 13키 자산영향도 (Haiku)
│   ├── graph_rag.py                   ← stratified sampling + Self-Regulating TKG
│   ├── blog_analyst.py                ← monygeek 관점 분석
│   └── news_vectordb.py              ← ChromaDB + hybrid_score 검색
├── pipeline/                          ← 배치 파이프라인
│   ├── daily_update.py                ← 일일 증분 (6단계)
│   ├── digest_builder.py              ← 블로그 월별 구조화 요약
│   ├── enriched_digest_builder.py     ← 블로그↔뉴스 교차검증
│   ├── news_content_pool_builder.py   ← 뉴스 클러스터링 + Haiku 요약
│   └── report_cache_builder.py        ← Streamlit 캐시 빌드
├── report/                            ← 보고서 생성
│   ├── comment_engine.py              ← BM/PA/프롬프트 + LLM 코멘트
│   ├── cli.py                         ← 통합 CLI (build/list/edit)
│   ├── debate_engine.py               ← 4인 debate + diversity guardrail
│   ├── timeseries_narrator.py         ← BM 시계열 + 뉴스 매칭
│   ├── report_service.py              ← 팩터 추출 + UI 오케스트레이션
│   ├── evidence_trace.py              ← [ref:N] evidence 파싱
│   └── numeric_guard.py               ← 수치 가드레일
├── tests/
│   └── ablation_test.py               ← 정제 효과 비교
├── docs/                              ← 설계/리뷰 문서
├── data/                              ← .gitignore 대상
│   ├── macro/                         ← indicators.csv, indicators.json
│   ├── news/                          ← {YYYY-MM}.json
│   ├── news_vectordb/                 ← ChromaDB
│   ├── monygeek/                      ← posts.json, monthly_digests/
│   └── report_cache/                  ← catalog.json, {YYYY-MM}/{fund}.json
└── output/                            ← 로그
```

## Main Components

### `collect/macro_data.py`

- Finnhub/네이버 금융 뉴스 수집 (NewsAPI는 약관 이슈로 보류)
- SCIP/FRED/NY Fed/ECOS 매크로 지표 수집
- 월별 뉴스 JSON + indicators.csv 출력

### `collect/naver_blog.py`

- monygeek 블로그 증분 스크래핑 (Selenium)
- `posts.json`, `log_nos.json` 유지

### `analyze/news_classifier.py`

- Haiku 기반 14개 토픽 분류 + 13키 자산영향도 벡터
- 날짜×자산군 상위 50건 필터 (중복 70% 절감)

### `core/dedupe.py` + `core/salience.py`

- article_id(MD5) + 중복제거 + TOPIC_NEIGHBORS 교차 event clustering
- salience = source_quality(0.3) + intensity(0.25) + corroboration(0.25) + bm_overlap(0.2)
- fallback 분류 (미분류 기사 키워드 기반 복구)

### `analyze/graph_rag.py`

- stratified sampling (300~500건) → 엔티티 추출(Haiku) → 인과추론(Sonnet)
- Self-Regulating TKG (decay/merge/prune/seed)

### `analyze/news_vectordb.py`

- ChromaDB + multilingual 임베딩
- hybrid_score = cosine + salience × 0.3

### `report/debate_engine.py`

- 4인 debate (Bull/Bear/Quant/monygeek) → Opus 종합
- diversity guardrail (토픽5/이벤트2)
- evidence_ids 추적

### `report/comment_engine.py`

- BM/PA/digest → LLM 프롬프트 빌드 + 코멘트 생성
- 8개 펀드: A포맷(08P22,08N81,08N33,07G02,07G03), C포맷(07G04), D포맷(2JM23,4JM12)

### `report/cli.py`

- 통합 CLI: `build` (대화형/auto), `list`, `edit`, `from-json`

### `pipeline/report_cache_builder.py`

- Streamlit 캐시 빌드
- `data/report_cache/catalog.json` + `{YYYY-MM}/{fund_code}.json`

## Dashboard Integration

- `tabs/report.py` — cache JSON 읽기 전용 (market_research 런타임 import 없음)
- `tabs/macro.py` — SCIP 벤치마크 수익률 표시 (market_research import 없음)

## Automation

- 일일 배치: `python -m market_research.pipeline.daily_update`
- 월별 배치: `market_research/collect/collect_news.bat`
- 시작 프로그램: Windows Startup shortcut → `collect_news.bat`

## Known Gaps

- 2025년 12개월 뉴스 데이터 미분류 (19,000건)
- evidence `[ref:N]` Opus 태깅 재검증 필요
- NewsAPI 무료 플랜 약관 위반 가능성 → 대체 소스 미구현
- GraphRAG 누적 폭발 — rolling window 리서치 필요
