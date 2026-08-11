"""표0 '시작일' 토글 — 기초일 AP 스냅샷 (2026-08-11 사용자 지시).

좌측 열을 BM/SAA 목표비중 ↔ **기초일 보유비중** 으로 전환하는 토글의 백엔드.
기준일은 `start_date` **직전 영업일** — PA 창 (기초일, 기간말] 과 같은 시점이라
비중 변화가 기여도·수익률과 정확히 대응한다([[reference_pa_period_start_offbyone]]).
`start_date` 당일로 잡으면 시작일 매매가 이미 반영돼 기간 변화가 과소 표시된다.
"""
from datetime import date

import pytest

from api.services import brinson_service as bs


def test_prev_business_day_excludes_self():
    """★ 기준일은 start_date 자신이 아니라 그 직전 영업일이다."""
    # 2026-04-23(목) → 04-22(수)
    assert bs._prev_business_day(date(2026, 4, 23)) == date(2026, 4, 22)
    # 월요일 → 직전 금요일 (주말 건너뜀)
    assert bs._prev_business_day(date(2026, 8, 10)) == date(2026, 8, 7)
    # 화요일 → 월요일
    assert bs._prev_business_day(date(2026, 8, 11)) == date(2026, 8, 10)


def test_prev_business_day_never_returns_self():
    """어떤 영업일을 넣어도 자기 자신이 나오면 안 된다(off-by-one 회귀 방지)."""
    for d in (date(2026, 4, 23), date(2026, 7, 1), date(2026, 8, 7)):
        assert bs._prev_business_day(d) != d


@pytest.mark.parametrize("fund", ["08N81", "08K88"])
def test_base_composition_matches_end_shape(client, fund):
    """기초일 스냅샷은 기말과 **같은 경로**로 만들어져 형태가 호환돼야 한다.

    (build_holdings → _build_ap_composition) 이 아니면 좌우 비교가 성립하지 않는다.
    """
    r = client.get(f"/api/funds/{fund}/brinson",
                   params={"start_date": "2026-04-23", "end_date": "2026-07-22"})
    assert r.status_code == 200
    body = r.json()
    if body["meta"]["is_fallback"]:
        pytest.skip("brinson fallback")
    base = body.get("ap_composition_base") or []
    end = body.get("ap_composition") or []
    if not end:
        pytest.skip("ap_composition 미생성(스냅샷 부재)")
    assert base, "기초일 스냅샷이 비어 있다 — 토글이 프론트에서 사라진다"
    assert body["base_date"] == "2026-04-22"
    # 자산군 키 집합이 겹쳐야 좌우 행이 맞는다(완전 일치까지는 요구하지 않음 — 신규편입/전량편출)
    assert {c["asset_class"] for c in base} & {c["asset_class"] for c in end}
    for c in base:
        assert isinstance(c["weight_pct"], (int, float))
        assert "items" in c
    # 합계는 100% 근처 (현금·미수금 포함 스냅샷)
    tot = sum(c["weight_pct"] for c in base)
    assert 95.0 <= tot <= 105.0, f"기초일 비중 합계 이상: {tot}"


def test_base_absent_is_not_an_error(client):
    """설정일 이전 등으로 기초일 스냅샷이 없으면 base_date=None + 빈 리스트.

    예외로 죽지 않고 토글만 사라져야 한다(기능 무중단).
    """
    r = client.get("/api/funds/08N81/brinson",
                   params={"start_date": "2015-01-05", "end_date": "2015-01-30"})
    # 설정 전 구간은 서비스가 clamp 하거나 fallback — 어느 쪽이든 500 이면 안 된다
    assert r.status_code in (200, 400, 404)
    if r.status_code == 200:
        body = r.json()
        if not (body.get("ap_composition_base") or []):
            assert body.get("base_date") is None
