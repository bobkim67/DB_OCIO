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

REPORT_SUFFIX = 'sentrep'  # 발송 보고서 아티팩트 suffix

router = APIRouter()


# ── DTO ──

class AdminFundRowDTO(BaseModel):
    fund_code: str
    fund_name: str
    compliance_status: str            # breach | warn | ok | none | error
    compliance_breaches: list[str] = []   # 위반/주의 항목 라벨
    returns: dict[str, float] = {}    # 1M/3M/6M/YTD/1Y/SI (raw ratio)
    comment_status: str               # not_generated | draft_generated | edited | approved
    report_status: str


class AdminFundsOverviewDTO(BaseModel):
    period: str
    rows: list[AdminFundRowDTO]


class WorkflowStageDTO(BaseModel):
    status: str
    text: str = ''
    approved_at: str = ''
    generated_at: str = ''


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
    return WorkflowStageDTO(
        status=status, text=text,
        approved_at=str((final or {}).get('approved_at') or ''),
        generated_at=str((draft or {}).get('generated_at') or ''),
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

@router.get('/admin/funds-overview', response_model=AdminFundsOverviewDTO)
def get_admin_funds_overview(
    period: str = Query(..., pattern=r'^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$'),
) -> AdminFundsOverviewDTO:
    """전 펀드: 컴플라이언스 상태 + 기간수익률 + 코멘트/보고서 워크플로우 상태."""
    from config.funds import FUND_LIST, FUND_META
    from market_research.report.report_store import get_status

    _SEV = {'breach': 3, 'warn': 2, 'ok': 1, 'none': 0}
    rows: list[AdminFundRowDTO] = []
    for fund in FUND_LIST:
        # 컴플라이언스 — holdings compliance 재사용 (인메모리 캐시, 콜드 시 수 초/펀드)
        comp_status, breaches = 'error', []
        try:
            from api.services.holdings_service import build_holdings
            h = build_holdings(fund, lookthrough=True)
            comp = getattr(h, 'compliance', None) or []
            worst = 0
            for c in comp:
                s = getattr(c, 'status', 'none')
                worst = max(worst, _SEV.get(s, 0))
                if s in ('breach', 'warn'):
                    breaches.append(f'{getattr(c, "label", "?")}({s})')
            comp_status = {3: 'breach', 2: 'warn', 1: 'ok', 0: 'none'}[worst]
        except Exception:
            pass
        # 기간수익률
        rets: dict[str, float] = {}
        try:
            from api.services.overview_service import build_period_returns
            pr = build_period_returns(fund)
            rets = {k: v for k, v in (pr.period_returns or {}).items()
                    if k in ('1M', '3M', '6M', 'YTD', '1Y', 'SI')}
        except Exception:
            pass
        rows.append(AdminFundRowDTO(
            fund_code=fund,
            fund_name=str(FUND_META.get(fund, {}).get('name', '')),
            compliance_status=comp_status,
            compliance_breaches=breaches,
            returns=rets,
            comment_status=get_status(period, fund),
            report_status=get_status(period, fund, target_suffix=REPORT_SUFFIX),
        ))
    return AdminFundsOverviewDTO(period=period, rows=rows)


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
    return _generate(fund, body, REPORT_SUFFIX)


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
