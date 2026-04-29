---
type: graph_evidence
status: draft
promoted_to_canonical: false
period: 2026-02
total_paths: 4
node_count: 246
edge_count: 231
source_of_truth: graph_rag.precompute_transmission_paths
phase: P0
updated_at: 2026-04-22T12:59:35
---

# Transmission Paths (DRAFT) — 2026-02

> Draft evidence only. **Do not reference from canonical asset/regime pages.**
> Promotion to canonical is gated on Phase 4+.

## Summary

- Total paths: 4
- Graph nodes: 246 · edges: 231

## Paths

| # | Trigger | Target | Confidence | Path |
|---|---------|--------|------------|------|
| 1 | `통화정책` | `환율` | 0.422 | 기준금리_결정 → 외환시장_개입 → 시장_기대_변화 → 환율 |
| 2 | `통화정책` | `크립토` | 0.107 | Fed_금리정책_발표 → 위험자산_선호도_변화 → 비트코인 |
| 3 | `관세_무역` | `크립토` | 0.360 | 무역_불확실성_증가 → 위험자산_선호도_변화 → 비트코인 |
| 4 | `경기_소비` | `금리` | 0.480 | 한은_경기_판단_수정 → 통화정책_방향_재검토 → 한은 → 기준금리_결정 |

## Usage guardrails

- 이 페이지는 `07_Graph_Evidence/` 하위 draft. canonical 05/01~04 페이지가 직접 참조하면 안 된다.
- P0 개선 (word-boundary 매칭 + self-loop 필터 + pair당 1경로) 적용 버전.
- P1 (dynamic trigger/target + alias) 완료 시 별도 페이지 분기 예정.
- P1까지 완료된 경로만 canonical asset page의 supporting evidence로 승격 검토 가능 (Phase 4+).

