from fastapi import APIRouter

from app.models.schemas import AHPWeightsRequest
from app.services import not_implemented

router = APIRouter(prefix="/ahp", tags=["ahp"])


@router.get("/criteria")
def list_criteria() -> dict:
    return not_implemented(
        "ahp_criteria",
        criteria=["wind_speed", "slope", "land_cover", "grid_proximity", "road_access"],
    )


@router.post("/weights")
def submit_weights(payload: AHPWeightsRequest) -> dict:
    return not_implemented("ahp_weights", received=payload.model_dump())
