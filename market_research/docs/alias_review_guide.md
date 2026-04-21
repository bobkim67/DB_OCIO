# Alias review operational guide (v14)

> Short, practical guide for the `propose → approve → apply → runtime overlay`
> loop around `PHRASE_ALIAS`. The policy here is **propose-only** —
> `taxonomy.py` source is never auto-mutated. Approved entries live in
> `config/phrase_alias_approved.yaml` and are merged at import time via
> `setdefault` (built-in wins on conflict).

## 1. Workflow at a glance

```text
┌──────────────────────────┐
│  _taxonomy_remap_trace   │  ← daily_update writes per-phrase mapping result
│  .jsonl (append-only)    │
└────────────┬─────────────┘
             │
             ▼
  propose ─► alias_candidates.{json,md}   ← human review artifact
             │
             ▼
  reviewer edits config/phrase_alias_approved.yaml
             │
             ▼
  apply --strict ─► validate + preview merge  (no code mutation)
             │
             ▼
  next import ─► taxonomy._load_approved_alias() overlays entries
             │
             ▼
  extract_taxonomy_tags("<phrase>") returns the mapped taxonomy label
```

CLI:
```bash
python -m market_research.tools.alias_review --propose
python -m market_research.tools.alias_review --apply --strict
```

## 2. What to approve — short rules

Approve a phrase when it is:

- **Short and referential.** Named event, named region, concrete subject.
  Examples: `"이란 위기" → 지정학`, `"휴전" → 지정학`.
- **Repeatable.** The phrase is likely to appear again in future news.
  One-shot sentences are not worth a permanent entry.
- **Single-topic.** It cleanly maps to exactly one taxonomy label. If the
  phrase could plausibly map to 2+ labels, don't approve.
- **Not already covered by built-in.** Check `--apply` output — if it shows
  `duplicates (same target)`, the built-in already handles it.

Counterexamples (do NOT approve):

- `"구조적 인플레 딜레마"` — descriptive, interpretation-heavy. Even if
  "딜레마" weakly hints at 물가_인플레이션, the full phrase encodes a
  narrative stance, not a topic tag.
- `"단기 랠리와 장기 리스크의 불일치"` — a full sentence. No taxonomy label
  carries this meaning without loss.
- `"유가 구조적 충격의 줄다리기"` — mixes `유가` and `구조적 충격` and
  `줄다리기`. Forcing any single tag discards context.

## 3. What to put in `keep_unresolved`

Every phrase that should stay out of `topic_tags` permanently belongs here.
Annotate each entry with a short reason:

```yaml
keep_unresolved:
  - "단기 랠리와 장기 리스크의 불일치"   # 문장형 · 해석 의존
  - "유가 구조적 충격의 줄다리기"         # 문장형 · 해석 의존
```

Reasons commonly seen:
- `문장형` — the phrase is a full sentence, not a tag.
- `해석 의존` — mapping requires interpreting market narrative.
- `반복 주제성 낮음` — unlikely to recur, not worth a persistent entry.
- `taxonomy 강제 매핑 위험` — would distort the contract if mapped.
- `서술형 색채 강함` — carries opinion/framing, not a topic.

`keep_unresolved` is **documentation**, not code behaviour. The runtime
loader ignores it — its purpose is to prevent the same phrase from being
re-proposed every cycle by future reviewers.

## 4. Built-in conflicts

If `--apply` reports a `duplicates (same target)` row, the entry is
redundant. Remove it from `approved:` — the built-in already maps that
phrase to the same label. Keeping redundant entries inflates yaml churn
without any runtime effect.

If `--apply` reports a `REJECTED ... conflicts with builtin → X` row, the
yaml tried to re-target a phrase that the built-in maps to a different
label. **Do not force this.** Either:
- accept the built-in (remove the yaml entry), or
- open a separate task to revise the built-in (with justification — the
  built-in is hand-curated authority).

The loader enforces **setdefault semantics**: built-in wins on conflict.
`--apply` mirrors that by refusing to preview conflicts as accepted.

## 5. Strict mode

`--apply --strict` returns exit 1 if any yaml entry is rejected (non-taxonomy
value, or builtin conflict). CI or pre-commit can use this to refuse PRs
that would silently drop entries.

## 6. When to re-run `--propose`

- After a daily_update batch that generates new `_taxonomy_remap_trace.jsonl`
  rows.
- Monthly at minimum — accumulated `unresolved` with count ≥ 2 is the main
  signal that a new alias might be worth approving.

Phrases that only appear once (`count=1`) should stay in `keep_unresolved`
by default. The built-in map already covers the recurring cases.

## 7. Do not

- **Do not** edit `market_research/wiki/taxonomy.py::PHRASE_ALIAS` for
  reactive fixes. That file is for authoritative built-in entries only.
- **Do not** bypass `--apply --strict`. If strict fails, investigate —
  never comment-out the check.
- **Do not** map a phrase into two taxonomy labels. If a phrase is genuinely
  multi-topic, it belongs in `keep_unresolved` (or its text should be
  normalised upstream before it reaches the extractor).

## 8. First-loop evidence (v14)

The first end-to-end run of this workflow was completed in v14:

```
$ python -m market_research.tools.alias_review --apply --strict
accepted (new aliases): 1
  + "이란 위기" -> 지정학
keep_unresolved entries: 5
  ~ 단기 랠리와 장기 리스크의 불일치
  ~ 유가 구조적 충격의 줄다리기
  ~ 인플레·성장 둔화의 불확실성 충돌
  ~ 에너지 인플레이션 압박의 긴장.
  ~ 구조적 인플레 딜레마
exit=0

$ python -c "from market_research.wiki.taxonomy import extract_taxonomy_tags;
            print(extract_taxonomy_tags('이란 위기'))"
(['지정학'], [])
```

See `docs/review_packet_v14.md` §Workstream B for full evidence.
