# R9-A Design Packet — Wiki-first Research Claim Normalization

**Status**: Design only (구현 X, LLM 호출 X)
**Author**: 2026-05-07
**Predecessors**: R6-A `[ref:N]` citation · R7 rule-based causal_graph · R7-B AdminTab toggle · R8-A evidence resolver · R8-B asset movement anchor · period boundary fix
**Scope**: market_research evidence → claim → wiki/anchor 흐름 재설계
**Constraints**: report_output / approved output / wiki / 운영 draft / LLM 대량 호출 0 변경

---

## 0. TL;DR

지금까지 P0~P2 트랙은 **evidence-first** 였다. raw news 카드가 분류 → salience → debate prompt → fund prompt 로 흐르는 동안, R7 rule-based causal_graph 가 path/claim 을 추출하지만 **rule-based recall 한계** (live observe 1건 `no_topic_matched` warning) 와 **claim 의 단일 source-of-truth 부재** (debate logs 안 nested, wiki 에는 별도 base page) 때문에:

- agent 4명이 자기 합성으로 amc 를 채우면서 alias 4종 분기 (`원자재/금`, `원자재·금`, ...)
- 같은 evidence 가 03_Assets / 02_Entities / 06_Debate_Memory / debate_logs / report_output 에 중복 등장
- causal_path 에 attached evidence/claims 가 0 인 path 다수 (live observe: 3 paths × claims=0/evidence=0)
- fund_comment 는 _market draft 와 fund draft 양쪽에서 같은 사실을 다시 인용 → KAP +0.32% 가 anchor -0.65% 와 충돌하는 dual-source 같은 문제 발생

**R9-A 는 evidence 와 wiki 사이에 명시적 `claim` 레이어를 둔다.** claim 은 LLM 으로 1회 추출 + 정규화 + dedup 한 후 wiki page (canonical) / causal_graph (R7) / asset movement anchor (R8-B) 가 모두 같은 claim 을 참조한다. evidence 는 claim 의 supporting source 로 격하, raw evidence 직접 LLM 주입은 claim 미커버 영역에만 한정.

목적:
- "이번 달 핵심 주장 N개" 가 단일 dict 로 존재 — wiki / anchor / debate / fund 모두 같은 ID 인용
- alias dedup 자동 (claim id 단일, label normalize)
- causal_path 와 anchor 의 attached_count > 0 보장 (claim 이 path 와 asset 양쪽에 명시 link)
- fund_comment 가 claim id 인용 → 자산군별 사실 정합 자동

이 packet 은 **설계만** 다룬다. 구현은 별도 R9-A-impl 트랙에서 사용자 승인 후 진행.

---

## 1. 현재 evidence / claim 구조 (R6-A ~ 보강 후)

### 1.1 Raw evidence 흐름

```
collect/macro_data.py news fetch
  → analyze/news_classifier.py (Haiku, TOPIC_TAXONOMY 14종 + 자산영향도)
  → core/dedupe.py (article_id MD5 12자 + dedup_group + event_group_id MD5 10자)
  → core/salience.py (3-tier source × 강도 × corroboration × bm_overlap)
  → data/news/{YYYY-MM}.json
```

evidence schema (월별 JSON 의 article 한 건):
```json
{
  "_article_id": "a1b2c3d4e5f6",
  "_dedup_group_id": "...",
  "_event_group_id": "event_5a3b9c4d2e",
  "title": "...", "date": "2026-04-15", "source": "Reuters", "url": "...",
  "_classified_topics": ["지정학", "에너지_원자재"],
  "primary_topic": "지정학",
  "_asset_impact_vector": {
    "국내주식": -0.4, "해외주식": -0.3, "유가": +0.7, "금": +0.5, ...
  },
  "_event_salience": 0.78,
  "_asset_relevance": {"국내주식": 0.6, ...}
}
```

### 1.2 R7 rule-based claim/path 추출

`tools/causal_graph.py::build_causal_layer()` 가 trace 시 evidence_annotations 를 입력으로:

- **TOPIC_RULES 10종** 정규식으로 evidence title 매칭 → claim
- **CAUSAL_TEMPLATES 7종** (cause→effect 명사쌍 7쌍) → causal edge
- **PATH_TEMPLATES 5종** → path (geopolitical_oil_inflation_rates_growth 등)
- LLM 호출 0

claim schema (R7):
```json
{
  "claim_id": "claim_a1b2_geo_unrest",
  "topic_rule": "geopolitical_unrest",
  "evidence_id": "a1b2c3d4e5f6",
  "summary": "이란 분쟁 격화로 유가 상승 압력",
  "asset_class_hint": null
}
```

### 1.3 R8-A evidence resolver

5단계 priority lookup (`tools/evidence_resolver.py`): fund_draft → market_source → debate_logs → news → research. trace 에 `_resolved=true/false` + source 추적. live observe 12/12 resolved (rate=1.0).

### 1.4 R8-B asset movement anchor

`asset_movement_anchor.build_asset_movement_anchors()` 가 자산군 8종 anchor 를 build:

```json
{
  "asset_class": "국내채권",
  "bm": {"name": "KAP종합채권", "kind": "level_pct",
         "level_start": 271.67, "level_end": 272.5258,
         "return_pct": 0.3150},
  "movement_direction": "up",
  "fund_exposure": {...},
  "causal_paths": [...],         # R7 path → asset 매핑
  "supporting_evidence_ids": [...],  # topic → asset 매핑
  "topic_tags": [...],
  "importance_score": ...
}
```

### 1.5 Wiki 2-tier (canonical / draft)

- `05_Regime_Canonical/`: machine-written, daily_update v12 판정식 단일 writer
- `06_Debate_Memory/`: debate_service write (debate run 단위)
- `01_Events/` `02_Entities/` `03_Assets/` `04_Funds/`: base draft pages, refresh_base_pages_after_refine 가 daily_update 시 일괄 작성
- `07_Graph_Evidence/`: transmission_paths_draft + summary

### 1.6 안 풀린 것

| 문제 | 증거 | 영향 |
|---|---|---|
| **claim source-of-truth 부재** | R7 claim 은 trace 시 임시 build, wiki 와 별도. debate_logs.agents.bull.asset_movement_commentary 도 별도 nested | 같은 사실이 여러 곳에 중복 / 변형 |
| **alias 분기** | 4월 사이클 amc 에 `원자재/금`, `원자재·금`, `원자재(금)`, `원자재 (Gold, 유가)` 4종 | LLM 합성 noise, importance score 산출 시 중복 |
| **causal path attached=0** | live observe 3 path 모두 claims=0 / evidence=0 (path-asset matching 실패) | path 로직이 prompt 에는 들어가지만 evidence link 가 없어 신뢰도 낮음 |
| **rule-based recall 한계** | 4월 사이클 1건 `no_topic_matched` (반도체 수출 호조) | 이런 evidence 가 anchor 에 unattached 로 빠짐 |
| **dual-source 충돌** | KAP +0.32% (comment) vs −0.65% (anchor old) | period boundary fix 로 일단 해소했지만, evidence/anchor/wiki 가 같은 source-of-truth 가 아니므로 재발 위험 |
| **wiki 재활용 약함** | 03_Assets / 04_Funds enrichment 는 daily_update 시 한 번 작성 후 거의 변동 없음 | claim 단위 동적 갱신 부재 |

---

## 2. R9-A 핵심 아이디어

### 2.1 Three-layer separation

```
Layer 1 — Raw evidence (news/research/blog)
    ↓ (분류 + dedup + salience, 기존 그대로)
Layer 2 — Normalized claims  ← R9-A 신규 단일 source-of-truth
    ↓ (claim → wiki / causal_graph / anchor / debate_input 모두 인용)
Layer 3 — Synthesized output (wiki page / debate / fund comment)
```

### 2.2 Claim object 의 위상

- 한 달치 evidence 를 **LLM 1회 호출** 로 N 개 claim 으로 정규화 (Haiku 또는 Sonnet, salience top-50 만, 비용 < $0.5)
- claim 은 deterministic ID + canonical label + 자산군/방향/horizon 메타 + supporting evidence list
- 중복/유사 claim 은 LLM normalization 단계에서 dedup
- 모든 downstream (wiki page / causal_graph / asset_movement_anchor / debate_engine prompt / fund_comment) 이 claim id 인용

### 2.3 Wiki-first 의미

- claim 이 들어왔을 때 **wiki page 에 먼저 promote** (`08_Claims/{YYYY-MM}_claim_{id}.md` 같은 새 dir 또는 03_Assets / 02_Entities 의 sub-section)
- debate / fund comment 는 wiki claim page 를 retrieve 하여 prompt 빌드
- 즉 "evidence → debate → wiki" 가 아니라 **"evidence → claim → wiki → debate"**
- wiki 가 단순 archive 가 아니라 **active source** 가 됨

### 2.4 LLM normalization 의 의미

- raw evidence 에 산재된 동일 주장을 한 claim 으로 통합 (e.g. "이란 휴전 → KOSPI 6.87% 급등" + "휴전 안도 → 위험선호 회복" → 한 claim)
- alias 정규화 (`원자재/금` ≡ `원자재·금` ≡ `원자재(금)` → 단일 label `원자재금`)
- direction / horizon / confidence 메타 부여 (rule-based 보다 정확)

---

## 3. Claim object schema

### 3.1 단일 claim 정의

```json
{
  "claim_id": "c_2026_04_iran_truce_korean_equity",
  "schema_version": "r9a-claim-1.0.0",
  "period": "2026-04",
  "label": "미-이란 휴전 합의로 KOSPI 6.87% 급등 + 위험선호 회복",
  "summary": "4/8 미-이란 휴전 합의 발표 직후 KOSPI 단일일 6.87% 급등, 코스피 5870선 회복. 글로벌 위험자산 전반 안도 랠리.",
  "affected_assets": [
    {"asset_class": "국내주식", "direction": "up", "magnitude": "high",
     "channel": "risk_appetite_recovery"},
    {"asset_class": "해외주식", "direction": "up", "magnitude": "medium",
     "channel": "risk_appetite_recovery"},
    {"asset_class": "환율(FX)", "direction": "down", "magnitude": "medium",
     "channel": "risk_appetite_recovery"}
  ],
  "causal_chain": [
    {"cause": "geopolitical_de_escalation", "effect": "risk_appetite_recovery"},
    {"cause": "risk_appetite_recovery", "effect": "korean_equity_rally"}
  ],
  "horizon": "immediate",
  "confidence": 0.92,
  "stance_signals": {
    "bullish_for": ["국내주식", "해외주식"],
    "bearish_for": [],
    "neutral_for": ["국내채권", "해외채권"]
  },
  "supporting_evidence_ids": ["a1b2c3d4e5f6", "b2c3d4e5f6a1", "c3d4e5f6a1b2"],
  "evidence_top_source": "Reuters",
  "salience": 0.94,
  "promoted_to_wiki": "08_Claims/2026-04_claim_iran_truce.md",
  "linked_wiki_pages": [
    "01_Events/2026-04_event_iran_ceasefire.md",
    "02_Entities/2026-04_graphnode__이란.md",
    "03_Assets/2026-04_국내주식.md"
  ],
  "linked_causal_paths": ["geopolitical_oil_inflation_rates_growth"],
  "extracted_at": "2026-05-07T12:00:00",
  "extractor_version": "r9a-llm-haiku-1.0.0",
  "extractor_cost_usd": 0.012
}
```

### 3.2 Field 정의

| Field | 타입 | 의미 | 출처 |
|---|---|---|---|
| `claim_id` | str | deterministic ID. period + topic_root + entity hash MD5 12자 | LLM extraction step |
| `label` | str (≤80) | 한 줄 canonical 표현. alias normalization 결과 | LLM |
| `summary` | str (≤300) | 2~3 문장 요약 | LLM |
| `affected_assets` | list[obj] | asset_class (R8-B 8종) + direction + magnitude + channel | LLM, schema enforce |
| `causal_chain` | list[obj] | cause→effect node pair (R7 graph_vocab.DRIVER/ASSET 사용) | LLM |
| `horizon` | enum | `immediate` (≤1주) / `short` (1주~1개월) / `medium` (1~3개월) / `long` (3개월+) | LLM |
| `confidence` | float | 0~1. corroboration count + source tier 가중 | computed |
| `stance_signals` | obj | debate agent stance 와 연동 (bullish_for / bearish_for / neutral_for) | LLM |
| `supporting_evidence_ids` | list[str] | 원 evidence article_id (R8-A resolver 호환) | computed (similarity match) |
| `salience` | float | 1순위 evidence salience 또는 evidence 평균 | computed |
| `promoted_to_wiki` | str\|null | wiki page 경로 (승격된 경우) | wiki promotion step |
| `linked_wiki_pages` | list[str] | claim 이 참조하는 기존 wiki pages | wiki retriever |
| `linked_causal_paths` | list[str] | R7 path_id 매핑 | rule-based + LLM |
| `extractor_version` | str | LLM 버전 + prompt hash. claim cache 무효화에 사용 | metadata |
| `extractor_cost_usd` | float | 누적 비용 추적 | metadata |

### 3.3 Direction / magnitude / channel enum

- `direction`: `up` / `down` / `flat` / `mixed`
- `magnitude`: `low` (≤1%) / `medium` (1~5%) / `high` (5%+) — magnitude 는 BM movement 가 있을 때만 산출 가능, 없으면 `qualitative`
- `channel` enum (causal mechanism): `risk_appetite_recovery`, `risk_appetite_loss`, `monetary_easing`, `monetary_tightening`, `inflation_pressure`, `inflation_easing`, `fx_translation`, `flight_to_quality`, `commodity_supply_shock`, `earnings_revision`, `policy_uncertainty`, `liquidity_injection`, `liquidity_drain`

---

## 4. Pipeline

### 4.1 새 단계 — Step 2.7 claim normalization

`pipeline/daily_update.py` 의 기존 step 흐름:

```
Step 0  매크로 지표
Step 1  뉴스 수집
Step 1.5 블로그 수집
Step 2  뉴스 분류 (Haiku)
Step 2.5 정제 (dedupe / salience / fallback)
Step 2.6 base wiki pages
Step 2.7 ★ NEW — claim normalization (Haiku 또는 Sonnet, 1회/월)
Step 3  GraphRAG 증분 + transmission_paths
Step 4  MTD 델타
Step 5  regime canonical
```

### 4.2 Step 2.7 세부

**Input**:
- `data/news/{YYYY-MM}.json` 에서 `_event_salience >= 0.5` 또는 top-100 evidence (whichever smaller)
- 기존 claim cache: `data/claims/{YYYY-MM}.json` (있으면 incremental, 없으면 full build)

**LLM call**:
- 모델: Haiku (cheap) 또는 Sonnet (recall)
- batch: 50 evidence / call, 약 4 calls / month
- prompt: 시스템 + JSON schema (claim 객체 list) + examples
- 비용 추정: $0.05~0.15 / 호출 × 4 = $0.2~0.6 / 월

**Output**:
- `data/claims/{YYYY-MM}.json` 에 N=20~50 claim
- `_claim_quality.jsonl` append (extractor cost / coverage / dedup rate)

**캐싱**:
- evidence article_id list hash 변경 안 되면 재호출 X
- extractor_version 변경 시만 재호출
- daily_update 가 동일 월 여러 번 실행되면 incremental update (새 evidence 만 LLM 에 전달)

**실패 시**:
- LLM 호출 실패 → claim 단계 skip, 기존 claim cache 유지
- daily_update 다른 step 영향 0
- Empty claim list → debate / anchor / fund_comment 모두 raw evidence + R7 rule-based fallback (현재 흐름과 동일)

### 4.3 비용 / 성능 budget

| 단계 | 모델 | 빈도 | 비용 / 회 | 월간 추정 |
|---|---|---|---|---|
| Step 2 분류 | Haiku | 일 | 미세 | $80~110 (기존) |
| Step 2.7 claim normalize | Haiku | 월 1~4 | $0.05~0.15 | $0.2~0.6 |
| 기존 debate (Opus + Haiku) | 그대로 | 월 1 | $0.34 | $0.34 |
| 기존 fund (Sonnet) | 그대로 | 월 7 | $0.07 | $0.5 |
| **R9-A 추가분** | | | | **$0.2~0.6 / 월** |

→ 비용 영향 작음. 기존 LLM 비용의 0.3~0.7% 추가.

---

## 5. Wiki promotion policy

### 5.1 promotion 기준 (rule-based, LLM 호출 0)

- `salience >= 0.7` AND `confidence >= 0.7` AND `affected_assets.count >= 2`
  → 신규 wiki claim page 작성 또는 기존 page update

- 또는: `causal_chain.length >= 2` (multi-step causal claim)

- 또는: 사용자 수동 promotion (admin UI)

### 5.2 Wiki page 위치

- 신설 디렉토리: `market_research/data/wiki/08_Claims/`
- 파일명: `{YYYY-MM}_claim_{claim_id_suffix}.md`
- frontmatter:
  ```yaml
  source_type: claim_wiki
  schema_version: r9a-claim-1.0.0
  claim_id: c_2026_04_iran_truce_korean_equity
  period: 2026-04
  promoted_at: 2026-05-07T12:00:00
  ```

### 5.3 Body template

```markdown
# {label}

## Summary
{summary}

## Affected Assets
- 국내주식: ▲ high (channel: risk_appetite_recovery)
- 해외주식: ▲ medium (channel: risk_appetite_recovery)
- 환율(FX): ▼ medium (channel: risk_appetite_recovery)

## Causal Chain
geopolitical_de_escalation → risk_appetite_recovery → korean_equity_rally

## Stance Signals
- bullish: 국내주식, 해외주식
- neutral: 국내채권, 해외채권

## Evidence ([ref:N])
- [ref:1] (Reuters, 2026-04-08) "이란 휴전 합의 — ..."
- [ref:2] (한국경제, 2026-04-08) "KOSPI 6.87% 급등 ..."

## Linked Wiki
- [01_Events/2026-04_event_iran_ceasefire.md]
- [02_Entities/2026-04_graphnode__이란.md]
- [03_Assets/2026-04_국내주식.md]

## Linked Causal Paths
- geopolitical_oil_inflation_rates_growth (R7)

## Metadata
- horizon: immediate
- confidence: 0.92
- salience: 0.94
- extractor: r9a-llm-haiku-1.0.0
```

### 5.4 promotion 보호장치

- `wiki/draft_pages.py` 의 `_is_enrichment_page()` guard 와 동일 패턴: `08_Claims/` 페이지는 daily_update base draft 단계에서 절대 overwrite 안 됨
- claim cache 가 `extractor_version` 동일하고 `supporting_evidence_ids` 동일하면 wiki page 도 재작성 X

---

## 6. Anchor / debate / fund_comment 통합

### 6.1 asset_movement_anchor (R8-B + R9-A)

`build_asset_movement_anchors()` 에 신규 input `claims=[...]` 추가:

- 기존 `evidence_annotations` / `causal_paths` 우선순위 위에 `claims` 우선
- claim.affected_assets.asset_class → asset_class anchor 의 새 field `linked_claims`
- claim.direction 이 BM movement_direction 과 다르면 warning (정합성 cross-check)
- claim.confidence 가 importance_score 가중 (path_count + claim_count)

```json
{
  "asset_class": "국내채권",
  "bm": {...},
  "movement_direction": "up",
  "fund_exposure": {...},
  "causal_paths": [...],
  "supporting_evidence_ids": [...],
  "linked_claims": [
    {"claim_id": "c_2026_04_iran_truce_korean_equity",
     "label": "미-이란 휴전 → 위험선호 회복",
     "direction_for_this_asset": "neutral",
     "channel": "risk_appetite_recovery",
     "confidence": 0.92}
  ],
  ...
}
```

### 6.2 debate_engine prompt

- `_build_shared_context` 에 `claims_text` 블록 신규 — top-N claim 의 label + summary + linked_assets
- `news_summary_text` 와 `graph_paths_text` 가 raw 이였다면 이제 claim 의 sub-list 로 격하
- agent prompt 가 claim 을 직접 인용 가능 (claim_id 형태)

### 6.3 fund_comment_service

- `_market_comment_to_inputs` pass-through 에 `claims` 추가
- comment_engine `build_report_prompt` 가 claim 섹션 inline (R8-B amc inline 패턴 동일)
- LLM 이 `[claim:c_2026_04_iran_truce]` 로 인용 → `evidence_trace` 가 R6-A 의 `[ref:N]` 외에 `[claim:X]` 도 트레이스

### 6.4 R7 causal_graph 와의 관계

- R7 rule-based path 는 그대로 유지 (LLM 호출 0 path inference)
- claim.linked_causal_paths 가 R7 path_id 와 매핑되어, `path_count > 0` 가 자동 보장 — live observe 에서 본 "claims=0/evidence=0" 문제 해소
- 추후 R7-C (LLM extractor) 가 합쳐지면 claim 자체가 LLM 기반이라 R7-C 와 통합 가능

---

## 7. 4월 운용보고 예시 (snippet)

R9-A 도입 후 _market draft.json 신규 필드:

```json
{
  "fund_code": "_market", "period": "2026-04",
  "debate_run_id": "...", "draft_comment": "...",
  "evidence_annotations": [...],
  "asset_movement_anchors": {...},
  "claims": [
    {
      "claim_id": "c_2026_04_iran_truce_korean_equity",
      "label": "미-이란 휴전 → KOSPI 6.87% 급등",
      "affected_assets": [
        {"asset_class": "국내주식", "direction": "up", "magnitude": "high"}
      ],
      "supporting_evidence_ids": ["a1b2c3d4e5f6"],
      "linked_causal_paths": ["geopolitical_oil_inflation_rates_growth"],
      "promoted_to_wiki": "08_Claims/2026-04_claim_iran_truce.md",
      "confidence": 0.92, "salience": 0.94
    },
    {
      "claim_id": "c_2026_04_kap_bond_inflation_pressure",
      "label": "KAP종합채권 +0.32% — 인플레이션 우려로 금리 하락 제한",
      "affected_assets": [
        {"asset_class": "국내채권", "direction": "up", "magnitude": "low",
         "channel": "inflation_pressure"}
      ],
      "supporting_evidence_ids": ["d4e5f6a1b2c3"],
      "linked_causal_paths": ["rates_domestic_bond"],
      ...
    }
  ],
  "claims_summary": {
    "total": 28, "promoted_to_wiki": 12,
    "by_asset_class": {"국내주식": 7, "해외주식": 6, "국내채권": 4, ...},
    "by_horizon": {"immediate": 10, "short": 12, "medium": 6, "long": 0}
  }
}
```

---

## 8. Roll-out phase 제안 (구현은 별도 R9-A-impl 트랙)

| Phase | 작업 | LLM 호출 | 산출물 |
|---|---|---|---|
| **R9-A.0** | claim schema 정의 + JSON schema validator + 단위 테스트 | 0 | `core/claim.py` + `tests/test_claim_schema.py` |
| **R9-A.1** | offline LLM extractor 프로토타입 (1개월 1회 manual run) | $0.2~0.6 / 월 | `analyze/claim_extractor.py` + `data/claims/{YYYY-MM}.json` |
| **R9-A.2** | wiki promotion writer + `_is_enrichment_page` 보호 | 0 | `wiki/claim_pages.py` + `08_Claims/` |
| **R9-A.3** | anchor / debate / fund_comment input pass-through (현재 R8-B wiring fix 와 동일 패턴) | 0 | `asset_movement_anchor.py`, `debate_service.py`, `fund_comment_service.py` 각 ~10줄 |
| **R9-A.4** | daily_update Step 2.7 통합 | $0.2~0.6 / 월 | `pipeline/daily_update.py` |
| **R9-A.5** | comment_trace 에 `claims` / `[claim:X]` 인용 surface | 0 | `tools/comment_trace.py` + `evidence_trace.py` |
| **R9-A.6** | 운영 사이클 1회 smoke (4월 또는 다음 월) | $1 내외 | live verification |

각 phase 사이에 사용자 승인 게이트. 본 packet 은 phase 0 시작 전 design lock.

---

## 9. Acceptance criteria

R9-A-impl 완료 시 충족해야 할 것:

| # | 항목 | 측정 방법 |
|---|---|---|
| 1 | claim 객체 schema_version + 모든 required field 존재 | `test_claim_schema_required_fields` |
| 2 | claim_id deterministic (같은 evidence list → 같은 ID) | `test_claim_id_deterministic` |
| 3 | LLM 호출 1회 / 월 (incremental cache hit 시 0회) | `_claim_quality.jsonl` row 수 |
| 4 | claim → wiki promotion rate 30~70% (너무 적으면 noise, 너무 많으면 spam) | salience ≥ 0.7 + confidence ≥ 0.7 비율 |
| 5 | causal_path attached_count > 0 (claim 통해 path 와 evidence 자동 link) | `test_anchor_path_attached_when_claims_present` |
| 6 | fund_comment 가 `[claim:X]` 인용 시 R6-A `[ref:N]` invalid 0 유지 | `comment_trace citation_validation` |
| 7 | alias dedup — 동일 사건이 동일 claim_id 로 통합 (live observe 4종 alias → 1종) | manual + auto similarity check |
| 8 | extractor 비용 < $1 / 월 | `extractor_cost_usd` 합계 |
| 9 | claim cache hit 시 LLM 호출 X (extractor_version + evidence_id_hash 매칭) | `_claim_quality.jsonl` 의 `cache_hit` flag |
| 10 | 모든 기존 anchor / debate / fund_comment 회귀 0 (claim 미존재 시 raw evidence fallback) | 기존 test suite 그대로 PASS |

---

## 10. Risks / open questions

### 10.1 Risks

| # | 위험 | 완화책 |
|---|---|---|
| 1 | LLM extractor hallucination (없는 사실을 claim 으로 만듦) | extractor 가 `supporting_evidence_ids` 1개 이상 강제, evidence 본문 인용 검증 step 추가 |
| 2 | claim alias normalization 의 trade-off — 다른 사건을 같은 claim 으로 묶을 위험 | similarity threshold cap (cosine ≥ 0.85), 보수적 dedup |
| 3 | wiki 8_Claims/ 디렉토리 폭주 (월 30~50 claim × 12달) | promotion 기준 엄격, 분기/연간 archive 정책, `dedupe across months` 옵션 |
| 4 | 기존 R7 rule-based path 와 LLM claim causal_chain 의 충돌 | claim.linked_causal_paths 로 explicit 매핑, 충돌 시 R7 우선 (rule = 신뢰도 높음) |
| 5 | extractor_version 변경 시 cache 전부 무효화 → 비용 폭증 | version bump 시 manual approval, 백업 cache 보존, gradual roll-out |
| 6 | claim 이 anchor 와 의견 다를 때 (e.g. claim direction=up but BM=down) | warning 만 발생, override 안 함. user 수동 판단 |

### 10.2 Open questions (이번 packet 에서 결정 안 한 것)

- O1. claim_id naming convention 최종 (현재 제안: `c_{YYYY_MM}_{topic_root}_{entity_short}`)
- O2. extractor 모델 선택 — Haiku (cheap, recall low) vs Sonnet (cost 5x, recall high). 첫 phase 는 Haiku 권장
- O3. claim wiki page 와 02_Entities / 03_Assets 의 boundary — 같은 사건이 entity page + claim page 양쪽에 들어갈 때 dedup 정책
- O4. claim cross-month linking — "이란 휴전 (4월)" claim 이 다음 달 "이란 휴전 깨짐" claim 과 어떻게 linked 되는지
- O5. fund-specific claims (08N81 듀레이션 확대 등 portfolio-level 결정)을 claim 화 할지 vs 기존 fund_comment_service 그대로 두기
- O6. claim 단위 admin 검수 UI (R7-B AdminTab Causal Graph mode 와 통합 vs 신규 탭)
- O7. legacy 운영보고 (4월 final.json) 에 backfill 안 함 — Option B 정책 (P1-④ 동일 방침)
- O8. 다국어 evidence (영문 Reuters / 한글 매경) 의 claim label 언어 정책

---

## 11. 변경하지 않는 것 (이번 packet 범위 보장)

- report_output / approved output / 운영 draft 변경 0
- 기존 wiki 97건 미커밋 변경 그대로
- LLM 호출 0 (이번 packet 은 설계만)
- R6-A `[ref:N]` / R7 causal_graph / R7-B AdminTab toggle / R8-A resolver / R8-B anchor / period boundary fix 모두 보존, 위에 claim layer 만 add
- BENCHMARK_MAP / SCIP_INDICATORS / FRED_INDICATORS / BMJISU_INDICATORS / `_ASSET_TO_INDICATOR` 매핑 모두 변경 0
- 기존 daily_update 0~5 step 무변경 (2.7 만 추가, 기존 step 의존성 0)
- comment_engine / debate_engine / fund_comment_service 의 기존 LLM 호출 빈도 / 모델 / 비용 변경 0

---

## 12. 결정 게이트 (이 packet 사용자 검토 항목)

다음 phase R9-A.0 시작 전 사용자 결정 필요:

- D1. **scope 승인** — Section 2~6 의 3-layer separation + claim schema + wiki promotion 정책 동의 여부
- D2. **모델 선택** — Haiku vs Sonnet (4.2 LLM call). 권장: Haiku 로 시작, 운영 1~2개월 후 recall 부족 시 Sonnet 로 격상
- D3. **wiki 디렉토리** — `08_Claims/` 신설 vs 03_Assets/02_Entities sub-section 으로만. 권장: `08_Claims/` 신설 (claim 단위 검색 / evidence trace / dedupe 가 단일 dir 에서 일관)
- D4. **promotion 임계** — `salience ≥ 0.7 AND confidence ≥ 0.7 AND assets ≥ 2` 권장. 운영 1~2개월 후 조정
- D5. **legacy backfill** — 미진행 (P1-④ Option B 정책 따름)
- D6. **Phase 0 (schema + 단위 테스트) 만 먼저** vs Phase 0~3 한 번에. 권장: Phase 0 만 먼저, 사용자 검토 후 1~3 진행
- D7. **claim_extractor.py 위치** — `analyze/` (현재 권장) vs `report/` (claim 이 보고서 입력이라). 권장: `analyze/` (수집/정제와 같은 layer)

---

## 13. 본 packet 에서 결정 끝낸 것

- claim 은 LLM normalization layer (rule-based 아님)
- claim 은 month 단위 batch (실시간 추출 X — 비용 / 안정성)
- claim 은 evidence-id 기반 deterministic ID
- claim 은 wiki page 로 promote (active source 화)
- claim 은 anchor / debate / fund_comment 모두에 inline (R8-B amc 패턴 재사용)
- 기존 R7 rule-based path 는 보존 (claim 과 cross-link 만)
- extractor_version 캐시 무효화 정책
- LLM 비용 < $1 / 월 budget 하드 캡

---

**End of R9-A Design Packet**

Total LOC: ~520 (R8-B packet 535 LOC parity).
Implementation gate: 사용자 D1~D7 결정 후 R9-A.0 (schema + 단위 테스트) 만 먼저 시작 권장.
