import { FormEvent, useMemo, useState } from 'react';
import MapView from './components/MapView';
import './styles.css';

type Metrics = {
  total: string;
  peak: string;
  avg: string;
  duration: string;
};

type HeatSeriesItem = {
  hour: number;
  tiles: {
    row: number;
    col: number;
    png_url: string;
    tif_url: string;
    bounds: [[number, number], [number, number]];
  }[];
};

type HeatSeriesResponse = {
  date: string;
  hours: number[];
  bounds: [[number, number], [number, number]];
  items: HeatSeriesItem[];
  route_tiles: [number, number][];
};

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/$/, '');

const mockMetrics: Metrics = {
  total: '18.7 km',
  peak: '38.2°C',
  avg: '33.6°C',
  duration: '32 min'
};

const formatLngLat = ([lng, lat]: [number, number]) => `${lng.toFixed(6)},${lat.toFixed(6)}`;

const parseLngLat = (rawValue: string): [number, number] | null => {
  const [lngText, latText] = rawValue.split(',').map((value) => value.trim());
  const lng = Number(lngText);
  const lat = Number(latText);

  if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
    return null;
  }

  return [lng, lat];
};

const resolveApiUrl = (path: string): string => {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }

  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return API_BASE_URL ? `${API_BASE_URL}${normalizedPath}` : normalizedPath;
};

async function requestHeatSeries(params: {
  date: string;
  start: string;
  end: string;
  startHour: number;
  nHours: number;
  profile: 'walking' | 'driving' | 'running';
}): Promise<HeatSeriesResponse> {
  const query = new URLSearchParams({
    date: params.date,
    start: params.start,
    end: params.end,
    start_hour: String(params.startHour),
    n_hours: String(params.nHours),
    profile: params.profile
  });

  const response = await fetch(resolveApiUrl(`/api/heat/mock/series?${query.toString()}`));
  if (!response.ok) {
    throw new Error('API unreachable / CORS blocked');
  }

  return (await response.json()) as HeatSeriesResponse;
}

function App() {
  const [startInput, setStartInput] = useState('114.1550,22.2760');
  const [endInput, setEndInput] = useState('114.1880,22.2480');
  const [startCoord, setStartCoord] = useState(startInput);
  const [endCoord, setEndCoord] = useState(endInput);
  const [planNonce, setPlanNonce] = useState(0);
  const [showHeatLayer, setShowHeatLayer] = useState(false);
  const [isHeatSeriesLoading, setIsHeatSeriesLoading] = useState(false);
  const [heatLayerError, setHeatLayerError] = useState<string | null>(null);

  const [heatSeries, setHeatSeries] = useState<HeatSeriesResponse | null>(null);
  const [selectedHour, setSelectedHour] = useState<number | null>(null);

  const metricCards = useMemo(
    () => [
      { label: 'Total', value: mockMetrics.total },
      { label: 'Peak', value: mockMetrics.peak },
      { label: 'Avg', value: mockMetrics.avg },
      { label: 'Duration', value: mockMetrics.duration }
    ],
    []
  );

  const themeSwatches = useMemo(
    () => [
      { name: 'Primary Orange', hex: '#FFA76E', usage: 'Primary actions, highlighted route, focus accents' },
      { name: 'Soft Sky Blue', hex: '#AEDFF7', usage: 'Data overlays, cool-state controls, charts' },
      { name: 'Warm White', hex: '#FFF9F2', usage: 'Main panel backgrounds and cards' },
      { name: 'Mist Gray', hex: '#EEF2F4', usage: 'Page background and section separation' },
      { name: 'Silver Gray', hex: '#C5CED6', usage: 'Borders, dividers, subtle line work' },
      { name: 'Ink Slate', hex: '#2F3A45', usage: 'Body text, labels, high-contrast UI copy' }
    ],
    []
  );

  const selectedHeatItem = useMemo(() => {
    if (!heatSeries || selectedHour === null) {
      return null;
    }

    return heatSeries.items.find((item) => item.hour === selectedHour) ?? null;
  }, [heatSeries, selectedHour]);

  const selectedHeatOverlays = useMemo(
    () =>
      selectedHeatItem?.tiles.map((tile) => ({
        row: tile.row,
        col: tile.col,
        url: resolveApiUrl(tile.png_url),
        bounds: tile.bounds
      })) ?? [],
    [selectedHeatItem]
  );

  const handlePlanRoute = (event: FormEvent) => {
    event.preventDefault();
    setStartCoord(startInput.trim());
    setEndCoord(endInput.trim());
    setPlanNonce((previous) => previous + 1);
  };

  const handleMapSelectionChange = (selection: {
    start?: [number, number];
    end?: [number, number] | null;
  }) => {
    if (selection.start) {
      const nextStart = formatLngLat(selection.start);
      setStartInput(nextStart);
      setStartCoord(nextStart);
    }

    if (selection.end === null) {
      setEndInput('');
      setEndCoord('');
    }

    if (selection.end) {
      const nextEnd = formatLngLat(selection.end);
      setEndInput(nextEnd);
      setEndCoord(nextEnd);
    }
  };

  const loadHeatSeries = async () => {
    const parsedStart = parseLngLat(startCoord.trim());
    const parsedEnd = parseLngLat(endCoord.trim());

    if (!parsedStart || !parsedEnd) {
      setHeatLayerError('Start/End format invalid. Use lng,lat.');
      return;
    }

    setHeatLayerError(null);
    setIsHeatSeriesLoading(true);

    try {
      const response = await requestHeatSeries({
        date: '2026-02-14',
        start: `${parsedStart[0]},${parsedStart[1]}`,
        end: `${parsedEnd[0]},${parsedEnd[1]}`,
        startHour: 13,
        nHours: 6,
        profile: 'walking'
      });

      setHeatSeries(response);
      setSelectedHour(response.hours[0] ?? null);
      return true;
    } catch (_error) {
      setHeatLayerError('API unreachable / CORS blocked');
      return false;
    } finally {
      setIsHeatSeriesLoading(false);
    }
  };

  const handleHeatConditionToggle = async () => {
    if (showHeatLayer) {
      setShowHeatLayer(false);
      return;
    }

    if (!heatSeries) {
      const loaded = await loadHeatSeries();
      if (!loaded) {
        return;
      }
    }

    setShowHeatLayer(true);
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>HeatExposure</h1>
        <p>Base route planning skeleton for exposure analysis.</p>
      </header>

      <main className="app-main">
        <section className="panel" aria-label="route planner panel">
          <h2>Route Planner</h2>
          <form onSubmit={handlePlanRoute} className="route-form">
            <label htmlFor="start-input">Start (lng,lat)</label>
            <input
              id="start-input"
              value={startInput}
              onChange={(event) => setStartInput(event.target.value)}
              placeholder="121.4737,31.2304"
            />

            <label htmlFor="end-input">End (lng,lat)</label>
            <input
              id="end-input"
              value={endInput}
              onChange={(event) => setEndInput(event.target.value)}
              placeholder="121.4998,31.2397"
            />

            <button type="submit">Plan route</button>
          </form>

          <div className="layer-actions">
            <button
              type="button"
              className={`heat-toggle-btn ${showHeatLayer ? 'is-on' : 'is-off'}`}
              onClick={() => {
                void handleHeatConditionToggle();
              }}
              disabled={isHeatSeriesLoading}
            >
              {isHeatSeriesLoading
                ? 'Loading heat condition...'
                : showHeatLayer
                  ? 'Show heat condition'
                  : 'Hide heat condition'}
            </button>
          </div>

          <label htmlFor="hour-select" className="hour-select-label">
            Hour
          </label>
          <select
            id="hour-select"
            className="hour-select"
            value={selectedHour ?? ''}
            onChange={(event) => {
              const value = Number(event.target.value);
              setSelectedHour(Number.isFinite(value) ? value : null);
            }}
            disabled={!heatSeries}
          >
            {!heatSeries && <option value="">Enable heat condition first</option>}
            {heatSeries?.hours.map((hour) => (
              <option key={hour} value={hour}>
                {hour}:00
              </option>
            ))}
          </select>

          {heatLayerError && <p className="panel-error">{heatLayerError}</p>}

          <div className="metrics-grid">
            {metricCards.map((metric) => (
              <article key={metric.label} className="metric-card">
                <span>{metric.label}</span>
                <strong>{metric.value}</strong>
              </article>
            ))}
          </div>

        </section>

        <section className="map-section" aria-label="map area">
          <MapView
            start={startCoord}
            end={endCoord}
            planNonce={planNonce}
            showHeatLayer={showHeatLayer}
            heatOverlays={selectedHeatOverlays}
            onSelectionChange={handleMapSelectionChange}
          />
        </section>
      </main>
    </div>
  );
}

export default App;
