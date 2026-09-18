"""Use the venv PROJ database, not an older PostgreSQL/PostGIS copy."""

from __future__ import annotations

import os
from pathlib import Path

import rasterio


def configure_proj() -> Path:
    """Point PROJ_LIB/PROJ_DATA at Rasterio's bundled proj.db.

    On Windows, PostgreSQL PostGIS often sets PROJ_LIB to an incompatible
    older database, which makes ``CRS.from_epsg(4326)`` fail.
    """
    proj_dir = Path(rasterio.__file__).parent / "proj_data"
    os.environ["PROJ_LIB"] = str(proj_dir)
    os.environ["PROJ_DATA"] = str(proj_dir)
    return proj_dir
