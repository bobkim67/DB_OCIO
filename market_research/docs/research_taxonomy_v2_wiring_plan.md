# Taxonomy v2 Consumer Wiring 계획서 (검토용 — 배선 전)

> 상태: **PLAN ONLY**. 코드 변경 0. 사용자 GO 후에만 배선.
> 작성: 2026-06-02. 선행: `research_taxonomy_v2_llm_asset_mapping.md`(설계), handoff_research_taxonomy_v2.
> 범위: 4-step 배선 순서 / 각 step 영향·회귀·롤백 / flag 단계 / `_remap_to_8class` 적용 지점 / md5 drift 0 검증.

---

## 0. 현재 상태 — 코드 실측 (handoff 와 차이 3건)

| 항목 | handoff 기재 | 실측 (2026-06-02) |
|---|---|---|
| git | "전부 미커밋 working tree" | **merge `f9c55fe`로 커밋 완료** — v2 코드는 main 에 있음 |
| `_remap_to_8class` | 설계 §1.A/§5 에 명시 | **미존재** — 신규 작성 필요 |
| production v2 prompt | "region 출력 프롬프트" | `_build_research_classification_prompt_v2` 는 **region+topic+direction+intensity 만** 출력. `affected_assets[]`/`primary_asset` 는 **dry driver 에만** (`debug/taxonomy/research_v2_dry_classify.py`), production 프롬프트엔 없음 |

검증된 불변 사실 (배선 설계 기반):
- `core/asset_taxonomy.py`: `route_by_region`(L50), `article_primary_asset`(L107, v1), `article_primary_asset_v2`(L137), `claim_primary_asset`(L199) 존재.
- `route_by_region`·`article_primary_asset`(v1)·`article_primary_asset_v2` 는 **동일 label space** = selector canonical (`국내주식 해외주식 국내채권 해외채권 환율 원자재에너지 금대체 크레딧 크립토`).
- `core/balanced_selector.py` `CORE_ASSETS`(L30) = `국내주식 해외주식 국내채권 해외채권 환율 원자재에너지 금대체` (7, **selector label**).
- `analyze/claim_extractor.py`: `ALLOWED_ASSET_CLASSES`(L79) = 8-class(`…환율(FX) 원자재금`), `REQUIRED_FIELDS`(L113, 18개), `OPTIONAL_FIELDS`(L143) = `{canonical_group_id, promotion_rule}` **만**. `serialize_claim`(L654) = `{k: claim[k] for k in REQUIRED if k in claim}` + OPTIONAL `if k in claim`.
- flag `MR_RESEARCH_REGION_V2` default OFF (`news_classifier._research_region_v2_enabled` L427).

### 0.1 핵심 함의 — label space 가 두 갈래

```
article path (selector):  국내주식 … 환율 원자재에너지 금대체 크레딧 크립토   ← v1·v2 동일
claim path (8-class):     국내주식 … 환율(FX) 원자재금                        ← ALLOWED_ASSET_CLASSES
bridge:                   claim_primary_asset() = ASSET_IMPACT_TO_CANONICAL.get(name,name)
                          (환율(FX)→환율, 원자재금→금대체 로 selector label 로 되돌림)
```

→ **selector article path(①)는 v1↔v2 label space 가 같아 `_remap` 불필요.**
→ **`_remap_to_8class` 는 오직 claim 진입 경계(②)에서만** 필요 (selector label → 8-class).

---

## 1. 스코프 경계 — ★확정 (2026-06-02 사용자 결정)

- **Q1 → (B) paid 프롬프트 확장 포함**: `_build_research_classification_prompt_v2` 에 affected_assets/primary_asset/*_confidence 출력 추가 + `claim_extractor` LLM 프롬프트에 region/sector/primary 출력 요구 추가. → **유료 재분류/재추출 발생**.
- **Q2 → claim_pages frontmatter 이번 포함**: `wiki/claim_pages.py` `_render_page` frontmatter 에 primary_asset/affected_assets/regions/sectors 추가 (③에 통합). → **08_Claims/ 페이지 재생성 발생**.

> **결과: 이 사이클은 코드 배선(무비용·flag-gated)과 유료 재실행·산출물 overwrite 를 모두 포함.** handoff 금지목록("flag ON / claim store overwrite / debate 재실행")을 **명시적으로 해제**하는 결정이므로, 아래 §2 단계를 **2-phase 체크포인트**로 나눈다:
> - **Phase W (배선, 무비용)**: 전 코드 변경 + flag OFF 회귀(md5 0) + `_remap`/validator unit + 소규모 dry(≤$0.2). 여기까지 한 번에.
> - **Phase R (유료 재실행, 별 GO)**: flag ON → v2 재분류/claim 재추출 → claim store·08_Claims/·context pack overwrite. **Phase W PASS 확인 + 비용/덮어쓸 산출물 목록 제시 후 사용자 2차 GO.**

---

## 2. 배선 순서 (4-step) — 영향 / 회귀 / 롤백

각 step 은 **독립 커밋**. 앞 step 회귀 PASS 후 다음 진행.

### ① balanced_selector `asset_of` → v2 primary

| | 내용 |
|---|---|
| 영향 파일/함수 | `wiki/draft_pages.py:454` Gate2 `asset_of=lambda g: article_primary_asset(_grp_rep(g[1]))` → `article_primary_asset_v2`. import(L431) 에 `article_primary_asset_v2` 추가. (`report/wiki_context_pack_builder.py` Gate3 의 article 콜백도 동일 패턴 있으면 동반 — 확인 후) |
| `_remap` 적용 | **불필요** (§0.1 — v1·v2 동일 selector label, `CORE_ASSETS` 와 정합). `크립토` 만 CORE 밖 → fill 로 흡수(v1 의 `크레딧`/`현금성`과 동일 무해). |
| 안전성 | `article_primary_asset_v2` 는 region 필드 없으면(`saw_region=False`) 내부에서 v1 로 위임(L166-167) → flag OFF 데이터(region 없음)에선 **v1 과 출력 동일** = 무회귀. region 있는 데이터에서만 v2 라우팅. |
| 회귀 테스트 | (a) `tests/test_taxonomy_v2_region.py`(12) 그대로 PASS. (b) 신규 `test_draft_pages_asset_of_v2_fallback`: region 無 article 입력 시 v2==v1 동치 + balanced_select 선별 결과 동일. (c) 기존 wiki contract test (`test_taxonomy_contract`) PASS. (d) `daily_update --dry-run` 으로 base wiki event 선별 산출 비교(파일 md5) — flag OFF 면 0 diff 기대. |
| 롤백 | lambda 한 줄 + import 되돌림. |

### ② claim extractor — primary_asset/regions/sectors OPTIONAL 수용 + affected_assets confidence/role

| | 내용 |
|---|---|
| 영향 파일/함수 | `analyze/claim_extractor.py`: `OPTIONAL_FIELDS`(L143) 에 `"primary_asset","regions","sectors"` 추가. `validate_claim`(L459) 에 설계 §4.3 의 rule 6(primary∈affected)·7(role=primary 1개)·8(direction enum)·9(consistency soft) **soft/optional 로만** 추가 (값 없으면 skip). `normalize_claim`(L372) 에 affected_assets 항목 `confidence`/`role` default 부여 — **단 기존 항목엔 미부착**(없으면 그대로). |
| **REQUIRED 미승격 (사용자 요구 4)** | 신규 3필드 전부 **OPTIONAL_FIELDS 만**. `REQUIRED_FIELDS`(L113, 18개) 불변. → `validate_claim` L474 의 `for f in REQUIRED_FIELDS` 루프에 신규 필드 안 들어가므로 **기존 운영 claim 이 missing 으로 fail 안 함**. |
| `_remap_to_8class` 적용 지점 ★ | **여기.** `core/asset_taxonomy.py` 에 신규 함수: `환율→환율(FX)`, `금대체→원자재금`, `원자재에너지→원자재금`, `크립토→None`, 그 외 동일. claim 진입 시 affected_assets[].asset_class·primary_asset 이 selector label 로 들어오면 8-class 로 collapse → `ALLOWED_ASSET_CLASSES` 검증 통과. (값이 이미 8-class 면 idempotent.) |
| 회귀 테스트 | (a) **md5 drift 0 회귀(사용자 요구 4)**: 기존 운영 claim store(`data/claims/2026-0X.json` 및 `08_Claims/` 페이지) read→`serialize_claim`→md5 가 배선 전후 동일 (신규 필드 미존재 claim 은 serialize 에 안 실림, L660-663). 전수 비교 스크립트 `debug/taxonomy/wiring_md5_check.py`. (b) `_remap_to_8class` unit test (9 케이스: 4 collapse + 크립토→None + 8-class idempotent + None). (c) validate_claim 신규 rule unit test (primary∈affected, role 1개, 값 無 skip). (d) 기존 claim_extractor test 전수 PASS. |
| ②-b (Phase R, 유료) | claim_extractor LLM 프롬프트(`claim_extractor_prompt.py`)에 region/sector/primary 출력 요구 추가 + `_build_research_classification_prompt_v2` 에 affected_assets[]/primary_asset/*_confidence 출력 추가(dry driver 프롬프트와 정합). normalize 가 LLM output `asset`→claim `asset_class` 매핑 + `_remap_to_8class`. **유료 재추출 — Phase R.** |
| 롤백 | OPTIONAL_FIELDS 3필드 제거 + validator 신규 rule 제거 + `_remap_to_8class` 미사용 + 프롬프트 원복. 데이터 호환(필드 optional) — Phase W 저장본 영향 0. |

### ③ wiki_context_pack_builder — claim primary_asset + affected_assets multi-bucket

| | 내용 |
|---|---|
| 영향 파일/함수 | `report/wiki_context_pack_builder.py`: `_reorder_claims_asset_roundrobin`(L185-201) — 현재 `claim_primary_asset({"affected_assets": e["affected_assets"][0]})`. 변경: **명시 `e["claim"].get("primary_asset")` 우선** → 없으면 기존 affected_assets[0] fallback. multi-bucket quota 는 `affected_assets` 전체 순회(role=primary 우선). Gate4 `_fm(r).get("primary_asset")`(L228) — 이미 frontmatter 읽음; claim_pages 가 primary_asset frontmatter 를 써줄 때만 효과(없으면 기존대로 None). |
| `_remap` 적용 | primary_asset 은 claim 8-class(②에서 remap 완료) → bucketing 시 `claim_primary_asset`/`ASSET_IMPACT_TO_CANONICAL` 가 이미 selector label 로 환원(L206). 추가 remap 불필요. |
| 안전성 | primary_asset 미존재 claim → 기존 affected_assets[0] 경로 100% 보존 = 무회귀. |
| 회귀 테스트 | (a) primary_asset 없는 기존 claim 입력 시 reorder 결과 **순서 byte 동일**. (b) primary_asset 있는 합성 claim 으로 multi-bucket quota 동작 unit test. (c) `build_wiki_context_pack` monthly/quarterly 산출 pack md5 — 기존 운영 claim(primary 無)으론 0 diff. |
| claim_pages frontmatter (이번 포함) | `wiki/claim_pages.py` `_render_page`(L307) frontmatter 에 primary_asset/affected_assets/regions/sectors 추가 → Gate4(L228) 층화 안정화. **코드는 Phase W**(값 없으면 frontmatter 키 생략 → 기존 페이지 md5 0), **실제 페이지 재생성은 Phase R**(claim 재추출로 값 생긴 뒤 write). Phase W 단계에선 빈 값 키 미출력 보장 → 08_Claims/ 8건 md5 불변. |
| 롤백 | reorder primary_asset 분기 제거 + frontmatter writer 원복 → 기존 affected_assets[0] only. |

### ④ v1 fallback 유지 (전 step 관통 — 신규 코드 아님, 보증 항목)

| | 내용 |
|---|---|
| 보증 | ① `article_primary_asset_v2` 내부 v1 위임(L166) 유지. ② claim 신규필드 미존재 → 기존 affected_assets 경로. ③ primary_asset 미존재 → affected_assets[0]. **모든 step 이 "v2 값 있으면 사용, 없으면 v1/기존" 형태** → flag OFF + 기존 데이터에서 출력 불변. |
| 회귀 테스트 | flag OFF 전체 파이프 `daily_update --dry-run` + `build_wiki_context_pack` 산출물 md5 가 배선 전과 0 diff (= v1 경로 완전 보존 증명). |

---

## 3. flag 단계 (OFF → shadow → ON) + `_remap_to_8class` 적용 지점

```
[OFF]    (현재) MR_RESEARCH_REGION_V2 unset. v2 코드 존재하나 region 출력 0 → 전 consumer v1 경로.
         배선 ①②③④ 머지 후에도 OFF 면 산출물 md5 0 diff (회귀 게이트).
   │
[shadow] flag 별도 (예: MR_RESEARCH_WIRING_SHADOW): v2 라우팅 결과를 trace 로만 기록
         (route_source / llm vs rule conflict) — 실제 선별/claim 에는 v1 적용.
         dry sample 로 v2-vs-v1 분포 비교 후 ON 판단. **유료 0 (A 스코프)**.
   │
[ON]     MR_RESEARCH_REGION_V2=1 (+ B 스코프면 claim prompt v2). region 출력 → article_primary_asset_v2
         가 실제 라우팅. claim 에 primary_asset/regions/sectors 부착. ★유료 재분류 → 별도 GO + 산출물 overwrite 승인.
```

**`_remap_to_8class` 적용 지점 (단일)**: §2-② claim 진입 경계 (selector label → 8-class collapse). selector article path(①)·context pack bucketing(③)은 selector label space 라 미적용. 함수는 `core/asset_taxonomy.py` 에 두고 claim ingestion 에서만 호출.

---

## 4. md5 drift 0 확인 (사용자 요구 4 — 전용 게이트)

> **범위 주의 (B 스코프)**: "md5 drift 0" 은 **Phase W(코드 배선, flag OFF) 게이트**다 — 코드 변경이 기존 산출물을 *실수로* 바꾸지 않음을 증명. **Phase R(flag ON 재추출)은 신규필드를 의도적으로 부착하므로 claim store·08_Claims/ 가 바뀌는 게 정상** (사용자 2차 GO 시 덮어쓸 목록 명시 후 진행). 즉 drift 0 은 "merge 직후~재실행 전" 구간 불변식.

배선 ②(claim 스키마) 가 Phase W 의 유일한 drift 위험. 게이트:

1. **REQUIRED 불변**: `REQUIRED_FIELDS`(18개) diff 0 — 신규 3필드 OPTIONAL 만. (grep assert)
2. **serialize 보존**: `serialize_claim`(L660-664) 은 `if k in claim` 조건부 → 신규필드 없는 기존 claim 은 직렬화에 미포함 → byte 동일.
3. **전수 회귀 스크립트** `debug/taxonomy/wiring_md5_check.py`: 운영 claim store + `08_Claims/` 페이지 전건 read → serialize → md5 배선 전/후 set 비교. **기대 diff 0**. (handoff 의 "운영 4 md5 + 08_Claims 8 + ledger 1 row 불변" 회귀와 동일 원칙.)
4. canonical_group_id 계산(`compute_canonical_group_id` L288) 입력에 신규필드 미포함 확인 → group_id 불변.

---

## 5. 금지사항

**Phase W (배선) 동안 유지**: flag ON / claim store·wiki·report cache overwrite / debate 재실행 / 대규모 backtest. (소규모 dry ≤$0.2 는 허용 — prompt 검증용.)
**전 Phase 유지 (handoff §45 중 미해제분)**: v1 제거 금지 / `route_by_region` 코드 수정 금지(§8 GLOBAL·지정학·관세 보정은 별 step + 회귀 test).
**Phase R 에서 해제(사용자 결정)**: flag ON / claim 재추출 + claim store·08_Claims/·context pack overwrite. → 2차 GO 시 비용·덮어쓸 파일 목록 제시 후 실행.

---

## 6. 커밋 단위 (제안)

**Phase W (무비용 배선):**
1. `feat(taxonomy): _remap_to_8class + unit test` (asset_taxonomy)
2. `feat(wiki): Gate2 asset_of → article_primary_asset_v2 (v1 fallback)` (①)
3. `feat(claims): primary_asset/regions/sectors OPTIONAL + validator soft rules + prompt v2 출력` (②, ②-b prompt 변경은 코드만)
4. `feat(context-pack+claim_pages): claim primary_asset 우선 multi-bucket + frontmatter 키` (③)
5. `test(taxonomy): wiring md5 drift 0 회귀 + flag OFF dry-run 동치` (④ 게이트)

**Phase R (유료, 2차 GO 후):**
6. dry sample(≤$0.2) → 분포/enum 확인 → 사용자 확인 → flag ON 재추출 → overwrite (커밋은 산출물 별도)

---

## 7. GO 체크리스트

- [x] Q1 = (B) paid 포함, Q2 = claim_pages 포함 (2026-06-02 확정)
- [x] **Phase W 완료** (2026-06-02). §6 1~5 무비용 배선 + flag OFF inert 확인.
- [ ] Phase R 2차 GO (prompt 확장 + dry sample + flag ON 재추출 + overwrite). 별도.

### 7.1 Phase W 중 발견·정정 (★flag-gate)

배선 중 **flag OFF 인데도 v2 가 v1 과 다른** 사례 발견 (운영 뉴스 68,996건 중
22,950건=33.3%). 원인: `route_by_region` 의 cross-asset sector(지정학/에너지/금/
크레딧/환율)는 region 무관 라우팅 → region 없어도 발동. 최다는 `지정학→원자재에너지`
(9,837건; 설계 §8 "고정매핑 폐기" 대상). → 계획 §2-① 의 "v2==v1 무회귀" 전제 위반.

**정정(사용자 결정 A)**: Gate2/frontmatter 는 `article_primary_asset_v2` 직접
호출이 아니라 **flag-gate 디스패처** `article_primary_asset_auto` 경유.
`MR_RESEARCH_REGION_V2` OFF → v1 (route_by_region **미호출**), ON → v2.
→ flag OFF 에서 v1 과 100% 동일 (shadow inert 계약 복구). v2 article 라우팅의
실제 활성화는 route_by_region §8 보정(별 트랙) **이후** Phase R 에서.

### 7.2 Phase W 산출 (코드)

| # | 변경 | 파일 |
|---|---|---|
| C1 | `_remap_to_8class` + REMAP dict | `core/asset_taxonomy.py` |
| C2 | flag-gate 디스패처 `article_primary_asset_auto` + Gate2/frontmatter 배선 | `asset_taxonomy.py`, `wiki/draft_pages.py` |
| C3 | OPTIONAL `primary_asset/regions/sectors` + soft validator(role/conf/primary∈aa/region/sector) + normalize remap | `analyze/claim_extractor.py` |
| C4 | context-pack `primary_asset` 우선 multi-bucket + WikiPageRecord.primary_asset 파싱 + claim_pages frontmatter(조건부) | `report/wiki_context_pack_builder.py`, `wiki/claim_pages.py` |
| C5 | md5 drift 0 게이트 + flag OFF 동치 게이트 | `debug/taxonomy/wiring_md5_check.py` |

테스트: `test_taxonomy_v2_region.py`(+디스패처/remap), `test_claim_extractor_schema.py`(+v2 schema),
`test_claim_pages_v2_frontmatter.py`(신규), `test_wiki_context_pack_builder.py`(+reorder/parse).

### 7.3 Phase R 로 미룬 항목 (prompt 코드 포함)

§6 commit 3 의 "prompt v2 출력(②-b)"은 **flag ON 시에만 호출**되고 실제 필드를
생성(유료)하므로 Phase R 로 이동: ① `_build_research_classification_prompt_v2` 에
affected_assets/primary_asset/*_confidence 출력 추가 ② claim_extractor LLM 프롬프트
region/sector/primary 요구 ③ dry sample(≤$0.2) ④ flag ON 재추출·overwrite.
