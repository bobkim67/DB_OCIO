# Entity diversity result — before/after (v13.3 Step 6)

- 작성: 2026-04-21
- 변경 적용: alias `원/달러 → 환율_FX` 1건 + `suppress_near_duplicates=True`

---

## 1. Before / After 요약

### 1.1 Final entity count

| | total | 분포 | 지정학 비중 |
|---|------:|------|-------------|
| **before (v13.2)** | 7 | 지정학 3 / 에너지 2 / FX 1 / 테크 1 | 43% (3/7) |
| **after (v13.3)** | 7 | 지정학 3 / 에너지 1 / FX 2 / 테크 1 | 43% (3/7) |

총 entity 수는 동일하나 분포가 변경됨.

### 1.2 Taxonomy coverage

| | covered taxonomies (14 중) |
|---|---|
| **before** | 4 (지정학 / 에너지 / FX / 테크) |
| **after** | 4 (지정학 / 에너지 / FX / 테크) |

coverage 동일.

---

## 2. 신규 편입 / 제거 entity

### 신규 편입
| label | taxonomy | 이유 |
|-------|----------|------|
| 원/달러 | 환율_FX | alias 신규 (`원/달러 → 환율_FX`) |

### 제거
| label | taxonomy | 이유 |
|-------|----------|------|
| 국제유가 | 에너지_원자재 | suppress_near_duplicates: "유가" ⊂ "국제유가" 관계, 후순위 drop |

### 기존 유지 (5건)
유가 / 이란 / 호르무즈 해협 / 환율 / 반도체 / 호르무즈 봉쇄

---

## 3. 전체 7건 final ranking

| # | label | taxonomy | importance | arts | events |
|---|-------|----------|-----------:|-----:|-------:|
| 1 | 유가 | 에너지_원자재 | 4.088 | 2,542 | 1,237 |
| 2 | 이란 | 지정학 | 2.805 | 3,096 | 1,693 |
| 3 | 호르무즈 해협 | 지정학 | 1.852 | 553 | 290 |
| 4 | 환율 | 환율_FX | 1.686 | 2,092 | 940 |
| 5 | 반도체 | 테크_AI_반도체 | 0.772 | 2,234 | 1,858 |
| 6 | 호르무즈 봉쇄 | 지정학 | 0.517 | 78 | 44 |
| 7 | **원/달러** ⓝ | 환율_FX | 0.282 | 183 | 80 |

ⓝ = v13.3 신규

`이란 협상`은 substring(이란)에 의해 suppress + 지정학 cap=3에 의해 어차피 drop됐을 것.

---

## 4. `달러` 편입 여부

**미편입 (의도된 결과)**.
`달러` 단독은 audit 결과(`dollar_taxonomy_policy_review.md`) defer 유지.
graph node `달러`는 taxonomy gate에서 계속 탈락.

---

## 5. False positive 의심 사례

`원/달러` 신규 entity 검수:
- arts=183 (4월 17일 기간 매칭)
- events=80
- 표본 title 검토:
  ```
  ['외환마감] 원·달러 환율 1504.2원···2.1원↓
  '호르무즈 해협 개방' 기대감에 환율 14.5원 내린 1505.2원
  트럼프 "2~3주간 이란 강한 공격"…원·달러 환율 1520원 돌파
  ```
- 모두 환율 맥락. **false positive 0건 관측**.

`국제유가` suppression 검수:
- 같은 dimension의 `유가`가 보존되어 **정보 손실 없음**.
- `국제유가` graph node 자체는 그대로 존재 (graph 분석에는 영향 없음).
- 본 변화는 **02_Entities/ 표면적 다양성** 조정에 한정.

---

## 6. 회귀

```
test_taxonomy_contract   3/3 PASS
test_alias_review        6/6 PASS
test_entity_builder      9/9 PASS  (case 8/9 신규 — suppress + floor 검증)
test_entity_demo_render  5/5 PASS
test_regime_replay       8/8 PASS
test_regime_decision_v12 4/4 PASS
test_regime_monitor      7/7 PASS
```

전체 42/42 PASS (v13.2의 40 + entity_builder case 8/9 신규).

---

## 7. 최종 권고

### **Adopt diversity controls** (suppress_near_duplicates 활성화 + floor 옵션화)

근거:
- entity 수 동일(7) 유지하면서 information de-duplication 달성 (유가/국제유가)
- 환율_FX 보강(1→2)으로 단일 dominant taxonomy 의존도 약간 완화
- 지정학 비중 % 자체는 변화 없음 — 분모/분자 모두 변화 없는 결과
- contract 위반 0, false positive 관측 0
- floor=1은 옵션만 추가 (default off) — 미래 alias 보강 시 활성화

### Adopt 안 할 것

- `달러` split rule: evidence 부족 (audit 결과)
- 종목명 alias 일괄 추가: 정책 미정
- `cap=2`로 축소: 지정학 비중 개선 폭이 entity 정보 손실(7→5)을 정당화 못함

---

## 8. 변경 파일 요약

```
M  market_research/wiki/entity_builder.py            # +per_taxonomy_floor, +suppress_near_duplicates 옵션
M  market_research/wiki/draft_pages.py               # refresh 호출에 suppress=True
M  market_research/config/phrase_alias_approved.yaml # +1 alias (원/달러)
M  market_research/tests/test_entity_builder.py      # +case8/9
A  market_research/docs/entity_diversity_diagnosis.md
A  market_research/docs/dollar_taxonomy_policy_review.md
A  market_research/docs/entity_diversity_policy_options.md
A  market_research/docs/entity_alias_diversity_review.md
A  market_research/docs/entity_diversity_result.md
M  market_research/data/wiki/02_Entities/            # 국제유가 → 원_달러로 교체
```

`entity_builder` 본문 로직 미수정 (옵션 flag만 추가). writer 경계 (05/06/07) 불변.
