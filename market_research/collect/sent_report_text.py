# -*- coding: utf-8 -*-
"""발송 운용보고 텍스트 추출 — DRM Office 파일을 COM 으로 열어 사이드카 .txt 생성.

사내 발신 Office 파일은 DRM 래핑이라 python 라이브러리로 직접 못 연다 (BadZipFile).
Office COM 은 문서보안 에이전트가 투명 복호화해 주므로 앱별 COM 으로 텍스트만 덤프.
- ppt/pptx: 슬라이드별 도형 텍스트 + 표
- doc/docx: 본문 전체
- xls/xlsx: 시트별 UsedRange (탭 구분)
- pdf: 추출 생략 (원본 다운로드만 제공)

출력: data/sent_reports/{fund}/{period}/{filename}.txt + index text_extracted 갱신.
"""
from __future__ import annotations

import json
from pathlib import Path

from market_research.collect.sent_report_collector import INDEX_PATH, SENT_DIR

MAX_CHARS = 30000  # 사이드카 상한 (프롬프트/뷰어 용도)


def _extract_ppt(app, path: Path) -> str:
    pres = app.Presentations.Open(str(path), ReadOnly=True, WithWindow=False)
    try:
        parts = []
        for i, slide in enumerate(pres.Slides, 1):
            lines = [f'--- 슬라이드 {i} ---']
            for shape in slide.Shapes:
                try:
                    if shape.HasTable:
                        tbl = shape.Table
                        for r in range(1, tbl.Rows.Count + 1):
                            cells = []
                            for c in range(1, tbl.Columns.Count + 1):
                                cells.append(str(tbl.Cell(r, c).Shape.TextFrame.TextRange.Text or '').strip())
                            lines.append('\t'.join(cells))
                    elif shape.HasTextFrame and shape.TextFrame.HasText:
                        t = str(shape.TextFrame.TextRange.Text or '').strip()
                        if t:
                            lines.append(t)
                except Exception:
                    continue
            parts.append('\n'.join(lines))
        return '\n\n'.join(parts)
    finally:
        pres.Close()


def _extract_word(app, path: Path) -> str:
    doc = app.Documents.Open(str(path), ReadOnly=True)
    try:
        return str(doc.Content.Text or '')
    finally:
        doc.Close(False)


def _extract_excel(app, path: Path) -> str:
    wb = app.Workbooks.Open(str(path), ReadOnly=True)
    try:
        parts = []
        for ws in wb.Worksheets:
            try:
                vals = ws.UsedRange.Value2
            except Exception:
                continue
            if vals is None:
                continue
            if not isinstance(vals, tuple):
                vals = ((vals,),)
            lines = [f'=== 시트: {ws.Name} ===']
            for row in vals[:300]:
                if not isinstance(row, tuple):
                    row = (row,)
                cells = ['' if v is None else str(v).strip() for v in row]
                if any(cells):
                    lines.append('\t'.join(cells).rstrip('\t'))
            parts.append('\n'.join(lines))
        return '\n\n'.join(parts)
    finally:
        wb.Close(False)


def extract_all(force: bool = False) -> dict:
    """index 순회 — 미추출 파일 텍스트 덤프. Office 앱은 종류별 1회만 기동."""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()

    if not INDEX_PATH.exists():
        return {'error': 'index 없음 — collector 먼저 실행'}
    index = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
    entries = index.get('entries', [])

    apps: dict[str, object] = {}

    def _get_app(kind: str):
        if kind in apps:
            return apps[kind]
        prog = {'ppt': 'PowerPoint.Application', 'word': 'Word.Application',
                'excel': 'Excel.Application'}[kind]
        app = win32com.client.DispatchEx(prog)
        if kind != 'ppt':  # PowerPoint 는 Visible=False 설정 불가
            app.Visible = False
            app.DisplayAlerts = False
        apps[kind] = app
        return app

    ok = fail = skip = 0
    try:
        for e in entries:
            path = SENT_DIR / e['rel_path']
            txt_path = Path(str(path) + '.txt')
            if e.get('text_extracted') and txt_path.exists() and not force:
                skip += 1
                continue
            ext = path.suffix.lower()
            if ext == '.pdf' or not path.exists():
                skip += 1
                continue
            try:
                if ext in ('.ppt', '.pptx'):
                    text = _extract_ppt(_get_app('ppt'), path)
                elif ext in ('.doc', '.docx'):
                    text = _extract_word(_get_app('word'), path)
                else:
                    text = _extract_excel(_get_app('excel'), path)
                txt_path.write_text(text[:MAX_CHARS], encoding='utf-8')
                e['text_extracted'] = True
                e['text_chars'] = min(len(text), MAX_CHARS)
                ok += 1
                print(f"  ok {e['rel_path']} ({e['text_chars']}자)")
            except Exception as exc:
                fail += 1
                print(f"  FAIL {e['rel_path']}: {exc}")
    finally:
        for kind, app in apps.items():
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    return {'ok': ok, 'fail': fail, 'skip': skip}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description='발송 운용보고 텍스트 추출 (Office COM)')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()
    st = extract_all(force=args.force)
    print(f'[sent_report_text] {st}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
