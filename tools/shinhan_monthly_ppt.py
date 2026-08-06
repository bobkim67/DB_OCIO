# -*- coding: utf-8 -*-
"""신한라이프 글로벌자산배분B형(2JM23) 월간운용보고서 PPT — 데이터 수집기 (2026-08-06).

## 산출물

`한국투자신탁운용_신한라이프_운용보고서(글로벌자산배분B형)_{YYYYMM}_회신.pptx`
4슬라이드: 표지 / ①그래프+②수익률표+③요약코멘트 / ④자산배분표 / ⑤종목표+⑥전망코멘트

## 데이터 소스 (2026-06 발송본 대조로 전부 검증)

| 항목 | 소스 | 검증 |
|---|---|---|
| ② 기간수익률 | 기준가(MOD_STPR) + **보수 일할 환원** | 1M/3M/6M/YTD 발송본 정확 일치 |
| ② 연환산 변동성 | **템플릿 값 승계**(수기) | 발송본 산식 미상 — 아래 §미해결 |
| ② BM 2종 | **템플릿 값 승계**(수기) | 발송본 산식 미상 — 아래 §미해결 |
| ③⑥ 코멘트 | 코멘트 엔진 **포맷 D** 승인본 | 구조 일치 |
| ④ 당월말 비중 | 당월 PA `sec_summary.순자산비중_끝` → TAA 집계 | 전 행 일치 |
| ④ 전월말 비중 | **전월** PA `sec_summary.순자산비중_끝` → TAA 집계 | 전 행 일치 |
| ④ 성과기여도 | 당월 PA `sec_summary.기여수익률` → TAA 집계 | 전 행 일치 |
| ④ TAA | **템플릿(전월 발송본) 값 승계** — 산출물 어디에도 없는 수기 입력 | — |
| ⑤ 종목표 | 당월 PA `sec_summary` + YTD PA 기여수익률 | 일치 |

## ⚠ 미해결 — 표② 보수 환원 산식

발송본은 "펀드 수익률 (보수차감전)". 기준가는 보수 차감 후라 환원이 필요하다.
BOS3203 컴포넌트 합 **7.225** 를 **연 0.7225%** 로 보고 일할 복리 환원하면:

    1M 2.50 ✅ / 3M 33.16 ✅ / 6M 32.77 (발송본 32.76) ✅ / YTD 32.77 ✅
    1Y 60.41 (발송본 59.96) ❌ / 설정후 199.68 (발송본 184.80) ❌

즉 **단기 4개 열은 정확히 재현되고 장기 2개 열만 어긋난다.** 장기 구간의 보수율
변동(A50 0.185→0.160, 2024-12-16) 만으로는 설명되지 않는다.
→ `FEE_ANNUAL_PCT` 를 상수로 빼두고, 빌드 결과에 1Y·설정후 편차를 **경고로 표시**한다.
   운용역이 그 두 칸만 확인하면 된다. 산식 확정되면 여기만 고치면 된다.

## ⚠ 미해결 — 표② 변동성·벤치마크 (2026-08-06 사용자 확정: 수기 유지)

- **연환산 변동성**: 우리 결과5(주간 표준편차×√52)와 전 구간 불일치. 다만 발송본
  자체가 6M 16.02 vs YTD 11.60 으로 모순된다(6월은 두 기간이 동일) — 발송본 쪽
  정합성이 의심돼 산식을 특정할 수 없었다.
- **KOSPI 200 / MSCI AC World**: 발송본 1년 230%·설정후 459% 로 구간수익률 스케일이
  아니다. SCIP 253/15·35/15 로는 재현 불가.

→ 둘 다 **템플릿 값을 그대로 두고 운용역이 수정**한다 (TAA 열과 동일 취급).
  빌더는 이 3개 행을 **건드리지 않는다**.

⚠ 2026-05 발송본의 표②는 **2026-04 기준값**이었다(1M 13.28% = 202604 실측 13.23%).
  그 달 보고서가 한 달 밀린 값으로 나갔다 — 대조 기준으로 쓰지 말 것.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date

FUND = '2JM23'
FUND_NAME = '글로벌 자산배분 B형'

# BOS3203 컴포넌트 합(7.225) × 0.1%p. 단기 4개 열이 발송본과 정확히 일치하는 값.
# `load_fund_meta().fee_bp` 도 2026-08-06 수정 후 같은 값(72.25bp)을 돌려주지만,
# 발송본으로 검증된 산출물이라 DB 값 변동에 흔들리지 않게 상수를 유지한다.
FEE_ANNUAL_PCT = 0.7225

# 표② 기간 컬럼 (발송본 순서)
PERIOD_COLS = ('1개월', '3개월', '6개월', '1년', '연초이후', '설정이후')

# 표② 에서 **빌더가 쓰는 유일한 행**. 나머지 3행(연환산 변동성 / KOSPI 200 /
# MSCI AC World)은 산식 미상이라 템플릿 값을 그대로 둔다 (2026-08-06 사용자 확정).
PERF_ROW_FUND = '펀드 수익률 (보수차감전, %)'
PERF_ROWS_KEEP = ('연환산 변동성', 'KOSPI 200 Index', 'MSCI AC World Index')


@dataclass
class AllocRow:
    """표④ 한 행."""
    group: str            # 주식 / 채권 / 대체 / 현금
    label: str            # 미국 성장주 …
    cur_w: float = 0.0    # 당월말 비중 %
    prev_w: float = 0.0   # 전월말 비중 %
    contrib: float = 0.0  # 성과기여도 %p

    @property
    def delta(self) -> float:
        return self.cur_w - self.prev_w


@dataclass
class SecRow:
    """표⑤ 한 행."""
    name: str
    label: str            # 세부 자산군
    weight: float         # 비중 %
    ret: float            # 월 수익률 %
    ytd_contrib: float    # 연초후 수익률 기여도 %p


@dataclass
class PptData:
    period: str                       # 'YYYY-MM'
    start: date
    end: date
    prev_end: date
    perf: dict = field(default_factory=dict)     # 표② {행: {기간: 값}}
    alloc: list = field(default_factory=list)    # 표④ AllocRow
    secs: list = field(default_factory=list)     # 표⑤ SecRow
    comment_summary: str = ''                    # ③
    comment_outlook: str = ''                    # ⑥
    warnings: list = field(default_factory=list)


# ────────────────────────────── 기간 ──────────────────────────────

def _month_bounds(period: str) -> tuple[date, date, date]:
    """('YYYY-MM') → (당월 첫 영업일, 당월 마지막 영업일, 전월 마지막 영업일)."""
    from modules.data_loader import load_business_days_set
    y, m = int(period[:4]), int(period[5:7])
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    days = sorted(load_business_days_set(
        f'{py}{pm:02d}01', f'{y}{m:02d}{calendar.monthrange(y, m)[1]:02d}'))
    cur = [d for d in days if d[:7] == f'{y}-{m:02d}']
    prev = [d for d in days if d[:7] == f'{py}-{pm:02d}']
    if not cur or not prev:
        raise ValueError(f'{period} 영업일 캘린더 부족')
    return (date.fromisoformat(cur[0]), date.fromisoformat(cur[-1]),
            date.fromisoformat(prev[-1]))


def _ymd(d: date) -> str:
    return d.strftime('%Y%m%d')


# ────────────────────────── 표② 수익률·변동성 ──────────────────────────

def _gross_up(nav, a: str, b: str) -> float:
    """기준가 구간수익률에 보수를 **일할 복리**로 되돌린 값(%)."""
    seg = nav.loc[a:b]
    if len(seg) < 2:
        return float('nan')
    net = seg.pct_change().dropna()
    return float(((1 + net + FEE_ANNUAL_PCT / 100 / 365).prod() - 1) * 100)


def collect_perf(period: str, end: date, warnings: list) -> dict:
    """표② **펀드 수익률(보수차감전) 행만**.

    연환산 변동성·BM 2행은 산식 미상이라 빌더가 건드리지 않는다(템플릿 승계).
    1년·설정후는 보수 환원이 발송본과 어긋나 warnings 에 남긴다.
    """
    from dateutil.relativedelta import relativedelta
    from modules.data_loader import load_fund_nav_with_aum

    nav_df = load_fund_nav_with_aum(FUND, start_date='20150101')
    nav_df = nav_df[['기준일자', 'MOD_STPR']].dropna().sort_values('기준일자')
    nav = nav_df.set_index(nav_df['기준일자'].dt.strftime('%Y%m%d'))['MOD_STPR'].astype(float)
    end_s = _ymd(end)
    if end_s not in nav.index:
        raise ValueError(f'{end_s} 기준가 없음')

    def _anchor(target: date) -> str:
        """기준일 이하 최근 관측일. 월간 보고서라 앵커는 **월말**이어야 한다 —
        `relativedelta(months=3)` 로 6/30→3/30 을 쓰면 3/31 하루가 빠져
        3개월 수익률이 발송본과 0.77%p 어긋난다(2026-06 실측)."""
        t = _ymd(target)
        prior = [d for d in nav.index if d <= t]
        return prior[-1] if prior else nav.index[0]

    def _month_end_before(n: int) -> date:
        """n개월 전 **월말** 날짜(달력 기준)."""
        m = end.replace(day=1) - relativedelta(months=n - 1)
        return m - relativedelta(days=1)

    anchors = {
        '1개월': _anchor(_month_end_before(1)),
        '3개월': _anchor(_month_end_before(3)),
        '6개월': _anchor(_month_end_before(6)),
        '1년': _anchor(_month_end_before(12)),
        '연초이후': _anchor(date(end.year - 1, 12, 31)),
        '설정이후': nav.index[0],
    }
    ret = {k: _gross_up(nav, a, end_s) for k, a in anchors.items()}
    warnings.append(
        '표② 1년·설정이후는 보수 환원이 발송본과 어긋난다(단기 4개 열은 정확 일치) '
        '— 이 두 칸은 반드시 눈으로 확인할 것')
    return {PERF_ROW_FUND: ret}


# ────────────────────────── 표④ 자산배분 ──────────────────────────

def _taa_weights(start: date, end: date) -> tuple[dict, dict, list]:
    """구간 PA → PPT 행별 (기말비중%, 기여수익률%p) + 미매핑 경고."""
    from config.taa_classification import ppt_row_for
    from modules.data_loader import compute_single_port_pa

    pa = compute_single_port_pa(FUND, start_date=_ymd(start), end_date=_ymd(end),
                                fx_split=False)
    ss = pa.get('sec_summary')
    w: dict[str, float] = {}
    c: dict[str, float] = {}
    unmapped: list[str] = []
    if ss is None:
        return w, c, ['PA sec_summary 없음']
    for _, r in ss.iterrows():
        code = str(r.get('종목코드') or '')
        if code in ('', '유동성및기타'):
            continue          # 유동성은 잔여(100−Σ)로 계산 — 발송본 관행
        row = ppt_row_for(code)
        if row is None:
            unmapped.append(f"{code} {r.get('종목명')}")
            continue
        w[row] = w.get(row, 0.0) + float(r.get('순자산비중_끝') or 0) * 100
        c[row] = c.get(row, 0.0) + float(r.get('기여수익률') or 0) * 100
    return w, c, unmapped


def collect_alloc(start: date, end: date, prev_end: date,
                  warnings: list) -> list:
    """표④ — 당월말/전월말 비중 + 성과기여도. TAA 열은 빌더가 템플릿 값을 남긴다."""
    from config.taa_classification import SHINHAN_PPT_SKELETON
    from dateutil.relativedelta import relativedelta

    cur_w, cur_c, un1 = _taa_weights(start, end)
    # 전월말 비중 = **전월 구간 PA 의 기말 비중** (2026-06 발송본으로 검증:
    # 미국 성장주 41.21 · 한국 주식 32.61 · 한국 장기채권 21.56 · 금 2.50 전부 일치).
    p_start = (prev_end.replace(day=1))
    prev_w, _, un2 = _taa_weights(p_start, prev_end)
    for u in set(un1 + un2):
        warnings.append(f'TAA 미매핑 종목 — 자산배분표에서 누락됨: {u}')

    rows = []
    for group, label in SHINHAN_PPT_SKELETON:
        if label == '현금':
            continue
        rows.append(AllocRow(group, label,
                             round(cur_w.get(label, 0.0), 2),
                             round(prev_w.get(label, 0.0), 2),
                             round(cur_c.get(label, 0.0), 2)))
    # 현금 = 잔여. 보유 합이 100 을 넘으면 음수가 된다 — 결제 시차(미지급금 25x계정)
    # 로 실제로 발생하며 원장상 정상이지만([[reference_settlement_conventions]]),
    # 고객 발송 표에 음수 현금이 찍히므로 **반드시 눈으로 확인**하게 경고한다.
    cash_cur = round(100 - sum(r.cur_w for r in rows), 2)
    cash_prev = round(100 - sum(r.prev_w for r in rows), 2)
    if cash_cur < 0 or cash_prev < 0:
        warnings.append(
            f'현금(잔여) 비중이 음수 — 당월 {cash_cur:.2f}% / 전월 {cash_prev:.2f}%. '
            f'보유 합이 100%를 넘습니다(결제 시차 가능). 발송 전 확인 필요')
    rows.append(AllocRow(
        '현금', '현금', cash_cur, cash_prev,
        round(-sum(r.contrib for r in rows) + _port_return(start, end), 2)))
    return rows


def _port_return(start: date, end: date) -> float:
    """PA 포트폴리오 개별수익률(%) — 현금 기여도 역산용."""
    from modules.data_loader import compute_single_port_pa
    pa = compute_single_port_pa(FUND, start_date=_ymd(start), end_date=_ymd(end),
                                fx_split=False)
    a = pa.get('asset_summary')
    if a is None:
        return 0.0
    hit = a[a['자산군'] == '포트폴리오']
    return float(hit['개별수익률'].iloc[0]) * 100 if len(hit) else 0.0


# ────────────────────────── 표⑤ 주요 종목 ──────────────────────────

def collect_secs(start: date, end: date, warnings: list) -> list:
    """표⑤ — 비중 내림차순. 월수익률 = 당월 PA, YTD기여도 = 연초~기말 PA."""
    from config.taa_classification import classify_taa, ppt_row_for
    from modules.data_loader import compute_single_port_pa

    pa = compute_single_port_pa(FUND, start_date=_ymd(start), end_date=_ymd(end),
                                fx_split=False)
    ytd = compute_single_port_pa(FUND, start_date=f'{end.year}0101',
                                 end_date=_ymd(end), fx_split=False)
    ytd_c = {}
    yss = ytd.get('sec_summary')
    if yss is not None:
        for _, r in yss.iterrows():
            ytd_c[str(r.get('종목코드'))] = float(r.get('기여수익률') or 0) * 100

    ss = pa.get('sec_summary')
    out = []
    if ss is None:
        warnings.append('PA sec_summary 없음 — 종목표 비어 있음')
        return out
    for _, r in ss.iterrows():
        code = str(r.get('종목코드') or '')
        w = float(r.get('순자산비중_끝') or 0) * 100
        if code == '유동성및기타' or not code:
            out.append(SecRow('유동성및기타', '', round(w, 2), 0.0,
                              round(ytd_c.get('유동성및기타', 0.0), 2)))
            continue
        hit = classify_taa(code)
        out.append(SecRow(
            str(r.get('종목명') or code),
            ppt_row_for(code) or (hit[3] if hit else '(미분류)'),
            round(w, 2),
            round(float(r.get('개별수익률') or 0) * 100, 2),
            round(ytd_c.get(code, 0.0), 2)))
    out.sort(key=lambda x: -x.weight)
    # 유동성 비중은 PA 가 0 으로 주므로 잔여로 보정 (발송본 관행)
    named = [x for x in out if x.name != '유동성및기타']
    for x in out:
        if x.name == '유동성및기타':
            x.weight = round(100 - sum(n.weight for n in named), 2)
    return out


# ────────────────────────── ③⑥ 코멘트 ──────────────────────────

def collect_comments(period: str, warnings: list) -> tuple[str, str]:
    """포맷 D 승인 코멘트 → (③ 운용성과 요약, ⑥ 시장환경 분석 및 운용계획)."""
    from market_research.report.report_store import load_final
    d = load_final(period, FUND)
    if not (d and d.get('approved')):
        warnings.append(f'{period} {FUND} 코멘트 승인본 없음 — 코멘트 칸 비움')
        return '', ''
    text = str(d.get('final_comment') or '')
    # 포맷 D: "1. 운용성과 요약" / "2. 시장환경 분석 및 펀드운용계획"
    parts = text.split('2. 시장환경 분석 및 펀드운용계획')
    head = parts[0].replace('1. 운용성과 요약', '').strip()
    tail = parts[1].strip() if len(parts) > 1 else ''
    if not tail:
        warnings.append('코멘트에서 2번 섹션을 찾지 못함 — 포맷 D 확인 필요')
    return head, tail


# ────────────────────────── 오케스트레이터 ──────────────────────────

def collect(period: str) -> PptData:
    """PPT 치환에 필요한 값 일괄 수집."""
    start, end, prev_end = _month_bounds(period)
    w: list[str] = []
    data = PptData(period=period, start=start, end=end, prev_end=prev_end,
                   warnings=w)
    data.perf = collect_perf(period, end, w)
    data.alloc = collect_alloc(start, end, prev_end, w)
    data.secs = collect_secs(start, end, w)
    data.comment_summary, data.comment_outlook = collect_comments(period, w)
    return data


# ══════════════════════════════════════════════════════════════
# PowerPoint COM 치환기
# ══════════════════════════════════════════════════════════════
#
# python-pptx 는 못 쓴다 — 발송본이 DRM 래핑(`<DOCUMENT SAFER`)이고 COM
# `SaveCopyAs` 결과물도 래핑된다(실측). `tools/kb_monthly_report.py`(Word COM)
# 와 같은 경로로 간다.
#
# ★ 빌더가 **건드리지 않는 것** (2026-08-06 사용자 확정):
#     표② 연환산 변동성 / KOSPI 200 / MSCI AC World  — 산식 미상
#     표④ TAA 열                                     — 수기 입력
#     ① 1년 성과 그래프 + 헤더의 (YTD기준) 문구         — BM 재현 불가라 함께 보류
#   전부 템플릿(전월 발송본) 값이 남는다. 빌드 결과에 경고로 알린다.

TEMPLATE_ROOT = r'C:\Users\user\Downloads\OCIO_DB\운용보고서\월'
OUT_NAME = '한국투자신탁운용_신한라이프_운용보고서(글로벌자산배분B형)_{ym}_회신.pptx'


def _prev_ym(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    return f'{y - 1}12' if m == 1 else f'{y}{m - 1:02d}'


def find_template(period: str) -> str | None:
    """전월 발송본을 틀로 쓴다. 없으면 None."""
    from pathlib import Path
    d = Path(TEMPLATE_ROOT) / _prev_ym(period) / FUND
    if not d.exists():
        return None
    cands = sorted(d.glob('*.pptx'), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(cands[0]) if cands else None


def _set_cell(tbl, r: int, c: int, text: str) -> None:
    tbl.Cell(r, c).Shape.TextFrame.TextRange.Text = text


def _get_cell(tbl, r: int, c: int) -> str:
    return (tbl.Cell(r, c).Shape.TextFrame.TextRange.Text or '').strip()


def _only_table(slide):
    for sh in slide.Shapes:
        if sh.HasTable == -1:
            return sh.Table
    return None


def _fill_perf_table(tbl, perf: dict) -> None:
    """표② — `펀드 수익률` 행만. 나머지 3행은 템플릿 값 유지."""
    row = perf.get(PERF_ROW_FUND) or {}
    for r in range(2, tbl.Rows.Count + 1):
        if _get_cell(tbl, r, 1).startswith('펀드 수익률'):
            for i, col in enumerate(PERIOD_COLS, start=2):
                v = row.get(col)
                if v is not None and v == v:
                    _set_cell(tbl, r, i, f'{v:.2f} %')
            return


def _fill_alloc_table(tbl, rows: list, warnings: list) -> None:
    """표④ — **행 라벨로 매칭**한다.

    템플릿의 채권 행 순서(미국 하이일드 / 미국 장기채권 / 한국 중기채권 /
    한국 장기채권)가 `SHINHAN_PPT_SKELETON` 과 달라, 인덱스로 쓰면 값이 어긋난다.
    소계·총계는 앞 그룹 합으로 다시 계산한다. TAA(3열)·비고(8열)는 손대지 않는다.
    """
    by = {r.label: r for r in rows}
    used: set = set()
    acc = {'cur': 0.0, 'prev': 0.0, 'con': 0.0}
    tot = {'cur': 0.0, 'prev': 0.0, 'con': 0.0}

    def _w(r, cur, prev, con):
        _set_cell(tbl, r, 4, f'{cur:.2f}%')
        _set_cell(tbl, r, 5, f'{prev:.2f}%')
        _set_cell(tbl, r, 6, f'{cur - prev:.2f}%')
        _set_cell(tbl, r, 7, f'{con:.2f}%')

    for r in range(2, tbl.Rows.Count + 1):
        label = _get_cell(tbl, r, 2)
        grp = _get_cell(tbl, r, 1)
        if '소계' in (label, grp):
            _w(r, acc['cur'], acc['prev'], acc['con'])
            acc = {'cur': 0.0, 'prev': 0.0, 'con': 0.0}
            continue
        if '총계' in (label, grp):
            _w(r, tot['cur'], tot['prev'], tot['con'])
            continue
        hit = by.get(label)
        if hit is None:
            warnings.append(f'표④ 템플릿 행 "{label}" 에 대응하는 산출값 없음 — 0 으로 채움')
            hit = AllocRow(grp, label)
        used.add(label)
        _w(r, hit.cur_w, hit.prev_w, hit.contrib)
        for k, v in (('cur', hit.cur_w), ('prev', hit.prev_w), ('con', hit.contrib)):
            acc[k] += v
            tot[k] += v

    for lbl in set(by) - used:
        if abs(by[lbl].cur_w) > 0.005:
            warnings.append(
                f'표④ 산출값 "{lbl}" {by[lbl].cur_w:.2f}% 를 넣을 행이 템플릿에 없음 — 누락')


def _fill_sec_table(tbl, secs: list, warnings: list) -> None:
    """표⑤ — 비중 내림차순. 템플릿 행 수가 고정이라 모자라면 경고."""
    cap = tbl.Rows.Count - 1
    if len(secs) > cap:
        warnings.append(f'표⑤ 보유 {len(secs)}건 > 템플릿 행 {cap}개 — 하위 종목 누락')
    for i in range(cap):
        r = i + 2
        if i < len(secs):
            s = secs[i]
            for c, v in ((1, str(i + 1)), (2, s.name), (3, s.label),
                         (4, f'{s.weight:.2f}'), (5, f'{s.ret:.2f}'),
                         (6, f'{s.ytd_contrib:.2f}')):
                _set_cell(tbl, r, c, v)
        else:
            for c in range(1, 7):
                _set_cell(tbl, r, c, '')


def _replace_text_shape(slide, predicate, text: str) -> bool:
    for sh in slide.Shapes:
        try:
            cur = sh.TextFrame.TextRange.Text or ''
        except Exception:
            continue
        if predicate(sh, cur):
            sh.TextFrame.TextRange.Text = text
            return True
    return False


def build(period: str, out_path: str | None = None,
          template: str | None = None) -> dict:
    """전월 발송본을 틀로 열어 표·코멘트를 치환하고 저장."""
    import re
    from pathlib import Path

    data = collect(period)
    tpl = template or find_template(period)
    if not tpl:
        raise FileNotFoundError(
            f'{_prev_ym(period)} 발송본(틀)을 찾지 못했습니다: {TEMPLATE_ROOT}')
    ym = period.replace('-', '')
    out = out_path or str(Path(__file__).resolve().parent.parent / 'output'
                          / OUT_NAME.format(ym=ym))
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    import win32com.client as win32
    app = win32.DispatchEx('PowerPoint.Application')
    try:
        pres = app.Presentations.Open(tpl, True, False, False)   # ReadOnly, 창 없음
        try:
            y, m = int(period[:4]), int(period[5:7])
            # 슬라이드1 — 기준월
            _replace_text_shape(
                pres.Slides(1),
                lambda sh, t: '월간운용보고서' in t,
                re.sub(r'\d{4}년\s*\d{1,2}월말 기준', f'{y}년 {m}월말 기준',
                       next((sh.TextFrame.TextRange.Text
                             for sh in pres.Slides(1).Shapes
                             if _safe_text(sh).find('월간운용보고서') >= 0), '')))
            # 슬라이드2 — 표② + ③ 코멘트
            t2 = _only_table(pres.Slides(2))
            if t2 is None:
                data.warnings.append('슬라이드2 표를 찾지 못함')
            else:
                _fill_perf_table(t2, data.perf)
            if data.comment_summary and not _replace_text_shape(
                    pres.Slides(2),
                    lambda sh, t: sh.Top > 400 and len(t) > 80,
                    data.comment_summary):
                data.warnings.append('③ 운용성과 요약 텍스트 상자를 찾지 못함')
            # 슬라이드3 — 표④
            t3 = _only_table(pres.Slides(3))
            if t3 is None:
                data.warnings.append('슬라이드3 표를 찾지 못함')
            else:
                _fill_alloc_table(t3, data.alloc, data.warnings)
            # 슬라이드4 — 표⑤ + ⑥ 코멘트
            t4 = _only_table(pres.Slides(4))
            if t4 is None:
                data.warnings.append('슬라이드4 표를 찾지 못함')
            else:
                _fill_sec_table(t4, data.secs, data.warnings)
            if data.comment_outlook and not _replace_text_shape(
                    pres.Slides(4),
                    lambda sh, t: t.strip().startswith('시장환경 분석'),
                    data.comment_outlook):
                data.warnings.append('⑥ 시장환경 분석 텍스트 상자를 찾지 못함')

            data.warnings.append(
                '수기 확인 필요 — 표② 연환산 변동성·KOSPI200·MSCI ACWI, 표④ TAA 열, '
                '① 1년 성과 그래프와 헤더는 템플릿(전월) 값 그대로입니다')
            pres.SaveAs(out, 24)          # ppSaveAsOpenXMLPresentation
        finally:
            pres.Close()
    finally:
        app.Quit()
    return {'path': out, 'template': tpl, 'warnings': data.warnings}


def _safe_text(sh) -> str:
    try:
        return sh.TextFrame.TextRange.Text or ''
    except Exception:
        return ''


if __name__ == '__main__':
    import sys
    r = build(sys.argv[1] if len(sys.argv) > 1 else '2026-07')
    print('저장:', r['path'])
    print('틀  :', r['template'])
    for _w in r['warnings']:
        print('  ⚠', _w)
