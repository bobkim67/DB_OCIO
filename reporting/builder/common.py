"""운용보고 PPT 빌더 — 공통 상수·A4 셸·pptx 헬퍼.

P0' 파일럿(pilot/pilot_s7.py)에서 확정한 스펙을 패키지화:
  - A4 가로 29.7x21cm, base 1600x900 → 1600x1131 (y500 흰행 삽입, 헤더/푸터 무왜곡)
  - 콘텐츠 y196~1055 선형 재배치 SV=1.3678, 본문 12pt 고정
  - 한글 a:ea/a:cs 슬롯, 표 셀 tcPr@anchor, 빈 셀 문단 폰트, ko-KR
  - 밴드 전폭 균일화 + 코너딥 평탄화, 로고/제목/페이지번호 = 편집 개체로 분리
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
from matplotlib import font_manager
import matplotlib.pyplot as plt

BUILDER = Path(__file__).parent
ROOT = BUILDER.parent                     # reporting/
REPO = ROOT.parent                        # DB_OCIO_Webview
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))         # modules/, config/ import 용

OUT = ROOT / 'out'
FONTS = ROOT / 'template' / 'fonts'
BASE_DIR = ROOT / 'template' / 'base'
KI_LOGO = REPO / 'web' / 'public' / 'ki-logo.png'

for _f in FONTS.glob('*.otf'):
    font_manager.fontManager.addfont(str(_f))
plt.rcParams['font.family'] = 'Pretendard'

# ── A4 좌표계 ──
EMU_A4_W, EMU_A4_H = 10_692_000, 7_560_000          # 29.7 x 21 cm
EMU_PER_PX = EMU_A4_W / 1600                         # 6682.5
PX_H = 1131
PT_PER_PX = 72 / (1600 / (EMU_A4_W / 914_400))       # 0.5262 (제목패널 비례 환산)
BODY_PT = 12                                         # 본문 고정
CANVAS_OFF = (40, 192)
_FOOT_OLD, _FOOT_NEW, _HDR = 824, 824 + (PX_H - 900), 196   # 푸터라인 1055
SV = (_FOOT_NEW - _HDR) / (_FOOT_OLD - _HDR)                 # 1.3678

# 색 (발송본 팔레트)
HDR_BLUE = '5B9BD5'; Z1 = 'D2DEEF'; Z2 = 'EAEFF7'
C_FUND = '#2E5E9E'; C_BM = '#E0A800'; C_EXC = '#B9C9E8'
BROWN = '7B401F'; INK = '222222'; RED = 'C00000'; BLUE = '0563C1'
PHASE_NAME = {1: '회복', 2: '팽창', 3: '침체', 4: '둔화'}


def remap(y):
    """900px 레이아웃 y → A4(1131px) 콘텐츠존 y."""
    return round(_HDR + (y - _HDR) * SV) if y >= _HDR else y


def sv(h):
    """세로 길이 스케일."""
    return round(h * SV)


# ──────────────────────────── A4 셸 base ────────────────────────────
def make_shell(base_name: str) -> Path:
    """base_slideNN.png → A4 셸: 제목/로고/페이지번호 제거, 밴드 균일화, 세로 확장."""
    from PIL import Image, ImageDraw
    import numpy as np
    src = BASE_DIR / base_name
    im = Image.open(src).convert('RGB')
    d = ImageDraw.Draw(im)
    d.rectangle([25, 12, 1150, 118], fill='white')     # 제목 (편집 텍스트로 대체)
    d.rectangle((1460, 12, 1576, 37), fill='white')    # 저해상 로고 (고해상 개체로 대체)
    d.rectangle((1480, 826, 1590, 890), fill='white')  # 페이지번호 (편집 텍스트로 대체)
    d.rectangle((30, 780, 1470, 823), fill='white')    # 푸터라인(824) 위 잘린 각주 잔재 (base09 등)
    d.rectangle((30, 825, 1470, 831), fill='white')    # 라인 아래 잔재 디센더 (base09)
    a = np.array(im)
    a[118:196, :] = 255                                # 제목 하단 음영밴드 제거 (2026-07-14 사용자 지시)
    filler = np.repeat(a[500:501, :, :], PX_H - 900, axis=0)   # y500 = 균일 백색 행
    a = np.vstack([a[:500], filler, a[500:]])
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f'shell_{base_name}'
    Image.fromarray(a).save(p)
    return p


# ──────────────────────────── pptx 헬퍼 ────────────────────────────
from pptx import Presentation                                  # noqa: E402
from pptx.util import Emu, Pt                                  # noqa: E402
from pptx.dml.color import RGBColor                            # noqa: E402
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR                # noqa: E402
from pptx.enum.shapes import MSO_SHAPE                         # noqa: E402
from pptx.enum.lang import MSO_LANGUAGE_ID                     # noqa: E402
from pptx.oxml.ns import qn                                    # noqa: E402
from lxml import etree                                         # noqa: E402


def E(px):
    return Emu(round(px * EMU_PER_PX))


def set_ko_font(font, family):
    """a:latin 만으로는 한글이 테마 EA(맑은고딕)로 폴백 — a:ea/a:cs 도 지정."""
    font.language_id = MSO_LANGUAGE_ID.KOREAN
    rPr = font._rPr
    latin = rPr.find(qn('a:latin')) if rPr is not None else None
    if latin is None:
        return
    for tag in ('a:cs', 'a:ea'):            # addnext 역순 → latin, ea, cs 순서
        e = rPr.makeelement(qn(tag), {'typeface': family})
        latin.addnext(e)


def new_presentation():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(EMU_A4_W), Emu(EMU_A4_H)
    return prs


def add_text(sl, px_x, px_y, px_w, px_h, text, pt_size, color, bold=False,
             family='Pretendard', align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
             wrap=False):
    tb = sl.shapes.add_textbox(E(px_x), E(px_y), E(px_w), E(px_h))
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run(); r.text = text
    r.font.name = family; r.font.size = Pt(pt_size)
    r.font.bold = bold; r.font.color.rgb = RGBColor.from_string(color)
    set_ko_font(r.font, family)
    return tb


def add_bullets(sl, px_x, px_y, px_w, lines, pt_size=BODY_PT, color=INK,
                line_gap_px=None):
    """여러 불릿 문단 텍스트박스 (word_wrap, 문단 간격)."""
    from pptx.util import Pt as _Pt
    tb = sl.shapes.add_textbox(E(px_x), E(px_y), E(px_w), E(40 * len(lines)))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if i > 0:
            p.space_before = _Pt((line_gap_px or sv(14)) * PT_PER_PX / 0.75)  # px→pt 근사
        r = p.add_run(); r.text = line
        r.font.name = 'Pretendard'; r.font.size = Pt(pt_size)
        r.font.color.rgb = RGBColor.from_string(color)
        set_ko_font(r.font, 'Pretendard')
    return tb


def add_pbar(sl, px_x, px_y, px_w, text, px_h=None):
    """파란 소제목 바 (편집 가능 도형)."""
    h = px_h or sv(34)
    sh = sl.shapes.add_shape(MSO_SHAPE.RECTANGLE, E(px_x), E(px_y), E(px_w), E(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = RGBColor.from_string(HDR_BLUE)
    sh.line.fill.background()
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = text
    r.font.name = 'Pretendard'; r.font.size = Pt(BODY_PT)
    r.font.bold = True; r.font.color.rgb = RGBColor.from_string('FFFFFF')
    set_ko_font(r.font, 'Pretendard')
    return sh


def add_table(sl, px_x, px_y, col_w_px, row_h_px, rows_spec):
    """네이티브 표. rows_spec: [(fill_hex|None, [(text, bold, color_hex), ...]), ...]"""
    n_r, n_c = len(rows_spec), len(col_w_px)
    gf = sl.shapes.add_table(n_r, n_c, E(px_x), E(px_y),
                             E(sum(col_w_px)), E(sum(row_h_px)))
    tbl = gf.table
    tblPr = tbl._tbl.tblPr
    tblPr.set('firstRow', '0'); tblPr.set('bandRow', '0')
    sid = tblPr.find(qn('a:tableStyleId'))
    if sid is not None:
        sid.text = '{2D5ABB26-0587-4C30-8999-92F81FD0307C}'   # No Style, No Grid
    for i, w in enumerate(col_w_px):
        tbl.columns[i].width = E(w)
    for i, h in enumerate(row_h_px):
        tbl.rows[i].height = E(h)
    for ri, (fill, cells) in enumerate(rows_spec):
        for ci, (text, bold, color) in enumerate(cells):
            cell = tbl.cell(ri, ci)
            if fill:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(fill)
            if ri < n_r - 1:                          # 행 사이 2px 흰 경계
                tcPr = cell._tc.get_or_add_tcPr()
                ln = etree.SubElement(tcPr, qn('a:lnB'))
                ln.set('w', '15240'); ln.set('cap', 'flat')
                sf = etree.SubElement(ln, qn('a:solidFill'))
                etree.SubElement(sf, qn('a:srgbClr')).set('val', 'FFFFFF')
                tcPr.insert(0, ln)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE   # 표 셀 세로가운데 = tcPr@anchor
            tf = cell.text_frame
            tf.margin_left = tf.margin_right = Emu(round(2 * EMU_PER_PX))
            tf.margin_top = tf.margin_bottom = 0
            tf.word_wrap = False
            p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
            p.font.name = 'Pretendard'; p.font.size = Pt(BODY_PT)   # 빈 셀 행높이 방지
            set_ko_font(p.font, 'Pretendard')
            if text:
                r = p.add_run(); r.text = text
                r.font.name = 'Pretendard'; r.font.size = Pt(BODY_PT)
                r.font.bold = bold; r.font.color.rgb = RGBColor.from_string(color)
                set_ko_font(r.font, 'Pretendard')
    return gf


def kdate(iso):
    y, m, d = iso.split('-')
    return f'{y}년 {int(m)}월 {int(d)}일'


def slide_scaffold(prs, base_name, title, asof_iso, page_label, subtitle='기준일'):
    """공통 골격: A4 셸 배경 + 고해상 로고 + 제목 + 부제 + 페이지번호.

    subtitle: '기준일'(기본 — asof 로 포맷) | 임의 문자열 | None(생략, s11/12 등)
    """
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    sl.shapes.add_picture(str(make_shell(base_name)), 0, 0, Emu(EMU_A4_W), Emu(EMU_A4_H))
    LOGO_W = 150
    LOGO_H = round(LOGO_W * 607 / 2467)
    sl.shapes.add_picture(str(KI_LOGO), E(1600 - 27 - LOGO_W), E(14), E(LOGO_W), E(LOGO_H))
    add_text(sl, 36, 22, 1000, 96, title, 76 * PT_PER_PX, '000000', family='Pretendard Black')
    if subtitle == '기준일':
        subtitle = f'기준일: {kdate(asof_iso)}'
    if subtitle:
        add_text(sl, 55, 133, 1100, 34, subtitle, 26 * PT_PER_PX, BROWN, bold=True)
    add_text(sl, 1440, 1062, 120, 30, page_label, 24 * PT_PER_PX, '444444',
             align=PP_ALIGN.RIGHT)
    return sl
