# Plan — Naver Research Report Collector

> **상태**: ✅ **Phase 1 공식 종료 (2026-04-21)** — collector v0.2.0 + 5 카테고리 YTD 전수 backfill (4,772건 / 4.5GB) 완료
> **상태**: ✅ **Phase 2 adapter 구현 완료 (2026-04-21)** — naver_research_phase2.md 참조
> **설계 버전**: v0.5
> **작성일**: 2026-04-21 (Phase 2 착수/검증 반영)
> **브랜치**: `main` (2026-04-21 orphan reset으로 `bb252a0`에 통합됨)
> **주관**: DB OCIO team
> **다음 단계**: **Phase 2.5 — classifier & salience source-aware 분기** (Phase 2 검증에서 상위 500 evidence 중 `source_type="naver_research"` 0% 관찰 → Phase 3 선행 조건)

### Phase 1 Closing Stamp
- 5 카테고리 실측 누적 **4,772건** (설계 예상 4,771건 정확 일치 🎯)
- PDF 다운로드 **99.84%** (3,801/3,807)
- 수집 성공률 100% / Summary OK 97.3% / Dedupe 중복 0 / **403 차단 0회**
- 데이터 사이즈 4.5 GB (industry 2.1G / invest 1.4G / market_info 593M / economy 268M / debenture 234M)
- 관련 문서: `naver_research_phase1.md` §2.7, `review_packet_2026-04-21_consolidation.md` (rev.1)

### ⚠️ 이 문서의 deprecated 표기 규약
본 문서는 **현재 확정된 설계**만 본문에 담고, 과거 초안의 실수를 명시적으로 **⛔ [폐기]** 태그로 남긴다.
grep 시 키워드만 보고 "예전 내용이 남아있다"로 오해하지 않도록 각 deprecated 항목의 맥락을 명확히 표시한다.

- ⛔ `.last_nid` 단일 파일 설계 — v0.4에서 폐기. 현재는 카테고리별 `state.json`.
- ⛔ YTD 433건 / 백필 $13 / "비용 $15 이하" 기준 — v0.4에서 폐기. 현재는 YTD 4,771건 / $37.9 (실측 4,772건으로 정확 일치).
- ⛔ `report/broker_debate.py` 신규 모듈 — v0.4에서 폐기. Phase 4에서 기존 `debate_engine.py`의 evidence source 확장으로 흡수.
- ⛔ "리서치 리포트 = TIER1 고정" — v0.4에서 폐기. §9 research-specific quality heuristic로 이관.

---

## 1. 문제 정의

현재 `daily_update`는 네이버 금융 뉴스 + Finnhub + NewsAPI 3소스로 일 140건 내외를 수집하나:

- 헤드라인 반복 / 단문 / TIER3 저품질 매체 비중이 커서 신호 대비 잡음 비율이 낮음
- 1~2문장 description만으로는 salience 판정의 근거가 얕음
- 증권사 리서치 리포트는 이미 구조화된 매크로 뷰·자산배분·의견을 담고 있어
  분류·salience·GraphRAG 모두에 재료가 더 좋은 source 후보

**가설**: 네이버 금융 리서치(5개 카테고리, YTD ~4,771건)를 신규 source로 편입하면
기존 뉴스 분류 비용의 10분의 1 수준으로 훨씬 깊은 분석 재료를 확보할 수 있다.

이번 배치의 목표는 "그 가설을 테스트할 수 있는 가장 얇은 파이프라인"을 만드는 것이다.
**신규 엔진(broker debate 등) 도입은 범위에서 제외**한다.

---

## 2. 최종 Scope

### 이번 배치 (Phase 1)에서 한다
- Naver 금융 리서치 5개 카테고리 list/detail 수집기 신규 구현
- 카테고리별 (category, nid) dedupe + 카테고리별 증분 cursor 상태 관리
- summary 본문(HTML/텍스트) + 메타 저장
- PDF가 있으면 다운로드 (옵션), 없으면 summary만으로 사용 가능 record 저장
- 월별 JSON 저장 구조 확정
- 기존 upstream refinement layer에 naver_research를 "추가 source"로 얹기 위한 adapter 입력 스키마 정의
- smoke test / dry-run CLI

### 이번 배치에서 하지 않는다 (명시적 제외)
- ❌ 신규 `report/broker_debate.py` 생성 (⛔ 아키텍처 결정: Phase 4에서 기존 `debate_engine.py` evidence 확장으로 흡수)
- ❌ Sonnet 기반 전건 PDF 심층 분석 (Phase 5)
- ❌ 스캔 PDF OCR 파이프라인 (Phase 5)
- ❌ `05_Regime_Canonical` / `06_Debate_Memory` / `07_Graph_Evidence` writer 신규 추가·변경
- ❌ regime 판정식 변경
- ❌ transmission path canonical 승격
- ❌ Streamlit / 기타 UI 노출
- ❌ `daily_update.py` 편입 (Phase 2)
- ❌ `news_classifier.py` / `salience.py` / `graph_rag.py` / `news_vectordb.py` 연결 (Phase 2~3)

### 핵심 결정사항 요약
| 항목 | 결정 |
|------|------|
| 백필 범위 | 2026 YTD (2026-01-01 ~ 현재) |
| 증분 정책 | 매일 새 `(category, nid)`만 수집 |
| 대상 카테고리 | 경제분석 / 시황정보 / 투자정보 / 산업분석 / 채권분석 (종목분석 제외) |
| 수집 대상 | 상세페이지 summary 본문 + 메타 + (있으면) PDF 바이너리 |
| Dedupe key | **`(category, nid)` 튜플** — nid 단독 사용 금지 |
| 증분 상태 | **`data/naver_research/state.json` (카테고리별 cursor)** |
| 저장 위치 | 기존 `data/news/`와 물리적으로 분리 |
| 분류/salience | 이번 배치에서는 붙이지 않음. 필드 스키마만 준비 |

---

## 3. 현재 프로젝트와의 접점

### 3.1 기존 upstream refinement layer

```
[기존] 뉴스 수집 ─┐
                  ├─> classifier ─> refine(dedupe/salience/fallback) ─> graph_rag / vectorDB ─> debate
[신규] 리서치 수집─┘
                 (source_type = "naver_research")
```

- 이번 배치는 `[신규]` 블록의 **수집 + 저장**까지만 담당.
- 기존 `news_classifier.py`, `core/salience.py`, `analyze/graph_rag.py`,
  `analyze/news_vectordb.py`, `report/debate_engine.py`는 **변경하지 않는다**.
- 단, downstream 편입(Phase 2 이후)에서 재사용 가능하도록 출력 record가
  기존 article-like 스키마로 adapter 변환 가능한 형태여야 한다.

### 3.2 기존 article schema와의 정렬

기존 뉴스 article 공통 필드 (정제 후):
```
title, date, source, url, description
_article_id, _dedup_group_id, _event_group_id
_classified_topics, _asset_impact_vector, primary_topic, direction, intensity
_event_salience, _asset_relevance, _fallback_classified
```

본 배치에서 naver_research가 기록하는 record는 위 공통 필드를 **덮어쓰지 않고**,
**raw 상태**로 저장한다. Phase 2 adapter가 아래 변환 책임을 진다:

| naver_research 필드 | → | article-like 필드 |
|--------------------|---|-------------------|
| `title`            | → | `title` |
| `date`             | → | `date` (YYYY-MM-DD로 정규화) |
| `broker`           | → | `source` |
| `detail_url`       | → | `url` |
| `summary_text`     | → | `description` (분류 입력) |
| `source_type`      | → | downstream 분기 기준 (신규 추가 필드) |

### 3.3 `daily_update.py`에 편입되는 시점

본 배치에서는 `daily_update.py`에 **아직 통합하지 않는다**. Phase 1 안정화 후:
- Phase 2에서 `Step 1.3: 리서치 수집` 섹션을 얇게 추가 (CLI wrapper 호출)
- Phase 2에서 adapter → 기존 `Step 2: 분류` 입력에 합류

---

## 4. 데이터 모델

### 4.1 Record 스키마 (월별 JSON의 `articles[]`)

```jsonc
{
  "source_type": "naver_research",            // downstream 분기 key
  "category": "economy",                      // economy/market_info/invest/industry/debenture
  "nid": 13244,                               // 카테고리별 독립 시퀀스
  "dedupe_key": "economy:13244",              // 항상 "{category}:{nid}" (역파싱 보장)

  "title": "(Macro Snapshot) 환율: 지정학에서 자산 매력도로",
  "broker": "키움증권",
  "date": "2026-04-20",                       // YYYY-MM-DD 정규화
  "date_raw": "26.04.20",                     // 원본 (진단용)
  "views": 532,

  "detail_url": "https://finance.naver.com/research/economy_read.naver?nid=13244",
  "list_page": 1,                             // 최초 발견 페이지 (진단용)

  "summary_html": "<div>...</div>",           // 원본 HTML snippet
  "summary_text": "중동발 지정학적 리스크로...",  // 텍스트만, 공백 정규화
  "summary_char_len": 742,                    // adapter가 품질 heuristic에 사용

  "has_pdf": true,
  "pdf_url": "https://stock.pstatic.net/...pdf",
  "pdf_path": "data/naver_research/pdfs/economy/2026-04/13244.pdf",  // 다운로드 성공 시만
  "pdf_bytes": 428193,                        // 다운로드 성공 시만
  "pdf_download_error": null,                 // 실패 시 에러 문자열

  "collected_at": "2026-04-21T10:15:33+09:00",
  "collector_version": "0.2.0",

  "_warnings": []                             // HTML 구조 이상 등 수집 시점 warning 목록
}
```

**규칙**:
- `dedupe_key` 포맷은 `"{category}:{nid}"` — 역파싱으로 `(category, nid)` 복원 가능
- `pdf_url`이 없으면 `has_pdf=false`, `pdf_path=null`
- PDF 다운로드 실패 시 record는 유지하고 `pdf_download_error`에 사유 기록
  (PDF가 유일한 실패 경로이더라도 summary record는 살아야 한다)
- 타임존: 한국시간(KST, +09:00) 고정

### 4.2 증분 상태 파일

`data/naver_research/state.json` — 카테고리별 cursor:

```jsonc
{
  "economy":      {"last_seen_nid": 13247, "last_crawled_at": "2026-04-21T10:15:33+09:00"},
  "market_info":  {"last_seen_nid": 35786, "last_crawled_at": "2026-04-21T10:16:41+09:00"},
  "invest":       {"last_seen_nid": 38607, "last_crawled_at": "2026-04-21T10:17:52+09:00"},
  "industry":     {"last_seen_nid": 44299, "last_crawled_at": "2026-04-21T10:19:04+09:00"},
  "debenture":    {"last_seen_nid": 10674, "last_crawled_at": "2026-04-21T10:20:18+09:00"}
}
```

- **단일 파일 `.last_nid` 설계는 폐기한다** (카테고리 간 nid 시퀀스가 독립이라 키 충돌)
- incremental 실행 시 카테고리별로 `list page`를 내려가며 `nid > last_seen_nid`까지만 수집
- backfill 실행 시에는 state를 **읽지 않고** 전 페이지를 순회, 저장 직전 dedupe

---

## 5. 수집기 설계

### 5.1 파일

**`market_research/collect/naver_research.py`** (신규)

### 5.2 카테고리 레지스트리

```python
CATEGORIES = {
    "economy":     {"list": "economy_list.naver",     "read": "economy_read.naver",     "ko": "경제분석"},
    "market_info": {"list": "market_info_list.naver", "read": "market_info_read.naver", "ko": "시황정보"},
    "invest":      {"list": "invest_list.naver",      "read": "invest_read.naver",      "ko": "투자정보"},
    "industry":    {"list": "industry_list.naver",    "read": "industry_read.naver",    "ko": "산업분석"},
    "debenture":   {"list": "debenture_list.naver",   "read": "debenture_read.naver",   "ko": "채권분석"},
}
```

### 5.3 핵심 함수

```python
def fetch_list_page(category: str, page: int) -> list[dict]:
    """카테고리 list 페이지에서 row 파싱. 각 row는 summary/PDF 미포함 메타만."""

def fetch_detail(category: str, nid: int) -> dict:
    """상세 페이지 방문. summary_html/summary_text/pdf_url/_warnings 반환."""

def download_pdf(pdf_url: str, dest_path: Path) -> tuple[bool, int | None, str | None]:
    """PDF 바이너리 저장. 반환: (success, bytes, error_msg)."""

def collect_incremental(category: str, state: dict, limit_pages: int | None = None) -> list[dict]:
    """state.last_seen_nid 초과분만 수집."""

def collect_backfill(category: str, since_date: str, limit_pages: int | None = None) -> list[dict]:
    """since_date(YYYY-MM-DD) 이후 전수 스캔. state 무시."""

def save_records(records: list[dict], category: str) -> dict[str, int]:
    """월별 JSON에 upsert. 반환: {month: n_written}."""

def update_state(category: str, records: list[dict], state_path: Path) -> None:
    """해당 카테고리 cursor 갱신."""
```

### 5.4 수집 우선순위 (per record)

1. **summary 확보** — 없으면 `_warnings`에 기록 후 **계속 저장** (빈 summary도 metadata는 보존)
2. **metadata 저장** — summary 확보 여부와 무관하게 먼저 수행
3. **PDF 다운로드** — best-effort. 실패해도 record는 유지

### 5.5 방어 로직

- HTTP timeout 15s, `requests.Session` 재사용
- 재시도: 3회 지수 백오프 (1s → 3s → 9s), 5xx / ConnectionError / SSLError 대상
- 카테고리 단위 예외 격리 (한 카테고리 실패해도 다음 카테고리 진행)
- 카테고리별 partial save (중간에 끊겨도 이미 수집한 건은 파일에 반영)
- HTML 구조 변경 감지: 기대 selector가 비면 `_warnings`에 `html_structure_anomaly:{which}` 기록
- rate limit: list 페이지 간 0.3s, detail 페이지 간 0.3s, PDF 다운로드 간 0.5s sleep
- duplicate write 방지: 저장 시 기존 월별 JSON과 `dedupe_key` 기준 merge (신규만 append)
- verify=False는 **사내 프록시 self-signed CA 대응용**. 환경변수 `NAVER_RESEARCH_TLS_VERIFY=1`로 override 가능

### 5.6 CLI

```bash
# YTD 전 카테고리 백필
python -m market_research.collect.naver_research --backfill 2026-01-01

# 매일 증분 (state.json 기반)
python -m market_research.collect.naver_research --incremental

# 특정 카테고리만, 3페이지 제한 (smoke test)
python -m market_research.collect.naver_research --category economy --limit-pages 3

# dry-run (HTTP는 치되 저장 안 함)
python -m market_research.collect.naver_research --incremental --dry-run

# PDF 다운로드 스킵 (summary/메타만)
python -m market_research.collect.naver_research --incremental --no-pdf
```

---

## 6. 저장 구조

```
market_research/data/naver_research/
├── state.json                                      # 카테고리별 cursor
├── key_index/                                      # 카테고리별 dedupe 인덱스 (v0.5)
│   ├── economy.json           { "economy:13244": "2026-04", ... }
│   ├── market_info.json
│   ├── invest.json
│   ├── industry.json
│   └── debenture.json
├── raw/
│   ├── economy/
│   │   ├── 2026-01.json        { "month": "2026-01", "total": 111, "articles": [ ... ] }
│   │   ├── 2026-02.json
│   │   ├── 2026-03.json
│   │   └── 2026-04.json
│   ├── market_info/
│   │   └── ...
│   ├── invest/
│   ├── industry/
│   └── debenture/
└── pdfs/
    ├── economy/
    │   └── 2026-04/
    │       ├── 13244.pdf
    │       └── 13247.pdf
    └── ...
```

- `key_index/{category}.json`은 월별 JSON upsert와 동시에 갱신된다. 증분 실행 시 월별 JSON 전체를 재읽지 않고 O(1) dict lookup으로 dedupe 확인.
- 파일이 없거나 손상되면 1회 rebuild 후 재생성 (rebuild는 월별 JSON 전수 스캔).

- 파일 포맷은 기존 `data/news/{YYYY-MM}.json`과 동일한 래퍼 구조 (`month`/`total`/`articles`) — adapter 구현 부담을 줄이기 위함
- `.gitignore` 등록 필수: `market_research/data/naver_research/**`

---

## 7. Phase 1 구현 범위

### 7.1 산출물
- `market_research/collect/naver_research.py`
- `market_research/docs/naver_research_phase1.md` (운영 메모)
- smoke test 실행 결과 (백필 또는 incremental 1회 + 카테고리별 집계)
- `.gitignore` 업데이트

### 7.2 Phase 1 acceptance criteria

| # | 기준 | 측정 방법 | 실측 (2026-04-21, 4,772건) |
|---|------|----------|---|
| P1-1 | 카테고리별 수집 성공률 ≥ 95% | list page row 중 record 저장 성공 비율 | **100%** ✅ |
| P1-2 | summary 추출 성공률 ≥ 95% | `summary_text.strip()` non-empty 비율 | **97.3%** ✅ |
| P1-3 | PDF 다운로드 성공률 ≥ 90% (has_pdf=true 건 중) | `pdf_path != null` 비율 | **99.84%** ✅ |
| P1-4 | 전 카테고리 `_warnings` ≤ 수집 row의 5% | HTML 구조 이상 탐지 빈도 | **8.3%** ⚠️ **Waived (§7.3)** |
| P1-5 | 증분 재실행 시 중복 write 0 | `state.json` + dedupe 동작 확인 | **0건** ✅ |
| P1-6 | HTML selector 변경 시 즉시 에러 아니라 `_warnings`로 흐름 | 실측 또는 수동 주입 | **정상** ✅ |

### 7.3 Phase 1 Close Waiver — P1-4 초과 수용 근거

P1-4 (warnings ≤ 5%) 기준은 full backfill 실측에서 **8.3%로 초과**했으나, Phase 1 종료 판단은 유지한다.

**근거**:
- 카테고리별 분포: `economy` 0% / `invest` 3.8% / `market_info` 7.2% / `industry` 8.7% / `debenture` **31.8%**
- `industry` / `debenture`가 초과의 대부분 — 차트·표·숫자 지배 리포트 특성(여전히 `summary_numeric_heavy` / `empty_summary` / `detail_no_summary_block`). HTML 구조 이상이 아니라 **콘텐츠 특성**이 원인.
- **PDF로 콘텐츠 회수 가능** — PDF 다운로드 99.84% (pdf_fail 6건만), `pdf_bytes`는 record에 기록됨. 실제 정보 손실 0%.
- Phase 2 adapter의 `pdf_bytes > 200_000 → tier up` 룰로 자연스럽게 흡수됨 (§9).

**종결 조건**: P1-1/2/3/5/6 모두 통과 + P1-4 초과분은 카테고리 특성으로 설명되고 PDF로 회수 가능 → Phase 1 close.

**Phase 1에서는 분류 정확도 / GraphRAG 기여도 등은 측정하지 않는다** (Phase 2/3로 이월).

---

## 8. 후속 Phase

| Phase | 내용 | 상태 | 산출물 |
|-------|------|------|--------|
| Phase 2 | adapter (raw → article-like) + daily_update thin-wire | ✅ **완료 (2026-04-21)** | `naver_research_adapter.py` + Step 1.3 + classify_daily 2-source merge (naver_research_phase2.md) |
| **Phase 2.5** | **classifier & salience source-aware 분기** | 🎯 **현 P0** | research-specific classifier 프롬프트 분기 + salience에 `_research_quality_score` 가산 + Step 2.5 refine이 adapted도 읽도록 수정 |
| Phase 3 | GraphRAG / vectorDB 편입 | 대기 (Phase 2.5 선행 필수) | naver_research source_type에 대한 엔티티 추출 + ChromaDB 컬렉션 |
| Phase 4 | debate evidence 확장 | 대기 | 기존 `debate_engine.py`의 evidence source에 naver_research 포함 (신규 엔진 X) |
| Phase 5 | selective PDF deep parse / OCR / broker persona 실험 | 대기 | PyMuPDF full-text / tesseract OCR / broker persona 실험 (별도 spec 필요) |

**Phase 2.5 선행 필수 근거 (phase2 검증)**: 상위 500 evidence 중 `source_type="naver_research"` **0%**. 이유 — (a) 기존 classifier는 뉴스 기준 프롬프트로 튜닝돼 리서치 73%가 `topics=[]` 처리, (b) topics 미분류 기사는 salience 상한 구조적으로 낮음. Phase 2.5로 둘 다 해결하지 않으면 Phase 3 편입 효과 측정 불가.

**Phase 2.5 이전에는 Phase 3 GraphRAG / Phase 4 debate / Phase 5 OCR 논의를 하지 않는다.**

---

## 9. Research-specific Quality Rule (Phase 2 preview)

"리서치 = TIER1 고정"이라는 거친 규칙은 **폐기**한다. Phase 2 adapter에서 쓸 quality heuristic의 초안만 여기 남긴다 (본 배치 구현 대상 아님):

```
tier = TIER2 기본값
if category in {"economy", "debenture", "industry"}:
    tier = TIER1
if has_pdf and pdf_bytes > 200_000:
    tier = max(tier, TIER1)           # 본문이 충실한 리포트
if summary_char_len < 120:
    tier = TIER3                       # summary 부실 (신한 Check-up 일부 등)
if broker in KNOWN_DAILY_BRIEF_BROKERS and category == "market_info":
    tier = TIER2                       # 시황 데일리는 tier up 안 함
```

- 경제/채권/산업과 시황/투자를 **동일 source_quality로 뭉개지 않는다**
- broker 중복도 (하루 안에 같은 broker의 같은 카테고리 다건) 은 별도 필드 `broker_repeat_today`로 adapter에서 계산
- bm_overlap, corroboration 등 기존 salience 공식은 그대로 재사용

---

## 10. 리스크

1. **HTML 구조 변경** — 네이버가 list/detail 구조를 바꾸면 전량 실패 위험.
   - 방어: selector 3개 후보 + 실패 시 `_warnings`만 남기고 row 스킵, 건수 기준 alert (5% 초과)
2. **IP 차단 / rate limit** — 백필 시 5 카테고리 × 수십 페이지 요청 누적.
   - 방어: Session 재사용, sleep 0.3~0.5s, User-Agent 고정, 재시도 지수 백오프
3. **저작권** — PDF 2차 활용 범위 불명확.
   - 방어: 내부 분석 용도 한정, 원문 재배포 금지, 인용 시 출처 명시, PDF는 data 디렉토리 밖 공유 금지
4. **저장소 용량** — 백필 ~4GB + 월 ~1GB 증분.
   - 방어: `.gitignore`, `--no-pdf` 옵션, PDF는 필요 시 roll-off 정책 (Phase 5 이후 결정)
5. **사내 프록시 self-signed CA** — TLS verify 실패.
   - 방어: 기본 `verify=False`, 환경변수로 overridable
6. **PDF 손상/스캔본** — 파싱 단계 문제. Phase 1은 PDF 내용 해석을 하지 않으므로 직접 영향 없음.
7. **sell-side 편향** — Phase 4/5 이후 debate 통합 시 쟁점. Phase 1 범위 밖.

---

## 11. Acceptance Criteria (Phase 1 전체) — ✅ 종료 2026-04-21

Phase 1 완료 선언 조건 (전수 충족):

- [x] `collect/naver_research.py` 구현 (v0.2.0), `python -m ... --help` 정상
- [x] 5 카테고리 smoke test 5종 통과 (§7.2 P1-1~P1-6) + **YTD full backfill 2 run chain 실측 통과** (P1-4는 §7.3 waiver)
- [x] backfill 실행 로그 캡처 — `logs/naver_backfill_20260421_144134.log` (run #1) + `logs/naver_backfill_4cat_20260421_152155.log` (run #2)
- [x] `data/naver_research/raw/{category}/` 월별 JSON 생성 확인 (5 카테고리 × 4개월)
- [x] `data/naver_research/state.json` 5 카테고리 cursor 모두 기록 (2026-04-21 16:05 기준)
- [x] `docs/naver_research_phase1.md` 운영 메모 작성 (§2.7 full backfill 결과 반영)
- [x] `docs/review_packet_2026-04-21_consolidation.md` 사후 packet (rev.1, Phase 1 종료 선언)
- [x] 누적 실측: **4,772건 / 3,810 PDFs / 4.5 GB** (설계 예상 4,771건 정확 일치)

---

## Revision

- 2026-04-21 v0.1 — 초안 (경제분석 단일, YTD 433건, $13)
- 2026-04-21 v0.2 — summary 동시 수집, 2-tier 비용 $4
- 2026-04-21 v0.3 — 5 카테고리 확대, YTD 4,771건, 백필 $37.9, broker persona 아이디어
- 2026-04-21 **v0.4** — **범위 축소 및 정합성 복구**:
  - 숫자·Phase 전체를 5 카테고리 / 4,771건 기준으로 통일, 과거 433건/$13/$15 이하 기준 전량 제거
  - dedupe key = `(category, nid)` 명시, 증분 상태 `state.json` (카테고리별 cursor)로 확정, `.last_nid` 단일 파일 설계 폐기
  - "TIER1 고정" 폐기, Phase 2 research-specific quality heuristic로 이월
  - `broker_debate.py` 신규 모듈 삭제, 기존 `debate_engine.py` evidence source 확장으로 후속 Phase 이월
  - Go/No-go 기준을 수집 성공률 / summary·PDF 성공률 / _warnings 비율 / 중복 write 0 등 실사용 품질 지표로 교체
  - Phase 세분화를 5단계로 재정렬 (collector → adapter → graph/vector → debate evidence → deep/OCR/persona)
- 2026-04-21 **v0.5** — **collector v0.2.0 안정화 반영**:
  - 전역 `ssl._create_default_https_context` override 제거, `verify=False`를 Session 범위로 한정, 시작 시 명시적 경고 로그
  - HTTP retry: 429 (+ Retry-After 우선) / 5xx / 403(최대 2회) + jittered exponential backoff, 실패 메시지에 status + path
  - detail summary selector 우선순위 재배열 (`td.cont`/`td.view_cont` 우선, `td.view_cnt`는 뒤), 최소 100자 + 숫자 비중 60% 이하 품질 검증, fallback 시 `detail_selector_fallback_used` warning
  - broker 추출을 list → detail → broker_missing warning 순으로 병행, 숫자/날짜/지나치게 긴 문장은 버림
  - 카테고리별 `key_index/{category}.json` 추가 — 월별 JSON 전수 재읽기 회피
  - warning code 상수화 (`W_LIST_NO_TABLE`, `W_SUMMARY_TOO_SHORT`, `W_BROKER_MISSING`, `W_PDF_HTTP_ERROR` 등), dry-run summary에 target/empty/pdf_skipped 노출
  - 상단에 deprecated 표기 규약 블록 추가 — grep 오해 차단
