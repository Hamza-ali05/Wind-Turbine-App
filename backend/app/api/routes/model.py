from fastapi import APIRouter

from app.services import not_implemented

router = APIRouter(prefix="/model", tags=["model"])


@router.post("/train")
def train_model() -> dict:
    """Trigger Random Forest training."""
    return not_implemented("random_forest_train")


@router.post("/predict")
def predict() -> dict:
    """Run Random Forest prediction over processed layers."""
    return not_implemented("random_forest_predict")
