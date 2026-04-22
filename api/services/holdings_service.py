from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from config.funds import FUND_LIST, FUND_META

from ..schemas.holdings import (
    HoldingAssetClassDTO,
    HoldingItemDTO,
    HoldingsResponseDTO,
)
from ..schemas.meta import BaseMeta, SourceBreakdown


_ASSET_CLASS_ORDER = [
    "국내주식", "해외주식", "국내채권", "해외채권",
    "대체투자", "FX", "모펀드", "유동성",
]

_ASSET_COLORS = {
    "국내주식": "#EF553B",
    "해외주식": "#636EFA",
    "국내채권": "#00CC96",
    "해외채권": "#AB63FA",
    "대체투자": "#FFA15A",
    "FX": "#19D3F3",
    "모펀드": "#FF6692",
    "유동성": "#B6E880",
}


def _iso_to_yyyymmdd(s: str) -> str:
    return s.replace("-", "")


def _load_holdings_df(
    fund_code: str, as_of: str | None, lookthrough: bool,
) -> pd.DataFrame | None:
    """data_loader 재사용. lookthrough=true → load_fund_holdings_lookthrough."""
    from modules.data_loader import (
        load_fund_holdings_classified,
        load_fund_holdings_lookthrough,
    )
    if lookthrough:
        return load_fund_holdings_lookthrough(fund_code, date=as_of)
    return load_fund_holdings_classified(fund_code, date=as_of)


def _load_nast(fund_code: str, as_of: date | None) -> float | None:
    """해당 기준일의 NAST_AMT. 없으면 최근 유효값."""
    if as_of is None:
        return None
    try:
        from modules.data_loader import load_fund_nav_with_aum
        df = load_fund_nav_with_aum(fund_code, as_of.strftime("%Y%m%d"))
        if df is None or df.empty or "NAST_AMT" not in df.columns:
            return None
        mask = pd.to_datetime(df["기준일자"]).dt.date == as_of
        sub = df[mask]
        if not sub.empty:
            v = sub["NAST_AMT"].iloc[-1]
            if pd.notna(v) and v > 0:
                return float(v)
        # fallback: 전체 중 마지막 유효값
        s = df["NAST_AMT"].dropna()
        if len(s) > 0:
            return float(s.iloc[-1])
    except Exception:
        return None
    return None


def _val(row: pd.Series, *names: str, default: Any = None) -> Any:
    for n in names:
        if n in row:
            v = row[n]
            if v is None:
                continue
            if isinstance(v, float) and np.isnan(v):
                continue
            return v
    return default


def _extract_as_of(df: pd.DataFrame) -> date | None:
    if "STD_DT" in df.columns:
        s = df["STD_DT"].iloc[0]
        try:
            return pd.to_datetime(str(int(s)), format="%Y%m%d").date()
        except Exception:
            pass
    if "기준일자" in df.columns:
        s = df["기준일자"].iloc[0]
        if hasattr(s, "date"):
            return s.date()
    return None


def build_holdings(
    fund_code: str,
    lookthrough: bool,
    as_of_date: str | None = None,
) -> HoldingsResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)

    meta_f = FUND_META.get(fund_code, {})
    warnings: list[str] = []
    sources: list[SourceBreakdown] = []
    source_kind: str = "db"

    as_of_param = _iso_to_yyyymmdd(as_of_date) if as_of_date else None

    # 1) holdings DataFrame
    try:
        df = _load_holdings_df(fund_code, as_of_param, lookthrough)
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")
        df = None

    if df is None or len(df) == 0:
        return HoldingsResponseDTO(
            meta=BaseMeta(
                as_of_date=None,
                source="mock",
                sources=[],
                is_fallback=True,
                warnings=warnings or ["보유종목 데이터 없음"],
                generated_at=datetime.now(timezone.utc),
            ),
            fund_code=fund_code,
            fund_name=meta_f.get("name", fund_code),
            as_of_date=None,
            lookthrough_applied=lookthrough,
            nast_amt=None,
            asset_class_weights=[],
            holdings_items=[],
        )

    sources.append(SourceBreakdown(component="holdings", kind="db"))

    # 2) as_of 확정
    as_of = _extract_as_of(df)

    # 3) NAST_AMT
    nast = _load_nast(fund_code, as_of)
    if nast is None or nast <= 0:
        warnings.append("NAST_AMT 미확보, 평가금액 비율로 대체")
        sources.append(SourceBreakdown(
            component="nast", kind="mock", note="NAST missing",
        ))
        source_kind = "mixed"
        denom = (
            float(df["EVL_AMT"].sum())
            if "EVL_AMT" in df.columns and df["EVL_AMT"].sum() > 0
            else None
        )
    else:
        sources.append(SourceBreakdown(component="nast", kind="db"))
        denom = nast

    # 4) 종목 DTO 생성
    items: list[HoldingItemDTO] = []
    for _, row in df.iterrows():
        evl_raw = _val(row, "EVL_AMT")
        if evl_raw is None:
            continue
        try:
            evl_f = float(evl_raw)
        except (TypeError, ValueError):
            continue
        weight = (evl_f / denom) if (denom and denom > 0) else 0.0
        ac_raw = _val(row, "자산군", "AST_CLSF_CD_NM", default="기타")
        items.append(HoldingItemDTO(
            item_cd=str(_val(row, "ITEM_CD", default="")),
            item_nm=str(_val(row, "ITEM_NM", default="")),
            asset_class=str(ac_raw),
            weight=weight,
            evl_amt=evl_f,
            sub_fund_cd=(
                str(_val(row, "SUB_FUND_CD", "sub_fund_cd"))
                if _val(row, "SUB_FUND_CD", "sub_fund_cd") is not None
                else None
            ),
        ))

    # 5) 자산군 집계
    by_class: dict[str, list[HoldingItemDTO]] = {}
    for it in items:
        by_class.setdefault(it.asset_class, []).append(it)

    asset_class_weights: list[HoldingAssetClassDTO] = []
    for ac in _ASSET_CLASS_ORDER:
        bucket = by_class.get(ac, [])
        if not bucket:
            continue
        asset_class_weights.append(HoldingAssetClassDTO(
            asset_class=ac,
            weight=sum(it.weight for it in bucket),
            evl_amt=sum(it.evl_amt for it in bucket),
            item_count=len(bucket),
            color=_ASSET_COLORS.get(ac),
        ))
    for ac, bucket in by_class.items():
        if ac in _ASSET_CLASS_ORDER:
            continue
        asset_class_weights.append(HoldingAssetClassDTO(
            asset_class=ac,
            weight=sum(it.weight for it in bucket),
            evl_amt=sum(it.evl_amt for it in bucket),
            item_count=len(bucket),
            color=None,
        ))

    # 6) 종목 정렬: 자산군 순서 → weight desc
    order_idx = {ac: i for i, ac in enumerate(_ASSET_CLASS_ORDER)}
    items.sort(key=lambda it: (order_idx.get(it.asset_class, 99), -it.weight))

    return HoldingsResponseDTO(
        meta=BaseMeta(
            as_of_date=as_of,
            source=source_kind,     # type: ignore[arg-type]
            sources=sources,
            is_fallback=False,
            warnings=warnings,
            generated_at=datetime.now(timezone.utc),
        ),
        fund_code=fund_code,
        fund_name=meta_f.get("name", fund_code),
        as_of_date=as_of,
        lookthrough_applied=lookthrough,
        nast_amt=nast,
        asset_class_weights=asset_class_weights,
        holdings_items=items,
    )
