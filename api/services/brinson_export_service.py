"""성과분석(Brinson) 엑셀 스냅샷 export.

GET /funds/{code}/brinson/export — 화면 조회조건 그대로 xlsx 생성 (2026-07-03 사용자 지정).

시트 구성:
  1. Overview          : 펀드정보 + 벤치 구성 + 조회기간 KPI + 기간별 수익률(조회 종료일 앵커)
                         + AP vs BM(SAA)/proxy 수익률 차트
  2. 성과분석({기간})    : 조회기간 기준 — 표1(방법1)/표2(방법3)/표3(계층→종목) + Dur/YTM
  3. 성과분석(YTD)      : 동일 양식, YTD(전년말~조회 종료일) 기준 (조회가 YTD 면 생략)
  4. 시계열(기준가)      : 설정일~최신 전체기간 — 기준가/지수 + 수익률(%) 컬럼.
                         BM 없는 펀드는 등록 SAA·proxy 두 벌 (사용자 확정: 차트+시계열만)
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta

import pandas as pd

from config.funds import FUND_META

from .brinson_service import build_brinson
from .overview_service import (
    _compute_bm_period_returns,
    _load_saa_series,
    build_overview,
    build_period_returns,
)

# 기간별 수익률 표 컬럼 (프론트 PERIOD_COLS 동일)
_PERIOD_COLS = [("MTD", "MTD"), ("1M", "1M"), ("3M", "3M"), ("6M", "6M"),
                ("1Y", "1Y"), ("YTD", "YTD"), ("SI", "설정후")]

_TS_SHEET = "시계열(기준가)"

_C_AP = "#557EAA"     # 브랜드 스틸블루 (NavChart 동일)
_C_BENCH = "#B07A2B"  # SAA/BM brown
_C_PROXY = "#8A8F98"


def _proxy_series_df(fund_code: str, inc_str: str) -> "pd.DataFrame | None":
    """proxy SAA(안전자산→KIS 종합채권 / 나머지→ACWI) 합성지수 — 시계열/차트용."""
    try:
        from modules.data_loader import _build_proxy_bm_info, load_composite_bm_prices
        info = _build_proxy_bm_info(fund_code, inc_str)
        if not info or not info.get("components"):
            return None
        warm = (datetime.strptime(inc_str, "%Y%m%d") - timedelta(days=30)).strftime("%Y%m%d")
        df = load_composite_bm_prices(info["components"], warm)
        return df if df is not None and len(df) > 0 else None
    except Exception:
        return None


def _align_rebase(df: "pd.DataFrame", nav_s: "pd.Series") -> "pd.Series | None":
    """합성지수(기준일자, value)를 NAV 날짜에 ffill 정렬 후 첫 공통 유효일의 AP 기준가로 리베이스.

    (head 결측이어도 첫 유효일부터 AP 기준가 레벨에서 합류 — 차트 비교 가능)
    """
    if df is None or len(df) == 0 or "value" not in df.columns:
        return None
    s = pd.Series(
        df["value"].astype(float).values, index=pd.to_datetime(df["기준일자"]),
    ).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    aligned = s.reindex(nav_s.index, method="ffill")
    valid = aligned.notna() & nav_s.notna() & (aligned != 0)
    if not valid.any():
        return None
    i0 = valid.idxmax()
    return aligned * (float(nav_s.loc[i0]) / float(aligned.loc[i0]))


def _bench_columns(fund_code: str, ov, inc_str: str, as_of) -> list[tuple[str, "pd.Series"]]:
    """시계열 시트 벤치 컬럼 — BM 펀드=[BM], SAA 펀드=[SAA, proxy] (AP 기준가 리베이스)."""
    nav_idx = pd.DatetimeIndex(pd.to_datetime([p.date_ for p in ov.nav_series]))
    nav_s = pd.Series([p.nav for p in ov.nav_series], index=nav_idx)
    cols: list[tuple[str, pd.Series]] = []
    if ov.benchmark_kind == "BM":
        bm = pd.Series(
            [float(p.bm) if p.bm is not None else float("nan") for p in ov.nav_series],
            index=nav_idx,
        )
        if bm.notna().any():
            cols.append(("BM", bm))
        return cols
    # BM 없는 펀드: 등록 SAA + proxy 두 컬럼
    saa_df = _load_saa_series(fund_code, inc_str, as_of)
    s = _align_rebase(saa_df, nav_s)
    if s is not None:
        cols.append(("SAA", s))
    p = _align_rebase(_proxy_series_df(fund_code, inc_str), nav_s)
    if p is not None:
        cols.append(("proxy", p))
    return cols


# 방법3 자산군 → 방법1(주식/채권/대체) 상위 매핑. 그 외(FX/유동성및기타/기타)는 자기 자신이 L1.
_L1_OF = {"국내주식": "주식", "해외주식": "주식",
          "국내채권": "채권", "해외채권": "채권",
          "대체": "대체", "대체투자": "대체"}


def _duration_info(fund_code: str, end_d: date):
    """편입종목 탭 동일 소스(duration_fetcher) — 종목별 Duration/YTM + 요약.

    returns (dur_by_name: {종목명: (duration|None, ytm|None)}, summary DTO|None)
    자산군/펀드 레벨은 시트에서 비중 SUMPRODUCT 수식으로 계산 (2026-07-03 사용자 지정).
    """
    try:
        from .holdings_service import build_holdings
        hold = build_holdings(fund_code, lookthrough=True, as_of_date=end_d.isoformat())
    except Exception:
        return {}, None
    dur_by_name: dict[str, tuple] = {}
    for it in hold.holdings_items:
        d = getattr(it, "duration", None)
        y = getattr(it, "ytm", None)
        if d is None and y is None:
            continue
        dur_by_name[it.item_nm] = (
            None if d is None else float(d),
            None if y is None else float(y),
        )
    return dur_by_name, hold.duration_summary


def _period_label(s: date, e: date) -> str:
    """시트명용 기간 라벨 — 1M/3M/6M/1Y/YTD, 그 외 '기간'."""
    if s == date(e.year - 1, 12, 31):
        return "YTD"
    d = (e - s).days
    if 25 <= d <= 35:
        return "1M"
    if 80 <= d <= 95:
        return "3M"
    if 170 <= d <= 190:
        return "6M"
    if 350 <= d <= 380:
        return "1Y"
    return "기간"


def _write_hierarchy_sheet(wb, br1, br3, dur, fmts, sheet_name: str) -> None:
    """자산군별(계층) 시트 — 주식/채권/대체(방법1) → 국내/해외…(방법3) → 종목 3-레벨.

    컬럼 그룹: 비중(B~D) | 기여(F~H) | Norm(J~K) | Duration·YTM(M~N) — 그룹 사이 좁은 갭 열.
    소계(L2)/중계(L1)/합계의 비중·기여·차이 = 하위 셀 참조 **수식**, Duration·YTM = 비중
    SUMPRODUCT 수식 (2026-07-03 사용자 지정). Norm 수익률만 raw 유지 — 일별 금액가중이라
    기간 비중×수익률 SUMPRODUCT 로 재구성 불가(검증: 국내채권 -2.145 vs 백엔드 -2.06).
    종목합≠자산군 기여 소계면 '기타(잔차)' 행으로 보정 (UI 표1 동일 규칙).
    """
    dur_by_name, dsum = dur
    lbl = "SAA" if br3.bm_source == "SAA" else "BM"
    ws = wb.add_worksheet(sheet_name)
    ws.hide_gridlines(2)
    ws.write(0, 0, f"{br3.fund_name} ({br3.fund_code}) — 자산군별 성과 (계층: 방법1 → 방법3 → 종목)",
             fmts["title"])
    ws.write(1, 0, f"기간 {br3.start_date} ~ {br3.end_date} · FX {'분리' if br3.fx_split else '포함'}"
                   f" · 벤치 {br3.bm_source}", fmts["muted"])
    # 컬럼 인덱스: 4/8/11 = 갭(빈 열). B=AP비중 C={lbl}비중 D=차이 F=AP기여 G={lbl}기여
    # H=초과기여 J=APNorm K={lbl}Norm M=Duration N=YTM
    headers = {0: "구분", 1: "AP비중(%)", 2: f"{lbl}비중(%)", 3: "차이(%p)",
               5: "AP기여(%)", 6: f"{lbl}기여(%)", 7: "초과기여(%)",
               9: "AP수익률(Norm, %)", 10: f"{lbl}수익률(Norm, %)",
               12: "Duration(년)", 13: "YTM(%)"}

    def _write_header(rr: int) -> None:
        for c, h in headers.items():
            ws.write(rr, c, h, fmts["head"])

    # FX 행 별도 유지 (2026-07-03 원복 — 환율 따로, 유동성및기타 따로)
    br1_rows = list(br1.asset_rows)
    br3_rows = list(br3.asset_rows)

    # 종목: 방법3 분류 기준, 자산군별 비중 내림차순.
    # 이름=자산군명인 집계성 행(유동성 잔차 등)은 제외 → 잔차 행으로 흡수 (UI 표0 동일 규칙)
    secs_by: dict[str, list] = {}
    for s in br3.sec_contrib:
        if s.item_nm == s.asset_class:
            continue
        secs_by.setdefault(s.asset_class, []).append(s)
    for arr in secs_by.values():
        arr.sort(key=lambda x: -x.weight_pct)
    # 방법3 leaf 를 L1 로 그룹핑 (정렬 유지 → 국내→해외 순)
    leaf_by_l1: dict[str, list] = {}
    for rowv in br3_rows:
        leaf_by_l1.setdefault(_L1_OF.get(rowv.asset_class, rowv.asset_class), []).append(rowv)

    # ── 요약 테이블 1·2 용 Dur/YTM (python 계산 — 종목 PA비중 가중, 커버 비중 기준) ──
    def _cls_dur_ytm(leaf_names: list) -> tuple:
        wd = wy = cwd = cwy = 0.0
        for cn in leaf_names:
            for s in secs_by.get(cn, []):
                dy = dur_by_name.get(s.item_nm)
                if not dy:
                    continue
                if dy[0] is not None:
                    wd += s.weight_pct * dy[0]
                    cwd += s.weight_pct
                if dy[1] is not None:
                    wy += s.weight_pct * dy[1]
                    cwy += s.weight_pct
        return (wd / cwd if cwd else None, wy / cwy if cwy else None)

    def _flat_table(rr: int, title: str, rows_src, leaf_names_of) -> int:
        """요약(플랫) 테이블 — 자산군 행 + 합계. 동일 컬럼 양식, 값은 raw. 다음 행 반환."""
        ws.write(rr, 0, title, fmts["title"])
        rr += 1
        _write_header(rr)
        rr += 1
        tw = tbw = tc = tbc = te = 0.0
        for rowv in rows_src:
            ex = rowv.alloc_effect + rowv.select_effect + rowv.cross_effect
            ws.write(rr, 0, rowv.asset_class, fmts["l2"])
            ws.write_number(rr, 1, rowv.ap_weight, fmts["num"])
            ws.write_number(rr, 2, rowv.bm_weight, fmts["num"])
            ws.write_number(rr, 3, rowv.ap_weight - rowv.bm_weight, fmts["num_s"])
            ws.write_number(rr, 5, rowv.contrib_return, fmts["num_s"])
            ws.write_number(rr, 6, rowv.bm_contrib, fmts["num_s"])
            ws.write_number(rr, 7, ex, fmts["num_s"])
            ws.write_number(rr, 9, rowv.ap_return, fmts["num_s"])
            ws.write_number(rr, 10, rowv.bm_return, fmts["num_s"])
            _d, _y = _cls_dur_ytm(leaf_names_of(rowv.asset_class))
            ws.write_number(rr, 12, _d if _d is not None else 0.0, fmts["durn"])
            ws.write_number(rr, 13, _y if _y is not None else 0.0, fmts["durn"])
            tw += rowv.ap_weight; tbw += rowv.bm_weight
            tc += rowv.contrib_return; tbc += rowv.bm_contrib; te += ex
            rr += 1
        ws.write(rr, 0, "합계", fmts["thead"])
        for c, v in [(1, tw), (2, tbw), (3, tw - tbw), (5, tc), (6, tbc), (7, te)]:
            ws.write_number(rr, c, v, fmts["tnum"])
        ws.write_number(rr, 9, br3.period_ap_return, fmts["tnum"])
        ws.write_number(rr, 10, br3.period_bm_return, fmts["tnum"])
        # 펀드 레벨 Dur/YTM = Σ(비중×값)/총비중 (채권비중 반영)
        _nd = _ny = 0.0
        for _cls, _ss in secs_by.items():
            for s in _ss:
                dy = dur_by_name.get(s.item_nm)
                if not dy:
                    continue
                if dy[0] is not None:
                    _nd += s.weight_pct * dy[0]
                if dy[1] is not None:
                    _ny += s.weight_pct * dy[1]
        if tw:
            ws.write_number(rr, 12, _nd / tw, fmts["durt"])
            ws.write_number(rr, 13, _ny / tw, fmts["durt"])
        return rr + 2  # 테이블 사이 빈 행

    _l1_leaves = {"주식": ["국내주식", "해외주식"], "채권": ["국내채권", "해외채권"]}
    r0 = 3
    r0 = _flat_table(r0, "1. 주식 · 채권 · 대체 (방법1)", br1_rows,
                     lambda ac: _l1_leaves.get(ac, [ac]))
    r0 = _flat_table(r0, "2. 세부 자산군 (방법3)", br3_rows, lambda ac: [ac])

    # ── 3. 계층 상세 테이블 (자산군 → 종목, 수식) ──
    ws.write(r0, 0, "3. 자산군 계층 → 종목 상세", fmts["title"])
    r0 += 1
    _write_header(r0)

    def _wavg(ranges: list, vcol: str, denom: str) -> str:
        """비중(B) 가중평균 수식 — 분모 = 해당 행 비중 셀 (미커버 종목은 0 으로 간주해 희석).

        비채권 셀에 0 을 채워 전 범위가 숫자 → SUMPRODUCT #VALUE! 원천 차단 (2026-07-03
        사용자 리포트 대응). 결과 0 은 durn/durl1/durt 서식이 화면에서 숨김.
        """
        num = "+".join(f"SUMPRODUCT({vcol}{s}:{vcol}{e},$B{s}:$B{e})" for s, e in ranges)
        return f"=IFERROR(IF(({denom})=0,0,({num})/({denom})),0)"

    def _sum_cells(col: str, xl_rows: list) -> str:
        return "=" + "+".join(f"{col}{x}" for x in xl_rows)

    def _sec_rows(rr: int, leaf):
        """leaf 자산군의 종목 행 + 잔차 행. returns (다음 행, (엑셀시작행, 엑셀끝행) | None)."""
        secs = secs_by.get(leaf.asset_class, [])
        if not secs:
            return rr, None
        s_xl = rr + 1
        sec_sum = 0.0
        for s in secs:
            ws.write(rr, 0, s.item_nm, fmts["l3"])
            ws.write_number(rr, 1, s.weight_pct, fmts["l3w"])
            ws.write_number(rr, 5, s.contrib_pct, fmts["l3n"])
            ws.write_number(rr, 9, s.return_pct, fmts["l3n"])
            # Dur/YTM 없는(비채권) 종목은 0 — 서식이 0 을 숨겨 안 보임, 수식 범위는 전부 숫자
            dy = dur_by_name.get(s.item_nm) or (None, None)
            ws.write_number(rr, 12, dy[0] if dy[0] is not None else 0.0, fmts["durl3"])
            ws.write_number(rr, 13, dy[1] if dy[1] is not None else 0.0, fmts["durl3"])
            sec_sum += s.contrib_pct
            rr += 1
        resid = leaf.contrib_return - sec_sum
        if abs(resid) >= 0.005:
            ws.write(rr, 0, "기타(잔차)", fmts["l3"])
            ws.write_number(rr, 5, resid, fmts["l3n"])
            ws.write_number(rr, 12, 0.0, fmts["durl3"])
            ws.write_number(rr, 13, 0.0, fmts["durl3"])
            rr += 1
        return rr, (s_xl, rr)  # 끝행 = 잔차 포함 (SUM 범위: 비중은 잔차 셀이 빈칸이라 무해)

    def _class_row(rr: int, rowv, name: str, level: str,
                   ranges: list | None = None, child_xl: list | None = None) -> None:
        """소계/중계 행 — 비중·기여·차이는 수식, Norm 은 raw. Dur/YTM 은 종목 SUMPRODUCT."""
        nf, wf, sf = ((fmts["l1"], fmts["l1w"], fmts["l1n"]) if level == "l1"
                      else (fmts["l2"], fmts["num"], fmts["num_s"]))
        xr = rr + 1
        ex = rowv.alloc_effect + rowv.select_effect + rowv.cross_effect
        ws.write(rr, 0, name, nf)
        if child_xl:
            # 중계(L1): 자식 소계 셀 합
            ws.write_formula(rr, 1, _sum_cells("B", child_xl), wf, rowv.ap_weight)
            ws.write_formula(rr, 2, _sum_cells("C", child_xl), wf, rowv.bm_weight)
            ws.write_formula(rr, 5, _sum_cells("F", child_xl), sf, rowv.contrib_return)
            ws.write_formula(rr, 6, _sum_cells("G", child_xl), sf, rowv.bm_contrib)
            ws.write_formula(rr, 7, _sum_cells("H", child_xl), sf, ex)
        elif ranges:
            # 소계(L2/자체leaf L1): AP측 = 종목 셀 합, BM측 = raw (종목 레벨 BM 없음)
            s, e = ranges[0]
            ws.write_formula(rr, 1, f"=SUM(B{s}:B{e})", wf, rowv.ap_weight)
            ws.write_number(rr, 2, rowv.bm_weight, wf)
            ws.write_formula(rr, 5, f"=SUM(F{s}:F{e})", sf, rowv.contrib_return)
            ws.write_number(rr, 6, rowv.bm_contrib, sf)
            ws.write_number(rr, 7, ex, sf)
        else:
            for c, v in [(1, rowv.ap_weight), (2, rowv.bm_weight)]:
                ws.write_number(rr, c, v, wf)
            for c, v in [(5, rowv.contrib_return), (6, rowv.bm_contrib), (7, ex)]:
                ws.write_number(rr, c, v, sf)
        ws.write_formula(rr, 3, f"=B{xr}-C{xr}", sf, rowv.ap_weight - rowv.bm_weight)
        ws.write_number(rr, 9, rowv.ap_return, sf)
        ws.write_number(rr, 10, rowv.bm_return, sf)
        durf = fmts["durl1"] if level == "l1" else fmts["durn"]
        if ranges:
            ws.write_formula(rr, 12, _wavg(ranges, "M", denom=f"B{xr}"), durf)
            ws.write_formula(rr, 13, _wavg(ranges, "N", denom=f"B{xr}"), durf)
        else:
            ws.write_number(rr, 12, 0.0, durf)
            ws.write_number(rr, 13, 0.0, durf)

    r = r0 + 1
    l1_xl: list[int] = []      # L1 엑셀 행번호 (합계 수식용)
    all_ranges: list = []      # 전 종목 (s,e) — 합계 Dur/YTM SUMPRODUCT 용
    for l1 in br1_rows:
        l1_r = r
        r += 1
        l1_xl.append(l1_r + 1)
        children = leaf_by_l1.get(l1.asset_class, [])
        self_leaf = len(children) == 1 and children[0].asset_class == l1.asset_class
        if self_leaf or not children:
            # L1 자신이 leaf (대체/FX/유동성및기타 등) → L2 생략, 종목 바로
            leaf = children[0] if children else l1
            r, rng = _sec_rows(r, leaf)
            rngs = [rng] if rng else []
            all_ranges += rngs
            _class_row(l1_r, l1, l1.asset_class, "l1", ranges=rngs or None)
        else:
            ch_xl: list[int] = []
            ch_rngs: list = []
            for ch in children:
                ch_r = r
                r += 1
                ch_xl.append(ch_r + 1)
                r, rng = _sec_rows(r, ch)
                rngs = [rng] if rng else []
                all_ranges += rngs
                ch_rngs += rngs
                _class_row(ch_r, ch, "  " + ch.asset_class, "l2", ranges=rngs or None)
            _class_row(l1_r, l1, l1.asset_class, "l1",
                       ranges=ch_rngs or None, child_xl=ch_xl)

    # 합계 — L1 셀 합 수식. Norm 은 기간 수익률(raw). Dur/YTM = Σ(비중×값)/합계 AP비중(채권비중 반영)
    xr = r + 1
    ws.write(r, 0, "합계", fmts["thead"])
    ws.write_formula(r, 1, _sum_cells("B", l1_xl), fmts["tnum"])
    ws.write_formula(r, 2, _sum_cells("C", l1_xl), fmts["tnum"])
    ws.write_formula(r, 3, f"=B{xr}-C{xr}", fmts["tnum"])
    ws.write_formula(r, 5, _sum_cells("F", l1_xl), fmts["tnum"])
    ws.write_formula(r, 6, _sum_cells("G", l1_xl), fmts["tnum"])
    ws.write_formula(r, 7, _sum_cells("H", l1_xl), fmts["tnum"])
    ws.write_number(r, 9, br1.period_ap_return, fmts["tnum"])
    ws.write_number(r, 10, br1.period_bm_return, fmts["tnum"])
    if all_ranges:
        ws.write_formula(r, 12, _wavg(all_ranges, "M", denom=f"B{xr}"), fmts["durt"])
        ws.write_formula(r, 13, _wavg(all_ranges, "N", denom=f"B{xr}"), fmts["durt"])
    else:
        ws.write_number(r, 12, 0.0, fmts["durt"])
        ws.write_number(r, 13, 0.0, fmts["durt"])

    ws.set_column(0, 0, 34)
    ws.set_column(1, 3, 11)
    ws.set_column(4, 4, 1.5)   # 갭: 비중 | 기여
    ws.set_column(5, 7, 11)
    ws.set_column(8, 8, 1.5)   # 갭: 기여 | Norm
    ws.set_column(9, 10, 17)   # "AP수익률(Norm, %)" 헤더 전체 표시
    ws.set_column(11, 11, 1.5)  # 갭: Norm | Dur·YTM
    ws.set_column(12, 13, 11)  # "Duration(년)" 헤더 전체 표시
    note_r = r + 2
    ws.write(note_r, 0, "※ 표3: 소계/중계/합계의 비중·기여·차이=하위 셀 수식, Duration·YTM=비중 "
                        "SUMPRODUCT/행 비중 (비채권 셀은 값 0, 서식으로 숨김 — 미커버 종목은 0 간주 희석).",
             fmts["muted"])
    ws.write(note_r + 1, 0, "※ Norm수익률 소계/중계는 raw — 일별 금액가중이라 기간 비중×수익률 "
                            "SUMPRODUCT 로 재구성되지 않음 (배분비중 미반영, AP는 기간 매매 반영).",
             fmts["muted"])
    if dsum:
        _db = f"{dsum.duration_bond:.2f}년" if dsum.duration_bond is not None else "—"
        _do = f"{dsum.duration_overall:.2f}년" if dsum.duration_overall is not None else "—"
        _cov = f"{dsum.coverage_ratio * 100:.0f}%" if dsum.coverage_ratio is not None else "—"
        ws.write(note_r + 2, 0,
                 f"※ 참고(기말 보유 스냅샷 기준): Duration(채권) = {_db} · Duration(펀드) = {_do}"
                 f" · 커버리지 {_cov} — 시트 수식은 PA 기간 비중이라 미세 차이 가능.",
                 fmts["muted"])


def build_brinson_export_xlsx(
    fund_code: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    mapping_method: str | None = None,
    pa_method: str = "8",
    fx_split: bool = False,
    saa_mode: str = "auto",
) -> tuple[bytes, str]:
    """xlsx bytes + 파일명(ascii) 생성. 화면 조회조건 스냅샷 + 방법1 재계산 + 전체기간 시계열."""
    br = build_brinson(
        fund_code, start_date=start_date, end_date=end_date,
        mapping_method=mapping_method, pa_method=pa_method,
        fx_split=fx_split, saa_mode=saa_mode,
    )
    # 주식/채권/대체 = 방법1 재계산 (사용자 확정 — R 로직 정확 수치)
    br1 = build_brinson(
        fund_code, start_date=br.start_date, end_date=br.end_date,
        mapping_method="방법1", pa_method=pa_method,
        fx_split=fx_split, saa_mode=saa_mode,
    )
    # 계층 시트 L2/종목 = 방법3 (스냅샷이 방법3 이 아니면 재계산 — 계층 프레임 고정)
    br3 = br if br.mapping_method == "방법3" else build_brinson(
        fund_code, start_date=br.start_date, end_date=br.end_date,
        mapping_method="방법3", pa_method=pa_method,
        fx_split=fx_split, saa_mode=saa_mode,
    )
    ov = build_overview(fund_code)
    prt = build_period_returns(fund_code, br.end_date.isoformat())
    inc_str = str(FUND_META.get(fund_code, {}).get("inception", "20220101"))
    # as_of 는 date 객체로 — _load_saa_series 가 .strftime 을 호출 (str 이면 예외→proxy 폴백 버그)
    bench_cols = _bench_columns(fund_code, ov, inc_str, br.end_date)
    lbl = "SAA" if br.bm_source == "SAA" else "BM"

    import xlsxwriter
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})

    # 전체 폰트 = Pretendard (셀·차트 포함, 2026-07-03 사용자 지정 — 미설치 PC 는 기본 폰트 폴백)
    _FN = "Pretendard"
    wb.formats[0].set_font_name(_FN)  # 무서식 셀의 기본 폰트

    def _fmt(props: dict):
        return wb.add_format({"font_name": _FN, **props})

    fmts = {
        "title": _fmt({"bold": True, "font_size": 13}),
        "muted": _fmt({"font_color": "#808891", "font_size": 9}),
        "head": _fmt({"bold": True, "bg_color": "#EEF1F5", "border": 1, "align": "center"}),
        "thead": _fmt({"bold": True, "top": 1}),
        "cell": _fmt({}),
        "k": _fmt({"font_color": "#606870"}),
        "num": _fmt({"num_format": "0.00"}),
        "num_s": _fmt({"num_format": "+0.00;-0.00;0.00"}),
        "tnum": _fmt({"bold": True, "top": 1, "num_format": "+0.00;-0.00;0.00"}),
        "nav": _fmt({"num_format": "#,##0.00"}),
        "dt": _fmt({"num_format": "yyyy-mm-dd"}),
        # 계층 시트 레벨별 포맷
        "l1": _fmt({"bold": True, "bg_color": "#F2F5F8"}),
        "l1w": _fmt({"bold": True, "bg_color": "#F2F5F8", "num_format": "0.00"}),
        "l1n": _fmt({"bold": True, "bg_color": "#F2F5F8", "num_format": "+0.00;-0.00;0.00"}),
        "l2": _fmt({}),
        "l3": _fmt({"font_color": "#808891", "indent": 2}),
        "l3w": _fmt({"font_color": "#808891", "num_format": "0.00"}),
        "l3n": _fmt({"font_color": "#808891", "num_format": "+0.00;-0.00;0.00"}),
        # Dur/YTM 전용 — 값 0 은 표시 안 함(서식 3번째 섹션 공백) → 비채권 셀에 0 을 넣어
        # 수식(SUMPRODUCT) 전 범위를 숫자로 유지하면서 눈에는 안 보이게 (2026-07-03 사용자 지정)
        "durn": _fmt({"num_format": "0.00;-0.00;;"}),
        "durl1": _fmt({"bold": True, "bg_color": "#F2F5F8", "num_format": "0.00;-0.00;;"}),
        "durl3": _fmt({"font_color": "#808891", "num_format": "0.00;-0.00;;"}),
        "durt": _fmt({"bold": True, "top": 1, "num_format": "0.00;-0.00;;"}),
    }

    # ── 1) Overview 시트 ──
    ws = wb.add_worksheet("Overview")
    ws.hide_gridlines(2)
    ws.write(0, 0, f"{br.fund_name} ({br.fund_code}) 성과분석 스냅샷", fmts["title"])
    ws.write(1, 0, f"생성 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 조회기간 {br.start_date} ~ {br.end_date}"
                   f" · 분류 {br.mapping_method} · FX {'분리' if br.fx_split else '포함'} · 벤치 {br.bm_source}"
                   f"{'' if saa_mode == 'auto' else f' ({saa_mode})'}", fmts["muted"])
    fm = ov.fund_meta
    info_rows = [
        ("설정일", str(fm.inception) if fm and fm.inception else "—"),
        ("표준코드", (fm.ticker if fm and fm.ticker else "—")),
        ("기준가(최신)", f"{fm.nav:,.2f}" if fm and fm.nav is not None else "—"),
        ("목표수익률(연)", f"{fm.target_return_annual * 100:.1f}%"
         if fm and fm.target_return_annual is not None else "—"),
    ]
    for c in ov.cards:
        info_rows.append((
            {"since_inception": "설정후 수익률", "ytd": "YTD 수익률",
             "vol": "변동성(연환산)", "mdd": "MDD"}.get(c.key, c.label),
            f"{c.value * 100:.2f}%",
        ))
    r = 3
    for k, v in info_rows:
        ws.write(r, 0, k, fmts["k"])
        ws.write(r, 1, v)
        r += 1

    # (벤치마크 구성 · 조회기간 성과 표는 2026-07-03 사용자 지시로 제거)

    # 기간별 수익률 + proxy 기준 — side by side (1열 갭, 2026-07-03 사용자 지정)
    _proxy_ser = next((s for n, s in bench_cols if n == "proxy"), None)
    _ppr: dict = {}
    if _proxy_ser is not None:
        _ps = _proxy_ser[_proxy_ser.index <= pd.Timestamp(br.end_date)].dropna()
        if len(_ps) >= 2:
            _ppr = _compute_bm_period_returns(_ps)

    def _wrow(rr, name, dic, c0=0):
        ws.write(rr, c0, name, fmts["cell"])
        for cc, (key, _) in enumerate(_PERIOD_COLS):
            v = dic.get(key)
            if v is None:
                ws.write(rr, c0 + cc + 1, "—")
            else:
                ws.write_number(rr, c0 + cc + 1, v * 100, fmts["num_s"])

    r += 1
    tbl_r = r
    ws.write(tbl_r, 0, f"기간별 수익률 (기준 {prt.end_date})", fmts["title"])
    ws.write(tbl_r + 1, 0, "구분", fmts["head"])
    for c, (_, h) in enumerate(_PERIOD_COLS):
        ws.write(tbl_r + 1, c + 1, h, fmts["head"])
    _wrow(tbl_r + 2, "AP 수익률(%)", prt.period_returns)
    _wrow(tbl_r + 3, f"{lbl} 수익률(%)", prt.bm_period_returns)
    ex = {k: prt.period_returns[k] - prt.bm_period_returns[k]
          for k in prt.period_returns if k in prt.bm_period_returns}
    _wrow(tbl_r + 4, "초과(%p)", ex)
    if _ppr:
        _c0 = 9  # J열 (I=갭 1열)
        ws.write(tbl_r, _c0, "기간별 수익률 — proxy 기준", fmts["title"])
        ws.write(tbl_r + 1, _c0, "구분", fmts["head"])
        for c, (_, h) in enumerate(_PERIOD_COLS):
            ws.write(tbl_r + 1, _c0 + c + 1, h, fmts["head"])
        _wrow(tbl_r + 2, "AP 수익률(%)", prt.period_returns, _c0)
        _wrow(tbl_r + 3, "proxy 수익률(%)", _ppr, _c0)
        _ex2 = {k: prt.period_returns[k] - _ppr[k] for k in prt.period_returns if k in _ppr}
        _wrow(tbl_r + 4, "초과(%p)", _ex2, _c0)
    chart_row = tbl_r + 6  # 라인차트 = 기간별 수익률 표 하단 (2026-07-03 사용자 지정)

    # 컬럼폭 — 테이블 필드명/값 기준 (타이틀·주석 길이 미반영, 2026-07-03 사용자 지정)
    ws.set_column(0, 0, 17)   # 라벨/구분 ("자산배분효과(%)" 등)
    ws.set_column(1, 1, 13)   # 값/자산군/MTD
    ws.set_column(2, 7, 9)    # 기간 컬럼
    ws.set_column(8, 8, 2)    # 갭
    ws.set_column(9, 9, 13)   # proxy 표 구분
    ws.set_column(10, 16, 9)  # proxy 표 기간 컬럼

    # ── 2·3) 성과분석 시트 — 조회기간 + YTD (2026-07-03 사용자 지정) ──
    dur_info = _duration_info(fund_code, br.end_date)
    _lbl1 = _period_label(br.start_date, br.end_date)
    _write_hierarchy_sheet(wb, br1, br3, dur_info, fmts, f"성과분석({_lbl1})")
    if _lbl1 != "YTD":
        _ytd_s = date(br.end_date.year - 1, 12, 31)
        try:
            _inc_d = datetime.strptime(inc_str, "%Y%m%d").date()
            if _inc_d > _ytd_s:
                _ytd_s = _inc_d
        except ValueError:
            pass
        if _ytd_s < br.end_date:
            try:
                br1y = build_brinson(
                    fund_code, start_date=_ytd_s, end_date=br.end_date,
                    mapping_method="방법1", pa_method=pa_method,
                    fx_split=fx_split, saa_mode=saa_mode,
                )
                br3y = build_brinson(
                    fund_code, start_date=_ytd_s, end_date=br.end_date,
                    mapping_method="방법3", pa_method=pa_method,
                    fx_split=fx_split, saa_mode=saa_mode,
                )
                _write_hierarchy_sheet(wb, br1y, br3y, dur_info, fmts, "성과분석(YTD)")
            except Exception:
                pass  # YTD 계산 실패 시 시트만 생략 (본 export 는 유지)

    # ── 4) 시계열(기준가) — 설정일~최신 전체기간. 레벨(기준가/지수) + 수익률(%) 컬럼 병기 ──
    ts = wb.add_worksheet(_TS_SHEET)
    ts.hide_gridlines(2)
    nb = len(bench_cols)
    rc0 = 3 + nb  # 수익률 블록 시작 컬럼 (레벨 블록 | 갭 1열 | 수익률 블록)
    ec0 = rc0 + nb + 1  # 초과수익률(%p) 블록 시작 컬럼 (차트 보조축 영역용)
    ts_headers = ["날짜", "AP 기준가"] + [f"{nm} 지수" for nm, _ in bench_cols]
    for c, h in enumerate(ts_headers):
        ts.write(0, c, h, fmts["head"])
    ts.write(0, rc0, "AP 수익률(%)", fmts["head"])
    for c, (nm, _) in enumerate(bench_cols):
        ts.write(0, rc0 + 1 + c, f"{nm} 수익률(%)", fmts["head"])
    for c, (nm, _) in enumerate(bench_cols):
        ts.write(0, ec0 + c, f"AP-{nm} 초과(%p)", fmts["head"])
    n = len(ov.nav_series)
    nav0 = float(ov.nav_series[0].nav) if n else 1.0
    # 벤치 수익률 기준값 = 각 시리즈 첫 유효값 (head 결측 시 합류 시점부터 0%)
    bench_base = []
    for _, ser in bench_cols:
        _v = ser.dropna()
        bench_base.append(float(_v.iloc[0]) if len(_v) and float(_v.iloc[0]) != 0 else None)
    for i, p in enumerate(ov.nav_series):
        rr = i + 1
        ts.write_datetime(rr, 0, datetime.combine(p.date_, datetime.min.time()), fmts["dt"])
        ts.write_number(rr, 1, float(p.nav), fmts["nav"])
        _ap_ret = (float(p.nav) / nav0 - 1.0) * 100
        ts.write_number(rr, rc0, _ap_ret, fmts["num_s"])
        for c, (_, ser) in enumerate(bench_cols):
            v = ser.iloc[i]
            if pd.isna(v):
                continue
            ts.write_number(rr, c + 2, float(v), fmts["nav"])
            if bench_base[c]:
                _b_ret = (float(v) / bench_base[c] - 1.0) * 100
                ts.write_number(rr, rc0 + 1 + c, _b_ret, fmts["num_s"])
                ts.write_number(rr, ec0 + c, _ap_ret - _b_ret, fmts["num_s"])
    ts.set_column(0, 0, 12)
    ts.set_column(1, 1 + nb, 13)
    ts.set_column(2 + nb, 2 + nb, 1.5)  # 갭: 레벨 | 수익률
    ts.set_column(rc0, rc0 + nb, 14)
    ts.set_column(ec0, ec0 + max(nb - 1, 0), 16)
    ts.freeze_panes(1, 0)

    # ── Overview 차트 (시계열 수익률 컬럼 참조, Y축=수익률%) — 기간별 수익률 표 하단, 가로 배치 ──
    # 초과수익률(AP−벤치) = 옅은 회색 영역, 보조축 (2026-07-03 사용자 지정).
    # xlsxwriter 는 보조축 시리즈가 combine 되는 쪽에 있어야 secondary axis 가 생성됨 —
    # 라인(기본) + 영역(combine, y2). 영역이 위에 그려지므로 투명도 50%로 라인 가시성 유지.
    ins_col = 0
    for c, (name, _) in enumerate(bench_cols):
        ch = wb.add_chart({"type": "line"})
        ch.add_series({
            "name": "펀드",
            "categories": [_TS_SHEET, 1, 0, n, 0],
            "values": [_TS_SHEET, 1, rc0, n, rc0],
            "line": {"color": _C_AP, "width": 1.5},
        })
        ch.add_series({
            "name": name,
            "categories": [_TS_SHEET, 1, 0, n, 0],
            "values": [_TS_SHEET, 1, rc0 + 1 + c, n, rc0 + 1 + c],
            "line": {"color": _C_BENCH if name != "proxy" else _C_PROXY, "width": 1.25},
        })
        ar = wb.add_chart({"type": "area"})
        ar.add_series({
            "name": "초과수익률",
            "categories": [_TS_SHEET, 1, 0, n, 0],
            "values": [_TS_SHEET, 1, ec0 + c, n, ec0 + c],
            "y2_axis": True,
            "fill": {"color": "#D9D9D9", "transparency": 50},
            "line": {"none": True},
        })
        # 결합 차트의 보조축 서식은 보조 차트 객체에 설정해야 반영됨.
        # 레이블 = 메인축과 동일 폰트/포맷(%) (2026-07-03 사용자 지정)
        ar.set_y2_axis({"num_font": {"size": 8, "name": _FN}, "num_format": '0"%"',
                        "major_gridlines": {"visible": False}})
        ch.combine(ar)
        ch.set_title({"name": f"펀드 vs {name} (수익률, 설정후)",
                      "name_font": {"size": 11, "name": _FN}})
        ch.set_legend({"position": "bottom", "font": {"size": 9, "name": _FN}})
        ch.set_x_axis({"num_font": {"size": 8, "name": _FN}, "num_format": "yy-mm",
                       "label_position": "low"})
        # 가로 눈금선 제거 + Y축 레이블 낮은쪽(2026-07-03 사용자 지정)
        ch.set_y_axis({"num_font": {"size": 8, "name": _FN}, "num_format": '0"%"',
                       "major_gridlines": {"visible": False}, "label_position": "low"})
        ch.set_size({"width": 560, "height": 300})
        ws.insert_chart(chart_row, ins_col, ch)
        ins_col += 8
    if not bench_cols:
        ch = wb.add_chart({"type": "line"})
        ch.add_series({
            "name": "펀드",
            "categories": [_TS_SHEET, 1, 0, n, 0],
            "values": [_TS_SHEET, 1, rc0, n, rc0],
            "line": {"color": _C_AP, "width": 1.5},
        })
        ch.set_title({"name": "펀드 수익률 (설정후)", "name_font": {"size": 11, "name": _FN}})
        ch.set_legend({"position": "bottom", "font": {"size": 9, "name": _FN}})
        ch.set_x_axis({"num_font": {"size": 8, "name": _FN}, "num_format": "yy-mm",
                       "label_position": "low"})
        ch.set_y_axis({"num_font": {"size": 8, "name": _FN}, "num_format": '0"%"',
                       "major_gridlines": {"visible": False}, "label_position": "low"})
        ch.set_size({"width": 560, "height": 300})
        ws.insert_chart(chart_row, 0, ch)

    wb.close()
    fname = f"brinson_{fund_code}_{br.start_date.strftime('%Y%m%d')}_{br.end_date.strftime('%Y%m%d')}.xlsx"
    return buf.getvalue(), fname
