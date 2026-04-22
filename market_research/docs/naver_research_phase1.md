# Naver Research — Phase 1 운영 메모

> **상태**: ✅ **Phase 1 공식 종료** (2026-04-21 YTD 전수 backfill 완료 — 4,772건 / 4.5GB)
> **후속**: ✅ **Phase 2 adapter 구현 완료** (2026-04-21) — 상세 `naver_research_phase2.md`
> **작성일**: 2026-04-21 (full backfill 결과 반영 + Phase 2 착수 반영)
> **브랜치**: `main` (2026-04-21 orphan reset으로 `bb252a0`에 통합됨)
> **상위 설계**: `plan_naver_research.md` v0.5
> **Collector 버전**: **v0.2.0**
> **다음 단계**: **Phase 2.5 — classifier & salience source-aware 분기** (§6 참조)

---

## 1. 이번 배치에서 구현한 것

### 파일
- `market_research/collect/naver_research.py` — Phase 1 collector **v0.2.0**
- `market_research/docs/plan_naver_research.md` — v0.5 (deprecated 표기 규약 + v0.5 revision)
- `market_research/docs/naver_research_phase1.md` — 본 문서 (v0.2.0 smoke test 결과로 갱신)
- `.gitignore` — `market_research/data/naver_research/` 추가

### v0.2.0에서 바뀐 것 (v0.1.0 → v0.2.0)

| 영역 | 변경 |
|------|------|
| **SSL** | `ssl._create_default_https_context` 전역 override 제거. TLS 제어는 `requests.Session.verify` 범위로 한정. `verify=False`일 때만 urllib3 경고 억제 + 시작 시 명시적 `[WARN] TLS certificate verification disabled ...` 출력. |
| **HTTP retry** | 429 (+ `Retry-After` 헤더 우선) / 5xx / 403(최대 2회) + `ConnectionError`/`Timeout`/`SSLError`. Backoff는 `base × 2^attempt + jitter(0~0.5s)`. |
| **최종 403 승격** | retry 한도 소진 후에도 403이면 `AccessBlockedError`로 승격. **경로 분리 (code truth)**: ① list/detail 403 → `AccessBlockedError` → `stats.errors.http_403_blocked_{list\|detail}` (detail 연속 3회 시 카테고리 조기 종료). ② PDF 403/실패 → `download_pdf()`가 Exception 흡수 → `record.pdf_download_error` + `warning_codes.pdf_http_error` + `stats.pdf_failed` (**`stats.errors` 경로 아님**). 상세는 §4 Observability 참조. |
| **detail selector** | 우선순위 재배열 (`td.cont` / `td.view_cont` / `div.view_cont` / `div.content` / `#content td`를 먼저, `td.view_cnt` 계열은 레거시로 강등). 품질 gate: 100자 미만 / 숫자·기호·공백 비중 60% 초과 / 순수 날짜 텍스트는 채택 거부. fallback 사용 시 `detail_selector_fallback_used` warning. |
| **broker 추출** | list page 휴리스틱 → detail page `div.sub_tit1` / `p.info` / `.bd_day` / `th.info` / `td.info` 블록 → summary 앞 120자 정규식(`…증권|투자신탁|자산운용|투자증권`) 순. 숫자/날짜/25자 초과 등은 거부. 모두 실패 시 `broker_missing` warning. record에 `broker_source` 필드 추가 (`list` / `detail` / `missing`). |
| **key_index** | `data/naver_research/key_index/{category}.json` — `{dedupe_key: month}` 맵. 월별 JSON 전수 스캔 회피, O(1) dedupe. 손상 시 1회 rebuild 후 재저장. |
| **Warning codes** | 자유문장 → 상수(`W_LIST_NO_TABLE`, `W_LIST_ROWS_NO_ITEMS`, `W_DETAIL_NO_SUMMARY_BLOCK`, `W_DETAIL_FALLBACK_USED`, `W_SUMMARY_TOO_SHORT`, `W_SUMMARY_NUMERIC_HEAVY`, `W_SUMMARY_EMPTY`, `W_BROKER_MISSING`, `W_PDF_HTTP_ERROR`). `CollectStats.warning_codes`에 카운트 누적. |
| **Dry-run** | 저장/state 갱신 스킵 유지. 요약 배너에 `DRY-RUN — storage/state skipped` 명시, per-category 테이블에 `target / summary_ok / sum_empty / pdf_declared / pdf_skipped / warnings` 전부 노출. |
| **헤더 정합성** | docstring 참조 버전을 `plan_naver_research.md v0.5`로 맞춤. |

### Record 스키마 (실측 샘플 `economy:13244`)
```
source_type: naver_research
category: economy
nid: 13244
dedupe_key: economy:13244
title: (Macro Snapshot) 환율: 지정학에서 자산 매력도로
broker: 키움증권
broker_source: list           (v0.2.0 신규)
date: 2026-04-20
date_raw: 26.04.20
views: 548
detail_url: https://finance.naver.com/research/economy_read.naver?nid=13244&page=1
list_page: 1
summary_html: [len=2253]
summary_text: "중동발 지정학적 리스크로..." (1,425자)
summary_char_len: 1425
summary_selector: td.view_cnt      (v0.2.0 신규 — 실제 선택된 selector 기록)
has_pdf: True
pdf_url: https://stock.pstatic.net/.../20260420_economy_754831000.pdf
pdf_path: data/naver_research/pdfs/economy/2026-04/13244.pdf  (or null)
pdf_bytes: 428193
pdf_download_error: null
collected_at: 2026-04-21T10:14:58.465310+09:00
collector_version: 0.2.0
_warnings: []
```

### state.json (2026-04-21 full backfill 완료 시점)
```json
{
  "economy":     {"last_seen_nid": 13247, "last_crawled_at": "2026-04-21T15:27:10+09:00"},
  "market_info": {"last_seen_nid": 35787, "last_crawled_at": "2026-04-21T15:42:16+09:00"},
  "invest":      {"last_seen_nid": 38607, "last_crawled_at": "2026-04-21T15:59:25+09:00"},
  "industry":    {"last_seen_nid": 44299, "last_crawled_at": "2026-04-21T15:02:39+09:00"},
  "debenture":   {"last_seen_nid": 10674, "last_crawled_at": "2026-04-21T16:05:00+09:00"}
}
```

### key_index (full backfill 후)
- `data/naver_research/key_index/economy.json`     — **433** entries
- `data/naver_research/key_index/industry.json`    — **1,454** entries
- `data/naver_research/key_index/market_info.json` — **1,256** entries
- `data/naver_research/key_index/invest.json`      — **1,226** entries
- `data/naver_research/key_index/debenture.json`   — **403** entries
- **합계 4,772건 / 3,810 PDFs / 4.5 GB**

---

## 2. Smoke Test 결과 (2026-04-21, v0.2.0)

> 공통: `[WARN] TLS certificate verification disabled ...` 배너가 모든 실행 상단에 출력됨 → TLS 제어가 세션 범위로만 동작하는 것 검증.

### 2.1 TEST 1 — economy 2페이지, PDF 스킵
```bash
python -m market_research.collect.naver_research --backfill 2026-01-01 \
    --category economy --limit-pages 2 --no-pdf
```
| 지표 | 값 |
|------|---:|
| list rows seen | 60 |
| target | **0** (key_index 60건 전수 적중) |
| records built | 0 |
| records saved | 0 |
| summary_ok / empty | 0 / 0 |
| pdf_declared | 0 |
| pdf_downloaded / failed / skipped | 0 / 0 / 0 |
| warnings | 0 |
| warning codes | — |
| 소요 | 0.9s |

### 2.2 TEST 2 — economy incremental 1페이지, dry-run
```bash
python -m market_research.collect.naver_research --incremental \
    --category economy --limit-pages 1 --dry-run
```
| 지표 | 값 |
|------|---:|
| list rows seen | 30 |
| target | 0 (`last_seen_nid=13247` 적중) |
| records built | 0 |
| records saved | **0 (DRY-RUN — storage/state skipped 명시)** |
| summary_ok / empty | 0 / 0 |
| pdf_declared | 0 |
| pdf_downloaded / failed / skipped | 0 / 0 / 0 |
| warnings | 0 |
| warning codes | — |
| 소요 | 0.2s |

### 2.3 TEST 3 — debenture 1페이지, PDF 포함
```bash
python -m market_research.collect.naver_research --backfill 2026-04-18 \
    --category debenture --limit-pages 1
```
| 지표 | 값 |
|------|---:|
| list rows seen | 30 |
| target | 0 (이전 세션 저장분 10건과 dedupe 적중) |
| records built | 0 |
| records saved | 0 |
| summary_ok / empty | 0 / 0 |
| pdf_declared | 0 |
| pdf_downloaded / failed / skipped | 0 / 0 / 0 |
| warnings | 0 |
| 소요 | 0.4s |

### 2.4 TEST 4 (추가) — invest 1페이지, PDF 스킵 (신 경로 full-exercise)
`TEST 1~3`가 모두 dedupe 적중으로 target=0이라, v0.2.0 신규 경로(selector 품질 gate, broker 보강, key_index 갱신, warning code 집계, dry-run 요약)를 실사용 데이터로 태우기 위해 이전에 수집하지 않은 카테고리(invest) 1페이지를 추가 실행.
```bash
python -m market_research.collect.naver_research --backfill 2026-04-20 \
    --category invest --limit-pages 1 --no-pdf
```
| 지표 | 값 |
|------|---:|
| list rows seen | 30 |
| target | 30 |
| records built | 30 |
| records saved | **30** (new month 2026-04) |
| summary_ok / empty | **29 / 1** (97%) |
| pdf_declared | 28 |
| pdf_downloaded / failed / skipped | 0 / 0 / **28** (`--no-pdf` 의도 스킵) |
| warnings | 3 |
| warning codes | `detail_no_summary_block: 1` / `summary_too_short: 1` / `empty_summary: 1` (동일 1건 3-stage 체인) |
| broker | 샘플: "하나증권" / "키움증권" / "신한투자증권" 등 정상 추출 (broker_missing 0) |
| 소요 | 11.3s |

### 2.5 TEST 5 (추가) — market_info 1페이지, PDF 스킵 (v0.2.0 collector 안정화 배치 직후 실행)
collector v0.2.0 안정화 직후, TEST 4(invest)와 동일한 취지로 손 안 댄 `market_info` 카테고리 1페이지를 별도 실행하여 v0.2.0 경로를 재확인. 이 수치가 §2.6 P1 Acceptance 표의 market_info 항목 근거.
```bash
python -m market_research.collect.naver_research --backfill 2026-04-20 \
    --category market_info --limit-pages 1 --no-pdf
```
| 지표 | 값 |
|------|---:|
| list rows seen | 30 |
| target | 30 |
| records built | 30 |
| records saved | **30** (new month 2026-04) |
| summary_ok / empty | **29 / 1** (97%) |
| pdf_declared | 22 |
| pdf_downloaded / failed / skipped | 0 / 0 / **22** (`--no-pdf` 의도 스킵) |
| warnings | 3 |
| warning codes | `detail_no_summary_block: 1` / `summary_too_short: 1` / `empty_summary: 1` (동일 1건 3-stage 체인) |
| broker | 샘플: "SK증권" / "신한투자증권" 등 정상 추출 (broker_missing 0) |
| 소요 | 11.6s |

### 2.6 P1 Acceptance Criteria 대조 (누적 기준)

| # | 기준 | 결과 |
|---|------|------|
| P1-1 | 카테고리별 수집 성공률 ≥ 95% | economy 60/60, debenture 10/10, invest 30/30, market_info 30/30 → **100%** ✅ |
| P1-2 | summary 추출 성공률 ≥ 95% | 128/130 (economy 60 + debenture 10 + invest 29 + market_info 29) → **98.5%** ✅ |
| P1-3 | PDF 다운로드 성공률 ≥ 90% (has_pdf=true 중, 실제 다운로드 시도분) | 9/9 (debenture TEST) → **100%** ✅ |
| P1-4 | `_warnings` 비율 ≤ 5% | 6/130 (invest 3 + market_info 3) → **4.6%** ✅ |
| P1-5 | 증분 재실행 중복 write 0 | TEST 1/2/3 전부 target=0 → **0%** ✅ |
| P1-6 | HTML 구조 이상 시 `_warnings`로 흐름 | `detail_no_summary_block` / `summary_too_short` 체인이 실측에서 정상 기록 확인 ✅ |
| P1-7 (신규) | **list/detail** 최종 403이 구조 warning으로 묻히지 않음 | `AccessBlockedError` 승격 → `stats.errors.http_403_blocked_{list|detail}` 코드. **PDF 다운로드 실패는 별도 경로** (`warning_codes.pdf_http_error` + `stats.pdf_failed` + `record.pdf_download_error`, `errors` 경로 아님). list/detail 실전 403 이벤트는 미발생 — **static 검증만 완료** ⚠️ |

### 2.7 Full Backfill (2026-04-21, Phase 1 공식 종료)

**2 run chain 실행** (총 65분, 4,641건 신규 saved):
- run #1 (14:41 ~ 15:02, 21분): `industry --backfill 2026-01-01` + 4 카테고리 `--incremental`
- run #2 (15:21 ~ 16:05, 44분): `economy/market_info/invest/debenture --backfill 2026-01-01` chain

**카테고리별 결과**:

| 카테고리 | rows | target | saved | sum_ok | sum_empty | pdf_decl | pdf_ok | pdf_fail | warnings | 소요 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| industry | 1500 | 1454 | 1454 | 1413 | 41 | 1270 | 1270 | 0 | 127 | 1265s |
| economy | 480 | 373 | 373 | 373 | 0 | 320 | 320 | 0 | **0** | 315s |
| market_info | 1290 | 1225 | 1225 | 1196 | 29 | 827 | 827 | 0 | 88 | 906s |
| invest | 1260 | 1196 | 1196 | 1182 | 14 | 1050 | 1046 | **4** | 46 | 1028s |
| debenture | 450 | 393 | 393 | 352 | 41 | 340 | 338 | **2** | 125 | 334s |
| **합계** | **4980** | **4641** | **4641** | **4516** | **125** | **3807** | **3801** | **6** | **386** | **3848s** |

**P1 Acceptance (4,641건 신규 + smoke test 131건 = 4,772건 누적)**:
- 수집 100% / Summary **97.3%** / PDF **99.84%** / Dedupe 중복 **0** / **403 차단 0회**
- Warnings 8.3% (P1-4 5% 기준 초과) — `industry` 8.7% / `debenture` 31.8%가 주요 원인. **Phase 1 close waiver** 적용: 콘텐츠 특성(차트/표 지배)이 원인이고 PDF 99.84%로 정보 손실 0% — `plan_naver_research.md` §7.3 참조

**월별 분포** (총 4,641 신규):

| 카테고리 | 2026-01 | 2026-02 | 2026-03 | 2026-04 |
|---|---:|---:|---:|---:|
| industry | 424 | 283 | 449 | 298 |
| market_info | 348 | 287 | 361 | 229 |
| invest | 350 | 289 | 354 | 203 |
| debenture | 121 | 102 | 102 | 68 |
| economy | 111 | 109 | 128 | 25 |

**데이터 사이즈** (누적): `data/naver_research/` 총 **4.5 GB** — industry 2.1G / invest 1.4G / market_info 593M / economy 268M / debenture 234M

**로그**:
- run #1: `logs/naver_backfill_20260421_144134.log` (131 lines)
- run #2: `logs/naver_backfill_4cat_20260421_152155.log` (249 lines)

**403 실전 미발생** ⚠️: 4,641건 수집 중 `AccessBlockedError` 단 1회도 발생 안 함. P1-7 임계치 재튜닝 근거 여전히 미수집.

---

## 3. 여전히 안 한 것 (명시적 제외)

- ~~전 5 카테고리 YTD full backfill~~ ✅ 2026-04-21 완료 (§2.7)
- `daily_update.py` 편입 (Step 1.3 wrapper) — **Phase 2 대상**
- `news_classifier` / `salience` / `graph_rag` / `news_vectordb` 편입 — Phase 3
- PDF 내용 파싱 (PyMuPDF), OCR — Phase 3+
- Research-specific quality heuristic 적용 — **Phase 2 adapter**
- Broker persona debate, Streamlit UI — Phase 4

---

## 4. Observability — 구조 warning vs 접근 차단

v0.2.0에서 **list/detail 접근 차단은 `errors`로**, **HTML 구조 이슈와 PDF 실패는 `warning_codes`**로 분리했다. 세 경로가 어느 필드에 남는지가 다르므로 혼동하지 말 것.

| 증상 | 의미 | 남는 곳 | 대응 |
|------|------|---------|------|
| `warning_codes.list_no_table` ↑ | 네이버 list HTML이 실제로 바뀌어 `table.type_1` selector가 안 먹힘 | `stats.warning_codes` | selector 재조사 |
| `warning_codes.detail_no_summary_block` ↑ | detail HTML 구조 변경 또는 summary 블록 소실 | `stats.warning_codes` | selector 후보 재조사 |
| `warning_codes.summary_too_short` / `summary_numeric_heavy` | 본문은 있으나 질이 낮음 (예: 데이터표만 있는 리포트) | `stats.warning_codes` | source 분포 확인, quality heuristic에서 활용 |
| `warning_codes.broker_missing` ↑ | list/detail 양쪽에서 broker 추출 실패 | `stats.warning_codes` | 휴리스틱 재정비 |
| `errors` 중 `http_403_blocked_list` | list 페이지 자체가 차단됨 (bot challenge 가능성) — `AccessBlockedError` 승격 경로 | `stats.errors` | User-Agent 교체, 인터벌 증가, IP 변경 |
| `errors` 중 `http_403_blocked_detail` | 특정 nid detail만 차단. 3회 연속 시 detail 루프 조기 중단 | `stats.errors` | list만 수집하거나 다른 IP에서 재시도 |
| `warning_codes.pdf_http_error` ↑ + `stats.pdf_failed` ↑ | PDF 다운로드 실패 (403/5xx/기타 네트워크). `download_pdf()` 내부가 `Exception`을 문자열로 흡수해 `record.pdf_download_error`로 기록 | `stats.warning_codes[pdf_http_error]`, `stats.pdf_failed`, `record.pdf_download_error` | PDF만 스킵하고 summary/메타 record는 유지 |

### 경로가 다른 이유 (code truth)
- **list/detail 403 → `errors`**: `http_get()`이 retry 소진 후 `AccessBlockedError` raise → `iter_list_pages()` / detail 루프에서 catch → `stats.errors.append("http_403_blocked_{stage}: ...")`. stage="list"는 해당 카테고리 나머지 list page 순회 중단, stage="detail"은 연속 3회 시 detail 루프 조기 종료.
- **PDF 403/실패 → `warning_codes` + `pdf_failed`**: `download_pdf()`가 `AccessBlockedError`를 포함한 모든 `Exception`을 catch하여 `(False, None, "http:...")` 문자열로 반환. 호출 측 `collect_category()`는 이 실패 반환값을 `record.pdf_download_error`에 저장하고 `_warnings`에 `W_PDF_HTTP_ERROR("pdf_http_error")` append, `stats.pdf_failed` 증가. **`stats.errors` 경로로는 들어가지 않는다**.

### 운영상 읽는 법
- `list_no_table`이 증가하는데 동시에 `http_403_blocked_list`가 없으면 진짜 HTML 구조 변경. 반대면 차단.
- `pdf_http_error`가 증가하는데 `http_403_blocked_*`가 없으면 PDF 리소스(`stock.pstatic.net`) 쪽만의 이슈일 가능성이 높다. 동시 증가하면 네이버 전체가 차단된 상태.

---

## 5. Known Risks (Phase 1 공식 종료 시점)

1. **HTML selector 실전 변경 이벤트 미검증** (유지)
   selector 후보 다중화 + longest-td fallback + 품질 gate까지 구현했으나, 실제 네이버가 구조를 바꿨을 때의 경보 경로는 아직 실증 대상이 없음. full backfill 4,641건 중 detail_no_summary_block 총 125건 발생했지만 모두 콘텐츠 특성(차트/표 리포트)이 원인 — 구조 변경 아님. `warning_codes.detail_no_summary_block` 비율이 수집 row의 5% 초과 + 동시에 `empty_summary`가 급증하면 수동 조사 트리거.

2. **403 차단 감지 정책 — 실전 발생 전 (여전)**
   최종 403 승격과 stage 구분은 구현되어 `AccessBlockedError` 경로가 준비되어 있으나, 전 카테고리 full backfill 4,641건 수집 중에도 **0회 발생**. `detail_blocked_hits >= 3` 조기 종료 정책의 임계치는 여전히 정적 검증만 완료. 매일 incremental 누적 운영 중 관찰 필요 (네이버 bot challenge 정책 변경 시점에 처음 만날 가능성).

3. **broker 휴리스틱의 edge case — 실전 데이터 기반** (완화)
   full backfill 4,641건 중 `broker_missing` 9건(0.19%)만 발생. 극소수 edge case 수준으로 안정 확인. 다만 `broker_source` 필드의 list vs detail vs missing 분포는 raw JSON 파싱으로 별도 집계 필요 (P1 후순위).

4. **PDF HTTP error 6건** (신규, 실전 확인)
   invest 4건 + debenture 2건. 3,807 PDF 시도 중 0.16% — 정상 범위. `warning_codes.pdf_http_error` 경로로 정상 처리. daily_update 편입 후 자연 회수 예상.

---

## 6. 다음 배치 추천 (우선순위)

### ~~배치 A — YTD 전 카테고리 full backfill~~ ✅ 2026-04-21 완료
- 2 run chain 실행 완료 (§2.7). 5 카테고리 누적 4,772건 / 4.5GB.
- 403 실전 0회 발생 — 임계치 재튜닝 근거 미수집.

### ~~배치 B — adapter 설계 + `daily_update.py` 얇은 편입 (Phase 2)~~ ✅ 2026-04-21 완료
- `market_research/collect/naver_research_adapter.py` 신규 구현
- `daily_update.py` Step 1.3 추가 + `classify_daily` 2-source merge
- 유닛 테스트 17/17 PASS, smoke test 1,354건 / band TIER1 81.2%
- **상세 보고서**: `naver_research_phase2.md`

### 배치 B.5 — classifier & salience source-aware 분기 (Phase 2.5) 🎯 **현 P0**

Phase 2 검증에서 발견된 구조적 이슈 대응:
1. **research-specific classifier 프롬프트** (또는 taxonomy 확장)
   - 현 프롬프트 "개별 종목/섹터는 빈 배열" 규칙 때문에 리서치 73%가 `topics=[]`
   - research 분기에서는 "리포트의 주요 거시 관점" 뽑도록 재정의
2. **salience 공식 `_research_quality_score` 가산**
   - `_event_salience += 0.2 * _research_quality_score` 등
   - naver_research 상위 500 evidence 0% 문제 해결
3. **Step 2.5 refine 수정** — adapted 파일도 읽어 salience 부착 (저장은 분리 유지)

### 배치 C — GraphRAG / vectorDB 편입 (Phase 3, Phase 2.5 선행 필수)
- `source_type="naver_research"` 엔티티 추출 경로
- ChromaDB 서브 컬렉션 (`category`, `broker`, `published_date` 메타)
- 비교 지표: 건당 엔티티 수, evidence card에서 리서치 선택 비율
- 입력 volume: 4,772건 (뉴스 대비 약 1/5)

---

## 7. 실행 명령 cheat-sheet

```bash
# 일반 증분 (cron)
python -m market_research.collect.naver_research --incremental

# YTD full backfill
python -m market_research.collect.naver_research --backfill 2026-01-01

# 한 카테고리만, 페이지 제한
python -m market_research.collect.naver_research --backfill 2026-01-01 \
    --category economy --limit-pages 3

# dry-run (HTTP만, 파일 저장 안 함)
python -m market_research.collect.naver_research --incremental --dry-run

# PDF 다운로드 생략
python -m market_research.collect.naver_research --incremental --no-pdf

# TLS 정상 검증 모드
NAVER_RESEARCH_TLS_VERIFY=1 python -m market_research.collect.naver_research --incremental
```
