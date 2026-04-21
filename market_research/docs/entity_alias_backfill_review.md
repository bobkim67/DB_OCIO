# Entity alias backfill — review (v13.2)

- 작성: 2026-04-21
- 입력 데이터:
  - `data/insight_graph/2026-04.json` (101 nodes, 4 hits / 97 misses)
  - `data/news/2026-04.json` (article matching evidence)
  - `_taxonomy_remap_trace.jsonl` (현재 0 entries — 이전 정리 후 누적 없음)
- 목적: PHRASE_ALIAS coverage 부족이 entity gate hit 4의 진짜 원인인지
  검증. **"entity를 늘리는 작업"이 아니라 "안전하게 늘릴 수 있는지 판정"**.

---

## 1. 후보 풀 — 분류

97개 miss를 3개 그룹으로 분류 (entity_builder._norm 기반 자동 분류):

| 그룹 | 개수 | 예시 |
|------|------|------|
| (A) 단독 명사형 | 14 | 달러 / 코스피 / 전쟁 / 국제유가 / 코스닥 / 나스닥 / 삼성전자 / SK하이닉스 / 유로 / 협상 / 긴장 ... |
| (B) 이벤트/구문 (≤4토큰) | 57 | 달러_강세_약세 / 유가_급등_압력 / 지정학적_리스크_확대 / 중동_원유_수송로_차단 / 글로벌_원유_공급_급감 ... |
| (C) 서술형 / 긴 문장 | 26 | 호르무즈 해협 / 미-이란 협상 결렬 / 호르무즈_해협_긴장_봉쇄_위협 / 이란_핵협상_또는_제재_강화 ... |

---

## 2. 후보 검토표 (16개 검토 → 4 approve / 8 reject / 4 defer)

| # | phrase | observed arts | events | proposed taxonomy | risk | rec | reason |
|---|--------|---------------|--------|-------------------|------|-----|--------|
| 1 | `국제유가` | 1032 | 420 | `에너지_원자재` | low | **APPROVE** | "유가" 동의어. 다의 없음. |
| 2 | `호르무즈 해협` | 553 | 290 | `지정학` | low | **APPROVE** | 지리적 명사. 지정학 외 해석 사실상 없음. |
| 3 | `호르무즈 봉쇄` | 78 | 44 | `지정학` | low | **APPROVE** | event form. supply/oil 맥락이지만 1차 분류는 지정학. |
| 4 | `이란 협상` | 165 | 58 | `지정학` | low | **APPROVE** | "이란"·"이란 위기" 이미 alias. "협상"도 같은 정치 dimension. |
| 5 | `미-이란 협상 결렬` | **0** | 0 | `지정학` | — | **REJECT** | article 0건 → alias 추가해도 entity 안 생김. (실제 표기 "미국-이란" 등으로 분기) |
| 6 | `지정학적_리스크_확대` | 35 | 33 | `지정학` | low | **defer** | descriptive form. "지정학적 리스크"는 이미 alias. underscore form 추가 가치 미미, contract와 충돌 우려. |
| 7 | `달러` | 3625 | 2017 | `달러_글로벌유동성` 또는 `환율_FX` | **high (다의어)** | **defer** | 환율_FX(USD/KRW 통화) vs 달러_글로벌유동성(funding/리저브) — 맥락에 따라 다름. 별도 정책 라운드 필요. |
| 8 | `코스피` | 2525 | 1629 | (없음) | — | **REJECT** | TOPIC_TAXONOMY 14에 "국내주식" 항목 없음. 임의 매핑 시 contract 위반. |
| 9 | `코스닥` | 1279 | 952 | (없음) | — | **REJECT** | 동일 이유. |
| 10 | `나스닥` | 894 | 319 | `테크_AI_반도체`? | med | **REJECT** | 나스닥은 미국 증시 일반(IT 외 포함). "테크"로만 보면 부정확, 해외주식 분류 항목 자체가 taxonomy에 없음. |
| 11 | `삼성전자` | 1756 | 1410 | `테크_AI_반도체` | med | **defer** | 종목명 alias 정책 미정. taxonomy는 sector level까지. 별도 라운드. |
| 12 | `SK하이닉스` | 1021 | 902 | `테크_AI_반도체` | med | **defer** | 동일. |
| 13 | `전쟁` | 2934 | 1881 | `지정학` | **high (다의어)** | **REJECT** | 우크라/중동/관세전쟁/심리전 등 광범위. false hit 다대. |
| 14 | `유로` | 191 | 137 | `환율_FX` 또는 `지정학(유럽)` | high | **REJECT** | 통화/지역/유로존 정책 등 다의어. |
| 15 | `유가_급등_압력` | **0** | 0 | `에너지_원자재` | — | **REJECT** | article 0건. graph node에서만 등장하는 LLM-inferred 구문. |
| 16 | `중동_지역_군사적_긴장_고조` | 0 | 0 | `지정학` | — | **REJECT** | article 0건. inferred 노드. |

> 0건 후보를 reject한 이유: alias 추가해도 entity 후보가 evidence gate
> (article≥2 OR event≥1 OR path_role)을 통과하지 못하므로 변화 없음.
> "후보 풀에서 거를" 단계에서 미리 정리.

---

## 3. 승인 규칙 적용 결과

**APPROVE (4건)**:
- `국제유가 → 에너지_원자재`
- `호르무즈 해협 → 지정학`
- `호르무즈 봉쇄 → 지정학`
- `이란 협상 → 지정학`

**REJECT (8건)**: 코스피, 코스닥, 나스닥, 전쟁, 유로, 미-이란 협상 결렬, 유가_급등_압력, 중동_지역_군사적_긴장_고조

**DEFER (4건)**: 달러, 삼성전자, SK하이닉스, 지정학적_리스크_확대

---

## 4. 예상 영향

| taxonomy | before (entities) | new alias 후보 | after 예상 (cap=3 적용) |
|----------|-------------------|----------------|--------------------------|
| 에너지_원자재 | 1 (유가) | +1 (국제유가) | 2 |
| 지정학 | 1 (이란) | +3 (호르무즈 해협, 호르무즈 봉쇄, 이란 협상) | min(4, cap=3) = 3 |
| 환율_FX | 1 (환율) | 0 | 1 |
| 테크_AI_반도체 | 1 (반도체) | 0 | 1 |
| **합계** | **4** | +4 후보 (per_taxonomy_cap 적용 후 +3) | **7 예상** |

per_taxonomy_cap=3로 "지정학" 그룹은 4개 후보 중 3개만 살아남음 (이란 + 신규 3 → 4 → cap drops 1).
실제 어느 후보가 떨어지는지는 랭킹(path_role_hit DESC, node_importance DESC, unique_article_count DESC)에 의존.

---

## 5. 다음 단계

→ Step 3 (yaml 적용) → Step 4 (refresh 재실행 + 비교) → Step 5 (go/no-go).

결과 문서: `entity_alias_backfill_result.md`.
