from typing import Literal

from pydantic import BaseModel

WarmupStatus = Literal["idle", "running", "done", "done_with_errors", "error"]


class WarmupErrorDTO(BaseModel):
    step: str
    error: str


class WarmupStatusDTO(BaseModel):
    status: WarmupStatus
    phase: str  # "" | essential | brinson
    total: int
    done: int
    essential_total: int
    essential_done: int
    essential_complete: bool  # 프론트 게이트 해제 신호
    error_count: int
    current: str
    # 시작 전/완료 전에는 null. (nullable optional)
    started_at: str | None = None
    finished_at: str | None = None
    errors: list[WarmupErrorDTO]
