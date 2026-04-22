from fastapi import APIRouter, Query

from ..schemas.admin import AdminEvidenceQualityResponseDTO
from ..services.admin_service import build_evidence_quality

router = APIRouter()


@router.get(
    "/admin/evidence-quality",
    response_model=AdminEvidenceQualityResponseDTO,
)
def get_evidence_quality(
    limit: int | None = Query(default=None, ge=1, le=500),
    fund_code: str | None = Query(default=None),
) -> AdminEvidenceQualityResponseDTO:
    fc = fund_code.strip() if fund_code else None
    if fc == "":
        fc = None
    return build_evidence_quality(limit=limit, fund_code=fc)
