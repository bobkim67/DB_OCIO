"""Wiki page raw markdown reader (R9-B viewer).

Read-only. WIKI_ROOT 하위 .md 단일 파일을 path 로 받아 frontmatter + body
를 반환. path traversal 방어.

builder 의 `parse_wiki_page` 와 같은 frontmatter parser 를 재사용한다 — 단
``WikiPageRecord`` 가 excerpt 만 들고 있어서, viewer 는 full body 가 필요.
parse_frontmatter 결과 + body 슬라이스를 별도 추출한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from market_research.report.wiki_context_pack_builder import (
    _DIR_TO_SOURCE_TYPE,
    _DIR_TO_TYPE,
    WIKI_ROOT,
    _extract_title,
    _parse_frontmatter,
)


# WIKI_ROOT 산하만 허용. relative path 는 forward-slash 권장 (다른 OS 호환).
def _validate_relative_path(rel: str) -> str:
    if not rel:
        raise ValueError("path is empty")
    rel = rel.strip().replace("\\", "/")
    if rel.startswith("/"):
        raise ValueError("path must be WIKI_ROOT-relative (no leading /)")
    if ".." in rel.split("/"):
        raise ValueError("path traversal not allowed")
    if not rel.endswith(".md"):
        raise ValueError("only .md files are exposed")
    # 알파벳/숫자/한글/`._-/__()` 정도만 허용 — wiki 파일명에 한글이 들어가서
    # 화이트리스트 정규식 대신 블랙리스트 (특수문자) 만.
    if any(c in rel for c in ('\x00', '<', '>', '|', '"')):
        raise ValueError("path contains forbidden characters")
    return rel


def resolve_safe_path(rel: str) -> Path:
    """WIKI_ROOT 산하 절대경로로 변환. escape 시 ValueError."""
    rel = _validate_relative_path(rel)
    root = WIKI_ROOT.resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(f"path escapes WIKI_ROOT: {candidate}")
    return candidate


def load_page(rel_path: str) -> dict[str, Any] | None:
    """rel_path → page dict. 파일 없으면 None.

    Raises ValueError on invalid path (traversal 등).
    """
    abs_path = resolve_safe_path(rel_path)
    if not abs_path.exists() or not abs_path.is_file():
        return None
    try:
        text = abs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    fm, body_off = _parse_frontmatter(text)
    body = text[body_off:]
    title = _extract_title(body)
    rel = rel_path.replace("\\", "/").lstrip("/")
    directory = rel.split("/", 1)[0] if "/" in rel else ""
    page_type = _DIR_TO_TYPE.get(directory, "")
    source_type = _DIR_TO_SOURCE_TYPE.get(directory, "unknown")
    return {
        "path": rel,
        "directory": directory,
        "page_type": page_type,
        "source_type": source_type,
        "title": title,
        "frontmatter": fm,
        "body": body,
        "byte_size": len(text.encode("utf-8")),
    }
