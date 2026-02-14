# HeatExposure

An app for fast heat exposure mapping.

## Mock heat layer API (placeholder)

This repository includes mock backend endpoints for repeatable heat-exposure raster artifacts.

### Single hour

- **Endpoint:** `GET /api/heat/mock`
- **Query params:**
  - `date=YYYY-MM-DD`
  - `hour=0-23`
  - `bbox=minLng,minLat,maxLng,maxLat`

### Time series along route

- **Endpoint:** `GET /api/heat/mock/series`
- **Query params:**
  - `date=YYYY-MM-DD`
  - `start=lng,lat`
  - `end=lng,lat`
  - preferred: `start_hour=13&n_hours=6`
  - optional alternative: `hours=13,14,15`
  - optional: `profile=walking|driving|running`
- **Returns:** `hours`, route-based `bounds`, and `items` with `png_url` / `tif_url` per hour.

Artifacts are generated under `server/results/YYYYMMDD/HH/`:

- `heat_exposure.tif`
- `heat_exposure.png` (jet-based discrete UTCI color mapping)

Mock generation is deterministic and seeded from request fields (date/hour/start/end for series).

## Frontend trigger

In the web UI panel:

1. Pick or type Start/End.
2. Click **Load heat series** (defaults to date `2026-02-14`, hours `13..18`).
3. Select hour from the **Hour** dropdown to switch overlay image.
4. Use **Show/Hide heat layer** to toggle visibility.
5. Map shows a fixed left-top discrete UTCI colorbar.
6. Basemap tiles are from OpenStreetMap raster tiles (attribution: © OpenStreetMap contributors).

## Dev API base URL configuration

Frontend uses `VITE_API_BASE_URL` to target backend in dev.

- default: empty (`""`), meaning same-origin requests
- cross-origin example: `VITE_API_BASE_URL=http://127.0.0.1:8000`

When set, both API fetch and overlay image path (`/results/...png`) are resolved against the same base URL.
