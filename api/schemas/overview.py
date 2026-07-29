from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .meta import BaseMeta


class NavPointDTO(BaseModel):
    date_: date = Field(alias="date")
    nav: float
    bm: float | None = None         # Week 2: BM rebased to NAV first value
    excess: float | None = None     # Week 2: (nav/nav[0]) - (bm/bm[0]), raw ratio
    aum: float | None = None

    model_config = {"populate_by_name": True}


class MetricCardDTO(BaseModel):
    key: str                        # "since_inception" | "ytd" | "mdd" | "vol"
    label: str
    value: float                    # raw ratio (0.0123 = 1.23%)
    unit: Literal["pct", "bp", "currency", "raw"] = "pct"
    bm_value: float | None = None
    excess_value: float | None = None


PeriodReturnsDTO = dict[str, float]
# keys: "1M" | "3M" | "6M" | "YTD" | "1Y" | "SI"
# value: raw ratio. 누락 기간은 dict에 key 미포함으로 표현.


class FundInfoDTO(BaseModel):
    """펀드 기본정보(Overview 메타바). OCIO 사모라 거래소 티커 대신 KSD 표준코드."""
    ticker: str | None = None        # KSD 표준코드 (거래소 티커 없음 — 사모)
    inception: date | None = None    # 설정일 (DWPI10011.FRST_OPNG_DT)
    setup_amount: float | None = None  # 설정액 = 설정 시점(첫 영업일) 순자산(NAST_AMT), 원
    fund_type: str | None = None     # 펀드타입 (사모 · 수익증권 등)
    manager: str | None = None       # 운용사
    fee_bp: float | None = None      # 총보수율 (bp, BOS3203 컴포넌트 합)
    nav: float | None = None         # 최신 기준가 (MOD_STPR)
    beneficiary: str | None = None   # 수익자 (FUND_BENEFICIARY, 하드코딩)
    target_return_annual: float | None = None  # 목표수익률 (연, fraction)


class PeriodReturnsResponseDTO(BaseModel):
    """기간별 수익률 표 전용 — 조회 종료일(end_date) 앵커 트레일링 기간수익률.

    end_date 미지정 시 최신 영업일 앵커(= OverviewResponseDTO.period_returns 와 동일).
    """
    fund_code: str
    end_date: date | None = None      # 실제 앵커일 (요청 end 이하 마지막 영업일)
    benchmark_kind: Literal["BM", "SAA", "none"] = "none"
    benchmark_label: str | None = None
    period_returns: PeriodReturnsDTO = Field(default_factory=dict)
    bm_period_returns: PeriodReturnsDTO = Field(default_factory=dict)
    # 벤치마크 미적재 시 end_date 는 BM 최종일로 당겨진다(펀드/BM 기간 정합).
    # fund_as_of = 펀드 기준가 최신일 — 둘이 다르면 UI 에 기준일 분리 표기.
    fund_as_of: date | None = None
    bm_as_of: date | None = None


class OverviewResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    fund_name: str
    inception_date: date
    bm_configured: bool
    cards: list[MetricCardDTO]                # Week 2: 최대 4개
    nav_series: list[NavPointDTO]             # Week 2: bm/excess 채움(가능 시)
    period_returns: PeriodReturnsDTO = Field(default_factory=dict)
    bm_period_returns: PeriodReturnsDTO = Field(default_factory=dict)
    fund_meta: FundInfoDTO | None = None      # 펀드 기본정보 (ticker/설정일/설정액/타입/운용사/보수/NAV)
    # --- Redesign: 벤치마크 종류(BM/SAA) + 추가 카드 데이터 ---
    benchmark_kind: Literal["BM", "SAA", "none"] = "none"  # nav_series.bm/excess 의 의미
    benchmark_label: str | None = None        # 차트/카드 표기용 라벨 (예: "SAA", "BM")
    bm_volatility: float | None = None         # 벤치마크 연환산 변동성 (설정후/누적, 주간 std×√52)
    operating_profit_krw: float | None = None  # 운용수익(보수차감후순), 원
    volatility_ytd: float | None = None         # 포트 YTD 연환산 변동성
    bm_volatility_ytd: float | None = None      # 벤치마크 YTD 연환산 변동성
    equity_weight: float | None = None          # 포트 주식비중(국내+해외, look-through), fraction
    bm_equity_weight: float | None = None       # 벤치마크 주식비중(컴포넌트 매핑), fraction
    # --- 기간 정합 / 소스 신선도 (2026-07-29) ---
    # returns_as_of: 수익률 계열(카드·기간수익률) 앵커일 = 벤치마크 최종일.
    # meta.as_of_date(기준가·AUM·차트 최신일) 와 다르면 UI 에 분리 표기.
    returns_as_of: date | None = None
    bm_as_of: date | None = None
    # BM 구성지수 대체 소스 발동 목록 (Bloomberg 피드 정지 대응)
    bm_source_notes: list[str] = Field(default_factory=list)
