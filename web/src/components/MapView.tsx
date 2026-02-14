import { MutableRefObject, useEffect, useRef, useState } from 'react';
import maplibregl, { GeoJSONSource, LngLatLike, Marker } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

type MapViewProps = {
  start: string;
  end: string;
  planNonce: number;
  onSelectionChange?: (selection: { start?: [number, number]; end?: [number, number] }) => void;
};

const DEFAULT_CENTER: LngLatLike = [121.4737, 31.2304];

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

function MapView({ start, end, planNonce, onSelectionChange }: MapViewProps) {
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
        onSelectionChange?.({ start: nextPoint });
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
      </div>
      <p className="map-status">{statusText}</p>
    </div>
  );
}

export default MapView;
