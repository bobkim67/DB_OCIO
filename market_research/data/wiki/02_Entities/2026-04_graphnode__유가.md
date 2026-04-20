---
type: entity
status: base
entity_id: graphnode__유가
label: "유가"
topic: news
period: 2026-04
graph_node_id: 유가
canonical_entity_label: "유가"
linked_events: [event_4, event_5, event_18, event_21, event_25]
has_draft_evidence: true
draft_sources: [graph_evidence]
source_of_truth: pipeline_refine
updated_at: 2026-04-20T09:31:25
---

# Entity — 유가

**Canonical label**: `유가`  
**Topic**: `news` · **Graph node**: `유가`

## Confirmed facts  _[source: `pipeline_refine`]_

- Mentioned in **6** articles this period
- Linked events: `event_4`, `event_5`, `event_18`, `event_21`, `event_25`
- Related asset classes (derived): `원자재`
- Related funds: —  _(populated in a later batch)_

### Recent articles
- [오늘의 금시세] 4월 20일, 이란 긴장 속 환율 상승…금값 약세
- 호르무즈 긴장에 유가 반등…WTI 6%↑
- 호르무즈 긴장 고조…국제유가 급등·코스피 혼조
- [애널픽] "종전이후 종목 차별화…AI 인프라·증권 주목"
- 코스피, 장초반 횡보…국제유가 7% 급등
- 亞 장초반...한국·일본·호주증시 '혼조', 달러 '절상', 유가 '폭등'

## Draft evidence  _[source: `07_Graph_Evidence` · draft]_

> Adjacency and transmission paths below are **draft evidence** produced
> by GraphRAG. Do NOT treat as confirmed regime signal.
> Canonical regime lives in `05_Regime_Canonical/`.

### Graph adjacency (top 5)
- ← `유가_상승_압력`  (causes, w=0.91)
- ← `유가_변동`  (causes, w=0.87)
- ← `원유_선물_가격_급등`  (causes, w=0.58)
- → `에너지·소재_기업_수익성_변화`  (causes, w=0.48)
- ← `국제유가`  (correlates, w=0.37)

### Transmission paths involving this node
- trigger `지정학` → target `유가`: `호르무즈_해협_긴장_봉쇄_위협` → `원유_수송로_차단_우려`  (conf=0.98)

## Provenance

- Base entity: `pipeline_refine` (daily_update Step 2.5 / 2.6)
- Graph node: `유가`
- Confidence proxy (node severity): `neutral`

> Base page. Canonical regime → `05_Regime_Canonical/`. Debate commentary → `06_Debate_Memory/`. Full transmission paths → `07_Graph_Evidence/`.
