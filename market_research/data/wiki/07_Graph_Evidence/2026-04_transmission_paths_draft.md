---
type: graph_evidence
status: draft
promoted_to_canonical: false
period: 2026-04
total_paths: 5
node_count: 274
edge_count: 252
source_of_truth: graph_rag.precompute_transmission_paths
phase: P0
updated_at: 2026-04-21T09:52:10
---

# Transmission Paths (DRAFT) — 2026-04

> Draft evidence only. **Do not reference from canonical asset/regime pages.**
> Promotion to canonical is gated on Phase 4+.

## Summary

- Total paths: 5
- Graph nodes: 274 · edges: 252

## Paths

| # | Trigger | Target | Confidence | Path |
|---|---------|--------|------------|------|
| 1 | `물가_인플레이션` | `국내주식` | 0.658 | 국내_수입_비용_증가_및_인플레이션_우려 → 기업_수익성_악화_전망 → 증시_하락_압력 → 코스피 |
| 2 | `지정학` | `국내주식` | 0.879 | 지정학적_리스크_확대 → 외국인_투자자_위험회피 → 코스피_하락_압력 |
| 3 | `지정학` | `유가` | 0.942 | 호르무즈 긴장 → 호르무즈_해협_원유_운송_차질_우려 |
| 4 | `관세_무역` | `국내주식` | 0.239 | 수출입_비용_및_경상수지_영향 → 투자심리_및_외국인_자금흐름_변동 → 코스피 |
| 5 | `테크_AI_반도체` | `국내주식` | 0.960 | 반도체_업황_변화 → 코스피_지수_연동 |

## Usage guardrails

- 이 페이지는 `07_Graph_Evidence/` 하위 draft. canonical 05/01~04 페이지가 직접 참조하면 안 된다.
- P0 개선 (word-boundary 매칭 + self-loop 필터 + pair당 1경로) 적용 버전.
- P1 (dynamic trigger/target + alias) 완료 시 별도 페이지 분기 예정.
- P1까지 완료된 경로만 canonical asset page의 supporting evidence로 승격 검토 가능 (Phase 4+).

