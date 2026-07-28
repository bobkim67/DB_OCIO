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
    preview_rev: int = 0    # p01.png mtime — 캡쳐 재생성 시 URL 이 바뀌어 캐시를 우회


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
        # 캡쳐 세대 — 재생성하면 mtime 이 바뀌고 프론트 img URL 도 바뀐다.
        # (사내 프록시가 옛 PNG 를 계속 주던 사고 2026-07-28)
        p01 = SENT_DIR / (e['rel_path'] + '.preview/p01.png')
        try:
            rev = int(p01.stat().st_mtime)
        except OSError:
            rev = 0
        by_period.setdefault(e['period'], []).append(SentReportFileDTO(
            filename=e['filename'], rel_path=e['rel_path'], kind=e.get('kind', ''),
            mail_date=e.get('mail_date', ''), mail_subject=e.get('mail_subject', ''),
            has_text=txt.exists(), text_chars=int(e.get('text_chars') or 0),
            preview_pages=int(e.get('preview_pages') or 0), preview_rev=rev,
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


class GeneratedReportDTO(BaseModel):
    period: str
    comment: str
    approved_at: str = ''


class GeneratedReportsDTO(BaseModel):
    fund_code: str
    reports: list[GeneratedReportDTO]


@router.get('/funds/{fund}/sent-reports/generated', response_model=GeneratedReportsDTO)
def list_generated_reports(
    fund: str = Path(..., min_length=1, max_length=32),
) -> GeneratedReportsDTO:
    """승인된 생성 보고서(client 노출) — Admin 워크플로우(sentrep) 승인본만.

    생성/편집/승인은 Admin 탭 (2026-07-09 사용자 프로세스: 코멘트 승인 → 보고서
    생성 → 보고서 승인 → client 노출).
    """
    from market_research.report.report_store import list_periods, load_final
    out: list[GeneratedReportDTO] = []
    for period in list_periods():
        f = load_final(period, fund, target_suffix='sentrep')
        if f and f.get('approved'):
            out.append(GeneratedReportDTO(
                period=period, comment=str(f.get('final_comment') or ''),
                approved_at=str(f.get('approved_at') or '')))
    out.sort(key=lambda x: x.period, reverse=True)
    return GeneratedReportsDTO(fund_code=fund, reports=out)


@router.get('/funds/{fund}/sent-reports/preview')
def get_sent_report_preview(
    fund: str = Path(..., min_length=1, max_length=32),
    rel_path: str = Query(..., max_length=300),
    page: int = Query(1, ge=1, le=99),
):
    """원본 레이아웃 PNG 캡쳐 페이지 (Office COM 렌더 — DRM 미래핑 경로).

    no-cache: 캡쳐를 재생성해도 프록시/브라우저가 옛 바이트를 계속 주는 사고가 있었다
    (2026-07-28 DRM 래핑본 → 클린 교체 시). 파일은 그대로면 304 로 끝나니 비용은 없다.
    """
    p = _safe_resolve(fund, f'{rel_path}.preview/p{page:02d}.png')
    return FileResponse(str(p), media_type='image/png',
                        content_disposition_type='inline',
                        headers={'Cache-Control': 'no-cache'})
