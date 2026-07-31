import React from "react";

import ServiceMapMap from "./ServiceMapMap";
import { getBounds } from "./utils";

type BustimesRouteMapConfig = {
  pageUrl: string;
  label?: string;
};

type RouteGeometryResponse = {
  stops?: GeoJSON.FeatureCollection;
  geometry?: GeoJSON.LineString | GeoJSON.MultiLineString;
};

function getServiceIdFromHtml(html: string) {
  const match = html.match(/SERVICE_ID\s*=\s*(\d+)\s*;/);
  return match ? Number.parseInt(match[1], 10) : undefined;
}

async function loadRouteGeometryFromPageUrl(pageUrl: string) {
  const page = new URL(pageUrl);
  page.hash = "";

  const html = await fetch(page.toString(), { credentials: "omit" }).then((response) => {
    if (!response.ok) {
      throw new Error(`Unexpected ${response.status} loading page HTML`);
    }
    return response.text();
  });

  const serviceId = getServiceIdFromHtml(html);
  if (!serviceId) {
    throw new Error("Could not find SERVICE_ID in page HTML");
  }

  const geometryUrl = `${page.origin}/services/${serviceId}.json`;
  const data = await fetch(geometryUrl, { credentials: "omit" }).then((response) => {
    if (!response.ok) {
      throw new Error(`Unexpected ${response.status} loading route geometry`);
    }
    return response.json() as Promise<RouteGeometryResponse>;
  });

  return {
    serviceId,
    geometryUrl,
    data,
  };
}

export default function BustimesRouteMap({
  pageUrl,
  label,
}: BustimesRouteMapConfig) {
  const [serviceId, setServiceId] = React.useState<number>();
  const [stopsAndGeometry, setStopsAndGeometry] = React.useState<
    Record<number, RouteGeometryResponse>
  >({});
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string>();

  React.useEffect(() => {
    let isCancelled = false;

    setLoading(true);
    setError(undefined);
    setServiceId(undefined);
    setStopsAndGeometry({});

    loadRouteGeometryFromPageUrl(pageUrl).then(
      (result) => {
        if (isCancelled) {
          return;
        }
        setServiceId(result.serviceId);
        setStopsAndGeometry({ [result.serviceId]: result.data });
        setLoading(false);
      },
      (err: unknown) => {
        if (isCancelled) {
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load route map.");
        setLoading(false);
      },
    );

    return () => {
      isCancelled = true;
    };
  }, [pageUrl]);

  const features = React.useMemo(
    () => (serviceId ? stopsAndGeometry[serviceId]?.stops?.features || [] : []),
    [serviceId, stopsAndGeometry],
  );

  const bounds = React.useMemo(
    () =>
      getBounds(features, (feature) =>
        feature.geometry?.type === "Point"
          ? (feature.geometry.coordinates as [number, number])
          : undefined,
      ),
    [features],
  );

  React.useEffect(() => {
    if (bounds) {
      window.EXTENT = [
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth(),
      ];
    }
  }, [bounds]);

  const mapLabel = label || pageUrl;
  let statusText = `Loading route geometry for ${mapLabel}.`;
  if (!loading && error) {
    statusText = error;
  } else if (!loading && serviceId) {
    statusText = `Loaded route geometry for service ${serviceId}.`;
  }

  return (
    <div className="live-vehicle-map">
      <p className="live-vehicle-map__status">{statusText}</p>
      <div className="depot-map live-vehicle-map__canvas">
        {serviceId && bounds ? (
          <ServiceMapMap
            serviceIds={new Set([serviceId])}
            stopsAndGeometry={stopsAndGeometry}
          />
        ) : null}
      </div>
    </div>
  );
}
