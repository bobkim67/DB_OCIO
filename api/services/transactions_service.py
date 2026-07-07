from datetime import datetime, timezone

from config.funds import FUND_LIST, FUND_META

from ..schemas.meta import BaseMeta, SourceBreakdown
from ..schemas.transactions import (
    CashflowRowDTO,
    FxForeignWeightPointDTO,
    FxPositionPointDTO,
    FxPositionResponseDTO,
    FxRatePointDTO,
    WeightNavPointDTO,
    SecuritiesResponseDTO,
    SecurityItemDTO,
    SecurityReturnPointDTO,
    SecurityReturnResponseDTO,
    SecurityTradeMarkerDTO,
    SecurityWeightPointDTO,
    TradeComponentDTO,
    TransactionRowDTO,
    TransactionsResponseDTO,
    WeightComponentDTO,
    WeightHistoryPointDTO,
    WeightHistoryResponseDTO,
    WeightMarkerDTO,
)


def _iso_to_yyyymmdd_int(s: str) -> int:
    return int(s.replace("-", ""))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_transactions(
    fund_code: str,
    start_date: str,
    end_date: str,
) -> TransactionsResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)

    # 지연 import (무거운 modules.data_loader 의존성 격리, 다른 서비스 동일 패턴)
    from modules.data_loader import (
        load_fund_cashflow_markers,
        load_fund_trades_lookthrough,
    )

    warnings: list[str] = []
    rows: list[TransactionRowDTO] = []
    funds_queried: list[str] = [fund_code]
    is_fof = False

    try:
        df, funds_queried, is_fof = load_fund_trades_lookthrough(
            fund_code,
            _iso_to_yyyymmdd_int(start_date),
            _iso_to_yyyymmdd_int(end_date),
        )
        for _, r in df.iterrows():
            # side 라벨은 로더에서 확정 (매수/매도/발행(BA정산)/환매(BA정산)/기타).
            # 환전·콜론은 로더에서 이미 제외됨.
            rows.append(TransactionRowDTO(
                date=str(r["날짜"]),
                fund_code=str(r["펀드"]),
                item_nm=str(r["종목명"]),
                asset_class=str(r["자산군"]),
                side=str(r["매수매도"]),
                amount_eok=float(r["금액(억)"]),
            ))
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")
        return TransactionsResponseDTO(
            meta=BaseMeta(
                source="mock", sources=[], is_fallback=True,
                warnings=warnings, generated_at=_now(),
            ),
            fund_code=fund_code,
            lookthrough_applied=False,
            funds_queried=[fund_code],
            start_date=start_date,
            end_date=end_date,
            rows=[],
        )

    if not rows:
        warnings.append("해당 기간 거래내역 없음")

    # 펀드 설정/해지 현금흐름 (부모펀드 기준 — 투자자 자금 유출입). 실패해도 거래내역은 반환.
    cashflows: list[CashflowRowDTO] = []
    try:
        for cf in load_fund_cashflow_markers(fund_code, start_date, end_date):
            cashflows.append(CashflowRowDTO(
                date=str(cf["date"]), side=str(cf["side"]),
                amount_eok=float(cf["amount"])))
    except Exception as exc:
        warnings.append(f"설정/해지 로드 실패: {type(exc).__name__}")

    return TransactionsResponseDTO(
        meta=BaseMeta(
            source="db",
            sources=[SourceBreakdown(component="transactions", kind="db")],
            is_fallback=False,
            warnings=warnings,
            generated_at=_now(),
        ),
        fund_code=fund_code,
        lookthrough_applied=is_fof,
        funds_queried=funds_queried,
        start_date=start_date,
        end_date=end_date,
        rows=rows,
        cashflows=cashflows,
    )


def _clip_by_date(df, end_date: str | None, col: str = "date"):
    """date 컬럼(YYYY-MM-DD str) 기준 end_date 이하로 절단. end_date 없으면 그대로."""
    if end_date is None or df is None or df.empty:
        return df
    return df[df[col].astype(str) <= end_date]


def build_weight_history(
    fund_code: str,
    start_date: str,
    level: str,
    end_date: str | None = None,
) -> WeightHistoryResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)
    if level not in ("security", "asset"):
        raise ValueError("level must be 'security' or 'asset'")

    from modules.data_loader import (
        load_fund_nav_with_aum,
        load_weight_history_lookthrough,
        load_weight_trade_markers,
    )

    warnings: list[str] = []

    try:
        df, is_fof, keys = load_weight_history_lookthrough(fund_code, start_date, level)
        df = _clip_by_date(df, end_date)
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")
        return WeightHistoryResponseDTO(
            meta=BaseMeta(
                source="mock", sources=[], is_fallback=True,
                warnings=warnings, generated_at=_now(),
            ),
            fund_code=fund_code, level=level, lookthrough_applied=False,
            start_date=start_date, keys=[], points=[], markers=[],
        )

    if df is None or df.empty:
        warnings.append("해당 기간 비중 데이터 없음")
        return WeightHistoryResponseDTO(
            meta=BaseMeta(
                source="mock", sources=[], is_fallback=True,
                warnings=warnings, generated_at=_now(),
            ),
            fund_code=fund_code, level=level, lookthrough_applied=is_fof,
            start_date=start_date, keys=[], points=[], markers=[],
        )

    # keys 정렬은 로더가 (버킷 순서, 평균비중 desc)로 확정
    points = [
        WeightHistoryPointDTO(
            date=str(r["date"]), key=str(r["key"]), weight=float(r["weight"]),
        )
        for _, r in df.iterrows()
    ]

    # 매매 마커 — 실패해도 차트 본체에 영향 없도록 격리
    markers: list[WeightMarkerDTO] = []
    try:
        mdf = load_weight_trade_markers(fund_code, start_date, level, end_date=end_date)
        if mdf is not None and not mdf.empty:
            markers = [
                WeightMarkerDTO(date=str(r["date"]), key=str(r["key"]),
                                net_eok=float(r["net_eok"]))
                for _, r in mdf.iterrows()
            ]
    except Exception as exc:
        warnings.append(f"마커 생성 실패: {type(exc).__name__}")

    # 일별 순자산(억) — 'NAV기준' 토글에서 비중×AUM 환산용 (부모펀드 기준). 실패해도 격리.
    nav: list[WeightNavPointDTO] = []
    try:
        ndf = load_fund_nav_with_aum(fund_code, str(start_date).replace("-", ""))
        if ndf is not None and not ndf.empty:
            nav = [
                WeightNavPointDTO(date=pd_ts.strftime("%Y-%m-%d"), aum_eok=float(aum))
                for pd_ts, aum in zip(ndf["기준일자"], ndf["AUM_억"])
                if end_date is None or pd_ts.strftime("%Y-%m-%d") <= end_date
            ]
    except Exception as exc:
        warnings.append(f"NAV 로드 실패: {type(exc).__name__}")

    return WeightHistoryResponseDTO(
        meta=BaseMeta(
            source="db",
            sources=[SourceBreakdown(component="weight_history", kind="db")],
            is_fallback=False,
            warnings=warnings,
            generated_at=_now(),
        ),
        fund_code=fund_code,
        level=level,
        lookthrough_applied=is_fof,
        nav=nav,
        start_date=start_date,
        keys=keys,
        points=points,
        markers=markers,
    )


def build_fx_position(
    fund_code: str, start_date: str, end_date: str | None = None,
) -> FxPositionResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)
    from modules.data_loader import (
        load_foreign_asset_weight_history,
        load_fx_position_history,
        load_usdkrw_series,
    )

    warnings: list[str] = []
    try:
        df, has_fx = load_fx_position_history(fund_code, start_date)
        df = _clip_by_date(df, end_date)
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")
        return FxPositionResponseDTO(
            meta=BaseMeta(source="mock", sources=[], is_fallback=True,
                          warnings=warnings, generated_at=_now()),
            fund_code=fund_code, has_fx=False, start_date=start_date,
            keys=[], points=[],
        )

    points, keys = [], []
    usdkrw: list[FxRatePointDTO] = []
    foreign_weight: list[FxForeignWeightPointDTO] = []
    if has_fx and df is not None and not df.empty:
        keys = list(dict.fromkeys(df["key"].tolist()))
        points = [
            FxPositionPointDTO(date=str(r["date"]), key=str(r["key"]),
                               weight=float(r["weight"]))
            for _, r in df.iterrows()
        ]
        # 보조 레이어 — 실패해도 FX 포지션 자체는 반환(경고만)
        try:
            rate_df = _clip_by_date(load_usdkrw_series(start_date), end_date)
            usdkrw = [FxRatePointDTO(date=str(r["date"]), rate=float(r["rate"]))
                      for _, r in rate_df.iterrows()]
        except Exception as exc:
            warnings.append(f"USD/KRW 로드 실패: {type(exc).__name__}")
        try:
            fw_df = _clip_by_date(load_foreign_asset_weight_history(fund_code, start_date), end_date)
            foreign_weight = [
                FxForeignWeightPointDTO(date=str(r["date"]), weight=float(r["weight"]))
                for _, r in fw_df.iterrows()
            ]
        except Exception as exc:
            warnings.append(f"해외자산 비중 로드 실패: {type(exc).__name__}")

    return FxPositionResponseDTO(
        meta=BaseMeta(
            source="db" if has_fx else "mock",
            sources=[SourceBreakdown(component="fx_position", kind="db")] if has_fx else [],
            is_fallback=not has_fx, warnings=warnings, generated_at=_now(),
        ),
        fund_code=fund_code, has_fx=has_fx, start_date=start_date,
        keys=keys, points=points, usdkrw=usdkrw, foreign_weight=foreign_weight,
    )


def build_securities(
    fund_code: str, start_date: str | None = None,
) -> SecuritiesResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)
    from modules.data_loader import load_fund_securities

    warnings: list[str] = []
    items: list[SecurityItemDTO] = []
    try:
        df = load_fund_securities(fund_code, start_date=start_date)
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                items.append(SecurityItemDTO(
                    item_cd=str(r["item_cd"]), item_nm=str(r["item_nm"]),
                    bucket=str(r["bucket"]), weight=float(r["weight"]),
                    has_price=bool(r["has_price"]),
                    currently_held=bool(r.get("currently_held", True)),
                ))
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")

    return SecuritiesResponseDTO(
        meta=BaseMeta(
            source="db" if items else "mock",
            sources=[SourceBreakdown(component="securities", kind="db")] if items else [],
            is_fallback=not items, warnings=warnings, generated_at=_now(),
        ),
        fund_code=fund_code, items=items,
    )


def build_security_return(
    fund_code: str, item_cd: str, item_nm: str,
    start_date: str, end_date: str,
) -> SecurityReturnResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)
    from modules.data_loader import (
        load_security_return_with_trades,
        load_weight_history_lookthrough,
    )

    warnings: list[str] = []
    points: list[SecurityReturnPointDTO] = []
    trades: list[SecurityTradeMarkerDTO] = []
    weights: list[SecurityWeightPointDTO] = []
    try:
        price, trade_list = load_security_return_with_trades(
            fund_code, item_cd, start_date, end_date)
        if price is not None and not price.empty:
            points = [
                SecurityReturnPointDTO(date=str(r["date"]), value=float(r["value"]))
                for _, r in price.iterrows()
            ]
        else:
            warnings.append("SCIP 가격 데이터 없음")
        trades = [
            SecurityTradeMarkerDTO(date=t["date"], side=t["side"], amount=float(t["amount"]))
            for t in trade_list
        ]
        # 보조축 비중 레이어 — 기존 weight-history(security, FoF 가중) 재사용, 종목명 매칭
        if item_nm:
            wdf, _fof, _keys = load_weight_history_lookthrough(
                fund_code, start_date, "security")
            if wdf is not None and not wdf.empty:
                w = wdf[wdf["key"] == item_nm]
                weights = [
                    SecurityWeightPointDTO(date=str(r["date"]), weight=float(r["weight"]))
                    for _, r in w.iterrows()
                ]
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")

    return SecurityReturnResponseDTO(
        meta=BaseMeta(
            source="db" if points else "mock",
            sources=[SourceBreakdown(component="security_return", kind="db")] if points else [],
            is_fallback=not points, warnings=warnings, generated_at=_now(),
        ),
        fund_code=fund_code, item_cd=item_cd, item_nm=item_nm,
        start_date=start_date, points=points, trades=trades, weights=weights,
    )


def build_asset_class_return(
    fund_code: str, asset_class: str, start_date: str, end_date: str,
) -> SecurityReturnResponseDTO:
    """자산군 바스켓 수익지수(클래스 내 정규화) + 자산군 순매수 마커 + 자산군 비중 보조축.
    종목 수익률과 동일 DTO 재사용(item_cd=item_nm=자산군)."""
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)
    if asset_class == "전체":
        return _build_total_return(fund_code, start_date, end_date)
    from modules.data_loader import (
        load_asset_class_return_index,
        load_weight_trade_markers,
        load_weight_history_lookthrough,
        _asset_class_member_names,
    )

    warnings: list[str] = []
    points: list[SecurityReturnPointDTO] = []
    trades: list[SecurityTradeMarkerDTO] = []
    weights: list[SecurityWeightPointDTO] = []
    weight_components: list[WeightComponentDTO] = []
    trade_components: list[TradeComponentDTO] = []
    try:
        idx, warn = load_asset_class_return_index(
            fund_code, asset_class, start_date, end_date)
        if warn:
            warnings.append(warn)
        if idx is not None and not idx.empty:
            points = [
                SecurityReturnPointDTO(date=str(r["date"]), value=float(r["value"]))
                for _, r in idx.iterrows()
            ]
        # 자산군 순매수 마커
        mdf = load_weight_trade_markers(fund_code, start_date, "asset", end_date)
        if mdf is not None and not mdf.empty:
            m = mdf[mdf["key"] == asset_class]
            for _, r in m.iterrows():
                net = float(r["net_eok"])
                trades.append(SecurityTradeMarkerDTO(
                    date=str(r["date"]),
                    side="순매수" if net >= 0 else "순매도",
                    amount=abs(net)))
        # 자산군 비중 보조축 + 종목별 분해(툴팁용)
        members = _asset_class_member_names(fund_code, asset_class, start_date)
        wdf, _fof, _keys = load_weight_history_lookthrough(fund_code, start_date, "asset")
        if wdf is not None and not wdf.empty:
            w = wdf[wdf["key"] == asset_class]
            weights = [
                SecurityWeightPointDTO(date=str(r["date"]), weight=float(r["weight"]))
                for _, r in w.iterrows()
            ]
        # 종목별 편입비중 (security 레벨에서 멤버 종목만)
        swdf, _f2, _k2 = load_weight_history_lookthrough(fund_code, start_date, "security")
        if swdf is not None and not swdf.empty:
            sw = swdf[swdf["key"].isin(members)]
            weight_components = [
                WeightComponentDTO(date=str(r["date"]), name=str(r["key"]),
                                   weight=float(r["weight"]))
                for _, r in sw.iterrows()
            ]
        # 종목별 순매수 (security 레벨 마커에서 멤버 종목만)
        smdf = load_weight_trade_markers(fund_code, start_date, "security", end_date)
        if smdf is not None and not smdf.empty:
            sm = smdf[smdf["key"].isin(members)]
            for _, r in sm.iterrows():
                net = float(r["net_eok"])
                trade_components.append(TradeComponentDTO(
                    date=str(r["date"]), name=str(r["key"]),
                    side="순매수" if net >= 0 else "순매도", amount=abs(net)))
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")

    return SecurityReturnResponseDTO(
        meta=BaseMeta(
            source="db" if points else "mock",
            sources=[SourceBreakdown(component="asset_class_return", kind="db")] if points else [],
            is_fallback=not points, warnings=warnings, generated_at=_now(),
        ),
        fund_code=fund_code, item_cd=asset_class, item_nm=asset_class,
        start_date=start_date, points=points, trades=trades, weights=weights,
        weight_components=weight_components, trade_components=trade_components,
    )


def _build_total_return(
    fund_code: str, start_date: str, end_date: str,
) -> SecurityReturnResponseDTO:
    """자산군 차트 '전체' 옵션 — 펀드 기준가(NAV) 수익지수 + 설정/해지 현금흐름 마커
    + 자산군별 비중 stacked(보조축). 종목/자산군 차트와 동일 DTO 재사용."""
    from modules.data_loader import (
        load_fund_total_return_index,
        load_fund_cashflow_markers,
        load_weight_history_lookthrough,
    )

    warnings: list[str] = []
    points: list[SecurityReturnPointDTO] = []
    trades: list[SecurityTradeMarkerDTO] = []
    weights: list[SecurityWeightPointDTO] = []
    weight_components: list[WeightComponentDTO] = []
    try:
        idx = load_fund_total_return_index(fund_code, start_date, end_date)
        if idx is not None and not idx.empty:
            points = [
                SecurityReturnPointDTO(date=str(r["date"]), value=float(r["value"]))
                for _, r in idx.iterrows()
            ]
        else:
            warnings.append("기준가(NAV) 데이터 없음")
        # 설정/해지 현금흐름 마커 (자금 유입=설정 ▲ / 유출=해지 ▼)
        for cf in load_fund_cashflow_markers(fund_code, start_date, end_date):
            trades.append(SecurityTradeMarkerDTO(
                date=str(cf["date"]), side=str(cf["side"]), amount=float(cf["amount"])))
        # 자산군별 비중 stacked area(보조축) + 일별 합계(툴팁 총비중)
        wdf, _fof, _keys = load_weight_history_lookthrough(fund_code, start_date, "asset")
        if wdf is not None and not wdf.empty:
            weight_components = [
                WeightComponentDTO(date=str(r["date"]), name=str(r["key"]),
                                   weight=float(r["weight"]))
                for _, r in wdf.iterrows()
            ]
            tot = wdf.groupby("date")["weight"].sum().reset_index()
            weights = [
                SecurityWeightPointDTO(date=str(r["date"]), weight=float(r["weight"]))
                for _, r in tot.iterrows()
            ]
    except Exception as exc:
        warnings.append(f"DB 접속 실패: {type(exc).__name__}")

    return SecurityReturnResponseDTO(
        meta=BaseMeta(
            source="db" if points else "mock",
            sources=[SourceBreakdown(component="asset_class_return", kind="db")] if points else [],
            is_fallback=not points, warnings=warnings, generated_at=_now(),
        ),
        fund_code=fund_code, item_cd="전체", item_nm="전체",
        start_date=start_date, points=points, trades=trades, weights=weights,
        weight_components=weight_components, trade_components=[],
    )
