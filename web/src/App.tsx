import { FormEvent, useMemo, useState } from 'react';
import MapView from './components/MapView';
import './styles.css';

type Metrics = {
  total: string;
  peak: string;
  avg: string;
  duration: string;
};

const mockMetrics: Metrics = {
  total: '18.7 km',
  peak: '38.2°C',
  avg: '33.6°C',
  duration: '32 min'
};

const formatLngLat = ([lng, lat]: [number, number]) => `${lng.toFixed(6)},${lat.toFixed(6)}`;

function App() {
  const [startInput, setStartInput] = useState('121.4737,31.2304');
  const [endInput, setEndInput] = useState('121.4998,31.2397');
  const [startCoord, setStartCoord] = useState(startInput);
  const [endCoord, setEndCoord] = useState(endInput);
  const [planNonce, setPlanNonce] = useState(0);
  const [heatRequestNonce, setHeatRequestNonce] = useState(0);
  const [showHeatLayer, setShowHeatLayer] = useState(false);

  const metricCards = useMemo(
    () => [
      { label: 'Total', value: mockMetrics.total },
      { label: 'Peak', value: mockMetrics.peak },
      { label: 'Avg', value: mockMetrics.avg },
      { label: 'Duration', value: mockMetrics.duration }
    ],
    []
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

  const handleLoadHeatLayer = () => {
    setShowHeatLayer(true);
    setHeatRequestNonce((previous) => previous + 1);
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
            <button type="button" onClick={handleLoadHeatLayer}>
              Load heat layer
            </button>
            <button type="button" onClick={() => setShowHeatLayer((value) => !value)}>
              {showHeatLayer ? 'Hide heat layer' : 'Show heat layer'}
            </button>
          </div>

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
            heatRequestNonce={heatRequestNonce}
            showHeatLayer={showHeatLayer}
            onSelectionChange={handleMapSelectionChange}
          />
        </section>
      </main>
    </div>
  );
}

export default App;
