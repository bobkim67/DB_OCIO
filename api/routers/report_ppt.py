"""Admin — 운용보고(비대면) PPT 빌드/다운로드 + s4·s6 코멘트 검수 (2026-07-14).

reporting.builder 래핑. 빌드는 프로세스 내 동시 1건만 허용
(matplotlib pyplot 스레드 안전 X + DB/LLM 부하). 코멘트 캐시(JSON)는
reporting/out/s4_manual_*.json / s6_manual_*.json — 빌더와 파일 규약 공유
(수정 저장 후 재빌드하면 LLM 재호출 없이 편집본이 PPT 에 반영).
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter()

_BUILD_LOCK = threading.Lock()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_S4_FILE_RE = re.compile(r"^s4_manual_\d{8}(_\d{8})?\.json$")
_S6_FILE_RE = re.compile(r"^s6_manual_[A-Za-z0-9]{5}_\d{8}\.json$")
_PPTX_FILE_RE = re.compile(r"^report_[A-Za-z0-9_]+\.pptx$")


class PptBuildBodyDTO(BaseModel):
    fund_code: str
    end_date: str                       # YYYY-MM-DD
    start_date: str | None = None       # None=전년말 YTD
    regen_comments: bool = False        # True=코멘트 캐시 삭제 후 빌드(LLM 재생성)


class S4BlockDTO(BaseModel):
    label: str
    lines: list[str]


class S4CommentDTO(BaseModel):
    headline: str
    comments: list[S4BlockDTO]


class S6CommentDTO(BaseModel):
    bullets: list[str]
    digest: str | None = None


class PptCommentsDTO(BaseModel):
    s4_file: str
    s4: S4CommentDTO | None = None
    s6_file: str
    s6: S6CommentDTO | None = None


class PptBuildResponseDTO(BaseModel):
    pptx_file: str
    elapsed_sec: float
    comments: PptCommentsDTO


class PptCommentsSaveBodyDTO(BaseModel):
    s4_file: str | None = None
    s4: S4CommentDTO | None = None
    s6_file: str | None = None
    s6: S6CommentDTO | None = None
    # 아카이브 메타 (저장 이력 파일명·내용에 기록)
    fund_code: str | None = None
    end_date: str | None = None
    start_date: str | None = None


class PptArchiveEntryDTO(BaseModel):
    file: str
    saved_at: str
    fund_code: str
    end_date: str
    start_date: str | None = None


class PptArchiveListDTO(BaseModel):
    entries: list[PptArchiveEntryDTO]


def _out_dir() -> Path:
    # reporting.builder.common.OUT 과 동일 경로 — 코멘트 조회/다운로드가
    # matplotlib 등 빌더 의존성 import 없이 동작하도록 직접 계산.
    return Path(__file__).resolve().parents[2] / "reporting" / "out"


def _check_date(v: str, name: str) -> None:
    if not _DATE_RE.match(v):
        raise HTTPException(422, f"{name}: YYYY-MM-DD 형식이어야 합니다 ({v!r})")


def _resolve_comment_files(fund: str, end: str, start: str | None) -> tuple[Path, Path]:
    """빌더의 캐시 파일 규약 재현 — s4=s4_manual_{end}[_{앵커시작}].json / s6=s6_manual_{fund}_{end}.json.

    커스텀 구간 s4 suffix 는 빌더가 앵커(영업일 스냅)된 period_start 를 쓰므로 전달값과
    다를 수 있음 → 정확 파일 없으면 같은 종료일의 suffix 파일 중 최신(mtime) 폴백.
    """
    out = _out_dir()
    end8 = end.replace("-", "")
    s6 = out / f"s6_manual_{fund}_{end8}.json"
    if start:
        exact = out / f"s4_manual_{end8}_{start.replace('-', '')}.json"
        if exact.exists():
            return exact, s6
        cands = sorted(out.glob(f"s4_manual_{end8}_*.json"), key=lambda p: p.stat().st_mtime)
        return (cands[-1] if cands else exact), s6
    return out / f"s4_manual_{end8}.json", s6


def _load_comments(fund: str, end: str, start: str | None) -> PptCommentsDTO:
    s4_p, s6_p = _resolve_comment_files(fund, end, start)
    s4 = s6 = None
    if s4_p.exists():
        s4 = S4CommentDTO(**json.loads(s4_p.read_text(encoding="utf-8")))
    if s6_p.exists():
        s6 = S6CommentDTO(**json.loads(s6_p.read_text(encoding="utf-8")))
    return PptCommentsDTO(s4_file=s4_p.name, s4=s4, s6_file=s6_p.name, s6=s6)


@router.post("/admin/report-ppt/build", response_model=PptBuildResponseDTO)
def build_ppt(body: PptBuildBodyDTO) -> PptBuildResponseDTO:
    _check_date(body.end_date, "end_date")
    if body.start_date:
        _check_date(body.start_date, "start_date")
    if not _BUILD_LOCK.acquire(blocking=False):
        raise HTTPException(409, "다른 PPT 빌드가 진행 중입니다 — 잠시 후 다시 시도하세요.")
    try:
        if body.regen_comments:
            s4_p, s6_p = _resolve_comment_files(body.fund_code, body.end_date, body.start_date)
            for p in (s4_p, s6_p):
                p.unlink(missing_ok=True)
        t0 = time.time()
        from reporting.builder.build import build_report
        try:
            out_path = build_report(body.fund_code, body.end_date, body.start_date)
        except Exception as e:            # noqa: BLE001 — DB/LLM/데이터 실패를 메시지로 전달
            raise HTTPException(500, f"PPT 빌드 실패: {e}") from e
        return PptBuildResponseDTO(
            pptx_file=Path(out_path).name,
            elapsed_sec=round(time.time() - t0, 1),
            comments=_load_comments(body.fund_code, body.end_date, body.start_date),
        )
    finally:
        _BUILD_LOCK.release()


@router.get("/admin/report-ppt/comments", response_model=PptCommentsDTO)
def get_ppt_comments(
    fund: str = Query(..., min_length=1, max_length=32),
    end: str = Query(...),
    start: str | None = Query(default=None),
) -> PptCommentsDTO:
    _check_date(end, "end")
    if start:
        _check_date(start, "start")
    return _load_comments(fund, end, start)


@router.put("/admin/report-ppt/comments", response_model=PptCommentsSaveBodyDTO)
def save_ppt_comments(body: PptCommentsSaveBodyDTO) -> PptCommentsSaveBodyDTO:
    if not (body.s4 and body.s4_file) and not (body.s6 and body.s6_file):
        raise HTTPException(422, "저장할 s4/s6 코멘트가 없습니다.")
    out = _out_dir()
    out.mkdir(parents=True, exist_ok=True)
    if body.s4 and body.s4_file:
        if not _S4_FILE_RE.match(body.s4_file):
            raise HTTPException(422, f"s4_file 형식 오류: {body.s4_file!r}")
        (out / body.s4_file).write_text(
            json.dumps(body.s4.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
    if body.s6 and body.s6_file:
        if not _S6_FILE_RE.match(body.s6_file):
            raise HTTPException(422, f"s6_file 형식 오류: {body.s6_file!r}")
        (out / body.s6_file).write_text(
            json.dumps(body.s6.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
    # 아카이브 — 날짜·시간·펀드코드 파일명으로 이력 보존 (추후 불러오기)
    if body.fund_code and body.end_date:
        import datetime
        arc = out / "archive"
        arc.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now()
        end8 = body.end_date.replace("-", "")
        s8 = f"_{body.start_date.replace('-', '')}" if body.start_date else ""
        fname = f"{now.strftime('%Y%m%d_%H%M%S')}_{body.fund_code}_{end8}{s8}.json"
        (arc / fname).write_text(json.dumps({
            "saved_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "fund_code": body.fund_code, "end_date": body.end_date,
            "start_date": body.start_date,
            "s4_file": body.s4_file, "s4": body.s4.model_dump() if body.s4 else None,
            "s6_file": body.s6_file, "s6": body.s6.model_dump() if body.s6 else None,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    return body


@router.post("/admin/report-ppt/comments/generate", response_model=PptCommentsDTO)
def generate_ppt_comments(body: PptBuildBodyDTO) -> PptCommentsDTO:
    """s4/s6 코멘트 LLM 생성 (기존 캐시 삭제 후 재생성) — 빌드와 분리된 전용 경로."""
    _check_date(body.end_date, "end_date")
    if body.start_date:
        _check_date(body.start_date, "start_date")
    if not _BUILD_LOCK.acquire(blocking=False):
        raise HTTPException(409, "다른 빌드/생성이 진행 중입니다 — 잠시 후 다시 시도하세요.")
    try:
        s4_p, s6_p = _resolve_comment_files(body.fund_code, body.end_date, body.start_date)
        for p in (s4_p, s6_p):
            p.unlink(missing_ok=True)
        try:
            # 빌더 s04.add/s06.add 와 동일한 앵커·태그 규약으로 생성
            from reporting.builder.data_fund import get_fund_data
            from reporting.builder.s04 import compute_rows
            from reporting.builder.s04_comment import build_manual
            from reporting.builder.s06_comment import build_s6_bullets
            ctx = get_fund_data(body.fund_code, body.end_date, body.start_date)
            is_ytd = ctx.get("is_ytd", True)
            data = compute_rows(body.end_date, None if is_ytd else ctx["period_start"])
            build_manual(data, body.end_date, use_llm=True,
                         tag="" if is_ytd else ctx["period_start"])
            build_s6_bullets(body.fund_code, ctx["period_start"], body.end_date)
        except Exception as e:            # noqa: BLE001 — DB/LLM 실패를 메시지로 전달
            raise HTTPException(500, f"코멘트 생성 실패: {e}") from e
        return _load_comments(body.fund_code, body.end_date, body.start_date)
    finally:
        _BUILD_LOCK.release()


_ARC_FILE_RE = re.compile(r"^\d{8}_\d{6}_[A-Za-z0-9]{5}_\d{8}(_\d{8})?\.json$")


@router.get("/admin/report-ppt/comments/archive", response_model=PptArchiveListDTO)
def list_comment_archive(
    fund: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
) -> PptArchiveListDTO:
    arc = _out_dir() / "archive"
    entries = []
    if arc.exists():
        for p in sorted(arc.glob("*.json"), reverse=True):
            if not _ARC_FILE_RE.match(p.name):
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:             # noqa: BLE001 — 파손 항목 건너뜀
                continue
            if fund and d.get("fund_code") != fund:
                continue
            entries.append(PptArchiveEntryDTO(
                file=p.name, saved_at=d.get("saved_at", ""),
                fund_code=d.get("fund_code", ""), end_date=d.get("end_date", ""),
                start_date=d.get("start_date")))
            if len(entries) >= limit:
                break
    return PptArchiveListDTO(entries=entries)


@router.get("/admin/report-ppt/comments/archive/{file}")
def get_comment_archive(file: str) -> dict:
    if not _ARC_FILE_RE.match(file):
        raise HTTPException(422, f"파일명 형식 오류: {file!r}")
    p = _out_dir() / "archive" / file
    if not p.exists():
        raise HTTPException(404, f"이력 없음: {file}")
    return json.loads(p.read_text(encoding="utf-8"))


class PptFileDTO(BaseModel):
    file: str
    size_kb: int
    mtime: str


class PptFileListDTO(BaseModel):
    files: list[PptFileDTO]


@router.get("/admin/report-ppt/files", response_model=PptFileListDTO)
def list_ppt_files() -> PptFileListDTO:
    """생성된 pptx 목록 (최신순) — 재빌드 없이 기존 산출물 다운로드용."""
    import datetime
    out = _out_dir()
    rows = []
    for p in out.glob("report_*.pptx"):
        if p.name.startswith("~$"):
            continue
        st = p.stat()
        rows.append(PptFileDTO(
            file=p.name, size_kb=round(st.st_size / 1024),
            mtime=datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        ))
    rows.sort(key=lambda r: r.mtime, reverse=True)
    return PptFileListDTO(files=rows)


@router.get("/admin/report-ppt/download")
def download_ppt(file: str = Query(..., max_length=128)) -> FileResponse:
    if not _PPTX_FILE_RE.match(file):
        raise HTTPException(422, f"파일명 형식 오류: {file!r}")
    p = _out_dir() / file
    if not p.exists():
        raise HTTPException(404, f"파일 없음: {file}")
    return FileResponse(
        str(p), filename=file,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
