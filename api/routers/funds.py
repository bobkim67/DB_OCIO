from datetime import datetime, timezone

from fastapi import APIRouter

from ..schemas.common import FundListResponseDTO
from ..schemas.meta import BaseMeta
from ..services.fund_query_service import list_funds

router = APIRouter()


@router.get("/funds", response_model=FundListResponseDTO)
def get_funds() -> FundListResponseDTO:
    return FundListResponseDTO(
        meta=BaseMeta(
            source="db",
            is_fallback=False,
            generated_at=datetime.now(timezone.utc),
        ),
        data=list_funds(),
    )
