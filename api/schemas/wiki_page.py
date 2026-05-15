"""Wiki page raw markdown viewer DTO (R9-B viewer endpoint).

Read-only — WIKI_ROOT 산하 .md 단일 파일을 path 로 받아 frontmatter+body 노출.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .meta import BaseMeta


class WikiPageResponseDTO(BaseModel):
    meta: BaseMeta
    path: str  # WIKI_ROOT-relative posix
    directory: str
    page_type: str
    source_type: str
    title: str
    frontmatter: dict[str, Any]
    body: str
    byte_size: int
