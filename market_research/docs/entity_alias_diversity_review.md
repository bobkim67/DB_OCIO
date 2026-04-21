# Alias diversity review — under-covered 보강 (v13.3 Step 4)

- 작성: 2026-04-21
- 우선순위: 지정학 alias 추가 금지. 경기_소비/관세_무역/달러_글로벌유동성/환율_FX/테크 보강 검토.

---

## 1. 후보 검토표

| # | phrase | proposed | in_graph | arts | events | risk | rec | reason |
|---|--------|----------|---------:|-----:|-------:|------|-----|--------|
| 1 | `원/달러` | 환율_FX | ✓ | 183 | 80 | low | **APPROVE** | 환율 명백, 다의 없음, near-dup risk 0 (substring 무관) |
| 2 | `삼성전자` | 테크_AI_반도체 | ✓ | 1756 | 1410 | med | **defer** | 종목명 정책 미정 (sector vs 종목 entity 분리 정책 결정 후 일괄 처리) |
| 3 | `SK하이닉스` | 테크_AI_반도체 | ✓ | 1021 | 902 | med | **defer** | 동일 |
| 4 | `나스닥` | 테크_AI_반도체 (또는 해외주식) | ✓ | 894 | 319 | high | **REJECT** | 나스닥은 미국 증시 일반 (IT 외 포함). taxonomy에 "해외주식" 자체가 없어 임의 매핑 contract 위반 |
| 5 | `유로` | 환율_FX 또는 지정학(유럽) | ✓ | 191 | 137 | high | **REJECT** | 통화/지역/유로존 정책 다의어 |
| 6 | `달러` | 환율_FX 또는 달러_글로벌유동성 | ✓ | 3625 | 2017 | **high** | **defer** | 별도 audit (`dollar_taxonomy_policy_review.md`) — defer 결론 |
| 7 | `원_달러_환율_변동` | 환율_FX | ✓ | — | — | low | defer | descriptive form, "환율"·"원달러" 이미 alias로 충분 |
| 8 | `반도체_업황_변화` | 테크_AI_반도체 | ✓ | — | — | low | defer | descriptive form |
| 9 | (관세 직접 단어) | 관세_무역 | — | — | — | — | n/a | graph node에 "관세"·"무역" 단독 노드 없음. 4월 데이터 자체 부재 |
| 10 | (경기 직접 단어) | 경기_소비 | — | — | — | — | n/a | 동일. graph node에 단독 명사 없음 |

지정학 후보는 검토 대상에서 제외 (이번 batch 금지).

---

## 2. 승인 결과

**APPROVE 1건**:
- `원/달러 → 환율_FX` (arts=183, events=80, risk=low)

**DEFER 4건**: 삼성전자 / SK하이닉스 / 달러 / 원_달러_환율_변동 / 반도체_업황_변화

**REJECT 2건**: 나스닥 / 유로

**N/A 2건**: 관세_무역, 경기_소비 (graph node 자체 부재)

---

## 3. 예상 영향

| taxonomy | before (entities) | new alias | after 예상 |
|----------|-------------------|-----------|-----------|
| 환율_FX | 1 | +1 (원/달러) | 2 |
| 다른 under-covered | 0 | 0 | 0 |

→ 환율_FX 보강 1건. 나머지 under-covered taxonomy(경기·관세·달러유동성·부동산·크립토)는 본 batch에서 변화 없음.
→ 지정학 비중은 소폭 하락 가능성 (분모 늘어 비중 감소).

---

## 4. 다음 라운드 후보 (defer/지정학 외)

본 batch 외 다음 라운드에서 검토:
- 종목 entity 정책 (sector entity layer 외 별도)
- 다의어 split rule (분류기 신뢰도 측정 후)
- under-covered taxonomy 14개 중 alias 풀이 5 이하인 것들의 systematic 조사
- floor=1 활성화 후 영향 측정
