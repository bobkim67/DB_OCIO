from typing import Literal

from pydantic import BaseModel

WarmupStatus = Literal["idle", "running", "done", "done_with_errors", "error"]


class WarmupErrorDTO(BaseModel):
    step: str
    error: str


class WarmupStatusDTO(BaseModel):
    status: WarmupStatus
    total: int
    done: int
    error_count: int
    current: str
    # 시작 전/완료 전에는 null. (nullable optional)
    started_at: str | None = None
    finished_at: str | None = None
    errors: list[WarmupErrorDTO]
