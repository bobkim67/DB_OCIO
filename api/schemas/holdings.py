from datetime import date

from pydantic import BaseModel

from .meta import BaseMeta


class HoldingAssetClassDTO(BaseModel):
    asset_class: str                # 국내주식/해외주식/국내채권/해외채권/대체투자/FX/모펀드/유동성
    weight: float                   # raw ratio (0.0123 = 1.23%)
    evl_amt: float                  # 평가금액 (KRW)
    item_count: int
    color: str | None = None        # UI 힌트 (ASSET_COLORS)


class HoldingItemDTO(BaseModel):
    item_cd: str
    item_nm: str
    asset_class: str
    weight: float                   # 순자산대비 비중 raw ratio
    evl_amt: float                  # 평가금액
    sub_fund_cd: str | None = None  # look-through 적용 시 원 하위 펀드코드
    is_short: bool = False          # 매도 포지션 여부 (DWPM10530 POS_DS_CD='매도')


class FxHedgeSummaryDTO(BaseModel):
    """USD 자산비중 vs 달러매도포지션 비중 → 헷지비율."""
    usd_asset_weight: float         # 해외주식+해외채권+대체투자+USD 예치금 등 USD 노출
    usd_short_weight: float         # FX 자산군 내 매도 포지션 합 (절대값, raw ratio)
    hedge_ratio: float | None = None  # = usd_short_weight / usd_asset_weight (없으면 None)


class HoldingsResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    fund_name: str
    as_of_date: date | None
    lookthrough_applied: bool
    nast_amt: float | None = None
    asset_class_weights: list[HoldingAssetClassDTO]
    holdings_items: list[HoldingItemDTO]
    fx_hedge: FxHedgeSummaryDTO | None = None
