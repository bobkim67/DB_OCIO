import json
import os
import threading
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from config.funds import FUND_LIST, FUND_META

from ..schemas.holdings import (
    ComplianceItemDTO,
    EquityFocusDTO,
    EquityHoldingDTO,
    EquityProxyRefDTO,
    FxHedgeSummaryDTO,
    HoldingAssetClassDTO,
    HoldingItemDTO,
    HoldingsResponseDTO,
    PortfolioMixSummaryDTO,
    WeightedDurationDTO,
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


# 종목코드 기반 식별 (사용자 합의, 2026-05-28).
_GOLD_ITEM_CDS = {
    "KR7411060007",   # ACE KRX금현물
    "US92189F1066",   # VanEck Gold Miners (GDX)
    "US46436F1030",   # iShares Gold Micro (IAUM)
}
_USHY_ITEM_CDS = {
    "US46435U8532",   # iShares Broad USD High Yield (USHY 본 ETF)
    "KR7468380001",   # KODEX iShares 미국하이일드액티브
}
_EM_BOND_ITEM_CDS = {"US9219468850"}  # VWOB (Vanguard EM Government Bond, 신흥국채권)
_CASH_USD_DEPOSIT_CDS = {"USMUSD022001"}
_EQUITY_ACS = {"국내주식", "해외주식"}
_BOND_ACS = {"국내채권", "해외채권"}


def _is_gold_item(it: HoldingItemDTO) -> bool:
    return it.item_cd.upper() in _GOLD_ITEM_CDS


def _is_ushy_item(it: HoldingItemDTO) -> bool:
    return it.item_cd.upper() in _USHY_ITEM_CDS


def _is_em_bond_item(it: HoldingItemDTO) -> bool:
    """신흥국채권(VWOB 등). data_loader._is_risk_bond 와 동일 식별."""
    if it.item_cd.upper() in _EM_BOND_ITEM_CDS:
        return True
    u = (it.item_nm or "").upper()
    return "EMERGING" in u or "VWOB" in u


def _is_cash_item(it: HoldingItemDTO) -> bool:
    """USD Deposit 종목코드 OR item_nm에 '예금' 포함."""
    if it.item_cd.upper() in _CASH_USD_DEPOSIT_CDS:
        return True
    return "예금" in (it.item_nm or "")


def _build_portfolio_mix(items: list[HoldingItemDTO]) -> PortfolioMixSummaryDTO:
    # 합집합 가산 — GDX 등 해외주식 ACS에 이미 들어간 금 종목 이중계산 방지.
    equity_w = sum(
        it.weight for it in items
        if it.asset_class in _EQUITY_ACS or _is_gold_item(it)
    )
    bond_w = sum(it.weight for it in items if it.asset_class in _BOND_ACS)
    risk_w = sum(
        it.weight for it in items
        if it.asset_class in _EQUITY_ACS
        or _is_gold_item(it)
        or _is_ushy_item(it)
    )
    cash_items = [it for it in items if _is_cash_item(it)]
    cash_w = sum(it.weight for it in cash_items)
    cash_amt = sum(it.evl_amt for it in cash_items)
    return PortfolioMixSummaryDTO(
        equity_weight=equity_w,
        bond_weight=bond_w,
        risk_asset_weight=risk_w,
        cash_weight=cash_w,
        cash_amount=cash_amt,
    )


def _build_equity_focus(items: list[HoldingItemDTO]) -> EquityFocusDTO:
    """주식(국내+해외) 보유 → proxy PER/EPS성장 매핑 + 가중집계 + 틸트. (금 제외)"""
    from modules.data_loader import (
        _classify_equity_proxy,
        load_equity_proxy_valuations,
    )
    try:
        vals = load_equity_proxy_valuations()
    except Exception:
        vals = {}
    eq_items = [it for it in items if it.asset_class in _EQUITY_ACS]
    tot_w = sum(it.weight for it in eq_items)
    holdings: list[EquityHoldingDTO] = []
    per_num = gr_num = per_cov = gr_cov = 0.0
    region = {"국내": 0.0, "해외": 0.0}
    style = {"성장": 0.0, "가치": 0.0, "기타": 0.0}
    for it in eq_items:
        tk = _classify_equity_proxy(it.item_cd, it.item_nm, it.asset_class)
        v = vals.get(tk, {}) if tk else {}
        per, gr = v.get("per"), v.get("eps_growth")
        holdings.append(EquityHoldingDTO(
            item_nm=it.item_nm, asset_class=it.asset_class, weight=it.weight,
            proxy_ticker=tk, per=per, eps_growth=gr,
        ))
        if per is not None:
            per_num += it.weight * per; per_cov += it.weight
        if gr is not None:
            gr_num += it.weight * gr; gr_cov += it.weight
        region["국내" if it.asset_class == "국내주식" else "해외"] += it.weight
        nm = (it.item_nm or "").upper()
        sk = "성장" if ("성장" in nm or "GROWTH" in nm) else (
            "가치" if ("가치" in nm or "VALUE" in nm) else "기타")
        style[sk] += it.weight
    refs = [
        EquityProxyRefDTO(ticker=tk, per=v.get("per"), eps_growth=v.get("eps_growth"))
        for tk, v in vals.items()
    ]
    return EquityFocusDTO(
        equity_weight=tot_w,
        weighted_per=(per_num / per_cov) if per_cov > 0 else None,
        weighted_eps_growth=(gr_num / gr_cov) if gr_cov > 0 else None,
        holdings=holdings, references=refs,
        region_tilt=region, style_tilt=style,
    )


def _risk_excl_safe(items: list[HoldingItemDTO]) -> float:
    """위험자산 = 안전자산(국내채권+유동성) 외 전부 (사용자 확정)."""
    return sum(it.weight for it in items if it.asset_class not in ("국내채권", "유동성"))


def _liquidity_weight(items: list[HoldingItemDTO]) -> float:
    """유동성 자산군 비중 (현금·미수금 잔여 포함). 컴플 '유동성' 기준."""
    return sum(it.weight for it in items if it.asset_class == "유동성")


def _ci(key: str, label: str, value: float,
        low: float | None = None, high: float | None = None) -> ComplianceItemDTO:
    if low is None and high is None:
        status = "none"
    elif (high is not None and value > high) or (low is not None and value < low):
        status = "breach"
    elif (high is not None and value > high * 0.97) or (low is not None and value < low * 1.03):
        status = "warn"
    else:
        status = "ok"
    return ComplianceItemDTO(key=key, label=label, value=value,
                             band_low=low, band_high=high, status=status)


def _subfund_metrics(fund_code: str) -> dict | None:
    """하위펀드 단독 보유(EVL 비중) → {equity, risk}. 07G04 의 ISP/RSP 한도용.

    equity = 주식+금(_build_portfolio_mix), risk = 안전자산 외 전부.
    """
    try:
        df = _load_holdings_df(fund_code, None, lookthrough=False)
    except Exception:
        return None
    if df is None or len(df) == 0 or "EVL_AMT" not in df.columns:
        return None
    tot = float(df["EVL_AMT"].sum())
    if tot <= 0:
        return None
    items: list[HoldingItemDTO] = []
    for _, row in df.iterrows():
        evl = _val(row, "EVL_AMT")
        if evl is None:
            continue
        try:
            evl_f = float(evl)
        except (TypeError, ValueError):
            continue
        cd = str(_val(row, "ITEM_CD", default=""))
        nm = str(_val(row, "ITEM_NM", default=""))
        ac = _reclassify_fx_deposit(
            cd, nm, str(_val(row, "자산군", "AST_CLSF_CD_NM", default="기타")))
        items.append(HoldingItemDTO(
            item_cd=cd, item_nm=nm, asset_class=ac,
            weight=evl_f / tot, evl_amt=evl_f,
        ))
    return {
        "equity": _build_portfolio_mix(items).equity_weight,
        "risk": _risk_excl_safe(items),
    }


def _build_compliance(
    fund_code: str, items: list[HoldingItemDTO],
    mix: PortfolioMixSummaryDTO, fx_hedge: FxHedgeSummaryDTO | None,
) -> list[ComplianceItemDTO]:
    """펀드별 실제 가이드라인 (2026-06-24 사용자 제공)."""
    rows: list[ComplianceItemDTO] = []
    risk = _risk_excl_safe(items)   # 위험자산 = 안전자산(국내채권+유동성) 외 전부
    liq = _liquidity_weight(items)  # 유동성 자산군(현금·미수금 포함)

    if fund_code == "08K88":
        rows.append(_ci("risk_asset", "위험자산", risk, high=0.92))

    elif fund_code == "2JM23":
        # 위험자산 ≤80% (= 안전자산 ≥20% 동치, 타 펀드와 표기 일관성)
        rows.append(_ci("risk_asset", "위험자산", risk, high=0.80))
        rows.append(_ci("cash", "유동성", liq, low=0.02))

    elif fund_code == "4JM12":
        # 위험자산 ≤50% (= 안전자산 ≥50% 동치, 타 펀드와 표기 일관성)
        rows.append(_ci("risk_asset", "위험자산", risk, high=0.50))
        rows.append(_ci("cash", "유동성", liq, low=0.05))
        # 환헤지 한도(사용자 정의 2026-06-29): USD 매도포지션(절대 NAV비중) ≤ 해외자산비중 + 10%p.
        # 예) 해외자산 50% → 매도 60%까지 허용. (구 ratio 1.10 고정 폐기)
        if fx_hedge:
            short_w = fx_hedge.usd_short_weight
            limit = fx_hedge.usd_asset_weight + 0.10
            r = _ci("hedge", "환헤지(USD매도포지션)", short_w, high=limit)
            r.breakdown = "해외자산+10%p"
            rows.append(r)

    elif fund_code == "07G04":
        for sub, nm, eq_lim, risk_lim in [
            ("07G02", "ISP", 0.20, 0.20), ("07G03", "RSP", 0.55, 0.70),
        ]:
            m = _subfund_metrics(sub)
            if m is None:
                continue
            rows.append(_ci(f"{sub}_eq", f"{nm} 주식비중", m["equity"], high=eq_lim))
            rows.append(_ci(f"{sub}_risk", f"{nm} 위험자산", m["risk"], high=risk_lim))

    elif fund_code in ("08N33", "08N81", "08P22"):
        # SAA 펀드 = 위반 판정 없이 현재 비중 vs SAA 목표 고지(비교용) only.
        # SAA는 중립배분 기준선이라 상·하한 한도가 아님 → status="none",
        # band_high 에 SAA 목표를 실어 프론트에서 참고 마커로 렌더.
        from config.funds import FUND_MP_DIRECT
        mp = FUND_MP_DIRECT.get(fund_code, {})
        t_eq = (mp.get("국내주식", 0) + mp.get("해외주식", 0) + mp.get("대체투자", 0)) / 100.0
        t_risk = sum(
            mp.get(k, 0) for k in mp if k not in ("국내채권", "유동성")
        ) / 100.0
        rows.append(ComplianceItemDTO(
            key="equity", label="주식비중", value=mix.equity_weight,
            band_low=None, band_high=t_eq, status="none"))
        rows.append(ComplianceItemDTO(
            key="risk_asset", label="위험자산", value=risk,
            band_low=None, band_high=t_risk, status="none"))

    # 라벨 구성 표기: 금이 편입돼 있을 때만 (사용자 지정 2026-06-29).
    #  주식비중 = 주식 + 금 / 위험자산 = 주식 + 금 + 하이일드(없고 신흥국채권 있으면 신흥국채권)
    has_gold = any(_is_gold_item(it) for it in items)
    if has_gold:
        has_ushy = any(_is_ushy_item(it) for it in items)
        has_em = any(_is_em_bond_item(it) for it in items)
        risk_parts = ["주식", "금"]
        if has_em:
            risk_parts.append("신흥국채권")
        elif has_ushy:
            risk_parts.append("하이일드")
        eq_bd = "주식 + 금"
        risk_bd = " + ".join(risk_parts)
        for r in rows:
            if r.key == "equity" or r.key.endswith("_eq"):
                r.breakdown = eq_bd
            elif r.key == "risk_asset" or r.key.endswith("_risk"):
                r.breakdown = risk_bd

    return rows


def _reclassify_fx_deposit(item_cd: str, item_nm: str, ac: str) -> str:
    """FX 자산군에 포획된 외화예치금(USD DEPOSIT/CALL 등)을 유동성으로 되돌림.

    data_loader의 FX 오버레이가 '외화' 키워드로 예치금을 끌어가는 문제 우회.
    재분류 대상: FX 자산군 + (ITEM_CD='USMUSD022001' OR ITEM_NM에 DEPOSIT/CALL).
    """
    if ac != "FX":
        return ac
    nm = (item_nm or "").upper()
    cd = (item_cd or "").upper()
    if cd == "USMUSD022001" or "DEPOSIT" in nm or nm.endswith(" CALL"):
        return "유동성"
    return ac


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


def _load_opng(fund_code: str, as_of: date | None) -> float | None:
    """해당 기준일의 OPNG_AMT (펀드 설정금액). DWPM10510 직접 쿼리."""
    if as_of is None:
        return None
    try:
        from modules.data_loader import get_connection
        std_dt = int(as_of.strftime("%Y%m%d"))
        conn = get_connection("dt")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT OPNG_AMT FROM DWPM10510 "
                    "WHERE FUND_CD = %s AND STD_DT = %s LIMIT 1",
                    (fund_code, std_dt),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                v = row.get("OPNG_AMT") if isinstance(row, dict) else row[0]
                if v is None:
                    return None
                f = float(v)
                return f if f > 0 else None
        finally:
            conn.close()
    except Exception:
        return None


_FIRST_DATE_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".cache", "holdings_first_dates.json",
)
_first_date_lock = threading.Lock()
_first_date_cache: dict[str, dict[str, str | None]] | None = None


def _first_date_store() -> dict[str, dict[str, str | None]]:
    global _first_date_cache
    if _first_date_cache is None:
        try:
            with open(_FIRST_DATE_CACHE_PATH, encoding="utf-8") as fp:
                _first_date_cache = json.load(fp)
        except Exception:
            _first_date_cache = {}
    return _first_date_cache


def _query_first_dates_db(fund_code: str, item_cds: list[str]) -> dict[str, str]:
    """DWPM10530 전이력 MIN(STD_DT) per ITEM_CD (현재 보유 ITEM_CD 한정)."""
    from modules.data_loader import _get_관련_fund_list, get_connection
    funds = _get_관련_fund_list(fund_code) or [fund_code]
    fph = ",".join(["%s"] * len(funds))
    iph = ",".join(["%s"] * len(item_cds))
    conn = get_connection("dt")
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT ITEM_CD, MIN(STD_DT) AS f FROM DWPM10530 "
                f"WHERE FUND_CD IN ({fph}) AND ITEM_CD IN ({iph}) "
                f"AND EVL_AMT > 0 GROUP BY ITEM_CD",
                tuple(funds) + tuple(item_cds),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    out: dict[str, str] = {}
    for row in rows:
        cd = row.get("ITEM_CD") if isinstance(row, dict) else row[0]
        f = row.get("f") if isinstance(row, dict) else row[1]
        if cd is None or f is None:
            continue
        s = str(f).strip()
        if len(s) == 8 and s.isdigit():
            out[str(cd)] = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return out


def _load_first_dates(fund_code: str, item_cds: list[str]) -> dict[str, str]:
    """ITEM_CD별 최초 편입일(YYYY-MM-DD). 정적 데이터라 영속 JSON 캐시.

    캐시 미스(신규 종목)만 DB 조회 → 캐시 갱신·저장. 전이력 GROUP BY 풀스캔(~7s)은
    펀드별 최초 1회만(이후 영구 instant). warmup_cli 가 build_holdings 호출로 선채움.
    """
    item_cds = [c for c in item_cds if c and not c.startswith("_")]
    if not item_cds:
        return {}
    store = _first_date_store()
    fund_cache = store.get(fund_code, {})
    missing = [c for c in item_cds if c not in fund_cache]
    if missing:
        try:
            fresh = _query_first_dates_db(fund_code, missing)
        except Exception:
            fresh = {}
        with _first_date_lock:
            fund_cache = dict(fund_cache)
            for c in missing:                 # 못 찾은 종목도 None 저장 → 재조회 방지
                fund_cache[c] = fresh.get(c)
            store[fund_code] = fund_cache
            try:
                os.makedirs(os.path.dirname(_FIRST_DATE_CACHE_PATH), exist_ok=True)
                with open(_FIRST_DATE_CACHE_PATH, "w", encoding="utf-8") as fp:
                    json.dump(store, fp, ensure_ascii=False)
            except Exception:
                pass
    return {c: fund_cache[c] for c in item_cds if fund_cache.get(c)}


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


def _resolve_as_of_from_db(fund_code: str, hint: str | None) -> date | None:
    """as_of hint(YYYYMMDD)가 있으면 그대로, 없으면 DWPM10530 최신 STD_DT 조회.

    lookthrough 경로의 DataFrame은 STD_DT/기준일자 컬럼이 유실되므로 NAST 매칭용 as_of
    확보를 위해 별도 경량 쿼리로 선행 resolve.
    """
    if hint:
        try:
            return pd.to_datetime(hint, format="%Y%m%d").date()
        except Exception:
            pass
    try:
        from modules.data_loader import get_connection
        conn = get_connection("dt")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(STD_DT) AS m FROM DWPM10530 WHERE FUND_CD = %s",
                    (fund_code,),
                )
                row = cur.fetchone()
                m = row.get("m") if isinstance(row, dict) else (row[0] if row else None)
                if m is None:
                    return None
                return pd.to_datetime(str(int(m)), format="%Y%m%d").date()
        finally:
            conn.close()
    except Exception:
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

    # as_of: 요청 or 최신(그대로). 환매 정산중(증권>NAST)이어도 표시 — 환매미지급금 라인(4.7)으로 균형.
    as_of_param = _iso_to_yyyymmdd(as_of_date) if as_of_date else None
    data_pending = False
    data_note: str | None = None

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

    # 2) as_of 확정 — df에서 우선 추출, 실패 시 DB로 fallback resolve
    #    (lookthrough 경로는 STD_DT/기준일자 컬럼이 유실되므로 fallback 필수)
    as_of = _extract_as_of(df) or _resolve_as_of_from_db(fund_code, as_of_param)

    # 3) NAST_AMT + OPNG_AMT
    nast = _load_nast(fund_code, as_of)
    opng = _load_opng(fund_code, as_of)
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
        item_cd_s = str(_val(row, "ITEM_CD", default=""))
        item_nm_s = str(_val(row, "ITEM_NM", default=""))
        ac_final = _reclassify_fx_deposit(item_cd_s, item_nm_s, str(ac_raw))
        pos_raw = _val(row, "POS_DS_CD", "pos_ds_cd", default="")
        is_short = "매도" in str(pos_raw)
        items.append(HoldingItemDTO(
            item_cd=item_cd_s,
            item_nm=item_nm_s,
            asset_class=ac_final,
            weight=weight,
            evl_amt=evl_f,
            sub_fund_cd=(
                str(_val(row, "SUB_FUND_CD", "sub_fund_cd"))
                if _val(row, "SUB_FUND_CD", "sub_fund_cd") is not None
                else None
            ),
            is_short=is_short,
        ))

    # 4.5) USD 노출/헷지 — FX 파생 포지션 제거 전에 산출 (4JM12 환헤지 게이지용)
    usd_asset_ac = {"해외주식", "해외채권", "대체투자"}
    usd_asset_w = sum(it.weight for it in items if it.asset_class in usd_asset_ac)
    usd_asset_w += sum(
        it.weight for it in items
        if it.asset_class == "유동성"
        and (it.item_cd.upper() == "USMUSD022001" or "DEPOSIT" in it.item_nm.upper())
    )
    usd_short_w = sum(
        it.weight for it in items if it.asset_class == "FX" and it.is_short
    )
    fx_hedge = FxHedgeSummaryDTO(
        usd_asset_weight=usd_asset_w,
        usd_short_weight=usd_short_w,
        hedge_ratio=(usd_short_w / usd_asset_w) if usd_asset_w > 0 else None,
    )

    # 4.6) FX(달러선물 등)는 포지션(notional)이지 NAV 구성이 아니므로 제외 (2026-06-24 사용자 확정)
    items = [it for it in items if it.asset_class != "FX"]

    # 4.7) 현금잔여 = NAST − Σ보유증권. 양수=현금·미수금(DWPM10530 미포함분), 음수=환매미지급금.
    #   환매 등 정산중엔 미지급금이 NAST에서만 차감(증권 미매도)돼 Σ증권>NAST → 음수 유동성 라인으로
    #   100% 균형 유지 + '환매미지급금' 별도 표기(결제일에 증권 매도로 청산). (2026-06-26 사용자 확정)
    if nast and nast > 0 and denom == nast:
        resid = nast - sum(it.evl_amt for it in items)
        if resid > nast * 0.005:
            items.append(HoldingItemDTO(
                item_cd="_CASH_RESIDUAL_", item_nm="현금·미수금",
                asset_class="유동성", weight=resid / nast, evl_amt=resid,
            ))
        elif resid < -nast * 0.005:
            items.append(HoldingItemDTO(
                item_cd="_REDEMPTION_PAYABLE_", item_nm="환매미지급금",
                asset_class="유동성", weight=resid / nast, evl_amt=resid,
            ))
            data_pending = True
            data_note = "환매 정산중 — 미지급금 반영(증권평가>순자산)"

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

    # 8) 가중평균 듀레이션 + 종목별 dur/ytm join
    duration_summary: WeightedDurationDTO | None = None
    try:
        from modules.duration_fetcher import (
            DURATION_SOURCES,
            compute_weighted_duration,
        )
        wd = compute_weighted_duration(
            [(it.item_cd, it.weight) for it in items]
        )
        comp_map = {c["item_cd"]: c for c in wd["components"]}
        for it in items:
            c = comp_map.get(it.item_cd)
            if c is not None:
                it.duration = c.get("duration")
                it.ytm = c.get("ytm")
        duration_summary = WeightedDurationDTO(
            duration_bond=wd["duration_bond"],
            ytm_bond=wd["ytm_bond"],
            duration_overall=wd["duration_overall"],
            ytm_overall=wd["ytm_overall"],
            covered_weight=wd["covered_weight"],
            total_weight=wd["total_weight"],
            coverage_ratio=wd["coverage_ratio"],
        )
        # source 추가 (외부 fetch라서 mixed 표기는 과한 듯 — 별도 component로만 기록)
        if wd["covered_weight"] > 0:
            sources.append(SourceBreakdown(component="duration", kind="db"))
    except Exception as exc:
        warnings.append(f"듀레이션 fetch 실패: {type(exc).__name__}")

    # 8.5) 최초 편입일 join (DWPM10530 전이력 MIN)
    try:
        first_map = _load_first_dates(fund_code, [it.item_cd for it in items])
        if first_map:
            for it in items:
                fd = first_map.get(it.item_cd)
                if fd:
                    it.first_date = fd
    except Exception as exc:
        warnings.append(f"편입일 조회 실패: {type(exc).__name__}")

    # 9) 포트폴리오 mix 카드 (주식/채권/위험자산/현금)
    portfolio_mix = _build_portfolio_mix(items)

    # 10) 주식 포커스 (PER×EPS성장) + 컴플라이언스 게이지
    try:
        equity_focus = _build_equity_focus(items)
    except Exception as exc:
        warnings.append(f"주식 밸류에이션 실패: {type(exc).__name__}")
        equity_focus = None
    compliance = _build_compliance(fund_code, items, portfolio_mix, fx_hedge)

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
        data_pending=data_pending,
        data_note=data_note,
        nast_amt=nast,
        opng_amt=opng,
        asset_class_weights=asset_class_weights,
        holdings_items=items,
        fx_hedge=fx_hedge,
        duration_summary=duration_summary,
        portfolio_mix=portfolio_mix,
        equity_focus=equity_focus,
        compliance=compliance,
    )
