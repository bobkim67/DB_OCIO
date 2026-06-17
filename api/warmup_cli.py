"""런처용 워밍업 CLI — cmd 창에 진행바를 그리며 디스크 캐시를 선계산한다.

`launch_dashboard.bat` 가 daily-update 질문 직후 호출(블로킹). 전 펀드의 디폴트
파라미터로 거래내역(holdings/transactions/weight/fx/securities)과 성과분석(Brinson)을
미리 계산해 영속 캐시(modules.db_cache SQLite + brinson .cache/brinson pkl)를 채운다.
이후 uvicorn 서버는 이 디스크 캐시를 읽어 즉시 응답한다(서버 자체 startup 워밍업은
런처가 OCIO_WARMUP_ON_STARTUP=false 로 꺼서 중복 방지).

- 외부 의존 없음(tqdm 미사용) — 수동 진행바를 stdout 에 \r 로 갱신.
- step 단위 예외 격리(한 펀드 실패해도 계속). 종료코드: 에러 0=0, 그 외=1.
- 프로젝트 루트에서 `python -m api.warmup_cli` 로 실행(모듈 import 경로).
"""
from __future__ import annotations

import sys
import time
from datetime import date


def _bar(done: int, total: int, label: str, t0: float) -> None:
    pct = done / total if total else 1.0
    w = 28
    fill = int(w * pct)
    el = time.monotonic() - t0
    sys.stdout.write(
        f"\r  [{'#' * fill}{'.' * (w - fill)}] {done:>3}/{total} "
        f"{pct * 100:3.0f}%  {el:5.0f}s  {label[:44]:<44}"
    )
    sys.stdout.flush()


# -------------------- step 실행기 (서비스 빌더 = 캐시 채움) --------------------

def _holdings(f: str):
    from api.services.holdings_service import build_holdings
    return build_holdings(f, lookthrough=True)


def _txn(f: str, s: str, e: str):
    from api.services.transactions_service import build_transactions
    return build_transactions(f, s, e)


def _weight(f: str, s: str, level: str):
    from api.services.transactions_service import build_weight_history
    return build_weight_history(f, s, level)


def _fx(f: str, s: str):
    from api.services.transactions_service import build_fx_position
    return build_fx_position(f, s)


def _securities(f: str):
    from api.services.transactions_service import build_securities
    return build_securities(f)


def _brinson(f: str):
    # 디폴트 파라미터(전년말~어제, 펀드 기본 분류방법) → brinson 디스크 캐시 기록
    from api.services.brinson_service import build_brinson
    return build_brinson(f)


def main() -> int:
    from config.funds import FUND_LIST

    today = date.today()
    som = date(today.year, today.month, 1).strftime("%Y-%m-%d")   # 거래내역 MTD
    soy = date(today.year, 1, 1).strftime("%Y-%m-%d")             # 비중/FX YTD

    steps: list[tuple[str, object]] = []
    for fund in FUND_LIST:
        steps.append((f"{fund} 편입종목", lambda f=fund: _holdings(f)))
        steps.append((f"{fund} 거래내역", lambda f=fund: _txn(f, som, today.strftime("%Y-%m-%d"))))
        steps.append((f"{fund} 비중추이(자산)", lambda f=fund: _weight(f, soy, "asset")))
        steps.append((f"{fund} 비중추이(종목)", lambda f=fund: _weight(f, soy, "security")))
        steps.append((f"{fund} FX포지션", lambda f=fund: _fx(f, soy)))
        steps.append((f"{fund} 보유목록", lambda f=fund: _securities(f)))
        steps.append((f"{fund} 성과분석(Brinson)", lambda f=fund: _brinson(f)))

    total = len(steps)
    errors = 0
    t0 = time.monotonic()
    print(f"[warmup] {len(FUND_LIST)}개 펀드 x 7스텝 = {total}. "
          f"거래내역 + Brinson 디폴트 선계산 (Brinson 콜드는 펀드당 ~1분)...")
    for i, (label, fn) in enumerate(steps):
        _bar(i, total, label, t0)
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — step 격리
            errors += 1
            sys.stdout.write(f"\n  ! {label}: {type(exc).__name__}: {exc}\n")
    _bar(total, total, "완료", t0)
    print()
    print(f"[warmup] 완료 — {time.monotonic() - t0:.0f}s, 에러 {errors}건")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
