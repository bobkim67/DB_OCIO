# -*- coding: utf-8 -*-
"""Wiki directory layout constants."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WIKI_ROOT = BASE_DIR / 'data' / 'wiki'

INDEX_DIR = WIKI_ROOT / '00_Index'
EVENTS_DIR = WIKI_ROOT / '01_Events'
ENTITIES_DIR = WIKI_ROOT / '02_Entities'
ASSETS_DIR = WIKI_ROOT / '03_Assets'
FUNDS_DIR = WIKI_ROOT / '04_Funds'
REGIME_CANONICAL_DIR = WIKI_ROOT / '05_Regime_Canonical'
DEBATE_MEMORY_DIR = WIKI_ROOT / '06_Debate_Memory'
GRAPH_EVIDENCE_DIR = WIKI_ROOT / '07_Graph_Evidence'
CLAIMS_WIKI_DIR = WIKI_ROOT / '08_Claims'
# wiki_from_naver_research — research consensus staging/audit (09, 05 renumber 안 함)
RESEARCH_SYNTHESIS_DIR = WIKI_ROOT / '09_Research_Synthesis'

for _d in (INDEX_DIR, EVENTS_DIR, ENTITIES_DIR, ASSETS_DIR, FUNDS_DIR,
           REGIME_CANONICAL_DIR, DEBATE_MEMORY_DIR, GRAPH_EVIDENCE_DIR,
           CLAIMS_WIKI_DIR, RESEARCH_SYNTHESIS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
