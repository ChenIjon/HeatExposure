from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.error import URLError
from urllib.request import urlopen

import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import tifffile
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT_DIR / 'server' / 'results'
DEFAULT_TILE_INDEX_PATH = ROOT_DIR / 'server' / 'data' / 'hk_tiles_index.json'
TILE_INDEX_PATH = Path(os.getenv('HEAT_TILE_INDEX_PATH', str(DEFAULT_TILE_INDEX_PATH))).expanduser()

app = FastAPI(title='HeatExposure Mock API')

DEV_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:4173',
    'http://127.0.0.1:4173',
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount('/results', StaticFiles(directory=RESULTS_DIR), name='results')


class HeatMockResponse(BaseModel):
    date: str
    hour: int
    bbox: Tuple[float, float, float, float]
    tif_path: str
    png_path: str
    bounds: Tuple[Tuple[float, float], Tuple[float, float]]


class HeatTileResult(BaseModel):
    row: int
    col: int
    png_url: str
    tif_url: str
    bounds: Tuple[Tuple[float, float], Tuple[float, float]]


class HeatSeriesHourResult(BaseModel):
    hour: int
    tiles: List[HeatTileResult]


class HeatSeriesResponse(BaseModel):
    date: str
    hours: List[int]
    bounds: Tuple[Tuple[float, float], Tuple[float, float]]
    items: List[HeatSeriesHourResult]
    route_tiles: List[Tuple[int, int]]


class TileMatchResponse(BaseModel):
    route_tiles: List[Tuple[int, int]]


class TileIndexMetaResponse(BaseModel):
    tile_index_path: str
    file_exists: bool
    tile_count: int


class HeatComputeManifest(BaseModel):
    date: str
    hour: int
    route_tiles: List[Tuple[int, int]]


def _parse_bbox(raw_bbox: str) -> Tuple[float, float, float, float]:
    try:
        values = [float(value.strip()) for value in raw_bbox.split(',')]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='bbox must be four comma-separated floats.') from exc

    if len(values) != 4:
        raise HTTPException(status_code=400, detail='bbox format: minLng,minLat,maxLng,maxLat')

    min_lng, min_lat, max_lng, max_lat = values
    if min_lng >= max_lng or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail='bbox is invalid: min must be smaller than max.')

    return min_lng, min_lat, max_lng, max_lat


def _parse_lng_lat(raw_coord: str, name: str) -> Tuple[float, float]:
    try:
        lng_text, lat_text = [item.strip() for item in raw_coord.split(',')]
        lng = float(lng_text)
        lat = float(lat_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'{name} must follow lng,lat format.') from exc

    return lng, lat


def _to_int(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith('-'):
            body = stripped[1:]
            return int(stripped) if body.isdigit() else None
        return int(stripped) if stripped.isdigit() else None
    return None


def _to_float(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _extract_tile_bounds(tile: Dict[str, object]) -> Optional[Tuple[float, float, float, float]]:
    bounds = tile.get('bounds')
    bbox = tile.get('bbox')

    if isinstance(bounds, list) and len(bounds) == 4:
        parsed = [_to_float(item) for item in bounds]
        if all(item is not None for item in parsed):
            min_lng, min_lat, max_lng, max_lat = parsed  # type: ignore[assignment]
            return min_lng, min_lat, max_lng, max_lat

    if isinstance(bbox, list) and len(bbox) == 4:
        parsed = [_to_float(item) for item in bbox]
        if all(item is not None for item in parsed):
            min_lng, min_lat, max_lng, max_lat = parsed  # type: ignore[assignment]
            return min_lng, min_lat, max_lng, max_lat

    min_lng = _to_float(tile.get('min_lng'))
    min_lat = _to_float(tile.get('min_lat'))
    max_lng = _to_float(tile.get('max_lng'))
    max_lat = _to_float(tile.get('max_lat'))
    if None not in (min_lng, min_lat, max_lng, max_lat):
        return min_lng, min_lat, max_lng, max_lat  # type: ignore[return-value]

    left = _to_float(tile.get('left'))
    bottom = _to_float(tile.get('bottom'))
    right = _to_float(tile.get('right'))
    top = _to_float(tile.get('top'))
    if None not in (left, bottom, right, top):
        return left, bottom, right, top  # type: ignore[return-value]

    extent = tile.get('extent')
    if isinstance(extent, list) and len(extent) == 4:
        parsed = [_to_float(item) for item in extent]
        if all(item is not None for item in parsed):
            min_lng, min_lat, max_lng, max_lat = parsed  # type: ignore[assignment]
            return min_lng, min_lat, max_lng, max_lat

    geometry = tile.get('geometry')
    if isinstance(geometry, dict):
        coordinates = geometry.get('coordinates')
        if isinstance(coordinates, list):
            flattened: List[Tuple[float, float]] = []

            def _collect_points(node: object) -> None:
                if not isinstance(node, list):
                    return

                if len(node) >= 2 and isinstance(node[0], (int, float, str)) and isinstance(node[1], (int, float, str)):
                    lng = _to_float(node[0])
                    lat = _to_float(node[1])
                    if lng is not None and lat is not None:
                        flattened.append((lng, lat))
                    return

                for item in node:
                    _collect_points(item)

            _collect_points(coordinates)
            if flattened:
                lng_values = [point[0] for point in flattened]
                lat_values = [point[1] for point in flattened]
                return min(lng_values), min(lat_values), max(lng_values), max(lat_values)

    return None


def _extract_row_col(tile: Dict[str, object]) -> Tuple[Optional[int], Optional[int]]:
    row_candidates = [tile.get('row'), tile.get('tile_row'), tile.get('r'), tile.get('y'), tile.get('tile_y')]
    col_candidates = [tile.get('col'), tile.get('tile_col'), tile.get('c'), tile.get('x'), tile.get('tile_x')]

    properties = tile.get('properties')
    if isinstance(properties, dict):
        row_candidates.extend(
            [
                properties.get('row'),
                properties.get('tile_row'),
                properties.get('r'),
                properties.get('y'),
                properties.get('tile_y'),
            ]
        )
        col_candidates.extend(
            [
                properties.get('col'),
                properties.get('tile_col'),
                properties.get('c'),
                properties.get('x'),
                properties.get('tile_x'),
            ]
        )

    row = next((parsed for candidate in row_candidates if (parsed := _to_int(candidate)) is not None), None)
    col = next((parsed for candidate in col_candidates if (parsed := _to_int(candidate)) is not None), None)
    return row, col


def _extract_raw_tiles(payload: object) -> List[object]:
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in ('tiles', 'features', 'items', 'index'):
            value = payload.get(key)
            if isinstance(value, list):
                return value

    return []


def _load_tile_index(path: Path = TILE_INDEX_PATH) -> List[Dict[str, object]]:
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []

    raw_tiles = _extract_raw_tiles(payload)
    if not raw_tiles:
        return []

    parsed_tiles: List[Dict[str, object]] = []
    for tile in raw_tiles:
        if not isinstance(tile, dict):
            continue

        row, col = _extract_row_col(tile)

        bounds = _extract_tile_bounds(tile)
        if row is None or col is None or bounds is None:
            continue

        min_lng, min_lat, max_lng, max_lat = bounds
        if min_lng >= max_lng or min_lat >= max_lat:
            continue

        parsed_tiles.append(
            {
                'row': row,
                'col': col,
                'min_lng': min_lng,
                'min_lat': min_lat,
                'max_lng': max_lng,
                'max_lat': max_lat,
            }
        )

    return parsed_tiles


def _tile_lookup_by_row_col(tile_index: List[Dict[str, object]]) -> Dict[Tuple[int, int], Dict[str, object]]:
    lookup: Dict[Tuple[int, int], Dict[str, object]] = {}
    for tile in tile_index:
        lookup[(int(tile['row']), int(tile['col']))] = tile
    return lookup


def _densify_route(route_coords: List[List[float]], max_step_deg: float = 0.0003) -> List[Tuple[float, float]]:
    if len(route_coords) < 2:
        return [(coord[0], coord[1]) for coord in route_coords]

    points: List[Tuple[float, float]] = []
    for index in range(len(route_coords) - 1):
        start_lng, start_lat = route_coords[index]
        end_lng, end_lat = route_coords[index + 1]
        delta_lng = end_lng - start_lng
        delta_lat = end_lat - start_lat
        max_delta = max(abs(delta_lng), abs(delta_lat))
        steps = max(1, int(max_delta / max_step_deg))

        for step in range(steps):
            ratio = step / steps
            points.append((start_lng + delta_lng * ratio, start_lat + delta_lat * ratio))

    last_lng, last_lat = route_coords[-1]
    points.append((last_lng, last_lat))
    return points


def _match_route_tiles(route_coords: List[List[float]], tile_index: List[Dict[str, object]]) -> List[Tuple[int, int]]:
    if not tile_index or len(route_coords) < 2:
        return []

    sampled_points = _densify_route(route_coords)
    matched: Set[Tuple[int, int]] = set()

    for lng, lat in sampled_points:
        for tile in tile_index:
            min_lng = float(tile['min_lng'])
            min_lat = float(tile['min_lat'])
            max_lng = float(tile['max_lng'])
            max_lat = float(tile['max_lat'])

            if min_lng <= lng <= max_lng and min_lat <= lat <= max_lat:
                matched.add((int(tile['row']), int(tile['col'])))

    return sorted(matched)


def _stable_seed(token: str) -> int:
    return int(hashlib.sha256(token.encode('utf-8')).hexdigest()[:8], 16)


def _mock_heat_array(seed: int, size: int = 256) -> np.ndarray:
    rng = np.random.default_rng(seed)
    y_grid, x_grid = np.mgrid[0:size, 0:size].astype(np.float32)

    base_gradient = (x_grid * 0.6 + y_grid * 0.4) / size
    ridge = np.sin(x_grid / 17.0) * 0.1 + np.cos(y_grid / 29.0) * 0.08
    noise = rng.random((size, size), dtype=np.float32) * 0.22

    heat = base_gradient + ridge + noise
    heat = np.clip(heat, 0.0, 1.0)
    return heat.astype(np.float32)


def _write_geotiff(heat: np.ndarray, path: Path, bbox: Tuple[float, float, float, float]) -> None:
    min_lng, _min_lat, max_lng, max_lat = bbox
    height, width = heat.shape
    pixel_width = (max_lng - min_lng) / float(width)
    pixel_height = (bbox[3] - bbox[1]) / float(height)

    model_pixel_scale = (pixel_width, pixel_height, 0.0)
    model_tie_point = (0.0, 0.0, 0.0, min_lng, max_lat, 0.0)
    geokey_directory = (
        1,
        1,
        0,
        7,
        1024,
        0,
        1,
        2,
        1025,
        0,
        1,
        1,
        2048,
        0,
        1,
        4326,
        2049,
        34737,
        7,
        0,
        2054,
        0,
        1,
        9102,
        2057,
        34736,
        1,
        1,
        2059,
        34736,
        1,
        0,
    )

    tifffile.imwrite(
        path,
        heat,
        dtype=np.float32,
        metadata=None,
        extratags=[
            (33550, 'd', 3, model_pixel_scale, False),
            (33922, 'd', 6, model_tie_point, False),
            (34735, 'H', len(geokey_directory), geokey_directory, False),
        ],
    )


def _discrete_utci_colormap() -> Tuple[mcolors.ListedColormap, mcolors.BoundaryNorm, List[float]]:
    boundaries = [0.0, 10.0, 20.0, 25.0, 28.0, 31.0, 34.0, 37.0, 40.0]
    color_count = len(boundaries) - 1
    base_cmap = cm.get_cmap('jet', color_count)
    colors = base_cmap(np.linspace(0, 1, color_count))
    cmap = mcolors.ListedColormap(colors)
    norm = mcolors.BoundaryNorm(boundaries, cmap.N, clip=True)
    return cmap, norm, boundaries


def _write_overlay_png_discrete(heat: np.ndarray, path: Path) -> None:
    cmap, norm, _boundaries = _discrete_utci_colormap()
    rgba = cmap(norm(heat))
    rgba[..., 3] = 0.65
    plt.imsave(path, rgba)


def _expand_bbox(bbox: Tuple[float, float, float, float], ratio: float = 0.05) -> Tuple[float, float, float, float]:
    min_lng, min_lat, max_lng, max_lat = bbox
    delta_lng = max(max_lng - min_lng, 1e-5)
    delta_lat = max(max_lat - min_lat, 1e-5)

    pad_lng = delta_lng * ratio
    pad_lat = delta_lat * ratio
    return min_lng - pad_lng, min_lat - pad_lat, max_lng + pad_lng, max_lat + pad_lat


def _bbox_from_route(route_coords: List[List[float]]) -> Tuple[float, float, float, float]:
    lngs = [coord[0] for coord in route_coords]
    lats = [coord[1] for coord in route_coords]
    return min(lngs), min(lats), max(lngs), max(lats)


def _fetch_route_geometry(
    start: Tuple[float, float],
    end: Tuple[float, float],
    profile: str,
) -> Optional[List[List[float]]]:
    allowed_profiles = {'walking', 'driving', 'running'}
    safe_profile = profile if profile in allowed_profiles else 'walking'
    url = (
        f'https://router.project-osrm.org/route/v1/{safe_profile}/'
        f'{start[0]},{start[1]};{end[0]},{end[1]}?overview=full&geometries=geojson'
    )

    try:
        with urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except (URLError, TimeoutError, json.JSONDecodeError):
        return None

    geometry = payload.get('routes', [{}])[0].get('geometry', {})
    coords = geometry.get('coordinates') if isinstance(geometry, dict) else None
    if not isinstance(coords, list) or len(coords) < 2:
        return None

    return [[float(point[0]), float(point[1])] for point in coords]


def _parse_hours(start_hour: Optional[int], n_hours: Optional[int], hours: Optional[str]) -> List[int]:
    if start_hour is not None and n_hours is not None:
        if n_hours <= 0:
            raise HTTPException(status_code=400, detail='n_hours must be greater than zero.')
        if start_hour < 0 or start_hour > 23:
            raise HTTPException(status_code=400, detail='start_hour must be between 0 and 23.')

        output: List[int] = []
        for offset in range(n_hours):
            hour = (start_hour + offset) % 24
            output.append(hour)
        return output

    if hours:
        try:
            parsed = [int(item.strip()) for item in hours.split(',') if item.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail='hours must be comma-separated integers.') from exc

        if not parsed:
            raise HTTPException(status_code=400, detail='hours cannot be empty.')

        for value in parsed:
            if value < 0 or value > 23:
                raise HTTPException(status_code=400, detail='each hour must be in 0..23.')
        return parsed

    raise HTTPException(status_code=400, detail='provide start_hour+n_hours or hours.')


def _generate_route_weighted_heat(
    seed: int,
    bbox: Tuple[float, float, float, float],
    route_coords: List[List[float]],
    size: int = 256,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    min_lng, min_lat, max_lng, max_lat = bbox

    width = max(max_lng - min_lng, 1e-6)
    height = max(max_lat - min_lat, 1e-6)

    step = max(1, len(route_coords) // 180)
    sampled = route_coords[::step]
    if sampled[-1] != route_coords[-1]:
        sampled.append(route_coords[-1])

    route_array = np.array(sampled, dtype=np.float32)
    route_norm_x = (route_array[:, 0] - min_lng) / width
    route_norm_y = (route_array[:, 1] - min_lat) / height

    y_index, x_index = np.mgrid[0:size, 0:size].astype(np.float32)
    grid_x = x_index / (size - 1)
    grid_y = y_index / (size - 1)

    dx = grid_x[..., None] - route_norm_x[None, None, :]
    dy = grid_y[..., None] - route_norm_y[None, None, :]
    dist = np.sqrt(dx * dx + dy * dy)
    min_dist = np.min(dist, axis=2)

    route_heat = np.exp(-min_dist * 14.0)
    broad_gradient = 0.35 + 0.65 * (0.5 * grid_x + 0.5 * grid_y)
    noise = rng.normal(loc=0.0, scale=0.55, size=(size, size)).astype(np.float32)

    utci = 8.0 + route_heat * 24.0 + broad_gradient * 9.0 + noise
    utci = np.clip(utci, 0.0, 40.0)
    return utci.astype(np.float32)


def _write_compute_manifest(date: str, hour: int, route_tiles: List[Tuple[int, int]]) -> None:
    manifest_dir = RESULTS_DIR / date.replace('-', '') / f'{hour:02d}'
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = manifest_dir / 'compute_manifest.json'
    payload = HeatComputeManifest(date=date, hour=hour, route_tiles=route_tiles).model_dump()
    manifest_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


@app.get('/api/heat/mock', response_model=HeatMockResponse)
def build_mock_heat_layer(
    date: str = Query(..., description='YYYY-MM-DD'),
    hour: int = Query(..., ge=0, le=23),
    bbox: str = Query(..., description='minLng,minLat,maxLng,maxLat'),
) -> HeatMockResponse:
    try:
        datetime.strptime(date, '%Y-%m-%d')
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='date must match YYYY-MM-DD.') from exc

    parsed_bbox = _parse_bbox(bbox)
    seed = _stable_seed(f'{date}-{hour}-{";".join(str(v) for v in parsed_bbox)}')
    heat_norm = _mock_heat_array(seed=seed)
    heat_utci = (heat_norm * 40.0).astype(np.float32)

    date_folder = date.replace('-', '')
    hour_folder = f'{hour:02d}'
    output_dir = RESULTS_DIR / date_folder / hour_folder
    output_dir.mkdir(parents=True, exist_ok=True)

    tif_file = output_dir / 'heat_exposure.tif'
    png_file = output_dir / 'heat_exposure.png'

    if not (tif_file.exists() and png_file.exists()):
        _write_geotiff(heat_utci, tif_file, parsed_bbox)
        _write_overlay_png_discrete(heat_utci, png_file)

    min_lng, min_lat, max_lng, max_lat = parsed_bbox
    return HeatMockResponse(
        date=date,
        hour=hour,
        bbox=parsed_bbox,
        tif_path=f'/results/{date_folder}/{hour_folder}/{tif_file.name}',
        png_path=f'/results/{date_folder}/{hour_folder}/{png_file.name}',
        bounds=((min_lng, min_lat), (max_lng, max_lat)),
    )


@app.get('/api/heat/mock/series', response_model=HeatSeriesResponse)
def build_mock_heat_series(
    date: str = Query(..., description='YYYY-MM-DD'),
    start: str = Query(..., description='lng,lat'),
    end: str = Query(..., description='lng,lat'),
    start_hour: Optional[int] = Query(default=None, ge=0, le=23),
    n_hours: Optional[int] = Query(default=None, ge=1, le=24),
    hours: Optional[str] = Query(default=None, description='comma-separated hours'),
    profile: str = Query(default='walking'),
) -> HeatSeriesResponse:
    try:
        datetime.strptime(date, '%Y-%m-%d')
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='date must match YYYY-MM-DD.') from exc

    start_point = _parse_lng_lat(start, 'start')
    end_point = _parse_lng_lat(end, 'end')
    parsed_hours = _parse_hours(start_hour=start_hour, n_hours=n_hours, hours=hours)

    route_coords = _fetch_route_geometry(start_point, end_point, profile=profile)
    if route_coords is None:
        route_coords = [[start_point[0], start_point[1]], [end_point[0], end_point[1]]]

    tile_index = _load_tile_index()
    route_tiles = _match_route_tiles(route_coords=route_coords, tile_index=tile_index)
    tile_lookup = _tile_lookup_by_row_col(tile_index)

    route_bbox = _expand_bbox(_bbox_from_route(route_coords), ratio=0.05)
    min_lng, min_lat, max_lng, max_lat = route_bbox

    date_folder = date.replace('-', '')
    items: List[HeatSeriesHourResult] = []

    for hour in parsed_hours:
        hour_folder = f'{hour:02d}'
        output_dir = RESULTS_DIR / date_folder / hour_folder
        tile_output_dir = output_dir / 'tiles'
        tile_output_dir.mkdir(parents=True, exist_ok=True)

        hour_tile_results: List[HeatTileResult] = []
        for row, col in route_tiles:
            tile_meta = tile_lookup.get((row, col))
            if not tile_meta:
                continue

            tile_bbox = (
                float(tile_meta['min_lng']),
                float(tile_meta['min_lat']),
                float(tile_meta['max_lng']),
                float(tile_meta['max_lat']),
            )

            tile_prefix = f'r{row}_c{col}'
            tif_file = tile_output_dir / f'{tile_prefix}.tif'
            png_file = tile_output_dir / f'{tile_prefix}.png'

            if not (tif_file.exists() and png_file.exists()):
                seed = _stable_seed(f'{date}-{hour}-{row}-{col}-{start}-{end}')
                heat = _generate_route_weighted_heat(seed=seed, bbox=tile_bbox, route_coords=route_coords)
                _write_geotiff(heat, tif_file, tile_bbox)
                _write_overlay_png_discrete(heat, png_file)

            hour_tile_results.append(
                HeatTileResult(
                    row=row,
                    col=col,
                    png_url=f'/results/{date_folder}/{hour_folder}/tiles/{png_file.name}',
                    tif_url=f'/results/{date_folder}/{hour_folder}/tiles/{tif_file.name}',
                    bounds=((tile_bbox[0], tile_bbox[1]), (tile_bbox[2], tile_bbox[3])),
                )
            )

        _write_compute_manifest(date=date, hour=hour, route_tiles=route_tiles)
        items.append(HeatSeriesHourResult(hour=hour, tiles=hour_tile_results))

    return HeatSeriesResponse(
        date=date,
        hours=parsed_hours,
        bounds=((min_lng, min_lat), (max_lng, max_lat)),
        items=items,
        route_tiles=route_tiles,
    )


@app.get('/api/tiles/route', response_model=TileMatchResponse)
def get_route_tile_matches(
    start: str = Query(..., description='lng,lat'),
    end: str = Query(..., description='lng,lat'),
    profile: str = Query(default='walking'),
) -> TileMatchResponse:
    start_point = _parse_lng_lat(start, 'start')
    end_point = _parse_lng_lat(end, 'end')

    route_coords = _fetch_route_geometry(start_point, end_point, profile=profile)
    if route_coords is None:
        route_coords = [[start_point[0], start_point[1]], [end_point[0], end_point[1]]]

    tile_index = _load_tile_index()
    route_tiles = _match_route_tiles(route_coords=route_coords, tile_index=tile_index)
    return TileMatchResponse(route_tiles=route_tiles)


@app.get('/api/tiles/index/meta', response_model=TileIndexMetaResponse)
def get_tile_index_meta() -> TileIndexMetaResponse:
    tile_index = _load_tile_index()
    return TileIndexMetaResponse(
        tile_index_path=str(TILE_INDEX_PATH),
        file_exists=TILE_INDEX_PATH.exists(),
        tile_count=len(tile_index),
    )


@app.get('/api/tiles/route', response_model=TileMatchResponse)
def get_route_tile_matches(
    start: str = Query(..., description='lng,lat'),
    end: str = Query(..., description='lng,lat'),
    profile: str = Query(default='walking'),
) -> TileMatchResponse:
    start_point = _parse_lng_lat(start, 'start')
    end_point = _parse_lng_lat(end, 'end')

    route_coords = _fetch_route_geometry(start_point, end_point, profile=profile)
    if route_coords is None:
        route_coords = [[start_point[0], start_point[1]], [end_point[0], end_point[1]]]

    tile_index = _load_tile_index()
    route_tiles = _match_route_tiles(route_coords=route_coords, tile_index=tile_index)
    return TileMatchResponse(route_tiles=route_tiles)
