# -*- coding: utf-8 -*-
"""KB국민은행 투자풀(07G07) 월간 워드 붙여넣기 엑셀 (2026-08-07).

신한(2JM23)과 같은 전환 — Word COM 치환기(`tools.kb_monthly_report.build_docx`)를
쓰지 않고, 이 엑셀에서 **블록 복사 → 발송본 워드 표에 붙여넣기** 한다.

생성 자체는 PA 를 여러 번 돌고 LLM 을 1회 태워 느리므로 여기서 다루지 않는다 —
배선·붙여넣기 격자·수치 표기 규약만 검증한다. 값은 2026-05 발송본 대조로
수동 검증했다 (요인 16셀 ±0.01%p, 절대성과 3값 정확 일치).
"""
from __future__ import annotations


def test_spec_wired_on_approve():
    from api.routers.admin_funds import _EXCEL_SPECS
    spec = _EXCEL_SPECS['07G07']
    assert spec['on'] == 'approve' and spec['kind'] == '월간'
    # 브린슨 엑셀 옵션이 붙으면 빌더 분기가 달라진다 (전용 빌더로 가야 한다)
    assert 'brinson' not in spec


def test_spec_name_matches_builder_out_name():
    """스펙 파일명 == 빌더 기본 출력명. 어긋나면 CLI 산출물과 admin 산출물이 갈린다."""
    from api.routers.admin_funds import _EXCEL_SPECS
    from tools.kb_monthly_excel import OUT_NAME
    assert _EXCEL_SPECS['07G07']['name'] == OUT_NAME


def test_excel_path_month_only():
    from api.routers.admin_funds import _excel_path
    assert _excel_path('07G07', '2026-Q2') is None
    p = _excel_path('07G07', '2026-07')
    assert p is not None and p.name.endswith('_202607.xlsx')


def test_factor_rows_match_sent_report_order():
    """워드 표3 자산군 행 순서 = 발송본 순서.

    ⚠ 엑셀은 **행 순서가 곧 정확도**다 — 워드 COM 치환기는 셀 좌표로 찍어서
      순서가 어긋나도 티가 안 났지만, 블록 복사는 값이 엉뚱한 행에 붙는다.
      (신한 엑셀 전환에서 채권 4행 순서가 뒤바뀌어 있던 것과 같은 함정)
    """
    from tools.kb_monthly_excel import FACTOR_ROWS
    assert FACTOR_ROWS == ('주식', '채권', 'FX', '유동성 및 비용')


def test_weight_keys_match_sent_report_order():
    from tools.kb_monthly_excel import WEIGHT_KEYS
    assert WEIGHT_KEYS == ('주식', '채권', '대체', '유동성')


def test_number_formats_are_strings():
    """값은 **문자열**로 쓴다.

    숫자+표시형식이면 '값만 붙여넣기' 에서 원본 숫자가 튀어나와 발송본 표기와
    달라진다 (신한 엑셀에서 확인된 함정).
    """
    from tools.kb_monthly_excel import _d1, _num2, _pct, _w1
    assert _pct(5.25) == '+5.25%' and _pct(-2.115) == '-2.12%'
    assert _num2(6.03) == '+6.03' and _num2(-7.3413) == '-7.34'
    assert _w1(37.04) == '37.0'
    assert _d1(3.0) == '+3.0' and _d1(-0.25) == '-0.2'


def test_fixed_lines_are_code_generated():
    """수치로만 결정되는 3줄은 LLM 을 안 태운다 (2JM23 성과 문장과 같은 규약)."""
    from datetime import date

    from tools.kb_monthly_excel import _fixed_lines
    raw = {'ret': {'m1': -7.3413, 'ytd': 1.7928, 'm1_ex': -3.7199,
                   'ytd_ex': 0.6419},
           'contrib': {'주식': -5.0, '채권': -0.8, 'FX': -1.52},
           'end': date(2026, 7, 31)}
    out = _fixed_lines(raw)
    assert out['성과_헤드라인'] == (
        'OCIO알아서 펀드 1개월 수익률은 -7.34% 연초 이후 수익률은 +1.79%')
    assert out['절대성과_환기여'] == '환기여수익률 -1.52%'
    assert out['bm_초과성과'] == '1개월 -3.72%, 연초 이후 +0.64%'


def test_fixed_lines_survive_missing_fx():
    """FX 행이 없어도 죽지 않는다 (FX 무보유 기간)."""
    from datetime import date

    from tools.kb_monthly_excel import _fixed_lines
    out = _fixed_lines({'ret': {'m1': 1.0, 'ytd': 2.0, 'm1_ex': 0.5,
                                'ytd_ex': 0.5},
                        'contrib': {}, 'end': date(2026, 7, 31)})
    assert out['절대성과_환기여'] == '환기여수익률 —'


def test_override_blocks_are_known_keys():
    """운용역 확정 문장(override)의 키는 워드 블록 목록에 있어야 한다.

    오타가 나면 조용히 무시돼 확정 문장이 LLM 초안으로 나간다.
    """
    from tools.kb_monthly_excel import _BLOCKS, NARRATIVE_OVERRIDES
    known = {k for k, _l, _n in _BLOCKS}
    for period, blocks in NARRATIVE_OVERRIDES.items():
        unknown = set(blocks) - known
        assert not unknown, f'{period}: {unknown}'


def test_check_flags_factor_sum_mismatch():
    """표3 안에서 두 기준(마스터 PA / 기준가)이 섞이면 경고해야 한다.

    2026-05 발송본이 실제로 그랬다 — 헤더 초과 +4.58 vs 요인 합계 +3.76.
    """
    from datetime import date

    from tools.kb_monthly_excel import SheetData, _check
    raw = {
        'ret': {'m1': 7.39, 'bm_m1': 2.80, 'm1_ex': 4.58, 'ytd': 0.0,
                'ytd_ex': 0.0, 'si': 0.0},
        'factors': {k: {'alloc': 0.0, 'select': 0.0, 'other': 0.0, 'sum': 0.0}
                    for k in ('주식', '채권', 'FX', '유동성 및 비용')},
        'factor_total': {'alloc': -0.06, 'select': 3.11, 'other': 0.71,
                         'sum': 3.76},
        'weights': {'주식': 37.0, '채권': 62.5, '대체': 0.0, '유동성': 0.5},
        'weights_prev': {}, 'saa': {}, 'contrib': {}, 'end': date(2026, 5, 31),
    }
    d = SheetData(period='2026-05', raw=raw)
    _check(d)
    assert any('어긋납니다' in w for w in d.warnings), d.warnings
