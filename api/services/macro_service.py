from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..schemas.macro import (
    MacroPointDTO,
    MacroSeriesDTO,
    MacroTimeseriesResponseDTO,
)
from ..schemas.meta import BaseMeta, SourceBreakdown


# Week 4 MVP 기본 public key 3개
DEFAULT_KEYS: list[str] = ["PE", "EPS", "USDKRW"]

# public key (UI용) → modules.data_loader.MACRO_DATASETS 내부 키 매핑
_PUBLIC_TO_INTERNAL: dict[str, str] = {
    "PE": "MSCI ACWI_PE",
    "EPS": "MSCI ACWI_EPS",
    "USDKRW": "USD/KRW",
}

# UI 라벨/단위 (MACRO_DATASETS에 없는 부가 정보만 유지)
_LABEL: dict[str, str] = {
    "PE": "PE (12M Fwd, MSCI ACWI)",
    "EPS": "EPS (12M Fwd, MSCI ACWI)",
    "USDKRW": "USD/KRW",
}
_UNIT: dict[str, str] = {
    "PE": "ratio",
    "EPS": "raw",
    "USDKRW": "krw",
}


def _iso_to_yyyymmdd(s: str) -> str:
    # modules.data_loader.load_macro_timeseries는 'YYYY-MM-DD' 형식도 허용하므로
    # 그대로 전달해도 무방. 통일성을 위해 원문 유지.
    return s


def _normalize_keys(raw: list[str] | None) -> list[str]:
    if raw is None:
        return list(DEFAULT_KEYS)
    out: list[str] = []
    for item in raw:
        for k in str(item).split(","):
            k = k.strip()
            if k:
                out.append(k)
    return out


def _resolve_internal_key(public_key: str) -> str:
    """public key → 내부 MACRO_DATASETS 키. 매핑 없으면 원본 사용."""
    return _PUBLIC_TO_INTERNAL.get(public_key, public_key)


def _known_internal_keys() -> set[str]:
    try:
        from modules.data_loader import MACRO_DATASETS
        return set(MACRO_DATASETS.keys())
    except Exception:
        return set()


def _load_one_series(public_key: str, start_date: str | None) -> pd.DataFrame | None:
    """단일 public key → DataFrame. 실패 시 None."""
    internal = _resolve_internal_key(public_key)
    try:
        from modules.data_loader import load_macro_timeseries
        res = load_macro_timeseries(
            indicator_keys=[internal],
            start_date=start_date if start_date else "2017-01-01",
        )
    except Exception:
        return None
    if not isinstance(res, dict):
        return None
    df = res.get(internal)
    if df is None or len(df) == 0:
        return None
    return df


def _extract_points(df: pd.DataFrame) -> list[MacroPointDTO]:
    # load_macro_timeseries 반환: DataFrame(기준일자, value)
    if "기준일자" not in df.columns or "value" not in df.columns:
        return []
    dates = pd.to_datetime(df["기준일자"])
    out: list[MacroPointDTO] = []
    for d, v in zip(dates, df["value"]):
        if pd.isna(v):
            continue
        out.append(MacroPointDTO(
            date=d.date() if hasattr(d, "date") else d,
            value=float(v),
        ))
    return out


def build_macro_timeseries(
    keys: list[str] | None,
    start_date: str | None = None,
) -> MacroTimeseriesResponseDTO:
    resolved_keys = _normalize_keys(keys)
    if not resolved_keys:
        raise ValueError("keys must be non-empty")

    known_internal = _known_internal_keys()
    _start = _iso_to_yyyymmdd(start_date) if start_date else None

    series: list[MacroSeriesDTO] = []
    sources: list[SourceBreakdown] = []
    warnings: list[str] = []
    failures = 0

    for k in resolved_keys:
        internal = _resolve_internal_key(k)
        if known_internal and internal not in known_internal:
            warnings.append(f"unknown key: {k}")
            sources.append(SourceBreakdown(
                component=k, kind="mock", note="unknown",
            ))
            failures += 1
            continue
        df = _load_one_series(k, _start)
        if df is None:
            warnings.append(f"load failed: {k}")
            sources.append(SourceBreakdown(
                component=k, kind="mock", note="load failed",
            ))
            failures += 1
            continue
        points = _extract_points(df)
        if not points:
            warnings.append(f"empty series: {k}")
            sources.append(SourceBreakdown(
                component=k, kind="mock", note="empty",
            ))
            failures += 1
            continue
        sources.append(SourceBreakdown(component=k, kind="db"))
        series.append(MacroSeriesDTO(
            key=k,
            label=_LABEL.get(k, k),
            unit=_UNIT.get(k, "raw"),  # type: ignore[arg-type]
            points=points,
        ))

    if len(series) == 0:
        return MacroTimeseriesResponseDTO(
            meta=BaseMeta(
                as_of_date=None,
                source="mock",
                sources=sources,
                is_fallback=True,
                warnings=warnings or ["시계열 로딩 실패"],
                generated_at=datetime.now(timezone.utc),
            ),
            series=[],
        )

    meta_source = "mixed" if failures > 0 else "db"
    as_of_candidates = [s.points[-1].date_ for s in series if s.points]
    as_of: date | None = max(as_of_candidates) if as_of_candidates else None

    return MacroTimeseriesResponseDTO(
        meta=BaseMeta(
            as_of_date=as_of,
            source=meta_source,                 # type: ignore[arg-type]
            sources=sources,
            is_fallback=False,
            warnings=warnings,
            generated_at=datetime.now(timezone.utc),
        ),
        series=series,
    )
