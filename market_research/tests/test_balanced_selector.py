"""balanced_selector 공통 모듈 단위 테스트. LLM 0, IO 0."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.core.balanced_selector import (  # noqa: E402
    SelectionParams, balanced_select,
)

# 콜백 (item = dict)
_S = lambda x: x["sal"]
_T = lambda x: x["topic"]
_A = lambda x: x.get("asset")
_W = lambda x: x.get("week")
_M = lambda x: x.get("ms", False)
_I = lambda x: x["id"]


def _sel(items, params):
    return balanced_select(items, params, salience_of=_S, topic_of=_T,
                           asset_of=_A, id_of=_I, week_of=_W, milestone_of=_M)


def _mk(i, sal, topic, asset=None, week=None, ms=False):
    return {"id": i, "sal": sal, "topic": topic, "asset": asset, "week": week, "ms": ms}


def test_empty_input():
    r = _sel([], SelectionParams(n=10))
    assert r.selected == [] and r.reasons == {}


def test_n_zero():
    r = _sel([_mk("a", 0.9, "t")], SelectionParams(n=0))
    assert r.selected == []


def test_fewer_than_n_returns_all():
    items = [_mk(f"a{i}", 0.5, "t", asset="국내주식", week=1) for i in range(3)]
    r = _sel(items, SelectionParams(n=10, min_per_week=1, min_per_asset=1))
    assert len(r.selected) == 3


def test_topic_cap_enforced():
    # 지정학 고salience 다수 + 다른 토픽/자산 충분 → fill 이 n 을 cap 내에서 채움.
    # n=10, cap 25% => ceil(2.5)=3 → 지정학 ≤3.
    items = [_mk(f"g{i}", 0.9 - i * 0.01, "지정학", asset="해외주식", week=1) for i in range(15)]
    items += [_mk(f"a{i}", 0.5, "경기_소비", asset="국내주식", week=2) for i in range(5)]
    items += [_mk(f"b{i}", 0.5, "금리_채권", asset="국내채권", week=3) for i in range(5)]
    items += [_mk(f"c{i}", 0.5, "통화정책", asset="해외채권", week=4) for i in range(5)]
    r = _sel(items, SelectionParams(n=10, min_per_week=0, min_per_asset=0,
                                    topic_cap_frac=0.25, milestone_slots=0))
    geo = sum(1 for x in r.selected if x["topic"] == "지정학")
    assert geo <= 3, f"지정학 {geo} > cap 3"
    assert len(r.selected) == 10  # cap 내에서 n 충족 (relaxed fill 불필요)


def test_asset_quota_floor():
    # 각 자산군 1개씩 존재 → min_per_asset=1 이면 모두 포함
    assets = ["국내주식", "해외주식", "국내채권", "해외채권", "환율", "원자재에너지", "금대체"]
    items = []
    for j, a in enumerate(assets):
        items.append(_mk(f"{a}", 0.5 + j * 0.01, "t", asset=a, week=1))
    # 노이즈 (지정학 다수, 고salience)
    items += [_mk(f"n{i}", 0.95, "지정학", asset="해외주식", week=1) for i in range(20)]
    r = _sel(items, SelectionParams(n=12, min_per_week=0, min_per_asset=1,
                                    topic_cap_frac=0.4, milestone_slots=0))
    present = {x["asset"] for x in r.selected}
    for a in assets:
        assert a in present, f"asset {a} 누락 (quota floor 실패)"


def test_week_quota():
    items = []
    for w in (1, 2, 3, 4, 5):
        for i in range(10):
            items.append(_mk(f"w{w}_{i}", 0.5, "t", asset="국내주식", week=w))
    r = _sel(items, SelectionParams(n=25, min_per_week=5, min_per_asset=0,
                                    topic_cap_frac=1.0, milestone_slots=0))
    for w in (1, 2, 3, 4, 5):
        cnt = sum(1 for x in r.selected if x["week"] == w)
        assert cnt >= 5, f"W{w} {cnt} < 5"


def test_milestone_rescue_latest_and_salient():
    # 마일스톤: 최신(week5, 저sal) + 고sal(week1) 둘 다 들어와야
    items = [
        _mk("ms_late", 0.30, "테크", asset="국내주식", week=5, ms=True),
        _mk("ms_early", 0.95, "테크", asset="국내주식", week=1, ms=True),
    ]
    items += [_mk(f"f{i}", 0.6, "지정학", asset="해외주식", week=2) for i in range(20)]
    r = _sel(items, SelectionParams(n=10, milestone_slots=3))
    assert "ms_late" in r.reasons and r.reasons["ms_late"] == "milestone_rescue"
    assert "ms_early" in r.reasons


def test_reasons_and_ids_present():
    items = [_mk(f"a{i}", 0.5, "t", asset="국내주식", week=1) for i in range(5)]
    r = _sel(items, SelectionParams(n=3, min_per_week=1, min_per_asset=1, milestone_slots=0))
    assert len(r.selected_ids) == len(r.selected) == 3
    assert all(rid in r.reasons for rid in r.selected_ids)


def test_n_guaranteed_under_tight_cap():
    # 전부 같은 topic, cap 으로 막혀도 relaxed fill 로 n 채움
    items = [_mk(f"a{i}", 0.9 - i * 0.01, "지정학", asset="해외주식", week=1) for i in range(20)]
    r = _sel(items, SelectionParams(n=10, min_per_week=0, min_per_asset=0,
                                    topic_cap_frac=0.2, milestone_slots=0))
    assert len(r.selected) == 10
    assert any(v == "salience_fill_relaxed" for v in r.reasons.values())


def test_deterministic():
    items = [_mk(f"a{i}", 0.5 + (i % 3) * 0.1, "t", asset="국내주식", week=(i % 5) + 1)
             for i in range(30)]
    p = SelectionParams(n=12)
    r1 = _sel(items, p)
    r2 = _sel(items, p)
    assert [x["id"] for x in r1.selected] == [x["id"] for x in r2.selected]
