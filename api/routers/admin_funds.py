# -*- coding: utf-8 -*-
"""Admin 펀드 운용 콘솔 API (2026-07-09 사용자 지시).

전 펀드(상단 선택 무관) 요약 + 2단계 승인 워크플로우:
  펀드코멘트(운영 경로, {fund}.draft/final) 생성→편집→승인
    → 승인돼야 보고서(suffix 'sentrep') 생성 가능 → 편집→승인 → client 노출.
client 노출 = 운용보고 탭(코멘트 final) / 발송 보고서 뷰(sentrep final).
⚠️ admin 계열은 인증 없는 환경에서 보안 경계 아님 (기존 admin 엔드포인트와 동일 주의).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from api.schemas.holdings import ComplianceItemDTO

REPORT_SUFFIX = 'sentrep'  # 발송 보고서 아티팩트 suffix

router = APIRouter()


# ── DTO ──

class AdminFundRowDTO(BaseModel):
    fund_code: str
    fund_name: str
    beneficiary: str | None = None    # 수익자 (FUND_BENEFICIARY)
    compliance_status: str            # breach | warn | ok | none | error
    compliance_breaches: list[str] = []   # 위반/주의 항목 라벨
    compliance: list[ComplianceItemDTO] = []  # 항목별 가이드 게이지 데이터(전 펀드 노출용)
    returns: dict[str, float] = {}    # MTD/1M/3M/6M/YTD/1Y/SI (raw ratio)
    bm_returns: dict[str, float] = {}    # 동일 기간 BM 수익률 (BM 펀드만)
    benchmark_kind: str = "none"      # BM | SAA | none
    duration_bond: float | None = None     # 채권성 가중평균 듀레이션 (년)
    ytm_bond: float | None = None          # 채권성 가중평균 YTM (%)
    duration_overall: float | None = None  # 펀드 전체 가중평균 듀레이션 (년)
    ytm_overall: float | None = None       # 펀드 전체 가중평균 YTM (%)


class AdminFundsOverviewDTO(BaseModel):
    as_of_date: str | None = None     # 스냅샷 기준일 (실제 데이터 기준일)
    rows: list[AdminFundRowDTO]


class WorkflowStageDTO(BaseModel):
    status: str
    text: str = ''
    approved_at: str = ''
    generated_at: str = ''
    excel_ready: bool = False   # 4JM12 월간: DB생명 월간보고 엑셀 생성 여부


class AdminFundWorkflowDTO(BaseModel):
    fund_code: str
    period: str
    comment: WorkflowStageDTO
    report: WorkflowStageDTO


class GenBodyDTO(BaseModel):
    kind: str    # '월간' | '분기'
    period: str


class EditBodyDTO(BaseModel):
    period: str
    text: str


class PeriodBodyDTO(BaseModel):
    period: str


# ── 내부 헬퍼 ──

def _parse_period(kind: str, period: str) -> tuple[str, int, int]:
    m = re.fullmatch(r'(\d{4})-(0[1-9]|1[0-2])', period)
    q = re.fullmatch(r'(\d{4})-Q([1-4])', period)
    if kind == '월간' and m:
        return '월별', int(m.group(1)), int(m.group(2))
    if kind == '분기' and q:
        return '분기', int(q.group(1)), int(q.group(2))
    raise HTTPException(status_code=400, detail='kind/period 조합 오류 (월간=YYYY-MM, 분기=YYYY-QN)')


# ── 4JM12 DB생명 월간보고 엑셀 (2026-07-31 사용자 지시) ──
# 보고서 생성(2단계, 코멘트 승인 게이트 뒤)이 실행되면 tools.dblife_monthly_excel 로
# 데이터 엑셀을 함께 생성한다. s6 코멘트 = 1단계 승인 코멘트(final.json)가 자동 인용됨.
_EXCEL_FUND, _EXCEL_KIND = '4JM12', '월간'


def _excel_path(fund: str, period: str):
    from pathlib import Path as _P
    if fund != _EXCEL_FUND or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', period or ''):
        return None
    base = _P(__file__).resolve().parent.parent.parent
    return base / 'output' / f'DB생명_월간보고_데이터_{period.replace("-", "")}.xlsx'


def _stage(period: str, fund: str, suffix: str | None) -> WorkflowStageDTO:
    from market_research.report.report_store import get_status, load_draft, load_final
    status = get_status(period, fund, target_suffix=suffix)
    final = load_final(period, fund, target_suffix=suffix)
    draft = load_draft(period, fund, target_suffix=suffix)
    text = ''
    if final and final.get('approved'):
        text = str(final.get('final_comment') or '')
    elif draft:
        text = str(draft.get('draft_comment') or '')
    xp = _excel_path(fund, period) if suffix == REPORT_SUFFIX else None
    return WorkflowStageDTO(
        status=status, text=text,
        approved_at=str((final or {}).get('approved_at') or ''),
        generated_at=str((draft or {}).get('generated_at') or ''),
        excel_ready=bool(xp and xp.exists()),
    )


def _generate(fund: str, body: GenBodyDTO, suffix: str | None) -> WorkflowStageDTO:
    mode, year, num = _parse_period(body.kind, body.period)
    from market_research.report.report_store import load_final
    market = load_final(body.period, '_market')
    if not market:
        raise HTTPException(status_code=409,
                            detail=f'{body.period} 시장 코멘트 승인본 없음 — 시장 debate 승인 먼저')
    from market_research.report.fund_comment_service import generate_fund_comment_and_save
    try:
        generate_fund_comment_and_save(mode, year, num, fund, body.period, market,
                                       target_suffix=suffix)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'생성 실패: {exc}')
    return _stage(body.period, fund, suffix)


# ── 전 펀드 요약 ──

# 이 스냅샷의 소스(기준가 DWPM10510 · 보유 DWPM10530)는 **익일 새벽 3시 적재** 라
# 장중에 값이 바뀌지 않는다. 600s TTL 은 10분마다 20초 재계산(펀드당 ~2s x 11)을
# 유발해 워밍업 선채움이 무의미했다 → **적재 시각 기준 '데이터 세대'** 로 무효화한다.
# (고정 20h TTL 은 갱신 시점이 매일 4시간씩 당겨져 언젠가 03시 적재 **이전**에 캐시가
#  채워지고, 그날 하루 종일 전일 데이터를 서빙하게 되므로 채택하지 않음.)
_OVERVIEW_LOAD_HOUR = 3                   # DB 적재 시각(새벽 3시) = 세대 경계
_OVERVIEW_TTL = 20 * 3600.0               # 상한 백스톱(세대가 안 바뀌는 이상상황 방어)
_overview_cache: dict = {}                # {as_of|None: (monotonic_ts, generation, DTO)}
_overview_lock = __import__('threading').Lock()


def _overview_generation() -> str:
    """현재 데이터 세대 키 — 03시 이전이면 전일 세대."""
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(hours=_OVERVIEW_LOAD_HOUR)).strftime('%Y-%m-%d')


@router.get('/admin/funds-overview', response_model=AdminFundsOverviewDTO)
def get_admin_funds_overview(
    as_of: str | None = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'),
) -> AdminFundsOverviewDTO:
    """전 펀드 스냅샷: 컴플라이언스 가이드(항목별) + 기간수익률 + 채권/펀드 듀레이션·YTM.
    as_of(YYYY-MM-DD) 미지정 시 최신 영업일 기준.

    응답 캐시 — 펀드당 ~2s x 11 재계산 방지. 서버 웜업이 선채움
    (api/warmup._warm_admin_overview, 2026-07-14). 소스가 새벽 3시 적재라
    **데이터 세대(03시 경계 일단위)** 가 바뀔 때만 무효화 → 하루 1회 재계산.
    """
    import time as _time
    gen = _overview_generation()
    with _overview_lock:
        hit = _overview_cache.get(as_of)
        if (hit and hit[1] == gen
                and _time.monotonic() - hit[0] < _OVERVIEW_TTL):
            return hit[2]
    dto = _build_funds_overview(as_of)
    with _overview_lock:
        _overview_cache[as_of] = (_time.monotonic(), gen, dto)
    return dto


def _build_funds_overview(as_of: str | None) -> AdminFundsOverviewDTO:
    from config.funds import FUND_LIST, FUND_META, FUND_BENEFICIARY

    _SEV = {'breach': 3, 'warn': 2, 'ok': 1, 'none': 0}
    _RET_KEYS = ('MTD', '1M', '3M', '6M', 'YTD', '1Y', 'SI')
    rows: list[AdminFundRowDTO] = []
    snapshot: str | None = None
    for fund in FUND_LIST:
        # 컴플라이언스 가이드 + 듀레이션/YTM — holdings 재사용 (인메모리 캐시)
        comp_status, breaches = 'error', []
        comp_items: list[ComplianceItemDTO] = []
        d_bond = y_bond = d_all = y_all = None
        try:
            from api.services.holdings_service import build_holdings
            h = build_holdings(fund, lookthrough=True, as_of_date=as_of)
            comp_items = list(getattr(h, 'compliance', None) or [])
            worst = 0
            for c in comp_items:
                s = getattr(c, 'status', 'none')
                worst = max(worst, _SEV.get(s, 0))
                if s in ('breach', 'warn'):
                    breaches.append(f'{getattr(c, "label", "?")}({s})')
            comp_status = {3: 'breach', 2: 'warn', 1: 'ok', 0: 'none'}[worst]
            ds = getattr(h, 'duration_summary', None)
            if ds is not None:
                d_bond, y_bond = ds.duration_bond, ds.ytm_bond
                d_all, y_all = ds.duration_overall, ds.ytm_overall
            if snapshot is None and getattr(h, 'as_of_date', None):
                snapshot = str(h.as_of_date)
        except Exception:
            pass
        # 기간수익률 + 동일기간 BM 수익률 (as_of 앵커)
        rets: dict[str, float] = {}
        bm_rets: dict[str, float] = {}
        bm_kind = 'none'
        try:
            from api.services.overview_service import build_period_returns
            pr = build_period_returns(fund, end_date=as_of)
            rets = {k: v for k, v in (pr.period_returns or {}).items() if k in _RET_KEYS}
            bm_rets = {k: v for k, v in (pr.bm_period_returns or {}).items() if k in _RET_KEYS}
            bm_kind = pr.benchmark_kind
        except Exception:
            pass
        rows.append(AdminFundRowDTO(
            fund_code=fund,
            fund_name=str(FUND_META.get(fund, {}).get('name', '')),
            beneficiary=FUND_BENEFICIARY.get(fund),
            compliance_status=comp_status,
            compliance_breaches=breaches,
            compliance=comp_items,
            returns=rets,
            bm_returns=bm_rets,
            benchmark_kind=bm_kind,
            duration_bond=d_bond, ytm_bond=y_bond,
            duration_overall=d_all, ytm_overall=y_all,
        ))
    return AdminFundsOverviewDTO(as_of_date=snapshot or as_of, rows=rows)


# ── 워크플로우 조회 ──

@router.get('/admin/funds/{fund}/workflow', response_model=AdminFundWorkflowDTO)
def get_fund_workflow(
    fund: str = Path(..., min_length=1, max_length=32),
    period: str = Query(..., pattern=r'^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$'),
) -> AdminFundWorkflowDTO:
    return AdminFundWorkflowDTO(
        fund_code=fund, period=period,
        comment=_stage(period, fund, None),
        report=_stage(period, fund, REPORT_SUFFIX),
    )


# ── 펀드코멘트 (1단계) ──

@router.post('/admin/funds/{fund}/comment/generate', response_model=WorkflowStageDTO)
def generate_comment(body: GenBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    return _generate(fund, body, None)


@router.put('/admin/funds/{fund}/comment/draft', response_model=WorkflowStageDTO)
def edit_comment(body: EditBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    from market_research.report.report_store import update_draft_comment
    if update_draft_comment(body.period, fund, body.text) is None:
        raise HTTPException(status_code=404, detail='draft 없음 — 먼저 생성')
    return _stage(body.period, fund, None)


@router.post('/admin/funds/{fund}/comment/approve', response_model=WorkflowStageDTO)
def approve_comment(body: PeriodBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    from market_research.report.report_store import approve_and_save_final
    if approve_and_save_final(body.period, fund) is None:
        raise HTTPException(status_code=404, detail='draft 없음 — 먼저 생성')
    return _stage(body.period, fund, None)


# ── 보고서 (2단계 — 코멘트 승인 게이트) ──

@router.post('/admin/funds/{fund}/report/generate', response_model=WorkflowStageDTO)
def generate_report(body: GenBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    from market_research.report.report_store import load_final
    cf = load_final(body.period, fund)
    if not (cf and cf.get('approved')):
        raise HTTPException(status_code=409,
                            detail='펀드코멘트가 먼저 승인돼야 보고서 생성 가능')
    stage = _generate(fund, body, REPORT_SUFFIX)
    # 4JM12 월간: DB생명 월간보고 데이터 엑셀 동시 생성 (s6 = 승인 코멘트 자동 인용)
    xp = _excel_path(fund, body.period) if body.kind == _EXCEL_KIND else None
    if xp is not None:
        try:
            from tools.dblife_monthly_excel import build as build_dblife_excel
            build_dblife_excel(body.period, xp)
            stage.excel_ready = True
        except Exception as exc:
            # 텍스트 보고서 draft 는 이미 저장됨 — 엑셀 실패만 명확히 알린다
            raise HTTPException(status_code=500,
                                detail=f'보고서 텍스트는 생성됨. DB생명 엑셀 생성 실패: {exc}')
    return stage


@router.get('/admin/funds/{fund}/report/excel')
def download_report_excel(fund: str = Path(..., max_length=32),
                          period: str = Query(..., max_length=10)):
    """4JM12 월간 DB생명 데이터 엑셀 다운로드 (보고서 생성 시 산출)."""
    from fastapi.responses import FileResponse
    xp = _excel_path(fund, period)
    if xp is None or not xp.exists():
        raise HTTPException(status_code=404, detail='엑셀 없음 — 보고서 생성 먼저')
    return FileResponse(str(xp), filename=xp.name)


@router.put('/admin/funds/{fund}/report/draft', response_model=WorkflowStageDTO)
def edit_report(body: EditBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    from market_research.report.report_store import update_draft_comment
    if update_draft_comment(body.period, fund, body.text,
                            target_suffix=REPORT_SUFFIX) is None:
        raise HTTPException(status_code=404, detail='보고서 draft 없음 — 먼저 생성')
    return _stage(body.period, fund, REPORT_SUFFIX)


@router.post('/admin/funds/{fund}/report/approve', response_model=WorkflowStageDTO)
def approve_report(body: PeriodBodyDTO, fund: str = Path(..., max_length=32)) -> WorkflowStageDTO:
    from market_research.report.report_store import approve_and_save_final
    if approve_and_save_final(body.period, fund, target_suffix=REPORT_SUFFIX) is None:
        raise HTTPException(status_code=404, detail='보고서 draft 없음 — 먼저 생성')
    return _stage(body.period, fund, REPORT_SUFFIX)
