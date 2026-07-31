const DEFAULT_COLOUR = "#2d6a9f";
const DEFAULT_TEXT_COLOUR = "#ffffff";

function trimSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function toAbsoluteUrl(base, path) {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  const root = trimSlash(base);
  return root ? `${root}${path.startsWith("/") ? "" : "/"}${path}` : path;
}

function extractResults(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.results)) return payload.results;
  return [];
}

export class VehicleEnricher {
  constructor({
    vehiclesApiUrl = "",
    vehicleUrlBase = "",
    cacheTtlMs = 300_000,
  } = {}) {
    this.vehiclesApiUrl = vehiclesApiUrl;
    this.vehicleUrlBase = vehicleUrlBase;
    this.cacheTtlMs = cacheTtlMs;
    this.cache = new Map();
  }

  async lookup(fleetNumber) {
    const fleetCode = String(fleetNumber || "").trim();
    if (!fleetCode || !this.vehiclesApiUrl) return null;

    const cached = this.cache.get(fleetCode);
    if (cached && Date.now() - cached.at < this.cacheTtlMs) return cached.value;

    const url = new URL(this.vehiclesApiUrl);
    url.searchParams.set("search", fleetCode);
    url.searchParams.set("limit", "5");

    try {
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(`vehicle API HTTP ${res.status}`);
      const vehicles = extractResults(await res.json());
      const vehicle =
        vehicles.find((v) => String(v.fleet_number || "") === fleetCode) ||
        vehicles.find((v) => String(v.fleet_code || "") === fleetCode) ||
        vehicles[0] ||
        null;
      const value = vehicle ? this.formatVehicle(vehicle) : null;
      this.cache.set(fleetCode, { at: Date.now(), value });
      return value;
    } catch (e) {
      console.error(`vehicle lookup failed for ${fleetCode}: ${e.message}`);
      this.cache.set(fleetCode, { at: Date.now(), value: null });
      return null;
    }
  }

  formatVehicle(vehicle) {
    const livery = vehicle.livery || {};
    const vehicleType = vehicle.vehicle_type?.name || vehicle.vehicle_type?.style || "";
    const features = [
      vehicleType,
      ...(Array.isArray(vehicle.special_features) ? vehicle.special_features : []),
    ]
      .filter(Boolean)
      .join("<br>");

    return {
      url: toAbsoluteUrl(this.vehicleUrlBase, vehicle.slug ? `/vehicles/${vehicle.slug}` : ""),
      name: String(vehicle.name || vehicle.fleet_code || vehicle.fleet_number || ""),
      fleet_number:
        vehicle.fleet_number != null
          ? String(vehicle.fleet_number)
          : String(vehicle.fleet_code || ""),
      reg: vehicle.reg || "",
      vehicle_type: vehicleType,
      features,
      livery: livery.id || null,
      colour: DEFAULT_COLOUR,
      text_colour: DEFAULT_TEXT_COLOUR,
      css: livery.left || DEFAULT_COLOUR,
      right_css: livery.right || livery.left || DEFAULT_COLOUR,
    };
  }

  fallbackVehicle(fleetNumber) {
    const fleetCode = String(fleetNumber || "").trim();
    return {
      url: "",
      name: fleetCode || "Train",
      fleet_number: fleetCode,
      reg: "",
      vehicle_type: "",
      features: "",
      livery: null,
      colour: DEFAULT_COLOUR,
      text_colour: DEFAULT_TEXT_COLOUR,
      css: DEFAULT_COLOUR,
      right_css: DEFAULT_COLOUR,
    };
  }
}
