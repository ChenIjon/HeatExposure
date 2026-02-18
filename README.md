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
- **Returns:** `hours`, route-based `bounds`, `route_tiles`, and per-hour `items` where each hour contains multiple tile results: `tiles[] -> {row,col,png_url,tif_url,bounds}`.

### Route tile matching

- **Endpoint:** `GET /api/tiles/route`
- **Query params:**
  - `start=lng,lat`
  - `end=lng,lat`
  - optional: `profile=walking|driving|running`
- **Returns:** `route_tiles` as `[[row, col], ...]`.

### How to provide your Hong Kong Island tile index JSON

Put your index file at:

- default path: `server/data/hk_tiles_index.json`
- or set env var: `HEAT_TILE_INDEX_PATH=/your/path/tile_index.json`

Supported JSON shapes:

1. Root list:

```json
[
  { "row": 12, "col": 7, "bounds": [114.10, 22.22, 114.12, 22.24] }
]
```

2. Object with `tiles`:

```json
{
  "tiles": [
    { "tile_row": 12, "tile_col": 7, "min_lng": 114.10, "min_lat": 22.22, "max_lng": 114.12, "max_lat": 22.24 }
  ]
}
```

3. Alternative boundary keys:

```json
{
  "tiles": [
    { "row": 12, "col": 7, "left": 114.10, "bottom": 22.22, "right": 114.12, "top": 22.24 }
  ]
}
```

4. GeoJSON `FeatureCollection`:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": { "row": 12, "col": 7 },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[114.10, 22.22], [114.12, 22.22], [114.12, 22.24], [114.10, 22.24], [114.10, 22.22]]]
      }
    }
  ]
}
```

### Check whether backend reads your index correctly

- **Endpoint:** `GET /api/tiles/index/meta`
- **Returns:** `tile_index_path`, `file_exists`, `tile_count`
- Use this to quickly verify the server can see your JSON and parsed tile count is non-zero.

Artifacts are generated under `server/results/YYYYMMDD/HH/`:

- `tiles/r{row}_c{col}.tif`
- `tiles/r{row}_c{col}.png` (one hour + one tile)
- `compute_manifest.json` (date, hour, and all route tile row/col tuples; placeholder payload for future server integration)

Mock generation is deterministic and seeded from request fields (date/hour/row/col/start/end for series).

## Frontend trigger

In the web UI panel:

1. Pick or type Start/End (defaults now in Hong Kong Island).
2. Click the heat-condition toggle button (it lazily loads hour-series on first enable).
3. Select hour from the **Hour** dropdown to switch all tile overlays for that hour.
4. Toggle button on/off to show or hide heat condition overlays.
5. Map shows a fixed left-top discrete UTCI colorbar.
6. Basemap uses OpenStreetMap raster tiles with attribution: © OpenStreetMap contributors.

## Dev API base URL configuration

Frontend uses `VITE_API_BASE_URL` to target backend in dev.

- default: empty (`""`), meaning same-origin requests
- cross-origin example: `VITE_API_BASE_URL=http://127.0.0.1:8000`

When set, both API fetch and overlay image path (`/results/...png`) are resolved against the same base URL.
