"""Brinson snapshot pytest — handoff 조건 2 충족용.

골든값: 08K88(방법3) + 4JM12(방법4) × 2026-01-08~2026-03-12.
R Excel 검증분 기간 (PA_single_*_(2026-01-08 ~ 2026-03-12)_방법3_FXsplit=TRUE.xlsx) 과 동일.

락:
  - totals 9 키 (rel 1e-3, AP/BM/Alloc/Select/Cross/Excess/ExcessRel/FX/Residual)
  - asset_rows 의 자산군별 alloc/select/cross/contrib (rel 1e-3)
  - sec_top5 의 종목명 + 기여수익률 (rel 1e-2)

스냅샷 갱신: 의도적 골든 변경 시 `api/tests/snapshots/brinson_*.json` 파일을 직접 갱신.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import urllib.parse

SNAP_DIR = Path(__file__).parent / "snapshots"

CASES = [
    ("08K88", "방법3", "2026-01-08", "2026-03-12"),
    ("4JM12", "방법4", "2026-01-08", "2026-03-12"),
]


def _load_snapshot(fund: str, method: str, sd: str, ed: str) -> dict:
    fp = SNAP_DIR / f"brinson_{fund}_{method}_{sd}_{ed}.json"
    return json.loads(fp.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fund,method,sd,ed", CASES)
def test_brinson_snapshot_totals(client, fund, method, sd, ed):
    snap = _load_snapshot(fund, method, sd, ed)
    r = client.get(
        f"/api/funds/{fund}/brinson",
        params={"start_date": sd, "end_date": ed,
                "mapping_method": method},
    )
    assert r.status_code == 200
    body = r.json()
    if body["meta"]["is_fallback"]:
        pytest.skip(f"fallback (DB unavailable) for {fund}")
    for k, expected in snap["totals"].items():
        actual = body[k]
        assert actual == pytest.approx(expected, rel=1e-3, abs=1e-4), \
            f"{fund} {method} totals.{k}: expected={expected} actual={actual}"


@pytest.mark.parametrize("fund,method,sd,ed", CASES)
def test_brinson_snapshot_asset_rows(client, fund, method, sd, ed):
    snap = _load_snapshot(fund, method, sd, ed)
    r = client.get(
        f"/api/funds/{fund}/brinson",
        params={"start_date": sd, "end_date": ed,
                "mapping_method": method},
    )
    body = r.json()
    if body["meta"]["is_fallback"]:
        pytest.skip(f"fallback for {fund}")
    snap_rows = {row["asset_class"]: row for row in snap["asset_rows"]}
    body_rows = {row["asset_class"]: row for row in body["asset_rows"]}
    assert set(body_rows.keys()) == set(snap_rows.keys()), \
        f"{fund} asset_class set differs: snap={set(snap_rows)} body={set(body_rows)}"
    for ac, snap_row in snap_rows.items():
        body_row = body_rows[ac]
        for fld in ("alloc_effect", "select_effect", "cross_effect", "contrib_return"):
            assert body_row[fld] == pytest.approx(snap_row[fld], rel=1e-3, abs=1e-4), \
                f"{fund} {ac} {fld}: snap={snap_row[fld]} body={body_row[fld]}"


@pytest.mark.parametrize("fund,method,sd,ed", CASES)
def test_brinson_snapshot_sec_top5(client, fund, method, sd, ed):
    snap = _load_snapshot(fund, method, sd, ed)
    r = client.get(
        f"/api/funds/{fund}/brinson",
        params={"start_date": sd, "end_date": ed,
                "mapping_method": method},
    )
    body = r.json()
    if body["meta"]["is_fallback"]:
        pytest.skip(f"fallback for {fund}")
    snap_top5 = snap["sec_top5"]
    body_top5 = body["sec_contrib"][:5]
    assert len(body_top5) == len(snap_top5), \
        f"{fund} sec_top5 length differs"
    for i, (s, b) in enumerate(zip(snap_top5, body_top5)):
        assert s["item_nm"] == b["item_nm"], \
            f"{fund} sec_top5[{i}].item_nm: snap={s['item_nm']} body={b['item_nm']}"
        assert b["contrib_pct"] == pytest.approx(s["contrib_pct"], rel=1e-2, abs=1e-3), \
            f"{fund} sec_top5[{i}].contrib_pct: snap={s['contrib_pct']} body={b['contrib_pct']}"
