---
type: graph_evidence
status: draft
promoted_to_canonical: false
period: 2026-04
total_paths: 6
node_count: 274
edge_count: 252
source_of_truth: graph_rag.precompute_transmission_paths
phase: P0
updated_at: 2026-04-17T13:24:14
---

# Transmission Paths (DRAFT) — 2026-04

> Draft evidence only. **Do not reference from canonical asset/regime pages.**
> Promotion to canonical is gated on Phase 4+.

## Summary

- Total paths: 6
- Graph nodes: 274 · edges: 252

## Paths

| # | Trigger | Target | Confidence | Path |
|---|---------|--------|------------|------|
| 1 | `물가_인플레이션` | `국내주식` | 0.358 | 인플레이션_압력_증가 → 투자심리_위축 → 코스피 |
| 2 | `물가_인플레이션` | `금리` | 0.298 | 인플레이션_압력_상승 → 기준금리_조정_검토 |
| 3 | `지정학` | `국내주식` | 0.588 | 지정학적_불확실성_완화 → 투자심리_개선 → 코스피 |
| 4 | `지정학` | `유가` | 0.925 | 중동_산유국_공급_불안 → 원유_선물_가격_급등 |
| 5 | `관세_무역` | `국내주식` | 0.770 | 수출입_비용_및_경상수지_영향 → 투자심리_및_외국인_자금흐름_변동 → 코스피 |
| 6 | `에너지_원자재` | `국내주식` | 0.256 | 유가_상승_우려 → 위험자산_선호_약화 → 외국인_매도세_확대 → 코스피 |

## Usage guardrails

- 이 페이지는 `07_Graph_Evidence/` 하위 draft. canonical 05/01~04 페이지가 직접 참조하면 안 된다.
- P0 개선 (word-boundary 매칭 + self-loop 필터 + pair당 1경로) 적용 버전.
- P1 (dynamic trigger/target + alias) 완료 시 별도 페이지 분기 예정.
- P1까지 완료된 경로만 canonical asset page의 supporting evidence로 승격 검토 가능 (Phase 4+).

