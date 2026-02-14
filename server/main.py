from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
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


class HeatSeriesItem(BaseModel):
    hour: int
    png_url: str
    tif_url: str


class HeatSeriesResponse(BaseModel):
    date: str
    hours: List[int]
    bounds: Tuple[Tuple[float, float], Tuple[float, float]]
    items: List[HeatSeriesItem]


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

    route_bbox = _expand_bbox(_bbox_from_route(route_coords), ratio=0.05)
    min_lng, min_lat, max_lng, max_lat = route_bbox

    date_folder = date.replace('-', '')
    items: List[HeatSeriesItem] = []

    for hour in parsed_hours:
        hour_folder = f'{hour:02d}'
        output_dir = RESULTS_DIR / date_folder / hour_folder
        output_dir.mkdir(parents=True, exist_ok=True)

        tif_file = output_dir / 'heat_exposure.tif'
        png_file = output_dir / 'heat_exposure.png'

        if not (tif_file.exists() and png_file.exists()):
            seed = _stable_seed(f'{date}-{hour}-{start}-{end}')
            heat = _generate_route_weighted_heat(seed=seed, bbox=route_bbox, route_coords=route_coords)

            _write_geotiff(heat, tif_file, route_bbox)
            _write_overlay_png_discrete(heat, png_file)

        items.append(
            HeatSeriesItem(
                hour=hour,
                png_url=f'/results/{date_folder}/{hour_folder}/{png_file.name}',
                tif_url=f'/results/{date_folder}/{hour_folder}/{tif_file.name}',
            )
        )

    return HeatSeriesResponse(
        date=date,
        hours=parsed_hours,
        bounds=((min_lng, min_lat), (max_lng, max_lat)),
        items=items,
    )
