from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class PlaceholderResponse(BaseModel):
    status: str = "not_implemented"
    stage: str


class SiteCreate(BaseModel):
    name: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class SiteUpdate(BaseModel):
    name: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class SiteRead(SiteCreate):
    id: int


class AHPWeightsRequest(BaseModel):
    criteria: dict[str, float] = Field(default_factory=dict)


class AccessibilityRequest(BaseModel):
    origin_latitude: float
    origin_longitude: float
    destination_latitude: float | None = None
    destination_longitude: float | None = None


class WindAcquireSummary(BaseModel):
    point_count: int
    wind_speed_min: float
    wind_speed_max: float
    wind_speed_mean: float
    wind_speed_height_m: int = 50
    grid_path: str
    raster_path: str


class TerrainAcquireSummary(BaseModel):
    elevation_min: float
    elevation_max: float
    elevation_mean: float
    slope_min: float
    slope_max: float
    slope_mean: float
    dem_path: str
    slope_path: str
    roughness_path: str
    source: str


class LandCoverAcquireSummary(BaseModel):
    class_counts: dict[str, int]
    class_percent: dict[str, float] = Field(default_factory=dict)
    class_fractions: dict[str, float] = Field(default_factory=dict)
    source: str
    land_cover_path: str
    reclassified_path: str


class InfrastructureAcquireSummary(BaseModel):
    road_edge_count: int
    road_length_km: float
    grid_feature_count: int
    substation_count: int
    tower_count: int
    power_line_count: int
    crs_wgs84: str
    crs_projected: str
    road_path: str
    road_utm_path: str
    grid_path: str
    grid_utm_path: str
