---
type: graph_evidence
status: draft
promoted_to_canonical: false
period: 2026-03
total_paths: 11
node_count: 258
edge_count: 233
source_of_truth: graph_rag.precompute_transmission_paths
phase: P0
updated_at: 2026-04-22T13:05:52
---

# Transmission Paths (DRAFT) — 2026-03

> Draft evidence only. **Do not reference from canonical asset/regime pages.**
> Promotion to canonical is gated on Phase 4+.

## Summary

- Total paths: 11
- Graph nodes: 258 · edges: 233

## Paths

| # | Trigger | Target | Confidence | Path |
|---|---------|--------|------------|------|
| 1 | `통화정책` | `국내주식` | 0.537 | Fed_통화정책_결정_→_미국_기준금리_변동 → 글로벌_금리_수준_영향 → 금리 → 기준금리_변동_→_국고채_금리_연동_변화 |
| 2 | `통화정책` | `국내채권` | 0.767 | Fed_통화정책_결정_→_미국_기준금리_변동 → 글로벌_금리_수준_영향 → 금리 → 기준금리_변동_→_국고채_금리_연동_변화 |
| 3 | `통화정책` | `유가` | 0.272 | 한국은행_금융통화위원회_→_기준금리_결정_→_시장금리_영향 → 금리 → 금리인상_→_달러_강세 → 달러_강세_→_원자재_가격유가_하락_압력 |
| 4 | `통화정책` | `환율` | 0.750 | 한은_기준금리_결정_→_내외금리차_변화 → 자본_유출입_변화_→_원달러_환율_변동 |
| 5 | `물가_인플레이션` | `국내주식` | 0.430 | 물가_상승인플레이션_→_중앙은행_긴축_필요성 → 기준금리_인상_결정 → 금리 → 기준금리_변동_→_국고채_금리_연동_변화 |
| 6 | `물가_인플레이션` | `국내채권` | 0.614 | 물가_상승인플레이션_→_중앙은행_긴축_필요성 → 기준금리_인상_결정 → 금리 → 기준금리_변동_→_국고채_금리_연동_변화 |
| 7 | `물가_인플레이션` | `금리` | 0.850 | 물가_상승인플레이션_→_중앙은행_긴축_필요성 → 기준금리_인상_결정 |
| 8 | `지정학` | `국내주식` | 0.800 | 전쟁_발발_→_지정학적_리스크_확대 → 글로벌_투자심리_악화_→_외국인_매도_→_코스피_하락 |
| 9 | `지정학` | `유가` | 0.850 | 전쟁_발발중동_산유국_→_원유_공급_차질_우려 → 공급_불안_→_유가_상승 |
| 10 | `에너지_원자재` | `국내주식` | 0.490 | 유가상승_→_에너지비용_증가 → 기업_수익성_악화 → 투자심리_위축_→_코스피_하락 |
| 11 | `에너지_원자재` | `환율` | 0.700 | 유가상승_→_경상수지_악화 → 달러_수요_증가_→_원화_약세_→_환율_상승 |

## Usage guardrails

- 이 페이지는 `07_Graph_Evidence/` 하위 draft. canonical 05/01~04 페이지가 직접 참조하면 안 된다.
- P0 개선 (word-boundary 매칭 + self-loop 필터 + pair당 1경로) 적용 버전.
- P1 (dynamic trigger/target + alias) 완료 시 별도 페이지 분기 예정.
- P1까지 완료된 경로만 canonical asset page의 supporting evidence로 승격 검토 가능 (Phase 4+).

