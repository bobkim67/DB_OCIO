# Architecture Memo — 3-Tier Runtime Boundary

> 2026-04-13 확정. 이 문서는 "어디까지 외부 배치이고 어디부터 Streamlit admin인지"를 한눈에 보여주는 메모.

---

## 한 줄 원칙

**무거운 전처리는 external `market_research`, debate 실행/검수/승인은 Streamlit admin, client는 approved final만 조회.**

---

## Tier 1: 외부 배치 (`market_research`)

**실행 환경**: CLI / cron / 수동 배치
**진입점**: `daily_update.py`, `cli.py build --prepare`

| 단계 | 파일 | 산출물 |
|------|------|--------|
| 매크로 지표 수집 | `collect/macro_data.py` | `data/macro/indicators.csv` |
| 뉴스 수집 | `collect/macro_data.py` | `data/news/{YYYY-MM}.json` |
| 블로그 수집 | `collect/naver_blog.py` | `data/monygeek/posts.json` |
| 뉴스 분류 | `analyze/news_classifier.py` | (JSON 내 `_classified_topics`) |
| 정제 | `core/dedupe.py`, `core/salience.py` | (JSON 내 `_event_salience` 등) |
| GraphRAG | `analyze/graph_rag.py` | `data/insight_graph/{YYYY-MM}.json` |
| vectorDB | `analyze/news_vectordb.py` | `data/news_vectordb/` |
| timeseries narrative | `report/timeseries_narrator.py` | (debate 입력용) |
| debate input package | `report/cli.py --prepare` | `data/report_output/{period}/{fund}.input.json` |
| PA 캐시 | `pipeline/report_cache_builder.py` | `data/report_cache/{period}/{fund}.json` |

**Streamlit에서 절대 실행하지 않는 것**: 뉴스 수집, 분류, 정제, GraphRAG, vectorDB 빌드, bm_anomaly 계산

---

## Tier 2: Streamlit Admin (`tabs/admin.py`)

**실행 환경**: Streamlit 앱 (admin 역할)
**진입점**: `tabs/admin.py::render(ctx)`

| 동작 | 트리거 | 저장 |
|------|--------|------|
| debate 실행 | "Debate 실행" 버튼 | `{fund}.draft.json` |
| 후처리 (sanitize) | debate 직후 자동 | draft 내 `validation_summary` |
| evidence annotations | debate 직후 자동 | draft 내 `evidence_annotations` |
| 결과 검토 | admin 화면 표시 | — |
| 코멘트 수정 | textarea → "Draft 저장" | draft 갱신 (status=edited) |
| 최종 승인 | "최종 승인" 버튼 | `{fund}.final.json` (status=approved) |
| 승인 해제 | "승인 해제" 버튼 | final 삭제, draft status=edited |

**debate 실행은 service wrapper 경유**: `_run_debate_and_save()` → `debate_engine.run_market_debate()` → `report_store.save_draft()`

**admin이 보는 것**: draft comment, admin summary, 합의/쟁점/테일리스크, evidence quality, warning severity, 출처 상세, evidence quality 누적 추적

---

## Tier 3: Client (`tabs/report.py`)

**실행 환경**: Streamlit 앱 (일반 사용자)
**진입점**: `tabs/report.py::render_macro()`

| 보이는 것 | 보이지 않는 것 |
|-----------|---------------|
| final_comment (승인 코멘트) | draft_comment |
| 생성일/승인일 | admin_summary |
| 합의 요약, 테일리스크 | disagreements (쟁점 상세) |
| 참고 뉴스 (제목/출처) | validation_summary |
| 관련 지표 차트 | evidence_quality |
| — | sanitize_warnings |
| — | token_usage, cost |

**데이터 소스**: `report_store.load_final()` → `{fund}.final.json`

---

## 저장 구조

```
market_research/data/report_output/
├── 2026-Q1/
│   ├── 07G04.input.json    ← Tier 1 (외부 배치)
│   ├── 07G04.draft.json    ← Tier 2 (admin debate)
│   └── 07G04.final.json    ← Tier 2→3 (승인 → client 조회)
├── 2026-04/
│   ├── 08P22.input.json
│   ├── 08P22.draft.json
│   └── 08P22.final.json
└── _evidence_quality.jsonl  ← 누적 evidence 추적
```

**상태 전이**: `not_generated` → `draft_generated` → `edited` → `approved`

---

## IO Contract

상세 스키마: `docs/io_contract.md`

| 파일 | 생성 주체 | 소비 주체 |
|------|-----------|-----------|
| `.input.json` | 외부 배치 | Streamlit admin |
| `.draft.json` | Streamlit admin | Streamlit admin |
| `.final.json` | Streamlit admin | Client |

---

## 금지 사항

1. Streamlit 안에서 뉴스 수집/분류/GraphRAG 실행
2. Streamlit 안에서 bm_anomaly / salience / fallback classify 실행
3. Client 화면에 draft/warning/evidence raw output 노출
4. `report_store.py` 우회하여 직접 JSON 저장/로딩
