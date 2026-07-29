# -*- coding: utf-8 -*-
"""Brinson 골든 스냅샷 재생성 — **의도적 골든 변경 시에만** 실행.

test_brinson_snapshot.py 가 읽는 snapshots/brinson_{fund}_{method}_{sd}_{ed}.json 을
현재 코드 산출로 덮어쓴다. 실행 전 반드시:
  1) 왜 골든이 바뀌는지 근거를 남긴다 (커밋 메시지 / devlog)
  2) `.cache/brinson/*{sd}_{ed}*` 를 지워 재계산을 강제한다

이력:
  2026-07-29 해외지수 T-1 참조를 '한국 영업일 shift' → '캘린더 전일'(전산 규약)로 변경.
             AP 측은 불변, BM 측만 이동 (08K88 total_alloc 1.2433→1.2546,
             4JM12 period_bm_return -0.56829→-0.57267). 사용자 확정.

실행: python -m api.tests.regen_brinson_snapshots
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from api.tests.test_brinson_snapshot import CASES, SNAP_DIR

TOTAL_KEYS = (
    "period_ap_return", "period_bm_return", "total_alloc", "total_select",
    "total_cross", "total_excess", "total_excess_relative", "fx_contrib",
    "residual",
)
ROW_KEYS = (
    "asset_class", "ap_weight", "bm_weight", "ap_return", "bm_return",
    "alloc_effect", "select_effect", "cross_effect", "contrib_return",
)
SEC_KEYS = ("asset_class", "item_nm", "weight_pct", "return_pct", "contrib_pct")


def main() -> None:
    client = TestClient(app)
    for fund, method, sd, ed in CASES:
        r = client.get(
            f"/api/funds/{fund}/brinson",
            params={"start_date": sd, "end_date": ed, "mapping_method": method},
        )
        r.raise_for_status()
        body = r.json()
        if body["meta"]["is_fallback"]:
            raise SystemExit(f"{fund}: fallback 상태 — DB 확인 후 재실행")
        snap = {
            "fund_code": fund,
            "mapping_method": method,
            "start_date": sd,
            "end_date": ed,
            "totals": {k: body[k] for k in TOTAL_KEYS},
            "asset_rows": [
                {k: row[k] for k in ROW_KEYS} for row in body["asset_rows"]
            ],
            "sec_top5": [
                {k: row[k] for k in SEC_KEYS} for row in body["sec_contrib"][:5]
            ],
        }
        fp = Path(SNAP_DIR) / f"brinson_{fund}_{method}_{sd}_{ed}.json"
        old = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else None
        fp.write_text(
            json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[갱신] {fp.name}")
        if old:
            for k in TOTAL_KEYS:
                o, n = old["totals"].get(k), snap["totals"][k]
                if o is not None and abs(float(o) - float(n)) > 1e-9:
                    print(f"    totals.{k}: {o} → {n}")


if __name__ == "__main__":
    main()
