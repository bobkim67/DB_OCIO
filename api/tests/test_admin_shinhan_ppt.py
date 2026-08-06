"""신한라이프 월간보고 PPT 엔드포인트 (2JM23 전용, 2026-08-06).

생성(POST)은 PowerPoint COM 을 띄우므로 여기서 다루지 않는다 — 게이트·경로·
다운로드만 검증한다. 빌더 자체는 2026-06 발송본 대조로 수동 검증했다.
"""
import pytest


def test_other_fund_returns_empty(client):
    d = client.get("/api/admin/funds/08K88/shinhan-ppt",
                   params={"period": "2026-07"}).json()
    assert d["ready"] is False


def test_other_fund_generate_rejected(client):
    r = client.post("/api/admin/funds/08K88/shinhan-ppt/generate",
                    json={"period": "2026-07"})
    assert r.status_code == 400
    assert "2JM23" in r.json()["detail"]


def test_quarterly_period_rejected(client):
    """09/PA 가 월 단위라 월간만 지원 — 분기 키는 422."""
    r = client.post("/api/admin/funds/2JM23/shinhan-ppt/generate",
                    json={"period": "2026-Q2"})
    assert r.status_code == 422


def test_download_404_when_absent(client):
    r = client.get("/api/admin/funds/2JM23/shinhan-ppt/download",
                   params={"period": "2099-01"})
    assert r.status_code == 404


def test_download_other_fund_400(client):
    r = client.get("/api/admin/funds/08K88/shinhan-ppt/download",
                   params={"period": "2026-07"})
    assert r.status_code == 400


def test_path_helper_month_only():
    from api.routers.admin_funds import _shinhan_ppt_path
    assert _shinhan_ppt_path("2026-Q2") is None
    assert _shinhan_ppt_path("not-a-period") is None
    p = _shinhan_ppt_path("2026-07")
    assert p is not None and p.name.endswith("_202607_회신.pptx")


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
