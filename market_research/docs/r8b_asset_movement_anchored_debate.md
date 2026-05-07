# R8-B Design Packet — Asset Movement Anchored Wiki Debate

**Status**: Design only (구현 X)
**Author**: 2026-05-07
**Scope**: market_research debate input package contract
**Constraints**: report_output / approved output / wiki / LLM 호출 0 변경

---

## 0. TL;DR

현재 debate prompt 는 raw evidence (15~30개 뉴스 카드) 와 GraphRAG transmission paths 를
"flat" 하게 나열한다. 결과적으로 LLM 이 자산군별로 "무엇이 얼마나 움직였고, 왜 그랬고,
근거가 무엇인지" 를 직접 합성해야 하며, 이 합성이 누락/혼동되면 펀드 코멘트로
fan-out 될 때 자산군 매칭이 부정확해진다 (대표 사례: WGBI/fx path 누락, 이번 R8-A
이전의 12/15 매핑 실패 시 메인 path 가 chain 3/5 로 떨어진 케이스).

R8-B 는 debate input 의 1차 구조를 **자산군 등락률 (DT BM 또는 universe BM 기준)** 을
"anchor" 로 잡고, 각 자산군 항목 아래에 **causal path** (R7 graph_seed_causal) 와
**supporting evidence** (R8-A resolved annotations) 를 nested 로 묶는 contract 로
바꾸자는 제안이다. raw evidence 직접 listing 은 "unattached" 섹션에만 남기고
대폭 축소한다.

목적:
- 과거 코멘트: "자산군별 등락 ← 어떤 causal path ← 어떤 evidence" 가 자동으로 얽힘
- 미래 코멘트: 자산군별 전망/선호 시그널 (debate agent 의 `asset_allocation_view`) 이
  근거 evidence 와 자동으로 매칭됨

---

## 1. 현재 debate input 구조

`_build_shared_context(year, month, fund_code)` (debate_engine.py:569) 가
4 인 agent 공유 context 를 만든다. agent prompt 는 아래 7 블록을 concatenate.

| 블록 | 출처 | 형태 | 자산군 anchor 여부 |
|---|---|---|:---:|
| `news_summary_text` | `data/news/{YYYY-MM}.json` + `_build_evidence_candidates()` | 토픽 카운트 + 자산군별 뉴스 영향 합산 + research/news 2-lane 카드 15~30개 | △ (집계만) |
| `graph_paths_text` | `data/insight_graph/{YYYY-MM}.json::transmission_paths` | confidence ≥ 0.3 인 path 6~10개 (path_labels) | ✗ |
| `wiki_context_text` | `wiki_retriever.retrieve_wiki_context(stage=market_debate)` | 05_Regime / 06_Debate_Memory / 03_Assets / 02_Entities top-N pages | △ (asset 페이지 일부) |
| `indicators_text` | `data/macro/indicators.csv` 마지막 행 | KOSPI / S&P500 / USDKRW / VIX / GoldUSD 등 단일 행 | △ (값만) |
| `timeseries_narrative_text` | `timeseries_narrator.build_debate_narrative()` | BEW segment + 뉴스 매칭 narrative | △ (BM 별 segment) |
| `asset_coverage_text` | `asset_coverage.build_asset_coverage_map()` | 자산군 8종에 대한 coverage 점수 (news/path/wiki/timeseries) | ✓ |
| `blog_context_text` (monygeek 만) | `data/blog_insight/` | 블로거 관점 | ✗ |

agent 출력 schema (debate_engine.py:927-931):
```json
{
  "stance": "bullish|bearish|neutral",
  "key_points": ["..."],
  "risk_assessment": "...",
  "asset_allocation_view": {
    "국내주식": "비중확대|유지|축소",
    "국내채권": "...",
    "해외주식": "...",
    "해외채권": "..."
  },
  "tail_risks": [...],
  "reasoning": "..."
}
```

문제:
- `asset_allocation_view` 라는 자산군 stance 출력은 있지만, **input** 측에는
  자산군별 등락률/PA 가 명시적 anchor 로 잡혀있지 않다. agent 가 indicators.csv +
  news 영향 + asset_coverage 에서 자기가 합성해야 한다.
- `news_summary_text` 가 가장 큰 비중 (raw 15~30 카드). LLM 이 카드 단위로 읽고
  자산군 매칭은 자기 추론.
- `graph_paths_text` 와 evidence 가 분리되어 있다. path 의 supporting evidence 는
  prompt 안에서 명시적 link 가 안 됨 — 똑같은 evidence 가 news_summary 와 graph
  양쪽에서 따로 등장.

---

## 2. 목표 debate input 구조 (R8-B)

`asset_movement_anchored` 라는 새 1 차 블록이 prompt 의 가장 윗단을 차지하고,
나머지 기존 블록은 보조 (선택적 fallback) 로 격하.

```
## {YYYY-MM} 자산군 movement anchor (R8-B)

[자산군 1: 국내주식]
- 기간 수익률: -2.50% (KOSPI -3.10%, 초과 +0.60%)
- BM: KOSPI Total Return (DT DWPM10040, fund-aligned)
- 펀드 노출: 평균 비중 25.0%, 기여수익률 -0.65% (Brinson selection)
- 주요 movement window: 2026-04-15 ~ 2026-04-22 (-4.2%, MDD -5.1%)
- 관련 causal path:
  · path:rates_domestic_bond  (conf 0.5)  ← evidence [ref:7] [ref:12]
  · path:geopolitical_oil_inflation_rates_growth (conf 1.0)  ← [ref:1] [ref:3] [ref:5]
- 관련 wiki: 03_Assets/2026-04_국내주식.md
- supporting evidence: [ref:1, 3, 5, 7, 12]  (총 5건)

[자산군 2: 해외주식]
...

## Unattached evidence (자산군 매칭 실패 — agent 가 직접 평가)
- [ref:99] (관세 위법 판결, 단기 호재)  topic=관세_무역
- [ref:103] (플라자 합의 가능성)        topic=환율_FX
...

## 매크로 지표 보조 (R8-B 보조)
- USDKRW: 1,476 (M-1 1,452 → +1.7%)
- VIX: 18.5
- HY OAS: 343 bp
...

## Wiki regime context (R8-B 보조)
05_Regime_Canonical/...
06_Debate_Memory/...
```

원칙:
1. **자산군이 1차 unit**. agent 는 자산군 list 를 따라 각 항목에 대해
   "stance / key_points / 근거" 를 출력. raw evidence 카드를 자산군 매칭 없이
   통째로 넘기지 않는다.
2. **causal path 는 자산군 hierarchy 안에 종속**. R7 의 `causal_paths.chain`
   에 `asset:*` 노드가 있으면 그 자산군 anchor 의 triggers 에 매핑.
3. **evidence 는 reference (ref:N) 로만 prompt 에 등장**, 자산군 anchor 안에서
   `supporting evidence: [ref:...]` 로. 본문 (title/source/date) 은 별도
   `evidence_pool` 에서 한번만 listing.
4. **fund_code 가 주어지면** PA 와 fund-aligned BM 으로 펀드 노출/기여를 같이
   anchor 에 박는다 (시장 debate 는 fund_code=None → universe BM 만).

---

## 3. 자산군 return / PA 데이터 source

### 3.1 자산군별 등락률 (BM 수익률)

| 자산군 | universe BM (fund_code=None) | DT alias | source 함수 | DB |
|---|---|---|---|---|
| 국내주식 | KOSPI Total Return | dataset_id 253 / dataseries_id 15 | `comment_engine._load_bm_returns_for_range` | SCIP |
| 해외주식 | MSCI ACWI (USD T-1 × USDKRW) | 35 / 15 | 동상 | SCIP |
| 국내채권 | KAP All-Bond Total | 257 / 9 | 동상 | SCIP |
| 해외채권 | Bloomberg Global Agg (hedged T-1) | 256 / 9 | 동상 | SCIP |
| 금/대체 | Gold Spot | 408 / 15 | 동상 | SCIP |
| FX | USDKRW (DXY 보조) | 31 / 6 | 동상 | SCIP / ECOS |
| 유동성 | KAP MMI Call | 255 / 9 | 동상 | SCIP |
| 크레딧 | US HY OAS Spread | 404 / — | (보조 지표) | SCIP |

펀드별 (fund_code 주어진 경우) → DT BM 우선 (DT 우선 → SCIP fallback 정책,
`data_loader._DT_BM_CONFIG` 5개 펀드: 07G02 / 07G03 / 07G04 / 08K88 / 4JM12).
`load_dt_bm_prices(fund_code, start_date)` (data_loader.py:536).

### 3.2 펀드 PA (fund-aligned debate / 펀드 코멘트 fan-out)

`compute_single_port_pa(fund_code, start_date, end_date).asset_summary` (data_loader.py:2353).
DataFrame 컬럼:
- `자산군` — 8 분류 (국내주식/해외주식/국내채권/해외채권/대체/FX/유동성/모펀드) +
  '포트폴리오' 행
- `개별수익률` — 자산군 자체 수익률 (decimal)
- `기여수익률` — 자산군이 펀드에 기여한 수익률 (decimal, 경로의존 누적)
- `순자산비중` — 평균 비중 (decimal 0~1)
- `순비중변화` — period 내 비중 변화

펀드 NAV: `dt.DWPM10510.MOD_STPR` → `load_fund_nav_with_aum`.

### 3.3 기간 변환

debate input 의 기간:
- 월별: `period = "YYYY-MM"` → 월초 prev_business_day ~ 월말 prev_business_day
- 분기: `period = "YYYY-Q[1-4]"` → 분기 1월초 ~ 분기 마지막달 말

PA 일자 변환 = `comment_engine._resolve_dates(mode, year, period_num)` 재사용.

---

## 4. Asset Movement Anchor Schema

신규 schema (input package 안):

```jsonc
{
  "schema_version": "r8b-asset-movement-anchor-1.0.0",
  "period": "2026-04",
  "fund_code": null,             // 시장 debate. 펀드 fan-out 시 "08N81" 등.
  "asset_movements": [
    {
      "asset_class": "국내주식",
      "bm": {
        "name": "KOSPI Total Return",
        "source": "SCIP:253/15",          // dataset_id/dataseries_id
        "fund_aligned": false,             // fund_code null 이면 false
        "return_pct": -2.50,               // 기간 누적
        "level_start": 5_640.12,
        "level_end": 5_499.20,
        "max_drawdown_pct": -5.10,
        "vol_annualized_pct": 14.2
      },
      "movement_windows": [                // 핵심 등락 구간 (3 ~ 5 개)
        {
          "label": "급락",
          "start": "2026-04-15", "end": "2026-04-22",
          "return_pct": -4.20,
          "trigger_topic": "지정학",
          "supporting_evidence_ids": ["ev1", "ev3"]
        }
      ],
      "fund_exposure": null,               // fund_code null 이면 null
                                            // fund 일 때:
                                            // { "weight_pct": 25.0,
                                            //   "contribution_pct": -0.65,
                                            //   "selection_excess_pct": 0.32,
                                            //   "trades_summary": "+1.2%p / -0.8%p" }
      "causal_paths": [                    // R7 graph_seed_causal 매칭
        {
          "path_id": "rates_domestic_bond",
          "label": "금리 → 국내채권",
          "confidence": 0.5,
          "covered_chain_nodes": ["macro:interest_rate"],
          "supporting_evidence_ids": ["ev7", "ev12"]
        }
      ],
      "wiki_pages": [
        "03_Assets/2026-04_국내주식.md"
      ],
      "supporting_evidence_ids": ["ev1", "ev3", "ev5", "ev7", "ev12"],
      "topic_tags": ["지정학", "금리_채권"],
      "metric_anchors": {
        "external_rate_change_bp": -25,
        "kospi_pe_12mf": 11.8
      }
    }
    // 자산군 8종 반복 (8 분류) + 미매칭 자산군은 빈 anchor (return 0, evidence [])
  ],
  "evidence_pool": [                       // raw card 풀 (anchor 의 ref:N 매핑용)
    {
      "ref": 1, "article_id": "ev1",
      "title": "이란 분쟁 격화로 유가 100달러 돌파",
      "source": "Reuters", "date": "2026-04-15",
      "topic": "지정학", "salience": 0.78
    }
    // 15 ~ 30개. anchor 안에서는 ref id 만 참조.
  ],
  "unattached_evidence": [                 // 자산군 매칭 실패 evidence
    { "ref": 99, "topic": "관세_무역", ... }
    // 의도적으로 LLM 이 자산 매칭 못 한 ev 표시 → recall 감지 + 별도 평가
  ],
  "macro_context": {                       // 기존 indicators.csv 압축 (보조)
    "USDKRW": { "value": 1476.20, "mom_pct": 1.7 },
    "VIX": { "value": 18.5 },
    "MOVE": { "value": 95.2 }
  },
  "wiki_regime_context": {                 // 기존 wiki retriever 결과 (보조)
    "regime_canonical_pages": [...],
    "debate_memory_pages": [...]
  },
  "_resolution_summary": { ... }           // R8-A resolution 통계 직접 노출
}
```

핵심 설계 결정:
- `asset_movements` 가 1차 anchor. **8 자산군 모두 포함**, return=0/evidence=[] 더라도
  anchor 자체는 만들어 LLM 이 "이 자산군에 대해 할 말 없음" 을 명시적으로 출력하게.
- evidence 본문은 `evidence_pool` 에 한 번. anchor 는 ref id 만 참조. 중복 0.
- `unattached_evidence` 는 의도적 노출 — LLM 이 매칭 실패 evidence 도 평가하게.

---

## 5. Asset Movement ↔ Causal Path 매칭 방식

### 5.1 path → asset_class 매핑 (rule-based, 결정론적)

R7 의 `PATH_TEMPLATES` 와 `TOPIC_DEFS` 를 활용:

```python
def _path_to_asset_classes(path: dict) -> list[str]:
    """path.chain 의 asset:* 노드에 매핑된 자산군 (Korean) list."""
    out = []
    for node in path["chain"]:
        if node.startswith("asset:"):
            kind, label = TOPIC_DEFS.get(node, ("", ""))
            # asset:us_growth_stock → "해외주식"
            out.append(_TOPIC_TO_ASSET_CLASS[node])
        elif node.startswith("macro:"):
            # macro 단독 path 는 asset:fx_usdkrw → "FX" 같은 alias
            ...
    return out
```

신규 `_TOPIC_TO_ASSET_CLASS` 매핑 (R8-B-impl 시):
| topic_id | asset_class |
|---|---|
| `asset:us_growth_stock` | 해외주식 |
| `asset:domestic_bond` | 국내채권 |
| `asset:gold` | 금/대체 |
| `asset:overseas_translation` | FX |
| `macro:fx_usdkrw` | FX (보조) |
| `macro:oil_price` | 금/대체 (간접) |
| `macro:interest_rate` | 국내채권/해외채권 (둘 다 link) |
| `event:geopolitical` | 자산군 매핑 X (모든 위험자산에 영향) → unattached |
| `event:wgbi` | 국내채권 |

### 5.2 evidence → asset_class 매핑

Priority:
1. evidence.`topic` (R8-A resolver 가 채움) 에 기반한 fixed mapping (`_TOPIC_TO_ASSET_CLASS`)
2. evidence.`all_topics` 의 OR (multi-asset evidence 는 여러 anchor 에 등장 가능)
3. salience.asset_impact_vector (기존 분류 단계 산출물) — bm_anomaly 매칭
4. 매칭 실패 → `unattached_evidence`

### 5.3 BM movement_window ↔ evidence 매칭

`timeseries_narrator.build_debate_narrative` 가 이미 BM segment ↔ 뉴스 매칭을
수행함 (z-score 기반). R8-B 는 그 결과를 자산군 anchor.movement_windows 에
구조화해 박는다 (현재는 자유 텍스트 narrative 로 prompt 에만 들어감).

---

## 6. wiki / causal graph 의 input 승격

### 6.1 wiki

| 현재 | R8-B |
|---|---|
| `wiki_context_text` 가 prompt 에 통째 inline (수천자) | 자산군 anchor 의 `wiki_pages` 에 path 만 (LLM 이 필요시 점프) + 5/6 dir (regime/debate_memory) 만 본문 inline |
| 03_Assets / 04_Funds 섹션 일부 본문 노출 | anchor.wiki_pages 에 path 만, 본문은 evidence_pool 옆에 별도 `wiki_excerpt_pool` (top 200자 only) |
| asset stage 차단 (G7) 그대로 | 변동 없음 |

→ wiki context_chars 30 ~ 50% 감소 예상 (3-Tier 가드는 유지, 본문만 압축).

### 6.2 causal graph

| 현재 | R8-B |
|---|---|
| `graph_paths_text` 에 transmission_paths 6~10 개 자유 prose | 자산군 anchor.causal_paths 에 path_id 와 supporting evidence 만. Path 본문 자체는 R7 PATH_TEMPLATES 의 label 그대로 |
| evidence ↔ path link 부재 | `supporting_evidence_ids` 로 명시적 link |
| GraphRAG transmission_paths (legacy) 그대로 사용 | R7 PATH_TEMPLATES 와 GraphRAG transmission_paths 를 union (R7 5개 + GraphRAG dynamic) |

---

## 7. raw evidence 직접 투입 축소

| 위치 | 현재 | R8-B |
|---|---|---|
| evidence_pool (본문 inline) | 15 ~ 30 카드, 각 200~400자 | 15 ~ 30 항목, 각 ref id + title 50자 + topic + salience 만 (~80% 압축) |
| anchor 안에 inline | 0 | ref id list 만 (본문 0) |
| unattached_evidence | 없음 (전부 한 묶음) | 자산군 매칭 실패만 별도 노출 (visibility ↑) |
| wiki context | inline 수천자 | regime/debate_memory 만 inline, asset/fund 페이지는 path 만 |

prompt 총 길이 추정:
- 현재: ~12,000 ~ 18,000 chars
- R8-B: ~6,000 ~ 9,000 chars (40 ~ 50% 감소)

→ token cap 16K (월별) / 32K (분기) 안에서 더 여유 + agent reasoning 공간 확보.

---

## 8. 4월 월간 보고서 예시 input contract (snippet)

`market_research/data/report_output/2026-04/_market.input.json` 가 갖는 형태:

```jsonc
{
  "schema_version": "r8b-asset-movement-anchor-1.0.0",
  "period": "2026-04",
  "fund_code": null,
  "generated_at": "2026-05-07T...",
  "asset_movements": [
    {
      "asset_class": "국내주식",
      "bm": {
        "name": "KOSPI Total Return",
        "source": "SCIP:253/15",
        "fund_aligned": false,
        "return_pct": -2.50,
        "level_start": 5640.12, "level_end": 5499.20,
        "max_drawdown_pct": -5.10,
        "vol_annualized_pct": 14.2
      },
      "movement_windows": [
        {
          "label": "급락",
          "start": "2026-04-15", "end": "2026-04-22",
          "return_pct": -4.20,
          "trigger_topic": "지정학",
          "supporting_evidence_ids": ["b07523c195c0", "c2715118960e"]
        }
      ],
      "fund_exposure": null,
      "causal_paths": [
        {
          "path_id": "rates_domestic_bond",
          "label": "금리 → 국내채권",
          "confidence": 0.5,
          "supporting_evidence_ids": ["d9f6a5f60d38"]
        }
      ],
      "wiki_pages": ["03_Assets/2026-04_국내주식.md"],
      "supporting_evidence_ids": ["b07523c195c0", "c2715118960e", "d9f6a5f60d38"],
      "topic_tags": ["지정학", "금리_채권"]
    }
    // 8 자산군 반복
  ],
  "evidence_pool": [
    {
      "ref": 1, "article_id": "b07523c195c0",
      "title_short": "이란 분쟁 격화로 유가 100달러 돌파",
      "source": "Reuters", "date": "2026-04-15",
      "topic": "지정학", "salience": 0.78,
      "linked_asset_classes": ["금/대체"]
    }
  ],
  "unattached_evidence": [
    { "ref": 17, "title_short": "관세 위법 판결",
      "topic": "관세_무역", "linked_asset_classes": [] }
  ],
  "macro_context": { "USDKRW": 1476.20, "VIX": 18.5 },
  "wiki_regime_context": {
    "regime_canonical_pages": ["05_Regime_Canonical/2026-Q2_경기_확장.md"],
    "debate_memory_pages": ["06_Debate_Memory/2026-04_market.md"]
  },
  "_resolution_summary": {
    "resolved_count": 28, "unresolved_count": 2,
    "resolution_rate": 0.93
  }
}
```

펀드 fan-out (`08N81.input.json` 등) 에서는 `fund_code="08N81"`, 모든 anchor 의
`bm.fund_aligned=true`, `fund_exposure` 채움, `asset_movements` 중 펀드가 보유하지
않는 자산군은 anchor 자체를 drop (또는 `held=false` flag).

---

## 9. Acceptance Criteria

기능:
- [ ] `_market.input.json` 와 `{fund}.input.json` 의 schema_version 이
      `r8b-asset-movement-anchor-1.0.0` 으로 박힘.
- [ ] `asset_movements` array 가 8 자산군 모두 포함 (return=0/evidence=[]
      anchor 도 명시적으로 존재).
- [ ] 각 anchor 의 `causal_paths` 에 1 개 이상 path 또는 명시적 빈 array.
- [ ] `evidence_pool` 의 각 ref 가 anchor.supporting_evidence_ids 또는
      `unattached_evidence` 둘 중 하나에만 등장 (중복 0, 누락 0).
- [ ] `_resolution_summary.resolution_rate >= 0.9` (R8-A resolver 활용).
- [ ] prompt 총 길이 ≤ 9,000 chars (16K cap 의 56%).

운영:
- [ ] 4월 _market 재생성 시 기존 final.json 무수정 (R8-B input 만 새 schema, debate 결과는 별도 cycle).
- [ ] 펀드 fan-out 7개 모두 fund_aligned=true 로 BM 매핑 (07G02/07G03/07G04/08K88/4JM12 → DT, 나머지 → universe BM fallback).
- [ ] 회귀: 기존 debate prompt 가 (구) input.json 도 read 가능 (backward compat 1 cycle).

품질 (사후 측정):
- [ ] R7 causal_paths 활성 path 수 ≥ 4 (기존 4/5 수준 유지).
- [ ] no_topic_matched warning ≤ 5 (R8-A 후 baseline 수준).
- [ ] LLM 이 출력하는 `asset_allocation_view` 의 `key_points` 안에 자산군별 ref:N
      인용 ≥ 평균 1.5 회 (현재 0 ~ 0.5 회 추정).

---

## 10. 위험 / 부작용

### 10.1 BM 결측 / 자산군 매핑 실패

| 위험 | 완화 |
|---|---|
| DT BM 미설정 펀드 (07G02 / 07G03 / 08N33 / 08N81 / 08P22 / 2JM23) | universe BM fallback. fund_aligned=false 로 표시 |
| SCIP dataset_id 결측 (예: 408 Gold 누락 시) | macro_context.warnings 에 기록, anchor.bm.return_pct=null |
| `_TOPIC_TO_ASSET_CLASS` 빈 자산군 (예: 신규 토픽) | unattached_evidence 로 fall-through |

### 10.2 schema breaking change

| 위험 | 완화 |
|---|---|
| 기존 input.json (R8-B 이전) 가 4월 사이클에서 in-flight | `schema_version` 분기. debate_engine 가 두 schema 모두 read (1 cycle deprecation) |
| 기존 final.json 의 debate 결과는 R8-B input 과 무관 | final.json schema 손대지 않음. debate output 만 wider asset awareness |

### 10.3 prompt 압축 부작용

| 위험 | 완화 |
|---|---|
| evidence 본문 압축 시 LLM 이 nuance 놓침 | evidence_pool.title_short 60자 + topic + salience 유지 (현재도 LLM 이 카드 본문 직접 인용은 드물게 함). 필요 시 anchor.movement_windows.label 에 1-2 keyword 추가 |
| asset_movements 8개 anchor 가 빈 자산군까지 포함 → noise | empty anchor 는 한 줄 ("[해외채권] 등락 미미, 직접 포지션 없음") 으로 압축 |

### 10.4 자산군 ↔ path 매핑 부정확

| 위험 | 완화 |
|---|---|
| `event:geopolitical` 같은 cross-asset event 가 어느 anchor 에도 안 들어감 | unattached_evidence 와 별도로 `cross_asset_events` 섹션 신설 검토 (R8-B-2) |
| path.chain 에 asset 노드 없는 경우 (rates_domestic_bond → 국내채권 link OK, 그러나 path:gold_hedge_volatility 는 chain=[asset:gold] 단독 → 금/대체 OK) | rule-based 매핑 + 빈 결과 시 path 자체를 unattached_paths 로 격리 |

### 10.5 운영 위험

| 위험 | 완화 |
|---|---|
| 첫 사이클 출력이 schema 깨짐 → fund fan-out 실패 | dry-run mode (`--dry-run-r8b`) 추가, input.json 만 만들고 debate 호출 X |
| approved final 손상 가능성 | R8-B 는 input package 단계만 변경, debate_engine output 미변경 |

---

## 11. 구현 phase 제안 (정보 only — 구현은 별도 R8-B-impl 트랙)

| Phase | scope | LOC 추정 |
|---|---|---:|
| R8-B-1 | `asset_movement_builder.py` 신규 (BM/PA fetch + path 매핑) + schema 정의 | 400 ~ 500 |
| R8-B-2 | `_build_shared_context` 의 dual-mode (legacy `news_summary_text` vs anchor) toggle + `--anchor` flag | 150 ~ 200 |
| R8-B-3 | agent prompt 재작성 — anchor 1 차 prompt + evidence_pool 보조 | 200 ~ 300 |
| R8-B-4 | input.json schema_version `r8b-asset-movement-anchor-1.0.0` migrate | 100 ~ 150 |
| R8-B-5 | 회귀 — pytest tmp_path mock + 4월 _market sample 재생성 dry-run | 250 ~ 350 |
| **합계** | | **~1,300 ~ 1,500 LOC + tests** |

→ 4 ~ 6 사이클 추정 (현재 R6/R7/R8-A 수준).

---

## 12. 본 packet 에서 결정 안 한 것 (open questions)

1. fund-aligned debate (펀드별 별도 _market 대신 fund-anchored 고유 prompt) 까지
   가야 하는지 — 현재는 시장 debate → fan-out 순서. R8-B 는 시장 debate 도
   asset anchor 로 바꾸면 fan-out 시 추가 transformation 필요.
2. evidence salience top-N (현재 15~30) 을 자산군 quota 기반으로 분배할지
   (예: 각 자산군 3 + unattached 5).
3. agent 출력 schema 에 `asset_movement_commentary` (per-asset 자유 텍스트 array)
   를 추가해 fan-out 코멘트의 pre-fill 로 활용할지.
4. R7-C (LLM claim extractor) 와의 순서 — R8-B 후 LLM extractor 가 anchor 의
   evidence cluster 단위로 호출되면 비용 효율 ↑.

이 4 항목은 R8-B-impl 진입 전에 사용자 결정 필요.

---

## 13. 변경하지 않는 것 (이번 packet 범위 보장)

- `report_output/` (final / draft) — 0
- approved output — 0
- `wiki/` — 0
- 08N81 draft — 0
- LLM 호출 — 0
- 기존 `_build_shared_context` 코드 — 0 (design only)
- `debate_engine.py` — 0
- agent 출력 schema — 0 (이번 packet 단계)

본 markdown 파일 1 개만 신규 (`market_research/docs/r8b_asset_movement_anchored_debate.md`).
