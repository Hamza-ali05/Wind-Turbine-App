from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.routes import (
    accessibility,
    ahp,
    data,
    health,
    model,
    preprocessing,
    sites,
    suitability,
    validation,
)
from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.LOG_LEVEL)

app = FastAPI(title="Wind Turbine Site Suitability API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Browsers hitting the origin get the interactive docs, not a 404."""
    return RedirectResponse(url="/docs")

for router in (
    health.router,
    data.router,
    preprocessing.router,
    ahp.router,
    model.router,
    accessibility.router,
    suitability.router,
    validation.router,
    sites.router,
):
    app.include_router(router, prefix="/api/v1")
