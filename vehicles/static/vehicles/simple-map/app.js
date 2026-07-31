const config = window.SIMPLE_MAP_CONFIG || {};
const STADIA_MAPS_API_KEY = config.stadiaApiKey || "";
const VEHICLES_API_URL = config.vehiclesApiUrl || "/vehicles/simple-map-data.json";
const REFRESH_MS = 30000;

const statusEl = document.getElementById("status");
const refreshButton = document.getElementById("refreshButton");

const map = L.map("map", {
  center: [54.5, -3.2],
  zoom: 6,
  minZoom: 5,
  maxZoom: 19,
});

if (STADIA_MAPS_API_KEY) {
  L.tileLayer(
    `https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}{r}.png?api_key=${encodeURIComponent(STADIA_MAPS_API_KEY)}`,
    {
      maxZoom: 20,
      attribution:
        '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> ' +
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    },
  ).addTo(map);
} else {
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
}

const markerLayer = L.layerGroup().addTo(map);
const markers = new Map();

function setStatus(text, isError = false) {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#f85149" : "#8b949e";
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function vehicleIdFromXml(activityNode) {
  const vehicleRef =
    activityNode.querySelector("VehicleRef")?.textContent?.trim() || "";
  const journeyRef =
    activityNode.querySelector("DatedVehicleJourneyRef")?.textContent?.trim() || "";
  return vehicleRef || journeyRef || `unknown-${Math.random().toString(36).slice(2)}`;
}

function parseXmlFeed(xmlText) {
  const parser = new DOMParser();
  const xml = parser.parseFromString(xmlText, "application/xml");
  const parseError = xml.querySelector("parsererror");
  if (parseError) throw new Error("Vehicle feed could not be parsed as XML.");

  const activities = Array.from(xml.querySelectorAll("VehicleActivity"));
  return activities
    .map((activity) => {
      const lon = parseFloat(
        activity.querySelector("Longitude")?.textContent?.trim() || "",
      );
      const lat = parseFloat(
        activity.querySelector("Latitude")?.textContent?.trim() || "",
      );
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

      return {
        id: vehicleIdFromXml(activity),
        lat,
        lon,
        lineRef: activity.querySelector("LineRef")?.textContent?.trim() || "Unknown",
        operatorRef:
          activity.querySelector("OperatorRef")?.textContent?.trim() || "Unknown",
        bearing: activity.querySelector("Bearing")?.textContent?.trim() || "N/A",
        aimedDestinationName:
          activity.querySelector("DestinationName")?.textContent?.trim() || "",
      };
    })
    .filter(Boolean);
}

function normalizeMappedVehicle(item) {
  const coords = item?.coordinates || [];
  const lon = Number(coords[0]);
  const lat = Number(coords[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

  return {
    id: String(item.id || `unknown-${Math.random().toString(36).slice(2)}`),
    lat,
    lon,
    lineRef: item?.service?.line_name || "Unknown",
    operatorRef: item?.vehicle?.operator || "Unknown",
    bearing: item?.heading ?? "N/A",
    aimedDestinationName: item?.destination || "",
  };
}

function parseJsonFeed(json) {
  // Existing site payload: /vehicles.json or /vehicles/simple-map-data.json
  if (Array.isArray(json)) {
    return json.map(normalizeMappedVehicle).filter(Boolean);
  }

  // Raw SIRI JSON payload support
  const activities =
    json?.Siri?.ServiceDelivery?.VehicleMonitoringDelivery?.[0]?.VehicleActivity ||
    json?.siri?.serviceDelivery?.vehicleMonitoringDelivery?.[0]?.vehicleActivity ||
    [];

  return activities
    .map((activity) => {
      const journey = activity?.MonitoredVehicleJourney || activity?.monitoredVehicleJourney;
      const location = journey?.VehicleLocation || journey?.vehicleLocation;
      const lat = Number(location?.Latitude ?? location?.latitude);
      const lon = Number(location?.Longitude ?? location?.longitude);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

      const vehicleRef = journey?.VehicleRef || journey?.vehicleRef || "";
      const datedRef =
        journey?.FramedVehicleJourneyRef?.DatedVehicleJourneyRef ||
        journey?.framedVehicleJourneyRef?.datedVehicleJourneyRef ||
        "";

      return {
        id: vehicleRef || datedRef || `unknown-${Math.random().toString(36).slice(2)}`,
        lat,
        lon,
        lineRef: journey?.LineRef || journey?.lineRef || "Unknown",
        operatorRef: journey?.OperatorRef || journey?.operatorRef || "Unknown",
        bearing:
          journey?.Bearing ||
          journey?.bearing ||
          journey?.VehicleLocation?.Bearing ||
          "N/A",
        aimedDestinationName:
          journey?.DestinationName ||
          journey?.destinationName ||
          journey?.DestinationRef ||
          "",
      };
    })
    .filter(Boolean);
}

async function fetchVehicles() {
  const response = await fetch(VEHICLES_API_URL, {
    headers: {
      Accept: "application/json, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    },
  });

  if (!response.ok) {
    throw new Error(`Vehicle request failed (${response.status})`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const json = await response.json();
    return parseJsonFeed(json);
  }

  const text = await response.text();
  try {
    return parseJsonFeed(JSON.parse(text));
  } catch {
    return parseXmlFeed(text);
  }
}

function popupHtml(vehicle) {
  return `
    <strong>Route:</strong> ${escapeHtml(vehicle.lineRef)}<br />
    <strong>Operator:</strong> ${escapeHtml(vehicle.operatorRef)}<br />
    <strong>Vehicle:</strong> ${escapeHtml(vehicle.id)}<br />
    <strong>Bearing:</strong> ${escapeHtml(vehicle.bearing)}<br />
    <strong>Destination:</strong> ${escapeHtml(vehicle.aimedDestinationName || "Unknown")}
  `;
}

function renderVehicles(vehicles) {
  const seen = new Set();

  for (const vehicle of vehicles) {
    seen.add(vehicle.id);
    const existing = markers.get(vehicle.id);
    if (existing) {
      existing.setLatLng([vehicle.lat, vehicle.lon]);
      existing.setPopupContent(popupHtml(vehicle));
      continue;
    }

    const marker = L.circleMarker([vehicle.lat, vehicle.lon], {
      radius: 5,
      color: "#58a6ff",
      fillColor: "#1f6feb",
      fillOpacity: 0.85,
      weight: 1,
    }).bindPopup(popupHtml(vehicle));

    marker.addTo(markerLayer);
    markers.set(vehicle.id, marker);
  }

  for (const [id, marker] of markers.entries()) {
    if (!seen.has(id)) {
      markerLayer.removeLayer(marker);
      markers.delete(id);
    }
  }
}

let initialFitDone = false;

async function refreshVehicles() {
  setStatus("Loading vehicles...");
  if (refreshButton) refreshButton.disabled = true;
  try {
    const vehicles = await fetchVehicles();
    renderVehicles(vehicles);
    setStatus(
      `Showing ${vehicles.length} live vehicles • Updated ${new Date().toLocaleTimeString()}`,
    );

    if (!initialFitDone && vehicles.length > 0) {
      const bounds = L.latLngBounds(vehicles.map((v) => [v.lat, v.lon]));
      if (bounds.isValid()) map.fitBounds(bounds.pad(0.08));
      initialFitDone = true;
    }
  } catch (error) {
    setStatus(`Error: ${error.message}`, true);
  } finally {
    if (refreshButton) refreshButton.disabled = false;
  }
}

if (refreshButton) {
  refreshButton.addEventListener("click", refreshVehicles);
}

refreshVehicles();
setInterval(refreshVehicles, REFRESH_MS);
