from fastapi import APIRouter

from app.models.schemas import AccessibilityRequest
from app.services import not_implemented

router = APIRouter(prefix="/accessibility", tags=["accessibility"])


@router.post("/route")
def compute_route(payload: AccessibilityRequest) -> dict:
    """OpenRouteService road-network routing for heavy-equipment access."""
    return not_implemented("ors_routing", received=payload.model_dump())


@router.post("/isochrone")
def compute_isochrone(payload: AccessibilityRequest) -> dict:
    return not_implemented("ors_isochrone", received=payload.model_dump())
