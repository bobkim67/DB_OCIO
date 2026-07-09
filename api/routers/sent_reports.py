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
):
    """발송 원본 파일 (DRM 래핑 그대로 — 사내 PC 에서만 열림, 사용자 확정)."""
    p = _safe_resolve(fund, rel_path)
    return FileResponse(str(p), filename=p.name)
