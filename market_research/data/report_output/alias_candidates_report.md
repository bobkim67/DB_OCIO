# Alias candidates report

- Generated: `2026-04-17T17:10:42`
- Source: `data\report_output\_taxonomy_remap_trace.jsonl`
- Total trace rows: **31**
- Match type counts: exact=3, alias=18, unresolved=10

## Unresolved phrases (propose candidates)

| phrase | count | sources | suggested tag | score | action |
|---|---|---|---|---|---|
| `에너지 인플레이션 압박의 긴장.` | 1 | history[5] | 물가_인플레이션 | 0.90 | review_needed |
| `구조적 유가 급등의 불안정한 균형` | 1 | history[4] | 에너지_원자재 | 0.60 | review_needed |
| `구조적 인플레 딜레마` | 1 | history[1] | 물가_인플레이션 | 0.60 | review_needed |
| `이란 위기` | 1 | history[7] | 지정학 | 0.60 | review_needed |
| `에너지 인플레 압력 교차` | 1 | history[2] | 물가_인플레이션 | 0.30 | keep_unresolved |
| `유가 구조적 충격의 줄다리기` | 1 | history[11] | 에너지_원자재 | 0.30 | keep_unresolved |
| `유가 인플레 충격` | 1 | history[3] | 물가_인플레이션 | 0.30 | keep_unresolved |
| `인플레 압력의 불확실성 충돌` | 1 | history[6] | 물가_인플레이션 | 0.30 | keep_unresolved |
| `인플레·성장 둔화의 불확실성 충돌` | 1 | history[0] | 물가_인플레이션 | 0.30 | keep_unresolved |
| `단기 랠리와 장기 리스크의 불일치` | 1 | regime_current | — | — | keep_unresolved |

## Action legend

- `propose_alias` — high confidence (score ≥ 0.4, count ≥ 2).
  Consider copying to `config/phrase_alias_approved.yaml::approved`.
- `review_needed` — medium confidence (score ≥ 0.4, count 1). Human review.
- `keep_unresolved` — no confident hit. Add to `keep_unresolved:` if it
  is a known descriptive phrase that should stay out of topic_tags.

## How to approve

1. Edit `market_research/config/phrase_alias_approved.yaml`.
2. Under `approved:`, add `"<phrase>": <taxonomy_tag>` entries.
3. Run `python -m market_research.tools.alias_review --apply` to
   validate and preview the runtime merge.

> Force-mapping descriptive phrases is disallowed by the v11 taxonomy
> contract. If the top suggestion is not accurate, prefer `keep_unresolved`.
