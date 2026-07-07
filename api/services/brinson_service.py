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

import os
import pickle
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
    BrinsonApCompItemDTO,
    BrinsonApCompositionDTO,
    BrinsonAssetRowDTO,
    BrinsonBmComponentDTO,
    BrinsonDailyClassDTO,
    BrinsonDailyPointDTO,
    BrinsonPeriodDTO,
    BrinsonPeriodRowDTO,
    BrinsonPeriodsResponseDTO,
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
    # YTD 시작 = 1/1 (엔진 규약: start=첫 수익 인식일, base=전년말).
    # 12/31 을 넘기면 base 가 12/30 으로 하루 밀려 R 대비 bp 왜곡 (2026-07-06 07G07 진단).
    ytd_start = date(year, 1, 1)
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

_BRINSON_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".cache", "brinson",
)
# 거래 캐시와 동일 플래그로 디스크 캐시 우회 가능
_DISK_DISABLED = os.environ.get("OCIO_DISABLE_DB_CACHE") == "1"


def _brinson_disk_path(fund_code: str, start_yyyymmdd: str,
                       end_yyyymmdd: str, mapping_method: str,
                       saa_mode: str = "auto", fx_split: bool = True) -> str:
    suffix = "" if saa_mode == "auto" else f"_{saa_mode}"
    # fx_split=True(분리) 는 기존 파일명 유지(골든·기존 캐시 호환), False('FX 포함') 만 별도 파일.
    fx_suffix = "" if fx_split else "_fxincl"
    safe = f"{fund_code}_{start_yyyymmdd}_{end_yyyymmdd}_{mapping_method}{suffix}{fx_suffix}".replace("/", "_")
    return os.path.join(_BRINSON_CACHE_DIR, safe + ".pkl")


@lru_cache(maxsize=128)
def _compute_cached(fund_code: str, start_yyyymmdd: str, end_yyyymmdd: str,
                    mapping_method: str, saa_mode: str = "auto",
                    fx_split: bool = True) -> dict | None:
    """compute_brinson_attribution_v2 결과를 LRU(인메모리) + 디스크(.cache/brinson) 캐시.

    캐시 키 (fund, start, end, method, saa_mode, fx_split). pa_method 만 후처리라 키 제외.
    fx_split 은 환효과를 자산군 수익률에 접느냐(False) 분리하느냐(True)로 compute 입력이라 키 포함.
    saa_mode='auto'(BM/등록SAA)·fx_split=True 는 기존 파일명 유지, 그 외 별도 파일.
    """
    path = _brinson_disk_path(fund_code, start_yyyymmdd, end_yyyymmdd, mapping_method, saa_mode, fx_split)
    if not _DISK_DISABLED and os.path.exists(path):
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass  # 손상 시 재계산
    from modules.data_loader import compute_brinson_attribution_v2
    raw = compute_brinson_attribution_v2(
        fund_code, start_yyyymmdd, end_yyyymmdd,
        mapping_method=mapping_method, saa_mode=saa_mode, fx_split=fx_split,
    )
    if raw is not None and not _DISK_DISABLED:
        try:
            os.makedirs(_BRINSON_CACHE_DIR, exist_ok=True)
            with open(path, "wb") as f:
                pickle.dump(raw, f)
        except Exception:
            pass  # 캐시 실패는 무시(계산 결과는 정상 반환)
    return raw


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
        "BM기여": other["BM기여"].sum() if "BM기여" in other.columns else 0.0,
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
            bm_contrib=float(r.get("BM기여", 0.0) or 0.0),
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
        nm = str(r.get("종목명", ""))
        w = float(r.get("비중(%)", r.get("순자산비중", 0.0)) or 0.0)
        ret = float(r.get("수익률(%)", r.get("개별수익률", 0.0)) or 0.0)
        contrib = float(r.get("기여수익률(%)", r.get("기여수익률", 0.0)) or 0.0)
        # PA 소스(MA000410 sec_id) 더미 행 — 이름이 0으로만 구성되고 값도 전부 0이면 제외
        # (예: 08N81 국내주식 '000000000000'). 값이 있으면 실포지션일 수 있어 유지.
        if nm and nm.strip("0") == "" and abs(w) < 1e-9 and abs(contrib) < 1e-9:
            continue
        out.append(BrinsonSecContribDTO(
            asset_class=str(r.get("자산군", "")),
            item_nm=nm,
            weight_pct=w,
            return_pct=ret,
            contrib_pct=contrib,
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
            ap_cum=float(r.get("ap_cum", 0.0) or 0.0),
            bm_cum=float(r.get("bm_cum", 0.0) or 0.0),
        ))
    return out


def _to_daily_class_rows(df: pd.DataFrame | None) -> list[BrinsonDailyClassDTO]:
    if df is None or df.empty:
        return []
    out: list[BrinsonDailyClassDTO] = []
    for _, r in df.iterrows():
        d = r["date"]
        if isinstance(d, pd.Timestamp):
            d = d.date()
        elif isinstance(d, str):
            d = datetime.strptime(d[:10], "%Y-%m-%d").date()
        out.append(BrinsonDailyClassDTO(
            date=d,
            asset_class=str(r.get("asset_class", "")),
            ap_weight=float(r.get("ap_weight", 0.0) or 0.0),
            bm_weight=float(r.get("bm_weight", 0.0) or 0.0),
            ap_contrib_cum=float(r.get("ap_contrib_cum", 0.0) or 0.0),
            bm_contrib_cum=float(r.get("bm_contrib_cum", 0.0) or 0.0),
            ap_ret_cum=float(r.get("ap_ret_cum", 0.0) or 0.0),
            bm_ret_cum=float(r.get("bm_ret_cum", 0.0) or 0.0),
        ))
    return out


@lru_cache(maxsize=256)
def _rf_period_pct(start_yyyymmdd: str, end_yyyymmdd: str) -> float | None:
    """기간(start~end) 무위험 누적수익률(%) — KIS CD Index 총수익.

    `(P_end/P_start − 1)` 의 '기간(누적) 수익률' 을 반환한다. **연율화는 하지 않는다** —
    프론트(brinsonMetrics.ts)가 AP/BM 과 동일한 252영업일 기준(`^(252/n)`)으로 연율화해
    샤프비율 분자/분모 기준을 통일하기 위함(이전 365.25 캘린더 연율화는 분자만 달라 불일치).
    시작일이 RF 첫 데이터일보다 이르면(예: 펀드 inception 직후) 내부 load 가 start 이상만
    가져와 start 가격 lookup 이 NaN 이 되는 문제를 피하려 **30일 버퍼 load 후 ffill lookup**.
    RF 시계열 로드 실패/결측 시 None (프론트 샤프비율은 rf=0 안전 처리). 캐시 키 (start, end).
    """
    try:
        from modules.data_loader import load_rf_index_from_db
        start_dt = pd.Timestamp(start_yyyymmdd)
        end_dt = pd.Timestamp(end_yyyymmdd)
        buf_start = (start_dt - pd.Timedelta(days=30)).strftime("%Y%m%d")
        df = load_rf_index_from_db(buf_start, end_yyyymmdd)
        if df is None or df.empty:
            return None
        s = df.set_index("기준일자")["기준가"].sort_index()

        def _at(d: pd.Timestamp) -> float:
            sub = s[s.index <= d]
            return float(sub.iloc[-1]) if len(sub) else float("nan")

        p0, p1 = _at(start_dt), _at(end_dt)
        days = (end_dt - start_dt).days
        if not (p0 > 0) or days <= 0 or p1 != p1:  # p1!=p1 → NaN
            return None
        return round((p1 / p0 - 1.0) * 100, 4)
    except Exception:
        return None


def _build_bm_meta(fund_code: str, method: str, as_of=None,
                   saa_mode: str = "auto", start_yyyymmdd=None):
    """item4/5: BM(FUND_BM) / SAA 벤치마크(DB 인덱스) / proxy / SAA(MP 목표비중) 구성.

    returns (bm_source, components, saa_dict_or_None)
      - bm_source: "BM" | "SAA" | "none"
      - components: list[BrinsonBmComponentDTO]
      - saa_dict: 구 weight-only SAA 면 {자산군: 목표비중%} (BM비중 주입용). 그 외 None.
    """
    from config.funds import FUND_BM, FUND_MP_DIRECT, FUND_MP_MAPPING
    from modules.data_loader import (
        _build_proxy_bm_info, _map_bm_component_to_asset_class, load_saa_components,
    )

    if saa_mode in ("proxy", "proxy_drift"):
        # proxy: 안전자산→KIS 종합채권 / 나머지→MSCI ACWI (구성 동일, drift 는 비중만 일별 변동)
        info = _build_proxy_bm_info(fund_code, start_yyyymmdd) if start_yyyymmdd else None
        if info and info.get("components"):
            comps = [
                BrinsonBmComponentDTO(
                    name=str(c["name"]),
                    weight=round(float(c["weight"]) * 100, 2),
                    asset_class=_map_bm_component_to_asset_class(str(c["name"]), method),
                    region=str(c.get("region", "") or ""),
                    hedged=bool(c.get("hedged", False)),
                )
                for c in info["components"]
            ]
            return "SAA", comps, None
        return "none", [], None

    bm = FUND_BM.get(fund_code)
    if bm:
        comps = [
            BrinsonBmComponentDTO(
                name=str(c.get("name", "")),
                weight=round(float(c.get("weight", 0.0)) * 100, 2),
                asset_class=_map_bm_component_to_asset_class(str(c.get("name", "")), method),
                region=str(c.get("region", "") or ""),
                hedged=bool(c.get("hedged", False)),
            )
            for c in bm.get("components", [])
        ]
        return "BM", comps, None

    # BM 미설정 → SAA 벤치마크(DB 인덱스 컴포넌트). 있으면 수익률·기여 분해 가능(_saa=None).
    try:
        saa_db = load_saa_components(fund_code, as_of)
    except Exception:
        saa_db = None
    if saa_db and saa_db.get("components"):
        comps = [
            BrinsonBmComponentDTO(
                name=str(c["name"]),
                weight=round(float(c["weight"]) * 100, 2),
                asset_class=_map_bm_component_to_asset_class(str(c["name"]), method),
                region=str(c.get("region", "") or ""),
                hedged=bool(c.get("hedged", False)),
            )
            for c in saa_db["components"]
        ]
        return "SAA", comps, None

    # BM/SAA-DB 둘 다 없음 → 구 SAA(MP) 목표비중 (비중 비교만, 수익률 분해 불가).
    saa = None
    if fund_code in FUND_MP_DIRECT:
        saa = {k: float(v) for k, v in FUND_MP_DIRECT[fund_code].items()}
    elif fund_code in FUND_MP_MAPPING:
        try:
            from modules.data_loader import load_mp_weights_8class
            raw = load_mp_weights_8class(FUND_MP_MAPPING[fund_code])
            if isinstance(raw, dict):
                saa = {k: float(v) for k, v in raw.items()}
        except Exception:
            saa = None
    if saa:
        # SAA(MP) 키(대체투자/유동성)를 Brinson 자산군명(대체/유동성및기타)으로 정규화
        # → asset_rows/daily_class 와 동일 클래스명으로 묶여 표0 중복행(대체 vs 대체투자) 방지
        _norm = {"대체투자": "대체", "유동성": "유동성및기타"}
        _agg: dict[str, float] = {}
        for ac, w in saa.items():
            if abs(w) <= 1e-9:
                continue
            k = _norm.get(ac, ac)
            _agg[k] = _agg.get(k, 0.0) + w
        comps = [
            BrinsonBmComponentDTO(name=k, weight=round(w, 2), asset_class=k)
            for k, w in _agg.items()
        ]
        return "SAA", comps, saa
    return "none", [], None


# -------------------- public --------------------

# build_holdings 8class → 표0(Brinson) 자산군. FX 는 build_holdings 가 이미 NAV 제외.
_H8_TO_BRINSON = {"대체투자": "대체", "유동성": "유동성및기타", "모펀드": "유동성및기타"}


def _build_ap_composition(hold, method: str) -> list[BrinsonApCompositionDTO]:
    """표0 AP비중 = 기말 보유 스냅샷(build_holdings 결과, FX 제외·현금/환매미지급금 포함) → 자산군 구성.

    period PA 비중과 별개(구성=스냅샷/기여=기간). 환매미지급금(음수 유동성)도 유동성및기타에 반영.
    """
    try:
        from collections import defaultdict
        from modules.data_loader import _collapse_asset_class
        w_by: dict[str, float] = defaultdict(float)
        items_by: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for it in hold.holdings_items:
            if it.asset_class == "FX":
                continue
            bc = _collapse_asset_class(_H8_TO_BRINSON.get(it.asset_class, it.asset_class), method)
            if not bc or bc == "FX":
                continue
            w_by[bc] += it.weight
            items_by[bc].append((it.item_nm, it.weight))
        out: list[BrinsonApCompositionDTO] = []
        for bc, w in w_by.items():
            items = [BrinsonApCompItemDTO(item_nm=nm, weight_pct=round(wt * 100, 2))
                     for nm, wt in sorted(items_by[bc], key=lambda x: -x[1])]
            out.append(BrinsonApCompositionDTO(
                asset_class=bc, weight_pct=round(w * 100, 2), items=items))
        return out
    except Exception:
        return []


def build_brinson(
    fund_code: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    mapping_method: str | None = None,
    pa_method: str = "8",
    fx_split: bool = True,
    saa_mode: str = "auto",
) -> BrinsonResponseDTO:
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)
    if pa_method not in ALLOWED_PA_METHODS:
        raise ValueError(f"pa_method must be one of {ALLOWED_PA_METHODS}")
    if saa_mode not in ("auto", "auto_drift", "proxy", "proxy_drift"):
        raise ValueError("saa_mode must be auto|auto_drift|proxy|proxy_drift")
    method = _resolve_mapping_method(fund_code, mapping_method)
    if method not in ALLOWED_MAPPING_METHODS:
        raise ValueError(f"mapping_method must be one of {ALLOWED_MAPPING_METHODS}")

    if start_date is None or end_date is None:
        d_start, d_end = _resolve_default_period(fund_code)
        start_date = start_date or d_start
        end_date = end_date or d_end

    # 종료일은 요청/기본 그대로(스킵 없음). 환매정산중은 표0 환매미지급금 라인으로 균형 + 배지 안내.
    data_pending = False
    data_note: str | None = None

    if start_date >= end_date:
        raise ValueError("start_date must be earlier than end_date")

    # 무위험 기간 누적수익률(%) — 샤프비율(프론트에서 252d 연율화)용. 실패 시 None.
    rf_period = _rf_period_pct(_to_yyyymmdd(start_date), _to_yyyymmdd(end_date))

    # 기간 종료일 기준 적용 리밸런싱(SAA DB) 으로 BM/SAA 구성 결정. proxy 면 안전자산 분해.
    bm_source, bm_components, _saa = _build_bm_meta(
        fund_code, method, _to_yyyymmdd(end_date),
        saa_mode=saa_mode, start_yyyymmdd=_to_yyyymmdd(start_date))

    sources: list[SourceBreakdown] = []
    warnings: list[str] = []
    is_fallback = False

    raw = _compute_cached(
        fund_code,
        _to_yyyymmdd(start_date), _to_yyyymmdd(end_date),
        method, saa_mode, fx_split,
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
            data_pending=data_pending,
            data_note=data_note,
            period_ap_return=0.0,
            period_bm_return=0.0,
            total_alloc=0.0,
            total_select=0.0,
            total_cross=0.0,
            total_excess=0.0,
            total_excess_relative=0.0,
            fx_contrib=0.0,
            residual=0.0,
            rf_period=rf_period,
            bm_source=bm_source,
            bm_components=bm_components,
            asset_rows=[],
            sec_contrib=[],
            daily_brinson=[],
        )

    sources.append(SourceBreakdown(component="pa", kind="db", note="dt.MA000410"))

    # BM 컴포넌트(지수)별 기간 기여/수익률 주입 (compute 산출, 구캐시엔 없음 → None 유지)
    _cstats = {s["name"]: s for s in (raw.get("bm_component_stats") or [])}
    for _c in bm_components:
        _s = _cstats.get(_c.name)
        if _s:
            _c.contrib = round(float(_s.get("contrib", 0.0)), 4)
            _c.ret = round(float(_s.get("ret", 0.0)), 4)

    pa_df = raw["pa_df"].copy()
    # BM 미설정 펀드: SAA(MP) 목표비중을 BM비중에 주입 → AP 대비 %p 비교가 동작(item1/5).
    # (수익률/기여 분해는 SAA 인덱스 정의가 없어 불가 → BM기여/Allocation 은 0 유지)
    if bm_source == "SAA" and _saa:
        # SAA 8분류 키(대체투자/유동성)를 Brinson 자산군명(대체/유동성및기타)으로 정규화
        _saa_b: dict[str, float] = {}
        for _k, _v in _saa.items():
            _bk = {"대체투자": "대체", "유동성": "유동성및기타"}.get(_k, _k)
            _saa_b[_bk] = _saa_b.get(_bk, 0.0) + float(_v)
        pa_df["BM비중"] = pa_df["자산군"].map(lambda a: _saa_b.get(a, 0.0))
    if pa_method == "5":
        pa_df = _collapse_5class(pa_df, method)
    if not fx_split and "FX" in set(pa_df["자산군"].astype(str)):
        pa_df = _drop_fx(pa_df)
    pa_df = _sort_pa_df(pa_df)

    # 빈 자산군 행 제거 — AP·BM 비중 및 AP·BM 기여가 모두 ≈0 (예: 미편입 '대체').
    # (유동성및기타처럼 BM비중/기여가 있으면 유지)
    def _nonempty(r) -> bool:
        return (
            abs(float(r.get("AP비중", 0) or 0)) > 1e-9
            or abs(float(r.get("BM비중", 0) or 0)) > 1e-9
            or abs(float(r.get("기여수익률", 0) or 0)) > 1e-9
            or abs(float(r.get("BM기여", 0) or 0)) > 1e-9
        )
    pa_df = pa_df[pa_df.apply(_nonempty, axis=1)].copy()

    # daily_class(추이/드롭다운)를 표에 남은 자산군으로 동기화
    # (FX 분리 off → FX 제거, 빈 '대체' 제거가 드롭다운에도 반영)
    _surviving = set(pa_df["자산군"].astype(str))
    _dc_df = raw.get("daily_class")
    if _dc_df is not None and not _dc_df.empty:
        _dc_df = _dc_df[_dc_df["asset_class"].isin(_surviving)]

    # 표0 AP 구성 = 기말 보유 스냅샷(build_holdings) + 환매정산중 플래그(배지 안내) — 한 번만 호출.
    ap_composition: list[BrinsonApCompositionDTO] = []
    try:
        from .holdings_service import build_holdings
        _hold = build_holdings(fund_code, lookthrough=True, as_of_date=end_date.isoformat())
        ap_composition = _build_ap_composition(_hold, method)
        data_pending = _hold.data_pending
        if _hold.data_note:
            data_note = _hold.data_note
    except Exception:
        pass

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
        data_pending=data_pending,
        data_note=data_note,
        period_ap_return=float(raw.get("period_ap_return", 0.0) or 0.0),
        period_bm_return=float(raw.get("period_bm_return", 0.0) or 0.0),
        total_alloc=float(raw.get("total_alloc", 0.0) or 0.0),
        total_select=float(raw.get("total_select", 0.0) or 0.0),
        total_cross=float(raw.get("total_cross", 0.0) or 0.0),
        total_excess=float(raw.get("total_excess", 0.0) or 0.0),
        total_excess_relative=float(raw.get("total_excess_relative", 0.0) or 0.0),
        fx_contrib=float(raw.get("fx_contrib", 0.0) or 0.0),
        residual=float(raw.get("residual", 0.0) or 0.0),
        rf_period=rf_period,
        bm_source=bm_source,
        bm_components=bm_components,
        asset_rows=_to_asset_rows(pa_df),
        sec_contrib=_to_sec_rows(raw.get("sec_contrib")),
        ap_composition=ap_composition,
        daily_brinson=_to_daily_rows(raw.get("daily_brinson")),
        daily_class=_to_daily_class_rows(_dc_df),
    )


def invalidate_cache() -> None:
    """관리용. NAV/PA 일일 갱신 후 호출."""
    _compute_cached.cache_clear()


# 성과분석 하단 기간 테이블 컬럼 (1M/3M/6M/1Y/YTD/SI)
_PERIOD_KEYS = ["1M", "3M", "6M", "1Y", "YTD", "SI"]


def _period_start(period: str, end: date, inception: date | None) -> date | None:
    """기간 시작일 — end 기준 relativedelta / YTD=전년말 / SI=inception.
    inception 보다 이르면 inception 으로 clamp. 시작≥종료면 None(스킵)."""
    from dateutil.relativedelta import relativedelta
    if period == "1M":
        s = end - relativedelta(months=1)
    elif period == "3M":
        s = end - relativedelta(months=3)
    elif period == "6M":
        s = end - relativedelta(months=6)
    elif period == "1Y":
        s = end - relativedelta(years=1)
    elif period == "YTD":
        s = date(end.year, 1, 1)  # base=전년말 (엔진 start=첫 수익 인식일 규약)
    elif period == "SI":
        s = inception
    else:
        return None
    if s is None:
        return None
    if inception and s < inception:
        s = inception
    if s >= end:
        return None
    return s


def build_brinson_periods(
    fund_code: str,
    *,
    end_date: date | None = None,
    mapping_method: str | None = None,
    pa_method: str = "8",
    fx_split: bool = False,
    saa_mode: str = "auto",
) -> BrinsonPeriodsResponseDTO:
    """기간별(1M/3M/6M/1Y/YTD/SI) Brinson 효과 — 성과분석 하단 토글 테이블용.

    각 기간 [start, end] 에 대해 build_brinson 을 호출(캐시 재사용)해 total 효과 +
    자산군별 분해를 모은다. golden 로직 불변(동일 compute 재사용). 첫 호출은 기간 수만큼
    compute 라 느릴 수 있으나 이후 캐시.
    """
    if fund_code not in FUND_LIST:
        raise KeyError(fund_code)

    end = end_date or (datetime.now().date() - timedelta(days=1))
    inc_raw = str((FUND_META.get(fund_code, {}) or {}).get("inception") or "").strip()
    inception: date | None = None
    if len(inc_raw) == 8 and inc_raw.isdigit():
        inception = date(int(inc_raw[:4]), int(inc_raw[4:6]), int(inc_raw[6:8]))

    warnings: list[str] = []
    periods: list[BrinsonPeriodDTO] = []
    for pk in _PERIOD_KEYS:
        s = _period_start(pk, end, inception)
        if s is None:
            continue
        try:
            r = build_brinson(
                fund_code, start_date=s, end_date=end,
                mapping_method=mapping_method, pa_method=pa_method,
                fx_split=fx_split, saa_mode=saa_mode,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{pk} 계산 실패: {type(exc).__name__}")
            continue
        # 자산군별 비중은 기간 평균(daily_class) 사용 — asset_rows 의 ap_weight 는 '종료일
        # 스냅샷'이라 모든 기간이 같은 종료일 → 비중차가 전 기간 동일해지고 효과(경로적분)와
        # 부호도 안 맞는 문제. 기간 평균으로 (a) 비중차가 기간마다 달라지고 a×b 가 효과에 근접.
        wsum: dict[str, list[float]] = {}
        for dc in r.daily_class:
            e = wsum.setdefault(dc.asset_class, [0.0, 0.0, 0.0])
            e[0] += float(dc.ap_weight); e[1] += float(dc.bm_weight); e[2] += 1.0
        avg_w = {ac: (v[0] / v[2], v[1] / v[2]) for ac, v in wsum.items() if v[2] > 0}
        rows = []
        for ar in r.asset_rows:
            aw, bw = avg_w.get(ar.asset_class, (ar.ap_weight, ar.bm_weight))
            rows.append(BrinsonPeriodRowDTO(
                asset_class=ar.asset_class, ap_weight=round(aw, 2),
                bm_weight=round(bw, 2), ap_return=ar.ap_return,
                bm_return=ar.bm_return, alloc_effect=ar.alloc_effect,
                select_effect=ar.select_effect, cross_effect=ar.cross_effect,
            ))
        periods.append(BrinsonPeriodDTO(
            period=pk, start_date=s.isoformat(),
            has_bm=(r.bm_source != "none"),
            total_alloc=r.total_alloc, total_select=r.total_select,
            total_cross=r.total_cross, total_excess=r.total_excess,
            rows=rows,
        ))

    return BrinsonPeriodsResponseDTO(
        meta=BaseMeta(
            source="db", sources=[SourceBreakdown(component="brinson_periods", kind="db")],
            is_fallback=not periods, warnings=warnings, generated_at=datetime.now(timezone.utc),
        ),
        fund_code=fund_code, end_date=end.isoformat(), periods=periods,
    )
