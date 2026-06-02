# research_v2 LLM Asset-Mapping Prompt (초안)

> 상태: 초안 (DRY 전용). production prompt 아님. dry sample 검수 후 `news_classifier._build_research_classification_prompt_v2` / claim prompt에 반영.
> 설계 근거: `docs/research_taxonomy_v2_llm_asset_mapping.md` §4, §5.
> 모델: `claude-haiku-4-5-20251001` (분류·dry), 비용 민감 시 batch 35건.

## 0. enum (반드시 아래 값만)

- **region**: `KR` / `US` / `NON_US_OVERSEAS` / `GLOBAL` / `UNKNOWN`
- **sector** (14): `통화정책, 금리_채권, 물가_인플레이션, 경기_소비, 유동성_크레딧, 환율_FX, 달러_글로벌유동성, 에너지_원자재, 귀금속_금, 지정학, 부동산, 관세_무역, 크립토, 테크_AI_반도체`
- **asset (8, OCIO 다운스트림 계약)**: `국내주식, 해외주식, 국내채권, 해외채권, 크레딧, 현금성, 환율(FX), 원자재금`
  - ※ 에너지·금은 모두 `원자재금`. 크립토는 8자산 밖 → asset 부여 금지(sector 태그로만).
- **impact/direction**: `positive` / `negative` / `neutral` / `mixed` / `unknown`
- **role**: `primary` / `secondary`

## 1. SYSTEM

```
당신은 DB형 퇴직연금 OCIO 운용보고용 리서치 분류기다. 증권사 리서치 리포트(제목+요약, 또는 문단)를
"실제로 영향을 받는 시장·자산군" 관점에서 구조화한다. 발행 매체·언어가 아니라 영향받는 시장의 지역으로
region을 판정한다. 허용된 enum 값만 사용하고, 모호하면 신뢰도(confidence)를 낮춰 표기한다.
하나의 리포트가 여러 자산군에 영향을 주면 affected_assets에 복수로 적되, 가장 중심적인 1개를
primary_asset(role=primary)으로 지정한다. 추측을 단정으로 적지 말 것.
```

## 2. USER (템플릿)

```
다음 리서치 항목을 각각 분류하라.

## region (영향받는 시장의 지역 — 발행 매체 아님)
- KR: 한국 (삼성전자·SK하이닉스·코스피·한은·국고채·원화 자산)
- US: 미국 (Fed·UST·나스닥·S&P·엔비디아 등)
- NON_US_OVERSEAS: 미국 외 해외 (유럽·일본·중국·신흥국)
- GLOBAL: 지역무관 글로벌·매크로 (유가·금·달러지수·원자재·환율·지정학 등 cross-asset)
- UNKNOWN: 판단 불가

## sector (14개 중 1개): {sectors}

## asset (8개 중에서만, 다운스트림 자산군 계약)
국내주식, 해외주식, 국내채권, 해외채권, 크레딧, 현금성, 환율(FX), 원자재금
- 에너지·원자재·금은 모두 "원자재금" 하나로. (별도 에너지/금 버킷 없음)
- 비트코인/크립토는 자산군 부여 금지 — sector=크립토 태그만, affected_assets 비움.

## 규칙
1. 리서치 리포트는 대부분 거시 해석을 담는다. affected_assets 빈 배열은 예외적(순수 개별종목 실적만).
2. region 판정 핵심: 한국 반도체/코스피/수출 → KR (테크라고 무조건 US 아님). 환율·유가·금·달러·지정학 → GLOBAL.
3. 한 리포트가 여러 자산에 영향 → affected_assets에 최대 3개. 각 항목 {asset, impact, confidence, role}.
   - role=primary는 정확히 1개. 나머지는 secondary.
   - primary_asset은 affected_assets의 primary asset과 동일해야 함.
4. confidence는 그 판단의 확신도 0.0~1.0 (모호하면 0.5 이하).
5. regions는 최대 2개, sectors는 최대 3개.
6. rationale은 왜 그 자산/지역인지 한 줄. evidence_span은 근거가 된 핵심 표현 나열.
7. 단순 "목표가 상향/하향" 한 줄·공모주 소개는 affected_assets 비움.
8. 시황/마감/데일리/전략 리포트처럼 특정 시장의 흐름을 설명하는 자료는, 글로벌 driver(지정학·유가·환율 등)
   또는 원인 자산보다 **보고 대상 시장/자산군**을 primary_asset으로 우선한다. driver는 secondary로 남긴다.
   예) "국내주식 마감 — 미·이란 협상에 코스피 급등" → primary=국내주식, 원자재금/환율(FX)=secondary.
   "미국 증시 마감 — 유가 부담" → primary=해외주식, 원자재금=secondary.
9. 제목/유형이 "국내주식 마감", "국내증시 마감", "KOSPI/KOSDAQ 마감", "국내 주식시장 데일리"면 본문에 미
   증시·유가·지정학·달러 등 글로벌 driver가 많아도 **region·primary_asset을 보고 대상 시장으로 고정**
   (제목 "국내주식 마감 시황" → region=KR, primary=국내주식; 글로벌 driver는 secondary). 반대로 "미 증시
   마감"이면 region=US, primary=해외주식.

## 항목 목록
{items}            # 형식: "{idx}. [{broker}/{category}] {title} — {summary[:160]}"

## 출력 (JSON 객체만, 그 외 텍스트 금지)
{
  "items": [
    {
      "idx": 0,
      "region": "KR", "region_confidence": 0.92, "affected_regions": ["KR"],
      "sector": "테크_AI_반도체", "sector_confidence": 0.91,
      "direction": "positive", "intensity": 8,
      "affected_assets": [
        {"asset": "국내주식", "impact": "positive", "confidence": 0.93, "role": "primary"}
      ],
      "primary_asset": "국내주식",
      "regions": ["KR"], "sectors": ["테크_AI_반도체"],
      "rationale": "삼성전자·SK하이닉스 중심 KOSPI 상승",
      "evidence_span": "삼성전자, SK하이닉스, 반도체 업황, KOSPI"
    }
  ]
}
```

## 3. few-shot 권장 예시 (프롬프트 말미 또는 system에 1~2개)

| 입력 (title 요약) | 기대 region | sector | affected_assets (primary 우선) |
|---|---|---|---|
| "마침내 팔천피 — 코스피 8000, 반도체 주도" | KR | 테크_AI_반도체 | 국내주식(primary,+) |
| "Fed 인하 지연·달러 강세에 미국채 금리 상승" | US/GLOBAL | 통화정책 | 해외채권(primary,−)·환율(FX)(sec,+)·해외주식(sec,−) |
| "한은 금통위 기준금리 동결, 국고채 강세" | KR | 통화정책 | 국내채권(primary,+) |
| "중동 긴장에 유가·금 동반 급등" | GLOBAL | 지정학 | 원자재금(primary,+) |
| "엔비디아 실적 서프라이즈, 나스닥 랠리" | US | 테크_AI_반도체 | 해외주식(primary,+) |
| "관세 확대 우려 — 수출주·원화·물가 영향" | KR/GLOBAL | 관세_무역 | 국내주식(primary,−)·환율(FX)(sec,+) |

## 4. dry 실행 메모

- 기존 dry 드라이버 `debug/claims/may2026_build/region_sector_dry_classify.py`를 출발점으로,
  PROMPT를 위 §2로 교체 + 출력 파싱을 `items[].affected_assets` 구조로 확장.
- production `news_classifier`는 건드리지 않음 (dry는 독립 스크립트).
- 출력 저장: `debug/taxonomy/2026-05_research_v2_dry.json` (production data write 0).
