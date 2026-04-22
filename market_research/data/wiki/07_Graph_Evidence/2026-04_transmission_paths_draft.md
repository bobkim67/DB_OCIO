---
type: graph_evidence
status: draft
promoted_to_canonical: false
period: 2026-04
total_paths: 7
node_count: 263
edge_count: 241
source_of_truth: graph_rag.precompute_transmission_paths
phase: P0
updated_at: 2026-04-22T13:14:23
---

# Transmission Paths (DRAFT) — 2026-04

> Draft evidence only. **Do not reference from canonical asset/regime pages.**
> Promotion to canonical is gated on Phase 4+.

## Summary

- Total paths: 7
- Graph nodes: 263 · edges: 241

## Paths

| # | Trigger | Target | Confidence | Path |
|---|---------|--------|------------|------|
| 1 | `통화정책` | `환율` | 0.186 | 한은_기준금리_결정_→_내외금리차_변화 → 자본_유출입_변화_→_원달러_환율_변동 |
| 2 | `물가_인플레이션` | `금리` | 0.650 | 전쟁으로_인한_인플레이션_압력 → 중앙은행_금리_정책_변화_검토 |
| 3 | `지정학` | `국내주식` | 0.422 | 지정학적_리스크_완화 → 투자_심리_개선 → 외국인_자금_유입 → 코스피_상승 |
| 4 | `지정학` | `유가` | 0.800 | 트럼프_대이란_제재_정책_발표 → 이란_원유_수출_제한 |
| 5 | `지정학` | `금리` | 0.650 | 전쟁으로_인한_인플레이션_압력 → 중앙은행_금리_정책_변화_검토 |
| 6 | `지정학` | `크립토` | 0.303 | 지정학적_리스크_완화 → 위험자산_선호_심리_회복 → 비트코인_등_가상자산_가격_상승 |
| 7 | `에너지_원자재` | `환율` | 0.173 | 유가상승_→_경상수지_악화 → 달러_수요_증가_→_원화_약세_→_환율_상승 |

## Usage guardrails

- 이 페이지는 `07_Graph_Evidence/` 하위 draft. canonical 05/01~04 페이지가 직접 참조하면 안 된다.
- P0 개선 (word-boundary 매칭 + self-loop 필터 + pair당 1경로) 적용 버전.
- P1 (dynamic trigger/target + alias) 완료 시 별도 페이지 분기 예정.
- P1까지 완료된 경로만 canonical asset page의 supporting evidence로 승격 검토 가능 (Phase 4+).

