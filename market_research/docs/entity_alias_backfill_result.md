# Entity alias backfill — result (v13.2)

- 작성: 2026-04-21
- 입력: `entity_alias_backfill_review.md` 의 4건 approve
- 적용 위치: `config/phrase_alias_approved.yaml` (코드 수정 없음)

---

## 1. 적용된 alias

```yaml
"국제유가": 에너지_원자재     # arts=1032
"호르무즈 해협": 지정학        # arts=553
"호르무즈 봉쇄": 지정학        # arts=78
"이란 협상": 지정학            # arts=165
```

`alias_review --apply` 검증: **5 accepted (1 기존 이란 위기 + 4 신규)**.
`taxonomy._load_approved_alias()` setdefault — builtin PHRASE_ALIAS 우선, conflict 0.

---

## 2. Before / After 요약

### 2.1 Taxonomy gate hit

| | hit / total nodes |
|---|---|
| **before** | 4 / 101 (3.96%) |
| **after** | 8 / 101 (7.92%) |
| 증감 | +4 (+100%) |

**after gate hit 8건 전체**:
환율 / 유가 / 반도체 / 이란 (기존) + 국제유가 / 호르무즈 봉쇄 / 이란 협상 / 호르무즈 해협 (신규)

### 2.2 Final entity count

| | 페이지 수 |
|---|---|
| **before** | 4 (유가 / 이란 / 환율 / 반도체) |
| **after** | 7 |
| 증감 | +3 |

신규 entity 4건 후보 중 1건은 `per_taxonomy_cap=3`에 막혀 탈락 (지정학 그룹: 이란 + 호르무즈 해협 + 호르무즈 봉쇄 = 3건 cap 충족, 이란 협상은 ranking에서 밀림).

---

## 3. 신규 편입 entity

| label | taxonomy_topic | node_importance | unique_articles | events | ranking |
|-------|----------------|-----------------|-----------------|--------|---------|
| 국제유가 | 에너지_원자재 | 2.396 | 1032 | 420 | 3위 |
| 호르무즈 해협 | 지정학 | 1.852 | 553 | 290 | 4위 |
| 호르무즈 봉쇄 | 지정학 | 0.517 | 78 | 44 | 7위 |

**탈락**: `이란 협상` (지정학 cap에서 4번째라 drop. importance 0.34 추정).

---

## 4. 전체 7건 final ranking

```
1. 유가          | 에너지_원자재  | imp=4.088 | arts=2542 | events=1237 | path_role=True
2. 이란          | 지정학        | imp=2.805 | arts=3096 | events=1693
3. 국제유가      | 에너지_원자재  | imp=2.396 | arts=1032 | events= 420  ← 신규
4. 호르무즈 해협 | 지정학        | imp=1.852 | arts= 553 | events= 290  ← 신규
5. 환율          | 환율_FX       | imp=1.686 | arts=2092 | events= 940
6. 반도체        | 테크_AI_반도체 | imp=0.772 | arts=2234 | events=1858
7. 호르무즈 봉쇄 | 지정학        | imp=0.517 | arts=  78 | events=  44  ← 신규
```

---

## 5. 회귀 결과

| 테스트 | before | after | 비고 |
|--------|--------|-------|------|
| test_taxonomy_contract | 3/3 | 3/3 | — |
| test_alias_review | 6/6 | 6/6 | yaml validation 정상 |
| test_entity_builder | 7/7 | 7/7 | case2 miss list 갱신 (호르무즈 봉쇄 제거) |
| test_entity_demo_render | 5/5 | 5/5 | — |

writer 경계: `entity_builder` / `draft_pages` / yaml 외 변경 0건.
canonical regime / debate_memory / regime_memory.json 미수정.

---

## 6. Go / No-go 판정

### **GO** (조건부 — alias 4건 한정 GO, defer 라운드는 별도 검토)

근거:
- entity 수 4 → 7 (+75%) — 의미 있는 증가
- 신규 3건 모두 article evidence 충분 (78~1032 articles)
- 다의어 risk=low로 분류된 후보만 통과, false positive 우려 낮음
- per_taxonomy_cap=3 작동 확인 (4번째 후보 자동 drop) — 과밀 방지 작동
- contract 위반 0건, 회귀 0건

추가 GO 신호:
- `호르무즈 해협 / 봉쇄`는 v15 replay에서 sentiment_flip 분석 시 명시적 reference로 등장하고 있어, base entity page가 있으면 cross-link 가치 있음
- `국제유가`는 `유가`와 별개 graph node (label 다름)이지만 동일 dimension → 두 entity 모두 가지면 분석 깊이 늘어남

리스크 한계:
- entity 7건은 여전히 sparse — taxonomy에 "국내주식"·"해외주식" 항목 자체가 없는 한 코스피/나스닥/삼성전자 류는 영원히 miss
- `이란 협상` 같은 4번째 후보가 cap에 가려 안 보임 — `per_taxonomy_cap` 4로 늘릴지 별도 판단

### NO-GO 시 결론 (대안)

만약 위 결과를 NO-GO로 본다면 권고는: **02_Entities 확대보다 07_Graph_Evidence summary
강화에 집중**. 그러나 현재 결과는 GO 조건을 충족하므로 이 옵션은 보류.

---

## 7. 다음 라운드 후보 (defer 항목)

| phrase | 다음 라운드 검토 사유 |
|--------|----------------------|
| `달러` | TOPIC_TAXONOMY 내 `달러_글로벌유동성` vs `환율_FX` 매핑 정책 확정 후 결정 |
| `삼성전자` / `SK하이닉스` | sector entity 외 종목 entity 정책 신설 여부 결정 |
| `지정학적_리스크_확대` | descriptive form alias 정책 (현재 contract와 충돌 우려) |
| `per_taxonomy_cap` 조정 | 현재 3 → 4 또는 5로 늘릴지, 가시성 vs 노이즈 trade-off 검토 |

별도 alias_review 루프에서 처리. 본 batch에서는 다루지 않음.

---

## 8. 변경 파일

```
M  market_research/config/phrase_alias_approved.yaml      # +5 line, 4 alias
M  market_research/tests/test_entity_builder.py           # case2 miss list 갱신
A  market_research/docs/entity_alias_backfill_review.md   # 후보 검토표
A  market_research/docs/entity_alias_backfill_result.md   # 본 문서
M  market_research/data/wiki/02_Entities/                 # +3 신규 페이지
```

**entity_builder.py / draft_pages.py 코드 수정 없음** — 작업지시서 §핵심 원칙 3
("entity selection 로직 자체는 원칙적으로 수정하지 않는다") 준수.
