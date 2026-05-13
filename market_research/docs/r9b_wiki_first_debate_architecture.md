# R9-B.1 — Wiki-first Debate Input Architecture (설계 리뷰)

> Status: design review only. 구현/운영 파일 변경 0, LLM 호출 0.
> Author: R9-B.1 work order (2026-05-13)
> 관련 close note: `r9a_claim_identity_and_monitoring_close_note.md`
> Pre-read: `io_contract.md`, `entity_page_redesign.md`,
> `r9a_wiki_first_claim_normalization.md`

---

## 0. Why this design exists

사용자 의도는 단순한 wiki page 생성이 아니다. 원하는 흐름은 다음이다.

```
Raw data source
  → Wiki page 생성 (canonical memory 축적)
  → Wiki page 를 중심으로 debate 수행
  → Debate 결과가 다시 memory/wiki 로 축적
```

현재 (origin/main = 57dc052 기준) 흐름은 다르다.

```
Raw data source
  → debate_engine._build_shared_context() 가 직접 읽음
  → wiki_retriever 는 보조 keyword retrieval 일 뿐
```

즉, 현재 debate 는 **raw-source-first + wiki retrieval 보조** 구조다.
R9-B 트랙은 이를 **wiki-context-first + raw validation/fallback** 으로
전환하는 작업이며, B.1 은 그 첫 단계인 **설계 리뷰** 다.

본 문서는 코드를 변경하지 않는다. 다음을 산출한다.

1. 현재 raw source / wiki writer inventory
2. 목표 구조 (wiki-first) 와 현재 구조의 gap
3. wiki page frontmatter / wiki date index / wiki_context_pack 스키마 초안
4. monthly-first / date-window-aware 설계 원칙
5. opt-in migration plan (B2~B7 단계)
6. risk + acceptance metric

---

## 1. 핵심 원칙 — Monthly-first, Window-aware

```
구현 기본값:  monthly-first
설계 원칙:    date-window-aware
```

당장 custom date debate 전체를 구현하지 않는다. 하지만 **schema,
context pack, retrieval/filter 설계는 custom window 를 수용** 해야 한다.

### 1.1 왜 `period` 하나로 처리하면 안 되는가

`period = 2026-04` 하나에 모든 날짜 의미를 몰아넣으면 다음 문제가 발생한다.

| 시나리오 | 현재 위험 |
|---|---|
| 2026-04 리포트 작성 중인데 2026-05 wiki page 가 섞임 | 미래 정보 누수 |
| 2026-04 사건인데 page `updated_at` 이 2026-05 | retrieval mis-rank |
| 2026-04-08~17 특정 window debate 요청 | `period=2026-04` 만으로는 filtering 불가 |
| daily_update 가 01_Events 를 wipe + 재생성한 뒤 다른 디렉토리가 stale | source_cutoff 차이를 표현 못 함 |

→ 반드시 다음 필드로 의미를 분리해야 한다.

```
period_type
period_key
window_start
window_end
as_of_date
source_cutoff_date
generated_at
available_from
```

### 1.2 월별 page 의 기본 schema

```yaml
period_type: monthly
period_key: 2026-04
window_start: 2026-04-01
window_end: 2026-04-30
as_of_date: 2026-04-30
source_cutoff_date: 2026-04-30
generated_at: 2026-05-01T09:00:00+09:00
available_from: 2026-05-01T09:00:00+09:00
```

파일명은 기존 `2026-04_claim_xxx.md` 형태 유지. 의미는 frontmatter 가
부담한다.

### 1.3 custom date debate 의 장기 설계

custom date debate 는 다음 형태.

```
2026-04-08 ~ 2026-04-17
2026-04-15 ~ 2026-05-10
특정 이벤트 전후 2주
```

장기적으로 debate input builder 입력 schema 는 다음을 수용한다.

```json
{
  "period_type": "custom",
  "period_key": "custom_2026-04-08_2026-04-17",
  "window_start": "2026-04-08",
  "window_end": "2026-04-17",
  "as_of_date": "2026-04-17",
  "source_cutoff_date": "2026-04-17"
}
```

원칙:

- **월별 wiki page 는 canonical memory 로 유지**
- custom debate 요청 시:
  1. 월별 wiki page 중 window 가 겹치는 것만 선택
  2. raw source 는 custom window 로 필터링
  3. 임시 `wiki_context_pack` 만 생성
  4. 영구 wiki page 는 만들지 않음

저장 위치(임시):

```
debug/wiki_context_packs/custom_2026-04-08_2026-04-17.json
```

운영화 이후:

```
market_research/data/wiki_context_packs/custom/custom_2026-04-08_2026-04-17.json
```

### 1.4 Window overlap rule

```
page.window_start <= request.window_end
and
page.window_end   >= request.window_start
```

추가로 cutoff:

```
page.source_cutoff_date <= request.as_of_date
page.available_from     <= debate_run_time
```

> ⚠️ `updated_at` 기준 selection 금지. `updated_at` 은 파일 수정일이지
> 사건 발생일/정보 기준일이 아니다. 현재 `wiki_retriever._is_future_page`
> 는 `period` / `as_of_date` frontmatter + filename `YYYY-MM` fallback 만
> 보지만, source_cutoff_date / available_from 까지 본 적은 없다.

---

## 2. 현재 구조 정밀 inventory

### 2.1 `_build_shared_context()` raw source 11종 (debate_engine.py:569~946)

| # | Source | 진입점 | 형태 | 비고 |
|---|---|---|---|---|
| 1 | `data/news/{YYYY-MM}.json` | L593 `news_file.read_text` | 직접 file read | primary 필터 + topic counter + asset_impact_vector 합산 |
| 2 | `data/insight_graph/{YYYY-MM}.json` | L647 `graph_file.read_text` | 직접 file read | `transmission_paths` 추출, confidence ≥0.3 우선 |
| 3 | `data/macro/indicators.csv` | L814 `csv.reader` | 직접 file read | 최신 row → `bm_returns` guard_ctx |
| 4 | `wiki_retriever.retrieve_wiki_context()` | L775 | 함수호출 → wiki dir glob | keyword 기반 top-N (max 5, max_chars 2000) |
| 4-a | `wiki_retriever.get_pinned_fund_context()` | L754 | 함수호출 → 04_Funds 직접 read | fund_comment stage 만 |
| 4-b | `wiki_retriever.extract_fund_keywords_from_pinned()` | L758 | helper | pinned 본문에서 키워드 추출 → kw_sources 보강 |
| 5 | `wiki.canonical.load_canonical_regime()` | L723 | 함수호출 → 05_Regime_Canonical | **keyword source only**, 본문은 prompt 미주입 |
| 6 | `analyze.blog_analyst.build_monygeek_context(y, m)` | L809 | 함수호출 | monygeek 블로그 분석 |
| 7 | `report.timeseries_narrator.build_debate_narrative(y, m)` | L832 | 함수호출 → BM 시계열 + 뉴스 매칭 | timeseries 내러티브 prose |
| 8 | `analyze.claim_store.select_promoted_claims_for_period(period, fund_code)` | L899 | 함수호출 → claim_store SQLite/JSON | R9-A canonical claims (read-only) |
| 9 | `report.asset_coverage.build_asset_coverage_map(...)` | L876 | 함수호출 (derived) | primary_news + graph + wiki + timeseries + topic_counts 합성 |
| 10 | `report.asset_movement_anchor.build_asset_movement_anchors(...)` | L931 | 함수호출 (derived) | indicators.csv + transmission paths + claims |
| 11 | `_build_evidence_candidates(...)` | L614 | helper | 아래 11-a/b/c 직접 read |
| 11-a | `naver_research_adapter.load_adapted({YYYY-MM})` | L254 | 함수호출 → naver research pool | TIER1/2 primary research |
| 11-b | `data/news/{YYYY-MM}.json` (again) | L272 | 직접 file read | intensity≥6 + corroboration 필터 |
| 11-c | `_load_bew_contract(year, month)` | L323 | BEW contract JSON | `force_window_ids` 적용 lane |

**관찰**:

- 직접 raw read 4건 (`news` 2회, `insight_graph`, `indicators.csv`).
- 함수호출 8건 — 일부는 내부에서 다시 raw read (`build_debate_narrative`,
  `build_monygeek_context`, `claim_store`, `asset_movement_anchor` 등).
- `wiki_retriever` 1건 — keyword top-N (max 5 page, max 2000 char).
- canonical regime 은 **keyword source 로만** 쓰이고 본문은 prompt 에 없음.
  → 사용자가 "regime 이 debate primary context 가 되어야 한다" 라고
  말할 때, 현재 흐름은 그 의도와 어긋난다.

### 2.2 Wiki writer / 입력 source per directory

CLAUDE.md (market_research) §Architecture 와 실코드 매칭. 각 디렉토리의
writer / 입력 / 갱신 주기 / regenerate 정책을 정리한다.

| Dir | Writer | 입력 source | 갱신 주기 | wipe? | 비고 |
|---|---|---|---|---|---|
| `00_Index/` | `draft_pages._refresh_index` | 다른 wiki dir 카운트 | daily_update | wipe + rebuild | `wiki_index` type, frontmatter 빈약 |
| `01_Events/` | `draft_pages.write_event_page` | `data/news/{p}.json` `_event_group_id` 클러스터 | daily_update (Step 2.6) | **wipe + rebuild** | top salience N 만 유지 |
| `02_Entities/` | `draft_pages.write_entity_page` (+ `entity_builder.select_entity_candidates`) | `insight_graph/{p}.json` nodes + articles | daily_update (Step 2.6) | selective update | `graph_node_id` + taxonomy_topic exact gate |
| `03_Assets/` | `draft_pages.write_asset_page` + `asset_fund_enrichment_builder.build_asset_page` | topic bucket articles + `_ASSET_TOPIC_MAP` | daily_update | selective | enrichment layer 별도 |
| `04_Funds/` | `draft_pages.write_fund_page` + `asset_fund_enrichment_builder.build_fund_page` | `FUND_CONFIGS` + enrichment | daily_update | selective | pinned-only (R2 G7) |
| `05_Regime_Canonical/` | `canonical.update_canonical_regime` + `write_regime_history_page` | `regime_memory.json` | daily_update (Step 5) | overwrite | canonical SSOT |
| `06_Debate_Memory/` | `debate_memory.write_debate_memory_page` | debate draft_data + canonical regime snapshot | debate 실행 시 | append (period+ts) | **debate 산출** — contamination 주의 |
| `07_Graph_Evidence/` | `graph_evidence.write_transmission_paths_draft` + `write_transmission_paths_summary` | GraphRAG P1 `transmission_paths` | daily_update (Step 3) | overwrite | canonical 승격 금지 (현재 draft only) |
| `08_Claims/` | `claim_pages.write_claim_page` + `promote_claims` | R9-A claim normalization 결과 | claim promote 시 | idempotent (`_is_claim_wiki` 가드) | canonical claim / lineage memory |

**중요한 구분**:

- 01~05, 07 = raw source 에서 생성되는 **base/canonical context**.
- 06 = debate 이후 생성되는 **interpreted memory** (LLM 산출, 자기강화 위험).
- 08 = claim extraction 이후 생성되는 **canonical claim memory**.

### 2.3 `wiki_retriever` 의 현재 역할 (보조 layer 확정)

`retrieve_wiki_context(keywords, stage, fund_code, period, ...)` 시그니처.

- Allowed dirs 는 stage 별:
  - `market_debate` / `quarterly_debate` / `fund_comment`: `01_Events`,
    `02_Entities`, `03_Assets`, `05_Regime_Canonical` (4개).
  - **04_Funds 는 retrieve 에서 제외** (R2 G7) — pinned 단일 진입.
  - **06/07/08 은 retrieve 에서 항상 제외** — debate prompt 에 들어갈
    수 있는 wiki 는 사실상 01/02/03/05 만.
- 점수: keyword token hit count + length bucket + source bonus.
- 결과: max 5 page, page 당 380 char 발췌, 합 max 2000 char.
- Filter:
  - `_is_future_page` — frontmatter `period` / `as_of_date` / filename
    YYYY-MM > target period 이면 제외 (P0-2).
  - cluster cap 2 (P0-4) — 동일 event_group 과점 방지.
  - `fund_code` exact match (P0-1) — 04_Funds 게이팅 (현재는 차단됨).
- Trace key 18개 (`wiki_candidate_pages`, `wiki_selected_pages`,
  `skipped_*` 등).

**결론**: 현재 wiki 는

```
1. 04_Funds 1 page (pinned, fund_comment 만)
+
2. 01/02/03/05 에서 keyword top-5 × 380자 발췌 (max 2000자)
```

= 시장 debate 입장에서 wiki 가 차지하는 prompt 분량은 **최대 2 KB**.
반면 raw `news_summary_text` + `graph_paths_text` + `timeseries_narrative`
+ `asset_coverage_text` + `asset_movement_anchors_text` 합산은 보통
**8~20 KB**. 즉 wiki 는 *수치상으로도* 5~10% 의 보조 layer 다.

### 2.4 현재 frontmatter inventory (디렉토리별 1 page 샘플)

origin 57dc052 상태의 frontmatter (Sec 2.2 writer 가 실제로 박는 필드):

| Dir | period | window | as_of | cutoff | available_from | generated_at / updated_at | 기타 시간 단서 |
|---|---|---|---|---|---|---|---|
| 00_Index | ✗ | ✗ | ✗ | ✗ | ✗ | `updated_at` | — |
| 01_Events | `period` (월) | ✗ | ✗ | ✗ | ✗ | `updated_at` | `top_topics`, `event_id` |
| 02_Entities | `period` (월) | ✗ (단 `first_seen`/`last_seen`) | ✗ | ✗ | ✗ | `updated_at` | `graph_node_id`, `taxonomy_topic` |
| 03_Assets | `period` (월) | ✗ | ✗ | ✗ | ✗ | ✗ | `asset_class`, `generated_by` |
| 04_Funds | `period` (월) | ✗ | ✗ | ✗ | ✗ | ✗ | `fund_code` |
| 05_Regime_Canonical | ✗ (단 `since`) | ✗ | ✗ | ✗ | ✗ | `updated_at` | `dominant_narrative`, `topic_tags`, `weeks` |
| 06_Debate_Memory | `period` (월) | ✗ | ✗ | ✗ | ✗ | `debate_date` | `fund_code`, `linked_regime_since` |
| 07_Graph_Evidence | `period` (월) | ✗ | ✗ | ✗ | ✗ | `updated_at` | `phase`, `total_paths` |
| 08_Claims | `period` (월) | ✗ | ✗ | ✗ | ✗ | `promoted_at` | `claim_id`, `schema_version`, `promotion_rule` |

**관찰**:

- `period` (월) 외에 window / as_of / cutoff / available_from 어디에도 없다.
- 02_Entities 의 `first_seen`/`last_seen` 가 **유일하게 window 개념에 가깝다.**
- 06_Debate_Memory 의 `debate_date` 가 generated_at 에 가깝지만,
  available_from 과 분리되어 있지 않다.
- 8개 dir 중 6개에 `updated_at` 만 있고, 그조차 4개 dir 은 ISO timestamp,
  2개 dir 은 누락.

---

## 3. 현재 vs 목표 구조

### 3.1 현재 (raw-source-first + wiki 보조)

```
[Raw Sources]
  ├─ news/{period}.json
  ├─ insight_graph/{period}.json
  ├─ macro/indicators.csv
  ├─ naver_research adapted pool
  ├─ blog / monygeek context
  ├─ asset_movement_anchor (← indicators + paths + claims)
  ├─ asset_coverage (← primary news + paths + wiki + timeseries)
  ├─ claim_store (08_Claims 의 dual-anchor)
  ├─ BEW contract / forced windows
  └─ wiki_retriever (보조)

        ↓ _build_shared_context()

shared_context 약 25개 key (textual 6 + trace 7 + derived 12)

        ↓ _build_agent_prompt() / _synthesize_debate()

[Debate Agents: bull / bear / quant / monygeek] → Opus 종합
```

Wiki 위치:

```
[Wiki Pages]                       ← 보조 layer
  ├─ 01_Events                       (debate prompt 에 발췌 진입)
  ├─ 02_Entities                     (debate prompt 에 발췌 진입)
  ├─ 03_Assets                       (debate prompt 에 발췌 진입)
  ├─ 04_Funds                        (fund_comment pinned 만)
  ├─ 05_Regime_Canonical             (keyword source 만, 본문 미주입)
  ├─ 06_Debate_Memory                (현재 prompt 미주입)
  ├─ 07_Graph_Evidence               (현재 prompt 미주입)
  └─ 08_Claims                       (claim_store 경유, wiki 본문은 미주입)

        ↓ wiki_retriever.retrieve_wiki_context()

shared_context['wiki_context_text']  (max 2 KB)
```

### 3.2 목표 (wiki-context-first + raw validation/fallback)

```
[Raw Sources]
  news / graph / macro / benchmark / fund / claim / regime / blog / BEW
            │
            ▼

[Wiki Build Layer]                                    ← daily_update
  01_Events / 02_Entities / 03_Assets / 04_Funds /
  05_Regime_Canonical / 07_Graph_Evidence / 08_Claims
  (06_Debate_Memory 는 *debate 산출물*, build layer 아님)
            │
            ▼

[Wiki Context Pack Builder]                           ← new layer
  market_context_pack
  asset_context_pack
  fund_context_pack
  regime_context_pack
  claim_context_pack
  graph_context_pack
  prior_debate_memory_pack (opt-in)
            │
            ▼

[Validation Pack]                                     ← parallel branch
  raw_sources_used (for numeric guardrail / fallback)
  numeric_guardrails (indicators latest row, BM returns)
            │
            ▼

[Debate]
  primary input = wiki_context_pack
  validation input = validation_pack
  source_type 구분: raw_evidence / canonical_memory /
  interpreted_memory / fund_context / regime_context /
  claim_memory / validation_source
            │
            ▼

[Debate Output → 06_Debate_Memory + 08_Claims (추가 promotion)]
```

### 3.3 가장 큰 gap

| 항목 | 현재 | 목표 | gap |
|---|---|---|---|
| primary context | raw text (8~20 KB) | wiki context pack | raw 가 99% 의 prompt 분량 차지 |
| wiki 본문 진입 | 발췌 380자 × 5 page | 디렉토리별 full / summary 섹션 | retrieval depth + structure 부족 |
| 06_Debate_Memory | prompt 미주입 | opt-in prior memory pack | contamination guard 필요 |
| 07_Graph_Evidence | prompt 미주입 | causal path memory pack | 현재 graph_paths_text 는 raw insight_graph 에서 매번 재추출 |
| 08_Claims | claim_store 경유, wiki 본문 미주입 | claim_context_pack + wiki page join | 현재 claim wiki path 는 persistence 만 |
| 05_Regime_Canonical | keyword source 만 | regime_context_pack 본문 주입 | "regime anchor" 가 사실상 미작동 |
| date 의미 분리 | `period` (월) 1개 | period_type / window / as_of / cutoff / available_from | future-leakage 방어 부분만 (`_is_future_page`), source_cutoff / available_from 없음 |
| custom window | 불가 | 월별 page overlap + custom context pack | schema 자체가 없음 |

### 3.4 한 문장 요약

> **현재**: raw source 가 debate 의 primary context 이고, wiki 는
> auxiliary context 다.
> **목표**: wiki context pack 이 debate 의 primary context 이고, raw
> source 는 validation / fallback source 다.

---

## 4. Raw source 분류표

분류 기준:

- **A** — 반드시 raw 유지 (evidence/숫자 검증)
- **B** — wiki page 로 대체 가능
- **C** — wiki primary + raw validation 병행
- **D** — wiki 가 있는데 debate 가 raw 를 다시 읽음 (중복)
- **E** — debate 산출 memory (contamination guard 필요)

| Source | Class | Current use | Wiki equivalent | Proposed role | Date/window policy | Notes |
|---|---|---|---|---|---|---|
| `news/{p}.json` evidence cards / topic counter | C | `news_summary_text` + `_evidence_ids` | 01_Events (이미 build 중) | wiki primary + raw evidence_id resolution | window_start/end overlap + source_cutoff | 원문 evidence 는 raw 유지 필요 (article_id → 본문) |
| `news/{p}.json` (primary_classified, intensity≥6) | A | `_build_evidence_candidates` Lane B | 01_Events salience metadata | raw evidence (no change) | window overlap | quality gate 는 raw 단계가 적합 |
| `naver_research_adapter.load_adapted` | A | Lane A primary research | 01_Events + 02_Entities 보강 | raw evidence | research_quality_band 유지 | TIER1/2 메타는 wiki 까지 안 올라가 있음 |
| `insight_graph/{p}.json` `transmission_paths` | D | `graph_paths_text` (raw 재추출) | **07_Graph_Evidence (이미 build 됨!)** | wiki primary | period + window overlap | 현재 wiki 는 prompt 미주입 — 가장 명백한 중복 |
| `macro/indicators.csv` 최신 row | C | `indicators_text` + `_guard_data_ctx` + asset_movement_anchor | 03_Assets / 05_Regime_Canonical 일부 | raw validation (numeric guardrail) | as_of_date cutoff | LLM 반올림 금지 — raw 유지 |
| `claim_store.select_promoted_claims_for_period` | D | `claims_text` (`_format_claims_for_context`) | **08_Claims (이미 wiki page 있음)** | wiki primary + canonical lineage | period_key + event_start/end | wiki path 는 persist 되지만 prompt 는 store 경유 |
| `wiki.canonical.load_canonical_regime` | D | **keyword source 만** | **05_Regime_Canonical (이미 build 됨!)** | wiki primary (regime anchor) | as_of_date / since / weeks | 본문이 prompt 에 안 들어가는 게 가장 큰 누수 |
| `blog_analyst.build_monygeek_context` | B | `blog_context_text` | 03_Assets 일부 또는 별도 09_Blog | monygeek-only pack | window overlap | 단일 블로거 관점 — 자기참조 위험 |
| `timeseries_narrator.build_debate_narrative` | B | `timeseries_narrative_text` | (없음 — narrative 자체는 LLM-free synth) | wiki primary or raw narrative | window overlap | derived narrative; wiki 화 가능하지만 비용 ↑ |
| `asset_coverage.build_asset_coverage_map` | A | `asset_coverage_text` + `_asset_coverage` | (없음) | derived validation (raw) | as_of_date | guardrail 성격이라 raw 가 적합 |
| `asset_movement_anchor.build_asset_movement_anchors` | C | `asset_movement_anchors_text` + `_asset_movement_anchors` | 03_Assets / 08_Claims affected_assets | wiki primary + raw indicator validation | as_of_date + period_key | claim affected_assets / BM 변동 / graph path 3원 결합 |
| `_load_bew_contract` (BEW) / `force_window_ids` | A | `_build_evidence_candidates` BEW lane | (없음) | raw evidence selection lane | event_start / event_end | viewer 산출, wiki 화 부적합 |
| `wiki_retriever.retrieve_wiki_context` | (현행) | top-5 발췌 (max 2KB) | (자기자신) | **wiki_context_pack 으로 격상** | period + window overlap + cluster cap | 발췌 폭/depth 재설계 필요 |
| `wiki_retriever.get_pinned_fund_context` | (현행) | 04_Funds exact pinned | (자기자신) | wiki_context_pack > fund_context | period + fund_code exact | retrieve 와 source 분리 유지 |
| `06_Debate_Memory` | E | prompt 미주입 | (자기자신) | opt-in prior_debate_memory_pack | available_from < current_debate_start | 자기강화 차단 필수 |

**가장 명백한 quick win** (D 클래스): 07_Graph_Evidence / 05_Regime_Canonical /
08_Claims 본문이 *wiki 에 이미 빌드되어 있는데* prompt 는 raw 에서 재조립
한다. B2 단계에서 이 3개부터 wiki context pack 으로 끌어올리면 가장 큰
구조 변경 없이 wiki-first 비중을 올릴 수 있다.

---

## 5. Wiki directory 별 debate input 역할 정의

### 00_Index

- 사용 목적: 전체 wiki 상태 / count / coverage overview.
- debate primary input 으로는 사용하지 않음 (메타 페이지).
- date handling: `generated_at` 만 있으면 충분.
- 추가 필드: `wiki_pages_total`, `pages_by_dir`, `last_daily_update_at`.

### 01_Events

- 사용 목적: 월간 주요 이벤트 context.
- debate role: **market event memory** (primary).
- daily_update 시 wipe + rebuild — context pack 입장에서는 build 직후
  최신 상태를 읽는다고 가정.
- date handling 필요: `event_start_date` / `event_end_date` /
  `source_cutoff_date`. 현재는 `period` (월) + `updated_at` 만.
- 추가 필드 제안: `dominant_topic`, `affected_asset_classes`,
  `top_article_ids` (이미 있는 `top_topics` 와 짝).

### 02_Entities

- 사용 목적: 거시/시장 entity 및 causal relation.
- debate role: **causal entity memory** (primary, taxonomy gate 통과 후보).
- date handling 필요: `first_seen` / `last_seen` 는 이미 있음. 추가로
  `window_start` / `window_end` / `source_cutoff_date`.
- 추가 필드 제안: `linked_event_ids`, `linked_claim_ids`,
  `node_centrality_rank`.

### 03_Assets

- 사용 목적: 자산군별 월간 흐름 및 기사 집계.
- debate role: **asset-class memory** (primary).
- date handling 필요: `period_key` + `window_start` / `window_end` +
  `as_of_date`.
- 추가 필드 제안: `bm_return_monthly`, `bm_anomaly_days`,
  `top_event_ids`, `top_claim_ids`.

### 04_Funds

- 사용 목적: 펀드별 특성 / 보유 / MP / enrichment.
- debate role: market_debate 에서는 **제외**. fund_comment 에서는
  **pinned input** (currently 단일 진입로 — R2 G7).
- date handling 필요: `holdings_as_of` / `pa_period_start` /
  `pa_period_end` / `report_period` + `generated_at`.
- 추가 필드 제안: `fund_code`, `nav_as_of_date`, `mp_release_date`,
  `top_asset_classes`.

### 05_Regime_Canonical

- 사용 목적: regime canonical state (현재 가장 큰 누수).
- debate role: **regime anchor** (primary — 본문 주입 필수).
- date handling 필요: `as_of_date` / `valid_from` / `valid_to` +
  `available_from`. 현재는 `since` / `weeks` / `updated_at` 만.
- 추가 필드 제안: `dominant_narrative_history[]`, `regime_strength_score`,
  `last_shift_at`.

### 06_Debate_Memory

- 사용 목적: 과거 debate 해석.
- debate role: **opt-in prior interpretation memory**.
- ⚠️ contamination 차단 필수: 이전 debate 의 LLM 해석이 현재 debate 를
  자기강화하지 않도록 source_type 을 별도로 표시.
- date handling 필요: `generated_at` / `available_from` 필수.
  `available_from >= current_debate_start_time` 이면 제외.
- 추가 필드 제안: `memory_type: debate_interpretation`,
  `source_period_key`, `generated_by_run_id`, `linked_regime_at_time`.

### 07_Graph_Evidence

- 사용 목적: GraphRAG transmission path memory.
- debate role: **causal path memory** (primary).
- 현재 wiki page 있지만 prompt 미주입 → D 클래스 (가장 명백한 quick win).
- date handling 필요: `path_start_date` / `path_end_date` /
  `source_cutoff_date` + `phase` (P0/P1).
- 추가 필드 제안: `selected_path_count`, `avg_confidence`,
  `affected_asset_classes`.

### 08_Claims

- 사용 목적: canonical claim memory / stable lineage.
- debate role: **claim memory** (primary, claim_store join 필요).
- 현재 wiki path 는 persist 되지만 prompt 는 store 만 본다 → D 클래스.
- date handling 필요: `event_start_date` / `event_end_date` /
  `source_latest_date` / `period_key` + `promoted_at` (이미 있음) +
  `available_from`.
- 추가 필드 제안: `canonical_group_id`, `related_group_ids`,
  `affected_assets` (이미 body 에 있음 → frontmatter 로 끌어올림),
  `lineage_rule` (R9-A.21A dual-anchor).

---

## 6. Wiki page frontmatter 표준 초안

### 6.1 공통 필드 (모든 page 가 반드시 가짐)

```yaml
---
page_id: claim:2026-04:e78dc83a1e        # 자연 키 (type+period+id)
page_type: claim                          # 디렉토리별 enum
period_type: monthly                      # monthly | custom (custom 미지원시 monthly 고정)
period_key: 2026-04                       # YYYY-MM 또는 custom_YYYY-MM-DD_YYYY-MM-DD
window_start: 2026-04-01
window_end:   2026-04-30
as_of_date:   2026-04-30                  # 데이터 기준일 (LLM/계산 입력의 latest)
source_cutoff_date: 2026-04-30            # 이 시점 이후 source 는 *반영 안 됨*
generated_at: 2026-05-01T09:00:00+09:00   # 페이지 작성 시각
available_from: 2026-05-01T09:00:00+09:00 # 이 시점부터 retrieval 노출 가능 (debate run 시간 비교용)
source_types:                             # 어떤 raw 입력으로 만들어졌는지
  - news
  - claim_store
source_hash: <sha10>                       # 입력 source 결정성 — 변경 감지용
schema_version: r9b-page-1.0.0            # frontmatter schema 버전
---
```

### 6.2 디렉토리별 추가 필드

(공통 필드 + 아래)

```yaml
# 01_Events
page_type: event
event_id: <id>
event_start_date: 2026-04-08              # ← 신규
event_end_date:   2026-04-17              # ← 신규
dominant_topic: 환율_FX
affected_asset_classes: [환율(FX), 해외주식]
top_topics: [환율_FX, 지정학, 테크_AI_반도체]
top_article_ids: [...]                    # primary article_id 목록
source_count: 217
avg_salience: 0.638

# 02_Entities
page_type: entity
entity_id: graphnode__AI
label: "AI"
taxonomy_topic: 테크_AI_반도체
graph_node_id: AI
node_importance: 0.9128
first_seen: 2026-02-09                    # 기존 유지
last_seen:  2026-04-29                    # 기존 유지
window_start: 2026-04-01                  # 신규 (page-level window)
window_end:   2026-04-30
linked_event_ids: [event_08e72409d0, ...]
linked_claim_ids: [claim:2026-04:..., ...]

# 03_Assets
page_type: asset
asset_class: 국내주식
bm_return_monthly: -1.32
bm_anomaly_days: 3
top_event_ids: [...]
top_claim_ids: [...]

# 04_Funds
page_type: fund
fund_code: 07G04
holdings_as_of: 2026-04-30
pa_period_start: 2026-04-01
pa_period_end:   2026-04-30
mp_release_date: 2026-03-15
top_asset_classes: [해외주식, 국내채권, ...]

# 05_Regime_Canonical
page_type: regime
status: confirmed
tag_match_mode: exact_taxonomy
dominant_narrative: "지정학 + 물가_인플레이션"
topic_tags: [지정학, 물가_인플레이션]
since: 2026-04-01
valid_from: 2026-04-01                    # 신규
valid_to:   null                          # 신규 (현재 regime 은 null)
direction: neutral
weeks: 6
regime_strength_score: 0.71               # 신규 (옵션)
last_shift_at: 2026-04-01

# 06_Debate_Memory
page_type: debate_memory
status: provisional
memory_type: debate_interpretation        # 신규 — contamination 식별용
source_period_key: 2026-03                # 신규
generated_by_run_id: <uuid>               # 신규
fund_code: _market
debate_date: 2026-04-23T16:25:10
linked_regime_at_time: "지정학 + 물가_인플레이션"
linked_regime_since: 2026-04-01

# 07_Graph_Evidence
page_type: graph_evidence
status: draft
phase: P1
promoted_to_canonical: false
total_paths: 4
selected_path_count: 4
node_count: 246
edge_count: 231
avg_confidence: 0.32                      # 신규
affected_asset_classes: [...]              # 신규
path_start_date: 2026-02-01                # 신규
path_end_date:   2026-02-28

# 08_Claims
page_type: claim
claim_id: claim:2026-04:e78dc83a1e
schema_version: r9a-claim-1.0.0
extractor_version: r9a.1-haiku
promotion_rule: B
canonical_group_id: group:2026-04:cfee0ff342    # 신규 (R9-A 후속과 자연 연동)
related_group_ids: [group:2026-04:cfee0ff342]   # 신규
affected_assets: [국내주식, 환율(FX)]            # frontmatter 승격
event_start_date: 2026-04-08                     # 신규
event_end_date:   2026-04-17                     # 신규
source_latest_date: 2026-04-17                   # 신규
lineage_rule: dual_anchor_v1                     # R9-A.21A
```

**원칙**:

- 기존 필드는 **삭제 금지** (backward compat). 신규 필드는 missing 시
  default null/empty 로 처리.
- frontmatter 가 점점 길어지면 별도 `*.frontmatter.yaml` 분리 고려
  (B5 이후).

---

## 7. Wiki date index 설계

매번 frontmatter 파싱하는 대신 **append-only date index** 를 둔다.

### 7.1 경로

```
market_research/data/wiki/00_Index/wiki_date_index.jsonl
```

(00_Index 안에 두는 이유: 기존 index 디렉토리와 위치 일관. 별도 `.index/`
경로도 후보.)

### 7.2 Row schema

```json
{
  "page_id": "claim:2026-04:e78dc83a1e",
  "path": "08_Claims/2026-04_claim_e78dc83a1e.md",
  "page_type": "claim",
  "period_type": "monthly",
  "period_key": "2026-04",
  "window_start": "2026-04-01",
  "window_end": "2026-04-30",
  "as_of_date": "2026-04-30",
  "source_cutoff_date": "2026-04-30",
  "available_from": "2026-05-01T09:00:00+09:00",
  "updated_at": "2026-05-13T13:20:00+09:00",
  "source_hash": "<sha10>",
  "claim_id": "e78dc83a1e",
  "canonical_group_id": "group:2026-04:cfee0ff342",
  "schema_version": "r9b-page-1.0.0"
}
```

### 7.3 갱신 정책

- daily_update Step 2.6 / Step 5 / claim promote / debate save 가 끝날
  때마다 **affected row 만 append**. 같은 page_id 가 여러 번 나오면
  마지막 row 가 latest.
- 별도 compaction 스크립트 (`tools/compact_wiki_date_index.py`, B6) 가
  주기적으로 중복 제거.

### 7.4 Selection 기준

```
period_key == request.period_key
또는
window_start <= request.window_end AND window_end >= request.window_start
AND source_cutoff_date <= request.as_of_date
AND available_from <= debate_run_time
AND page_type in allowed_dir_types
AND (stage allowed for page_type)
```

> ⚠️ **`updated_at` 으로 selection 금지** — `updated_at` 은 파일 수정
> 타임이라 stale page 가 최신처럼 보일 위험.

### 7.5 마이그레이션

- B1 (현 단계): 인덱스 없음. 기존 retrieve 동작 그대로.
- B2: builder 가 인덱스 생성 (현재 frontmatter 에 없는 필드는 best-effort
  추정 — 예: filename 의 YYYY-MM → window).
- B3: dry-run 시 인덱스 vs 직접 glob 차이 비교.
- B4 이후: 인덱스가 source of truth.

---

## 8. Wiki Context Pack schema

### 8.1 Top-level

```json
{
  "schema_version": "r9b-context-pack-1.0.0",
  "period_type": "monthly",
  "period_key": "2026-04",
  "window_start": "2026-04-01",
  "window_end": "2026-04-30",
  "as_of_date": "2026-04-30",
  "stage": "market_debate",
  "fund_code": null,
  "mode": "wiki_first",
  "generated_at": "2026-05-01T09:00:00+09:00",
  "debate_run_id": null,

  "market_context": { ... },
  "asset_context": { ... },
  "fund_context": { ... },
  "regime_context": { ... },
  "claim_context": { ... },
  "graph_context": { ... },
  "prior_memory": { ... },

  "validation_pack": { ... },
  "source_trace": { ... },
  "warnings": []
}
```

### 8.2 `market_context` (01_Events + 02_Entities 결합)

```json
{
  "events": [
    {
      "page_id": "event:2026-04:08e72409d0",
      "path": "01_Events/2026-04_event_08e72409d0.md",
      "dominant_topic": "환율_FX",
      "event_start_date": "2026-04-08",
      "event_end_date": "2026-04-17",
      "affected_asset_classes": ["환율(FX)", "해외주식"],
      "source_count": 217,
      "avg_salience": 0.638,
      "excerpt": "(본문 400~800자)",
      "source_type": "canonical_memory"
    }
  ],
  "entities": [
    {
      "page_id": "entity:graphnode__AI",
      "label": "AI",
      "taxonomy_topic": "테크_AI_반도체",
      "node_importance": 0.9128,
      "linked_event_ids": [...],
      "excerpt": "...",
      "source_type": "canonical_memory"
    }
  ]
}
```

### 8.3 `asset_context` (03_Assets)

```json
{
  "assets": [
    {
      "page_id": "asset:2026-04:국내주식",
      "asset_class": "국내주식",
      "bm_return_monthly": -1.32,
      "bm_anomaly_days": 3,
      "top_event_ids": [...],
      "excerpt": "...",
      "source_type": "canonical_memory"
    }
  ]
}
```

### 8.4 `fund_context` (04_Funds, fund_comment 전용)

```json
{
  "fund_page": {
    "page_id": "fund:2026-04:07G04",
    "fund_code": "07G04",
    "holdings_as_of": "2026-04-30",
    "pa_period_start": "2026-04-01",
    "pa_period_end": "2026-04-30",
    "top_asset_classes": ["해외주식", "국내채권"],
    "excerpt": "...",
    "source_type": "fund_context"
  },
  "fund_claims": [...],
  "fund_asset_exposures": [...]
}
```

(market_debate stage 에서는 `fund_context.fund_page = null`)

### 8.5 `regime_context` (05_Regime_Canonical)

```json
{
  "current": {
    "dominant_narrative": "지정학 + 물가_인플레이션",
    "topic_tags": ["지정학", "물가_인플레이션"],
    "narrative_description": "...",
    "since": "2026-04-01",
    "valid_from": "2026-04-01",
    "valid_to": null,
    "weeks": 6,
    "direction": "neutral",
    "excerpt": "(현재 regime 본문 300자)",
    "source_type": "regime_context"
  },
  "recent_history": [
    {"narrative": "...", "valid_from": "...", "valid_to": "..."}
  ]
}
```

### 8.6 `claim_context` (08_Claims, claim_store join)

```json
{
  "claims": [
    {
      "page_id": "claim:2026-04:e78dc83a1e",
      "claim_id": "claim:2026-04:e78dc83a1e",
      "canonical_group_id": "group:2026-04:cfee0ff342",
      "related_group_ids": [...],
      "claim_text": "...",
      "claim_type": "...",
      "affected_assets": [...],
      "event_start_date": "2026-04-08",
      "event_end_date": "2026-04-17",
      "promotion_rule": "B",
      "supporting_evidence_ids": [...],
      "wiki_path": "08_Claims/...",
      "excerpt": "(causal chain 200자)",
      "source_type": "claim_memory"
    }
  ],
  "claim_store_to_wiki_join_rate": 1.0
}
```

### 8.7 `graph_context` (07_Graph_Evidence)

```json
{
  "transmission_paths": [
    {
      "page_id": "graph:2026-04:...",
      "path_id": "p1",
      "labels": [...],
      "confidence": 0.42,
      "tier": "보조",
      "target": "국내주식",
      "affected_asset_classes": [...],
      "phase": "P1",
      "excerpt": "...",
      "source_type": "canonical_memory"
    }
  ]
}
```

### 8.8 `prior_memory` (06_Debate_Memory, opt-in)

```json
{
  "include_policy": "disabled",       // disabled | summary_only | full
  "debate_memory": [
    {
      "page_id": "debate_memory:2026-03:...",
      "memory_type": "debate_interpretation",
      "source_period_key": "2026-03",
      "generated_by_run_id": "<uuid>",
      "debate_date": "2026-04-23T16:25:10",
      "linked_regime_at_time": "...",
      "excerpt": "(summary 200자)",
      "source_type": "interpreted_memory"
    }
  ]
}
```

**contamination guard**:

- `available_from >= current_debate_start_time` → 제외.
- 같은 `generated_by_run_id` 의 memory → 제외 (re-run 자기참조 차단).
- include_policy 기본 `disabled`. summary_only 도입은 별도 평가 필요.

### 8.9 `validation_pack`

```json
{
  "raw_sources_used": [
    "data/news/2026-04.json",
    "data/macro/indicators.csv",
    "data/insight_graph/2026-04.json"
  ],
  "numeric_guardrails": {
    "bm_returns": {"MSCI ACWI": -2.3, ...},
    "macro_latest": {"UST_10Y": 4.25, ...}
  },
  "source_cutoff_date": "2026-04-30",
  "evidence_pool": {
    "research_count": 12,
    "news_count": 3,
    "bew_consumed": [...]
  }
}
```

### 8.10 `source_trace`

```json
{
  "wiki_pages_considered": 0,
  "wiki_pages_selected": 0,
  "selected_wiki_paths": [],
  "selected_claim_ids": [],
  "selected_related_group_ids": [],
  "raw_sources_used_for_validation": [],
  "source_type_counts": {
    "canonical_memory": 0,
    "interpreted_memory": 0,
    "fund_context": 0,
    "regime_context": 0,
    "claim_memory": 0,
    "validation_source": 0,
    "raw_evidence": 0
  },
  "skipped_future_pages": 0,
  "skipped_cutoff_violations": 0,
  "skipped_available_from_violations": 0,
  "claim_store_to_wiki_join_rate": 0.0,
  "window_overlap_selected_count": 0
}
```

### 8.11 `warnings`

```json
[
  {"code": "no_regime_page", "msg": "..."},
  {"code": "future_leakage_detected", "msg": "..."},
  {"code": "wiki_pages_selected_zero", "msg": "..."}
]
```

### 8.12 source_type 분류

prompt 에 주입될 때 LLM 이 구분할 수 있도록 다음을 명시한다.

| source_type | 의미 | 예 |
|---|---|---|
| `raw_evidence` | 원문 기사 | news article body |
| `canonical_memory` | base wiki page (build layer 산출) | 01_Events / 02_Entities / 03_Assets / 07_Graph_Evidence |
| `interpreted_memory` | 이전 debate 의 해석 | 06_Debate_Memory |
| `fund_context` | 04_Funds pinned | fund_comment 전용 |
| `regime_context` | 05_Regime_Canonical | current regime 본문 |
| `claim_memory` | 08_Claims canonical | promoted claim |
| `validation_source` | raw numeric guardrail | indicators.csv 최신 row |

---

## 9. Debate input 우선순위 (현재 vs 목표)

### 9.1 현재

```
shared_context = {
  bm_text, pa_text, indicators_text, news_summary_text,
  graph_paths_text, blog_context_text, wiki_context_text,
  timeseries_narrative_text, asset_coverage_text,
  asset_movement_anchors_text, claims_text, ...
}

→ raw text 들이 _build_agent_prompt() 에서 단순 concat
→ wiki_context_text 는 최대 2KB (~5%)
```

### 9.2 목표

```
shared_context = {
  wiki_context_pack: { ... },           # 8KB~16KB primary
  validation_pack: { ... },             # 1KB~3KB
  raw_pack: {                           # fallback only
    news_summary_text: "",              # wiki_context_pack 으로 대체
    graph_paths_text: "",               # 07_Graph_Evidence 로 대체
    claims_text: "",                    # claim_context 로 대체
    ...
  }
}

→ _build_agent_prompt() 가 wiki_context_pack 을 *섹션별로* 구조화 주입
→ raw_pack 은 source_type=validation_source 표시로 보조 진입
```

### 9.3 5-step pipeline

```
Step 1. raw sources → wiki pages (이미 build layer 존재)
Step 2. wiki_context_pack builder (B2 신규)
Step 3. raw validation pack builder
Step 4. shared_context = wiki_context_pack + validation_pack
Step 5. _build_agent_prompt() 가 source_type 구분해 prompt 조립
```

---

## 10. Opt-in migration plan (B2~B7)

기존 debate 결과가 갑자기 바뀌지 않도록 **opt-in flag** 부터.

**flag**: `--wiki-first-context` (debate CLI / fund_comment_service)
**기본값**: `False`
**환경변수**: `R9B_WIKI_FIRST=0|1` (CI/배치 토글)

| Phase | 작업 | LLM 비용 | 운영 영향 | 산출물 |
|---|---|---|---|---|
| **B1 (현재)** | 설계 문서 (this) | $0 | 0 | `r9b_wiki_first_debate_architecture.md` |
| **B2** | wiki_context_pack builder 구현 (read-only). debate prompt 미주입. debug dump 만 | $0 | 0 | `wiki_context_pack_builder.py`, `debug/wiki_context_packs/*.json` |
| **B3** | dry-run comparison — raw-first vs wiki-first 차이 비교 (token len, selected pages, source coverage, claim join rate) | $0~$0.05 (소량 LLM 비교) | 0 | `debug/wiki_first_dryrun_report.md` |
| **B4** | debate opt-in — `--wiki-first-context` 사용 시에만 wiki_context_pack 을 prompt 주입. 기존 raw 경로 그대로 유지 | $0.10~0.30 / debate | flag 사용시에만 | debate output `_context_mode` 필드 추가 |
| **B5** | gradual raw source reduction — wiki 로 대체된 raw 의 비중 축소. 단 `news_summary_text` (evidence card) / `indicators_text` / `_guard_data_ctx` 는 validation 으로 유지 | $0 | flag 사용시 prompt 길이 ↓ | debate prompt 길이 metrics |
| **B6** | UI/debug surface — `wiki_pages_selected`, `selected_wiki_paths`, `source_type_distribution`, `raw_validation_sources`, window 표시 | $0 | admin 탭 추가 | `tabs/admin_macro.py` wiki_context surface |
| **B7** | custom date support — monthly page overlap filtering + custom wiki_context_pack 생성. 영구 custom wiki page 는 별도 정책 결정 후 | $0~$0.10 | custom CLI 옵션 추가 | `--window-start/-end` debate CLI flag |

### 10.1 B4 부분 도입 strategy

- 첫 1 cycle: `--wiki-first-context` 를 *market_debate 만* 적용 (fund_comment
  는 raw 유지 — pinned 가 이미 wiki-first 에 가깝다).
- 2~3 cycle: market 비교 결과 OK 면 fund_comment 도 enable.
- 최종: 기본값 True 로 전환 + raw 경로는 fallback only.

### 10.2 Rollback 조건

각 phase 에서 다음 중 하나라도 발생하면 즉시 이전 phase 로 rollback:

- `wiki_pages_selected = 0` (page 가 없는 게 아니라 selection 실패)
- token budget 50% 초과
- `claim_store_to_wiki_join_rate < 0.5` (join 실패)
- 최종 코멘트 자산군 mention 가 raw-first 대비 30% 이상 감소

---

## 11. Risk 정리

### R1. Raw evidence ↔ interpreted memory 혼동

- 위험: 뉴스 원문과 wiki 해석을 같은 evidence 처럼 취급하면 LLM 이
  사실/해석 구분 못 함.
- 대응: prompt 섹션에 `[source_type]` 헤더 명시. `source_type=raw_evidence`
  만 [ref:N] 인용 대상.

### R2. Debate memory contamination

- 위험: 06_Debate_Memory 를 무조건 재사용하면 이전 LLM 해석이
  자기강화.
- 대응: `prior_memory.include_policy = disabled` 기본. summary_only 도
  별도 평가 후 도입.

### R3. Wiki staleness

- 위험: wiki page 가 daily_update 에서 재생성되지 않았거나
  source_hash 가 stale.
- 대응: `source_hash` 비교 + `available_from` cutoff + warning code
  `wiki_stale_page`.

### R4. Event page wipe/rebuild

- 위험: 01_Events 는 daily_update 시 wipe + rebuild. 다른 디렉토리는
  selective. context pack 이 wipe 중간에 잡으면 부분 상태.
- 대응: daily_update 종료 시 `wiki_build_completed_at` 마커. context pack
  builder 는 이 마커 이후 read.

### R5. Claim under-selection (R9-A.21A 연동)

- 위험: 08_Claims 는 Rule A/B selection 과 wiki page join 필요. store
  selected claim 과 wiki page 가 불일치할 수 있음 (R9-A 트랙에서 이미
  관측된 패턴).
- 대응: `claim_store_to_wiki_join_rate` metric 추적. <1.0 이면 warning.

### R6. Token budget

- 위험: wiki page 전체를 넣으면 prompt 가 길어짐. 현재 wiki 2KB → 목표
  8~16KB → 시장 debate prompt 30KB 도달 가능.
- 대응: page 당 excerpt cap (400~800자) + section 별 max count + 전체
  cap (예: market_context_pack 8KB, claim_context 4KB).

### R7. Fund vs market stage 차이

- 위험: market_debate 에서 04_Funds 노출 시 시장 debate 가 fund-specific
  해석 흡수 (이미 R2 G7 fix 됨).
- 대응: stage 별 wiki_context_pack 섹션 enable/disable contract.
  market_debate → fund_context = null.

### R8. Evaluation difficulty

- 위험: wiki-first 가 raw-first 보다 좋은지 비교 기준이 없음.
- 대응: B3 dry-run report 에 다음 metric 병기 — token usage,
  selected_count, claim join rate, asset coverage pass, evidence
  attribution rate.

### R9. Future-data leakage

- 위험: `updated_at` 기준 selection 하면 미래 page 가 통과.
- 대응: `source_cutoff_date` / `available_from` 양쪽 cutoff 필수.
  `_is_future_page` 는 이미 frontmatter `period`/`as_of_date` 본다 —
  여기에 두 필드 추가.

### R10. Custom window explosion

- 위험: custom date 마다 영구 wiki page 만들면 폭증.
- 대응: 월별 page 만 canonical. custom 은 `debug/wiki_context_packs/`
  임시 산출물.

### R11. Backward compat 깨짐

- 위험: frontmatter 신규 필드 누락 page 에서 builder 가 KeyError.
- 대응: 모든 신규 필드 default null/empty + `schema_version` 으로 분기.

---

## 12. Acceptance / evaluation metrics

각 metric 은 B3 dry-run report 및 B4 이후 운영 trace 에 포함.

### 12.1 Coverage metrics

- `wiki_pages_considered` — index 단계 통과 후보 수
- `wiki_pages_selected` — pack 에 들어간 수
- `selected_wiki_paths` — 실제 path 목록
- `source_type_distribution` — pack 내 source_type 별 count
- `08_Claims_selected_count`
- `03_Assets_selected_count`
- `07_Graph_Evidence_selected_count`
- `05_Regime_selected` — bool (regime page 가 prompt 에 본문 진입했는가)

### 12.2 Join metrics (가장 중요)

- `claim_store_to_wiki_join_rate` — store selected claim 중 wiki page
  매칭된 비율. 목표 **= 1.0**.
- `event_to_entity_join_rate` — 01_Events 와 02_Entities 의 linked_event_ids
  매칭 비율.
- `transmission_path_to_asset_join_rate`.

### 12.3 Date hygiene

- `date_window_overlap_selected_count`
- `source_cutoff_violations` — 목표 **= 0**.
- `available_from_violations` — debate run time 이전에 available 인 page
  가 잘못 선택된 수. 목표 0.
- `future_leakage_warnings`.

### 12.4 Budget / size

- `wiki_context_pack_bytes`
- `validation_pack_bytes`
- `prompt_total_chars`
- `raw_source_fallback_count` — wiki 가 비어 raw 로 떨어진 횟수.

### 12.5 Output quality (downstream)

- debate output asset coverage pass (기존 metric 유지)
- final_comment evidence attribution coverage
- numeric guardrail violations (`numeric_guard.py`)

### 12.6 가장 중요한 4가지 합격선

```
wiki_pages_selected > 0
claim_store_to_wiki_join_rate >= 0.9
source_type 에 wiki_memory 와 raw_evidence 가 분리 표시됨
source_cutoff_violations = 0
```

---

## 13. 이번 작업에서 하지 말 것

**금지** (B1 = 설계 리뷰 단계):

- `debate_engine.py` / `daily_update.py` / `wiki_retriever.py` /
  prompt / writer 코드 변경
- 실제 debate 실행
- LLM 호출
- 운영 wiki / claims / report_output / regime_memory.json 변경

**허용**:

- 코드 읽기
- 현재 구조 조사 (위 Section 2 inventory)
- 설계 문서 작성 (this)
- risk / migration plan 작성

---

## 14. 산출물

### 필수

- `market_research/docs/r9b_wiki_first_debate_architecture.md` ← this file

### 선택 (gitignored 영역)

- `debug/wiki/r9b_current_source_inventory.json`
- `debug/wiki/r9b_current_source_inventory.md`

---

## 15. Acceptance Criteria 체크

| # | 기준 | 충족 위치 |
|---|---|---|
| 1 | 현재 `_build_shared_context` raw source 목록 정리 | §2.1 (11종 + sub) |
| 2 | raw-source-first vs wiki-first 구조 차이 명확화 | §3.1~3.4 |
| 3 | wiki directory 별 debate input 역할 정의 | §5 (00~08) |
| 4 | raw source 별 A/B/C/D/E 분류표 | §4 |
| 5 | date-window aware schema 원칙 반영 | §1, §6, §7 |
| 6 | monthly-first / custom-date-compatible 설계 명시 | §1.2~1.4 |
| 7 | wiki page frontmatter 표준 초안 | §6 |
| 8 | wiki_date_index.jsonl 설계 초안 | §7 |
| 9 | wiki_context_pack schema 초안 | §8 (10 sub-schema) |
| 10 | opt-in migration plan | §10 (B2~B7) |
| 11 | risk / guardrail 정리 | §11 (R1~R11) |
| 12 | evaluation metric 제안 | §12 |
| 13 | 구현 코드 변경 없음 | §13 + commit diff |
| 14 | 운영 파일 변경 없음 | §13 |
| 15 | LLM 호출 없음 | $0 |

---

## 16. 한 문장으로

> 사용자가 원하는 것은 wiki page 를 단순히 생성하는 것이 아니라, raw
> data source 를 취합해 만든 wiki page 를 **debate 의 primary context**
> 로 사용하는 구조다. 지금은 월별 page 로 가도 되지만 schema 와 debate
> input 은 반드시 **date-window aware** 로 설계해야 한다.

---

## 17. 다음 권장 (R9-B.2)

`market_research/report/wiki_context_pack_builder.py` 신규 모듈.

- read-only loader: §7 의 date index (없으면 frontmatter 직접 파싱) 를
  사용해 dir 별 page 목록 후보화.
- §8 의 sub-pack (market/asset/fund/regime/claim/graph/prior_memory) 생성.
- excerpt cap, source_type 부여, source_trace 채움.
- debate prompt 미주입. `debug/wiki_context_packs/{period}.json` dump 만.
- LLM 호출 없음. 비용 0.
- 테스트: §12.6 4가지 합격선을 dry-run report 로 확인.

R9-B.1 (this doc) GO 후 R9-B.2 workorder 작성 예정.
