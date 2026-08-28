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
    evl_amt: float                  # 평가금액 (원화, DWPM10530.EVL_AMT)
    # 외화표시 종목(DWPM10530.CURR_DS_CD != KRW)의 원통화 평가액 — 원화와 병기용.
    # USD DEPOSIT 처럼 "몇 달러인지"가 원화액보다 직관적인 라인이 있다(2026-08-28 사용자 지시).
    currency: str | None = None     # 'USD' 등. 원화/미상이면 None
    fc_evl_amt: float | None = None # DWPM10530.FC_EVL_AMT (look-through 시 지분 배수 적용)
    sub_fund_cd: str | None = None  # look-through 적용 시 원 하위 펀드코드
    is_short: bool = False          # 매도 포지션 여부 (DWPM10530 POS_DS_CD='매도')
    duration: float | None = None   # 모듈 duration_fetcher 매핑 종목만 채움
    ytm: float | None = None        # 단위: % (예: 3.73)
    first_date: str | None = None   # 최초 편입일 YYYY-MM-DD (DWPM10530 전이력 MIN)


class FxHedgeSummaryDTO(BaseModel):
    """USD 자산비중 vs 달러매도포지션 비중 → 헷지비율."""
    usd_asset_weight: float         # 해외주식+해외채권+대체투자+USD 예치금 등 USD 노출
    usd_short_weight: float         # FX 자산군 내 매도 포지션 합 (절대값, raw ratio)
    hedge_ratio: float | None = None  # = usd_short_weight / usd_asset_weight (없으면 None)


class PortfolioMixSummaryDTO(BaseModel):
    """편입종목 상단 카드용 비중 요약.

    종목코드 기반 식별 (item_cd 정확 매칭):
      - 금 = {KR7411060007 ACE KRX금현물, US92189F1066 GDX, US46436F1030 IAUM}
      - USHY = {US46435U8532 iShares Broad USD HY, KR7468380001 KODEX 미국HY액티브}
      - 현금 = {USMUSD022001 USD Deposit} ∪ item_nm에 '예금' 포함

    모든 weight는 raw ratio (NAST 분모, FX 자산군 short 처리 그대로 — abs 안 함).
    """
    equity_weight: float = 0.0          # 주식(국내+해외) + 금
    bond_weight: float = 0.0            # 채권(국내+해외)
    risk_asset_weight: float = 0.0      # 주식 + 금 + USHY
    cash_weight: float = 0.0            # USD Deposit + 예금 종목
    cash_amount: float = 0.0            # 위의 KRW 평가금액 합


class WeightedDurationDTO(BaseModel):
    """모듈 duration_fetcher.compute_weighted_duration 결과를 client용으로 노출.

    Raw ratio 단위 일관 (weight). dur/ytm 단위는 fetcher 그대로 (년/%).

    두 가지 가중평균:
      - bond: 매핑된 채권성 종목만으로 산출 (분모 = covered_weight)
      - overall: 전체 보유 비중 분모 (미매핑 종목 dur=0 가정 효과)
    """
    duration_bond: float | None = None      # 채권성 종목 가중평균 듀레이션 (년)
    ytm_bond: float | None = None           # 채권성 종목 가중평균 YTM (%)
    duration_overall: float | None = None   # 전체 비중 가중평균 듀레이션 (년)
    ytm_overall: float | None = None        # 전체 비중 가중평균 YTM (%)
    covered_weight: float = 0.0             # 매핑된 종목 합산 비중 (raw ratio)
    total_weight: float = 0.0               # 입력 전체 합산 비중 (raw ratio)
    coverage_ratio: float = 0.0             # covered / total (0~1)


class EquityHoldingDTO(BaseModel):
    """주식 포커스 산점도용 — 보유 주식 ETF 의 proxy 밸류에이션."""
    item_nm: str
    asset_class: str
    weight: float
    proxy_ticker: str | None = None   # VUG/VTV/SPY/VWO/EFA/EWY
    per: float | None = None
    eps_growth: float | None = None   # YoY, fraction


class EquityProxyRefDTO(BaseModel):
    """산점도 참조 스타일 점 (proxy ETF 밸류에이션 지도)."""
    ticker: str
    per: float | None = None
    eps_growth: float | None = None


class EquityFocusDTO(BaseModel):
    equity_weight: float = 0.0
    weighted_per: float | None = None
    weighted_eps_growth: float | None = None
    holdings: list[EquityHoldingDTO] = []
    references: list[EquityProxyRefDTO] = []
    region_tilt: dict[str, float] = {}   # {국내, 해외} weight 합
    style_tilt: dict[str, float] = {}    # {성장, 가치, 기타}


class ComplianceItemDTO(BaseModel):
    """컴플라이언스 게이지 — 현재 비중 vs 가이드라인 밴드."""
    key: str                          # equity/bond/risk_asset/cash
    label: str
    value: float                      # 현재 비중 (fraction)
    band_low: float | None = None
    band_high: float | None = None
    status: str = "none"              # ok / warn / breach / none
    breakdown: str | None = None      # 라벨 옆 구성 표기 예: "주식 + 금" / "주식 + 금 + 하이일드"


class PendingSettlementDTO(BaseModel):
    """기준일 시점에 결제가 안 끝난 거래 — 안내 배너용 (2026-08-03).

    source:
      - 'mail'   : 브로커 체결확인서(Outlook 해외거래 폴더)에만 있고 원장 미반영.
                   해외 거래는 체결 다음 영업일(SettleDate)에야 원장에 잡히므로
                   그 사이 화면 비중에 전혀 반영되지 않는다.
      - 'ledger' : 원장(DWPM10520)에 있고 결제일만 미도래. 비중에는 이미
                   매입/환매미지급금(부채)으로 반영돼 있다 — 유동성이 음수로
                   보이는 이유가 대개 이것.
    비중·평가금액은 건드리지 않는다 (원장 = SSOT, 2026-08-03 사용자 확정).
    """
    source: str                        # mail / ledger
    item_nm: str
    ticker: str | None = None
    side: str                          # 매수 / 매도
    qty: float | None = None
    ccy: str = "KRW"
    amount: float | None = None        # 결제금액 (원통화)
    amount_krw: float | None = None    # 원화 환산 (외화는 매매기준율 적용, 참고값)
    trade_date: date | None = None
    settle_date: date | None = None
    # 화면 반영 예정일 = 결제일 다음 영업일 (2026-08-03).
    # 원장 STD_DT 는 결제일(T+1)이지만 보유·기준가 스냅샷은 익일 새벽 적재라
    # 눈에 보이는 건 하루 더 뒤 = 체결 기준 T+2. 배너/카드의 '{M/D} 반영'이 이 값.
    reflect_date: date | None = None
    note: str | None = None


class HoldingsResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    fund_name: str
    as_of_date: date | None
    lookthrough_applied: bool
    data_pending: bool = False        # 현재 기준일이 환매정산중(증권>NAST, 비중 왜곡)
    data_note: str | None = None      # 배지 안내 (정산중 스킵/경고)
    nast_amt: float | None = None
    opng_amt: float | None = None
    asset_class_weights: list[HoldingAssetClassDTO]
    holdings_items: list[HoldingItemDTO]
    # FX(달러선물 등) — **NAV 구성이 아니라 포지션(notional)** 이라 holdings_items 와
    # 자산군 비중에서는 빠진다(2026-06-24 확정). 화면에서 통째로 사라지면 포지션을
    # 놓치므로 별도로 실어 **펀드 합계 아래 참고 행**으로 표시한다 (2026-08-07).
    fx_positions: list[HoldingItemDTO] = []
    fx_hedge: FxHedgeSummaryDTO | None = None
    duration_summary: WeightedDurationDTO | None = None
    portfolio_mix: PortfolioMixSummaryDTO | None = None
    equity_focus: EquityFocusDTO | None = None       # 주식 포커스 (PER×EPS성장)
    compliance: list[ComplianceItemDTO] = []         # 컴플 게이지
    pending_settlements: list[PendingSettlementDTO] = []   # 결제 예정 안내 (비중 미반영)
