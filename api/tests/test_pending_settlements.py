"""결제 예정 안내 (2026-08-03) — 메일 확인서 미반영분 + 원장 미결제분.

배경: 해외 ETF 는 체결 다음 영업일(브로커 SettleDate)에야 원장(DWPM10520)에
잡혀서, 그 사이 대시보드가 매매를 전혀 모른다. 확인서 메일을 배치 파싱해
"결제 예정"으로 안내만 한다 (비중은 원장 그대로 — SSOT 불변).
"""
from datetime import date

from api.services import holdings_service as hs


_MAIL = [
    # 기준일(8/2) 이후 결제 → 원장 미반영 → 표시
    {"fund_cd": "2JM23", "ticker": "IAUM US", "isin": "US46436F1030",
     "security_name": "ISHARES GOLD TRUST", "side": "S", "ccy": "USD",
     "order_date": "2026-07-31", "settle_date": "2026-08-03",
     "qty": 19000.0, "net_amount": 765198.83, "broker": "한국투자증권"},
    # 기준일 이전 결제 → 원장에 이미 있음 → 숨김
    {"fund_cd": "2JM23", "ticker": "IAUM US", "isin": "US46436F1030",
     "security_name": "ISHARES GOLD TRUST", "side": "S", "ccy": "USD",
     "order_date": "2026-07-20", "settle_date": "2026-07-21",
     "qty": 13000.0, "net_amount": 518947.09, "broker": "한국투자증권"},
    # 다른 펀드 → 숨김
    {"fund_cd": "08K88", "ticker": "VEA US", "isin": "US9219438580",
     "security_name": "VANGUARD FTSE", "side": "B", "ccy": "USD",
     "order_date": "2026-07-31", "settle_date": "2026-08-03",
     "qty": 100.0, "net_amount": 7000.0, "broker": "DB증권"},
]


def _patch(monkeypatch, mail=None, ledger=None, rate=1441.1):
    monkeypatch.setattr(hs, "_load_pending_mail_trades", lambda: mail or [])
    monkeypatch.setattr(hs, "_load_ledger_unsettled", lambda f, a: ledger or [])
    monkeypatch.setattr(hs, "_usdkrw_on", lambda a: rate)


def test_mail_trade_after_asof_shown(monkeypatch):
    _patch(monkeypatch, mail=_MAIL)
    out = hs._build_pending_settlements("2JM23", date(2026, 8, 2))
    assert len(out) == 1
    p = out[0]
    assert p.source == "mail"
    assert p.side == "매도"
    assert p.qty == 19000.0
    assert p.ccy == "USD"
    assert p.amount == 765198.83
    assert p.settle_date == date(2026, 8, 3)
    # 원화 환산은 참고값 (매매기준율)
    assert p.amount_krw is not None
    assert abs(p.amount_krw - 765198.83 * 1441.1) < 1


def test_mail_trade_already_settled_hidden(monkeypatch):
    """결제일이 기준일 이하면 원장에 이미 반영 — 중복 안내 금지."""
    _patch(monkeypatch, mail=_MAIL)
    out = hs._build_pending_settlements("2JM23", date(2026, 8, 5))
    assert out == []


def test_ledger_unsettled_marked_reflected(monkeypatch):
    """원장 미결제분은 미지급금으로 이미 비중에 반영 — source='ledger'."""
    ledger = [{
        "item_nm": "ACE 200", "buy_sell_ds_cd": "M", "trd_qty": 10000.0,
        "curr_ds_cd": "KRW", "stl_amt": 1043524120.0, "krw_stl_amt": 0.0,
        "std_dt": "20260731", "stl_dt": "20260804",
    }]
    _patch(monkeypatch, ledger=ledger)
    out = hs._build_pending_settlements("2JM23", date(2026, 8, 2))
    assert len(out) == 1
    p = out[0]
    assert p.source == "ledger"
    assert p.side == "매수"
    # KRW 거래는 krw_stl_amt 가 0이어도 stl_amt 가 이미 원화
    assert p.amount_krw == 1043524120.0
    assert p.settle_date == date(2026, 8, 4)


def test_sorted_by_settle_date(monkeypatch):
    ledger = [{
        "item_nm": "ACE 200", "buy_sell_ds_cd": "M", "trd_qty": 1.0,
        "curr_ds_cd": "KRW", "stl_amt": 100.0, "krw_stl_amt": 100.0,
        "std_dt": "20260731", "stl_dt": "20260804",
    }]
    _patch(monkeypatch, mail=_MAIL, ledger=ledger)
    out = hs._build_pending_settlements("2JM23", date(2026, 8, 2))
    assert [p.settle_date for p in out] == [date(2026, 8, 3), date(2026, 8, 4)]


def test_no_asof_returns_empty(monkeypatch):
    _patch(monkeypatch, mail=_MAIL)
    assert hs._build_pending_settlements("2JM23", None) == []


def test_missing_cache_file_is_silent(monkeypatch):
    """배치 미실행(.cache 파일 없음) → 배너 없음, 예외 없음 (기능 무중단)."""
    monkeypatch.setattr(hs, "_PENDING_JSON", r"C:\__nonexistent__\pending.json")
    assert hs._load_pending_mail_trades() == []


def test_holdings_endpoint_exposes_field(client):
    """엔드포인트 계약 — pending_settlements 키가 항상 존재."""
    r = client.get("/api/funds/2JM23/holdings")
    assert r.status_code == 200
    body = r.json()
    assert "pending_settlements" in body
    assert isinstance(body["pending_settlements"], list)
    for p in body["pending_settlements"]:
        assert p["source"] in ("mail", "ledger")
        assert p["side"] in ("매수", "매도")
