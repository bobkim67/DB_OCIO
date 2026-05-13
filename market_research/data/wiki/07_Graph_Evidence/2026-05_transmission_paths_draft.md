---
type: graph_evidence
status: draft
promoted_to_canonical: false
period: 2026-05
total_paths: 9
node_count: ?
edge_count: ?
source_of_truth: graph_rag.precompute_transmission_paths
phase: P0
updated_at: 2026-05-06T12:49:54
---

# Transmission Paths (DRAFT) — 2026-05

> Draft evidence only. **Do not reference from canonical asset/regime pages.**
> Promotion to canonical is gated on Phase 4+.

## Summary

- Total paths: 9
- Graph nodes: ? · edges: ?

## Paths

| # | Trigger | Target | Confidence | Path |
|---|---------|--------|------------|------|
| 1 | `통화정책` | `해외주식` | 0.878 | 유가_상승_→_인플레이션_압력_→_연준_긴축_우려_→_S&P500_하락_압력 → S&P500 |
| 2 | `물가_인플레이션` | `해외주식` | 0.898 | 지정학적_불확실성_해소_→_인플레이션_압력_완화_기대_→_기업_실적_전망_개선_→_S&P500_상승 → S&P500 |
| 3 | `지정학` | `해외주식` | 0.898 | 지정학적_불확실성_해소_→_인플레이션_압력_완화_기대_→_기업_실적_전망_개선_→_S&P500_상승 → S&P500 |
| 4 | `지정학` | `유가` | 0.938 | 지정학적_분쟁_휴전_합의_→_공급_차질_우려_완화_→_유가_하락_압력 → 유가 |
| 5 | `지정학` | `금리` | 0.809 | 지정학적_분쟁_휴전_합의_→_공급_차질_우려_완화_→_유가_하락_압력 → 유가 → 유가_상승_→_물가_상승_→_금리_인상_기대_→_성장주_밸류에이션_압박_→_나스닥_하락 |
| 6 | `테크_AI_반도체` | `국내주식` | 0.968 | 반도체_업황_→_대형주_주가_→_코스피_지수_변동 → 코스피 |
| 7 | `테크_AI_반도체` | `해외주식` | 0.910 | 빅테크·제조업_실적_영향 → S&P500_구성_종목_주가_반영 |
| 8 | `에너지_원자재` | `해외주식` | 0.878 | 유가 → 유가_상승_→_인플레이션_압력_→_연준_긴축_우려_→_S&P500_하락_압력 |
| 9 | `에너지_원자재` | `금리` | 0.863 | 유가 → 유가_상승_→_물가_상승_→_금리_인상_기대_→_성장주_밸류에이션_압박_→_나스닥_하락 |

## Usage guardrails

- 이 페이지는 `07_Graph_Evidence/` 하위 draft. canonical 05/01~04 페이지가 직접 참조하면 안 된다.
- P0 개선 (word-boundary 매칭 + self-loop 필터 + pair당 1경로) 적용 버전.
- P1 (dynamic trigger/target + alias) 완료 시 별도 페이지 분기 예정.
- P1까지 완료된 경로만 canonical asset page의 supporting evidence로 승격 검토 가능 (Phase 4+).

