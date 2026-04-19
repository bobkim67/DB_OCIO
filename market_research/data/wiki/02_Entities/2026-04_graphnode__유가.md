---
type: entity
status: base
entity_id: graphnode__유가
label: "유가"
topic: news
period: 2026-04
graph_node_id: 유가
canonical_entity_label: "유가"
linked_events: [event_12, event_29, event_35, event_39, event_44]
has_draft_evidence: true
draft_sources: [graph_evidence]
source_of_truth: pipeline_refine
updated_at: 2026-04-17T14:39:28
---

# Entity — 유가

**Canonical label**: `유가`  
**Topic**: `news` · **Graph node**: `유가`

## Confirmed facts  _[source: `pipeline_refine`]_

- Mentioned in **6** articles this period
- Linked events: `event_12`, `event_29`, `event_35`, `event_39`, `event_44`
- Related asset classes (derived): `원자재`
- Related funds: —  _(populated in a later batch)_

### Recent articles
- [경제 안테나] 원유가 충격과 인플레, 그리고 금리
- "중동전쟁에 경기 하방위험 커져...물가·민생부담 확대 우려"
- 트럼프 "이란전 순조롭게 진행" 발언에…국제유가 하락 전환
- 미-이란 협상 교착… 호르무즈 해협 봉쇄 우려에 국제유가 2%대 상승
- 이란 전쟁 종료 기대에 국제 유가 하락
- 트럼프 약발 끝?...장중, 아시아 6개국 증시 '일제히 하락'

## Draft evidence  _[source: `07_Graph_Evidence` · draft]_

> Adjacency and transmission paths below are **draft evidence** produced
> by GraphRAG. Do NOT treat as confirmed regime signal.
> Canonical regime lives in `05_Regime_Canonical/`.

### Graph adjacency (top 5)
- ← `원유_선물_가격_급등`  (causes, w=0.83)
- ← `국제유가`  (correlates, w=0.69)
- ← `공급_차질_우려_심화`  (causes, w=0.66)
- → `에너지·소재_기업_수익성_변화`  (causes, w=0.63)
- → `에너지_비용_상승`  (causes, w=0.45)

### Transmission paths involving this node
- trigger `지정학` → target `유가`: `지정학적_리스크_상승` → `중동_산유국_공급_불안` → `원유_선물_가격_급등` → `유가`  (conf=0.79)
- trigger `유가_급등` → target `유가`: `유가_급등_압력` → `국제유가`  (conf=0.66)
- trigger `지정학` → target `유가`: `중동_지정학적_불안_고조` → `유가_상승_우려`  (conf=0.64)
- trigger `유가_급등` → target `유가`: `유가_급등_압력` → `국제유가` → `유가`  (conf=0.44)

## Provenance

- Base entity: `pipeline_refine` (daily_update Step 2.5 / 2.6)
- Graph node: `유가`
- Confidence proxy (node severity): `neutral`

> Base page. Canonical regime → `05_Regime_Canonical/`. Debate commentary → `06_Debate_Memory/`. Full transmission paths → `07_Graph_Evidence/`.
