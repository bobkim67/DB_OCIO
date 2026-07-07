from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from config.funds import FUND_BM, FUND_LIST, FUND_META

from ..schemas.meta import BaseMeta, SourceBreakdown
from ..schemas.overview import (
    FundInfoDTO,
    MetricCardDTO,
    NavPointDTO,
    OverviewResponseDTO,
    PeriodReturnsDTO,
    PeriodReturnsResponseDTO,
)


# -------------------- util --------------------

def _parse_yyyymmdd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _iso_to_yyyymmdd(s: str) -> str:
    return s.replace("-", "")


def _inception_base(fund_code: str) -> float:
    """설정후 분모 = 기준가 base 1000 (4JM12 등 승계펀드는 _FUND_INCEPTION_BASE, 절대 유지).

    설정일 첫 기준가 행에는 이미 1일차 손익이 반영돼 있어(≠1000, DD1_ERN_RT>0)
    첫 관측값을 분모로 쓰면 1일차 수익률이 누락된다 — DT 전산·stats '누적'(ref=1000)과
    일치하려면 base 1000 (2026-07-06 9펀드 전수 점검).
    """
    try:
        from modules.data_loader import _FUND_INCEPTION_BASE
    except ImportError:
        _FUND_INCEPTION_BASE = {}
    return _FUND_INCEPTION_BASE.get(fund_code, 1000.0)


# 설정후 BM 분모 override — 편입일 기준 펀드는 BM도 편입 전영업일 값 앵커.
# 07G07: KB투자풀 편입(2022-01-04) 전영업일 DT BM1(DWPM10041) 값.
_FUND_BM_INCEPTION_BASE = {'07G07': 999.55727568946}


# -------------------- BM load --------------------

def _load_bm_series(
    fund_code: str, start_date: str,
) -> tuple[pd.DataFrame | None, str | None]:
    """DT BM 우선 → SCIP composite fallback. (df, 'dt'|'scip') — 둘 다 실패 시 (None, None).

    소스 구분이 필요한 이유: DT BM 은 base 1000 절대지수라 설정후 분모=1000,
    SCIP composite 는 임의 리베이스라 첫 관측값 분모 유지.
    """
    # 1) DT BM
    try:
        from modules.data_loader import load_dt_bm_prices
        dt = load_dt_bm_prices(fund_code, start_date)
        if dt is not None and len(dt) > 0:
            return dt, "dt"
    except Exception:
        pass
    # 2) SCIP composite fallback
    bm_cfg = FUND_BM.get(fund_code)
    if not bm_cfg:
        return None, None
    try:
        from modules.data_loader import load_composite_bm_prices
        comp = load_composite_bm_prices(bm_cfg["components"], start_date)
        if comp is not None and len(comp) > 0:
            return comp, "scip"
    except Exception:
        pass
    return None, None


# -------------------- performance stats --------------------

# compute_full_performance_stats 반환 구조 (실측 기준):
#   { 'periods': { '누적': {annualized_return, annualized_risk, period_return, ...},
#                  '1M'/'3M'/'6M'/'1Y'/'YTD': {...} } }
_PERIOD_ALIAS_TO_DTO = {
    "누적": "SI",
    "1W": "1W",
    "MTD": "MTD",
    "1M": "1M",
    "3M": "3M",
    "6M": "6M",
    "1Y": "1Y",
    "YTD": "YTD",
}

# Redesign 기간 스트립: 1W·1M·3M·6M·YTD·SI. MTD·1Y 도 함께 산출.
# MTD/YTD 시작일 = 전월말/전년말 영업일(직전 영업일값) — _calc_ref_dates 가 처리(전산 일치).
_STATS_PERIODS = ["누적", "1W", "MTD", "1M", "3M", "6M", "1Y", "YTD"]


def _try_compute_stats(fund_code: str, end_date: date) -> dict[str, Any] | None:
    try:
        from modules.data_loader import compute_full_performance_stats
        return compute_full_performance_stats(
            fund_code, end_date.strftime("%Y%m%d"), periods=_STATS_PERIODS,
        )
    except Exception:
        return None


def _load_saa_series(
    fund_code: str, start_yyyymmdd: str, as_of: date | None,
) -> "pd.DataFrame | None":
    """BM-less 펀드용 SAA 시계열. 등록 SAA → proxy SAA → 복합지수 복원.

    load_composite_bm_prices 와 동일 포맷(기준일자, value) 반환 → BM 정렬 로직 재사용.
    """
    try:
        from modules.data_loader import (
            _build_proxy_bm_info,
            load_composite_bm_prices,
            load_saa_components,
        )
    except Exception:
        return None
    info = None
    try:
        info = load_saa_components(
            fund_code, as_of.strftime("%Y%m%d") if as_of else None,
        )
    except Exception:
        info = None
    if not info or not info.get("components"):
        try:
            info = _build_proxy_bm_info(fund_code, start_yyyymmdd)
        except Exception:
            info = None
    if not info or not info.get("components"):
        return None
    # 워밍업: 복합지수는 pct_change 로 첫날을 잃어 시작일이 설정일보다 하루 늦다.
    # NAV 설정일을 ffill 로 덮으려면 ~30일 앞에서 로드(서비스단 재rebase 라 절대레벨 무관).
    try:
        warm = (
            datetime.strptime(str(start_yyyymmdd), "%Y%m%d") - timedelta(days=30)
        ).strftime("%Y%m%d")
    except Exception:
        warm = start_yyyymmdd
    try:
        comp = load_composite_bm_prices(info["components"], warm)
        if comp is not None and len(comp) > 0:
            return comp
    except Exception:
        pass
    return None


def _weekly_vol(aligned: "pd.Series | None") -> float | None:
    """벤치마크 연환산 변동성 ≈ 주간(W-FRI) 수익률 std(ddof=1) × √52.

    bm_aligned 는 NAV 영업일에 ffill 정렬된 시계열. 포트 변동성(R 파이프라인)과
    방법이 미세하게 달라 정확 일치는 아니며 델타 표시용 근사값.
    """
    if aligned is None or len(aligned) < 3:
        return None
    s = aligned.dropna()
    if len(s) < 3:
        return None
    wk = s.resample("W-FRI").last().dropna()
    rets = wk.pct_change().dropna()
    if len(rets) < 2:
        return None
    v = float(rets.std(ddof=1) * np.sqrt(52))
    return None if np.isnan(v) else v


def _portfolio_equity_weight(fund_code: str) -> float | None:
    """포트 주식비중(국내+해외, look-through 최신 스냅샷). fraction(0~1) 반환."""
    try:
        from modules.data_loader import load_fund_holdings_lookthrough
        df = load_fund_holdings_lookthrough(fund_code)
        if df is None or len(df) == 0 or "자산군" not in df.columns:
            return None
        w = df[df["자산군"].isin(["국내주식", "해외주식"])]["비중(%)"].sum()
        return float(w) / 100.0
    except Exception:
        return None


def _benchmark_equity_weight(
    fund_code: str, kind: str, as_of: date | None, start_yyyymmdd: str,
) -> float | None:
    """벤치마크(BM/SAA) 주식비중 — 컴포넌트를 자산군 매핑(방법3)해 국내+해외주식 합. fraction."""
    comps = None
    if kind == "BM":
        from config.funds import FUND_BM
        info = FUND_BM.get(fund_code)
        comps = info.get("components") if info else None
    elif kind == "SAA":
        try:
            from modules.data_loader import (
                _build_proxy_bm_info,
                load_saa_components,
            )
            info = None
            try:
                info = load_saa_components(
                    fund_code, as_of.strftime("%Y%m%d") if as_of else None,
                )
            except Exception:
                info = None
            if not info or not info.get("components"):
                info = _build_proxy_bm_info(fund_code, start_yyyymmdd)
            comps = info.get("components") if info else None
        except Exception:
            comps = None
    if not comps:
        return None
    try:
        from modules.data_loader import _map_bm_component_to_asset_class
        eq = 0.0
        for c in comps:
            ac = _map_bm_component_to_asset_class(c["name"], "방법3")
            if ac in ("국내주식", "해외주식"):
                eq += float(c["weight"])
        return eq
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


def _compute_bm_period_returns(
    bm_aligned: pd.Series, si_base: float | None = None,
) -> PeriodReturnsDTO:
    """Streamlit tabs/overview.py:165-195 BM 기간수익률 로직 미러.

    bm_aligned: NAV dates에 ffill로 정렬된 BM 시계열 (DatetimeIndex).
    기간 = {1M, 3M, 6M, 1Y}는 relativedelta, YTD는 당해년 1/1, SI는 첫 값 기준.
    각 기간은 target 이전(<=) 마지막 영업일 값을 ref로 사용.
    si_base: SI(설정후) 분모 override — DT BM(base 1000 절대지수)은 1000을 넘겨
    설정일 당일 BM 등락 누락을 방지. None이면 기존대로 첫 값.
    """
    if bm_aligned is None or len(bm_aligned) == 0:
        return {}
    b0 = bm_aligned.iloc[0]
    end_v = bm_aligned.iloc[-1]
    if pd.isna(b0) or pd.isna(end_v) or float(b0) == 0:
        return {}
    end_dt = pd.Timestamp(bm_aligned.index[-1])
    # MTD: 전월말 영업일 시작(전산 일치) — target=월초-1일 → '<=' 조회가 전월말로 떨어짐.
    # YTD: 연초(1/1) target + '<=' → 1/1 휴장이라 전년말로 떨어짐(포트 _calc_ref_dates 와 동일).
    _month_start = pd.Timestamp(f"{end_dt.year}-{end_dt.month:02d}-01")
    targets = {
        "1W": end_dt - pd.Timedelta(days=7),
        "MTD": _month_start - pd.Timedelta(days=1),
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
    out["SI"] = float(end_v) / (float(si_base) if si_base else float(b0)) - 1.0
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
    base = _inception_base(fund_code)
    last_nav = float(nav_df["MOD_STPR"].iloc[-1])
    as_of_raw = nav_df["기준일자"].iloc[-1]
    as_of = as_of_raw.date() if hasattr(as_of_raw, "date") else as_of_raw

    # --- 2) 벤치마크 (BM 설정 펀드 → BM, 아니면 SAA[등록→proxy]) ---
    bm_aligned: pd.Series | None = None
    bm_first_val: float | None = None
    benchmark_kind: str = "none"
    benchmark_label: str | None = None
    bm_df: pd.DataFrame | None = None
    bm_src: str | None = None
    if bm_configured:
        benchmark_kind, benchmark_label = "BM", "BM"
        bm_df, bm_src = _load_bm_series(fund_code, _start)
        if bm_df is None or len(bm_df) == 0:
            warnings.append("BM 로딩 실패")
            sources.append(SourceBreakdown(
                component="bm", kind="mock", note="BM load failed",
            ))
    else:
        bm_df = _load_saa_series(fund_code, _start, as_of)
        if bm_df is not None and len(bm_df) > 0:
            benchmark_kind, benchmark_label = "SAA", "SAA"
        else:
            warnings.append("SAA 로딩 실패")
            sources.append(SourceBreakdown(
                component="bm", kind="mock", note="SAA load failed",
            ))

    if bm_df is not None and len(bm_df) > 0:
        if "value" not in bm_df.columns:
            warnings.append("벤치마크 컬럼 인식 실패")
            sources.append(SourceBreakdown(
                component="bm", kind="mock", note="value column missing",
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
                warnings.append("벤치마크 첫 값 결측 — 표시 생략")
                bm_aligned = None
                sources.append(SourceBreakdown(
                    component="bm", kind="mock", note="head missing",
                ))
            else:
                # DT BM은 base 1000 절대지수 — 설정일 행에 이미 1일차 등락이 반영돼
                # 있어(08K88 -0.70%) 첫 관측값 분모는 설정후를 +1.16%p 왜곡한다.
                # 편입일 기준 펀드(07G07)는 편입 전영업일 BM 값을 분모로 사용.
                bm_first_val = _FUND_BM_INCEPTION_BASE.get(fund_code) or (
                    1000.0 if bm_src == "dt" else float(_b0))
                sources.append(SourceBreakdown(component="bm", kind="db"))

    # --- 3) nav_series 조립 (bm/excess 채움) ---
    # T-1 합성 base 행 (R '기준가 T-1에 1000 추가' 동일 컨벤션): 설정일 행에는 이미
    # 1일차 손익이 반영돼 있어 첫 관측값 앵커는 1일차 수익률을 누락한다. 시리즈가
    # 설정일부터 시작할 때만 붙이며, 차트·윈도우 카드·엑셀 시계열이 이 행을 앵커로 사용.
    if _start == inc_str:
        _d0_raw = nav_df["기준일자"].iloc[0]
        _d0 = (_d0_raw.date() if hasattr(_d0_raw, "date") else _d0_raw) - timedelta(days=1)
        _bm0 = float(base) if (bm_aligned is not None and bm_first_val) else None
        nav_series_dto.append(NavPointDTO(
            date=_d0, nav=float(base), bm=_bm0,
            excess=0.0 if _bm0 is not None else None, aum=None,
        ))
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
                bm_v = float(bm_raw) / bm_first_val * base
                excess_v = (nav_v / base) - (float(bm_raw) / bm_first_val)
        aum_val = None
        if aum_col is not None:
            _a = aum_col.iloc[i]
            if _a is not None and not pd.isna(_a):
                aum_val = float(_a)
        nav_series_dto.append(NavPointDTO(
            date=d, nav=nav_v, bm=bm_v, excess=excess_v, aum=aum_val,
        ))

    # --- 4) cards ---
    # 4-1) since_inception: 분모=base(1000/승계 override) — stats '누적'(ref=1000)·DT 전산 정합
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
    # SI는 base 규약(1000/승계/편입 override)과 정합 — stats '누적'(ref=1000 고정)은
    # 4JM12(1970.76)·07G07(1019.50) 등 override 펀드에서 어긋난다.
    period_returns["SI"] = last_nav / base - 1.0

    # --- 5-bis) bm_period_returns (BM 설정 + 정렬 성공 시) ---
    if bm_aligned is not None and bm_first_val is not None:
        bm_period_returns = _compute_bm_period_returns(
            bm_aligned, si_base=bm_first_val,
        )

    # --- 5-ter) 펀드 기본정보 (메타바) + 운용수익 ---
    from config.funds import FUND_BENEFICIARY, FUND_TARGET_RETURN
    target_ann = FUND_TARGET_RETURN.get(fund_code)
    # 운용수익(보수차감후순) = 현재순자산 − 설정원본환산.
    #   설정원본환산 = 현재순자산 / (1+설정후수익률) = 현재순자산 × base/last_nav.
    #   → 운용수익 = 현재순자산 × (1 − base/last_nav). 자금 유출입 타이밍은 무시한 근사.
    operating_profit_krw: float | None = None
    fund_meta_dto: FundInfoDTO | None = None
    try:
        from modules.data_loader import load_fund_meta
        fm = load_fund_meta(fund_code)
        # 순자산(현재)은 최신 NAST_AMT.
        setup_amt = None
        current_nast = None
        if "NAST_AMT" in nav_df.columns:
            _first = nav_df["NAST_AMT"].iloc[0]
            _last = nav_df["NAST_AMT"].iloc[-1]
            if _first is not None and not pd.isna(_first):
                setup_amt = float(_first)        # fallback (DWPM12880 실패 시)
            if _last is not None and not pd.isna(_last):
                current_nast = float(_last)
        # 설정액 = 누적 순설정(설정−해지 누계, DWPM12880). 실패 시 첫 영업일 NAST.
        try:
            from modules.data_loader import _load_net_subscription
            _ns = _load_net_subscription(fund_code, inc_str)
            if _ns is not None and len(_ns):
                _tot = float(_ns["net_subscription"].sum())
                if _tot and not np.isnan(_tot):
                    setup_amt = _tot
        except Exception:
            pass
        # 운용수익(보수차감후순) = 현재순자산 × (1 − base/last_nav)
        if current_nast is not None and last_nav and base:
            operating_profit_krw = current_nast * (1.0 - base / last_nav)
        inc_meta = None
        if fm.get("inception"):
            try:
                inc_meta = _parse_yyyymmdd(fm["inception"])
            except Exception:
                inc_meta = None
        fund_meta_dto = FundInfoDTO(
            ticker=fm.get("ticker"),
            inception=inc_meta,
            setup_amount=setup_amt,
            fund_type=fm.get("fund_type"),
            manager=fm.get("manager"),
            fee_bp=fm.get("fee_bp"),
            nav=last_nav,
            beneficiary=FUND_BENEFICIARY.get(fund_code),
            target_return_annual=target_ann,
        )
    except Exception as exc:
        warnings.append(f"펀드 기본정보 로딩 실패: {type(exc).__name__}")

    # --- 5-quater) 변동성 (설정후/누적 + YTD) ---
    bm_vol = _weekly_vol(bm_aligned)
    vol_ytd = _stats_value(stats, "YTD", "annualized_risk")
    bm_vol_ytd = None
    if bm_aligned is not None and as_of is not None:
        _y0 = pd.Timestamp(f"{as_of.year}-01-01")
        bm_vol_ytd = _weekly_vol(bm_aligned[bm_aligned.index >= _y0])

    # --- 5-quinque) 주식비중 (포트 look-through vs 벤치마크 컴포넌트) ---
    equity_weight = _portfolio_equity_weight(fund_code)
    bm_equity_weight = _benchmark_equity_weight(
        fund_code, benchmark_kind, as_of, _start,
    )

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
        fund_meta=fund_meta_dto,
        benchmark_kind=benchmark_kind,        # type: ignore[arg-type]
        benchmark_label=benchmark_label,
        bm_volatility=bm_vol,
        operating_profit_krw=operating_profit_krw,
        volatility_ytd=vol_ytd,
        bm_volatility_ytd=bm_vol_ytd,
        equity_weight=equity_weight,
        bm_equity_weight=bm_equity_weight,
    )


# -------------------- period returns (end-date anchored) --------------------

@lru_cache(maxsize=256)
def _period_returns_cached(
    fund_code: str, end_yyyymmdd: str | None,
) -> PeriodReturnsResponseDTO:
    """조회 종료일 앵커 기간별 수익률 — build_overview 의 period/bm_period 로직만 경량 재사용.

    end_yyyymmdd 이하 마지막 영업일을 앵커로 compute_full_performance_stats(포트) +
    _compute_bm_period_returns(벤치)를 계산. end=None 이면 최신 영업일(기존 표와 동일).
    캐시 키 (fund, end) — end=최신일은 날짜가 바뀌면 새 키라 자연 갱신.
    """
    meta_f = FUND_META.get(fund_code, {})
    inc_str = meta_f.get("inception", "20220101")

    empty = PeriodReturnsResponseDTO(fund_code=fund_code)
    try:
        from modules.data_loader import load_fund_nav_with_aum
        nav_df = load_fund_nav_with_aum(fund_code, inc_str)
    except Exception:
        return empty
    if nav_df is None or len(nav_df) == 0:
        return empty
    nav_df = nav_df.sort_values("기준일자").reset_index(drop=True)
    nav_dates_all = pd.to_datetime(nav_df["기준일자"])
    if end_yyyymmdd:
        try:
            end_ts = pd.Timestamp(datetime.strptime(end_yyyymmdd, "%Y%m%d"))
        except ValueError:
            return empty
        nav_df = nav_df[nav_dates_all <= end_ts].reset_index(drop=True)
        if len(nav_df) == 0:
            return empty

    as_of_raw = nav_df["기준일자"].iloc[-1]
    as_of = as_of_raw.date() if hasattr(as_of_raw, "date") else as_of_raw

    # 포트 기간수익률 (앵커=as_of, R 파이프라인 재사용 — Overview 표와 동일 규약)
    stats = _try_compute_stats(fund_code, as_of)
    period_returns = _period_returns_from_stats(stats)
    # SI는 base 규약 정합 (build_overview 와 동일 — 승계/편입 override 반영)
    try:
        _last_nav = float(nav_df["MOD_STPR"].iloc[-1])
        period_returns["SI"] = _last_nav / _inception_base(fund_code) - 1.0
    except Exception:
        pass

    # 벤치(BM/SAA) 기간수익률 — build_overview 와 동일 로드 경로, NAV(≤end) 날짜에 정렬
    benchmark_kind: str = "none"
    benchmark_label: str | None = None
    bm_period_returns: PeriodReturnsDTO = {}
    bm_src: str | None = None
    if fund_code in FUND_BM:
        benchmark_kind, benchmark_label = "BM", "BM"
        bm_df, bm_src = _load_bm_series(fund_code, inc_str)
    else:
        bm_df = _load_saa_series(fund_code, inc_str, as_of)
        if bm_df is not None and len(bm_df) > 0:
            benchmark_kind, benchmark_label = "SAA", "SAA"
    if bm_df is not None and len(bm_df) > 0 and "value" in bm_df.columns:
        bm_df = bm_df.sort_values("기준일자").reset_index(drop=True)
        bm_series = pd.Series(
            bm_df["value"].astype(float).values,
            index=pd.to_datetime(bm_df["기준일자"]),
        )
        nav_dates = pd.to_datetime(nav_df["기준일자"])
        bm_aligned = bm_series.reindex(nav_dates, method="ffill")
        _b0 = bm_aligned.iloc[0]
        if not (pd.isna(_b0) or _b0 == 0):
            _si_base = _FUND_BM_INCEPTION_BASE.get(fund_code) or (
                1000.0 if bm_src == "dt" else None)
            bm_period_returns = _compute_bm_period_returns(
                bm_aligned, si_base=_si_base,
            )

    return PeriodReturnsResponseDTO(
        fund_code=fund_code,
        end_date=as_of,
        benchmark_kind=benchmark_kind,   # type: ignore[arg-type]
        benchmark_label=benchmark_label,
        period_returns=period_returns,
        bm_period_returns=bm_period_returns,
    )


def build_period_returns(
    fund_code: str, end_date: str | None = None,
) -> PeriodReturnsResponseDTO:
    """GET /funds/{code}/period-returns — end_date(YYYY-MM-DD) 앵커 기간별 수익률."""
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)
    end_key = _iso_to_yyyymmdd(end_date) if end_date else None
    return _period_returns_cached(fund_code, end_key)
