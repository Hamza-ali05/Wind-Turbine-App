# Wind Suitability Platform

Site Suitability Analysis for Wind Turbines in the Sindh Wind Corridor using AHP + Random Forest + OpenRouteService, with an interactive GIS dashboard.

This project implements Muhammad Mustafa Khan's MS thesis work: a hybrid AHP + Random Forest model over GIS layers for the Sindh Wind Corridor (Gharo–Jhimpir), with an interactive dashboard for exploring suitability and validating against existing wind farms.

## Research objectives

1. Build a hybrid model combining environmental data with road logistics to find the best wind farm locations in Sindh, ensuring sites are both windy and reachable for heavy equipment.
2. Create an interactive map dashboard that displays these findings and validates the model against real-world data from existing wind farms in Gharo-Jhimpir.

## Layout

- `backend/` — FastAPI + GIS/ML service (GeoPandas, OSMnx, Rasterio, scikit-learn, OpenRouteService)
- `frontend/` — Schach admin template, adapted into a GIS dashboard

## Stack

- **Backend:** Python, FastAPI, GeoPandas, OSMnx, Rasterio, scikit-learn, OpenRouteService
- **Frontend:** Schach admin dashboard
- **Data/APIs:** NASA POWER (wind), SRTM/ALOS PALSAR (elevation), ESA Copernicus (land cover), OpenStreetMap/OSMnx (roads + grid), OpenRouteService (road-network routing), WWF-Pakistan/PBS shapefiles (exclusion zones)
