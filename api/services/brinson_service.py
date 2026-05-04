"""Brinson 3-Factor Attribution service.

`modules.data_loader.compute_brinson_attribution_v2` 호출 + LRU 캐시 + 후처리(5분류 축소,
FX off, 유동성/잔차 합산) + DTO 매핑.

기간 기본값:
  - start_date 미지정: YTD (당해 연도 1월 1일 — 정확히는 전년도 12/31 = R 동일).
  - 펀드 inception 이 YTD 시작 이후라면 inception 으로 보정.
  - end_date 미지정: 어제 (KST naive).

mapping_method 기본값:
  - `FUND_DEFAULT_MAPPING_METHOD[code]` (4JM12 = 방법4) 우선, 없으면 `DEFAULT_MAPPING_METHOD` (방법3).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import pandas as pd

from config.funds import (
    DEFAULT_MAPPING_METHOD,
    FUND_DEFAULT_MAPPING_METHOD,
    FUND_LIST,
    FUND_META,
)

from ..schemas.brinson import (
    BrinsonAssetRowDTO,
    BrinsonDailyPointDTO,
    BrinsonResponseDTO,
    BrinsonSecContribDTO,
)
from ..schemas.meta import BaseMeta, SourceBreakdown

ALLOWED_MAPPING_METHODS: tuple[str, ...] = ("방법1", "방법2", "방법3", "방법4")
ALLOWED_PA_METHODS: tuple[str, ...] = ("8", "5")

# 5분류 축소: Streamlit tabs/brinson.py:102-108 동일
_CORE5_BY_METHOD: dict[str, tuple[str, ...]] = {
    "방법1": ("주식", "채권", "대체", "FX"),
    "방법2": ("주식", "채권", "FX"),
    "방법3": ("국내주식", "해외주식", "국내채권", "해외채권", "대체"),
    "방법4": ("국내주식", "해외주식", "국내채권", "해외채권"),
}

# Asset class 정렬 (Streamlit tabs/brinson.py:273)
_BRINSON_ROW_ORDER = (
    "주식", "채권",
    "국내주식", "국내채권", "해외주식", "해외채권",
    "대체", "대체투자",
    "FX",
    "모펀드",
    "기타",
    "유동성", "유동성및기타",
)
_ROW_ORDER_MAP = {ac: i for i, ac in enumerate(_BRINSON_ROW_ORDER)}


# -------------------- date helpers --------------------

def _yesterday_kst() -> date:
    # KST 의미상이지만 서버 로컬 시간 기준 어제. 운영 환경이 KST 라 일치.
    return (datetime.now() - timedelta(days=1)).date()


def _resolve_default_period(fund_code: str) -> tuple[date, date]:
    """YTD 기본값 — 단, inception 이 당해년도면 inception 사용.

    Streamlit tabs/brinson.py:32-38 동일 로직.
    """
    end = _yesterday_kst()
    year = end.year
    ytd_start = date(year - 1, 12, 31)
    inception_str = (FUND_META.get(fund_code, {}) or {}).get("inception", "20220101")
    try:
        inception_dt = datetime.strptime(inception_str, "%Y%m%d").date()
    except ValueError:
        inception_dt = ytd_start
    if inception_dt > ytd_start:
        ytd_start = inception_dt
    return ytd_start, end


def _resolve_mapping_method(fund_code: str, override: str | None) -> str:
    if override:
        return override
    return FUND_DEFAULT_MAPPING_METHOD.get(fund_code, DEFAULT_MAPPING_METHOD)


def _to_yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


# -------------------- core compute (cached) --------------------

@lru_cache(maxsize=128)
def _compute_cached(fund_code: str, start_yyyymmdd: str, end_yyyymmdd: str,
                    mapping_method: str) -> dict | None:
    """compute_brinson_attribution_v2 호출 결과를 LRU 캐시.

    캐시 키에 (fund, start, end, method) 만 포함. pa_method/fx_split 은
    동일 결과의 후처리 (자산군 합산 / FX 행 제거) 로 처리해 재계산 회피.
    end_date 가 변경되면 자연 invalidation.
    """
    from modules.data_loader import compute_brinson_attribution_v2
    return compute_brinson_attribution_v2(
        fund_code, start_yyyymmdd, end_yyyymmdd,
        mapping_method=mapping_method,
    )


# -------------------- post-processing --------------------

def _collapse_5class(pa_df: pd.DataFrame, mapping_method: str) -> pd.DataFrame:
    """8분류 → 5분류 축소 (Streamlit tabs/brinson.py:99-121)."""
    core5 = _CORE5_BY_METHOD.get(
        mapping_method, ("국내주식", "해외주식", "국내채권", "해외채권", "대체투자")
    )
    in_core = pa_df[pa_df["자산군"].isin(core5)].copy()
    other = pa_df[~pa_df["자산군"].isin(core5)]
    if other.empty:
        return in_core
    other_row = pd.DataFrame([{
        "자산군": "기타",
        "AP비중": other["AP비중"].sum(),
        "BM비중": other["BM비중"].sum(),
        "AP수익률": 0.0,
        "BM수익률": 0.0,
        "Allocation": other["Allocation"].sum(),
        "Selection": other["Selection"].sum(),
        "Cross": other["Cross"].sum(),
        "기여수익률": other["기여수익률"].sum(),
    }])
    return pd.concat([in_core, other_row], ignore_index=True)


def _drop_fx(pa_df: pd.DataFrame) -> pd.DataFrame:
    return pa_df[pa_df["자산군"] != "FX"].copy()


def _sort_pa_df(pa_df: pd.DataFrame) -> pd.DataFrame:
    df = pa_df.copy()
    df["_sort"] = df["자산군"].map(_ROW_ORDER_MAP).fillna(99)
    df = df.sort_values("_sort").drop(columns="_sort").reset_index(drop=True)
    return df


def _to_asset_rows(pa_df: pd.DataFrame) -> list[BrinsonAssetRowDTO]:
    rows: list[BrinsonAssetRowDTO] = []
    for _, r in pa_df.iterrows():
        rows.append(BrinsonAssetRowDTO(
            asset_class=str(r["자산군"]),
            ap_weight=float(r.get("AP비중", 0.0) or 0.0),
            bm_weight=float(r.get("BM비중", 0.0) or 0.0),
            ap_return=float(r.get("AP수익률", 0.0) or 0.0),
            bm_return=float(r.get("BM수익률", 0.0) or 0.0),
            alloc_effect=float(r.get("Allocation", 0.0) or 0.0),
            select_effect=float(r.get("Selection", 0.0) or 0.0),
            cross_effect=float(r.get("Cross", 0.0) or 0.0),
            contrib_return=float(r.get("기여수익률", 0.0) or 0.0),
        ))
    return rows


def _to_sec_rows(sec_df: pd.DataFrame | None) -> list[BrinsonSecContribDTO]:
    if sec_df is None or sec_df.empty:
        return []
    out: list[BrinsonSecContribDTO] = []
    for _, r in sec_df.iterrows():
        out.append(BrinsonSecContribDTO(
            asset_class=str(r.get("자산군", "")),
            item_nm=str(r.get("종목명", "")),
            weight_pct=float(r.get("비중(%)", r.get("순자산비중", 0.0)) or 0.0),
            return_pct=float(r.get("수익률(%)", r.get("개별수익률", 0.0)) or 0.0),
            contrib_pct=float(r.get("기여수익률(%)", r.get("기여수익률", 0.0)) or 0.0),
        ))
    return out


def _to_daily_rows(daily_df: pd.DataFrame | None) -> list[BrinsonDailyPointDTO]:
    if daily_df is None or daily_df.empty:
        return []
    out: list[BrinsonDailyPointDTO] = []
    for _, r in daily_df.iterrows():
        d = r["기준일자"]
        if isinstance(d, pd.Timestamp):
            d = d.date()
        elif isinstance(d, str):
            d = datetime.strptime(d[:10], "%Y-%m-%d").date()
        out.append(BrinsonDailyPointDTO(
            date=d,
            alloc_cum=float(r.get("alloc_cum", 0.0) or 0.0),
            select_cum=float(r.get("select_cum", 0.0) or 0.0),
            cross_cum=float(r.get("cross_cum", 0.0) or 0.0),
            excess_cum=float(r.get("excess_cum", 0.0) or 0.0),
        ))
    return out


# -------------------- public --------------------

def build_brinson(
    fund_code: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    mapping_method: str | None = None,
    pa_method: str = "8",
    fx_split: bool = True,
) -> BrinsonResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)
    if pa_method not in ALLOWED_PA_METHODS:
        raise ValueError(f"pa_method must be one of {ALLOWED_PA_METHODS}")
    method = _resolve_mapping_method(fund_code, mapping_method)
    if method not in ALLOWED_MAPPING_METHODS:
        raise ValueError(f"mapping_method must be one of {ALLOWED_MAPPING_METHODS}")

    if start_date is None or end_date is None:
        d_start, d_end = _resolve_default_period(fund_code)
        start_date = start_date or d_start
        end_date = end_date or d_end

    if start_date >= end_date:
        raise ValueError("start_date must be earlier than end_date")

    sources: list[SourceBreakdown] = []
    warnings: list[str] = []
    is_fallback = False

    raw = _compute_cached(
        fund_code,
        _to_yyyymmdd(start_date), _to_yyyymmdd(end_date),
        method,
    )

    if raw is None or (raw.get("pa_df") is None) or raw["pa_df"].empty:
        is_fallback = True
        warnings.append(
            "MA000410 PA 데이터 없음 또는 보유종목 매핑 실패 — 빈 결과 반환"
        )
        pa_df = pd.DataFrame(columns=[
            "자산군", "AP비중", "BM비중", "AP수익률", "BM수익률",
            "Allocation", "Selection", "Cross", "기여수익률"
        ])
        empty_dailies = pd.DataFrame()
        empty_sec = pd.DataFrame()
        return BrinsonResponseDTO(
            meta=BaseMeta(
                as_of_date=end_date,
                source="db",
                sources=sources,
                is_fallback=True,
                warnings=warnings,
                generated_at=datetime.now(timezone.utc),
            ),
            fund_code=fund_code,
            fund_name=str((FUND_META.get(fund_code, {}) or {}).get("name", fund_code)),
            start_date=start_date,
            end_date=end_date,
            mapping_method=method,
            pa_method=pa_method,
            fx_split=fx_split,
            period_ap_return=0.0,
            period_bm_return=0.0,
            total_alloc=0.0,
            total_select=0.0,
            total_cross=0.0,
            total_excess=0.0,
            total_excess_relative=0.0,
            fx_contrib=0.0,
            residual=0.0,
            asset_rows=[],
            sec_contrib=[],
            daily_brinson=[],
        )

    sources.append(SourceBreakdown(component="pa", kind="db", note="dt.MA000410"))

    pa_df = raw["pa_df"].copy()
    if pa_method == "5":
        pa_df = _collapse_5class(pa_df, method)
    if not fx_split and "FX" in set(pa_df["자산군"].astype(str)):
        pa_df = _drop_fx(pa_df)
    pa_df = _sort_pa_df(pa_df)

    return BrinsonResponseDTO(
        meta=BaseMeta(
            as_of_date=end_date,
            source="db",
            sources=sources,
            is_fallback=is_fallback,
            warnings=warnings,
            generated_at=datetime.now(timezone.utc),
        ),
        fund_code=fund_code,
        fund_name=str((FUND_META.get(fund_code, {}) or {}).get("name", fund_code)),
        start_date=start_date,
        end_date=end_date,
        mapping_method=method,
        pa_method=pa_method,
        fx_split=fx_split,
        period_ap_return=float(raw.get("period_ap_return", 0.0) or 0.0),
        period_bm_return=float(raw.get("period_bm_return", 0.0) or 0.0),
        total_alloc=float(raw.get("total_alloc", 0.0) or 0.0),
        total_select=float(raw.get("total_select", 0.0) or 0.0),
        total_cross=float(raw.get("total_cross", 0.0) or 0.0),
        total_excess=float(raw.get("total_excess", 0.0) or 0.0),
        total_excess_relative=float(raw.get("total_excess_relative", 0.0) or 0.0),
        fx_contrib=float(raw.get("fx_contrib", 0.0) or 0.0),
        residual=float(raw.get("residual", 0.0) or 0.0),
        asset_rows=_to_asset_rows(pa_df),
        sec_contrib=_to_sec_rows(raw.get("sec_contrib")),
        daily_brinson=_to_daily_rows(raw.get("daily_brinson")),
    )


def invalidate_cache() -> None:
    """관리용. NAV/PA 일일 갱신 후 호출."""
    _compute_cached.cache_clear()
