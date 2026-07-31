import React from "react";
import { Marker, Popup } from "react-map-gl/maplibre";
import type { Map as MapLibreMap } from "maplibre-gl";

import BusTimesMap from "./Map";
import { getBounds } from "./utils";

type DepotPoint = {
  address: string;
  coordinates: [number, number];
  group_name?: string;
  group_url?: string;
  name: string;
  notes: string;
  operator_name?: string;
  operator_url?: string;
};

export default function DepotMap({ points }: { points: DepotPoint[] }) {
  const [selectedIndex, setSelectedIndex] = React.useState<number | null>(
    points.length === 1 ? 0 : null,
  );

  const bounds = React.useMemo(
    () => getBounds(points, (point) => point.coordinates),
    [points],
  );

  const initialViewState = React.useMemo(() => {
    if (points.length === 1) {
      return {
        longitude: points[0].coordinates[0],
        latitude: points[0].coordinates[1],
        zoom: 10.5,
      };
    }

    if (bounds) {
      return {
        bounds,
        fitBoundsOptions: {
          maxZoom: 11,
          padding: 48,
        },
      };
    }

    return {
      latitude: 54,
      longitude: -2.9,
      zoom: 5,
    };
  }, [bounds, points]);

  const handleMapInit = React.useCallback(
    (map: MapLibreMap) => {
      if (points.length === 1) {
        map.easeTo({
          center: points[0].coordinates,
          duration: 0,
          zoom: 10.5,
        });
        return;
      }

      if (bounds) {
        map.fitBounds(bounds, { maxZoom: 11, padding: 48 });
      }
    },
    [bounds, points],
  );

  const selectedPoint = selectedIndex === null ? null : points[selectedIndex];

  return (
    <div className="depot-map">
      <BusTimesMap
        initialViewState={initialViewState}
        onClick={() => setSelectedIndex(null)}
        onMapInit={handleMapInit}
      >
        {points.map((point, index) => (
          <Marker
            key={`${point.name}-${point.coordinates.join(",")}-${index}`}
            anchor="bottom"
            latitude={point.coordinates[1]}
            longitude={point.coordinates[0]}
          >
            <button
              aria-label={point.name}
              className={`depot-marker${selectedIndex === index ? " is-selected" : ""}`}
              onClick={(event) => {
                event.stopPropagation();
                setSelectedIndex(index);
              }}
              type="button"
            >
              <span className="depot-marker__dot" />
            </button>
          </Marker>
        ))}
        {selectedPoint ? (
          <Popup
            anchor="top"
            closeOnClick={false}
            latitude={selectedPoint.coordinates[1]}
            longitude={selectedPoint.coordinates[0]}
            onClose={() => setSelectedIndex(null)}
          >
            <strong>{selectedPoint.name}</strong>
            {selectedPoint.operator_name ? (
              <p className="depot-popup__meta">
                {selectedPoint.operator_url ? (
                  <a href={selectedPoint.operator_url}>
                    {selectedPoint.operator_name}
                  </a>
                ) : (
                  selectedPoint.operator_name
                )}
              </p>
            ) : null}
            {selectedPoint.group_name ? (
              <p className="depot-popup__meta">
                {selectedPoint.group_url ? (
                  <a href={selectedPoint.group_url}>{selectedPoint.group_name}</a>
                ) : (
                  selectedPoint.group_name
                )}
              </p>
            ) : null}
            {selectedPoint.address ? <p>{selectedPoint.address}</p> : null}
            {selectedPoint.notes ? <p>{selectedPoint.notes}</p> : null}
          </Popup>
        ) : null}
      </BusTimesMap>
    </div>
  );
}