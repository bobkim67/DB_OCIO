---
type: graph_evidence
status: draft
promoted_to_canonical: false
period: 2026-04
total_paths: 4
node_count: 274
edge_count: 252
source_of_truth: graph_rag.precompute_transmission_paths
phase: P0
updated_at: 2026-04-20T09:32:14
---

# Transmission Paths (DRAFT) — 2026-04

> Draft evidence only. **Do not reference from canonical asset/regime pages.**
> Promotion to canonical is gated on Phase 4+.

## Summary

- Total paths: 4
- Graph nodes: 274 · edges: 252

## Paths

| # | Trigger | Target | Confidence | Path |
|---|---------|--------|------------|------|
| 1 | `물가_인플레이션` | `국내주식` | 0.754 | 국내_수입_비용_증가_및_인플레이션_우려 → 기업_수익성_악화_전망 → 증시_하락_압력 → 코스피 |
| 2 | `지정학` | `국내주식` | 0.906 | 지정학적_리스크_부각 → 글로벌_위험회피_심리_확산 → 외국인_투자자_신흥국_자산_매도 → 코스피_하락_압력 |
| 3 | `지정학` | `유가` | 0.986 | 호르무즈 긴장 → 호르무즈_해협_원유_운송_차질_우려 |
| 4 | `관세_무역` | `국내주식` | 0.342 | 수출입_비용_및_경상수지_영향 → 투자심리_및_외국인_자금흐름_변동 → 코스피 |

## Usage guardrails

- 이 페이지는 `07_Graph_Evidence/` 하위 draft. canonical 05/01~04 페이지가 직접 참조하면 안 된다.
- P0 개선 (word-boundary 매칭 + self-loop 필터 + pair당 1경로) 적용 버전.
- P1 (dynamic trigger/target + alias) 완료 시 별도 페이지 분기 예정.
- P1까지 완료된 경로만 canonical asset page의 supporting evidence로 승격 검토 가능 (Phase 4+).

