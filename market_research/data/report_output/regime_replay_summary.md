# Regime replay summary

> **Historical replay / backfill — NOT live monitor.**
> Supplementary verification path. Does not touch
> `regime_memory.json`, live `_regime_quality.jsonl`, or
> `05_Regime_Canonical/*`. Thresholds are not tuned from this
> artefact alone.

- Generated: `2026-04-17T17:49:42`
- Window: `2026-04-01` ~ `2026-04-17`
- Lookback: **45** days
- Initial state: `neutral_empty`
- Total replay dates: **17**  (unique: 17)
- Total loaded articles (union across touched months): 58,871
- Per-date avg article count (asof-slice): 1262.29
- Runtime: **351.63 s**

## Aggregate indicators (replay)

| indicator | value |
|---|---|
| candidate_days | 0 |
| confirmed_count | 0 |
| sentiment_flip_days | 0 |
| cooldown_days | 14 |
| empty_tag_days | 17 |
| avg coverage_current | 0.0 |
| avg coverage_today (core_top3) | 0.0 |
| churn proxy (confirmed / candidate_day) | None |

## consecutive_day_distribution

| consecutive_days | count |
|---|---|
| 0 | 17 |

## Notes

- Replay loop builds one row per calendar date in the window,
  including days with zero articles (delta remains empty, judgement
  runs on the carry state).
- Each date uses only articles with `date <= asof`; future rows in
  `_taxonomy_remap_trace.jsonl` / `_regime_quality.jsonl` do not
  influence any asof cut.
- Initial state is `neutral_empty` — the live regime snapshot is
  deliberately not used to avoid leaking live state into historical
  backfill.
- `churn_proxy` here is a day-level proxy (candidate_days includes
  same calendar-day, since replay emits one row per calendar date).
