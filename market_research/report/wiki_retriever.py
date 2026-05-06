"""WikiTree retrieval helper for debate prompt enrichment.

stage 별 retrieval contract:

| stage              | allowed dirs                                                        | 비고                              |
|--------------------|---------------------------------------------------------------------|----------------------------------|
| market_debate      | 01_Events, 02_Entities, 03_Assets, 05_Regime_Canonical              | _market debate 전용              |
| fund_comment       | + 04_Funds (fund_code exact match 만 허용)                          | 펀드 코멘트 단계                  |
| quarterly_debate   | market_debate 와 동일                                               | 분기 시장 debate                 |
| admin_preview      | 모든 디렉토리                                                       | 디버그/관리자 검수용              |

stage 미명시 시 fund_code 로 추론:
  - fund_code in (None, '', '_market') → market_debate
  - 그 외 → fund_comment

fund_code 게이팅 (04_Funds):
  - market_debate / quarterly_debate stage 에서는 04_Funds 디렉토리 자체가 allowed 에 없음
  - fund_comment stage 에서는 04_Funds 페이지 중 파일명에 fund_code 포함된 페이지만 통과
  - 그 외 펀드의 04_Funds 페이지는 skipped_fund_mismatch 카운트

규칙:
  - 500자 미만 page 는 length_bucket=0 으로 강등
  - source/ref/evidence 가 있는 page 우선
  - max wiki_context_chars 기본 1500~2000 (debug trace 노출)
  - 본문 발췌는 page 당 200~400자

이력:
  - 2026-05-04: 03/04 enrichment 후 TARGET_DIRS 5개로 확장 (b6eec0d)
  - 2026-05-06: stage / period / fund_code 시그니처 도입.
                _market debate 에서 04_Funds 제외 (stage contamination 방지 — 시장
                causal graph 와 fund-specific commentary graph 분리). P0-1 + P0-3.
"""
from __future__ import annotations

import re
from pathlib import Path

WIKI_ROOT = Path(__file__).resolve().parent.parent / "data" / "wiki"

# 모든 가용 디렉토리 (admin_preview / 후보 superset)
ALL_DIRS: tuple[str, ...] = (
    "01_Events",
    "02_Entities",
    "03_Assets",
    "04_Funds",
    "05_Regime_Canonical",
)

# Stage 별 allowed dirs (P0-1)
STAGE_ALLOWED_DIRS: dict[str, tuple[str, ...]] = {
    "market_debate": ("01_Events", "02_Entities", "03_Assets", "05_Regime_Canonical"),
    "fund_comment": ("01_Events", "02_Entities", "03_Assets", "04_Funds", "05_Regime_Canonical"),
    "quarterly_debate": ("01_Events", "02_Entities", "03_Assets", "05_Regime_Canonical"),
    "admin_preview": ALL_DIRS,
}

# Backward-compat alias (외부 import 가 있다면 보존)
TARGET_DIRS = ALL_DIRS

MIN_GOOD_LENGTH = 500
MAX_PAGES = 5
PER_PAGE_EXCERPT_CHARS = 380
DEFAULT_MAX_CONTEXT_CHARS = 2000


def _strip_frontmatter(text: str) -> str:
    """YAML frontmatter (--- ... ---) 제거 후 본문 반환."""
    if text.startswith("---"):
        end = text.find("\n---", 4)
        if end > 0:
            return text[end + 4 :].lstrip("\n")
    return text


def _excerpt(text: str, n: int = PER_PAGE_EXCERPT_CHARS) -> str:
    body = _strip_frontmatter(text).strip()
    if len(body) <= n:
        return body
    cut = body[:n]
    last_nl = cut.rfind("\n\n")
    if last_nl > n // 2:
        cut = cut[:last_nl]
    return cut.rstrip() + " …"


def _resolve_stage(stage: str | None, fund_code: str | None) -> str:
    """stage 명시 우선 → fund_code 추론 fallback (legacy compat).

    - stage 명시: STAGE_ALLOWED_DIRS 의 키 중 하나여야 함 (그 외는 ValueError)
    - stage None + fund_code in (None, '', '_market') → 'market_debate'
    - stage None + fund_code 그 외 → 'fund_comment'
    """
    if stage:
        if stage not in STAGE_ALLOWED_DIRS:
            raise ValueError(
                f"Unknown wiki stage {stage!r}. "
                f"Expected one of {sorted(STAGE_ALLOWED_DIRS)}"
            )
        return stage
    if fund_code in (None, "", "_market"):
        return "market_debate"
    return "fund_comment"


def _allowed_dirs(stage: str) -> tuple[str, ...]:
    return STAGE_ALLOWED_DIRS.get(stage, ALL_DIRS)


def _list_candidate_pages(allowed_dirs: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for d in allowed_dirs:
        dp = WIKI_ROOT / d
        if not dp.exists():
            continue
        for fp in sorted(dp.glob("*.md")):
            out.append(fp)
    return out


def _fund_match(fp: Path, fund_code: str | None) -> bool:
    """04_Funds 페이지가 fund_code 와 매칭되는지.

    - 04_Funds 외 디렉토리 페이지: 항상 True (게이팅 무관)
    - 04_Funds 디렉토리 페이지:
        fund_code in (None, '', '_market') → False (전부 차단)
        그 외 → 파일명에 fund_code 포함되어야 True
    """
    if fp.parent.name != "04_Funds":
        return True
    if not fund_code or fund_code == "_market":
        return False
    return fund_code in fp.name


def _split_tokens(s: str) -> list[str]:
    """단어 단위 분할 — 한글/영문 모두 길이 2자 이상만 보존."""
    parts = re.split(r"[\s/,()·_\-→\->]+", s or "")
    return [p for p in parts if len(p) >= 2]


def _score_page(
    page_text: str,
    page_name: str,
    keyword_tokens: list[str],
) -> tuple[int, int, int]:
    """(hit_count, length_bucket, source_bonus) 반환. 큰 값일수록 우선."""
    body_lower = page_text.lower()
    name_lower = page_name.lower()
    hit = 0
    for tok in keyword_tokens:
        tl = tok.lower()
        if not tl:
            continue
        hit += body_lower.count(tl)
        hit += name_lower.count(tl) * 2
    length_bucket = 1 if len(page_text) >= MIN_GOOD_LENGTH else 0
    src_bonus = 1 if (
        "source" in body_lower
        or "[ref:" in body_lower
        or "evidence" in body_lower
    ) else 0
    return hit, length_bucket, src_bonus


def retrieve_wiki_context(
    keywords: list[str],
    *,
    stage: str | None = None,
    fund_code: str | None = None,
    max_pages: int = MAX_PAGES,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> dict:
    """keywords 기반 wiki page 검색 → 발췌 결합.

    Args:
        keywords: 매칭에 사용할 키워드 리스트
        stage: market_debate / fund_comment / quarterly_debate / admin_preview.
               None 이면 fund_code 로 추론 (legacy compat).
        fund_code: fund_comment stage 에서 04_Funds 게이팅. _market/None 이면
                   04_Funds 전체 차단.

    Returns:
        {
          "text": str,
          "selected_pages": list[str],
          "candidate_count": int,                # allowed dir 내 page 수 (gating 후)
          "selected_count": int,
          "context_chars": int,
          "skipped_short_pages": int,
          "skipped_fund_mismatch": int,          # P0-1: 04_Funds 게이팅으로 제외
          "stage_used": str,
          "keywords": list[str],
        }
    """
    resolved_stage = _resolve_stage(stage, fund_code)
    allowed = _allowed_dirs(resolved_stage)

    # tokenize + dedupe
    keyword_tokens: list[str] = []
    for kw in keywords or []:
        keyword_tokens.extend(_split_tokens(kw))
    seen: set[str] = set()
    deduped: list[str] = []
    for t in keyword_tokens:
        tl = t.lower()
        if tl in seen:
            continue
        seen.add(tl)
        deduped.append(t)
    keyword_tokens = deduped

    out_text: list[str] = []
    selected_pages: list[str] = []
    skipped_short = 0
    skipped_fund_mismatch = 0
    total_chars = 0

    raw_candidates = _list_candidate_pages(allowed)

    if not keyword_tokens or not raw_candidates:
        return {
            "text": "",
            "selected_pages": [],
            "candidate_count": len(raw_candidates),
            "selected_count": 0,
            "context_chars": 0,
            "skipped_short_pages": 0,
            "skipped_fund_mismatch": 0,
            "stage_used": resolved_stage,
            "keywords": keyword_tokens,
        }

    # 04_Funds fund_code 게이팅 (P0-1)
    candidates: list[Path] = []
    for fp in raw_candidates:
        if not _fund_match(fp, fund_code):
            skipped_fund_mismatch += 1
            continue
        candidates.append(fp)

    scored: list[tuple[tuple[int, int, int], Path, str]] = []
    for fp in candidates:
        try:
            txt = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        sc = _score_page(txt, fp.name, keyword_tokens)
        if sc[0] == 0:
            continue
        scored.append((sc, fp, txt))

    scored.sort(key=lambda x: (-x[0][0], -x[0][1], -x[0][2]))

    for sc, fp, txt in scored:
        if len(selected_pages) >= max_pages:
            break
        if total_chars >= max_context_chars:
            break
        if sc[1] == 0:
            skipped_short += 1
            continue
        excerpt = _excerpt(txt, PER_PAGE_EXCERPT_CHARS)
        rel = str(fp.relative_to(WIKI_ROOT)).replace("\\", "/")
        block = f"### [{rel}]\n{excerpt}"
        room = max_context_chars - total_chars
        if len(block) > room:
            ELLIPSIS = " …"
            keep = max(0, room - len(ELLIPSIS))
            block = block[:keep].rstrip() + ELLIPSIS
            if len(block) > room:
                block = block[:room]
        if not block.strip():
            continue
        out_text.append(block)
        selected_pages.append(rel)
        total_chars += len(block)

    text = "\n\n".join(out_text)
    return {
        "text": text,
        "selected_pages": selected_pages,
        "candidate_count": len(candidates),
        "selected_count": len(selected_pages),
        "context_chars": total_chars,
        "skipped_short_pages": skipped_short,
        "skipped_fund_mismatch": skipped_fund_mismatch,
        "stage_used": resolved_stage,
        "keywords": keyword_tokens,
    }


def format_wiki_context_for_prompt(retrieval: dict) -> str:
    """retrieval dict → prompt 삽입용 한국어 섹션 텍스트."""
    if not retrieval or not retrieval.get("text"):
        return ""
    return (
        "## 관련 WikiTree 메모\n"
        "다음은 본 debate 의 주요 키워드와 관련된 사내 WikiTree 페이지 발췌입니다. "
        "사실 인용 시 이 내용을 활용하되, 원문 그대로 옮겨 적지 말고 해석으로 사용하세요.\n\n"
        + retrieval["text"]
    )
