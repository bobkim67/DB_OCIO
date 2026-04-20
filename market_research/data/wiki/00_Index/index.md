---
type: wiki_index
updated_at: 2026-04-20T09:31:25
---

# Wiki Index

Latest period: **2026-04**

## Tier map

- **Base pages (01~04)** — factual aggregation from refine step
  - `01_Events/` — event pages (event_group_id 단위)
  - `02_Entities/` — entity pages
  - `03_Assets/` — asset pages
  - `04_Funds/` — fund pages
- **Confirmed memory (05)** — `05_Regime_Canonical/` — daily_update.Step 5 writer only
- **Provisional memory (06)** — `06_Debate_Memory/` — debate_engine interpretations
- **Graph evidence (07)** — `07_Graph_Evidence/` — transmission path draft (not canonical)

## Latest batch counts (base pages)
- Events: 5
- Entities: 8
- Assets: 6
- Funds: 2

## Query routing order
1. `05_Regime_Canonical/` (confirmed memory)
2. `01_Events/` ~ `04_Funds/` (base pages)
3. `06_Debate_Memory/` (interpretations)
4. `07_Graph_Evidence/` or GraphRAG retrieval
5. raw source chunk

