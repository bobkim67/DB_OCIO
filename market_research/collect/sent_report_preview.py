# -*- coding: utf-8 -*-
"""발송 운용보고 프리뷰(PNG 캡쳐) 생성 — 원본 레이아웃 그대로 탭에서 보기 (2026-07-09).

DRM 제약 실측:
- PowerPoint Slide.Export(PNG) = 클린 PNG (PPT 앱 파일출력은 DRM 미후킹)
- Excel ExportAsFixedFormat/Chart.Export = **DRM 재래핑** (사용 불가)
→ 우회: Excel Range.CopyPicture(클립보드) → PowerPoint 슬라이드 Paste → Slide.Export.
  Word 도 Range.Copy → PPT PasteSpecial(EnhancedMetafile) 동일 경로. PDF 원본은 클린이라
  변환 불필요(브라우저 inline).

출력: {rel_path}.preview/p01.png … + index preview_pages 갱신.
"""
from __future__ import annotations

import json
from pathlib import Path

from market_research.collect.sent_report_collector import INDEX_PATH, SENT_DIR

MAX_SLIDES = 30
MAX_SHEETS = 8
EXPORT_WIDTH = 1600


def _export_ppt(papp, path: Path, out_dir: Path) -> int:
    pres = papp.Presentations.Open(str(path.resolve()), ReadOnly=True, WithWindow=False)
    try:
        n = min(pres.Slides.Count, MAX_SLIDES)
        ratio = pres.PageSetup.SlideHeight / pres.PageSetup.SlideWidth
        for i in range(1, n + 1):
            pres.Slides(i).Export(str(out_dir / f'p{i:02d}.png'), 'PNG',
                                  EXPORT_WIDTH, int(EXPORT_WIDTH * ratio))
        return n
    finally:
        pres.Close()


def _paste_to_png(papp, out_path: Path, w: float, h: float, paste_fn) -> bool:
    """클립보드 그림 → 새 PPT 슬라이드 → PNG export. paste_fn(slide) 가 붙여넣기 수행."""
    pres = papp.Presentations.Add(WithWindow=False)
    try:
        w = max(64.0, min(w, 4000.0))
        h = max(64.0, min(h, 4000.0))
        pres.PageSetup.SlideWidth = w
        pres.PageSetup.SlideHeight = h
        slide = pres.Slides.Add(1, 12)  # ppLayoutBlank
        shp = paste_fn(slide)
        try:
            shp.Left = 0
            shp.Top = 0
        except Exception:
            pass
        scale = min(2.0, 4000.0 / w)
        slide.Export(str(out_path), 'PNG', int(w * scale), int(h * scale))
        return out_path.exists()
    finally:
        pres.Close()


def _export_excel(xapp, papp, path: Path, out_dir: Path) -> int:
    wb = xapp.Workbooks.Open(str(path.resolve()), ReadOnly=True)
    try:
        n = 0
        for ws in wb.Worksheets:
            if n >= MAX_SHEETS:
                break
            try:
                if ws.Visible != -1:  # xlSheetVisible
                    continue
                rng = ws.UsedRange
                if rng is None or (rng.Rows.Count <= 1 and rng.Columns.Count <= 1):
                    continue
                rng.CopyPicture(Appearance=1, Format=-4147)  # xlScreen, xlPicture
                ok = _paste_to_png(papp, out_dir / f'p{n + 1:02d}.png',
                                   float(rng.Width), float(rng.Height),
                                   lambda s: s.Shapes.Paste())
                if ok:
                    n += 1
            except Exception:
                continue
        return n
    finally:
        wb.Close(False)


def _export_word(wapp, papp, path: Path, out_dir: Path) -> int:
    doc = wapp.Documents.Open(str(path.resolve()), ReadOnly=True)
    try:
        doc.Range().Copy()
        # A4 세로 비율 근사 (여러 페이지면 세로로 길어져 잘릴 수 있음 — 코멘트 문서 1~2p 용)
        ok = _paste_to_png(papp, out_dir / 'p01.png', 595.0, 842.0,
                           lambda s: s.Shapes.PasteSpecial(DataType=2))  # EnhancedMetafile
        return 1 if ok else 0
    finally:
        doc.Close(False)


def build_previews(force: bool = False) -> dict:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()

    if not INDEX_PATH.exists():
        return {'error': 'index 없음'}
    index = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
    entries = index.get('entries', [])

    papp = win32com.client.DispatchEx('PowerPoint.Application')
    xapp = wapp = None
    ok = fail = skip = 0
    try:
        for e in entries:
            src = SENT_DIR / e['rel_path']
            ext = src.suffix.lower()
            out_dir = Path(str(src) + '.preview')
            if ext == '.pdf' or not src.exists():
                skip += 1
                continue
            if e.get('preview_pages') and out_dir.exists() and not force:
                skip += 1
                continue
            out_dir.mkdir(exist_ok=True)
            try:
                if ext in ('.ppt', '.pptx'):
                    n = _export_ppt(papp, src, out_dir)
                elif ext in ('.xls', '.xlsx'):
                    if xapp is None:
                        xapp = win32com.client.DispatchEx('Excel.Application')
                        xapp.Visible = False
                        xapp.DisplayAlerts = False
                    n = _export_excel(xapp, papp, src, out_dir)
                else:
                    if wapp is None:
                        wapp = win32com.client.DispatchEx('Word.Application')
                        wapp.Visible = False
                        wapp.DisplayAlerts = False
                    n = _export_word(wapp, papp, src, out_dir)
                e['preview_pages'] = n
                ok += 1
                print(f"  ok {e['rel_path']} ({n}p)")
            except Exception as exc:
                fail += 1
                print(f"  FAIL {e['rel_path']}: {exc}")
    finally:
        for app in (papp, xapp, wapp):
            try:
                if app is not None:
                    app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    return {'ok': ok, 'fail': fail, 'skip': skip}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description='발송 운용보고 프리뷰 PNG 생성 (Office COM)')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()
    print(f'[sent_report_preview] {build_previews(force=args.force)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
