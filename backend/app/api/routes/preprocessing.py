from fastapi import APIRouter

from app.services import not_implemented

router = APIRouter(prefix="/preprocessing", tags=["preprocessing"])


@router.post("/run")
def run_preprocessing() -> dict:
    """Trigger cleaning, reprojection, and exclusion masking."""
    return not_implemented("preprocessing")
