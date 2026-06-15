"""워밍업 상태 endpoint + 시작 멱등성/스텝 구성 (DB 미접속, 순수 로직)."""
import api.warmup as warmup


def test_warmup_status_endpoint_shape(client):
    r = client.get("/api/warmup-status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in (
        "idle", "running", "done", "done_with_errors", "error",
    )
    for key in (
        "phase", "total", "done", "essential_total", "essential_done",
        "essential_complete", "error_count", "current", "errors",
    ):
        assert key in body
    assert isinstance(body["errors"], list)
    assert isinstance(body["essential_complete"], bool)


def test_warmup_idle_before_start(client):
    # conftest 가 OCIO_WARMUP_ON_STARTUP=false 로 두므로, TestClient 만으로는
    # startup 워밍업이 절대 돌지 않아야 한다 (요구사항 #4).
    body = client.get("/api/warmup-status").json()
    assert body["status"] == "idle"
    assert body["done"] == 0
    assert body["error_count"] == 0
    assert body["essential_complete"] is False


def test_build_steps_split_essential_and_brinson():
    from config.funds import FUND_LIST

    essential = warmup._build_essential_steps()
    brinson = warmup._build_brinson_steps()
    # essential = 펀드당 6스텝(편입종목/거래내역/비중추이x2/FX/보유종목목록)
    assert len(essential) == len(FUND_LIST) * 6
    # brinson = 펀드당 1스텝(성과분석)
    assert len(brinson) == len(FUND_LIST)
    # 전체 = essential + brinson
    assert len(warmup._build_steps()) == len(FUND_LIST) * 7

    ess_labels = " ".join(label for label, _ in essential)
    assert "편입종목" in ess_labels    # holdings
    assert "거래내역" in ess_labels    # transactions
    assert "성과분석" not in ess_labels  # brinson 은 게이트에서 제외
    assert all("성과분석" in label for label, _ in brinson)


def test_call_with_timeout_returns_value():
    assert warmup._call_with_timeout(lambda: 42, timeout=5) == 42


def test_call_with_timeout_raises_on_slow_step():
    import time

    import pytest

    with pytest.raises(TimeoutError):
        warmup._call_with_timeout(lambda: time.sleep(2), timeout=1)


def test_run_step_isolates_timeout(monkeypatch):
    # 느린 step 이 error 로 집계되고 예외가 새지 않아야 한다 (블로킹 방지).
    import time

    monkeypatch.setattr(warmup, "_state", warmup._WarmupState(), raising=True)
    warmup._run_step("느린스텝", lambda: time.sleep(2), timeout=1)
    st = warmup.get_state()
    assert st["error_count"] == 1
    assert st["errors"][0]["step"] == "느린스텝"


def test_start_warmup_is_idempotent(monkeypatch):
    # _run 을 no-op 으로 대체해 DB 접속 없이 멱등성만 검증 (요구사항 #3).
    monkeypatch.setattr(warmup, "_started", False, raising=False)
    calls = {"n": 0}

    def _fake_run():
        calls["n"] += 1

    monkeypatch.setattr(warmup, "_run", _fake_run)

    first = warmup.start_warmup_background()
    second = warmup.start_warmup_background()
    assert first is True
    assert second is False  # 두 번째 호출은 멱등 가드로 무시
