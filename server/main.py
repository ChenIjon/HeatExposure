from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Tuple

import matplotlib.cm as cm
import matplotlib.pyplot as plt
import numpy as np
import tifffile
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT_DIR / 'server' / 'results'

app = FastAPI(title='HeatExposure Mock API')
app.mount('/results', StaticFiles(directory=RESULTS_DIR), name='results')


class HeatMockResponse(BaseModel):
    date: str
    hour: int
    bbox: Tuple[float, float, float, float]
    tif_path: str
    png_path: str
    bounds: Tuple[Tuple[float, float], Tuple[float, float]]


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


def _stable_seed(date: str, hour: int, bbox: Tuple[float, float, float, float]) -> int:
    bbox_text = ','.join(f'{value:.6f}' for value in bbox)
    token = f'{date}-{hour}-{bbox_text}'
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
    min_lng, min_lat, max_lng, max_lat = bbox
    height, width = heat.shape
    pixel_width = (max_lng - min_lng) / float(width)
    pixel_height = (max_lat - min_lat) / float(height)

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


def _write_overlay_png(heat: np.ndarray, path: Path) -> None:
    jet = cm.get_cmap('jet')
    rgba = jet(heat)
    rgba[..., 3] = 0.75
    plt.imsave(path, rgba)


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
    seed = _stable_seed(date, hour, parsed_bbox)
    heat = _mock_heat_array(seed=seed)

    date_folder = date.replace('-', '')
    hour_folder = f'{hour:02d}'
    output_dir = RESULTS_DIR / date_folder / hour_folder
    output_dir.mkdir(parents=True, exist_ok=True)

    tif_file = output_dir / 'heat_exposure.tif'
    png_file = output_dir / 'heat_exposure.png'

    _write_geotiff(heat, tif_file, parsed_bbox)
    _write_overlay_png(heat, png_file)

    min_lng, min_lat, max_lng, max_lat = parsed_bbox
    return HeatMockResponse(
        date=date,
        hour=hour,
        bbox=parsed_bbox,
        tif_path=f'/results/{date_folder}/{hour_folder}/{tif_file.name}',
        png_path=f'/results/{date_folder}/{hour_folder}/{png_file.name}',
        bounds=((min_lng, min_lat), (max_lng, max_lat)),
    )
