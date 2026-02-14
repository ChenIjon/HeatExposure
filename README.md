# HeatExposure

An app for fast heat exposure mapping.

## Mock heat layer API (placeholder)

This repository now includes a mock backend endpoint for generating repeatable heat-exposure raster artifacts:

- **Endpoint:** `GET /api/heat/mock`
- **Query params:**
  - `date=YYYY-MM-DD`
  - `hour=0-23`
  - `bbox=minLng,minLat,maxLng,maxLat`
- **Response fields:** `date`, `hour`, `bbox`, `tif_path`, `png_path`, `bounds`

Artifacts are generated under `server/results/YYYYMMDD/HH/`:

- `heat_exposure.tif` (mock GeoTIFF)
- `heat_exposure.png` (jet-colored PNG overlay)

Mock generation is deterministic. The seed is derived from:

`sha256(f"{date}-{hour}-{bbox}")[:8]`

## Frontend trigger

In the web UI panel:

1. Click **Load heat layer** (defaults to date `2026-02-14`, hour `13`).
2. The frontend uses `map.getBounds()` as bbox and calls `/api/heat/mock`.
3. Returned `png_path` + `bbox` are overlaid as a MapLibre image/raster layer.
4. Use **Show/Hide heat layer** to toggle visibility.
