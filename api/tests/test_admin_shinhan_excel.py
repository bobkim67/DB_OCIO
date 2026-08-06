"""신한라이프 월간보고 엑셀 (2JM23 전용).

2026-08-06 사용자 지시로 **PPT COM 치환기를 폐기하고 엑셀 2시트로 대체**했다
(`tools/shinhan_monthly_excel.py` — Comment · 자산배분현황). 배선은 SAA 펀드
엑셀과 같은 `_EXCEL_SPECS['2JM23']` 경로 — 보고서 승인 시 재생성,
`/report/excel` 다운로드.

생성 자체는 PA 를 두 번 돌아 느리므로 여기서 다루지 않는다 — 경로·스펙 결선과
붙여넣기 규약(표 골격)만 검증한다. 값은 2026-07 발송본 대조로 수동 검증했다.
"""
import pytest


def test_spec_wired_on_approve():
    """보고서 **승인** 단계에 걸려야 한다 (4JM12 처럼 generate 가 아니라)."""
    from api.routers.admin_funds import _EXCEL_SPECS, SHINHAN_PPT_FUND
    spec = _EXCEL_SPECS[SHINHAN_PPT_FUND]
    assert spec["on"] == "approve" and spec["kind"] == "월간"
    # 브린슨 엑셀 옵션이 붙으면 안 된다 — 빌더 분기가 달라진다
    assert "brinson" not in spec


def test_spec_name_matches_builder_out_name():
    """스펙 파일명 == 빌더 기본 출력명. 어긋나면 CLI 산출물과 admin 산출물이 갈린다."""
    from api.routers.admin_funds import _EXCEL_SPECS, SHINHAN_PPT_FUND
    from tools.shinhan_monthly_excel import OUT_NAME
    assert _EXCEL_SPECS[SHINHAN_PPT_FUND]["name"] == OUT_NAME


def test_excel_path_month_only():
    from api.routers.admin_funds import _excel_path
    assert _excel_path("2JM23", "2026-Q2") is None
    assert _excel_path("2JM23", "not-a-period") is None
    p = _excel_path("2JM23", "2026-07")
    assert p is not None and p.name.endswith("_202607_데이터.xlsx")


def test_download_404_when_absent(client):
    r = client.get("/api/admin/funds/2JM23/report/excel",
                   params={"period": "2099-01"})
    assert r.status_code == 404


def test_ppt_builder_is_gone():
    """PPT COM 치환기는 폐기됐다 — 되살아나면 두 산출물이 갈린다."""
    with pytest.raises(ImportError):
        __import__("tools.shinhan_monthly_ppt")


def test_removed_endpoints_are_gone(client):
    """구 전용 엔드포인트는 제거됐다 — 프론트가 이 경로를 다시 물면 안 된다.

    POST 가 405 인 건 SPA fallback(GET catch-all)이 경로만 먼저 잡기 때문 —
    라우트가 없다는 뜻은 같다.
    """
    assert client.get("/api/admin/funds/2JM23/shinhan-ppt",
                      params={"period": "2026-07"}).status_code == 404
    assert client.post("/api/admin/funds/2JM23/shinhan-ppt/generate",
                       json={"period": "2026-07"}).status_code in (404, 405)


# ── 붙여넣기 규약 (발송본 표 골격) ──

def test_alloc_header_matches_sent_report():
    """자산배분 표 8열 — 2026-07 발송본 COM 덤프와 글자 그대로 같아야 한다.

    자동 산출 4열이 D~G 로 **연속**이어야 D:G 블록 복사가 성립한다.
    """
    from tools.shinhan_monthly_excel import ALLOC_HEADER
    assert ALLOC_HEADER == (
        '자산군', '세부자산군', 'TAA(%)', '당월말 비중(%)',
        '전월말 비중(%)', '비중 변화(%p)', '성과 기여도(%p)', '비고')
    assert ALLOC_HEADER[3:7] == ('당월말 비중(%)', '전월말 비중(%)',
                                 '비중 변화(%p)', '성과 기여도(%p)')


def test_sec_header_matches_sent_report():
    """종목 표 7열 — 자동 산출 6열이 A~F 로 연속, G 만 수기."""
    from tools.shinhan_monthly_excel import SEC_HEADER
    assert SEC_HEADER == (
        '순번', '종목명', '세부 자산군', '비중(%)', '월 수익률(%)',
        '연초후 수익률 기여도(%p)', '향후 관리 방안')


def test_skeleton_row_order_matches_sent_report():
    """행 순서 = 발송본 표 순서. 어긋나면 붙여넣은 값이 엉뚱한 행에 들어간다.

    ⚠ 채권 4행이 하이일드/미국장기/한국중기/한국장기 순이다 — 종전 상수는
      한국장기와 미국장기가 뒤바뀌어 있었다(PPT 치환기는 라벨 매칭이라 무해했음).
    """
    from config.taa_classification import SHINHAN_PPT_SKELETON
    assert SHINHAN_PPT_SKELETON == (
        ('주식', '미국 주식'),
        ('주식', '미국 성장주'),
        ('주식', '한국 주식'),
        ('채권', '미국 하이일드'),
        ('채권', '미국 장기채권'),
        ('채권', '한국 중기채권'),
        ('채권', '한국 장기채권'),
        ('대체', '금'),
        ('현금', '현금'),
    )


# ── 빌더 순수 로직 (COM·DB 미사용) ──

def test_disp_len_counts_hangul_as_two():
    """열 폭 계산 — 한글을 1칸으로 세면 표가 잘린다."""
    from tools.shinhan_monthly_excel import _disp_len
    assert _disp_len('AB') == 2
    assert _disp_len('한글') == 4
    assert _disp_len('금 ETF') == 6


def test_value_formatting_matches_sent_report():
    """발송본 표기 — 자산배분은 '%' 포함, 종목표는 숫자만."""
    from tools.shinhan_monthly_excel import _num, _pct
    assert _pct(39.45) == '39.45%'
    assert _pct(-1.08) == '-1.08%'
    assert _num(29.82) == '29.82'
    assert _num(-12.2) == '-12.20'


@pytest.mark.parametrize("isin,expect", [
    ("KR7367380003", "미국 성장주"),      # ACE 미국나스닥100
    ("US78464A4094", "미국 성장주"),      # SPDR S&P500 Growth — 같은 행으로 합산
    ("KR7105190003", "한국 주식"),
    ("KR7365780006", "한국 장기채권"),    # 자산군_소 '한국 10년국고채권'
    ("US46436F1030", "금"),
    ("XX0000000000", None),              # 미등록 → None (조용히 흘리지 않음)
])
def test_taa_ppt_row_mapping(isin, expect):
    from config.taa_classification import ppt_row_for
    assert ppt_row_for(isin) == expect


def test_alloc_row_delta():
    from tools.shinhan_monthly_excel import AllocRow
    r = AllocRow("주식", "한국 주식", cur_w=11.10, prev_w=32.61)
    assert round(r.delta, 2) == -21.51      # 2026-06 발송본 실측값


def test_skeleton_covers_mapping_targets():
    """TAA_SO_TO_PPT_ROW 의 목적지가 전부 표 골격에 존재해야 한다."""
    from config.taa_classification import SHINHAN_PPT_SKELETON, TAA_SO_TO_PPT_ROW
    labels = {lbl for _, lbl in SHINHAN_PPT_SKELETON}
    assert set(TAA_SO_TO_PPT_ROW.values()) <= labels
