import * as Sentry from "@sentry/react";
import React, { lazy } from "react";
import { createRoot } from "react-dom/client";

import "./maps.css";
import "maplibre-gl/dist/maplibre-gl.css";

import DepotMap from "./DepotMap";
import { ErrorFallback } from "./LoadingSorry";
import BustimesRouteMap from "./BustimesRouteMap";
import LiveVehicleMap from "./LiveVehicleMap";
import RouteEditor from "./RouteEditor";
import ServiceMap from "./ServiceMap";
import BlocksTab from "./BlocksTab";
const History = lazy(() => import("./History"));
const MapRouter = lazy(() => import("./MapRouter"));

if (process.env.NODE_ENV === "production") {
  Sentry.init({
    dsn: "https://0d628b6fff45463bb803d045b99aa542@o55224.ingest.sentry.io/1379883",
    allowUrls: [/https:\/\/bustimes\.org\/static\//],
    ignoreErrors: [
      "'_loaded'",
      "Load failed",
      "AbortError: The user aborted a request.",
      "'this.getContainer().ownerDocument'",
    ],
    integrations: [
      Sentry.globalHandlersIntegration({
        onerror: false,
        onunhandledrejection: false,
      }),
    ],
    release: process.env.KAMAL_CONTAINER_NAME,
  });
}

declare global {
  interface Window {
    SERVICE_ID?: number;
    OPERATOR_ID?: string;
    VEHICLE_ID: number;
    globalThis: Window;
    MAP_DEFAULT_STYLE?: string;
    MAP_STYLE_URL?: string;
    MAP_STYLE_DARK_URL?: string;
    STADIA_MAPS_API_KEY?: string;
    TRAINS_JSON_URL?: string;
    BLOCKS_TAB_PROPS?: {
      operatorNoc: string;
      date: string;
    };
  }
}

if (typeof window.globalThis === "undefined") {
  window.globalThis = window;
}

type LiveVehicleMapConfig = {
  apiUrl: string;
  label: string;
};

type BustimesRouteMapConfig = {
  pageUrl: string;
  label?: string;
};

const createRootOptions = {
  onUncaughtError: Sentry.reactErrorHandler((error, errorInfo) => {
    console.warn("Uncaught error", error, errorInfo.componentStack);
  }),
  onCaughtError: Sentry.reactErrorHandler(),
  onRecoverableError: Sentry.reactErrorHandler(),
};

let rootElement: HTMLElement | null;
if ((rootElement = document.getElementById("history"))) {
  const root = createRoot(rootElement, createRootOptions);
  root.render(
    <React.StrictMode>
      <Sentry.ErrorBoundary fallback={ErrorFallback}>
        <History />
      </Sentry.ErrorBoundary>
    </React.StrictMode>,
  );
} else if (
  window.SERVICE_ID &&
  (rootElement = document.getElementById("map-link"))
) {
  const root = createRoot(rootElement, createRootOptions);
  root.render(
    <React.StrictMode>
      <Sentry.ErrorBoundary fallback={ErrorFallback}>
        <ServiceMap
          serviceId={window.SERVICE_ID}
          buttonText={rootElement.innerText}
        />
      </Sentry.ErrorBoundary>
    </React.StrictMode>,
  );
} else if ((rootElement = document.getElementById("depot-map-root"))) {
  const dataElement = document.getElementById("depot-map-data");
  if (dataElement?.textContent) {
    const root = createRoot(rootElement, createRootOptions);
    root.render(
      <React.StrictMode>
        <Sentry.ErrorBoundary fallback={ErrorFallback}>
          <DepotMap points={JSON.parse(dataElement.textContent)} />
        </Sentry.ErrorBoundary>
      </React.StrictMode>,
    );
  }
} else if ((rootElement = document.getElementById("live-vehicle-map-root"))) {
  const dataElement = document.getElementById("live-vehicle-map-data");
  if (dataElement?.textContent) {
    const root = createRoot(rootElement, createRootOptions);
    root.render(
      <React.StrictMode>
        <Sentry.ErrorBoundary fallback={ErrorFallback}>
          <LiveVehicleMap
            {...(JSON.parse(dataElement.textContent) as LiveVehicleMapConfig)}
          />
        </Sentry.ErrorBoundary>
      </React.StrictMode>,
    );
  }
} else if ((rootElement = document.getElementById("bustimes-route-map-root"))) {
  const dataElement = document.getElementById("bustimes-route-map-data");
  if (dataElement?.textContent) {
    const root = createRoot(rootElement, createRootOptions);
    root.render(
      <React.StrictMode>
        <Sentry.ErrorBoundary fallback={ErrorFallback}>
          <BustimesRouteMap
            {...(JSON.parse(dataElement.textContent) as BustimesRouteMapConfig)}
          />
        </Sentry.ErrorBoundary>
      </React.StrictMode>,
    );
  }
} else if ((rootElement = document.getElementById("route-editor-root"))) {
  const dataElement = document.getElementById("route-editor-data");
  const initialServiceId = dataElement?.textContent
    ? (JSON.parse(dataElement.textContent) as number | null)
    : undefined;
  const root = createRoot(rootElement, createRootOptions);
  root.render(
    <React.StrictMode>
      <Sentry.ErrorBoundary fallback={ErrorFallback}>
        <RouteEditor initialServiceId={initialServiceId || undefined} />
      </Sentry.ErrorBoundary>
    </React.StrictMode>,
  );
} else if ((rootElement = document.getElementById("hugemap"))) {
  const root = createRoot(rootElement, createRootOptions);
  root.render(
    <React.StrictMode>
      <Sentry.ErrorBoundary fallback={ErrorFallback}>
        <MapRouter />
      </Sentry.ErrorBoundary>
    </React.StrictMode>,
  );
} else if ((rootElement = document.getElementById("blocks-tab-root"))) {
  if (window.BLOCKS_TAB_PROPS) {
    const root = createRoot(rootElement, createRootOptions);
    root.render(
      <React.StrictMode>
        <Sentry.ErrorBoundary fallback={ErrorFallback}>
          <BlocksTab {...window.BLOCKS_TAB_PROPS} />
        </Sentry.ErrorBoundary>
      </React.StrictMode>,
    );
  }
}
