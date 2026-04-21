# -*- coding: utf-8 -*-
"""market_research.core — 공유 인프라 (DB, BM, 상수, JSON 유틸)"""

from market_research.core.db import DB_CONFIG, get_conn, parse_blob
from market_research.core.benchmarks import BENCHMARK_MAP, BM_ASSET_CLASS_MAP, BM_SEARCH_QUERIES
from market_research.core.constants import FUND_CONFIGS, ANTHROPIC_API_KEY, LLM_MODEL, PA_CLASSIFICATION_RULES
