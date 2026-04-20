---
type: entity
status: base
entity_id: graphnode__달러
label: "달러"
topic: 달러
period: 2026-04
graph_node_id: 달러
canonical_entity_label: "달러"
linked_events: [event_0, event_1, event_4, event_5, event_6]
has_draft_evidence: true
draft_sources: [graph_evidence]
source_of_truth: pipeline_refine
updated_at: 2026-04-20T09:31:25
---

# Entity — 달러

**Canonical label**: `달러`  
**Topic**: `달러` · **Graph node**: `달러`

## Confirmed facts  _[source: `pipeline_refine`]_

- Mentioned in **6** articles this period
- Linked events: `event_0`, `event_1`, `event_4`, `event_5`, `event_6`
- Related asset classes (derived): —
- Related funds: —  _(populated in a later batch)_

### Recent articles
- [오늘 금시세]호르무즈 해협 재개방에 금값, 상승 마감 전망
- [오늘의 채권ㆍ외환 메모] (04월20일)
- [오늘의 금시세] 4월 20일, 이란 긴장 속 환율 상승…금값 약세
- 호르무즈 긴장에 유가 반등…WTI 6%↑
- 코스피 상승 출발, 원달러환율은 하락
- 코스피, 중동 긴장 재격화에도 상승…6200선 출발

## Draft evidence  _[source: `07_Graph_Evidence` · draft]_

> Adjacency and transmission paths below are **draft evidence** produced
> by GraphRAG. Do NOT treat as confirmed regime signal.
> Canonical regime lives in `05_Regime_Canonical/`.

### Graph adjacency (top 5)
- → `달러_강세_약세`  (causes, w=0.51)
- ← `달러_강세_또는_약세_반응`  (reacts_to, w=0.42)
- → `달러-유로_역의_상관관계`  (correlates, w=0.31)

### Transmission paths involving this node
- _No transmission path matched this node this period._

## Provenance

- Base entity: `pipeline_refine` (daily_update Step 2.5 / 2.6)
- Graph node: `달러`
- Confidence proxy (node severity): `neutral`

> Base page. Canonical regime → `05_Regime_Canonical/`. Debate commentary → `06_Debate_Memory/`. Full transmission paths → `07_Graph_Evidence/`.
