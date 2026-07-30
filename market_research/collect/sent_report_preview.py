# -*- coding: utf-8 -*-
"""발송 운용보고 프리뷰(PNG 캡쳐) 생성 — 원본 레이아웃 그대로 탭에서 보기 (2026-07-09).

DRM 제약 실측:
- PowerPoint Slide.Export(PNG) = 클린 PNG (PPT 앱 파일출력은 DRM 미후킹)
  ※ 2026-07-28 재실측에서도 보호(pptx) 원본 → 클린 PNG 확인. 다만 **저장분 174장이
    전부 래핑돼 있던 사고**가 있었다(생성 시점 정책/상태 차이 추정) → 생성 즉시
    시그니처 검증(_clean_png_count). 래핑되면 preview_pages=0 으로 두고 탭은
    확장자 플레이스홀더로 폴백한다.
- Excel ExportAsFixedFormat/Chart.Export = **DRM 재래핑** (사용 불가)
→ 우회: Excel Range.CopyPicture(클립보드) → PowerPoint 슬라이드 Paste → Slide.Export.
  Word 도 Range.Copy → PPT PasteSpecial(EnhancedMetafile) 동일 경로. PDF 원본은 클린이라
  변환 불필요(브라우저 inline).

출력: {rel_path}.preview/p01.webp … + index preview_pages 갱신.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from market_research.collect.sent_report_collector import INDEX_PATH, SENT_DIR

MAX_SLIDES = 30
MAX_SHEETS = 8
# ★ 엑셀 시트 필터 (2026-07-28) — 보고서 뒤에 붙는 raw data 시트를 캡쳐에서 뺀다.
# 실측: 07G07 FactSheet 0.43 / 4JM12 분기 0.74~0.89 (본문) vs 수정기준가 data 13.0 ·
# BM data 8.0 · 2JM23 U보유내역Top10 18,671(UsedRange 가 1,048,545행으로 오염).
# 초장문 시트는 _paste_to_png 의 4000pt 클램프에 걸려 빈 영역만 찍히기도 했다
# (Appendix 썸네일이 하얗게 보이던 원인).
MAX_SHEET_RATIO = 3.0     # 세로/가로 — 초과 시 데이터 시트로 보고 스킵
MIN_SHEET_AREA = 20000    # pt² — 사실상 빈 시트(08N33 'Comment' 54x16) 스킵
# 캡쳐가 client 가 보는 **유일한 경로**다(원본은 DRM 이라 사외에서 못 연다) → 해상도 우선.
# 1600 → 3000px (2026-07-28). 저장은 WebP q90 — 같은 화질에서 PNG 대비 ~43% 용량이라
# 해상도를 올리고도 총량이 준다(PNG 2400px 185MB → WebP 3000px 약 120MB).
EXPORT_WIDTH = 3000
WEBP_QUALITY = 90

PNG_SIG = b'\x89PNG\r\n\x1a\n'
PAGE_EXT = '.webp'

# ★ 엑셀 요약 카드 (2026-07-30 사용자 지시) — 통합/양식 엑셀은 시트 캡쳐 대신
# **핵심 내용만 추출해 깔끔한 카드 이미지로 재구성**.
# (행 숨김 캡쳐는 병합셀 때문에 타 펀드(구조화혼합형 등)가 새어 나와 폐기.)
# kind='shinhan' (신한라이프 변액 — 전 라인업이 한 표, 해당 펀드 행만 추출):
#   - 월간(월별요약보고서): 'U코멘트관리' 시트 → 기준일자·펀드코드·운용사·펀드명·코멘트
#   - 분기(코멘트_통합): '작성요청' 시트 → 펀드코드·운용사·펀드명·지난분기·다음분기 코멘트
# kind='dblife' (DB생명 변액 분기 — 단일 펀드 파일, 2026-07-31 추가):
#   - '운용경과 및 수익률 현황' 시트 → ▶ 운용경과 / ▶ 향후 운용방침 두 섹션
# 추출 실패 시 기존 시트 캡쳐로 폴백. 엑셀은 ReadOnly — 원본 불변.
EXCEL_SUMMARY = {
    '2JM23': {'kind': 'shinhan', 'fund_name_kw': '자산배분B형'},     # 신한라이프 U80002
    '4JM12': {'kind': 'dblife', 'name': '글로벌Active자산배분혼합형',
              'mgr': '한국투자신탁운용'},
}


def _page_path(out_dir: Path, i: int) -> Path:
    return out_dir / f'p{i:02d}{PAGE_EXT}'


def _is_clean_image(p: Path) -> bool:
    """DRM 래핑(`<DOCUMENT SAFER ...`)이 아닌 진짜 이미지인가 — WebP/PNG 매직 검사."""
    try:
        with open(p, 'rb') as f:
            head = f.read(16)
    except OSError:
        return False
    if head[:8] == PNG_SIG:
        return True
    return head[:4] == b'RIFF' and head[8:12] == b'WEBP'


def _clean_png_count(out_dir: Path, n: int) -> int:
    """생성된 p01..pNN 중 **진짜 이미지** 인 것의 수.

    DRM 에이전트가 산출물을 재래핑하면(`<DOCUMENT SAFER ...`) 크기·개수는 정상인데
    브라우저가 렌더하지 못한다. 2026-07-28 저장분 174장이 전부 이 상태였고 서버는
    200 을 주고 있어 화면을 보기 전까지 아무도 몰랐다. → 생성 즉시 검증한다.
    """
    return sum(1 for i in range(1, n + 1) if _is_clean_image(_page_path(out_dir, i)))


def _export_slide(slide, out_path: Path, w: int, h: int) -> None:
    """슬라이드 → PNG. **temp 로 export 후 파이썬이 복사**한다.

    ★ 2026-07-28 실측: DRM 후킹은 '쓰는 프로세스' 기준이라 PowerPoint 가
    data/sent_reports 아래에 직접 쓰면 신규 파일도 `<DOCUMENT SAFER ...` 로 래핑된다
    (덮어쓰기 여부 무관). 같은 슬라이드를 %TEMP% 로 내보내면 클린이고, 그 파일을
    파이썬이 sent_reports 로 복사하면 클린이 유지된다. → 이 우회가 필수.
    """
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / 'slide.png'
        slide.Export(str(tmp), 'PNG', w, h)
        # 최종 write 는 파이썬(비-Office) — DRM 미후킹. 겸사겸사 WebP 로 줄인다.
        with Image.open(tmp) as im:
            im.convert('RGB').save(out_path, 'WEBP', quality=WEBP_QUALITY, method=4)


def _export_ppt(papp, path: Path, out_dir: Path) -> int:
    pres = papp.Presentations.Open(str(path.resolve()), ReadOnly=True, WithWindow=False)
    try:
        n = min(pres.Slides.Count, MAX_SLIDES)
        ratio = pres.PageSetup.SlideHeight / pres.PageSetup.SlideWidth
        for i in range(1, n + 1):
            _export_slide(pres.Slides(i), _page_path(out_dir, i),
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
        # Excel/Word 는 슬라이드 크기가 원본 range 크기(pt)라 배율로 해상도를 올린다.
        # 2026-07-28: 2.0 → 3.0 (상한 6000px) — PPT EXPORT_WIDTH 2400 과 눈높이 맞춤.
        scale = min(3.0, 6000.0 / w)
        _export_slide(slide, out_path, int(w * scale), int(h * scale))
        return out_path.exists()
    finally:
        pres.Close()


# ── 요약 카드: 추출 ─────────────────────────────────────────────

def _cells(row) -> list[str]:
    t = row if isinstance(row, tuple) else (row,)
    return ['' if c is None else str(c) for c in t]


def _fmt_ymd(v: str) -> str:
    """'20260531.0' / '20260531' → '2026-05-31'. 못 읽으면 원문."""
    s = v.split('.')[0].strip()
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    return v


def _extract_summary_monthly(vals, kw: str) -> dict | None:
    """'U코멘트관리' 시트 → {기준일자, 펀드코드, 운용사, 펀드명, 코멘트}."""
    hdr_i, hdr = None, None
    for i, row in enumerate(vals[:8]):
        cs = _cells(row)
        if any('펀드코드' in c for c in cs) and any('코멘트' in c for c in cs):
            hdr_i, hdr = i, cs
            break
    if hdr is None:
        return None
    col = lambda sub: next((j for j, c in enumerate(hdr) if sub in c), None)
    c_date = col('적용일자')
    if c_date is None:      # ⚠ '적용일자' 는 0번 컬럼 — `or` 쓰면 falsy 0 이 폴백에 먹힌다
        c_date = col('기준일자')
    c_code = col('펀드코드')
    c_mgr, c_name, c_cmt = col('운용사'), col('펀드명'), col('코멘트')
    if None in (c_code, c_name, c_cmt):
        return None
    for row in vals[hdr_i + 1:]:
        cs = _cells(row)
        if c_name < len(cs) and kw in cs[c_name]:
            g = lambda j: cs[j].strip() if j is not None and j < len(cs) else ''
            return {'type': 'monthly', 'date': _fmt_ymd(g(c_date)), 'code': g(c_code),
                    'mgr': g(c_mgr), 'name': g(c_name), 'comment': g(c_cmt)}
    return None


def _extract_summary_dblife(vals) -> dict | None:
    """DB생명 분기 '운용경과 및 수익률 현황' 시트 → ▶ 운용경과 / ▶ 향후 운용방침 본문.

    행 단위로 비어있지 않은 셀을 이어붙여 텍스트 라인으로 만들고, ▶ 마커 사이를 본문으로.
    '[글로벌Active자산배분혼합형]' 식 대괄호 헤더 행은 제목 후보로만 쓰고 본문에선 제외.
    """
    lines = []
    for row in vals:
        cs = [c.strip() for c in _cells(row) if c and c.strip()]
        # 셀 안 개행([펀드명]\n본문이 한 셀) → 논리 라인으로 분리 (대괄호 헤더 skip 이 먹히도록)
        lines.extend(' '.join(cs).replace('\r', '').split('\n'))
    i_p = next((i for i, l in enumerate(lines) if '▶' in l and '운용경과' in l), None)
    i_n = next((i for i, l in enumerate(lines) if '▶' in l and '운용방침' in l), None)
    if i_p is None or i_n is None or i_n <= i_p:
        return None
    bracket_name = ''

    def body(a: int, b: int) -> str:
        nonlocal bracket_name
        out = []
        for l in lines[a:b]:
            s = l.strip()
            if not s:
                continue
            if s.startswith('[') and s.endswith(']'):
                bracket_name = bracket_name or s.strip('[]').strip()
                continue
            out.append(s)
        return '\n'.join(out)

    prev, nxt = body(i_p + 1, i_n), body(i_n + 1, len(lines))
    if not (prev or nxt):
        return None
    return {'type': 'dblife_q', 'name': bracket_name, 'prev': prev, 'next': nxt}


def _extract_summary_quarterly(vals, kw: str) -> dict | None:
    """'작성요청' 시트 → {펀드코드, 운용사, 펀드명, 지난분기, 다음분기}. 헤더가 2행에 걸쳐 있어
    상위 8행 전체에서 컬럼별 첫 매칭을 취한다."""
    cols: dict[str, int] = {}
    for row in vals[:8]:
        cs = _cells(row)
        for key, sub in (('code', '펀드코드'), ('mgr', '운용사'), ('name', '펀드명'),
                         ('prev', '지난 분기'), ('next', '다음 분기')):
            if key not in cols:
                j = next((j for j, c in enumerate(cs) if sub in c), None)
                if j is not None:
                    cols[key] = j
    if not all(k in cols for k in ('code', 'name', 'prev', 'next')):
        return None
    for row in vals:
        cs = _cells(row)
        if cols['name'] < len(cs) and kw in cs[cols['name']]:
            g = lambda k: cs[cols[k]].strip() if k in cols and cols[k] < len(cs) else ''
            return {'type': 'quarterly', 'code': g('code'), 'mgr': g('mgr'),
                    'name': g('name'), 'prev': g('prev'), 'next': g('next')}
    return None


# ── 요약 카드: 렌더 (PIL — Office 미경유라 DRM 재래핑 없음) ─────────

_CARD_W = 2200
_CARD_M = 120
_INK, _MUTED, _ACCENT, _RULE = '#1f2430', '#69707d', '#E8473B', '#e5e8ee'


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    name = 'malgunbd.ttf' if bold else 'malgun.ttf'
    return ImageFont.truetype(rf'C:\Windows\Fonts\{name}', size)


def _wrap(draw, text: str, font, width: float) -> list[str]:
    """단어 단위 + 초장단어 문자 단위 폴백 줄바꿈. 원문 개행 유지."""
    out: list[str] = []
    for para in text.replace('\r', '').split('\n'):
        if not para.strip():
            out.append('')
            continue
        line = ''
        for word in para.split(' '):
            cand = f'{line} {word}'.strip()
            if draw.textlength(cand, font=font) <= width:
                line = cand
                continue
            if line:
                out.append(line)
            # 단어 자체가 폭 초과 → 문자 단위 분할
            while draw.textlength(word, font=font) > width:
                k = len(word)
                while k > 1 and draw.textlength(word[:k], font=font) > width:
                    k -= 1
                out.append(word[:k])
                word = word[k:]
            line = word
        out.append(line)
    while out and not out[-1]:
        out.pop()
    return out


def _render_summary_card(out_path: Path, head_meta: list[str], title: str,
                         sections: list[tuple[str, str]]) -> bool:
    """깔끔한 보고 카드 — 제목(펀드명) + 메타 한 줄 + 섹션(소제목/본문)들."""
    from PIL import Image, ImageDraw
    f_title, f_meta = _font(72, True), _font(40)
    f_h, f_b = _font(46, True), _font(42)
    lh_b = 66
    body_w = _CARD_W - _CARD_M * 2

    probe = ImageDraw.Draw(Image.new('RGB', (8, 8)))
    wrapped = [(h, _wrap(probe, body, f_b, body_w)) for h, body in sections if body.strip()]
    if not wrapped:
        return False
    H = _CARD_M + 96 + 64 + 40   # 제목 + 메타 + 구분선 여백
    for _h, lines in wrapped:
        H += 60 + 46 + 28 + len(lines) * lh_b + 40
    H += _CARD_M - 40

    im = Image.new('RGB', (_CARD_W, H), 'white')
    d = ImageDraw.Draw(im)
    y = _CARD_M
    d.text((_CARD_M, y), title, font=f_title, fill=_INK)
    y += 96
    d.text((_CARD_M, y), '  ·  '.join(m for m in head_meta if m), font=f_meta, fill=_MUTED)
    y += 64
    d.rectangle([_CARD_M, y, _CARD_W - _CARD_M, y + 3], fill=_RULE)
    y += 40
    for h, lines in wrapped:
        y += 60
        d.rectangle([_CARD_M, y + 6, _CARD_M + 10, y + 44], fill=_ACCENT)
        d.text((_CARD_M + 34, y), h, font=f_h, fill=_INK)
        y += 46 + 28
        for ln in lines:
            d.text((_CARD_M, y), ln, font=f_b, fill=_INK)
            y += lh_b
        y += 40
    im.save(out_path, 'WEBP', quality=WEBP_QUALITY, method=4)
    return True


def _export_excel_summary(xapp, path: Path, out_dir: Path, cfg: dict, fund: str) -> int:
    """EXCEL_SUMMARY 펀드 — 핵심 내용 추출 → 카드 이미지 1장. 실패 시 0 (폴백은 호출부)."""
    kind = cfg.get('kind', 'shinhan')
    wb = xapp.Workbooks.Open(str(path.resolve()), ReadOnly=True)
    try:
        info = None
        for ws in wb.Worksheets:
            try:
                if ws.Visible != -1:
                    continue
                nm = str(ws.Name)
                if kind == 'shinhan':
                    if nm not in ('U코멘트관리', '작성요청'):
                        continue
                    vals = ws.UsedRange.Value
                    if not isinstance(vals, tuple):
                        continue
                    kw = cfg['fund_name_kw']
                    info = (_extract_summary_monthly(vals, kw) if nm == 'U코멘트관리'
                            else _extract_summary_quarterly(vals, kw))
                else:  # dblife
                    if '운용경과' not in nm:
                        continue
                    vals = ws.UsedRange.Value
                    if not isinstance(vals, tuple):
                        continue
                    info = _extract_summary_dblife(vals)
                if info:
                    break
            except Exception:
                continue
    finally:
        wb.Close(False)
    if not info:
        return 0
    if info['type'] == 'dblife_q':
        title = info.get('name') or cfg.get('name', '')
        meta = [cfg.get('mgr', ''), fund]
        sections = [('운용경과', info.get('prev', '')),
                    ('향후 운용방침', info.get('next', ''))]
    elif info['type'] == 'monthly':
        title = info.get('name', '')
        meta = [info.get('mgr', ''), info.get('code', ''),
                f"기준일 {info['date']}" if info.get('date') else '']
        sections = [('운용 코멘트', info.get('comment', ''))]
    else:
        title = info.get('name', '')
        meta = [info.get('mgr', ''), info.get('code', '')]
        sections = [('지난 분기 시장과 펀드 성과', info.get('prev', '')),
                    ('다음 분기 시장 전망 및 펀드 운용 계획', info.get('next', ''))]
    ok = _render_summary_card(_page_path(out_dir, 1), meta, title, sections)
    if ok:
        print(f'    summary card: {title} ({info["type"]})')
    return 1 if ok else 0


def _export_excel(xapp, papp, path: Path, out_dir: Path, fund: str = '') -> int:
    # 멀티펀드 통합 엑셀 → 요약 카드 (실패 시 아래 일반 캡쳐로 폴백)
    summ = EXCEL_SUMMARY.get(fund)
    if summ:
        try:
            n = _export_excel_summary(xapp, path, out_dir, summ, fund)
            if n:
                return n
            print(f'    summary 추출 실패 → 시트 캡쳐 폴백: {path.name}')
        except Exception as exc:
            print(f'    summary 실패({type(exc).__name__}) → 시트 캡쳐 폴백: {path.name}')
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
                w, h = float(rng.Width), float(rng.Height)
                if w <= 0 or h <= 0 or w * h < MIN_SHEET_AREA:
                    continue
                if h / w > MAX_SHEET_RATIO:
                    print(f'    skip sheet "{ws.Name}" (세로/가로 {h / w:.1f} — 데이터 시트)')
                    continue
                rng.CopyPicture(Appearance=1, Format=-4147)  # xlScreen, xlPicture
                ok = _paste_to_png(papp, _page_path(out_dir, n + 1), w, h,
                                   lambda s: s.Shapes.Paste())
                if ok:
                    n += 1
            except Exception:
                continue
        return n
    finally:
        wb.Close(False)


_WD_GOTO_PAGE = 1
_WD_GOTO_ABSOLUTE = 1
_WD_STAT_PAGES = 2


def _export_word(wapp, papp, path: Path, out_dir: Path) -> int:
    """Word → 페이지별 PNG.

    ★ 2026-07-28 fix: 이전엔 `doc.Range()` 전체를 A4 한 장에 붙여넣고 무조건 1페이지로
    잘랐다(07G07 KB 코멘트 docx 가 전부 1p 로만 올라와 있던 원인). 이제 GoTo(wdGoToPage)
    로 페이지 경계를 잡아 페이지 단위로 복사한다. 용지 크기도 A4 가정 대신 문서 설정 사용.
    """
    doc = wapp.Documents.Open(str(path.resolve()), ReadOnly=True)
    try:
        try:
            n = int(doc.ComputeStatistics(_WD_STAT_PAGES))
        except Exception:
            n = 1
        n = max(1, min(n, MAX_SLIDES))
        ps = doc.PageSetup
        w, h = float(ps.PageWidth), float(ps.PageHeight)

        made = 0
        for i in range(1, n + 1):
            try:
                start = doc.GoTo(_WD_GOTO_PAGE, _WD_GOTO_ABSOLUTE, i).Start
                end = (doc.GoTo(_WD_GOTO_PAGE, _WD_GOTO_ABSOLUTE, i + 1).Start
                       if i < n else doc.Content.End)
                if end <= start:
                    continue
                doc.Range(start, end).Copy()
            except Exception:
                continue
            if _paste_to_png(papp, _page_path(out_dir, made + 1), w, h,
                             lambda s: s.Shapes.PasteSpecial(DataType=2)):  # EnhancedMetafile
                made += 1
        return made
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
    ok = fail = skip = drm = 0
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
            # 페이지 수가 줄면 이전 실행의 p03.png 같은 고아가 남는다 → 매번 비우고 시작
            for stale in list(out_dir.glob('p*.png')) + list(out_dir.glob('p*.webp')):
                stale.unlink(missing_ok=True)
            try:
                if ext in ('.ppt', '.pptx'):
                    n = _export_ppt(papp, src, out_dir)
                elif ext in ('.xls', '.xlsx'):
                    if xapp is None:
                        xapp = win32com.client.DispatchEx('Excel.Application')
                        xapp.Visible = False
                        xapp.DisplayAlerts = False
                    n = _export_excel(xapp, papp, src, out_dir, fund=str(e.get('fund') or ''))
                else:
                    if wapp is None:
                        wapp = win32com.client.DispatchEx('Word.Application')
                        wapp.Visible = False
                        wapp.DisplayAlerts = False
                    n = _export_word(wapp, papp, src, out_dir)
                clean = _clean_png_count(out_dir, n)
                if n and clean < n:
                    # 래핑본을 남기면 화면에 깨진 이미지가 뜬다 → 0 으로 두고 폴백시킨다
                    e['preview_pages'] = 0
                    drm += 1
                    print(f"  DRM {e['rel_path']} ({clean}/{n}p 만 클린 — 캡쳐 비활성)")
                    continue
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
    return {'ok': ok, 'fail': fail, 'skip': skip, 'drm': drm}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description='발송 운용보고 프리뷰 PNG 생성 (Office COM)')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()
    print(f'[sent_report_preview] {build_previews(force=args.force)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
