---
type: entity
status: base
entity_id: graphnode__환율
label: "환율"
topic: news
period: 2026-04
graph_node_id: 환율
canonical_entity_label: "환율"
linked_events: [event_0, event_4, event_6, event_7, event_10]
has_draft_evidence: true
draft_sources: [graph_evidence]
source_of_truth: pipeline_refine
updated_at: 2026-04-20T09:31:25
---

# Entity — 환율

**Canonical label**: `환율`  
**Topic**: `news` · **Graph node**: `환율`

## Confirmed facts  _[source: `pipeline_refine`]_

- Mentioned in **6** articles this period
- Linked events: `event_0`, `event_4`, `event_6`, `event_7`, `event_10`
- Related asset classes (derived): `환율`
- Related funds: —  _(populated in a later batch)_

### Recent articles
- [오늘 금시세]호르무즈 해협 재개방에 금값, 상승 마감 전망
- [오늘의 금시세] 4월 20일, 이란 긴장 속 환율 상승…금값 약세
- 코스피 상승 출발, 원달러환율은 하락
- 코스피, 중동 긴장 재격화에도 상승…6200선 출발
- 환율, 미·이란 휴전 종료 시한 임박 속 소폭 하락…1,478.4원
- 코스피, 0.36% 상승 개장...6,210대 등락

## Draft evidence  _[source: `07_Graph_Evidence` · draft]_

> Adjacency and transmission paths below are **draft evidence** produced
> by GraphRAG. Do NOT treat as confirmed regime signal.
> Canonical regime lives in `05_Regime_Canonical/`.

### Graph adjacency (top 5)
- ← `원_달러_환율_변동`  (causes, w=0.51)
- ← `원_달러`  (correlates, w=0.38)
- → `원화약세→외국인_자금유출`  (causes, w=0.26)
- ← `환율_상승_하락`  (causes, w=0.12)

### Transmission paths involving this node
- _No transmission path matched this node this period._

## Provenance

- Base entity: `pipeline_refine` (daily_update Step 2.5 / 2.6)
- Graph node: `환율`
- Confidence proxy (node severity): `neutral`

> Base page. Canonical regime → `05_Regime_Canonical/`. Debate commentary → `06_Debate_Memory/`. Full transmission paths → `07_Graph_Evidence/`.
