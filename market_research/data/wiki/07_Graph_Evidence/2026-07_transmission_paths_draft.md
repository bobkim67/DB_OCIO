---
type: graph_evidence
status: draft
promoted_to_canonical: false
period: 2026-07
total_paths: 2
node_count: ?
edge_count: ?
source_of_truth: graph_rag.precompute_transmission_paths
phase: P0
updated_at: 2026-07-01T08:08:47
---

# Transmission Paths (DRAFT) — 2026-07

> Draft evidence only. **Do not reference from canonical asset/regime pages.**
> Promotion to canonical is gated on Phase 4+.

## Summary

- Total paths: 2
- Graph nodes: ? · edges: ?

## Paths

| # | Trigger | Target | Confidence | Path |
|---|---------|--------|------------|------|
| 1 | `테크_AI_반도체` | `국내주식` | 0.922 | 반도체 → 삼성전자·SK하이닉스_시총_비중 → 코스피_지수_변동 |
| 2 | `테크_AI_반도체` | `해외주식` | 0.938 | 빅테크_기업_밸류에이션_상승 → 나스닥_지수_견인 |

## Usage guardrails

- 이 페이지는 `07_Graph_Evidence/` 하위 draft. canonical 05/01~04 페이지가 직접 참조하면 안 된다.
- P0 개선 (word-boundary 매칭 + self-loop 필터 + pair당 1경로) 적용 버전.
- P1 (dynamic trigger/target + alias) 완료 시 별도 페이지 분기 예정.
- P1까지 완료된 경로만 canonical asset page의 supporting evidence로 승격 검토 가능 (Phase 4+).

