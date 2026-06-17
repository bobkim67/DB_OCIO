# -*- coding: utf-8 -*-
"""Debate context source policy (Phase 1).

debate engine 이 prompt 에 넣는 **컨텍스트 소스를 명시적으로 통제**하는 정책 객체.
기존엔 news/graph/wiki_retriever/blog 가 코드에 하드와이어 → research-only 전환이
불가능했다. 이 모듈은 소스별 on/off + 하드코딩 knob 을 한 곳에 모은다.

- `LEGACY_POLICY`  : 기존 동작 그대로 (전 소스 on). 운영 default — 출력 불변.
- `RESEARCH_ONLY_POLICY` : naver_research wiki + structured synthesis 중심. news /
  graph_paths / wiki keyword retriever / news-derived wiki dir(01/02/07) 차단.
  monygeek **blog source** 는 monygeek **persona** 한정으로 유지(둘은 다른 개념).

⚠️ 명명 규칙 (혼동 방지):
  - `monygeek persona`      = debate 에이전트(유로달러/Jeff Snider 관점). AGENT_PERSONAS['monygeek'].
  - `monygeek_blog_source`  = 네이버 블로그 기반 데이터 소스(blog_context_text).
  policy flag `monygeek_blog_enabled` 는 **blog source** 를 가리킨다.

Phase 1 범위: 정책/조립부 분리 + research-only mode opt-in 배선. default flip 은
09_Research_Synthesis 1급 승격(Phase 2) 후로 미룬다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# research-only mode 에서 wiki_context_pack 이 읽도록 허용하는 dir.
# 01_Events / 02_Entities / 07_Graph_Evidence 는 news/mixed-source 라 제외.
# 09_Research_Synthesis 는 별도 hook build_research_synthesis_context 로 주입.
# Phase 2.7: **08_Claims 제외** — 08 은 뉴스 트랙 claim. 09 가 이미 research claim 을
#   분해→재종합(§4/§5 원자 claim 포함)하므로 research-only 는 09 단일 트랙으로 충분.
#   (08 의 cross-month canonical lineage 는 월간 debate 에 불필요 — operational 트랙에 잔존.)
RESEARCH_WIKI_DIRS: tuple[str, ...] = (
    "03_Assets",
    "05_Regime_Canonical",
)


@dataclass(frozen=True)
class DebateContextPolicy:
    """debate prompt 에 들어갈 소스 on/off + 하드코딩 knob.

    flag=True 면 해당 소스가 컨텍스트에 채워지고, False 면 빈 값으로 남아 prompt 에서
    자연 누락된다(_build_agent_prompt 는 빈 문자열 섹션을 skip).
    """
    name: str

    # ── [B] raw / news-derived 소스 ──
    news_summary_enabled: bool = True          # news_summary_text (토픽 카운트 + asset_impact 집계)
    news_evidence_lane_enabled: bool = True     # evidence Lane B (data/news)
    graph_paths_enabled: bool = True            # graph_paths_text (insight_graph transmission paths)
    wiki_keyword_retriever_enabled: bool = True # wiki_context_text (wiki_retriever 키워드 검색)

    # ── [A] wiki context pack ──
    research_wiki_enabled: bool = True          # build_wiki_context_pack 호출 여부
    # context pack dir 제한 (None = stage default = 전체). research-only 면 RESEARCH_WIKI_DIRS.
    wiki_context_pack_dirs: tuple[str, ...] | None = None
    research_synthesis_enabled: bool = False    # 09_Research_Synthesis hook (Phase 2 승격 대상)

    # ── 공통 ──
    macro_indicators_enabled: bool = True       # indicators_text (data/macro)
    fund_context_enabled: bool = True           # pa_text / bm_text (펀드 코멘트)
    monygeek_blog_enabled: bool = True          # blog_context_text → monygeek **persona** 전용
    # operational(R9-A) claim store(뉴스 트랙) → claims_text. Phase 2.7: research-only 는
    # 09 §4/§5 research claim 으로 대체하므로 False (08 트랙 완전 제외).
    operational_claims_enabled: bool = True

    # ── 하드코딩 knob → config 이동 ──
    evidence_target_count: int = 15
    research_quota: float = 0.7                 # research lane 비율 (나머지 = news)
    max_per_topic: int = 5
    max_per_event: int = 2
    graph_path_min: int = 6
    graph_path_max: int = 10
    graph_confidence_threshold: float = 0.3
    wiki_context_max_pages: int = 12
    # 09_Research_Synthesis (Phase 2)
    research_synthesis_max_assets: int = 8      # 자산군 페이지 상한
    research_synthesis_asset_chars: int = 900   # 자산군별 §1~§3 synthesis 발췌 char 상한
    # Phase 2.7 — 08_Claims 제외 보완: 09 §4/§5 원자 claim 을 debate 에 직접 공급.
    research_synthesis_include_claims: bool = False
    research_synthesis_claims_chars: int = 700  # 자산군별 §4/§5 claim bullet char 상한


LEGACY_POLICY = DebateContextPolicy(name="legacy")

RESEARCH_ONLY_POLICY = DebateContextPolicy(
    name="research_only",
    news_summary_enabled=False,
    news_evidence_lane_enabled=False,
    graph_paths_enabled=False,
    wiki_keyword_retriever_enabled=False,
    research_wiki_enabled=True,
    wiki_context_pack_dirs=RESEARCH_WIKI_DIRS,   # Phase 2.7: 08_Claims 제외(03/05 만)
    research_synthesis_enabled=True,
    research_synthesis_include_claims=True,        # 09 §4/§5 원자 claim 직접 공급(08 대체)
    operational_claims_enabled=False,              # R9-A 뉴스-트랙 claim 제외(09 로 대체)
    macro_indicators_enabled=True,
    fund_context_enabled=True,
    monygeek_blog_enabled=True,   # blog **source** 는 유지 (persona 한정 주입)
)

_PRESETS = {
    "legacy": LEGACY_POLICY,
    "research_only": RESEARCH_ONLY_POLICY,
}


def resolve_policy(context_mode: str = "legacy", *,
                   research_only: bool = False) -> DebateContextPolicy:
    """context_mode → policy. 기존 `research_only: bool` backward-compatible.

    - context_mode='research_only' → RESEARCH_ONLY_POLICY.
    - context_mode='legacy' (default):
        - research_only=False → LEGACY_POLICY (기존 동작 그대로).
        - research_only=True  → 기존 `research_only` 의미(=news evidence lane 만 차단)
          만 보존하는 legacy variant. 다른 소스(news_summary/graph/retriever)는 그대로.
          (과거 호출 시맨틱 불변 — full research-only 와 구분.)
    """
    if context_mode not in _PRESETS:
        raise ValueError(
            f"unknown context_mode: {context_mode!r} (expected {list(_PRESETS)})")
    if context_mode == "research_only":
        return RESEARCH_ONLY_POLICY
    if research_only:
        return replace(LEGACY_POLICY, name="legacy_research_lane_only",
                       news_evidence_lane_enabled=False)
    return LEGACY_POLICY


# ──────────────────────────────────────────────────────────────────
# Debug dump / validation (Phase 1 산출물 §6)
# ──────────────────────────────────────────────────────────────────

# prompt 섹션 라벨 → context dict key. _build_agent_prompt 의 실제 조립 순서 반영.
PROMPT_SECTION_KEYS: dict[str, str] = {
    "wiki_primary_context": "wiki_primary_context_text",  # [A]
    "asset_movement_anchors": "asset_movement_anchors_text",
    "claims": "claims_text",
    "research_synthesis": "research_synthesis_text",       # 09 hook
    "news_summary": "news_summary_text",                   # [B] news
    "indicators": "indicators_text",
    "timeseries_narrative": "timeseries_narrative_text",
    "graph_paths": "graph_paths_text",                     # [B] graph
    "wiki_keyword_retriever": "wiki_context_text",         # [B] retriever
    "asset_coverage": "asset_coverage_text",
    "monygeek_blog": "blog_context_text",                  # monygeek persona 전용
}

# research-only mode 에서 prompt 에 **들어가면 안 되는** 섹션 (검증용).
RESEARCH_ONLY_FORBIDDEN = ("news_summary", "graph_paths", "wiki_keyword_retriever")


def summarize_prompt_sections(context: dict) -> dict[str, int]:
    """context dict 에 채워진 prompt 섹션별 char 수 (0 = 미포함)."""
    return {
        label: len((context.get(key) or "").strip())
        for label, key in PROMPT_SECTION_KEYS.items()
    }


def active_sections(context: dict) -> list[str]:
    """실제로 prompt 에 들어가는(비어있지 않은) 섹션 라벨."""
    return [s for s, n in summarize_prompt_sections(context).items() if n > 0]


def validate_research_only_clean(context: dict) -> tuple[bool, list[str]]:
    """research-only mode 에서 금지 소스(news/graph/retriever)가 비었는지 검증.

    Returns (ok, violations). ok=False 면 raw news 등이 prompt 에 샌 것.
    """
    sizes = summarize_prompt_sections(context)
    violations = [s for s in RESEARCH_ONLY_FORBIDDEN if sizes.get(s, 0) > 0]
    return (not violations), violations
