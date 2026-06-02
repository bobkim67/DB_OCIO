# Research Taxonomy v2 — LLM Asset Mapping + Multi-Asset Claim (설계)

> 상태: **설계 (DESIGN ONLY)**. production 미수정. dry sample → 비교(rule/LLM/hybrid) → backtest 선행 필수.
> 작성: 2026-06-02. 선행: `classification_region_sector_taxonomy_v2.md` (region×sector rule routing).
> 범위: schema / prompt / validator / fallback priority / dry plan / 코드변경 inventory. **consumer 배선·flag ON·backtest 실행 금지.**

## 0. 한 줄 요지

리서치 문단을 LLM이 `region·sector·affected_assets[]·primary_asset·confidence`로 직접 해석하게 하고,
`route_by_region()`은 **production primary mapping이 아니라 fallback / consistency checker**로 강등한다.
claim은 단일 자산 강제 귀속을 폐기하고 **multi-asset 구조**(이미 부분 지원)를 명시 schema로 승격한다.

---

## 1. 가장 먼저 — 발견한 충돌 (설계 전 반드시 해소)

### 1.1 자산 enum이 두 개의 이름공간으로 갈라져 있음 ★최우선 리스크

| 공간 | 라벨 | 정의 위치 |
|---|---|---|
| **claim 다운스트림 계약 (8자산)** | `국내주식 해외주식 국내채권 해외채권 크레딧 현금성 환율(FX) 원자재금` | `analyze/claim_extractor.py:79` `ALLOWED_ASSET_CLASSES` |
| **selector canonical (route_by_region 출력)** | `국내주식 해외주식 국내채권 해외채권 환율 원자재에너지 금대체 크레딧 크립토` | `core/asset_taxonomy.py` `route_by_region` (이번 step1-3) |
| bridge dict | `환율(FX)→환율, 원자재금→금대체, 원자재→원자재에너지 …` | `core/asset_taxonomy.py:16` `ASSET_IMPACT_TO_CANONICAL` |

- **claim 계약(8)에는 `원자재에너지`·`금대체`·`크립토`가 없다.** 에너지·금이 모두 단일 `원자재금` 버킷으로 합쳐지고, 크립토는 OCIO 8자산에 아예 없음.
- `route_by_region`은 `원자재에너지`/`금대체`/`크립토`를 별개로 emit → **claim affected_assets에 그대로 넣으면 enum invalid.**
- `claim_primary_asset()`(`asset_taxonomy.py:103`)은 `ASSET_IMPACT_TO_CANONICAL.get(name, name)`로 `환율(FX)→환율`, `원자재금→금대체`로 역매핑 → claim store는 `환율(FX)/원자재금`을 쓰지만 selector는 `환율/금대체`로 본다.

### 1.2 워크오더 §5 제안 enum과의 불일치

워크오더 §5 MVP asset 후보(`…환율, 원자재에너지, 금대체, 크레딧, 현금성, 기타, UNKNOWN`)는 **세 번째 이름공간**을 만든다.

> **설계 결론 (1.A):** v2 `affected_assets[].asset`의 **source of truth = 기존 8-class `ALLOWED_ASSET_CLASSES`**.
> 새 enum(`원자재에너지/금대체/크립토/기타`)을 claim schema에 도입하지 않는다. 이유: claim store·debate prompt·
> wiki claim page·selector가 모두 8-class를 (직접 또는 bridge dict로) 소비 중. 세 번째 공간은 회귀 위험만 키움.
> - `원자재에너지`·`금대체` 구분은 **article-level(route_by_region) 편의**로만 유지 → claim 진입 시 `원자재금`으로 collapse.
> - `크립토`는 OCIO 8자산 밖 → claim affected_assets로 승격 안 함. (article 태그로만 보존, claim fallback=None+trace)
> - `기타`는 다운스트림 계약에 없음 → **추가하지 않음.** 미정은 `None`(claim 미생성) 또는 `UNKNOWN`(article meta only).

### 1.3 `topic` vs `sector` 필드명 (워크오더 §4.1)

- 현 article `_classified_topics[]`는 `topic` 키 사용 (news_classifier 전반·`route_by_region(region, sector)` 호출부 `asset_taxonomy.py:155`에서 `t.get("topic")`).
- claim에는 sector 필드 자체가 없음.

> **설계 결론 (1.B):** article-level은 기존 `topic` 키 유지(회귀 0). claim/문단 신규 출력은 `sector`로 명명하되,
> **소비부는 `t.get("sector") or t.get("topic")`로 양쪽 흡수.** prompt는 신규이므로 `sector` 출력으로 통일.

---

## 2. claim은 이미 multi-asset — v2는 "명시화"

- `affected_assets`는 **이미 list** of `{asset_class, direction}` (`claim_extractor.py:120`, 검증 `:552-577`).
- 추출 프롬프트 rule 5가 이미 "여러 자산군이면 3개 이상 명시"를 지시 (`claim_extractor_prompt.py:111`).
- 즉 multi-asset 컨테이너는 존재. **v2 신규분은:**
  1. affected_assets 항목에 `confidence`·`role` 추가 (현재 `asset_class`+`direction`만).
  2. 명시 `primary_asset` 필드 (현재는 `affected_assets[0]`에서 파생 — `claim_primary_asset()`).
  3. `regions`·`sectors` claim-level 메타 (현재 article에만 존재).

> **설계 결론 (2.A):** multi-asset claim **채택**. 단 호환 우선 — `affected_assets[]`의 `asset_class`/`direction` 키는
> 유지하고 `confidence`·`role`은 **optional 추가**. `primary_asset`·`regions`·`sectors`는 **OPTIONAL_FIELDS**로 추가
> (REQUIRED 승격 금지 → 기존 운영 claim이 validate fail 안 함, md5 drift 0).

---

## 3. 파이프라인 (목표)

```
research paragraph / section (현재는 리포트 title+요약 단위; 문단 세그멘테이션은 후순위)
  ↓ LLM classification (research_v2 prompt)
  region, region_confidence, affected_regions[]
  sector, sector_confidence, direction, intensity
  affected_assets[] = {asset, impact, confidence, role}   ← asset ∈ 8-class
  primary_asset (single, ∈ affected_assets)
  rationale, evidence_span
  ↓ validator (enum / floor / consistency / 개수 cap / primary∈affected / role=primary 1개)
  ↓ fallback priority
    1) LLM affected_assets+primary valid           → use LLM
    2) route_by_region(region, sector) → 8-class remap → use rule (route_source=rule)
    3) v1 article_primary_asset(article)            → use v1 (route_source=v1)
    4) None
  ↓ conflict trace (llm vs rule 불일치 시 consistency_warning 기록, LLM 우선 유지)
```

- **분류 단위:** MVP는 리서치 리포트(title+요약) 단위 유지. PDF 문단 세그멘테이션은 별 트랙(후순위).
- **route_by_region 강등:** production primary 결정자 → fallback/consistency checker. 제거 금지(§ non-goals).

---

## 4. Schema 제안

### 4.1 LLM classification output (문단/리포트 단위)

```json
{
  "items": [
    {
      "span_id": "doc1_p03_s02",
      "text_summary": "삼성전자·SK하이닉스 반도체 업황 개선으로 KOSPI 상승세",
      "region": "KR",
      "region_confidence": 0.92,
      "affected_regions": ["KR"],
      "sector": "테크_AI_반도체",
      "sector_confidence": 0.91,
      "direction": "positive",
      "intensity": 8,
      "affected_assets": [
        {"asset": "국내주식", "impact": "positive", "confidence": 0.93, "role": "primary"}
      ],
      "primary_asset": "국내주식",
      "rationale": "삼성전자·SK하이닉스 중심 KOSPI 상승 설명 문단",
      "evidence_span": "삼성전자, SK하이닉스, 반도체 업황, KOSPI 상승"
    }
  ]
}
```

enum:
- `region` ∈ REGION_SET = `{KR, US, NON_US_OVERSEAS, GLOBAL, UNKNOWN}` (`core/asset_taxonomy.py:REGION_TAXONOMY`)
- `sector` ∈ TOPIC_TAXONOMY (14) (`analyze/news_classifier.py:43`)
- `asset` ∈ **ALLOWED_ASSET_CLASSES (8)** (`claim_extractor.py:79`) — §1.A 결론
- `impact`/`direction` ∈ ALLOWED_DIRECTIONS = `{positive, negative, neutral, mixed, unknown}`
- `role` ∈ `{primary, secondary}`

### 4.2 claim schema 증분 (기존 R9-A schema 위 OPTIONAL 추가)

```json
{
  "claim_text": "Fed 인하 지연·달러 강세로 미국채 금리와 원달러 환율이 동시 상승 압력",
  "claim_type": "macro_to_asset",
  "affected_assets": [
    {"asset_class": "해외채권", "direction": "negative", "confidence": 0.88, "role": "primary"},
    {"asset_class": "환율(FX)", "direction": "positive", "confidence": 0.82, "role": "secondary"},
    {"asset_class": "해외주식", "direction": "negative", "confidence": 0.61, "role": "secondary"}
  ],
  "primary_asset": "해외채권",
  "regions": ["US", "GLOBAL"],
  "sectors": ["통화정책", "금리_채권", "달러_글로벌유동성"],
  "direction": "negative", "horizon": "short", "confidence": 0.85, "salience": 0.9,
  "supporting_evidence_ids": ["..."], "...": "기존 필드 유지"
}
```

- `affected_assets[].asset_class`는 **기존 키명 유지** (`asset` 아님 — claim 계약 호환). LLM output의 `asset`→claim의 `asset_class`로 매핑.
- `confidence`·`role` = affected_assets 항목 내 optional 추가.
- `primary_asset`·`regions`·`sectors` = claim-level OPTIONAL_FIELDS 추가.
- 권장 cap: affected_assets ≤3, regions ≤2, sectors ≤3.

### 4.3 validator schema (소프트/하드 구분)

| # | 항목 | 종류 | 위반 처리 |
|---|---|---|---|
| 1 | region ∈ REGION_SET | hard | invalid region → `UNKNOWN`으로 강등 + warning |
| 2 | sector ∈ TOPIC_TAXONOMY | hard | 제거 + warning (sectors에서 drop) |
| 3 | asset ∈ ALLOWED_ASSET_CLASSES(8) | hard | 항목 제거 + warning |
| 4 | affected_assets 개수 ≤3 | soft | 초과분 confidence desc로 trim |
| 5 | confidence floor (§6) | hard | floor 미달 asset 제거 |
| 6 | primary_asset ∈ affected_assets(asset_class) | hard | 위반 시 confidence 최고 asset으로 재지정 |
| 7 | role=primary 정확히 1개 | hard | 0개 → confidence 최고에 primary 부여 / 2개+ → 1개만 |
| 8 | direction/impact ∈ ALLOWED_DIRECTIONS | hard | invalid → `unknown` |
| 9 | region·sector·asset 명백 충돌 | soft | trace `consistency_warning` (예: region=KR인데 asset=해외주식 + sector=테크 → 충돌 후보) |
| 10 | evidence_span 존재 | soft | 없으면 warning (제거는 안 함) |

> consistency check(9)는 **차단 아님** — LLM이 맞을 수도 있음(다국적/글로벌). trace만 남기고 dry에서 수동 검수.

---

## 5. fallback priority

```python
def resolve_assets(item):
    llm_aa = validate_affected_assets(item.get("affected_assets"))   # §4.3
    llm_pri = item.get("primary_asset")
    if llm_aa and llm_pri in {a["asset"] for a in llm_aa}:
        final, src = llm_pri, "llm"
    else:
        rule = route_by_region(item.get("region"), item.get("sector") or item.get("topic"))
        rule = _remap_to_8class(rule)                                 # §1.A collapse
        if rule:
            final, src = rule, "rule"
        else:
            v1 = article_primary_asset(item)                          # 벡터+KR키워드
            final, src = (v1, "v1") if v1 else (None, "none")
    # conflict trace (차단 아님)
    rule_chk = _remap_to_8class(route_by_region(item.get("region"), item.get("sector")))
    warn = "rule_conflict" if (src == "llm" and rule_chk and rule_chk != final) else None
    return {"final_primary_asset": final, "route_source": src,
            "llm_primary_asset": llm_pri, "rule_primary_asset": rule_chk,
            "consistency_warning": warn}
```

`_remap_to_8class`: `환율→환율(FX)`, `금대체→원자재금`, `원자재에너지→원자재금`, `크립토→None`(8자산 밖), 그 외 동일.

---

## 6. confidence floor (초안, dry 후 조정)

```
asset confidence        >= 0.60   (floor 미달 → 해당 asset 제거)
primary_asset confidence>= 0.70
region confidence       >= 0.60   (미달 → region=UNKNOWN)
sector confidence       >= 0.60   (미달 → sectors에서 drop)
```

dry `low_confidence_rate` / `fallback_rate` 보고 캘리브레이션. floor가 너무 높으면 fallback_rate 폭증 → rule/v1 의존도↑.

---

## 7. rule-only / LLM-only / hybrid 비교 (dry plan §sample_plan.md)

| 방식 | primary 결정 | 강점 | 약점 |
|---|---|---|---|
| Rule-only | `route_by_region` only | 결정적·비용0·재현성 | 고정 매핑(지정학→원자재 등) 오류, multi-asset 불가 |
| LLM-only | LLM primary/affected 직접 | 문맥·multi-asset·복합매크로 | enum 이탈·환각·비용·재현성↓ |
| **Hybrid (권장)** | LLM valid 우선 → rule → v1 | 문맥+통제, 안전망 | 구현 복잡, conflict 해석 필요 |

> **설계 결론 (7.A):** Hybrid 권장. dry에서 세 방식 동일 sample로 KR_equity_recovery / cross_asset_accuracy /
> consistency_violation_rate 비교 후 확정.

---

## 8. cross-asset / GLOBAL 라우팅 보정 (워크오더 §4.2/§4.3)

현 `route_by_region` 고정 매핑의 보정 — **단 이번 step에서 route_by_region 코드는 수정하지 않음(설계만).** 향후 적용 후보:

- **GLOBAL + region-의존 sector(주식성/금리성) → None** (현재는 해외주식/해외채권 default). 해외로 새는 오분류 차단. GLOBAL은 region-free sector(환율/달러/에너지/금/크립토)에만 직접 route.
- **지정학 → 단일 원자재에너지 고정 폐기.** 지정학은 원유·금·환율·주식·채권 전반 → rule fallback에서 `None`(LLM affected_assets에 위임)이 안전.
- **관세_무역 → 주식성 고정 폐기.** 관세는 주식·물가·환율·금리·크레딧 다발 → rule fallback `None` + LLM multi-asset.

> dry에서 "지정학/관세 문단의 LLM multi-asset 정확도"를 측정해, rule fallback None화 안전성 확인 후 route_by_region 보정 PR(별 step).

---

## 9. downstream 영향 (consumer 배선 — 이번 step 금지, 후순위)

| consumer | 현재 | v2 적용 시 |
|---|---|---|
| `wiki/draft_pages.py` event 페이지 (Gate2) | `article_primary_asset`(v1) as `asset_of` + frontmatter `primary_asset` | v2 asset 사용 + frontmatter `affected_assets`/`regions` 추가 (옵션) |
| `report/wiki_context_pack_builder.py` Gate3 | `claim_primary_asset`(affected_assets[0]) round-robin | 명시 `primary_asset` 우선 + affected_assets로 multi-bucket quota |
| `report/wiki_context_pack_builder.py` Gate4 | frontmatter `primary_asset` 층화 | 동일 (primary_asset 명시화로 안정) |
| `wiki/claim_pages.py` | body `## Affected Assets` list, frontmatter에 asset 없음 | frontmatter `primary_asset`/`affected_assets`/`regions`/`sectors` 추가 |
| `report/debate_engine.py` | affected_assets 콤마 join (단일처럼 표시) | role/primary/secondary 구조로 prompt 표현 |

---

## 10. 리스크 / rollback

| risk | severity | mitigation |
|---|---|---|
| 자산 enum 3중 분기(§1) → claim invalid·selector 불일치 | **high** | source of truth = 8-class 고정, remap dict, dry `asset_enum_valid_rate` |
| LLM region/asset 환각 | high | hard enum validator + floor + fallback + dry 수동검수 |
| GLOBAL default 오분류(해외로 샘) | med | GLOBAL+region의존 → None 보정(§8), dry로 확인 |
| primary 강제 → 복합매크로 정보손실 | med | multi-asset 채택(§2), primary는 selector용 1개만 |
| 비용(재분류) | med | 30~50 sample dry 우선, 전체 backtest는 acceptance 후 |
| OPTIONAL→REQUIRED 승격 시 기존 claim fail | med | OPTIONAL 유지, md5 drift 0 회귀 |
| route_by_region 보정이 기존 article 선별 회귀 | med | route_by_region 코드 미수정(설계만), 보정은 별 step + 회귀 test |
| rollback | — | flag OFF → v1(`article_primary_asset` + research_v1 prompt). region/asset 필드 optional이라 데이터 호환 |

---

## 11. non-goals (이번 step 명시적 제외)

production consumer 배선 / `route_by_region` 제거·수정 / v1 제거 / 운영 산출물·claim store·report cache overwrite /
debate 재실행 / full paid backtest / flag ON / 뉴스 pipeline 개선 / PDF 문단 세그멘테이션.

---

## 12. 코드 변경 inventory

| module | 현재 역할 | 변경 필요 | 변경 내용 | 위험도 |
|---|---|---|---|---|
| `analyze/news_classifier.py` | research_v2 prompt(region)·flag(`MR_RESEARCH_REGION_V2`)·region passthrough (step1-3 완료) | sector 출력명 / asset·confidence 출력 확장 | research_v2 prompt에 `affected_assets[]`+`primary_asset`+`*_confidence` 요구, `_apply_classification_results` passthrough 확장 | med |
| research adapter `collect/naver_research_adapter.py` | `source_type='naver_research'`, `DOWNSTREAM_PRESERVE_FIELDS`로 `_classified_topics`/`_classifier_prompt` 보존 | preserve 목록에 v2 신규필드 추가 | `_affected_assets_v2`,`_primary_asset_v2`,`region` 등 보존필드 등록 | low |
| `core/asset_taxonomy.py` | `route_by_region`/`article_primary_asset_v2`(step1-3), `claim_primary_asset`, `ASSET_IMPACT_TO_CANONICAL` | `_remap_to_8class` 추가, route_by_region §8 보정(별 step) | 8-class remap 함수 + (후순위)GLOBAL/지정학/관세 None화 | med |
| `wiki/taxonomy.py` | `validate_regions`/`REGION_SET`(완료), `validate_tags`(sector) | sector list validator 재사용 확인 | 변경 거의 없음 (validate_tags로 sectors 검증) | low |
| claim 추출 `analyze/claim_extractor*.py` | affected_assets list(asset_class+direction), 8-class·multi-asset 이미 지원 | confidence/role/primary/regions/sectors 수용 | validator에 §4.3 7·8·9 추가, normalize에서 confidence/role default, prompt에 region/sector/primary 요구 | **high** |
| claim store schema `analyze/claim_extractor.py` REQUIRED/OPTIONAL | 18 required + 2 optional | OPTIONAL 추가 | `primary_asset`,`regions`,`sectors`를 OPTIONAL_FIELDS에 (REQUIRED 금지) | med |
| wiki claim page writer `wiki/claim_pages.py` | body affected_assets list, frontmatter asset 없음 | frontmatter 확장 | `primary_asset`/`affected_assets`/`regions`/`sectors` frontmatter (배선 step) | low |
| balanced selector adapter `core/balanced_selector.py`+wiring | `article_primary_asset`/`claim_primary_asset` as asset_of | asset_of를 v2/primary_asset로 전환(배선 step) | Gate2 `draft_pages.py:454`, Gate3 `wiki_context_pack_builder.py:201` 콜백 교체 | med |
| wiki context pack builder `report/wiki_context_pack_builder.py` | Gate3 claim round-robin(primary[0]), Gate4 event 층화(frontmatter) | 명시 primary_asset + multi-asset quota | `_reorder_claims_asset_roundrobin` primary_asset 우선, affected_assets multi-bucket | med |
| report/debate prompt `report/debate_engine.py` | affected_assets 콤마 join(`:1309-1337`) | role/primary 구조 표현 | claims_text에 primary/secondary·region 표시 | med |

---

## 13. 다음 단계 (별도 GO)

1. 30~50 sample dry classification (research_v2 prompt) — `debug/taxonomy/research_v2_sample_plan.md`
2. validator prototype + unit test — `debug/taxonomy/research_v2_validator_tests.md`
3. rule-only / LLM-only / hybrid 비교 (동일 sample)
4. 2026-05 research backtest (acceptance §classification_..._v2.md §7)
5. 통과 시 consumer wiring (Gate2/3/4 → v2)
6. claim/wiki/context pack 연결

관련: `classification_region_sector_taxonomy_v2.md`, `io_contract.md`, R9-A claim schema.
