"""Admin 리서치 wiki 뷰어 (2026-08-06) — 조회 전용.

09 는 자산군당 salience 상위 N 만 싣는다. 무엇이 잘렸는지 보이게 하는 것이
이 엔드포인트의 목적이므로, **컷된 claim 도 반드시 응답에 포함**되어야 한다.

tmp_path 격리 — 실 데이터 의존 없음.
"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_mr(tmp_path: Path, monkeypatch) -> Path:
    """admin_funds 가 경로를 `__file__` 기준으로 잡으므로 모듈 __file__ 을 옮긴다."""
    import api.routers.admin_funds as af
    fake_root = tmp_path / "repo"
    (fake_root / "api" / "routers").mkdir(parents=True)
    monkeypatch.setattr(af, "__file__",
                        str(fake_root / "api" / "routers" / "admin_funds.py"))
    base = fake_root / "market_research" / "data"
    (base / "claims").mkdir(parents=True)
    (base / "wiki" / "09_Research_Synthesis").mkdir(parents=True)
    (base / "naver_research" / "adapted").mkdir(parents=True)
    (base / "broker_mail").mkdir(parents=True)
    return base


def _seed(base: Path, *, page: str = "") -> None:
    (base / "claims" / "2026-07.research.json").write_text(json.dumps({
        "claims": [
            {"claim_id": "claim:2026-07:aaaaaaaaaa", "claim_text": "채택된 클레임",
             "primary_asset": "환율(FX)", "salience": 0.95, "confidence": 0.9,
             "stance": "bearish", "horizon": "short", "source_type": "broker",
             "source_evidence_ids": ["ev_naver"]},
            {"claim_id": "claim:2026-07:bbbbbbbbbb", "claim_text": "엔캐리 트레이드 재개 가능성",
             "primary_asset": "환율(FX)", "salience": 0.72, "confidence": 0.75,
             "stance": "bearish", "horizon": "medium", "source_type": "broker",
             "source_evidence_ids": ["ev_broker"]},
            {"claim_id": "claim:2026-07:cccccccccc", "claim_text": "국내주식 클레임",
             "primary_asset": "국내주식", "salience": 0.8, "confidence": 0.8,
             "stance": "bullish", "horizon": "short", "source_type": "broker",
             "source_evidence_ids": []},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    (base / "wiki" / "09_Research_Synthesis" / "2026-07_환율FX.md").write_text(
        page or "# 2026-07 환율(FX)\n- [claim:aaaaaaaaaa] 채택된 클레임\n",
        encoding="utf-8")
    (base / "naver_research" / "adapted" / "2026-07.json").write_text(json.dumps({
        "articles": [{"_article_id": "ev_naver", "title": "슈퍼 엔저에 동승한 원 약세",
                      "date": "2026-07-01", "_raw_broker": "iM증권",
                      "url": "https://finance.naver.com/research/x?nid=1"}],
    }, ensure_ascii=False), encoding="utf-8")
    (base / "broker_mail" / "2026-07.json").write_text(json.dumps({
        "articles": [{"_article_id": "ev_broker", "title": "키움 데일리",
                      "date": "2026-07-29", "_raw_broker": "키움증권",
                      "url": "", "_raw_attach_names": ["daily.pdf"]}],
    }, ensure_ascii=False), encoding="utf-8")


def test_returns_all_claims_including_cut(client, tmp_mr):
    """★ 핵심 — 09 에 안 실린 claim 도 응답에 있어야 진단이 된다."""
    _seed(tmp_mr)
    d = client.get("/api/admin/research-wiki",
                   params={"period": "2026-07", "asset": "환율(FX)"}).json()
    assert d["claims_total"] == 2
    assert d["adopted_total"] == 1
    texts = {c["text"]: c["adopted"] for c in d["claims"]}
    assert texts["채택된 클레임"] is True
    assert texts["엔캐리 트레이드 재개 가능성"] is False      # 컷됐지만 응답에 존재


def test_rank_follows_salience(client, tmp_mr):
    _seed(tmp_mr)
    d = client.get("/api/admin/research-wiki",
                   params={"period": "2026-07", "asset": "환율(FX)"}).json()
    assert [c["rank"] for c in d["claims"]] == [1, 2]
    assert d["claims"][0]["salience"] > d["claims"][1]["salience"]


def test_naver_source_has_url_broker_mail_has_attachments(client, tmp_mr):
    """naver 는 링크로, broker_mail 은 URL 없이 첨부명으로만 추적한다."""
    _seed(tmp_mr)
    d = client.get("/api/admin/research-wiki",
                   params={"period": "2026-07", "asset": "환율(FX)"}).json()
    by = {c["text"]: c["sources"] for c in d["claims"]}
    nav = by["채택된 클레임"][0]
    assert nav["lane"] == "naver_research" and nav["url"].startswith("https://")
    brk = by["엔캐리 트레이드 재개 가능성"][0]
    assert brk["lane"] == "broker_mail" and brk["url"] == ""
    assert "daily.pdf" in brk["attachments"]


def test_evidence_id_falls_back_to_dedupe_key_and_nid(client, tmp_mr):
    """★ 회귀 — 추출기와 같은 폴백(_raw_dedupe_key → _raw_nid)으로 인덱싱해야 한다.

    `research_claim_extractor._load_lane_evidence` 는 `_article_id` 가 없으면
    `_raw_dedupe_key`/`_raw_nid` 로 evidence id 를 만든다(메모리 한정, 파일 미저장).
    `_article_id` 만 인덱싱하면 그 claim 들의 원본이 통째로 안 붙는다 —
    2026-07 실측으로 222건이 "원본 연결 없음" 이었다.
    """
    base = tmp_mr
    (base / "claims" / "2026-07.research.json").write_text(json.dumps({
        "claims": [
            {"claim_id": "claim:2026-07:dddddddddd", "claim_text": "dedupe_key 로 연결",
             "primary_asset": "환율(FX)", "salience": 0.9, "stance": "bullish",
             "source_evidence_ids": ["dk-123"]},
            {"claim_id": "claim:2026-07:eeeeeeeeee", "claim_text": "nid 로 연결",
             "primary_asset": "환율(FX)", "salience": 0.8, "stance": "bullish",
             "source_evidence_ids": [36576]},          # 정수 nid
        ],
    }, ensure_ascii=False), encoding="utf-8")
    (base / "naver_research" / "adapted" / "2026-07.json").write_text(json.dumps({
        "articles": [
            {"_raw_dedupe_key": "dk-123", "title": "슈퍼 엔저", "date": "2026-07-01",
             "_raw_broker": "iM증권", "url": "https://x/1"},
            {"_raw_nid": 36576, "title": "Daily Morning Brief", "date": "2026-07-31",
             "_raw_broker": "다올투자증권", "url": "https://x/2"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    (base / "wiki" / "09_Research_Synthesis" / "2026-07_환율FX.md").write_text(
        "# x", encoding="utf-8")

    d = client.get("/api/admin/research-wiki",
                   params={"period": "2026-07", "asset": "환율(FX)"}).json()
    by = {c["text"]: c["sources"] for c in d["claims"]}
    assert by["dedupe_key 로 연결"][0]["title"] == "슈퍼 엔저"
    assert by["nid 로 연결"][0]["broker"] == "다올투자증권"   # 정수 id 도 매칭


def test_asset_list_and_default(client, tmp_mr):
    _seed(tmp_mr)
    d = client.get("/api/admin/research-wiki", params={"period": "2026-07"}).json()
    assert set(d["assets"]) == {"환율(FX)", "국내주식"}
    assert d["asset"] == "환율(FX)"      # claim 수 최다 자산군이 기본


def test_unknown_asset_falls_back(client, tmp_mr):
    _seed(tmp_mr)
    d = client.get("/api/admin/research-wiki",
                   params={"period": "2026-07", "asset": "없는자산"}).json()
    assert d["asset"] == "환율(FX)"


def test_stale_flag(client, tmp_mr):
    """claims 가 09 보다 최신이면 stale 배지."""
    import os
    import time
    _seed(tmp_mr)
    page = tmp_mr / "wiki" / "09_Research_Synthesis" / "2026-07_환율FX.md"
    old = time.time() - 86400
    os.utime(page, (old, old))
    d = client.get("/api/admin/research-wiki",
                   params={"period": "2026-07", "asset": "환율(FX)"}).json()
    assert d["page_stale"] is True


def test_missing_period_returns_empty(client, tmp_mr):
    d = client.get("/api/admin/research-wiki", params={"period": "2099-01"}).json()
    assert d["claims_total"] == 0 and d["assets"] == []


def test_bad_period_422(client, tmp_mr):
    r = client.get("/api/admin/research-wiki", params={"period": "2026-Q1"})
    assert r.status_code == 422
