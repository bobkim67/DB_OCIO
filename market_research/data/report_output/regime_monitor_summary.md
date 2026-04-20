# Regime monitor summary

- Generated: `2026-04-21T07:57:39`
- Source: `data\report_output\_regime_quality.jsonl`
- Window: `2026-04-08` ~ `2026-04-21` (14 days)
- Source rows: 97  (window rows: 97, malformed skipped: 0)

> `source_rows` = 전체 집계 대상 row 수. `window_rows` = 윈도우 내 row.
> `unique_dates_in_window` = 실제 관측 일수. 동일 날짜에 여러 row가
> append될 수 있으므로 row 수와 관측 일수는 다를 수 있다.
> 지표 이름에 `_rows`가 붙은 것은 모두 **row-level count**이며,
> day-level 해석은 `unique_dates_in_window`가 충분히 커진 뒤에만
> 의미를 가진다.

## Aggregate indicators (row-level operational observation)

| indicator | value |
|---|---|
| source_rows | 97 |
| window_rows | 97 |
| unique_dates_in_window | 3 |
| unique_date_coverage_ratio | 0.2143 |
| row_per_date_ratio | 32.33 |
| observed_unique_dates_with_candidate | 3 |
| observed_unique_dates_with_empty_tags | 3 |
| malformed_skipped | 0 |
| shift_candidate_rows | 32 |
| shift_confirmed_count | 1 |
| sentiment_flip_rows | 31 |
| cooldown_block_rows | 32 |
| sparse_fallback_rows | 30 |
| empty_tag_rows | 32 |
| avg coverage_current | 0.0968 |
| avg coverage_today (core top3) | 0.0107 |
| churn proxy (confirmed / candidate_row) | 0.0312 |

## consecutive_row_streak distribution

| consecutive_row_streak | rows |
|---|---|
| 0 | 65 |
| 1 | 31 |
| 3 | 1 |

## candidate_rule distribution

| rule | count |
|---|---|
| `low_coverage_today` | 90 |
| `low_coverage_current` | 75 |
| `sentiment_flip` | 31 |

## Day-level prep metrics (v14)

- `unique_date_coverage_ratio` = unique_dates / window_days
  (`null` when `window_days=0`). Tells the reviewer how close the
  summary is to a full day-level view of the window.
- `row_per_date_ratio` = window_rows / unique_dates (`null` when no
  dates). High values mean many same-date appends — operational
  debug noise, not drift signal.
- `observed_unique_dates_with_candidate` — distinct dates that
  produced at least one `shift_candidate=true` row. Day-level
  proxy; row-level equivalent is `shift_candidate_rows`.
- `observed_unique_dates_with_empty_tags` — distinct dates that
  saw at least one empty-tags hold. Day-level proxy for
  `empty_tag_rows`.

> These four indicators are passive prep metrics. They do NOT drive
> any decision and do NOT change v12 judgement logic. Use them to
> tell row-level append noise apart from day-level drift.

## Notes

- This report is passive. v12 thresholds (coverage_current 0.5 /
  coverage_today=core_top3 / sentiment_flip; 3-day consecutive + 14-day
  cooldown) are **not** tuned here. Accumulate sufficient
  `unique_dates_in_window` (≥14) before any re-tuning decision
  (see review_packet_v12_1.md → section 6).
- All `_rows` indicators count jsonl rows, not distinct days.
  Same-date append (tests, debug, multi-scenario rerun) inflates row
  counts without adding day-level coverage. True day-level drift
  interpretation is blocked until `unique_dates_in_window` grows.
- `churn_proxy` low means most candidate rows did not convert to
  confirmed, which is *consistent* with the 3-day consecutive guard —
  but it is not proof the guard is firing, because "consecutive" here
  is row-level streak, not day-level streak. Read as operational
  observation only.
- `empty_tag_rows` counts rows where `current.topic_tags` was empty —
  those are held intentionally (description-based judgement is banned).
