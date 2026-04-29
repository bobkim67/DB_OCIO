from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from config.funds import FUND_BM, FUND_LIST, FUND_META

from ..schemas.meta import BaseMeta, SourceBreakdown
from ..schemas.overview import (
    MetricCardDTO,
    NavPointDTO,
    OverviewResponseDTO,
    PeriodReturnsDTO,
)


# -------------------- util --------------------

def _parse_yyyymmdd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _iso_to_yyyymmdd(s: str) -> str:
    return s.replace("-", "")


def _inception_base(fund_code: str, first_nav: float) -> float:
    """4JM12 등 _FUND_INCEPTION_BASE 보정 (Week 1에서 이식, 절대 유지)."""
    try:
        from modules.data_loader import _FUND_INCEPTION_BASE
    except ImportError:
        _FUND_INCEPTION_BASE = {}
    return _FUND_INCEPTION_BASE.get(fund_code, first_nav)


# -------------------- BM load --------------------

def _load_bm_series(fund_code: str, start_date: str) -> pd.DataFrame | None:
    """DT BM 우선 → SCIP composite fallback. 둘 다 실패 시 None."""
    # 1) DT BM
    try:
        from modules.data_loader import load_dt_bm_prices
        dt = load_dt_bm_prices(fund_code, start_date)
        if dt is not None and len(dt) > 0:
            return dt
    except Exception:
        pass
    # 2) SCIP composite fallback
    bm_cfg = FUND_BM.get(fund_code)
    if not bm_cfg:
        return None
    try:
        from modules.data_loader import load_composite_bm_prices
        comp = load_composite_bm_prices(bm_cfg["components"], start_date)
        if comp is not None and len(comp) > 0:
            return comp
    except Exception:
        pass
    return None


# -------------------- performance stats --------------------

# compute_full_performance_stats 반환 구조 (실측 기준):
#   { 'periods': { '누적': {annualized_return, annualized_risk, period_return, ...},
#                  '1M'/'3M'/'6M'/'1Y'/'YTD': {...} } }
_PERIOD_ALIAS_TO_DTO = {
    "누적": "SI",
    "1M": "1M",
    "3M": "3M",
    "6M": "6M",
    "1Y": "1Y",
    "YTD": "YTD",
}


def _try_compute_stats(fund_code: str, end_date: date) -> dict[str, Any] | None:
    try:
        from modules.data_loader import compute_full_performance_stats
        return compute_full_performance_stats(
            fund_code, end_date.strftime("%Y%m%d"),
        )
    except Exception:
        return None


def _period_returns_from_stats(
    stats: dict[str, Any] | None,
) -> PeriodReturnsDTO:
    """stats['periods'][<label>]['period_return'] → DTO keys"""
    if not stats or not isinstance(stats.get("periods"), dict):
        return {}
    out: PeriodReturnsDTO = {}
    for label, dto_key in _PERIOD_ALIAS_TO_DTO.items():
        p = stats["periods"].get(label)
        if not isinstance(p, dict):
            continue
        v = p.get("period_return")
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        out[dto_key] = float(v)
    return out


def _stats_value(
    stats: dict[str, Any] | None, period: str, field: str,
) -> float | None:
    if not stats or not isinstance(stats.get("periods"), dict):
        return None
    p = stats["periods"].get(period)
    if not isinstance(p, dict):
        return None
    v = p.get(field)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return float(v)


def _compute_bm_period_returns(bm_aligned: pd.Series) -> PeriodReturnsDTO:
    """Streamlit tabs/overview.py:165-195 BM 기간수익률 로직 미러.

    bm_aligned: NAV dates에 ffill로 정렬된 BM 시계열 (DatetimeIndex).
    기간 = {1M, 3M, 6M, 1Y}는 relativedelta, YTD는 당해년 1/1, SI는 첫 값 기준.
    각 기간은 target 이전(<=) 마지막 영업일 값을 ref로 사용.
    """
    if bm_aligned is None or len(bm_aligned) == 0:
        return {}
    b0 = bm_aligned.iloc[0]
    end_v = bm_aligned.iloc[-1]
    if pd.isna(b0) or pd.isna(end_v) or float(b0) == 0:
        return {}
    end_dt = pd.Timestamp(bm_aligned.index[-1])
    targets = {
        "1M": end_dt - relativedelta(months=1),
        "3M": end_dt - relativedelta(months=3),
        "6M": end_dt - relativedelta(months=6),
        "1Y": end_dt - relativedelta(years=1),
        "YTD": pd.Timestamp(f"{end_dt.year}-01-01"),
    }
    idx = bm_aligned.index
    arr = bm_aligned.to_numpy(dtype=float)
    out: PeriodReturnsDTO = {}
    for key, target in targets.items():
        mask = idx <= target
        if not mask.any():
            continue
        pos = int(np.where(mask)[0][-1])
        ref_v = arr[pos]
        if np.isnan(ref_v) or ref_v == 0:
            continue
        out[key] = float(end_v) / float(ref_v) - 1.0
    out["SI"] = float(end_v) / float(b0) - 1.0
    return out


def _compute_mdd_from_nav(nav_series: pd.Series) -> float | None:
    """MDD = min(nav / cummax(nav) - 1). Streamlit tabs/overview.py:264-281 동일."""
    if nav_series is None or len(nav_series) == 0:
        return None
    arr = nav_series.astype(float).to_numpy()
    running_max = np.maximum.accumulate(arr)
    with np.errstate(invalid="ignore", divide="ignore"):
        drawdown = arr / running_max - 1.0
    if len(drawdown) == 0:
        return None
    m = float(np.min(drawdown))
    if np.isnan(m):
        return None
    return m


# -------------------- main --------------------

def build_overview(
    fund_code: str, start_date: str | None = None,
) -> OverviewResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)

    meta_f = FUND_META.get(fund_code, {})
    inc_str = meta_f.get("inception", "20220101")
    _start = _iso_to_yyyymmdd(start_date) if start_date else inc_str

    warnings: list[str] = []
    sources: list[SourceBreakdown] = []
    nav_series_dto: list[NavPointDTO] = []
    cards: list[MetricCardDTO] = []
    period_returns: PeriodReturnsDTO = {}
    bm_period_returns: PeriodReturnsDTO = {}
    as_of: date | None = None
    bm_configured = fund_code in FUND_BM

    # --- 1) NAV ---
    try:
        from modules.data_loader import load_fund_nav_with_aum
        nav_df = load_fund_nav_with_aum(fund_code, _start)
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")
        nav_df = None

    if nav_df is None or len(nav_df) == 0:
        return OverviewResponseDTO(
            meta=BaseMeta(
                as_of_date=None,
                source="mock",
                sources=[],
                is_fallback=True,
                warnings=warnings or ["NAV 데이터 없음"],
                generated_at=datetime.now(timezone.utc),
            ),
            fund_code=fund_code,
            fund_name=meta_f.get("name", fund_code),
            inception_date=_parse_yyyymmdd(inc_str),
            bm_configured=bm_configured,
            cards=[],
            nav_series=[],
            period_returns={},
            bm_period_returns={},
        )

    sources.append(SourceBreakdown(component="nav", kind="db"))
    nav_df = nav_df.sort_values("기준일자").reset_index(drop=True)
    first_nav = float(nav_df["MOD_STPR"].iloc[0])
    base = _inception_base(fund_code, first_nav)
    last_nav = float(nav_df["MOD_STPR"].iloc[-1])
    as_of_raw = nav_df["기준일자"].iloc[-1]
    as_of = as_of_raw.date() if hasattr(as_of_raw, "date") else as_of_raw

    # --- 2) BM (BM 설정된 펀드만 시도) ---
    bm_aligned: pd.Series | None = None
    bm_first_val: float | None = None
    if bm_configured:
        bm_df = _load_bm_series(fund_code, _start)
        if bm_df is None or len(bm_df) == 0:
            warnings.append("BM 로딩 실패")
            sources.append(SourceBreakdown(
                component="bm", kind="mock", note="BM load failed",
            ))
        else:
            if "value" not in bm_df.columns:
                warnings.append("BM 컬럼 인식 실패")
                sources.append(SourceBreakdown(
                    component="bm", kind="mock", note="BM column missing",
                ))
            else:
                bm_df = bm_df.sort_values("기준일자").reset_index(drop=True)
                bm_series = pd.Series(
                    bm_df["value"].astype(float).values,
                    index=pd.to_datetime(bm_df["기준일자"]),
                )
                nav_dates = pd.to_datetime(nav_df["기준일자"])
                bm_aligned = bm_series.reindex(nav_dates, method="ffill")
                # 첫 값 결측 체크
                _b0 = bm_aligned.iloc[0]
                if pd.isna(_b0) or _b0 == 0:
                    warnings.append("BM 첫 값 결측 — BM 표시 생략")
                    bm_aligned = None
                    # sources는 db로 유지하지 않고 mock로 기록
                    sources.append(SourceBreakdown(
                        component="bm", kind="mock", note="BM head missing",
                    ))
                else:
                    bm_first_val = float(_b0)
                    sources.append(SourceBreakdown(component="bm", kind="db"))

    # --- 3) nav_series 조립 (bm/excess 채움) ---
    nav_arr = nav_df["MOD_STPR"].astype(float).to_numpy()
    aum_col = nav_df["NAST_AMT"] if "NAST_AMT" in nav_df.columns else None
    for i in range(len(nav_df)):
        d_raw = nav_df["기준일자"].iloc[i]
        d = d_raw.date() if hasattr(d_raw, "date") else d_raw
        nav_v = float(nav_arr[i])
        bm_v: float | None = None
        excess_v: float | None = None
        if bm_aligned is not None and bm_first_val:
            bm_raw = bm_aligned.iloc[i]
            if not pd.isna(bm_raw):
                bm_v = float(bm_raw) / bm_first_val * first_nav
                excess_v = (nav_v / first_nav) - (float(bm_raw) / bm_first_val)
        aum_val = None
        if aum_col is not None:
            _a = aum_col.iloc[i]
            if _a is not None and not pd.isna(_a):
                aum_val = float(_a)
        nav_series_dto.append(NavPointDTO(
            date=d, nav=nav_v, bm=bm_v, excess=excess_v, aum=aum_val,
        ))

    # --- 4) cards ---
    # 4-1) since_inception: Week 1 로직(base 보정) 유지
    cards.append(MetricCardDTO(
        key="since_inception", label="설정후",
        value=last_nav / base - 1.0, unit="pct",
    ))
    # 4-2) YTD / vol: compute_full_performance_stats 재사용
    stats = _try_compute_stats(fund_code, as_of)
    if stats is None:
        warnings.append("성과 통계 계산 실패 — YTD/변동성 생략")
    else:
        ytd_v = _stats_value(stats, "YTD", "period_return")
        if ytd_v is not None:
            cards.append(MetricCardDTO(
                key="ytd", label="YTD", value=ytd_v, unit="pct",
            ))
        vol_v = _stats_value(stats, "누적", "annualized_risk")
        if vol_v is not None:
            cards.append(MetricCardDTO(
                key="vol", label="변동성", value=vol_v, unit="pct",
            ))
    # 4-3) MDD: NAV 기반 직접 계산 (Streamlit tabs/overview.py:264-281 동일 공식)
    mdd_v = _compute_mdd_from_nav(nav_df["MOD_STPR"])
    if mdd_v is not None:
        cards.append(MetricCardDTO(
            key="mdd", label="MDD", value=mdd_v, unit="pct",
        ))

    # --- 5) period_returns (포트) ---
    period_returns = _period_returns_from_stats(stats)

    # --- 5-bis) bm_period_returns (BM 설정 + 정렬 성공 시) ---
    if bm_aligned is not None and bm_first_val is not None:
        bm_period_returns = _compute_bm_period_returns(bm_aligned)

    # --- 6) meta.source 결정 ---
    bm_mock_present = any(
        s.component == "bm" and s.kind != "db" for s in sources
    )
    if bm_mock_present:
        meta_source: str = "mixed"
    else:
        meta_source = "db"

    return OverviewResponseDTO(
        meta=BaseMeta(
            as_of_date=as_of,
            source=meta_source,          # type: ignore[arg-type]
            sources=sources,
            is_fallback=False,
            warnings=warnings,
            generated_at=datetime.now(timezone.utc),
        ),
        fund_code=fund_code,
        fund_name=meta_f.get("name", fund_code),
        inception_date=_parse_yyyymmdd(inc_str),
        bm_configured=bm_configured,
        cards=cards,
        nav_series=nav_series_dto,
        period_returns=period_returns,
        bm_period_returns=bm_period_returns,
    )
