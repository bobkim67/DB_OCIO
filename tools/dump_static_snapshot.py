# -*- coding: utf-8 -*-
"""정적 스냅샷 덤프 — GitHub Pages 배포용 (2026-07-07).

FastAPI TestClient 로 대시보드 기본 뷰 API 응답을 web/public/snapshot/*.json 으로
저장한다. 프론트는 VITE_SNAPSHOT=1 빌드 시 axios 어댑터가 이 파일들을 조회
(web/src/api/client.ts 의 snapshotKey 와 키 규칙 동일해야 함).

키 규칙: path(선행 / 제거, 비영숫자→'_') + 화이트리스트 파라미터를
          `__{k}-{v}` (k 정렬, v 비영숫자→'_') 로 이어붙임.
날짜류 파라미터(start/end 등)는 키에서 제외 — 스냅샷은 기본 기간 조합만 유효.

실행: python -m tools.dump_static_snapshot
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("OCIO_WARMUP_ON_STARTUP", "false")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dateutil.relativedelta import relativedelta
from fastapi.testclient import TestClient

from api.main import app
from config.funds import FUND_LIST

OUT_DIR = Path(__file__).resolve().parents[1] / "web" / "public" / "snapshot"
PARAM_WHITELIST = ("asset_class", "item_cd", "level", "lookthrough", "period")

_SAN = re.compile(r"[^A-Za-z0-9]+")


def _san(s: str) -> str:
    return _SAN.sub("_", str(s)).strip("_")


def _san_value(s: str) -> str:
    """파라미터 값 정규화 — 한글 등 비ASCII 는 percent-encoding 16진수로 보존.
    (client.ts sanitizeValue 와 동일 규칙이어야 함)"""
    from urllib.parse import quote
    return _SAN.sub("_", quote(str(s), safe="").replace("%", "")).strip("_")


def snapshot_key(path: str, params: dict | None) -> str:
    key = _san(path.lstrip("/"))
    for k in sorted((params or {}).keys()):
        if k in PARAM_WHITELIST:
            key += f"__{k}-{_san_value(params[k])}"
    return key


def main() -> None:
    client = TestClient(app)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    start_1m = (date.today() - relativedelta(months=1)).isoformat()

    saved, failed = 0, []

    def dump(path: str, params: dict | None = None) -> dict | list | None:
        nonlocal saved
        try:
            r = client.get(f"/api{path}", params=params)
            if r.status_code != 200:
                failed.append(f"{path} {params} -> {r.status_code}")
                return None
            data = r.json()
            fp = OUT_DIR / f"{snapshot_key(path, params)}.json"
            fp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            saved += 1
            return data
        except Exception as exc:  # noqa: BLE001 — 스냅샷은 되는 것만 담는다
            failed.append(f"{path} {params} -> {type(exc).__name__}")
            return None

    dump("/funds")
    dump("/warmup-status")  # idle — WarmupGate 오버레이/폴링 즉시 종료용

    # 운용보고(매크로): 승인 기간 전부
    mp = dump("/market-report/approved-periods")
    for period in (mp or {}).get("periods", []):
        dump("/market-report", {"period": period})

    for fund in FUND_LIST:
        print(f"[{fund}] ...", flush=True)
        dump(f"/funds/{fund}/overview")
        dump(f"/funds/{fund}/period-returns")
        for lt in ("true", "false"):
            dump(f"/funds/{fund}/holdings", {"lookthrough": lt})
        dump(f"/funds/{fund}/brinson")  # 기본 기간(YTD)·기본 분류 — 콜드면 펀드당 1~2분
        dump(f"/funds/{fund}/transactions", {"start": start_1m, "end": today})
        for level in ("asset", "security"):
            dump(f"/funds/{fund}/weight-history",
                 {"start": start_1m, "end": today, "level": level})
        dump(f"/funds/{fund}/fx-position", {"start": start_1m, "end": today})
        secs = dump(f"/funds/{fund}/securities", {"start": start_1m})
        for it in (secs or {}).get("items", []):
            if not it.get("has_price"):
                continue
            dump(f"/funds/{fund}/security-returns", {
                "item_cd": it["item_cd"], "item_nm": it["item_nm"],
                "start": start_1m, "end": today,
            })
        for ac in ("국내주식", "해외주식", "국내채권", "해외채권", "금·대체", "전체"):
            dump(f"/funds/{fund}/asset-class-return",
                 {"asset_class": ac, "start": start_1m, "end": today})
        # 운용보고(펀드)
        fp = dump(f"/funds/{fund}/report/approved-periods")
        for period in (fp or {}).get("periods", []):
            dump(f"/funds/{fund}/report", {"period": period})

    print(f"\n저장 {saved}건 -> {OUT_DIR}")
    if failed:
        print(f"실패/스킵 {len(failed)}건:")
        for f in failed[:30]:
            print("  ", f)


if __name__ == "__main__":
    main()
