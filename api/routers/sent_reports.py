# -*- coding: utf-8 -*-
"""발송 운용보고 아카이브 API — data/sent_reports 조회/다운로드 (2026-07-09).

수집·텍스트추출은 PC 배치(collect.sent_report_collector / sent_report_text)가 수행,
서버는 파일·index 읽기 전용. 갱신 = sent_reports 폴더 동기화 (재시작 불필요).
"""
from __future__ import annotations

from pathlib import Path as _P

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from market_research.collect.sent_report_collector import SENT_DIR, load_index

router = APIRouter()


class SentReportFileDTO(BaseModel):
    filename: str
    rel_path: str
    kind: str
    mail_date: str
    mail_subject: str
    has_text: bool
    text_chars: int = 0
    preview_pages: int = 0  # 원본 레이아웃 PNG 캡쳐 수 (sent_report_preview 산출)


class SentReportPeriodDTO(BaseModel):
    period: str
    files: list[SentReportFileDTO]


class SentReportListDTO(BaseModel):
    fund_code: str
    periods: list[SentReportPeriodDTO]


def _safe_resolve(fund: str, rel_path: str) -> _P:
    """경로 traversal 방지 — fund 하위 + SENT_DIR 내부만 허용."""
    p = (SENT_DIR / rel_path).resolve()
    base = SENT_DIR.resolve()
    if not str(p).startswith(str(base)) or not rel_path.replace('\\', '/').startswith(f'{fund}/'):
        raise HTTPException(status_code=400, detail='invalid path')
    if not p.exists():
        raise HTTPException(status_code=404, detail='file not found')
    return p


@router.get('/funds/{fund}/sent-reports', response_model=SentReportListDTO)
def list_sent_reports(fund: str = Path(..., min_length=1, max_length=32)) -> SentReportListDTO:
    rows = [e for e in load_index() if e.get('fund') == fund]
    by_period: dict[str, list[SentReportFileDTO]] = {}
    for e in rows:
        txt = SENT_DIR / (e['rel_path'] + '.txt')
        by_period.setdefault(e['period'], []).append(SentReportFileDTO(
            filename=e['filename'], rel_path=e['rel_path'], kind=e.get('kind', ''),
            mail_date=e.get('mail_date', ''), mail_subject=e.get('mail_subject', ''),
            has_text=txt.exists(), text_chars=int(e.get('text_chars') or 0),
            preview_pages=int(e.get('preview_pages') or 0),
        ))
    periods = [SentReportPeriodDTO(period=p, files=sorted(fs, key=lambda f: f.filename))
               for p, fs in by_period.items()]
    periods.sort(key=lambda x: x.period, reverse=True)
    return SentReportListDTO(fund_code=fund, periods=periods)


class SentReportTextDTO(BaseModel):
    rel_path: str
    text: str


@router.get('/funds/{fund}/sent-reports/text', response_model=SentReportTextDTO)
def get_sent_report_text(
    fund: str = Path(..., min_length=1, max_length=32),
    rel_path: str = Query(..., max_length=300),
) -> SentReportTextDTO:
    p = _safe_resolve(fund, rel_path + '.txt')
    return SentReportTextDTO(rel_path=rel_path, text=p.read_text(encoding='utf-8'))


@router.get('/funds/{fund}/sent-reports/file')
def download_sent_report(
    fund: str = Path(..., min_length=1, max_length=32),
    rel_path: str = Query(..., max_length=300),
    inline: bool = Query(False),
):
    """발송 원본 파일 (DRM 래핑 그대로 — 사내 PC 에서만 열림, 사용자 확정).

    inline=true 는 클린 PDF(비정기 대면보고) 브라우저 내장 뷰어 표시용.
    """
    p = _safe_resolve(fund, rel_path)
    return FileResponse(str(p), filename=p.name,
                        content_disposition_type='inline' if inline else 'attachment')


class SentGenRequestDTO(BaseModel):
    kind: str    # '월간' | '분기'
    period: str  # '2026-06' | '2026-Q2'


class SentGenResponseDTO(BaseModel):
    fund_code: str
    period: str
    comment: str
    reference: str = ''      # 참조한 직전 발송본
    warnings: list[str] = []


@router.post('/funds/{fund}/sent-reports/generate', response_model=SentGenResponseDTO)
def generate_sent_report_comment(
    body: SentGenRequestDTO,
    fund: str = Path(..., min_length=1, max_length=32),
) -> SentGenResponseDTO:
    """발송 보고서용 펀드 코멘트 생성 (LLM, 1~2분).

    직전 발송본 서술을 기준 원고로 잇는 프롬프트(fund_comment_service 주입) 사용.
    target_suffix='sentgen' 격리 저장 — 운영 draft/final 워크플로우 불변.
    시장 debate 승인본(_market.final)이 해당 기간에 있어야 한다.
    """
    import re as _re
    m = _re.fullmatch(r'(\d{4})-(0[1-9]|1[0-2])', body.period)
    q = _re.fullmatch(r'(\d{4})-Q([1-4])', body.period)
    if body.kind == '월간' and m:
        mode, year, num = '월별', int(m.group(1)), int(m.group(2))
    elif body.kind == '분기' and q:
        mode, year, num = '분기', int(q.group(1)), int(q.group(2))
    else:
        raise HTTPException(status_code=400, detail='kind/period 조합이 잘못됨 '
                            '(월간=YYYY-MM, 분기=YYYY-QN)')

    from market_research.report.report_store import load_final
    market = load_final(body.period, '_market')
    if not market:
        raise HTTPException(status_code=409, detail=f'{body.period} 시장 코멘트 승인본 없음 '
                            '— Admin 에서 시장 debate 승인 후 생성 가능')

    from market_research.report.fund_comment_service import (
        _load_sent_report_reference, generate_fund_comment_and_save)
    try:
        draft = generate_fund_comment_and_save(
            mode, year, num, fund, body.period, market, target_suffix='sentgen')
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'생성 실패: {exc}')
    ref = None
    try:
        ref = _load_sent_report_reference(fund, body.period)
    except Exception:
        pass
    comment = str(draft.get('draft_comment') or draft.get('comment') or '')
    return SentGenResponseDTO(
        fund_code=fund, period=body.period, comment=comment,
        reference=f"{ref['period']} {ref['filename']}" if ref else '',
        warnings=[str(w) for w in (draft.get('data_warnings') or [])][:8],
    )


@router.get('/funds/{fund}/sent-reports/preview')
def get_sent_report_preview(
    fund: str = Path(..., min_length=1, max_length=32),
    rel_path: str = Query(..., max_length=300),
    page: int = Query(1, ge=1, le=99),
):
    """원본 레이아웃 PNG 캡쳐 페이지 (Office COM 렌더 — DRM 미래핑 경로)."""
    p = _safe_resolve(fund, f'{rel_path}.preview/p{page:02d}.png')
    return FileResponse(str(p), media_type='image/png',
                        content_disposition_type='inline')
