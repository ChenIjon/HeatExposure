import { useEffect, useRef, useState } from 'react';
import maplibregl, { GeoJSONSource, LngLatLike } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

type MapViewProps = {
  start: string;
  end: string;
  planNonce: number;
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

function MapView({ start, end, planNonce }: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [statusText, setStatusText] = useState('Click "Plan route" to request a demo path from OSRM.');

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
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

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
      <div ref={mapContainerRef} className="map-canvas" />
      <p className="map-status">{statusText}</p>
    </div>
  );
}

export default MapView;
