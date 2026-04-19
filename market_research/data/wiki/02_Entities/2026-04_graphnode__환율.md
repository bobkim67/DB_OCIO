---
type: entity
status: base
entity_id: graphnode__환율
label: "환율"
topic: news
period: 2026-04
graph_node_id: 환율
canonical_entity_label: "환율"
linked_events: [event_0, event_5, event_6, event_7, event_26]
has_draft_evidence: true
draft_sources: [graph_evidence]
source_of_truth: pipeline_refine
updated_at: 2026-04-17T14:39:28
---

# Entity — 환율

**Canonical label**: `환율`  
**Topic**: `news` · **Graph node**: `환율`

## Confirmed facts  _[source: `pipeline_refine`]_

- Mentioned in **6** articles this period
- Linked events: `event_0`, `event_5`, `event_6`, `event_7`, `event_26`
- Related asset classes (derived): `환율`
- Related funds: —  _(populated in a later batch)_

### Recent articles
- 센터포인트에너지, 분기 배당 주당 0.23달러 확정…6월 11일 지급
- '경상수지 흑자=환율 하락' 공식 깨졌다..."개인 해외 투자 확대 영향"
- [서환] 개장 전 마(MAR) '+0.05원' 거래…픽싱 스퀘어
- 정부 "중동 전쟁에 경기 하방위험 확대"
- 한은 "'경상흑자=환율 하락' 공식 깨져"… 해외투자·저축 증가 영향
- 톰 리 “이번 하락은 크립토 윈터 아니다”…비트코인, 기술주와 동조 ...

## Draft evidence  _[source: `07_Graph_Evidence` · draft]_

> Adjacency and transmission paths below are **draft evidence** produced
> by GraphRAG. Do NOT treat as confirmed regime signal.
> Canonical regime lives in `05_Regime_Canonical/`.

### Graph adjacency (top 5)
- ← `원_달러_환율_변동`  (causes, w=0.80)
- ← `원_달러`  (correlates, w=0.71)
- → `원화약세→외국인_자금유출`  (causes, w=0.49)
- ← `환율_상승_하락`  (causes, w=0.29)

### Transmission paths involving this node
- _No transmission path matched this node this period._

## Provenance

- Base entity: `pipeline_refine` (daily_update Step 2.5 / 2.6)
- Graph node: `환율`
- Confidence proxy (node severity): `neutral`

> Base page. Canonical regime → `05_Regime_Canonical/`. Debate commentary → `06_Debate_Memory/`. Full transmission paths → `07_Graph_Evidence/`.
