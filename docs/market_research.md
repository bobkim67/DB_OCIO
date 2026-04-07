# market_research

## Purpose

`market_research/` supports macro monitoring and report-comment generation for the OCIO dashboard.

It currently covers four layers:

1. daily data collection
2. monthly blog digest generation
3. news vector indexing and retrieval
4. market-environment / report cache generation

## Directory Layout

```text
market_research/
  collect_news.bat
  engine.py
  digest_builder.py
  news_vectordb.py
  comment_engine.py
  report_cache_builder.py
  report_cli.py
  scrapers/
    macro_data.py
    naver_blog.py
  data/
    macro/
    news/
    report_cache/
    news_vectordb/
    monygeek/
      posts.json
      log_nos.json
      monthly_digests/
  output/
```

## Main Components

### `scrapers/macro_data.py`

- Collects macro-related news
- Collects macro indicator series
- Writes monthly news JSON and macro indicator files

### `scrapers/naver_blog.py`

- Incrementally scrapes the `monygeek` blog
- Maintains:
  - `posts.json`
  - `log_nos.json`

### `digest_builder.py`

- Builds monthly structured digests from blog posts
- Main function:
  - `build_monthly_digest(year, month)`

### `engine.py`

- Matches blog topics with macro indicators
- Builds pattern DB
- Produces current macro diagnosis
- Main functions:
  - `build()`
  - `infer()`

### `news_vectordb.py`

- Builds and queries the vector index used for factor retrieval
- Used by report comment workflows

### `comment_engine.py`

- Generates market-environment and report text
- Important functions:
  - `generate_common_market(...)`
  - `generate_report(...)`

### `report_cache_builder.py`

- Builds JSON cache files for the Streamlit report tab
- Writes:
  - `data/report_cache/catalog.json`
  - `data/report_cache/{YYYY-MM}/{fund_code}.json`

### `report_cli.py`

- CLI wrapper around report generation logic

## Current Integration With Dashboard

- `tabs/macro.py`
  - partially uses `market_research.comment_engine`
  - especially for benchmark period-return presentation
- `tabs/report.py`
  - reads batch-generated JSON caches only
  - does not directly import heavy `market_research` runtime code for normal rendering

## Current Automation

- Daily automation entrypoint:
  - `market_research/collect_news.bat`
- Startup trigger:
  - Windows Startup shortcut `CollectNews.lnk`
- Current fixed behavior:
  - Startup shortcut now launches `cmd.exe /c "...collect_news.bat"`
  - batch now also rebuilds report cache after digest/vector refresh

## Confirmed 2026-03-31 State

- Prior root cause:
  - Startup shortcut targeted a nonexistent sandbox path
- Fix:
  - vendored `market_research/` into this repo
  - rewrote batch file to use repo-relative paths
  - repaired Startup shortcut
- Verification:
  - `collect_20260331.log` created successfully
  - blog/news/vector files updated successfully
  - `data/report_cache/2026-03/*.json` generated for five report funds

## Known Gaps

- NewsAPI collection is not currently restricted to same-day-only articles
- Some Korean strings are still mojibake in generated cache/catalog payloads because upstream source strings need cleanup
- Blog scraping still emits a `cp949` console-encoding warning on emoji output
- `prototype.py` app-shell refactor is not fully finished yet

## Recommended Next Refactor

1. Keep `tabs/report.py` cache-only and avoid reintroducing direct `market_research` runtime imports into Streamlit
2. Clean up Korean source strings so report cache payloads are human-readable
3. Keep `modules/comment_ui.py` as a temporary compatibility wrapper only
4. Add explicit NewsAPI date-window policy
5. Separate collection, digest, RAG, and comment ownership across agents
