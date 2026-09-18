from fastapi import APIRouter

from app.services import not_implemented

router = APIRouter(prefix="/suitability", tags=["suitability"])


@router.post("/run")
def run_suitability() -> dict:
    """Fuse AHP + Random Forest + accessibility into a suitability map."""
    return not_implemented("fused_suitability")


@router.get("/map")
def get_suitability_map() -> dict:
    return not_implemented("suitability_map", format="geojson")
