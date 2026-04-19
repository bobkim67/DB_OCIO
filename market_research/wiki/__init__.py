# -*- coding: utf-8 -*-
"""Wiki layer — canonical / draft / debate memory pages.

Two-tier design:
  - Canonical (daily_update only writer): confirmed regime, event, entity, asset, fund
  - Draft/Debate (debate_engine writer): debate narrative, alt interpretations, watchpoints

See: market_research/docs/graphrag_transmission_paths_review.md §Part 2
"""
from market_research.wiki.paths import (
    WIKI_ROOT, INDEX_DIR, EVENTS_DIR, ENTITIES_DIR, ASSETS_DIR, FUNDS_DIR,
    REGIME_CANONICAL_DIR, DEBATE_MEMORY_DIR, GRAPH_EVIDENCE_DIR,
)
from market_research.wiki.canonical import (
    update_canonical_regime, write_regime_history_page, normalize_regime_memory,
)
from market_research.wiki.debate_memory import write_debate_memory_page
from market_research.wiki.graph_evidence import (
    write_transmission_paths_draft, write_transmission_paths_summary,
)
from market_research.wiki.draft_pages import (
    write_event_page, write_entity_page, write_asset_page, write_fund_page,
    refresh_base_pages_after_refine,
    refresh_draft_pages_after_refine,   # 하위 호환 alias
)

__all__ = [
    'WIKI_ROOT', 'INDEX_DIR', 'EVENTS_DIR', 'ENTITIES_DIR', 'ASSETS_DIR',
    'FUNDS_DIR', 'REGIME_CANONICAL_DIR', 'DEBATE_MEMORY_DIR', 'GRAPH_EVIDENCE_DIR',
    'update_canonical_regime', 'write_regime_history_page', 'normalize_regime_memory',
    'write_debate_memory_page',
    'write_transmission_paths_draft', 'write_transmission_paths_summary',
    'write_event_page', 'write_entity_page', 'write_asset_page', 'write_fund_page',
    'refresh_base_pages_after_refine',
    'refresh_draft_pages_after_refine',
]
