from pydantic import BaseModel

from .meta import BaseMeta


class TransactionRowDTO(BaseModel):
    date: str               # YYYYMMDD (원본 std_dt 문자열)
    fund_code: str          # 거래가 발생한 (자)펀드 코드
    item_nm: str
    asset_class: str        # 6분류 (국내주식/해외주식/국내채권/해외채권/대체투자/FX/모펀드/유동성)
    side: str               # 매수 / 매도
    amount_eok: float       # 거래금액 (억원)


class TransactionsResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    lookthrough_applied: bool       # FoF면 True (자펀드 거래로 치환됨)
    funds_queried: list[str]        # 실제 조회된 펀드 (FoF면 자펀드들)
    start_date: str                 # YYYY-MM-DD
    end_date: str                   # YYYY-MM-DD
    rows: list[TransactionRowDTO]


class WeightHistoryPointDTO(BaseModel):
    date: str               # YYYY-MM-DD
    key: str                # 종목명 (level=security) 또는 자산군 (level=asset)
    weight: float           # % (일자별 합 ≈ 100)


class WeightMarkerDTO(BaseModel):
    date: str               # YYYY-MM-DD
    key: str                # WeightHistoryPointDTO.key 와 동일 (버킷 또는 종목명)
    net_eok: float          # 순매수(억). >0 매수우위 ▲ / <0 매도우위 ▼


class WeightHistoryResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    level: str                      # 'security' | 'asset'
    lookthrough_applied: bool       # FoF면 True (자펀드 가중평균 전개)
    start_date: str                 # YYYY-MM-DD
    keys: list[str]                 # 정렬된 key (버킷 순서 → 평균비중 desc). security면 '유동성' 묶음 포함
    points: list[WeightHistoryPointDTO]
    markers: list[WeightMarkerDTO]  # 일자·key별 순매수 마커 (영역차트 ▲▼)


# === FX 포지션 (달러선물 등) 별도 라인차트 ===
class FxPositionPointDTO(BaseModel):
    date: str               # YYYY-MM-DD
    key: str                # 계약명 (예: 미국달러 F 202607)
    weight: float           # 순비중 % (매도=음수)


class FxPositionResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    has_fx: bool            # 달러선물 포지션 존재 여부
    start_date: str
    keys: list[str]
    points: list[FxPositionPointDTO]


# === 종목별 수익률 라인차트 + 매수/매도 마커 ===
class SecurityItemDTO(BaseModel):
    item_cd: str
    item_nm: str
    bucket: str             # 6버킷 (국내주식~금/대체)
    weight: float           # 최근일 비중 %
    has_price: bool         # SCIP 가격 커버리지


class SecuritiesResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    items: list[SecurityItemDTO]


class SecurityReturnPointDTO(BaseModel):
    date: str               # YYYY-MM-DD
    value: float            # 수익률 지수 (시작=100)


class SecurityTradeMarkerDTO(BaseModel):
    date: str               # YYYY-MM-DD
    side: str               # 매수/매도/발행(BA정산)/환매(BA정산)
    amount: float           # 금액(억)


class SecurityWeightPointDTO(BaseModel):
    date: str               # YYYY-MM-DD
    weight: float           # 종목 편입비중 % (보조축 레이어용)


class SecurityReturnResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    item_cd: str
    item_nm: str
    start_date: str
    points: list[SecurityReturnPointDTO]
    trades: list[SecurityTradeMarkerDTO]
    weights: list[SecurityWeightPointDTO]   # 보조축 비중 시계열 (옅은 레이어)
