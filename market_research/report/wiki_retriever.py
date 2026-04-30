"""WikiTree retrieval helper for debate prompt enrichment.

01_Events / 02_Entities / 05_Regime_Canonical 페이지를 keyword 매칭으로 검색
하여 debate prompt 의 "관련 WikiTree 메모" 섹션에 발췌를 삽입한다.

규칙 (사용자 지시):
  - 03_Assets / 04_Funds 는 빈약하므로 이번 retrieval 대상에서 제외
  - 500자 미만 page 는 낮은 우선순위
  - source/ref 가 있는 page 우선
  - max wiki_context_chars 기본 1500~2000 (debug trace 노출)
  - 본문 발췌는 page 당 200~400자
"""
from __future__ import annotations

import re
from pathlib import Path

WIKI_ROOT = Path(__file__).resolve().parent.parent / "data" / "wiki"
TARGET_DIRS: tuple[str, ...] = ("01_Events", "02_Entities", "05_Regime_Canonical")
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
    # 자연스러운 줄 끊김 시도 (마지막 문단 경계)
    last_nl = cut.rfind("\n\n")
    if last_nl > n // 2:
        cut = cut[:last_nl]
    return cut.rstrip() + " …"


def _list_candidate_pages() -> list[Path]:
    out: list[Path] = []
    for d in TARGET_DIRS:
        dp = WIKI_ROOT / d
        if not dp.exists():
            continue
        for fp in sorted(dp.glob("*.md")):
            out.append(fp)
    return out


def _normalize_keyword(s: str) -> str:
    return s.replace("_", " ").replace("·", " ").strip().lower()


def _split_tokens(s: str) -> list[str]:
    """단어 단위 분할 — 한글/영문 모두 길이 2자 이상만 보존."""
    parts = re.split(r"[\s/,()·_\-→\->]+", s or "")
    return [p for p in parts if len(p) >= 2]


def _score_page(
    page_text: str,
    page_name: str,
    keyword_tokens: list[str],
) -> tuple[int, int, int]:
    """(hit_count, length_bucket, source_bonus) 반환. 큰 값일수록 우선.

    hit_count: page 본문 + 파일명에서 token 출현 횟수
    length_bucket: 0(<500ch) / 1(>=500ch)
    source_bonus: source/ref/evidence 포함 시 1
    """
    body_lower = page_text.lower()
    name_lower = page_name.lower()
    hit = 0
    for tok in keyword_tokens:
        tl = tok.lower()
        if not tl:
            continue
        hit += body_lower.count(tl)
        hit += name_lower.count(tl) * 2  # 파일명 가중
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
    max_pages: int = MAX_PAGES,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> dict:
    """keywords 기반 wiki page 검색 → 발췌 결합.

    Returns:
        {
          "text": str,                         # prompt 삽입용 본문 (빈 문자열 허용)
          "selected_pages": list[str],         # 상대 경로 (debug trace)
          "candidate_count": int,
          "selected_count": int,
          "context_chars": int,
          "skipped_short_pages": int,          # < MIN_GOOD_LENGTH 로 우선순위 낮춰진 page 수
          "keywords": list[str],               # 매칭에 사용된 token
        }
    """
    keyword_tokens: list[str] = []
    for kw in keywords or []:
        keyword_tokens.extend(_split_tokens(kw))
    # dedupe
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
    total_chars = 0
    candidates = _list_candidate_pages()

    if not keyword_tokens or not candidates:
        return {
            "text": "",
            "selected_pages": [],
            "candidate_count": len(candidates),
            "selected_count": 0,
            "context_chars": 0,
            "skipped_short_pages": 0,
            "keywords": keyword_tokens,
        }

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

    # 정렬: hit_count desc → length_bucket desc → source_bonus desc
    scored.sort(key=lambda x: (-x[0][0], -x[0][1], -x[0][2]))

    for sc, fp, txt in scored:
        if len(selected_pages) >= max_pages:
            break
        if total_chars >= max_context_chars:
            break
        # 짧은 page 는 우선순위 강등 — 후순위로 보내고 카운트
        if sc[1] == 0:
            skipped_short += 1
            # 단, 사용 가능한 후보가 부족하면 짧은 page 도 흡수 (일단 skip)
            continue
        excerpt = _excerpt(txt, PER_PAGE_EXCERPT_CHARS)
        rel = str(fp.relative_to(WIKI_ROOT)).replace("\\", "/")
        block = f"### [{rel}]\n{excerpt}"
        # max_context_chars 초과 시 잘라 맞춤 (header + " …" suffix 포함 전체 길이 기준)
        room = max_context_chars - total_chars
        if len(block) > room:
            ELLIPSIS = " …"
            keep = max(0, room - len(ELLIPSIS))
            block = block[:keep].rstrip() + ELLIPSIS
            if len(block) > room:  # rstrip 으로 짧아져 약간 여유 있을 수도; 보호적
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
        "keywords": keyword_tokens,
    }


def format_wiki_context_for_prompt(retrieval: dict) -> str:
    """retrieval dict → prompt 삽입용 한국어 섹션 텍스트.

    빈 retrieval 이면 빈 문자열 반환 (graceful)."""
    if not retrieval or not retrieval.get("text"):
        return ""
    return (
        "## 관련 WikiTree 메모\n"
        "다음은 본 debate 의 주요 키워드와 관련된 사내 WikiTree 페이지 발췌입니다. "
        "사실 인용 시 이 내용을 활용하되, 원문 그대로 옮겨 적지 말고 해석으로 사용하세요.\n\n"
        + retrieval["text"]
    )
