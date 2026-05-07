# -*- coding: utf-8 -*-
"""Plan B BM 보강 회귀: KAP_BOND_TR / HY_TR 컬럼이 indicators.csv 에 들어왔을 때
asset_movement_anchor 가 국내채권 / 크레딧 자산군을 level_pct 가격 변동 기준
movement_direction + return_pct 로 산출하는지 검증.

지난 사이클까지 국내채권 = BOK_RATE bp_diff (정책금리), 크레딧 = US_HY_OAS bp_diff
(스프레드) proxy 였음. Plan B 로 KAP종합채권 (dt.BMJISU) + Bloomberg US HY TR
(SCIP id=401) 가격 anchor 로 교체.

LLM 호출 0. tmp_path / monkeypatch 만 사용.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _make_indicators_csv(tmp_path: Path,
                         kap_start: float = 270.0, kap_end: float = 272.5,
                         hy_start: float = 2900.0, hy_end: float = 2949.0) -> Path:
    """Plan B 컬럼 (KAP_BOND_TR, HY_TR) + 기존 컬럼 모두 포함.

    국내채권 4월 +0.93% / 크레딧 4월 +1.69% 시나리오 default.
    """
    csv_text = (
        "date,DXY,USDKRW,SP500_TR,MSCI_KOREA,GOLD,US_HY_OAS,FED_UPPER,"
        "UST_7_10Y_TR,KAP_BOND_TR,HY_TR\n"
        f"2026-04-01,103.0,1450.0,5500.0,90.0,2300.0,320.0,5.50,180.0,"
        f"{kap_start},{hy_start}\n"
        f"2026-04-30,104.5,1500.0,5400.0,87.0,2400.0,340.0,5.50,178.5,"
        f"{kap_end},{hy_end}\n"
    )
    fp = tmp_path / "indicators.csv"
    fp.write_text(csv_text, encoding="utf-8")
    return fp


# ──────────────────────────────────────────────────────────────────
# 1. _ASSET_TO_INDICATOR mapping 자체 검증
# ──────────────────────────────────────────────────────────────────

def test_asset_to_indicator_mapping_uses_new_columns():
    """국내채권 / 크레딧 매핑이 신규 level_pct 컬럼을 가리킨다."""
    from market_research.report.asset_movement_anchor import _ASSET_TO_INDICATOR

    col, kind, label = _ASSET_TO_INDICATOR["국내채권"]
    assert col == "KAP_BOND_TR"
    assert kind == "level_pct", f"국내채권 kind must be level_pct, got {kind}"
    assert "KAP" in label

    col, kind, label = _ASSET_TO_INDICATOR["크레딧"]
    assert col == "HY_TR"
    assert kind == "level_pct", f"크레딧 kind must be level_pct, got {kind}"
    assert "HY" in label

    # 현금성 / 해외채권 / FX / 원자재금 / 주식 매핑 변경 없음 확인
    assert _ASSET_TO_INDICATOR["현금성"][0] == "FED_UPPER"
    assert _ASSET_TO_INDICATOR["현금성"][1] == "bp_diff"
    assert _ASSET_TO_INDICATOR["해외채권"][0] == "UST_7_10Y_TR"
    assert _ASSET_TO_INDICATOR["국내주식"][0] == "MSCI_KOREA"
    assert _ASSET_TO_INDICATOR["해외주식"][0] == "SP500_TR"


# ──────────────────────────────────────────────────────────────────
# 2. KAP_BOND_TR 가 indicators.csv 에 있을 때 국내채권 anchor return_pct 산출
# ──────────────────────────────────────────────────────────────────

def test_domestic_bond_uses_kap_bond_tr_level_pct(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    ind = _make_indicators_csv(tmp_path,
                               kap_start=270.0, kap_end=272.5)  # +0.926%
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=ind,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    bond = by_ac["국내채권"]
    assert bond["bm"]["kind"] == "level_pct"
    assert bond["bm"]["return_pct"] is not None
    # 270 → 272.5 = +0.9259% (rounded 4)
    assert abs(bond["bm"]["return_pct"] - 0.9259) < 0.01
    assert bond["movement_direction"] == "up"
    # diff_bp 키는 더 이상 없음 (level_pct 모드)
    assert "diff_bp" not in bond["bm"] or bond["bm"].get("diff_bp") is None
    # 매핑 source 정확성
    assert "KAP_BOND_TR" in bond["bm"]["source"]


# ──────────────────────────────────────────────────────────────────
# 3. HY_TR 가 indicators.csv 에 있을 때 크레딧 anchor return_pct 산출
# ──────────────────────────────────────────────────────────────────

def test_credit_uses_hy_tr_level_pct(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    ind = _make_indicators_csv(tmp_path,
                               hy_start=2900.0, hy_end=2949.0)  # +1.690%
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=ind,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    credit = by_ac["크레딧"]
    assert credit["bm"]["kind"] == "level_pct"
    assert credit["bm"]["return_pct"] is not None
    # 2900 → 2949 = +1.6897% (rounded 4)
    assert abs(credit["bm"]["return_pct"] - 1.6897) < 0.01
    assert credit["movement_direction"] == "up"
    assert "HY_TR" in credit["bm"]["source"]


# ──────────────────────────────────────────────────────────────────
# 4. 음의 return / flat 시나리오
# ──────────────────────────────────────────────────────────────────

def test_domestic_bond_negative_return(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    ind = _make_indicators_csv(tmp_path,
                               kap_start=275.0, kap_end=272.0)  # -1.09%
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=ind,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    bond = by_ac["국내채권"]
    assert bond["bm"]["return_pct"] < 0
    assert bond["movement_direction"] == "down"


def test_credit_flat_when_unchanged(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    ind = _make_indicators_csv(tmp_path,
                               hy_start=2900.0, hy_end=2900.0)  # 0%
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=ind,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    credit = by_ac["크레딧"]
    assert credit["bm"]["return_pct"] is not None
    assert abs(credit["bm"]["return_pct"]) < 0.001
    assert credit["movement_direction"] == "flat"


# ──────────────────────────────────────────────────────────────────
# 5. legacy 호환 — KAP_BOND_TR / HY_TR 컬럼 부재 시 missing fallback
# ──────────────────────────────────────────────────────────────────

def test_missing_new_columns_fallback_gracefully(tmp_path):
    """과거 indicators.csv (KAP_BOND_TR / HY_TR 없음) → bm=None default,
    asset_class 는 출력에 그대로 등장 (importance=0, direction=flat).
    """
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors, ASSET_CLASSES_R8B,
    )
    # legacy 형식 — KAP_BOND_TR / HY_TR 없음
    fp = tmp_path / "indicators.csv"
    fp.write_text(
        "date,DXY,USDKRW,SP500_TR,MSCI_KOREA,GOLD,US_HY_OAS,FED_UPPER,UST_7_10Y_TR\n"
        "2026-04-01,103.0,1450.0,5500.0,90.0,2300.0,320.0,5.50,180.0\n"
        "2026-04-30,104.5,1500.0,5400.0,87.0,2400.0,340.0,5.50,178.5\n",
        encoding="utf-8",
    )
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=fp,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    # 8자산군 모두 출력 schema 보존
    assert sorted(by_ac.keys()) == sorted(ASSET_CLASSES_R8B)
    # 국내채권 / 크레딧 — 컬럼 부재로 bm 기본값
    assert by_ac["국내채권"]["bm"].get("return_pct") is None
    assert by_ac["국내채권"]["movement_direction"] == "flat"
    assert by_ac["크레딧"]["bm"].get("return_pct") is None
    assert by_ac["크레딧"]["movement_direction"] == "flat"
    # 다른 자산군은 정상 산출
    assert by_ac["해외주식"]["bm"]["return_pct"] is not None
    assert by_ac["환율(FX)"]["bm"]["return_pct"] is not None
    # warnings 에 missing 기록
    warns = " ".join(out.get("warnings", []) or [])
    assert "KAP_BOND_TR" in warns
    assert "HY_TR" in warns


# ──────────────────────────────────────────────────────────────────
# 6. macro_data 컬렉터 — SCIP_INDICATORS / BMJISU_INDICATORS 등록 확인
# ──────────────────────────────────────────────────────────────────

def test_scip_indicators_includes_hy_ig_tr():
    """SCIP_INDICATORS 에 HY_TR (id=401, ds=9), IG_TR (id=139, ds=6, USD blob) 등록."""
    from market_research.collect.macro_data import SCIP_INDICATORS

    assert "HY_TR" in SCIP_INDICATORS
    hy = SCIP_INDICATORS["HY_TR"]
    assert hy["dataset_id"] == 401
    assert hy["dataseries_id"] == 9
    assert "HY" in hy["desc"]

    assert "IG_TR" in SCIP_INDICATORS
    ig = SCIP_INDICATORS["IG_TR"]
    assert ig["dataset_id"] == 139
    assert ig["dataseries_id"] == 6
    assert ig.get("blob_key") == "USD"


def test_bmjisu_indicators_kap_bond_tr_registered():
    """BMJISU_INDICATORS 에 KAP_BOND_TR (KM000000) 등록."""
    from market_research.collect.macro_data import BMJISU_INDICATORS

    assert "KAP_BOND_TR" in BMJISU_INDICATORS
    cfg = BMJISU_INDICATORS["KAP_BOND_TR"]
    assert cfg["index_cd"] == "KM000000"
    assert "KAP" in cfg["desc"]


def test_save_results_accepts_bmjisu_data(tmp_path, monkeypatch):
    """save_results 가 bmjisu_data keyword arg 를 받아 wide CSV 에 컬럼 추가."""
    from market_research.collect import macro_data

    monkeypatch.setattr(macro_data, "DATA_DIR", tmp_path)
    monkeypatch.setattr(macro_data, "OUTPUT_FILE", tmp_path / "indicators.json")
    monkeypatch.setattr(macro_data, "OUTPUT_CSV", tmp_path / "indicators.csv")

    scip = {"SP500_TR": {"2026-04-01": 5500.0, "2026-04-30": 5400.0},
            "HY_TR": {"2026-04-01": 2900.0, "2026-04-30": 2949.0}}
    fred = {}
    nyfed = {}
    ecos = {}
    bmjisu = {"KAP_BOND_TR": {"2026-04-01": 270.0, "2026-04-30": 272.5}}

    df = macro_data.save_results(scip, fred, nyfed, ecos, bmjisu_data=bmjisu)

    # CSV 검증
    csv_fp = tmp_path / "indicators.csv"
    assert csv_fp.exists()
    with csv_fp.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert "KAP_BOND_TR" in reader.fieldnames
    assert "HY_TR" in reader.fieldnames
    # 4/30 row
    end_row = next(r for r in rows if r["date"] == "2026-04-30")
    assert float(end_row["KAP_BOND_TR"]) == 272.5
    assert float(end_row["HY_TR"]) == 2949.0
