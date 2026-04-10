# AGENTS.md

This file defines recommended agent ownership for this repository.

## Rules

- Keep `prototype.py` ownership separate from `modules/data_loader.py`.
- Only one agent may edit shared infra files at a time.
- Treat `market_research/` as a separate workstream from Streamlit tab modularization.
- First-pass work should focus on file boundaries and ownership, not broad logic redesign.

## UI Agents

### `app-shell-agent`

- Owns: `prototype.py`
- Responsibilities:
  - Streamlit bootstrapping
  - session/login state
  - top fund selector
  - `ctx` and cache registry assembly
  - tab routing

### `shared-infra-agent`

- Owns:
  - `modules/data_loader.py`
  - `modules/charts.py`
  - `config/funds.py`
- Responsibilities:
  - shared data access
  - chart helpers
  - fund metadata and mappings

### `overview-agent`

- Owns: `tabs/overview.py`
- Responsibilities:
  - KPI cards
  - NAV/BM/AUM display
  - period return table
  - latest holdings summary

### `holdings-agent`

- Owns: `tabs/holdings.py`
- Responsibilities:
  - holdings views
  - look-through flow
  - MP gap
  - holdings history charts

### `brinson-agent`

- Owns: `tabs/brinson.py`
- Responsibilities:
  - Brinson attribution UI
  - single-port PA display
  - fallback and formatting boundaries

### `macro-report-admin-agent`

- Owns:
  - `tabs/macro.py`
  - `tabs/admin.py`
  - `modules/comment_ui.py`
- Responsibilities:
  - macro tab cleanup
  - admin tab cleanup
  - report UI migration to `tabs/report.py`

## market_research Agents

### `mr-collector-agent`

- Owns:
  - `market_research/collect/macro_data.py`
  - `market_research/collect/naver_blog.py`
  - `market_research/collect/collect_news.bat`
- Responsibilities:
  - daily news collection
  - blog incremental updates
  - Windows batch/startup stability

### `mr-digest-agent`

- Owns:
  - `market_research/pipeline/digest_builder.py`
  - `market_research/analyze/engine.py`
- Responsibilities:
  - monthly digest generation
  - blog + indicator macro diagnosis
  - month-end macro summary logic

### `mr-rag-agent`

- Owns:
  - `market_research/analyze/news_vectordb.py`
  - `market_research/data/news/`
  - `market_research/data/news_vectordb/`
- Responsibilities:
  - vector index generation
  - news retrieval quality
  - factor search and categorization

### `mr-comment-agent`

- Owns:
  - `market_research/report/comment_engine.py`
  - `market_research/report/cli.py`
  - `modules/comment_ui.py`
- Responsibilities:
  - report comment generation
  - market environment text
  - LLM prompting and formatting

## Recommended Execution Order

1. `app-shell-agent`
2. `shared-infra-agent`
3. `overview-agent`, `holdings-agent`, `brinson-agent` in parallel
4. `macro-report-admin-agent`
5. `mr-collector-agent`, `mr-digest-agent`, `mr-rag-agent`, `mr-comment-agent` as a separate lane

## Files To Avoid Multi-Agent Conflicts On

- `prototype.py`
- `modules/data_loader.py`
- `modules/comment_ui.py`
- `market_research/data/news/{YYYY-MM}.json`
- `market_research/data/monygeek/posts.json`
- `market_research/data/news_vectordb/`
