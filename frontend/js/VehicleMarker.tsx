import React, { type ReactElement, memo } from "react";
import { type MapLayerMouseEvent, Marker } from "react-map-gl/maplibre";

export function getClickedVehicleMarkerId(
  e: MapLayerMouseEvent,
): number | undefined {
  // handle click on VehicleMarker element
  const target = e.originalEvent.target;
  if (target instanceof HTMLElement || target instanceof SVGElement) {
    let vehicleId = target.dataset.vehicleId;
    if (!vehicleId && target.parentElement) {
      vehicleId = target.parentElement.dataset.vehicleId;
    }
    if (
      !vehicleId &&
      (target.firstChild instanceof HTMLElement ||
        target.firstChild instanceof SVGElement)
    ) {
      vehicleId = target.firstChild.dataset.vehicleId;
    }
    if (vehicleId) {
      return Number.parseInt(vehicleId, 10);
    }
  }
}

export type Vehicle = {
  id: number;
  journey_id?: number;
  coordinates: [number, number];
  heading?: number;
  datetime: string;
  destination: string;
  block?: string;
  tfl_code?: string;
  trip_id?: number;
  service_id?: number;
  service?: {
    url?: string;
    line_name: string;
  };
  operator?: {
    name: string;
    url?: string;
  };
  vehicle?: {
    url: string;
    name: string;
    fleet_number?: string;
    reg?: string;
    vehicle_type?: string;
    features?: string;
    livery?: number;
    livery_type?: string;
    livery_svg_url?: string;
    colour?: string;
    text_colour?: string;
    css?: string;
    right_css?: string;
  };
  progress?: {
    id: number;
    sequence: number;
    prev_stop: string;
    next_stop: string;
    progress: number;
  };
  delay?: number;
  seats?: string;
  wheelchair?: string;
};

type VehicleMarkerProps = {
  vehicle: Vehicle;
  selected: boolean;
};

function VehicleMarker({ vehicle, selected }: VehicleMarkerProps) {
  let className = "vehicle-marker";

  let rotation = vehicle.heading;

  let background = "";
  if (vehicle.vehicle?.css) {
    background = vehicle.vehicle.css;
  }

  if (rotation != null) {
    if (rotation < 180) {
      rotation -= 90;
      className += " right";
      if (vehicle.vehicle?.right_css) {
        background = vehicle.vehicle.right_css;
      }
    } else {
      rotation -= 270;
    }
  }

  const liveryId = vehicle.vehicle?.livery;

  if (liveryId) {
    className += ` livery-${liveryId}`;
  } else if (background && vehicle.vehicle?.text_colour) {
    className += " white-text";
  }

  if (selected) {
    className += " selected";
  }

  let marker: string | ReactElement = vehicle.service?.line_name || "";

  const isSvgLivery = vehicle.vehicle?.livery_type === 'svg' && vehicle.vehicle?.livery_svg_url;

  if (isSvgLivery) {
    marker = (
      <img
        src={vehicle.vehicle.livery_svg_url}
        alt={marker}
        title={marker}
        width="24"
        height="16"
        data-vehicle-id={vehicle.id}
        style={{ objectFit: 'contain' }}
      />
    );
  } else if (liveryId && liveryId !== 262 && liveryId !== 1502) {
    // not London or Bee Network
    marker = (
      // biome-ignore lint/a11y/noSvgWithoutTitle: not sure what the best title would be
      <svg
        width="24"
        height="16"
        data-vehicle-id={vehicle.id}
        className={className}
      >
        <text x="12" y="12">
          {marker}
        </text>
      </svg>
    );
  } else {
    marker = (
      <div
        data-vehicle-id={vehicle.id}
        className={className}
        style={background ? { background: background } : undefined}
      >
        {marker}
      </div>
    );
  }

  return (
    <Marker
      latitude={vehicle.coordinates[1]}
      longitude={vehicle.coordinates[0]}
      rotation={rotation}
      style={{ zIndex: selected ? 1 : 0 }}
      data-vehicle-id={vehicle.id}
    >
      {marker}
      {rotation == null ? null : (
        <div className="arrow" data-vehicle-id={vehicle.id} />
      )}
    </Marker>
  );
}

function propsAreEqual(prev: VehicleMarkerProps, props: VehicleMarkerProps) {
  const pc = prev.vehicle.coordinates;
  const nc = props.vehicle.coordinates;
  return (
    prev.selected === props.selected &&
    prev.vehicle.datetime === props.vehicle.datetime &&
    pc[0] === nc[0] &&
    pc[1] === nc[1]
  );
}

export default memo(VehicleMarker, propsAreEqual);
