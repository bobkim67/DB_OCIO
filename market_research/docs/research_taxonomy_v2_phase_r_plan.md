# Taxonomy v2 Phase R — 작업지시서/설계서 (구현 전, 검토용)

> 상태: **DESIGN ONLY**. 코드 변경 0 / prompt 확장 0 / paid 0 / flag ON 0.
> 작성: 2026-06-02. 선행: `research_taxonomy_v2_wiring_plan.md`(Phase W 완료, main `7286d90`),
> `research_taxonomy_v2_llm_asset_mapping.md`(설계 §4·§5·§8), `handoff_research_taxonomy_v2`.
> 각 WS(workstream)는 **개별 GO 게이트**. 유료/flag ON/overwrite 는 명시 승인 시에만.

---

## 0. 한 줄 요지 + Phase W 와의 경계

Phase W = **shadow 배선**(flag OFF 에서 v1 완전 동일, 스키마는 v2 필드 *수용*만).
Phase R = **v2 필드 실제 생성 + 라우팅 보정 + 측정**. 즉:
1. LLM 이 region·sector·affected_assets·primary 를 **실제 출력**하도록 prompt 확장 (유료).
2. rule fallback(`route_by_region`)의 **known-bad 고정매핑 보정**(§8) — flag ON 전에.
3. flag ON **shadow 측정**(운영 overwrite 없이) → v1 vs v2 drift report.
4. 소액 dry → 통과 시 full backtest/적용 여부 결정.

> **불변 원칙**: WS3(§8 보정)가 WS4(flag ON 측정)보다 **먼저**. 지정학→원자재에너지 등
> 설계가 폐기 대상으로 지목한 매핑이 살아있는 채로 v2 라우팅을 켜면 측정값이 오염된다.

---

## 1. 작업 분해 (4 WS) + 의존 순서

```
WS3  route_by_region §8 보정 (지정학·관세 None화 + GLOBAL 재검토) + 회귀   ← 먼저
WS1  research_v2 분류 prompt 확장 + hybrid resolver (article-level)
WS2  claim_extractor LLM prompt 확장 (claim-level region/sector/primary/conf/role)
WS4  flag ON shadow 측정 (no-overwrite harness) → drift report → 적용 여부 결정

의존(=GO 순서):
  WS3(§8 보정) ──→ WS1(prompt/resolver) + WS2(claim prompt) ──→ dry(≤$0.2)
            ──→ full shadow 측정 ──→ [GO] 운영 적용
```

**WS3 가 가장 먼저.** WS1 의 hybrid resolver fallback 이 `route_by_region` 을 쓰고,
WS4 측정이 그 결과를 본다 → known-bad 고정매핑(지정학→원자재에너지 9,837건 등)을
먼저 None 화하지 않으면 resolver·측정값이 모두 오염된다. WS3·WS1·WS2 는 **코드/prompt
변경**(flag OFF 면 무발동 — WS1·WS2 는 prompt 분기, WS3 은 article_primary_asset_v2
ON 시에만 영향). WS4 만 paid + flag ON.

---

## 2. WS1 — research_v2 분류 prompt 확장 + hybrid resolver

### 2.1 현재 상태 (Phase W 기준)
- `news_classifier._build_research_classification_prompt_v2`(L436): **region+topic+
  direction+intensity 만** 출력. affected_assets/primary 없음.
- `_apply_classification_results`(L575): region passthrough 만(L592-595). asset 은
  `TOPIC_ASSET_SENSITIVITY` 벡터로 *간접* 산출.
- `article_primary_asset_v2`(asset_taxonomy): **rule(route_by_region) 라우팅만**.
  LLM 직접 affected_assets/primary 소비 경로 **미구현** (설계 §5 priority 1 미적용).

### 2.2 변경 (검증된 dry prompt 반영)
| 대상 | 변경 |
|---|---|
| `_build_research_classification_prompt_v2` | dry `debug/taxonomy/research_v2_llm_asset_prompt.md`(rule 1-9, region pinning 포함)의 schema 로 교체: 각 item 에 `affected_assets[]={asset(8-class), impact, confidence, role}`, `primary_asset`, `regions`(≤2), `sectors`(≤3), `rationale`, `evidence_span` 추가. SYSTEM/USER 템플릿 동일. |
| `_apply_classification_results` | LLM 출력의 `affected_assets`/`primary_asset` 를 article 에 **passthrough 필드**로 보존: `_affected_assets_v2`, `_primary_asset_v2`, `_regions_v2`, `_sectors_v2`. validator(아래) 통과분만. 기존 region passthrough 유지. |
| validator (신규, dry `research_v2_dry_classify.py` validator 이식) | enum(asset 8/region/sector) hard, confidence floor(asset≥0.60·primary≥0.70·region≥0.60), primary∈affected, role=primary 1개, affected≤3·regions≤2·sectors≤3. 위반 처리 = 설계 §4.3 표. `asset` → `_remap_to_8class` collapse. |
| `article_primary_asset_v2` (hybrid 화, 설계 §5 `resolve_assets`) | priority: ① LLM `_primary_asset_v2` valid → 사용 ② rule `route_by_region`+`_remap_to_8class` ③ v1 `article_primary_asset` ④ None. conflict(LLM≠rule) 시 `_route_source`/`_consistency_warning` trace(차단 X). **단 출력 label space: article path 는 selector label 유지** — LLM 8-class 출력은 selector-bucket 비교 시 `claim_primary_asset` 역매핑 재사용. |

### 2.3 flag/회귀/롤백
- 전부 `MR_RESEARCH_REGION_V2` ON 경로에서만 발동(prompt 분기 `news_classifier:664`).
  OFF → research_v1 prompt, v1 resolver → Phase W inert 유지.
- 회귀: (a) `test_taxonomy_v2_region.py` 확장 — hybrid resolver priority(LLM>rule>v1)
  단위테스트(monkeypatch flag ON, 합성 article). (b) flag OFF 동치 게이트
  (`wiring_md5_check.py` 그대로 PASS). (c) passthrough 필드는 `_`-prefix 라 claim/
  selector 계약 무영향.
- 롤백: prompt/resolver 원복 → v1. passthrough 필드 optional 이라 데이터 호환.

---

## 3. WS2 — claim_extractor LLM prompt 확장 (claim-level)

### 3.1 현재 상태
- `claim_extractor_prompt.py`: output schema `affected_assets=[{asset_class,direction}]`
  (L119), rule 5 가 이미 multi-asset 3개+ 지시(L111). region/sector/primary/conf/role
  **없음**.
- claim 스키마(Phase W): `primary_asset`/`regions`/`sectors` OPTIONAL **수용 가능**,
  normalize 가 `_remap_to_8class` 적용, validator soft rule 준비됨. → **생성만 남음**.

### 3.2 변경
| 대상 | 변경 |
|---|---|
| `claim_extractor_prompt.py` output schema | `affected_assets[]` 에 `confidence`·`role` 추가. claim-level `primary_asset`·`regions`(≤2)·`sectors`(≤3) 추가. rule 에 "primary_asset=affected 의 role=primary 와 동일", "regions/sectors enum" 명시. asset enum = 8-class(기존 `asset_list` 그대로). |
| 추출 파이프라인 normalize | **Phase W 에서 이미 완료** (normalize_claim remap + OPTIONAL serialize). 추가 코드 거의 없음 — prompt 가 채우면 자동 보존. |
| `wiki/claim_pages.py` frontmatter | **Phase W 완료** (조건부 emit). 값 생기면 자동 출력. |
| `report/wiki_context_pack_builder.py` | **Phase W 완료** (primary_asset 우선 reorder + 파싱). |
| `report/debate_engine.py` (선택) | affected_assets 콤마 join(L~1309)을 role=primary/secondary·region 표시로 보강(설계 §9). **별 sub-step, 저우선** (debate prompt 변경 → 재실행 유발하므로 measure 후). |

### 3.3 flag/회귀/롤백
- claim 추출 자체가 paid LLM step(별 트리거). prompt 변경은 코드만, 실행은 WS4/운영.
- 회귀: 합성 LLM 출력(conf/role/primary 포함)으로 normalize→validate→serialize→
  claim_pages frontmatter round-trip 단위테스트(Phase W 테스트 확장).
- 롤백: prompt schema 원복. 스키마는 optional 이라 기존 claim 무영향.

### 3.4 R-2 실행 결과 (2026-06-02, ✅ DONE — 코드만, 무비용)
WS1+WS2 prompt/resolver/validator 배선. 전부 flag OFF inert (prompt 는 flag ON 에서만
호출, resolver priority 1 은 `_primary_asset_v2` 부착 시에만 = flag ON).

- **WS1** `news_classifier`: `_build_research_classification_prompt_v2` 에 affected_assets
  [{asset,impact,confidence,role}]/primary_asset/regions 출력 + rule 7-9(multi-asset/
  role=1/시황 pinning) 추가(topics[] 유지 = downstream `_classified_topics` 무영향).
  `_validate_v2_asset_layer`(remap→8class/floor0.6/dedupe/cap3/primary∈affected/role=1)
  + `_apply_classification_results` passthrough(`_affected_assets_v2`/`_primary_asset_v2`/
  `_regions_v2`/`_sectors_v2`). `article_primary_asset_v2` hybrid: LLM primary(8class→
  selector) > rule(route_by_region §8) > v1.
- **WS2** `claim_extractor_prompt`: affected_assets 에 confidence/role + primary_asset/
  regions/sectors 출력 + region/sector enum 제약. (스키마 수용·normalize remap·
  frontmatter 는 Phase W 완료 → prompt 만.)
- 검증: 통합 passthrough(국내주식 마감 합성) → `_primary_asset_v2`=국내주식, 환율→환율(FX)
  remap, resolver=국내주식. flag OFF auto==v1 mismatch 0·claim md5 0·shadow 19,286 불변.
  단위 28 + 회귀 262 통과.
- 다음 = **R-3 dry 100건**(flag ON harness, ≤$0.2, **paid 첫 단계 — 별 GO**).

---

## 4. WS3 — route_by_region §8 보정 (flag ON 전 필수)

### 4.1 현재 known-bad (Phase W 측정, 운영뉴스 v2!=v1 22,950건 중)
| 매핑 | 건수(top) | 문제 | 설계 §8 |
|---|---|---|---|
| 지정학 → 원자재에너지 | 9,837 | 지정학은 원유·금·환율·주식·채권 전반 → 단일 고정 오류 | 고정 폐기, rule fallback `None`(LLM affected 위임) |
| 관세_무역 → 주식(EQUITY) | — | 관세는 주식·물가·환율·금리·크레딧 다발 | 고정 폐기, `None` |
| GLOBAL + 주식성/금리성 → 해외주식/해외채권 default | 다수 | 해외로 새는 오분류 | GLOBAL 은 region-free sector(환율/달러/에너지/금/크립토)에만 직접 route; region-의존 sector 는 `None` |

### 4.2 변경 (route_by_region 함수)
- 지정학: `return "원자재에너지"`(L70) → **`return None`** (LLM affected_assets 위임).
- 관세_무역: EQUITY 분기(L73)에서 **제외** → 단독 `None`.
- GLOBAL + EQUITY/RATE sector: `해외주식`/`해외채권` default(L76·L83) → **`None`**
  (GLOBAL 은 cross-asset sector 직접 매핑만 유지).
- ※ 이 변경은 `article_primary_asset_v2` 의 rule fallback 결과를 바꾼다 → **flag ON
  일 때만** 영향(OFF 는 v1). 단 `_remap_to_8class`/dispatcher 무관.

### 4.3 회귀/롤백
- 회귀: `test_taxonomy_v2_region.py` 의 cross-asset 테스트 **수정 필요**
  (`test_cross_asset_sectors_region_invariant` 의 지정학==원자재에너지 기대 →
  None 으로). + GLOBAL None 케이스 추가. + hybrid resolver 에서 rule None →
  v1 fallback 동작 확인.
- **shadow 재측정**: 보정 후 `wiring_md5_check.py` [B] 재실행 → 지정학→원자재에너지
  9,837건이 v2 에서 사라지고 LLM affected(WS1) 또는 v1 로 분산되는지 확인.
- 롤백: route_by_region 3개 분기 원복. 단위테스트 동반 원복.

### 4.4 R-1 실행 결과 (2026-06-02, ✅ DONE)
route_by_region §8 보정 적용 (지정학·관세→None, GLOBAL+주식/금리→None). 검증:
- **지정학→원자재에너지 = 0건** (운영뉴스 전수; 적용 전 9,837건). 관세→주식·GLOBAL
  default 도 None.
- v2 shadow mismatch **22,950 → 19,286**(−3,664). 남은 원자재에너지 route 는 **100%
  에너지_원자재 sector(6,900건) 직접매핑** = 정상 cross-asset (지정학 0 확인).
- flag OFF auto==v1 mismatch **0 유지**(dispatcher inert 불변), claim md5 drift **0**.
- 테스트: `test_taxonomy_v2_region.py` §8 케이스 추가/수정(지정학·관세 None, GLOBAL
  region-의존 None, 지정학 단독→v1 위임) 전건 통과. 무비용·flag OFF inert.

---

## 5. WS4 — flag ON shadow 측정 (no-overwrite harness)

### 5.1 원칙
- **운영 산출물 0 overwrite**: 측정은 별도 출력 경로(`debug/taxonomy/phase_r_shadow/`)
  에만 기록. claim store / wiki / report cache / regime / debate 미실행·미덮어쓰기.
- flag ON 은 **측정 harness 프로세스 환경변수로만**(`MR_RESEARCH_REGION_V2=1`),
  운영 배치/스케줄러엔 미설정.

### 5.2 측정 항목 (drift report 스키마)
| metric | 정의 | 비교 |
|---|---|---|
| asset distribution | v1 vs v2 자산군 분포(%) | 국내주식·해외채권 등 |
| KR-equity recovery | reference set(코스피/삼성/반도체/마감) 국내주식 정분류율 | dry 82.9% 회귀 |
| enum valid | asset/region/sector enum 통과율 | dry 100% |
| fallback rate | LLM invalid → rule/v1 비율 | dry 6.1% |
| consistency violation | LLM≠rule trace 비율 | dry 20.7% (rule 고정매핑 교정분 포함) |
| selected events drift | base wiki Gate2 선택 event set v1 vs v2 (no-write dry) | Δ event ids |
| context pack drift | claim reorder/primary_asset 적용 시 pack 순서·멤버십 | 멤버십 불변 확인 |
| §8 효과 | 지정학→원자재에너지 잔존 건수 (WS3 전/후) | →0 기대 |

### 5.3 harness
- 신규 `debug/taxonomy/phase_r_shadow_measure.py`: 운영 뉴스(read-only) → flag ON
  분류(소액 dry 우선) → WS1 resolver → 위 metric 집계 → `phase_r_shadow/report.{md,json}`.
- **dry sample = 100건**(≤$0.2). 44건은 sample dry 에서 이미 봤고 약점도 드러남 →
  이번엔 §8 보정 + prompt 확장 + hybrid resolver 가 들어간 상태의 안정성 확인이 목적
  이라 100건. → enum/분포 sanity 통과 시 full(2026-05 1,142건 규모, dry backtest 와
  동일 driver 재사용) 여부 **별도 GO**.
- **spot-check 30건 수동라벨**: Claude 가 `expected_asset`/`expected_region`/
  `expected_reason` **1차 초안** 생성 → 사용자가 **애매·중요 건만 검수**. 완전 자동
  proxy 단독으로 acceptance 판단 금지(이전 keyword proxy noise 재발 방지).

### 5.3.1 R-3 실행 결과 (2026-06-02, ✅ DONE — dry 100건, ~$0.1, out 16,022 tok)
harness `debug/taxonomy/phase_r_shadow_measure.py` (production 경로, flag ON 프로세스
국소, no-overwrite). 2026-05 research 1,142건 → strided 100건.

- **route_source**: llm **97%** / rule 0 / v1 0 / none 3% → LLM affected/primary 가
  사실상 단독 결정(hybrid priority 1). rule fallback 거의 불필요(§8 None화와 정합).
- **asset 분포 v1→v2**: 국내주식 26→**61**, 해외채권 23→**3**(v1 과다귀속 교정),
  해외주식 24→19, 금대체 0→7(에너지·금 8class 병합 후 selector 환원). 
- **KR-equity recovery**: keyword ref 51건 국내주식 정분류 v1 47.1% → **v2 74.5%**.
  (단 keyword ref 는 코스피/삼성/반도체/마감만 잡아 KR 섹터리포트 누락 → 실제 더 높음:
  spotcheck 참조.)
- **§8 효과**: 지정학 topic 32건 중 v2 가 원자재로 간 건 **5건**(적용 전이면 32/32 강제).
  나머지 27건은 보고대상/LLM affected 우선 → 국내주식·해외주식 등으로 분산.
- **multi-asset 42%**, **unknown 3%**(acceptance <30% 충족), enum 위반 0(resolver 보장).
- **spotcheck 30건** (Claude 초안 라벨 + verdict): **agree 26 / ambiguous 3 / disagree 1**.
  disagree 1 = "Daily Bond Morning Brief" 가 topic 테크/지정학으로 **오태깅**되어 v2 가
  해외주식(채권이어야) → routing 아닌 **classification(topic) 단계 오류**. KR 섹터리포트
  (방산/조선/2차전지/철강/음식료/바이오)는 v1 해외주식/채권 오분류를 v2 가 국내주식으로
  대거 교정 — keyword ref 가 못 잡는 진짜 recovery 확인.

### 5.4 게이트 (운영 적용 전)
acceptance(설계 §classification_v2 §7, dry backtest 기준):
- asset enum ≥95% (dry 100%), KR-equity ≥90%(dry 82.9% → spotcheck 수동라벨로 실측 확정),
  fallback <30%(dry 6.1%), 국내주식 비중 정상화 유지, **§8 보정 후 지정학 오라우팅 ≈0**.
- 통과 + 사용자 GO → 운영 flag ON / claim 재추출 / wiki·pack overwrite(별 단계, 목록 제시).

---

## 6. 순서 / GO 게이트 요약

| 단계 | 내용 | 비용 | GO |
|---|---|---|---|
| R-1 | WS3 route_by_region §8 보정 + 회귀 (코드만) | 0 | 1 GO |
| R-2 | WS1 prompt+resolver + WS2 claim prompt (코드만, flag OFF inert) | 0 | 1 GO |
| R-3 | dry sample 측정 (flag ON, harness, ≤$0.2) | ~$0.2 | R-2 PASS + GO |
| R-4 | full shadow 측정 + drift report | backtest 규모 | R-3 PASS + GO |
| R-5 | 운영 적용 (flag ON + 재추출 + overwrite) | paid | R-4 acceptance + 목록제시 + GO |

> R-1(§8) 먼저 → R-2 → 측정. R-1/R-2 는 무비용·flag OFF inert 라 Phase W 처럼
> 안전 커밋 가능. paid 는 R-3 부터.

---

## 7. 리스크 / 롤백

| risk | sev | mitigation |
|---|---|---|
| §8 None화로 rule fallback 급감 → unknown_rate 폭증 | med | LLM affected(WS1) 우선이라 None 이어도 LLM 이 채움. dry 에서 unknown_rate 측정 후 floor 조정 |
| LLM region/asset 환각 | high | hard enum validator + confidence floor + v1 fallback + dry 수동검수(spotcheck 30건 라벨) |
| prompt 확장 비용 | med | dry 우선(≤$0.2), BATCH=20(dry 검증), full 은 별 GO |
| 측정이 운영 오염 | high | no-overwrite harness, 별도 출력 경로, flag 프로세스-국소 |
| consistency 20.7% 해석 오류 | med | conflict 는 trace only(차단 X), 수동 라벨로 "개선 vs 오분류" 분리 |
| debate prompt 변경(WS2 선택분) 재실행 유발 | med | measure 후 별 sub-step, 이번 제외 |
| 롤백 | — | 전 WS flag OFF / prompt 원복 / route_by_region 원복. 데이터 optional 호환 |

---

## 8. non-goals (Phase R 에서도 제외)

PDF 문단 세그멘테이션 / 뉴스 pipeline 개선 / regime·debate writer 변경 / 세 번째 asset
enum 도입 / v1 제거 / 운영 스케줄러 flag 상시 ON / dry 전 full paid backtest.

---

## 9. 산출물 (예정)

- 코드: `news_classifier`(WS1), `claim_extractor_prompt`(WS2), `core/asset_taxonomy`(WS3)
- 테스트: `test_taxonomy_v2_region.py`(resolver/§8), claim schema(WS2), 신규 resolver 테스트
- harness/리포트: `debug/taxonomy/phase_r_shadow_measure.py`, `phase_r_shadow/report.{md,json}`
- 갱신: 본 문서 단계별 결과 + handoff_research_taxonomy_v2

## 10. 결정 사항 (2026-06-02 확정)

- **Q1 → 동의.** R-1 = WS3 `route_by_region` §8 보정부터. 이유: 지정학→원자재에너지 /
  관세→주식성 / GLOBAL+주식·금리→해외자산 known-bad 매핑이 남은 채 flag ON shadow
  측정하면 결과 오염. §1·§6 순서 WS3-first 로 통일.
- **Q2 → 동의.** WS2 의 debate_engine prompt 보강(role/region 표시)은 measure 후 별
  sub-step. 순서: taxonomy/routing 측정 → context pack 변화 확인 → debate prompt 표시
  개선. (동시 변경 시 원인 분리 불가.)
- **Q3 → dry sample 100건.** §8 보정 + prompt 확장 + hybrid resolver 적용 상태의 안정성
  확인 목적. spot-check 30건 = Claude 초안 라벨 + 사용자 애매건 검수(자동 proxy 단독
  acceptance 금지).

> 미해제 게이트: Phase R 구현 / paid dry / flag ON / 운영 overwrite 는 R-1 GO 부터
> 단계별 별도 승인 필요(§6). 본 문서는 기준점 — 커밋만 완료.
