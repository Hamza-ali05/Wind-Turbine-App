from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment / .env files."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    NASA_POWER_BASE_URL: str = "https://power.larc.nasa.gov"
    OPENROUTESERVICE_API_KEY: str = ""
    OSM_OVERPASS_URL: str = "https://overpass.kumi.systems/api/interpreter"
    BACKEND_CORS_ORIGINS: str = "http://localhost:8080,http://127.0.0.1:8080"
    DATABASE_URL: str = "sqlite:///./data/app.db"
    OPENTOPOGRAPHY_API_KEY: str = ""
    ESA_WORLDCOVER_BASE_URL: str = (
        "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
    )
    COPERNICUS_LANDCOVER_WCS_URL: str = ""
    COPERNICUS_LANDCOVER_URL: str = ""
    COPERNICUS_API_KEY: str = ""
    LOG_LEVEL: str = "INFO"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.BACKEND_CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
