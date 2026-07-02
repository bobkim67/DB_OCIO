# -*- coding: utf-8 -*-
"""R9-B.4.1 — Opus synthesis streaming hotfix tests.

LLM 호출 0. monkeypatch 로 anthropic SDK 차단.

검증:
  1. _call_llm stream=False (default) → 기존 messages.create 경로 그대로
  2. _call_llm stream=True → messages.stream 사용, 청크 누적, 동일 text 반환
  3. _synthesize_debate Opus call site 2 곳에서 stream=True 가 명시되는지
  4. token/cost 로깅 schema 보존 (input_tokens / output_tokens / stream)
  5. legacy 호출 경로 회귀 없음
"""
from __future__ import annotations

from types import SimpleNamespace
from contextlib import contextmanager
from pathlib import Path

import pytest

from market_research.report import debate_engine as de


# ──────────────────────────────────────────────────────────────────
# Stubbed anthropic client
# ──────────────────────────────────────────────────────────────────

class _FakeMessage:
    def __init__(self, text: str, in_tok: int = 10, out_tok: int = 5):
        self.content = [SimpleNamespace(text=text)]
        self.usage = SimpleNamespace(
            input_tokens=in_tok, output_tokens=out_tok,
        )


class _FakeStream:
    """anthropic SDK stream context manager imitation."""
    def __init__(self, chunks: list[str], in_tok: int = 12, out_tok: int = 7):
        self._chunks = chunks
        self._in = in_tok
        self._out = out_tok
        self.text_stream = iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def get_final_message(self):
        return SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=self._in, output_tokens=self._out,
            )
        )


class _FakeMessagesClient:
    def __init__(self, *, text: str = "FAKE OUTPUT.",
                 chunks: list[str] | None = None,
                 create_in_tok: int = 10, create_out_tok: int = 5,
                 stream_in_tok: int = 12, stream_out_tok: int = 7):
        self._text = text
        self._chunks = chunks or ["FAKE ", "STREAM ", "OUTPUT."]
        self._cit = create_in_tok
        self._cot = create_out_tok
        self._sit = stream_in_tok
        self._sot = stream_out_tok
        self.create_called: list[dict] = []
        self.stream_called: list[dict] = []

    def create(self, **kwargs):
        self.create_called.append(kwargs)
        return _FakeMessage(self._text, self._cit, self._cot)

    def stream(self, **kwargs):
        self.stream_called.append(kwargs)
        return _FakeStream(self._chunks, self._sit, self._sot)


class _FakeAnthropic:
    def __init__(self, *, messages: _FakeMessagesClient):
        self.messages = messages


@pytest.fixture
def reset_debug_log():
    de._debug_log.clear()
    yield
    de._debug_log.clear()


def _install_fake_sdk(monkeypatch, fake_client: _FakeAnthropic):
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key=None: fake_client)
    # api key fetch 차단 (실 호출 0 보장)
    monkeypatch.setattr(de, "_get_api_key", lambda: "sk-fake")


# ──────────────────────────────────────────────────────────────────
# 1. default stream=False — 기존 경로 보존
# ──────────────────────────────────────────────────────────────────

def test_call_llm_default_uses_messages_create(monkeypatch, reset_debug_log):
    messages = _FakeMessagesClient(text="LEGACY OUT.")
    _install_fake_sdk(monkeypatch, _FakeAnthropic(messages=messages))

    out = de._call_llm(
        model="claude-opus-4-6", system="sys", prompt="p",
        max_tokens=100, log_label="t1",
    )
    assert out == "LEGACY OUT."
    assert len(messages.create_called) == 1
    assert len(messages.stream_called) == 0
    # 로그 schema 보존
    entry = de._debug_log[-1]
    assert entry["event"] == "llm_call"
    assert entry["model"] == "claude-opus-4-6"
    assert entry["input_tokens"] == 10
    assert entry["output_tokens"] == 5
    assert entry["stream"] is False


def test_call_llm_explicit_false_matches_default(monkeypatch, reset_debug_log):
    messages = _FakeMessagesClient(text="LEGACY.")
    _install_fake_sdk(monkeypatch, _FakeAnthropic(messages=messages))
    out = de._call_llm(
        model="claude-haiku-4-5", system="s", prompt="p",
        max_tokens=50, log_label="t2",
        stream=False,
    )
    assert out == "LEGACY."
    assert len(messages.stream_called) == 0


# ──────────────────────────────────────────────────────────────────
# 2. stream=True — chunks 누적 + final usage
# ──────────────────────────────────────────────────────────────────

def test_call_llm_stream_concatenates_chunks(monkeypatch, reset_debug_log):
    messages = _FakeMessagesClient(
        chunks=["alpha ", "beta ", "gamma."],
        stream_in_tok=42, stream_out_tok=99,
    )
    _install_fake_sdk(monkeypatch, _FakeAnthropic(messages=messages))

    out = de._call_llm(
        model="claude-opus-4-6", system="s", prompt="p",
        max_tokens=2000, log_label="syn_step1",
        stream=True,
    )
    assert out == "alpha beta gamma."  # joined + stripped
    assert len(messages.stream_called) == 1
    assert len(messages.create_called) == 0
    # final_message usage 로깅 보존
    entry = de._debug_log[-1]
    assert entry["stream"] is True
    assert entry["input_tokens"] == 42
    assert entry["output_tokens"] == 99
    assert entry["label"] == "syn_step1"


def test_call_llm_stream_returns_stripped_text(monkeypatch, reset_debug_log):
    """stream 결과의 앞뒤 공백/개행이 strip 되어야 한다 (create 경로와 동일)."""
    messages = _FakeMessagesClient(chunks=["  \n  ", "real text", "  \n"])
    _install_fake_sdk(monkeypatch, _FakeAnthropic(messages=messages))
    out = de._call_llm(
        model="claude-opus-4-6", system="", prompt="",
        max_tokens=10, stream=True,
    )
    assert out == "real text"


def test_call_llm_stream_passes_kwargs_to_sdk(monkeypatch, reset_debug_log):
    messages = _FakeMessagesClient()
    _install_fake_sdk(monkeypatch, _FakeAnthropic(messages=messages))
    de._call_llm(
        model="claude-opus-4-6", system="SYSPROMPT",
        prompt="USERPROMPT",
        max_tokens=4321, stream=True,
    )
    args = messages.stream_called[0]
    assert args["model"] == "claude-opus-4-6"
    assert args["max_tokens"] == 4321
    assert args["system"] == "SYSPROMPT"
    assert args["messages"] == [{"role": "user", "content": "USERPROMPT"}]


# ──────────────────────────────────────────────────────────────────
# 3. _synthesize_debate 가 Opus call 에 stream=True 를 전달
# ──────────────────────────────────────────────────────────────────

def test_synthesize_debate_uses_stream_for_opus(monkeypatch, reset_debug_log):
    """Step 1 (customer_comment) + Step 2 (analysis) 둘 다 stream=True."""
    seen_calls: list[dict] = []

    def _fake_call_llm(model, system, prompt, max_tokens=1500,
                       log_label="", *, stream=False):
        seen_calls.append({
            "model": model, "max_tokens": max_tokens,
            "log_label": log_label, "stream": stream,
        })
        # Step2 는 JSON 형태가 요구되므로 parse 가능한 stub 반환
        if "synthesis_step2" in log_label:
            return ('{"consensus_points":["c1"],"disagreements":[],'
                    '"tail_risks":["t1"],"admin_summary":"x."}')
        return "코멘트 본문."

    monkeypatch.setattr(de, "_call_llm", _fake_call_llm)

    agent_responses = {
        "bull": {"agent": "bull", "stance": "bullish",
                 "key_points": ["p1"], "risk_assessment": "r",
                 "asset_allocation_view": {}, "tail_risks": [],
                 "reasoning": "ok"},
        "bear": {"agent": "bear", "stance": "bearish",
                 "key_points": [], "risk_assessment": "",
                 "asset_allocation_view": {}, "tail_risks": [],
                 "reasoning": ""},
        "quant": {"agent": "quant", "stance": "neutral",
                  "key_points": [], "risk_assessment": "",
                  "asset_allocation_view": {}, "tail_risks": [],
                  "reasoning": ""},
        "monygeek": {"agent": "monygeek", "stance": "neutral",
                     "key_points": [], "risk_assessment": "",
                     "asset_allocation_view": {}, "tail_risks": [],
                     "reasoning": ""},
    }
    context = {
        "year": 2026, "month": 4, "fund_code": None,
        "news_summary_text": "뉴스 요약",
        "graph_paths_text": "",
        "wiki_context_text": "",
        "asset_coverage_text": "",
        "claims_text": "",
        "wiki_primary_context_text": "",
    }
    result = de._synthesize_debate(agent_responses, None, context)
    # Opus Step 1 + Step 2 둘 다 streamed (모델 버전 무관 prefix 매칭 — 2026-07-02)
    opus_calls = [c for c in seen_calls
                   if c["model"].startswith("claude-opus")]
    assert len(opus_calls) == 2
    assert all(c["stream"] is True for c in opus_calls)
    # log_label 별로 둘 다 streamed
    labels = sorted(c["log_label"] for c in opus_calls)
    assert labels == ["synthesis_step1_comment", "synthesis_step2_analysis"]
    # 결과 schema 보존
    assert "customer_comment" in result
    assert result["consensus_points"] == ["c1"]


def test_synthesize_debate_quarterly_uses_stream(monkeypatch, reset_debug_log):
    """분기 모드도 동일 — Step1/Step2 양쪽 stream=True (regression target)."""
    seen: list[dict] = []

    def _fake(model, system, prompt, max_tokens=1500, log_label="",
              *, stream=False):
        seen.append({"label": log_label, "stream": stream,
                      "max_tokens": max_tokens, "model": model})
        if "synthesis_step2" in log_label:
            return ('{"consensus_points":[],"disagreements":[],'
                    '"tail_risks":[],"admin_summary":""}')
        return "분기 본문."

    monkeypatch.setattr(de, "_call_llm", _fake)
    agent_responses = {a: {"agent": a, "stance": "neutral", "key_points": [],
                            "risk_assessment": "", "asset_allocation_view": {},
                            "tail_risks": [], "reasoning": ""}
                       for a in ("bull", "bear", "quant", "monygeek")}
    context = {
        "year": 2026, "month": 3, "fund_code": None,
        "_quarterly": True, "_quarter": 1, "_quarterly_months": [1, 2, 3],
        "news_summary_text": "뉴스",
        "wiki_primary_context_text": "wiki primary 1300 chars 정도 stub",
    }
    de._synthesize_debate(agent_responses, None, context)
    opus = [c for c in seen if c["model"].startswith("claude-opus")]  # 버전 무관 (2026-07-02)
    assert len(opus) == 2
    assert all(c["stream"] is True for c in opus)
    # 분기 Step1 max_tokens = 32000 (월별 16000) — comment_max_tokens 분기 분기
    step1 = next(c for c in opus
                  if c["label"] == "synthesis_step1_comment")
    assert step1["max_tokens"] == 32000


# ──────────────────────────────────────────────────────────────────
# 4. 다른 Opus/Haiku 호출 사이트는 영향 없음 (legacy 회귀 없음)
# ──────────────────────────────────────────────────────────────────

def test_other_call_sites_remain_non_streaming():
    """grep 결과로 _call_llm 호출 사이트 4 개. _synthesize_debate 2 곳만
    stream=True. agent run + debate_narrative 는 그대로 default(False)."""
    src = (Path(__file__).resolve().parent.parent /
           "report" / "debate_engine.py").read_text(encoding="utf-8")
    # synthesis_step1 / synthesis_step2 사이트만 stream=True
    step1_idx = src.index("synthesis_step1_comment")
    step2_idx = src.index("synthesis_step2_analysis")
    # 두 사이트 모두 같은 함수 호출 블록 안에 stream=True 가 함께 있어야 함
    # (간단히는 같은 줄에 'stream=True' 포함 여부를 확인)
    def _block_has_stream_true(anchor: int) -> bool:
        # anchor 위치 전후 400자 안에 stream=True 가 있는지
        s = max(0, anchor - 400)
        e = min(len(src), anchor + 400)
        return "stream=True" in src[s:e]
    assert _block_has_stream_true(step1_idx)
    assert _block_has_stream_true(step2_idx)

    # agent run 사이트 ('agent_' log_label) 는 stream=True 가 없어야 함
    # 정확 매칭: log_label='agent_ 가 등장하는 호출 블록 주위에는 stream True 없음
    agent_idx = src.index("log_label=f'agent_")
    s = max(0, agent_idx - 400)
    e = min(len(src), agent_idx + 200)
    assert "stream=True" not in src[s:e]

    # debate_narrative 사이트도 stream 미사용 (Haiku, 50 토큰)
    narr_idx = src.index("log_label='debate_narrative'")
    s = max(0, narr_idx - 200)
    e = min(len(src), narr_idx + 100)
    assert "stream=True" not in src[s:e]


def test_call_llm_signature_keeps_stream_keyword_only():
    """stream 은 keyword-only — 기존 positional 호출 충돌 없음."""
    import inspect
    sig = inspect.signature(de._call_llm)
    p = sig.parameters["stream"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert p.default is False
