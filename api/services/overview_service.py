from datetime import date, datetime, timezone

from config.funds import FUND_BM, FUND_LIST, FUND_META

from ..schemas.meta import BaseMeta, SourceBreakdown
from ..schemas.overview import MetricCardDTO, NavPointDTO, OverviewResponseDTO


def _parse_yyyymmdd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _iso_to_yyyymmdd(s: str) -> str:
    return s.replace("-", "")


def _inception_base(fund_code: str, first_nav: float) -> float:
    """4JM12 등 _FUND_INCEPTION_BASE 보정.

    Streamlit(`tabs/overview.py`)과 동일하게 시스템 기준가 사용.
    다른 펀드는 nav_series[0]의 값(=설정일 기준가) 그대로.
    """
    try:
        from modules.data_loader import _FUND_INCEPTION_BASE
    except ImportError:
        _FUND_INCEPTION_BASE = {}
    return _FUND_INCEPTION_BASE.get(fund_code, first_nav)


def build_overview(fund_code: str, start_date: str | None = None) -> OverviewResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)

    meta_f = FUND_META.get(fund_code, {})
    inc_str = meta_f.get("inception", "20220101")
    _start = _iso_to_yyyymmdd(start_date) if start_date else inc_str

    warnings: list[str] = []
    is_fallback = False
    source = "db"
    sources: list[SourceBreakdown] = []
    nav_series: list[NavPointDTO] = []
    cards: list[MetricCardDTO] = []
    as_of: date | None = None

    try:
        from modules.data_loader import load_fund_nav_with_aum
        nav_df = load_fund_nav_with_aum(fund_code, _start)
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")
        nav_df = None

    if nav_df is None or len(nav_df) == 0:
        is_fallback = True
        source = "mock"
        if not warnings:
            warnings.append("NAV 데이터 없음")
    else:
        sources.append(SourceBreakdown(component="nav", kind="db"))
        for _, row in nav_df.iterrows():
            d_raw = row["기준일자"]
            d = d_raw.date() if hasattr(d_raw, "date") else d_raw
            aum_val = row.get("NAST_AMT")
            nav_series.append(NavPointDTO(
                date=d,
                nav=float(row["MOD_STPR"]),
                aum=float(aum_val) if aum_val is not None else None,
            ))
        if nav_series:
            as_of = nav_series[-1].date_
            base = _inception_base(fund_code, nav_series[0].nav)
            last_nav = nav_series[-1].nav
            cards.append(MetricCardDTO(
                key="since_inception",
                label="설정후",
                value=last_nav / base - 1.0,
                unit="pct",
            ))

    return OverviewResponseDTO(
        meta=BaseMeta(
            as_of_date=as_of,
            source=source,
            sources=sources,
            is_fallback=is_fallback,
            warnings=warnings,
            generated_at=datetime.now(timezone.utc),
        ),
        fund_code=fund_code,
        fund_name=meta_f.get("name", fund_code),
        inception_date=_parse_yyyymmdd(inc_str),
        bm_configured=fund_code in FUND_BM,
        cards=cards,
        nav_series=nav_series,
    )
