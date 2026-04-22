# Naver Research — Phase 2 Adapter + Thin Integration

> **상태**: Phase 2 adapter 구현 완료 + 검증 실행. daily_update thin-wire 연결 완료.
> **작성일**: 2026-04-21
> **브랜치**: `main` (orphan reset 후 HEAD `bb252a0` 기준)
> **선행**: Phase 1 공식 종료 — 4,772건 YTD backfill 완료 (naver_research_phase1.md §2.7)
> **본 배치 범위**: adapter 모듈 + classify_daily 얇은 merge + daily_update Step 1.3 추가 + 검증 3종

---

## 1. 배치 목표 (지침 §1)

1. `naver_research` raw record → **article-like dict** 변환
2. `daily_update.py`에 **Step 1.3 얇은 wrapper** 추가 (기존 Step 수정 최소)
3. research-specific quality heuristic을 **최소 수준**으로 부착

명시적 제외: debate_engine 수정, GraphRAG 구조 변경, vectorDB 구조 변경, PDF 파싱, Streamlit UI, raw storage refactor.

---

## 2. 수정/생성 파일

| 파일 | 상태 | 용도 |
|---|---|---|
| `market_research/collect/naver_research_adapter.py` | **신규** | 변환 + heuristic + IO |
| `market_research/analyze/news_classifier.py::classify_daily` | 수정 | news + adapted 2 소스 merge (저장은 분리 유지) |
| `market_research/pipeline/daily_update.py` | 수정 | `Step 1.3: Naver Research adapter` 5~10라인 추가 + `_step_naver_research_adapter` helper |
| `market_research/tests/test_naver_research_adapter.py` | **신규** | 유닛 테스트 17개 |
| `market_research/docs/naver_research_phase2.md` | **신규** | 본 문서 |

raw storage `data/naver_research/raw/` 구조 **불변**. 신규 adapted 저장 경로:
- `data/naver_research/adapted/{YYYY-MM}.json` — **월별 단일 파일**, 5 카테고리 union

---

## 3. 스키마 매핑 (raw → article-like)

### 3.1 raw record (Phase 1 collector v0.2.0 출력)

```
{title, date, broker, broker_source, category, nid, dedupe_key,
 detail_url, summary_html, summary_text, summary_char_len, summary_selector,
 has_pdf, pdf_url, pdf_path, pdf_bytes, pdf_download_error,
 views, list_page, collected_at, date_raw,
 source_type: "naver_research",
 collector_version: "0.2.0",
 _warnings: [...]}
```

### 3.2 article-like (기존 뉴스 파이프라인 호환)

| 필드 | 출처 | 비고 |
|---|---|---|
| `title` | raw.title | 그대로 |
| `date` | raw.date | YYYY-MM-DD |
| `source` | raw.broker if raw.broker else raw.category | **broker 우선, 없으면 category fallback** |
| `url` | raw.detail_url | |
| `description` | raw.summary_text | 기존 뉴스의 description 자리 |
| `source_type` | 고정 `"naver_research"` | downstream이 구분 가능 |
| `_raw_category` | raw.category | 예: `economy / market_info / invest / industry / debenture` |
| `_raw_nid` | raw.nid | |
| `_raw_dedupe_key` | raw.dedupe_key | 예: `economy:13247` |
| `_raw_has_pdf` | raw.has_pdf | |
| `_raw_pdf_bytes` | raw.pdf_bytes | quality heuristic용 |
| `_raw_summary_char_len` | raw.summary_char_len | quality heuristic용 |
| `_raw_broker` | raw.broker | |
| `_raw_broker_source` | raw.broker_source | list / detail / missing |
| `_raw_warnings` | raw._warnings | heuristic에서 참조 후 보존 |
| `_research_quality_band` | heuristic 산출 | `TIER1 / TIER2 / TIER3` |
| `_research_quality_score` | band 매핑 | 1.0 / 0.7 / 0.3 |
| `_adapter_flags` | heuristic 산출 | `category_tier1 / pdf_rich / short_summary / …` |

**핵심 원칙**: raw record는 덮어쓰지 않는다. `_raw_*` 접두사로 보존 계층을 분리해 Phase 3 GraphRAG / vectorDB / Phase 4 debate에서도 무손실 참조 가능.

---

## 4. Quality Heuristic

plan_naver_research.md §9 초안을 최소 수준으로 구현.

### 4.1 규칙 (apply_research_quality_heuristic)

```
band = TIER2 (default)
if category in {economy, debenture, industry}:
    band = TIER1
    flag += "category_tier1"
elif category in {market_info, invest}:
    band = TIER2
    flag += "category_tier2"

if has_pdf and pdf_bytes > 200_000:
    flag += "pdf_rich"
    if band == TIER2: band = TIER1     # 본문 충실한 리포트면 tier up

if summary_char_len < 120:             # 강제 강등 (최우선)
    band = TIER3
    flag += "short_summary"

if raw_warnings ∩ {detail_no_summary_block, summary_too_short, empty_summary}:
    flag += "raw_warning_downgrade"
    band = one step down (TIER1→2, TIER2→3)

if raw_warnings ∩ {broker_missing}:
    flag += "missing_broker"
    if band == TIER1: band = TIER2      # 소폭 하향

# flag 추가: has_pdf / empty_description

score = {TIER1: 1.0, TIER2: 0.7, TIER3: 0.3}[band]
```

### 4.2 근거

- **리서치 ≠ 무조건 TIER1 금지** (plan §9) — 이번 adapter는 `market_info / invest`를 TIER2 기본.
- **PDF 충실도는 승격 근거** — `pdf_bytes > 200KB`는 본문이 구조화된 리포트 신호. industry/debenture의 차트·표 리포트도 PDF 경유로 회수 가능 (Phase 1 close waiver §7.3 참조).
- **summary_char_len < 120은 TIER3 강제 강등** — 어떤 카테고리든 본문 부실하면 tier up 불가.
- **raw warning은 버리지 않는다** — 이후 Phase 3 vectorDB / Phase 4 debate에서 재참조 가능하도록 `_raw_warnings`로 보존.

### 4.3 heuristic 튜닝 로깅 포인트 (P1)

- `TIER3 비율 > 10%`면 `summary_char_len` 임계(120)가 너무 높은지 재검토
- `TIER1 비율 > 90%`면 과도 승격 — `pdf_rich` 임계(200KB) 상향 검토
- `raw_warning_downgrade` 비율 > 10%이면 collector selector 개선 우선순위

---

## 5. daily_update.py 편입 방식

기존 Step 구조를 유지하며 **두 지점만 변경**:

### 5.1 Step 1.3 신규 추가 (기존 Step 수정 X)

```python
# Step 1.3: Naver Research adapter (raw → article-like)
nr_adapt_result = _step_naver_research_adapter(month_str)
result['steps']['naver_research_adapter'] = nr_adapt_result
```

`_step_naver_research_adapter(month)`가 수행:
1. `build_naver_research_articles(month)` — raw 5 카테고리 union → article-like 변환
2. `save_adapted(month, articles)` — `adapted/{month}.json` 저장
3. band 분포 return (관찰용)

### 5.2 Step 2 classify_daily 내부에서 2 소스 merge (얇은 수정)

`news_classifier.classify_daily(date_str)` 내부 로직:

```
1. news/{month}.json 로드 → news_articles
2. naver_research/adapted/{month}.json 로드 → nr_articles  (있으면)
3. merged = news_articles + nr_articles  (in-memory concat)
4. date 필터 + '_classified_topics' 미분류만 → daily
5. classify_batch(daily)  — in-place field 갱신
6. 저장: news_articles, nr_articles 각각 원본 파일로 분리 저장
```

→ **raw news 파일은 naver_research 기사로 오염되지 않는다** (리스트 reference 분리 유지).

### 5.3 수정하지 않은 것

- Step 2.5 refine (`_step_refine`) — **수정 안 함**. 현재는 news 파일만 읽음. naver_research에 salience 부착은 별도 배치(Phase 2.5 후보).
- Step 3 GraphRAG, Step 4 MTD 델타, Step 5 regime check — 변경 없음.
- collector 자체 — 변경 없음.

---

## 6. 검증 결과 (지침 §6)

### 6.1 검증 1 — adapter smoke test (2026-01 full)

```
총 건수: 1,354
quality band 분포: TIER1=1099 (81.2%) / TIER2=185 (13.7%) / TIER3=70 (5.2%)
description non-empty: 1308/1354 (96.6%)
broker 채움: 1353/1354 (99.9%)  — broker_missing 1건
source=broker: 1353/1354 (category fallback 1건)
adapter_flags top: has_pdf 1103, pdf_rich 1072, category_tier2 698,
                   category_tier1 656, short_summary 70, raw_warning_downgrade 46
raw_warnings: detail_no_summary_block 46, empty_summary 46, summary_numeric_heavy 33,
              summary_too_short 13, broker_missing 1
```

**카테고리별 band 분포**:

| 카테고리 | total | TIER1 | TIER2 | TIER3 |
|---|---:|---:|---:|---:|
| debenture | 121 | 99 (81.8%) | 0 | 22 (18.2%) |
| economy | 111 | 111 (100%) | 0 | 0 |
| industry | 424 | 405 (95.5%) | 1 | 18 (4.2%) |
| invest | 350 | 290 (82.9%) | 48 | 12 (3.4%) |
| market_info | 348 | 194 (55.7%) | 136 (39.1%) | 18 (5.2%) |

**해석**:
- economy 100% TIER1 — 거시경제는 모두 PDF 충실 + summary OK.
- debenture TIER3 18.2% — 채권 보고서의 숫자/표 비중 높은 특성 (phase1 close waiver 근거와 일치).
- market_info는 TIER1/TIER2가 55/40 — 시황은 PDF 유무로 양분됨.
- 전체 TIER3 5.2%로 관리 가능한 수준.

### 6.2 검증 2 — 30건 샘플 분류 (classify_batch, Haiku)

5 카테고리 균등 층화 샘플(각 6건) 분류 결과:

```
분류 성공: 8/30 (26.7%)
primary_topic 분포:
  경기_소비: 3
  금리_채권: 2
  관세_무역: 1
  유동성_크레딧: 1
  통화정책: 1

카테고리별 avg topics:
  economy      avg=0.33  (1/6)
  market_info  avg=0.00  (0/6)
  invest       avg=0.17  (1/6)
  industry     avg=0.17  (1/6)
  debenture    avg=0.67  (4/6)  ← 최고
```

**해석**:
- **debenture 67% 분류** — 금리/채권 토픽이 classifier taxonomy와 잘 매칭.
- **market_info 0%** — 시황 리포트는 다자산 혼합 / 종목 순환 특성으로 기존 `primary_topic` 14개 분류체계에 잘 안 맞음.
- **economy 17%** — "모닝레터" 등 범용 형식이 특정 토픽에 안 걸림.
- 기존 classifier 프롬프트는 뉴스 기사 기준으로 튜닝돼 있음 (§3번 규칙: "개별 종목/ETF/IPO 분석은 빈 배열"). 리서치 리포트는 상당수가 이 조건에 걸려 topics=[] 처리됨 — **의도된 동작**이지만 리서치 활용도가 낮아짐.

**시사**: Phase 2.5 이후에 research-specific classifier 프롬프트 분기 또는 taxonomy 확장 검토 필요.

### 6.3 검증 3 — source 활용도 (salience 상위 N 중 naver_research 비율)

2026-01 news(5,050건) + naver_research(1,354건) = 6,404건 merge 후 `compute_salience_batch` 적용.

| 상위 N | naver_research 건수 | 비율 |
|---:|---:|---:|
| 50 | 0 | 0.0% |
| 100 | 0 | 0.0% |
| 200 | 0 | 0.0% |
| 500 | 0 | 0.0% |
| **baseline (전체 비율)** | 1,354 / 6,404 | **21.1%** |

**salience 점수 분포**:

| 소스 | mean | median | max |
|---|---:|---:|---:|
| naver_research | 0.213 | 0.140 | **0.340** |
| news | 0.364 | 0.340 | 0.775 |

→ **naver_research 최고 점수(0.340)가 news 중간값(0.340)에 그침** — 상위 500건에서도 0%.

**원인**:
- `compute_salience_batch`는 `_classified_topics` 기반 점수 계산 (topic intensity / bm_anomaly / source tier 등)
- naver_research 기사 대부분 `_classified_topics = []` 상태 (검증 2의 73% 미분류와 일관)
- topics 없으면 salience 상한이 구조적으로 낮음

**상위 5 naver_research 기사 (band=TIER1만, salience=0.340 동률)**:
```
#1 salience=0.340 band=TIER1 cat=economy "1/2 Weekly Macro, 혼재된 고용 신호와 금융시장 영향"
#2 salience=0.340 band=TIER1 cat=economy "신한 Econ Check-up"
#3 salience=0.340 band=TIER1 cat=economy "신한 FX Check-up"
#4 salience=0.340 band=TIER1 cat=economy "트럼프 2기 2년차 이슈와 리스크"
#5 salience=0.340 band=TIER1 cat=economy "베네수엘라 사태 후폭풍은 제한적일 듯"
```

**판정**: 지침 §10 "전혀 안 뽑히는지 / 과도하게 다 먹는지" → **전혀 안 뽑힘** (0%). Phase 2.5 대응 필요 (§7).

---

## 7. 1차 판단 — 리서치 source가 쓸 만한가?

| 항목 | 판정 |
|---|---|
| adapter 스키마 호환 | ✅ — classify_batch in-place 동작, refine 호출 가능 |
| quality heuristic 분포 | ✅ — TIER1 81% / TIER3 5% 합리적 |
| 분류 성공률 | ⚠️ **27%** — 기존 news classifier 프롬프트가 리서치와 미스핏 |
| salience 상위 랭크 기여 | ❌ **0% (상위 500 중)** — topics 미분류 기사가 구조적으로 점수 낮음 |

**1차 결론**: adapter 자체는 동작하지만, **그대로는 downstream에서 리서치가 evidence로 선택될 수 없다**. classifier 프롬프트 분기 또는 salience 공식 `source_type` 가중치 부여가 선행돼야 Phase 3 (GraphRAG/vectorDB 편입)로 넘어갈 수 있다.

---

## 8. 다음 배치 추천

### Phase 2.5 (권장, Phase 3 선행) — **classifier & salience source-aware 분기**

1. **research-specific classifier 프롬프트** (또는 taxonomy 확장)
   - 현 프롬프트는 "개별 종목/섹터는 빈 배열" 규칙 때문에 리서치 상당수가 제외됨
   - research용 분기에서는 "리포트 자체의 주요 거시 관점"을 뽑도록 재정의
2. **salience 공식에 `_research_quality_score` 가산**
   - `_event_salience += 0.2 * _research_quality_score` 형태
   - 기존 news와 동률 경쟁에서 밀리지 않도록
3. **Step 2.5 refine 수정**
   - 현재는 `news/{month}.json`만 읽음 — adapted도 읽어서 naver_research에도 salience 부착
   - 저장은 여전히 분리 유지

### Phase 3 (salience 문제 해결 후)

- GraphRAG 편입 — `source_type="naver_research"` 엔티티 추출 경로
- vectorDB ChromaDB 서브 컬렉션 (`category`, `broker`, `published_date` 메타)

---

## 9. 남은 리스크 3개

1. **classifier 프롬프트 미스핏** (Phase 2.5 P0) — 현 프롬프트는 뉴스 기준으로 튜닝됐고 리서치 73%가 `topics=[]` 처리. 이대로 Phase 3 편입 시 GraphRAG에도 엔티티 추출 못 함.
2. **adapted 파일 관리 정책 부재** — daily_update가 매일 `adapted/{month}.json`을 전수 재생성. 기존 분류 결과(`_classified_topics` 등)가 덮어써지는지 idempotency 검증 필요. 현재 구현은 **매일 재생성** (raw 기준 deterministic) — 분류 결과는 classify_daily 저장 단계에서 보존됨 → 확인 완료.
3. **salience source-aware 가중치 미적용 시 Phase 3 무의미** — naver_research가 evidence 상위로 못 올라오면 GraphRAG/vectorDB 편입의 효과 측정 불가. Phase 2.5 선행 필수.

---

## 10. 실행 명령 cheat-sheet

```bash
# adapter 단독 실행 (month 지정)
python -m market_research.collect.naver_research_adapter 2026-01

# 특정 카테고리만
python -m market_research.collect.naver_research_adapter 2026-01 --category economy --category debenture

# dry-run (저장 안 함, 통계만)
python -m market_research.collect.naver_research_adapter 2026-01 --dry-run

# daily_update (Step 1.3 포함)
python -m market_research.pipeline.daily_update 2026-04-21

# 유닛 테스트
python -m unittest market_research.tests.test_naver_research_adapter -v
```

---

**End of Phase 2 doc.**
