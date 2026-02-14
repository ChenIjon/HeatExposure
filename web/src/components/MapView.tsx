import { MutableRefObject, useEffect, useRef, useState } from 'react';
import maplibregl, { GeoJSONSource, LngLatLike, Marker } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

type SelectionPayload = {
  start?: [number, number];
  end?: [number, number] | null;
};

type MapViewProps = {
  start: string;
  end: string;
  planNonce: number;
  showHeatLayer: boolean;
  heatOverlayUrl: string | null;
  heatOverlayBounds: [[number, number], [number, number]] | null;
  onSelectionChange?: (selection: SelectionPayload) => void;
};

const DEFAULT_CENTER: LngLatLike = [121.4737, 31.2304];
const HEAT_SOURCE_ID = 'heat-overlay';
const HEAT_LAYER_ID = 'heat-overlay-layer';

const OSM_RASTER_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: [
        'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
        'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
        'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png'
      ],
      tileSize: 256,
      attribution: '&copy; OpenStreetMap contributors'
    }
  },
  layers: [
    {
      id: 'osm-raster',
      type: 'raster',
      source: 'osm'
    }
  ]
} as const;

const parseLngLat = (rawValue: string): [number, number] | null => {
  const [lngText, latText] = rawValue.split(',').map((value) => value.trim());
  const lng = Number(lngText);
  const lat = Number(latText);

  if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
    return null;
  }

  return [lng, lat];
};

const toImageCoordinates = (bounds: [[number, number], [number, number]]) => {
  const [[minLng, minLat], [maxLng, maxLat]] = bounds;
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
  showHeatLayer,
  heatOverlayUrl,
  heatOverlayBounds,
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
      style: OSM_RASTER_STYLE,
      center: DEFAULT_CENTER,
      zoom: 12
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: '&copy; OpenStreetMap contributors'
      }),
      'bottom-right'
    );

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

      const url = `https://router.project-osrm.org/route/v1/walking/${parsedStart[0]},${parsedStart[1]};${parsedEnd[0]},${parsedEnd[1]}?overview=full&geometries=geojson`;

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
    const map = mapRef.current;
    if (!map || !heatOverlayUrl || !heatOverlayBounds) {
      return;
    }

    const coordinates = toImageCoordinates(heatOverlayBounds);
    const source = map.getSource(HEAT_SOURCE_ID) as maplibregl.ImageSource | undefined;

    if (!source) {
      map.addSource(HEAT_SOURCE_ID, {
        type: 'image',
        url: heatOverlayUrl,
        coordinates
      });
    } else {
      source.updateImage({
        url: heatOverlayUrl,
        coordinates
      });
    }

    if (!map.getLayer(HEAT_LAYER_ID)) {
      map.addLayer({
        id: HEAT_LAYER_ID,
        type: 'raster',
        source: HEAT_SOURCE_ID,
        paint: {
          'raster-opacity': 0.72
        }
      });
    }

    map.setLayoutProperty(HEAT_LAYER_ID, 'visibility', showHeatLayer ? 'visible' : 'none');
    setStatusText('Heat series overlay updated.');
  }, [heatOverlayUrl, heatOverlayBounds, showHeatLayer]);

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

        <aside className="heat-colorbar" aria-label="UTCI discrete colorbar">
          <h3>UTCI (°C)</h3>
          <ul>
            <li>
              <span className="swatch swatch-1" />0-10
            </li>
            <li>
              <span className="swatch swatch-2" />10-20
            </li>
            <li>
              <span className="swatch swatch-3" />20-25
            </li>
            <li>
              <span className="swatch swatch-4" />25-28
            </li>
            <li>
              <span className="swatch swatch-5" />28-31
            </li>
            <li>
              <span className="swatch swatch-6" />31-34
            </li>
            <li>
              <span className="swatch swatch-7" />34-37
            </li>
            <li>
              <span className="swatch swatch-8" />37-40
            </li>
          </ul>
        </aside>
      </div>
      <p className="map-status">{statusText}</p>
    </div>
  );
}

export default MapView;
