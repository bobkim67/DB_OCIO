"""Brinson 3-Factor Attribution DTO.

`modules.data_loader.compute_brinson_attribution_v2` 반환을 Pydantic 으로 정규화.

단위 규약:
  - 비중 (AP비중/BM비중): % (예: 25.3 → 25.3%) — Streamlit 화면 그대로.
  - 수익률·기여도·factor effect: % (예: 1.23 → 1.23%) — Streamlit `pa_df` 컬럼 단위.
  - daily_brinson 누적: % (이미 ×100 적용됨, raw cum*100).
  - sec_contrib 의 수익률(%)/기여수익률(%): %.

Streamlit `tabs/brinson.py` 와 단위 일관 (raw ratio 가 아님). 클라이언트에서 추가 변환 불필요.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from .meta import BaseMeta


class BrinsonAssetRowDTO(BaseModel):
    """compute_brinson_attribution_v2['pa_df'] 한 행."""
    asset_class: str           # 자산군 (예: "국내주식")
    ap_weight: float           # AP비중 (%)
    bm_weight: float           # BM비중 (%) — BM 없으면 SAA 목표비중
    ap_return: float           # AP수익률 (%)
    bm_return: float           # BM수익률 (%)
    bm_contrib: float          # BM 기여수익률 (%) — 경로의존, 합 = period_bm_return
    alloc_effect: float        # Allocation Effect (%)
    select_effect: float       # Selection Effect (%)
    cross_effect: float        # Cross Effect (%)
    contrib_return: float      # 기여수익률 (AP 기여, %)


class BrinsonBmComponentDTO(BaseModel):
    """BM(또는 SAA) 구성 한 행 — item4 'BM 셋팅 vs AP' 비교 표용."""
    name: str                  # 인덱스명(BM) 또는 자산군명(SAA)
    weight: float              # 목표비중 (%)
    asset_class: str           # 매핑 자산군 (AP 자산군 비중과 대조용)
    region: str = ""           # KR / ex_KR (BM 컴포넌트만)
    hedged: bool = False       # 환헤지 여부 (BM 컴포넌트만)
    # 지수별 기간 기여/수익률 (%) — 표1 펼침용, 경로의존(합≈BM 기간수익률). 구캐시=None.
    contrib: float | None = None
    ret: float | None = None


class BrinsonBmEquitySplitRowDTO(BaseModel):
    """BM 해외주식(ACWI) 4분할 한 행."""
    name: str                  # 지수명 (MSCI USA Growth 등)
    weight: float              # 펀드 BM 기준 비중 (%)
    bucket: str = ""           # growth | value | dm_int | em — AP 종목과 짝짓는 안정 키


class BrinsonBmEquitySplitDTO(BaseModel):
    """BM 해외주식(MSCI ACWI) 레그의 스타일·지역 4분할 — 표0 종목펼치기 **표시 전용**.

    ★ Brinson 수식/BM 총수익률/초과성과에는 일절 관여하지 않는다. 비중만 보여준다.
      (4개 지수를 실제 BM 컴포넌트로 쪼개면 합성 수익률이 ACWI 단일 지수와 달라져
       BM 총수익률이 +0.43%p 움직인다 — 실측 08K88 YTD 18.10% → 18.53%.)
    시총 항등식이 정확히 성립하므로(load_acwi_equity_split 주석) 4행 합 = total_weight.
    """
    asset_class: str = "해외주식"
    rows: list[BrinsonBmEquitySplitRowDTO]
    total_weight: float        # ACWI 레그 합계 비중 (%)
    as_of: str                 # 시총 기준일 (YYYY-MM-DD)
    hedge_note: str = ""       # 레그 2개 이상일 때 "환노출 22.5% + 환헤지 22.5%"


class BrinsonSecContribDTO(BaseModel):
    """compute_brinson_attribution_v2['sec_contrib'] 한 행 (전체 종목)."""
    asset_class: str           # 자산군
    bucket: str = ""           # ACWI 4분할 버킷키 — 기말 미보유 종목도 행 맞춤에 쓰인다
    item_nm: str               # 종목명
    weight_pct: float          # 비중(%)
    return_pct: float          # 수익률(%)
    contrib_pct: float         # 기여수익률(%)


class BrinsonApCompItemDTO(BaseModel):
    """표0 AP 구성 — 기말 보유 스냅샷(현금 포함) 종목."""
    item_nm: str
    weight_pct: float          # 순자산대비 비중(%)
    bucket: str = ""           # ACWI 4분할 버킷키 — BM 세부지수와 행 맞추기용(해외주식만)


class BrinsonApCompositionDTO(BaseModel):
    """표0 AP비중 = 기말 보유 스냅샷(현금·미수금 포함, FX 제외). period PA 비중과 별개."""
    asset_class: str           # 표0 자산군 (국내주식/.../유동성및기타)
    weight_pct: float          # 자산군 비중 합(%)
    items: list[BrinsonApCompItemDTO]


class BrinsonDailyPointDTO(BaseModel):
    """compute_brinson_attribution_v2['daily_brinson'] 한 행."""
    date: date                 # 기준일자
    alloc_cum: float           # 누적 Allocation (%)
    select_cum: float          # 누적 Selection (%)
    cross_cum: float           # 누적 Cross (%)
    excess_cum: float          # 누적 초과수익 (%)
    ap_cum: float = 0.0        # 누적 AP 수익률 (%) — B4(a) 우측 차트
    bm_cum: float = 0.0        # 누적 BM 수익률 (%) — B4(a) 우측 차트


class BrinsonDailyClassDTO(BaseModel):
    """자산군별 일별 시계열 (B4: AP비중 추이 + 자산군 누적기여)."""
    date: date                 # 기준일자
    asset_class: str           # 자산군
    ap_weight: float           # AP 일별 비중 (%)
    bm_weight: float           # SAA/BM 목표비중 (%, 기간 고정)
    ap_contrib_cum: float      # AP 누적 기여수익률 (%)
    bm_contrib_cum: float      # BM 누적 기여수익률 (%)
    ap_ret_cum: float = 0.0    # AP 자산군 누적 실제수익률 (%, 0%시작) — Allocation/Selection 진단
    bm_ret_cum: float = 0.0    # BM 자산군(인덱스) 누적 실제수익률 (%, 0%시작)


class BrinsonResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    fund_name: str
    start_date: date
    end_date: date
    # 표0 '시작일' 토글 기준일 = start_date 직전 영업일(기초일). PA 창 (기초일, 기간말]
    # 과 같은 시점이라 비중 변화가 기여도·수익률과 정확히 대응한다 (2026-08-11 사용자 확정).
    base_date: date | None = None
    mapping_method: str        # "방법1"|"방법2"|"방법3"|"방법4"
    pa_method: str             # "8"|"5"
    fx_split: bool             # FX 분리 토글 echo
    data_pending: bool = False # 종료일이 환매정산중(증권>NAST)
    data_note: str | None = None  # 배지 안내 (정산중 스킵/경고)
    # 합계 (모두 %)
    period_ap_return: float
    period_bm_return: float
    total_alloc: float
    total_select: float
    total_cross: float
    total_excess: float
    total_excess_relative: float
    fx_contrib: float
    residual: float
    # 무위험 기간(start~end) 누적수익률 (%, KIS CD Index 총수익) — 샤프비율 계산용.
    # 프론트가 AP/BM 연율화(252영업일 기준)와 동일 공식으로 연율화하도록 '기간수익률'을
    # 그대로 전달 (이전 rf_annual 은 365.25 캘린더 연율화라 분자/분모 기준 불일치였음).
    # 로드 실패 시 None.
    rf_period: float | None = None
    # BM/SAA 구성 (item4: BM 셋팅 vs AP 비교 표). bm_source: "BM"|"SAA"|"none"
    bm_source: str
    bm_components: list[BrinsonBmComponentDTO]
    # BM 해외주식(ACWI) 4분할 — 표0 펼치기 표시 전용 (없으면 None)
    bm_equity_split: BrinsonBmEquitySplitDTO | None = None
    # 자산군별
    asset_rows: list[BrinsonAssetRowDTO]
    # 종목별 기여 (top 20)
    sec_contrib: list[BrinsonSecContribDTO]
    # 표0 AP 구성 = 기말 보유 스냅샷(현금 포함). 빈 리스트=fallback(프론트가 period 비중 사용)
    ap_composition: list[BrinsonApCompositionDTO] = []
    # 표0 '시작일' 토글용 = base_date(기초일) 보유 스냅샷. ap_composition 과 **완전히 같은
    # 경로**(build_holdings→_build_ap_composition)라 기말과 1:1 비교가 성립한다.
    # 빈 리스트면 프론트가 토글 자체를 감춘다(설정일 이전 등 스냅샷 부재).
    ap_composition_base: list[BrinsonApCompositionDTO] = []
    # 일별 누적 Brinson (수익률 비교 차트용)
    daily_brinson: list[BrinsonDailyPointDTO]
    # 자산군별 일별 시계열 (B4: AP비중 추이 + 자산군 누적기여)
    daily_class: list[BrinsonDailyClassDTO] = []


# === 기간별(1M/3M/6M/1Y/YTD/SI) Brinson 효과 — 성과분석 하단 기간 테이블 ===
class BrinsonPeriodRowDTO(BaseModel):
    """기간×자산군 한 행 (Allocation/Selection 토글 분해 테이블용)."""
    asset_class: str
    ap_weight: float
    bm_weight: float
    ap_return: float
    bm_return: float
    alloc_effect: float
    select_effect: float
    cross_effect: float


class BrinsonPeriodDTO(BaseModel):
    period: str                # "1M"|"3M"|"6M"|"1Y"|"YTD"|"SI"
    start_date: str            # YYYY-MM-DD (inception clamp 반영)
    has_bm: bool               # BM/SAA 있음 → 효과 분해 유효
    total_alloc: float
    total_select: float
    total_cross: float
    total_excess: float
    rows: list[BrinsonPeriodRowDTO]


class BrinsonPeriodsResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    end_date: str              # 기준 종료일 (모든 기간 공통)
    periods: list[BrinsonPeriodDTO]
