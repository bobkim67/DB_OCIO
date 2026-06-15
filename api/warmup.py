"""앱 시작 시 9개 펀드의 디폴트 데이터를 백그라운드로 미리 산출(워밍업)하고
진행률 상태를 노출한다.

설계 메모:
- 워밍업은 transactions/holdings/brinson 서비스 빌더를 UI 디폴트와 동일한
  파라미터로 호출 → 동일한 캐시(`modules.data_loader._ttl_cache`,
  `brinson_service._compute_cached`)를 채운다.
- step 단위로 실패해도 계속 진행한다. 최종 상태는 error_count 에 따라
  `done` / `done_with_errors` 로 구분한다. (요구사항 #2)
- 데몬 스레드 1개에서 순차 실행한다. `asyncio.to_thread` 의 취소는 실행 중인
  스레드를 즉시 멈추지 못하므로, 시작은 `_run_lock` + `_started` 플래그로
  멱등(중복 실행 금지) 보장한다. (요구사항 #3)
"""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))


@dataclass
class _WarmupState:
    status: str = "idle"  # idle | running | done | done_with_errors | error
    total: int = 0
    done: int = 0
    error_count: int = 0
    current: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    errors: list[dict] = field(default_factory=list)


_state = _WarmupState()
_state_lock = threading.Lock()

# 시작 멱등성 가드 — 중복 워밍업 스레드 방지 (요구사항 #3)
_run_lock = threading.Lock()
_started = False


# -------------------- 상태 조회 --------------------

def get_state() -> dict:
    with _state_lock:
        return asdict(_state)


def _now_iso() -> str:
    return datetime.now(_KST).isoformat(timespec="seconds")


# -------------------- step 정의 --------------------

def _ymd(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _warm_holdings(fund: str):
    from api.services.holdings_service import build_holdings
    # UI 디폴트: lookthrough=True
    return build_holdings(fund, lookthrough=True)


def _warm_brinson(fund: str):
    from api.services.brinson_service import build_brinson
    # 기본 기간(YTD: 전년 12/31~어제) + 펀드별 mapping_method
    return build_brinson(fund)


def _warm_transactions(fund: str, start: date, end: date):
    from api.services.transactions_service import build_transactions
    return build_transactions(fund, _ymd(start), _ymd(end))


def _warm_weight(fund: str, start: date, level: str):
    from api.services.transactions_service import build_weight_history
    return build_weight_history(fund, _ymd(start), level)


def _warm_fx(fund: str, start: date):
    from api.services.transactions_service import build_fx_position
    return build_fx_position(fund, _ymd(start))


def _warm_securities(fund: str):
    from api.services.transactions_service import build_securities
    return build_securities(fund)


def _build_steps() -> list[tuple[str, object]]:
    """(label, callable) 리스트 — UI 디폴트 파라미터와 동일."""
    from config.funds import FUND_LIST

    today = datetime.now(_KST).date()
    som = today.replace(day=1)            # MTD 시작 (당월 1일)
    soy = date(today.year, 1, 1)          # YTD 시작 (연초)

    steps: list[tuple[str, object]] = []
    for fund in FUND_LIST:
        steps.append((f"{fund} · 편입종목", lambda f=fund: _warm_holdings(f)))
        steps.append((f"{fund} · 성과분석", lambda f=fund: _warm_brinson(f)))
        steps.append((f"{fund} · 거래내역",
                      lambda f=fund: _warm_transactions(f, som, today)))
        steps.append((f"{fund} · 비중추이(자산)",
                      lambda f=fund: _warm_weight(f, soy, "asset")))
        steps.append((f"{fund} · 비중추이(종목)",
                      lambda f=fund: _warm_weight(f, soy, "security")))
        steps.append((f"{fund} · FX포지션", lambda f=fund: _warm_fx(f, soy)))
        steps.append((f"{fund} · 보유종목목록", lambda f=fund: _warm_securities(f)))
    return steps


def _record_error(label: str, msg: str) -> None:
    with _state_lock:
        _state.error_count += 1
        _state.errors.append({"step": label, "error": msg})


def _run() -> None:
    try:
        steps = _build_steps()
        with _state_lock:
            _state.status = "running"
            _state.total = len(steps)
            _state.done = 0
            _state.error_count = 0
            _state.errors = []
            _state.current = ""
            _state.started_at = _now_iso()
            _state.finished_at = None

        for label, fn in steps:
            with _state_lock:
                _state.current = label
            try:
                res = fn()
                # 서비스 빌더는 DB 실패 시 예외 대신 fallback DTO + warning을 반환한다.
                # "DB 접속 실패" warning 을 step 실패로 집계한다.
                warns = getattr(getattr(res, "meta", None), "warnings", None) or []
                if any("DB 접속 실패" in str(w) for w in warns):
                    _record_error(label, "DB 접속 실패")
            except Exception as exc:  # noqa: BLE001 — step 단위 격리
                _record_error(label, f"{type(exc).__name__}: {exc}")
            finally:
                with _state_lock:
                    _state.done += 1

        with _state_lock:
            _state.current = ""
            _state.finished_at = _now_iso()
            _state.status = "done" if _state.error_count == 0 else "done_with_errors"
    except Exception as exc:  # noqa: BLE001 — 전체 실패 (예: import 오류)
        with _state_lock:
            _state.status = "error"
            _state.current = ""
            _state.finished_at = _now_iso()
            _state.errors.append({"step": "<runner>", "error": f"{type(exc).__name__}: {exc}"})


def start_warmup_background() -> bool:
    """워밍업 데몬 스레드를 1회만 시작한다 (멱등). 이미 시작됐으면 False."""
    global _started
    with _run_lock:
        if _started:
            return False
        _started = True
    t = threading.Thread(target=_run, name="ocio-warmup", daemon=True)
    t.start()
    return True
