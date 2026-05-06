"""R4 DTO: Comment trace report.

list / latest / by-id endpoint 응답 schema.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .meta import BaseMeta


class CommentTraceListItemDTO(BaseModel):
    trace_id: str
    fund_code: str
    period: str
    generated_at: str | None = None
    schema_version: str | None = None
    graph_node_count: int = 0
    graph_edge_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    size_bytes: int = 0


class CommentTraceListResponseDTO(BaseModel):
    meta: BaseMeta
    traces: list[CommentTraceListItemDTO]


class CommentTraceFullResponseDTO(BaseModel):
    """Full payload — schema 진화 호환 위해 dict[str, Any] 그대로."""
    meta: BaseMeta
    trace_id: str
    payload: dict[str, Any]
