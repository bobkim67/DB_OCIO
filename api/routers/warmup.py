from fastapi import APIRouter

from ..schemas.warmup import WarmupStatusDTO
from ..warmup import get_state

router = APIRouter()


@router.get("/warmup-status", response_model=WarmupStatusDTO)
def warmup_status() -> WarmupStatusDTO:
    """앱 시작 시 백그라운드 워밍업 진행률.

    status: idle | running | done | done_with_errors | error
    """
    return WarmupStatusDTO(**get_state())
