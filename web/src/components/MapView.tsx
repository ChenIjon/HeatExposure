import { MutableRefObject, useEffect, useRef, useState } from 'react';
import maplibregl, { GeoJSONSource, LngLatLike, Marker } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

type SelectionPayload = {
  start?: [number, number];
  end?: [number, number] | null;
};

type HeatResponse = {
  date: string;
  hour: number;
  bbox: [number, number, number, number];
  tif_path: string;
  png_path: string;
  bounds: [[number, number], [number, number]];
};

type MapViewProps = {
  start: string;
  end: string;
  planNonce: number;
  heatRequestNonce: number;
  showHeatLayer: boolean;
  onSelectionChange?: (selection: SelectionPayload) => void;
};

const DEFAULT_CENTER: LngLatLike = [121.4737, 31.2304];
const HEAT_SOURCE_ID = 'heat-overlay';
const HEAT_LAYER_ID = 'heat-overlay-layer';

const parseLngLat = (rawValue: string): [number, number] | null => {
  const [lngText, latText] = rawValue.split(',').map((value) => value.trim());
  const lng = Number(lngText);
  const lat = Number(latText);

  if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
    return null;
  }

  return [lng, lat];
};

const formatLngLat = (coords: [number, number] | null) =>
  coords ? `${coords[0].toFixed(6)}, ${coords[1].toFixed(6)}` : '--';

const getBboxFromMap = (map: maplibregl.Map): [number, number, number, number] => {
  const bounds = map.getBounds();
  return [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];
};

const requestHeatMap = async (params: {
  date: string;
  hour: number;
  bbox: [number, number, number, number];
}): Promise<HeatResponse> => {
  const { date, hour, bbox } = params;
  const query = new URLSearchParams({
    date,
    hour: String(hour),
    bbox: bbox.map((value) => value.toFixed(6)).join(',')
  });

  // TODO: replace this with real heat exposure calculation API; keep response schema.
  const response = await fetch(`/api/heat/mock?${query.toString()}`);
  if (!response.ok) {
    throw new Error('Failed to request heat layer.');
  }

  return (await response.json()) as HeatResponse;
};

const toImageCoordinates = (bbox: [number, number, number, number]) => {
  const [minLng, minLat, maxLng, maxLat] = bbox;
  return [
    [minLng, maxLat],
    [maxLng, maxLat],
    [maxLng, minLat],
    [minLng, minLat]
  ] as [[number, number], [number, number], [number, number], [number, number]];
};

function MapView({
  start,
  end,
  planNonce,
  heatRequestNonce,
  showHeatLayer,
  onSelectionChange
}: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const startMarkerRef = useRef<Marker | null>(null);
  const endMarkerRef = useRef<Marker | null>(null);
  const startSelectionRef = useRef<[number, number] | null>(null);
  const endSelectionRef = useRef<[number, number] | null>(null);

  const [selectedStart, setSelectedStart] = useState<[number, number] | null>(parseLngLat(start));
  const [selectedEnd, setSelectedEnd] = useState<[number, number] | null>(parseLngLat(end));
  const [statusText, setStatusText] = useState('Click map to pick Start and End points, then press "Plan route".');

  const updateMarker = (
    markerRef: MutableRefObject<Marker | null>,
    map: maplibregl.Map,
    coords: [number, number] | null,
    color: string
  ) => {
    if (!coords) {
      markerRef.current?.remove();
      markerRef.current = null;
      return;
    }

    if (!markerRef.current) {
      markerRef.current = new maplibregl.Marker({ color }).setLngLat(coords).addTo(map);
      return;
    }

    markerRef.current.setLngLat(coords);
  };

  useEffect(() => {
    startSelectionRef.current = selectedStart;
    endSelectionRef.current = selectedEnd;
  }, [selectedStart, selectedEnd]);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: 'https://demotiles.maplibre.org/style.json',
      center: DEFAULT_CENTER,
      zoom: 12
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    map.on('load', () => {
      map.addSource('route', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: []
        }
      });

      map.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'route',
        paint: {
          'line-color': '#f97316',
          'line-width': 5
        }
      });

      updateMarker(startMarkerRef, map, startSelectionRef.current, '#16a34a');
      updateMarker(endMarkerRef, map, endSelectionRef.current, '#dc2626');
    });

    map.on('click', (event) => {
      const nextPoint: [number, number] = [event.lngLat.lng, event.lngLat.lat];

      if (!startSelectionRef.current || endSelectionRef.current) {
        setSelectedStart(nextPoint);
        setSelectedEnd(null);
        onSelectionChange?.({ start: nextPoint, end: null });
        setStatusText('Start point selected. Click again to set End point.');
        return;
      }

      setSelectedEnd(nextPoint);
      onSelectionChange?.({ end: nextPoint });
      setStatusText('End point selected. Press "Plan route" to fetch route.');
    });

    mapRef.current = map;

    return () => {
      startMarkerRef.current?.remove();
      endMarkerRef.current?.remove();
      map.remove();
      mapRef.current = null;
      startMarkerRef.current = null;
      endMarkerRef.current = null;
    };
  }, [onSelectionChange]);

  useEffect(() => {
    const nextStart = parseLngLat(start);
    const nextEnd = parseLngLat(end);
    setSelectedStart(nextStart);
    setSelectedEnd(nextEnd);
  }, [start, end]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }

    updateMarker(startMarkerRef, map, selectedStart, '#16a34a');
    updateMarker(endMarkerRef, map, selectedEnd, '#dc2626');

    if (!selectedStart || !selectedEnd) {
      const source = map.getSource('route') as GeoJSONSource | undefined;
      source?.setData({
        type: 'FeatureCollection',
        features: []
      });
    }
  }, [selectedStart, selectedEnd]);

  useEffect(() => {
    if (planNonce === 0) {
      return;
    }

    const map = mapRef.current;
    const parsedStart = parseLngLat(start);
    const parsedEnd = parseLngLat(end);

    if (!map || !parsedStart || !parsedEnd) {
      setStatusText('Invalid coordinate format. Use lng,lat (example: 121.4737,31.2304).');
      return;
    }

    const fetchRoute = async () => {
      setStatusText('Planning route...');

      const url = `https://router.project-osrm.org/route/v1/driving/${parsedStart[0]},${parsedStart[1]};${parsedEnd[0]},${parsedEnd[1]}?overview=full&geometries=geojson`;

      try {
        const response = await fetch(url);
        const payload = await response.json();
        const geometry = payload?.routes?.[0]?.geometry;

        if (!geometry) {
          setStatusText('No route returned by OSRM API.');
          return;
        }

        const source = map.getSource('route') as GeoJSONSource | undefined;
        source?.setData({
          type: 'Feature',
          properties: {},
          geometry
        });

        map.fitBounds([parsedStart, parsedEnd], { padding: 80, duration: 800 });
        setStatusText('Route loaded (OSRM demo).');
      } catch (_error) {
        setStatusText('Failed to fetch route from OSRM API.');
      }
    };

    void fetchRoute();
  }, [start, end, planNonce]);

  useEffect(() => {
    if (heatRequestNonce === 0) {
      return;
    }

    const map = mapRef.current;
    if (!map) {
      return;
    }

    const fetchHeatLayer = async () => {
      const bbox = getBboxFromMap(map);
      setStatusText('Loading mock heat layer...');

      try {
        const payload = await requestHeatMap({
          date: '2026-02-14',
          hour: 13,
          bbox
        });

        const rasterCoordinates = toImageCoordinates(payload.bbox);
        const pngUrl = payload.png_path.startsWith('/') ? payload.png_path : `/${payload.png_path}`;

        const existingSource = map.getSource(HEAT_SOURCE_ID) as maplibregl.ImageSource | undefined;
        if (existingSource) {
          existingSource.updateImage({
            url: pngUrl,
            coordinates: rasterCoordinates
          });
        } else {
          map.addSource(HEAT_SOURCE_ID, {
            type: 'image',
            url: pngUrl,
            coordinates: rasterCoordinates
          });

          map.addLayer({
            id: HEAT_LAYER_ID,
            type: 'raster',
            source: HEAT_SOURCE_ID,
            paint: {
              'raster-opacity': 0.72
            }
          });
        }

        if (map.getLayer(HEAT_LAYER_ID)) {
          map.setLayoutProperty(HEAT_LAYER_ID, 'visibility', showHeatLayer ? 'visible' : 'none');
        }

        setStatusText(`Heat layer loaded: ${payload.date} ${payload.hour}:00`);
      } catch (_error) {
        setStatusText('Failed to load mock heat layer.');
      }
    };

    void fetchHeatLayer();
  }, [heatRequestNonce, showHeatLayer]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer(HEAT_LAYER_ID)) {
      return;
    }

    map.setLayoutProperty(HEAT_LAYER_ID, 'visibility', showHeatLayer ? 'visible' : 'none');
  }, [showHeatLayer]);

  return (
    <div className="map-wrapper">
      <div className="map-canvas-wrap">
        <div ref={mapContainerRef} className="map-canvas" />
        <div className="coord-overlay" aria-live="polite">
          <p>
            <strong>Start:</strong> {formatLngLat(selectedStart)}
          </p>
          <p>
            <strong>End:</strong> {formatLngLat(selectedEnd)}
          </p>
        </div>
        <div className="heat-legend" aria-label="heat legend">
          <div className="heat-legend__title">Heat exposure (mock)</div>
          <div className="heat-legend__bar" />
          <div className="heat-legend__labels">
            <span>0</span>
            <span>1</span>
          </div>
        </div>
      </div>
      <p className="map-status">{statusText}</p>
    </div>
  );
}

export default MapView;
