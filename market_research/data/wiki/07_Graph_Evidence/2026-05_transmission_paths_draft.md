---
type: graph_evidence
status: draft
promoted_to_canonical: false
period: 2026-05
total_paths: 2
node_count: ?
edge_count: ?
source_of_truth: graph_rag.precompute_transmission_paths
phase: P0
updated_at: 2026-05-06T08:54:38
---

# Transmission Paths (DRAFT) — 2026-05

> Draft evidence only. **Do not reference from canonical asset/regime pages.**
> Promotion to canonical is gated on Phase 4+.

## Summary

- Total paths: 2
- Graph nodes: ? · edges: ?

## Paths

| # | Trigger | Target | Confidence | Path |
|---|---------|--------|------------|------|
| 1 | `테크_AI_반도체` | `국내주식` | 0.857 | 삼성전자·SK하이닉스_등_반도체_대형주_주가_변동 → 코스피_시가총액_비중_상위_종목_등락 |
| 2 | `테크_AI_반도체` | `해외주식` | 0.910 | 빅테크·제조업_실적_영향 → S&P500_구성_종목_주가_반영 |

## Usage guardrails

- 이 페이지는 `07_Graph_Evidence/` 하위 draft. canonical 05/01~04 페이지가 직접 참조하면 안 된다.
- P0 개선 (word-boundary 매칭 + self-loop 필터 + pair당 1경로) 적용 버전.
- P1 (dynamic trigger/target + alias) 완료 시 별도 페이지 분기 예정.
- P1까지 완료된 경로만 canonical asset page의 supporting evidence로 승격 검토 가능 (Phase 4+).

