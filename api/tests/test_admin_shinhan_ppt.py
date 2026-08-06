"""신한라이프 월간보고 PPT (2JM23 전용, 2026-08-06).

2026-08-06 사용자 지시로 **SAA 펀드 엑셀과 같은 경로**로 통합됐다 — 전용
엔드포인트 3종은 사라지고 `_EXCEL_SPECS['2JM23']` 에 얹혀 보고서 승인 시
재생성 + `/report/excel` 다운로드를 탄다. 생성(승인)은 PowerPoint COM 을 띄우므로
여기서 다루지 않는다 — 경로·스펙 결선만 검증한다.
빌더 자체는 2026-06 발송본 대조로 수동 검증했다.
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
    """스펙의 파일명 == 빌더가 실제로 쓰는 이름. 어긋나면 승인해도 '없음'이 뜬다."""
    from api.routers.admin_funds import _EXCEL_SPECS, SHINHAN_PPT_FUND
    from tools.shinhan_monthly_ppt import OUT_NAME
    assert _EXCEL_SPECS[SHINHAN_PPT_FUND]["name"] == OUT_NAME


def test_excel_path_month_only():
    from api.routers.admin_funds import _excel_path
    assert _excel_path("2JM23", "2026-Q2") is None
    assert _excel_path("2JM23", "not-a-period") is None
    p = _excel_path("2JM23", "2026-07")
    assert p is not None and p.name.endswith("_202607_회신.pptx")


def test_download_404_when_absent(client):
    r = client.get("/api/admin/funds/2JM23/report/excel",
                   params={"period": "2099-01"})
    assert r.status_code == 404


def test_removed_endpoints_are_gone(client):
    """구 전용 엔드포인트는 제거됐다 — 프론트가 이 경로를 다시 물면 안 된다.

    POST 가 405 인 건 SPA fallback(GET catch-all)이 경로만 먼저 잡기 때문 —
    라우트가 없다는 뜻은 같다.
    """
    assert client.get("/api/admin/funds/2JM23/shinhan-ppt",
                      params={"period": "2026-07"}).status_code == 404
    assert client.post("/api/admin/funds/2JM23/shinhan-ppt/generate",
                       json={"period": "2026-07"}).status_code in (404, 405)


# ── 빌더 순수 로직 (COM·DB 미사용) ──

def test_prev_ym_rollover():
    from tools.shinhan_monthly_ppt import _prev_ym
    assert _prev_ym("2026-07") == "202606"
    assert _prev_ym("2026-01") == "202512"


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
    from tools.shinhan_monthly_ppt import AllocRow
    r = AllocRow("주식", "한국 주식", cur_w=11.10, prev_w=32.61)
    assert round(r.delta, 2) == -21.51      # 2026-06 발송본 실측값


def test_skeleton_covers_mapping_targets():
    """TAA_SO_TO_PPT_ROW 의 목적지가 전부 PPT 골격에 존재해야 한다."""
    from config.taa_classification import SHINHAN_PPT_SKELETON, TAA_SO_TO_PPT_ROW
    labels = {lbl for _, lbl in SHINHAN_PPT_SKELETON}
    assert set(TAA_SO_TO_PPT_ROW.values()) <= labels
