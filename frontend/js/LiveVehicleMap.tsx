import React from "react";
import type { LngLatBounds, Map as MapLibreMap } from "maplibre-gl";
import type {
  MapLayerMouseEvent,
  ViewStateChangeEvent,
} from "react-map-gl/maplibre";

import BusTimesMap from "./Map";
import { getBounds } from "./utils";
import VehicleMarker, {
  type Vehicle,
  getClickedVehicleMarkerId,
} from "./VehicleMarker";
import VehiclePopup from "./VehiclePopup";

type LiveVehicleMapConfig = {
  apiUrl: string;
  label: string;
};

type LiveVehicleMapResponse = {
  configured: boolean;
  vehicles: Vehicle[];
  error?: string;
};

type LiveVehiclePayload = LiveVehicleMapResponse | Vehicle[];

declare global {
  interface Window {
    LIVERIES_CSS_URL: string;
  }
}

const DEFAULT_VIEW_STATE = {
  latitude: 54,
  longitude: -2.9,
  zoom: 5,
};
const MAX_VEHICLE_AGE_MS = 10 * 60 * 1000;
const BOUNDS_PRECISION = 6;

function roundCoordinate(value: number) {
  return value.toFixed(BOUNDS_PRECISION);
}

function buildBoundsApiUrl(apiUrl: string, bounds?: LngLatBounds) {
  if (!bounds) {
    return apiUrl;
  }

  const url = new URL(apiUrl, window.location.origin);
  url.searchParams.set("ymax", roundCoordinate(bounds.getNorth()));
  url.searchParams.set("xmax", roundCoordinate(bounds.getEast()));
  url.searchParams.set("ymin", roundCoordinate(bounds.getSouth()));
  url.searchParams.set("xmin", roundCoordinate(bounds.getWest()));

  return url.toString();
}

function isFreshVehicle(vehicle: Vehicle) {
  const timestamp = new Date(vehicle.datetime).getTime();
  if (!Number.isFinite(timestamp)) {
    return false;
  }
  return Date.now() - timestamp <= MAX_VEHICLE_AGE_MS;
}

export default function LiveVehicleMap({ apiUrl, label }: LiveVehicleMapConfig) {
  const [data, setData] = React.useState<LiveVehicleMapResponse>();
  const [loading, setLoading] = React.useState(true);
  const [selectedVehicleId, setSelectedVehicleId] = React.useState<number>();
  const [requestUrl, setRequestUrl] = React.useState<string>();
  const mapRef = React.useRef<MapLibreMap | null>(null);
  const hasFittedBounds = React.useRef(false);
  const hasLoadedOnce = React.useRef(false);

  React.useEffect(() => {
    const href = window.LIVERIES_CSS_URL?.trim();
    if (!href) {
      return;
    }

    const existing = document.querySelector(
      `link[rel="stylesheet"][href="${href}"]`,
    );
    if (existing) {
      return;
    }

    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
  }, []);

  const vehicles = data?.vehicles || [];
  const bounds = React.useMemo(
    () => getBounds(vehicles, (vehicle) => vehicle.coordinates),
    [vehicles],
  );

  const normalizePayload = React.useCallback(
    (payload: LiveVehiclePayload): LiveVehicleMapResponse => {
      if (Array.isArray(payload)) {
        return {
          configured: true,
          vehicles: payload,
        };
      }
      return payload;
    },
    [],
  );

  const fitMap = React.useCallback(() => {
    if (!mapRef.current) {
      return;
    }

    if (vehicles.length === 1) {
      mapRef.current.easeTo({
        center: vehicles[0].coordinates,
        duration: 0,
        zoom: 11.5,
      });
      hasFittedBounds.current = true;
      return;
    }

    if (bounds) {
      mapRef.current.fitBounds(bounds, { padding: 48, maxZoom: 11.5 });
      hasFittedBounds.current = true;
    }
  }, [bounds, vehicles]);

  const updateRequestUrl = React.useCallback(() => {
    if (!mapRef.current) {
      return;
    }

    setRequestUrl(buildBoundsApiUrl(apiUrl, mapRef.current.getBounds()));
  }, [apiUrl]);

  React.useEffect(() => {
    let timeout: number;
    let isCancelled = false;

    const loadVehicles = () => {
      if (!requestUrl) {
        return;
      }
      if (document.hidden && hasLoadedOnce.current) {
        timeout = window.setTimeout(loadVehicles, 15000);
        return;
      }

      fetch(requestUrl, { credentials: "omit" })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`Unexpected ${response.status}`);
          }
          return response.json() as Promise<LiveVehiclePayload>;
        })
        .then(
          (payload) => {
            if (isCancelled) {
              return;
            }
            const normalizedPayload = normalizePayload(payload);
            normalizedPayload.vehicles = normalizedPayload.vehicles.filter(
              isFreshVehicle,
            );
            setData(normalizedPayload);
            setLoading(false);
            hasLoadedOnce.current = true;
            setSelectedVehicleId((current) =>
              normalizedPayload.vehicles.some((vehicle) => vehicle.id === current)
                ? current
                : undefined,
            );
            if (!hasFittedBounds.current && normalizedPayload.vehicles.length) {
              window.setTimeout(() => {
                if (mapRef.current) {
                  if (normalizedPayload.vehicles.length === 1) {
                    mapRef.current.easeTo({
                      center: normalizedPayload.vehicles[0].coordinates,
                      duration: 0,
                      zoom: 11.5,
                    });
                    hasFittedBounds.current = true;
                  } else {
                    const nextBounds = getBounds(normalizedPayload.vehicles, (vehicle) => vehicle.coordinates);
                    if (nextBounds) {
                      mapRef.current.fitBounds(nextBounds, { padding: 48, maxZoom: 11.5 });
                      hasFittedBounds.current = true;
                    }
                  }
                }
              }, 0);
            }
            timeout = window.setTimeout(loadVehicles, 15000);
          },
          () => {
            if (isCancelled) {
              return;
            }
            setData({
              configured: true,
              vehicles: [],
              error: "Live vehicle tracking is temporarily unavailable.",
            });
            setLoading(false);
            hasLoadedOnce.current = true;
            timeout = window.setTimeout(loadVehicles, 15000);
          },
        );
    };

    loadVehicles();

    const handleVisibilityChange = () => {
      if (!document.hidden) {
        loadVehicles();
      }
    };

    window.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      isCancelled = true;
      window.removeEventListener("visibilitychange", handleVisibilityChange);
      clearTimeout(timeout);
    };
  }, [normalizePayload, requestUrl]);

  React.useEffect(() => {
    if (!hasFittedBounds.current && vehicles.length) {
      fitMap();
    }
  }, [fitMap, vehicles.length]);

  const handleMapInit = React.useCallback(
    (map: MapLibreMap) => {
      mapRef.current = map;
      updateRequestUrl();
      if (vehicles.length) {
        fitMap();
      }
    },
    [fitMap, updateRequestUrl, vehicles.length],
  );

  const handleMoveEnd = React.useCallback(
    (_event: ViewStateChangeEvent) => {
      updateRequestUrl();
    },
    [updateRequestUrl],
  );

  const handleMapClick = React.useCallback((event: MapLayerMouseEvent) => {
    const clickedVehicleId = getClickedVehicleMarkerId(event);
    if (clickedVehicleId) {
      setSelectedVehicleId(clickedVehicleId);
      return;
    }
    setSelectedVehicleId(undefined);
  }, []);

  const selectedVehicle =
    selectedVehicleId == null
      ? undefined
      : vehicles.find((vehicle) => vehicle.id === selectedVehicleId);

  let statusText = `Tracking ${vehicles.length} vehicle${vehicles.length === 1 ? "" : "s"} for ${label}.`;
  if (loading) {
    statusText = `Loading live vehicle tracking for ${label}.`;
  } else if (!data?.configured) {
    statusText = "Live vehicle tracking is not configured on this page.";
  } else if (data?.error) {
    statusText = data.error;
  } else if (!vehicles.length) {
    statusText = `No vehicles are tracking for ${label} right now.`;
  }

  return (
    <div className="live-vehicle-map">
      <p className="live-vehicle-map__status">{statusText}</p>
      <div className="depot-map live-vehicle-map__canvas">
        <BusTimesMap
          initialViewState={DEFAULT_VIEW_STATE}
          onClick={handleMapClick}
          onMapInit={handleMapInit}
          onMoveEnd={handleMoveEnd}
        >
          {vehicles.map((vehicle) => (
            <VehicleMarker
              key={vehicle.id}
              selected={vehicle.id === selectedVehicleId}
              vehicle={vehicle}
            />
          ))}
          {selectedVehicle ? (
            <VehiclePopup
              item={selectedVehicle}
              onClose={() => setSelectedVehicleId(undefined)}
            />
          ) : null}
        </BusTimesMap>
      </div>
    </div>
  );
}
