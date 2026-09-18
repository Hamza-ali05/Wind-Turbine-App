from fastapi import APIRouter

from app.services import not_implemented

router = APIRouter(prefix="/validation", tags=["validation"])


@router.get("/gharo-jhimpir")
def validate_against_existing_farms() -> dict:
    """Compare model output to existing Gharo-Jhimpir wind farms."""
    return not_implemented("validation_gharo_jhimpir", farms=[])
