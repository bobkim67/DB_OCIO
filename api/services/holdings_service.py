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
    PendingSettlementDTO,
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
    style = {"성장": 0.0, "가치": 0.0, "혼합": 0.0}
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
        # 스타일 = proxy 분류 기반(키워드 직접판정 대신) — ITEM_NM 잘림에도 일관.
        # 나스닥100=대형 기술·성장 편중 → 성장. KOSPI200/S&P500=시장 전체 → 혼합(blend).
        sk = ("성장" if tk in ("미국대형성장", "NASDAQ100")
              else "가치" if tk == "미국대형가치" else "혼합")
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


def _subfund_weights(parent_code: str) -> dict[str, float]:
    """부모 펀드(07G04) 내 서브펀드(07G02/07G03) 비중 {서브코드: EVL 비중}.
    ITEM_CD 가 '...07G02'/'...07G03' 형태로 서브펀드 코드를 포함한다."""
    try:
        df = _load_holdings_df(parent_code, None, lookthrough=False)
    except Exception:
        return {}
    if df is None or len(df) == 0 or "EVL_AMT" not in df.columns:
        return {}
    tot = float(df["EVL_AMT"].sum())
    if tot <= 0:
        return {}
    out: dict[str, float] = {}
    for _, row in df.iterrows():
        cd = str(_val(row, "ITEM_CD", default=""))
        evl = _val(row, "EVL_AMT")
        for sub in ("07G02", "07G03"):
            if sub in cd and evl is not None:
                try:
                    out[sub] = out.get(sub, 0.0) + float(evl) / tot
                except (TypeError, ValueError):
                    pass
    return out


def _build_compliance(
    fund_code: str, items: list[HoldingItemDTO],
    mix: PortfolioMixSummaryDTO, fx_hedge: FxHedgeSummaryDTO | None,
) -> list[ComplianceItemDTO]:
    """펀드별 실제 가이드라인 (2026-06-24 사용자 제공)."""
    rows: list[ComplianceItemDTO] = []
    risk = _risk_excl_safe(items)   # 위험자산 = 안전자산(국내채권+유동성) 외 전부
    liq = _liquidity_weight(items)  # 유동성 자산군(현금·미수금 포함)

    if fund_code == "08K88":
        # 자산군별 비중 모니터링 (2026-07-07 사용자 제공 — 구 '위험자산 ≤92%' 대체):
        # SAA 해외주식 56 / 국내주식 24 / 해외채권 10 / 국내채권 10 (%),
        # 허용범위 해외주식 ±12%p · 국내주식 ±8%p · 채권 ±2%p
        def _acw(ac: str) -> float:
            return sum(it.weight for it in items if it.asset_class == ac)
        rows.append(_ci("fstk", "해외주식", _acw("해외주식"), low=0.44, high=0.68))
        rows.append(_ci("kstk", "국내주식", _acw("국내주식"), low=0.16, high=0.32))
        rows.append(_ci("fbond", "해외채권", _acw("해외채권"), low=0.08, high=0.12))
        rows.append(_ci("kbond", "국내채권", _acw("국내채권"), low=0.08, high=0.12))

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

    elif fund_code == "07G02":
        # ISP(인컴추구 모펀드) 단독 가이드: 주식 ≤20%, 위험자산 ≤20%
        # (07G04 내 ISP 서브펀드 한도와 동일 — 2026-07-09 사용자 확정)
        rows.append(_ci("equity", "주식비중", mix.equity_weight, high=0.20))
        rows.append(_ci("risk_asset", "위험자산", risk, high=0.20))

    elif fund_code in ("07G03", "06X08"):
        # RSP 가이드: 주식 ≤55%, 위험자산 ≤70%.
        # 07G03(수익추구 모펀드) = 07G04 내 RSP 서브펀드 한도(2026-07-09).
        # 06X08(퇴직연금 알아서RSP)도 07G03과 동일 적용(2026-07-10 사용자 지시).
        rows.append(_ci("equity", "주식비중", mix.equity_weight, high=0.55))
        rows.append(_ci("risk_asset", "위험자산", risk, high=0.70))

    elif fund_code in ("07G04", "07G07"):
        # 07G07 은 07G04 의 C-F 클래스 별칭 → 동일 가이드 적용.
        # ISP(07G02)/RSP(07G03) 를 나눠 기재하지 않고 07G04 내 서브펀드 비중으로
        # 가중평균해 주식비중·위험자산 2행으로 표기 (2026-07-10 사용자 지시).
        subw = _subfund_weights("07G04")   # {서브펀드코드: 07G04 내 비중}
        tot_w = v_eq = v_risk = lim_eq = lim_risk = 0.0
        for sub, eq_lim, risk_lim in (("07G02", 0.20, 0.20), ("07G03", 0.55, 0.70)):
            m = _subfund_metrics(sub)
            w = subw.get(sub, 0.0)
            if m is None or w <= 0:
                continue
            tot_w += w
            v_eq += w * m["equity"]; v_risk += w * m["risk"]
            lim_eq += w * eq_lim; lim_risk += w * risk_lim
        if tot_w > 0:
            rows.append(_ci("equity", "주식비중", v_eq / tot_w, high=lim_eq / tot_w))
            rows.append(_ci("risk_asset", "위험자산", v_risk / tot_w, high=lim_risk / tot_w))

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


def _fc_amount(row: pd.Series) -> tuple[str | None, float | None]:
    """외화표시 종목의 (통화, 원통화 평가액). 원화·미상이면 (None, None).

    DWPM10530 은 원화 EVL_AMT 와 별도로 FC_EVL_AMT(원통화)를 준다 — 환산이 아니라
    원장값이라 환율 가정이 끼지 않는다. KRW 행은 FC_EVL_AMT 가 0/결측이라 걸러낸다.
    """
    ccy = str(_val(row, "CURR_DS_CD", "curr_ds_cd", default="") or "").strip().upper()
    if not ccy or ccy == "KRW":
        return None, None
    raw = _val(row, "FC_EVL_AMT", "fc_evl_amt")
    if raw is None:
        return ccy, None
    try:
        amt = float(raw)
    except (TypeError, ValueError):
        return ccy, None
    return ccy, (amt if amt != 0 else None)


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


# ── 결제 예정 (2026-08-03) ─────────────────────────────────────────────
# 해외 ETF 는 체결 다음 영업일(브로커 SettleDate)에야 원장에 잡힌다. 그 사이엔
# 화면이 매매를 전혀 모르므로, 확인서 메일을 배치 파싱한 JSON 을 읽어 안내만 한다.
# 비중은 손대지 않는다 (원장 = SSOT, 사용자 확정).
_PENDING_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".cache", "pending_trades.json",
)


def _load_pending_mail_trades() -> list[dict]:
    """.cache/pending_trades.json (tools/parse_overseas_confirmations.py 산출)."""
    try:
        with open(_PENDING_JSON, encoding="utf-8") as fh:
            return json.load(fh).get("trades", [])
    except (OSError, ValueError):
        return []          # 배치 미실행/파손 → 배너 없음 (기능 무중단)


def _usdkrw_on(as_of: date | None) -> float | None:
    """as_of 이하 최신 USD 매매기준율 (DWCI10260). 배너 원화 환산용 참고값."""
    if as_of is None:
        return None
    try:
        from modules.data_loader import get_connection
        conn = get_connection("dt")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT TR_STD_RT FROM DWCI10260 WHERE CURR_DS_CD='USD' "
                    "AND STD_DT <= %s ORDER BY STD_DT DESC LIMIT 1",
                    (as_of.strftime("%Y%m%d"),))
                row = cur.fetchone()
                if not row:
                    return None
                v = row.get("TR_STD_RT") if isinstance(row, dict) else row[0]
                return float(v) if v else None
        finally:
            conn.close()
    except Exception:      # noqa: BLE001 — 환율 없으면 원통화만 표기
        return None


def _load_ledger_unsettled(fund_code: str, as_of: date | None) -> list[dict]:
    """원장에 있으나 결제일 미도래(STL_DT > 기준일)인 거래. 미지급금으로 이미 반영됨."""
    if as_of is None:
        return []
    try:
        from modules.data_loader import _portfolio_fund, get_connection
        conn = get_connection("dt")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT item_nm, buy_sell_ds_cd, trd_qty, curr_ds_cd, "
                    "       stl_amt, krw_stl_amt, std_dt, stl_dt "
                    "FROM DWPM10520 WHERE fund_cd=%s AND stl_dt > %s AND std_dt <= %s "
                    "ORDER BY stl_dt, item_nm",
                    (_portfolio_fund(fund_code), as_of.strftime("%Y%m%d"),
                     as_of.strftime("%Y%m%d")))
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception:      # noqa: BLE001
        return []

    out = []
    for r in rows:
        d = r if isinstance(r, dict) else dict(zip(
            ["item_nm", "buy_sell_ds_cd", "trd_qty", "curr_ds_cd",
             "stl_amt", "krw_stl_amt", "std_dt", "stl_dt"], r))
        out.append(d)
    return out


def _next_business_day(d: date | None) -> date | None:
    """d 다음 영업일 (DWCI10220). 결제일 → 화면 반영일 계산용.

    원장 STD_DT 는 결제일이지만 보유·기준가 스냅샷이 익일 새벽 적재라 화면에
    나타나는 건 하루 뒤다. 캘린더 조회 실패 시 주말만 건너뛰는 fallback.
    """
    if d is None:
        return None
    from datetime import timedelta
    try:
        from modules.data_loader import load_business_days_set
        days = load_business_days_set(
            d.strftime("%Y%m%d"), (d + timedelta(days=21)).strftime("%Y%m%d"))
    except Exception:      # noqa: BLE001
        days = frozenset()
    nxt = d + timedelta(days=1)
    for _ in range(21):
        if days:
            if nxt.strftime("%Y-%m-%d") in days:
                return nxt
        elif nxt.weekday() < 5:       # 캘린더 없으면 주말만 제외
            return nxt
        nxt += timedelta(days=1)
    return None


def _parse_ymd(s) -> date | None:
    if not s:
        return None
    try:
        return pd.to_datetime(str(s).replace("-", "")[:8], format="%Y%m%d").date()
    except Exception:
        return None


def _build_pending_settlements(
    fund_code: str, as_of: date | None,
) -> list[PendingSettlementDTO]:
    """결제 예정 목록 = 메일 확인서 중 원장 미반영분 + 원장 내 미결제분."""
    if as_of is None:
        return []
    out: list[PendingSettlementDTO] = []
    rate = None

    # 1) 확인서 메일 — SettleDate > 기준일 이면 아직 원장에 없다
    #    (실측: 원장 STD_DT = 브로커 SettleDate. 2026-08-03 IAUM 건으로 확인)
    from modules.data_loader import _portfolio_fund
    _pf = _portfolio_fund(fund_code)
    for t in _load_pending_mail_trades():
        if t.get("fund_cd") not in (fund_code, _pf):
            continue
        settle = _parse_ymd(t.get("settle_date"))
        if settle is None or settle <= as_of:
            continue                                # 이미 원장에 반영됐거나 반영 예정일 지남
        amt = t.get("net_amount")
        krw = None
        if t.get("ccy") == "USD" and amt:
            if rate is None:
                rate = _usdkrw_on(as_of)
            krw = amt * rate if rate else None
        out.append(PendingSettlementDTO(
            source="mail",
            item_nm=t.get("security_name") or t.get("ticker") or "",
            ticker=t.get("ticker") or None,
            side="매도" if str(t.get("side", "")).upper().startswith("S") else "매수",
            qty=t.get("qty"),
            ccy=t.get("ccy") or "USD",
            amount=amt,
            amount_krw=krw,
            trade_date=_parse_ymd(t.get("order_date")),
            settle_date=settle,
            reflect_date=_next_business_day(settle),
            note=f"{t.get('broker', '')} 확인서 — 원장 미반영".strip(),
        ))

    # 2) 원장 미결제 — 비중엔 이미 미지급금으로 반영돼 있음 (유동성 음수의 원인)
    for d in _load_ledger_unsettled(fund_code, as_of):
        krw = d.get("krw_stl_amt") or None
        amt = d.get("stl_amt") or None
        ccy = str(d.get("curr_ds_cd") or "KRW").strip() or "KRW"
        if ccy == "KRW" and not krw:
            krw = amt
        out.append(PendingSettlementDTO(
            source="ledger",
            item_nm=str(d.get("item_nm") or ""),
            side="매도" if str(d.get("buy_sell_ds_cd") or "").upper() == "D" else "매수",
            qty=float(d["trd_qty"]) if d.get("trd_qty") is not None else None,
            ccy=ccy,
            amount=float(amt) if amt else None,
            amount_krw=float(krw) if krw else None,
            trade_date=_parse_ymd(d.get("std_dt")),
            settle_date=_parse_ymd(d.get("stl_dt")),
            note="원장 반영됨 — 미지급금 계상",
        ))

    out.sort(key=lambda p: (p.settle_date or date.max, p.item_nm))
    return out


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
    #    룩스루 홀딩스의 EVL_AMT 는 포트폴리오 마스터(07G07→07G04) 절대금액이므로
    #    비중 분모(NAST)도 마스터 기준이어야 정합. 안 그러면 07G07 은 07G04 NAST/07G07 NAST
    #    (~3.94배)만큼 비중이 부풀려져 듀레이션 등이 왜곡된다 (2026-07-10 fix).
    from modules.data_loader import _portfolio_fund
    _pf = _portfolio_fund(fund_code)
    nast = _load_nast(_pf, as_of)
    opng = _load_opng(_pf, as_of)
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
        ccy, fc_amt = _fc_amount(row)
        items.append(HoldingItemDTO(
            item_cd=item_cd_s,
            item_nm=item_nm_s,
            asset_class=ac_final,
            weight=weight,
            evl_amt=evl_f,
            currency=ccy,
            fc_evl_amt=fc_amt,
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

    # 4.6) FX(달러선물 등)는 포지션(notional)이지 NAV 구성이 아니므로 **합계에서 제외**
    #      (2026-06-24 사용자 확정). 다만 화면에서 아예 안 보이면 포지션을 놓친다
    #      → `fx_positions` 로 따로 내보내 편입종목 표의 **펀드 합계 아래**에 참고 행으로
    #        붙인다 (2026-08-07 사용자 지시). 100% 구성은 그대로 유지된다.
    fx_positions = [it for it in items if it.asset_class == "FX"]
    items = [it for it in items if it.asset_class != "FX"]

    def _load_payable_rows(fc: str, asof) -> list[tuple[str, float]]:
        """원장 부채성 계정(25x·미지급 계열, 로더 제외분) — 잔차 실명 표기용 (2026-07-14)."""
        from modules.data_loader import _portfolio_fund, get_connection
        std = str(asof).replace("-", "")[:8]
        try:
            conn = get_connection("dt")
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT ITEM_NM, SUM(EVL_AMT) amt FROM DWPM10530 "
                    "WHERE FUND_CD=%s AND STD_DT=%s "
                    "AND (ITEM_CD LIKE '25%%' OR ITEM_NM LIKE '%%미지급%%') "
                    "AND EVL_AMT > 0 GROUP BY ITEM_NM",
                    (_portfolio_fund(fc), std))
                rows = cur.fetchall()
                # get_connection 커서가 dict/tuple 어느 쪽이든 대응
                return [(str(r['ITEM_NM'] if isinstance(r, dict) else r[0]),
                         float(r['amt'] if isinstance(r, dict) else r[1]))
                        for r in rows]
            finally:
                conn.close()
        except Exception:                 # noqa: BLE001 — 조회 실패 시 기존 라벨 폴백
            return []

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
            # 실제 부채 계정 조회 (2026-07-14): 잔차의 실체가 매입미지급금(정상 T+1~2 결제대기)
            # 인 경우가 있는데 일괄 '환매미지급금' 표기는 오인 유발 (2JM23 ACE200 매수 사례).
            # 원장 25x/미지급 계열과 금액이 맞으면 실명으로, 아니면 기존 라벨 폴백.
            payables = _load_payable_rows(fund_code, as_of)
            if payables and abs(sum(a for _n, a in payables) + resid) < max(abs(resid) * 0.05, 1e6):
                for nm, amt in payables:
                    items.append(HoldingItemDTO(
                        item_cd="_PAYABLE_", item_nm=nm,
                        asset_class="유동성", weight=-amt / nast, evl_amt=-amt,
                    ))
                data_note = "결제 대기 — " + "·".join(n for n, _a in payables) + " 반영"
            else:
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
    #      FX 포지션도 포함 — 화면에 편입일을 같이 찍는다 (2026-08-07 사용자 지시).
    #      달러선물은 월물이 바뀌므로 **그 월물의 진입일**이 나온다.
    try:
        _fd_targets = items + fx_positions
        first_map = _load_first_dates(fund_code, [it.item_cd for it in _fd_targets])
        if first_map:
            for it in _fd_targets:
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

    # 11) 결제 예정 안내 (비중 불변 — 배너 표시용)
    try:
        pending_settlements = _build_pending_settlements(fund_code, as_of)
    except Exception as exc:      # noqa: BLE001 — 부가 안내라 실패해도 본문 유지
        warnings.append(f"결제예정 조회 실패: {type(exc).__name__}")
        pending_settlements = []

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
        fx_positions=fx_positions,
        fx_hedge=fx_hedge,
        duration_summary=duration_summary,
        portfolio_mix=portfolio_mix,
        equity_focus=equity_focus,
        compliance=compliance,
        pending_settlements=pending_settlements,
    )
