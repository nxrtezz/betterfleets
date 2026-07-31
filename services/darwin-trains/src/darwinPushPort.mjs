import { createHash } from "node:crypto";
import { Kafka, logLevel } from "kafkajs";
import { coordForLocation } from "./gtfs.mjs";
import { VehicleEnricher } from "./vehicleEnrichment.mjs";

function stableNumericId(value) {
  const h = createHash("sha256").update(String(value)).digest();
  return h.readUInt32BE(0) & 0x7fffffff;
}

function compact(value) {
  if (value == null) return "";
  return String(value).trim();
}

function asArray(value) {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

function numberOrNull(value) {
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : null;
}

function walk(value, visit) {
  if (value == null) return;
  if (Array.isArray(value)) {
    for (const item of value) walk(item, visit);
    return;
  }
  if (typeof value !== "object") return;
  visit(value);
  for (const child of Object.values(value)) walk(child, visit);
}

function findFirst(payload, names) {
  const wanted = new Set(names.map((n) => n.toLowerCase()));
  let found = "";
  walk(payload, (obj) => {
    if (found) return;
    for (const [key, value] of Object.entries(obj)) {
      if (!wanted.has(key.toLowerCase())) continue;
      const text = compact(value);
      if (text) {
        found = text;
        return;
      }
    }
  });
  return found;
}

function extractFleetNumber(payload) {
  const direct = findFirst(payload, [
    "fleet_number",
    "fleetNumber",
    "unit",
    "unitNumber",
    "trainNumber",
    "train_number",
    "vehicleRef",
    "vehicle_ref",
  ]);
  const match = direct.match(/\b\d{5,6}\b/);
  if (match) return match[0];

  const rid = findFirst(payload, ["rid", "rsid", "trainId", "train_id", "uid"]);
  return rid.match(/\b\d{5,6}\b/)?.[0] || "";
}

function extractCoordinates(payload) {
  let coordinates = null;
  walk(payload, (obj) => {
    if (coordinates) return;
    const lon =
      numberOrNull(obj.lon) ??
      numberOrNull(obj.lng) ??
      numberOrNull(obj.longitude) ??
      numberOrNull(obj.Longitude);
    const lat =
      numberOrNull(obj.lat) ??
      numberOrNull(obj.latitude) ??
      numberOrNull(obj.Latitude);
    if (lat != null && lon != null) coordinates = [lon, lat];
  });
  return coordinates;
}

function extractLocationCode(payload) {
  return findFirst(payload, [
    "crs",
    "CRS",
    "locationCrs",
    "location_crs",
    "tpl",
    "tiploc",
    "TIPLOC",
    "location",
    "location_code",
  ]).toUpperCase();
}

function extractStops(payload) {
  const stops = [];
  walk(payload, (obj) => {
    const crs = compact(obj.crs || obj.CRS || obj.locationCrs).toUpperCase();
    const tpl = compact(obj.tpl || obj.tiploc || obj.TIPLOC).toUpperCase();
    const code = crs || tpl;
    if (!code) return;
    const coord = coordForLocation(code);
    if (!coord) return;
    stops.push({
      code,
      name: compact(obj.locationName || obj.name || obj.location) || code,
      coordinates: [coord.lon, coord.lat],
    });
  });
  return stops;
}

function extractTimestamp(payload) {
  const text = findFirst(payload, [
    "actual_timestamp",
    "actualTimestamp",
    "timestamp",
    "time",
    "createdAt",
    "created_at",
    "msg_queue_timestamp",
  ]);
  const n = Number.parseInt(text, 10);
  if (Number.isFinite(n) && n > 0) {
    return new Date(n > 10_000_000_000 ? n : n * 1000).toISOString();
  }
  const parsed = Date.parse(text);
  if (Number.isFinite(parsed)) return new Date(parsed).toISOString();
  return new Date().toISOString();
}

function extractHeading(payload) {
  return (
    numberOrNull(findFirst(payload, ["heading", "bearing", "direction"])) ?? undefined
  );
}

function extractLineName(payload) {
  return (
    findFirst(payload, ["headcode", "train_service_code", "service", "rsid"]) ||
    "Train"
  );
}

function extractDestination(payload) {
  return findFirst(payload, [
    "destination",
    "destinationName",
    "destination_name",
    "dest",
    "to",
  ]);
}

function extractOperator(payload) {
  const name = findFirst(payload, ["operator", "toc", "tocName", "toc_name"]);
  const code = findFirst(payload, ["toc_id", "tocId", "operatorCode"]);
  return {
    name: name || code || "National Rail",
    url: "",
  };
}

export function parsePushPortConfig(env) {
  const brokers = (env.DARWIN_KAFKA_BROKERS || "")
    .split(",")
    .map((b) => b.trim())
    .filter(Boolean);
  const topic = compact(env.DARWIN_KAFKA_TOPIC);
  const username = compact(env.DARWIN_KAFKA_USERNAME);
  const password = compact(env.DARWIN_KAFKA_PASSWORD);
  const groupId = compact(env.DARWIN_KAFKA_GROUP_ID);

  if (!topic) throw new Error("DARWIN_KAFKA_TOPIC is required");
  if (!brokers.length) throw new Error("DARWIN_KAFKA_BROKERS is required");
  if (!username) throw new Error("DARWIN_KAFKA_USERNAME is required");
  if (!password) throw new Error("DARWIN_KAFKA_PASSWORD is required");
  if (!groupId) throw new Error("DARWIN_KAFKA_GROUP_ID is required");
  if (!env.GTFS_STOPS_PATH?.trim()) {
    throw new Error("GTFS_STOPS_PATH is required (path to GTFS stops.txt)");
  }

  return {
    source: "push-port",
    brokers,
    topic,
    clientId: compact(env.DARWIN_KAFKA_CLIENT_ID) || "betterfleet-darwin-trains",
    groupId,
    username,
    password,
    saslMechanism: compact(env.DARWIN_KAFKA_SASL_MECHANISM) || "plain",
    ssl: String(env.DARWIN_KAFKA_SSL || "true").toLowerCase() !== "false",
    staleAfterMs:
      Number.parseInt(env.DARWIN_PUSH_STALE_AFTER_MS || "180000", 10) || 180000,
    gtfsStopsPath: env.GTFS_STOPS_PATH.trim(),
    vehicleEnricher: new VehicleEnricher({
      vehiclesApiUrl: env.VEHICLES_API_URL,
      vehicleUrlBase: env.VEHICLE_URL_BASE,
      cacheTtlMs:
        Number.parseInt(env.VEHICLE_CACHE_TTL_MS || "300000", 10) || 300000,
    }),
  };
}

export class DarwinPushPortStore {
  constructor(config) {
    this.config = config;
    this.items = new Map();
    this.started = false;
    this.lastAt = 0;
  }

  async start() {
    if (this.started) return;
    this.started = true;

    const kafka = new Kafka({
      clientId: this.config.clientId,
      brokers: this.config.brokers,
      ssl: this.config.ssl,
      sasl: {
        mechanism: this.config.saslMechanism,
        username: this.config.username,
        password: this.config.password,
      },
      logLevel: logLevel.WARN,
    });

    const consumer = kafka.consumer({ groupId: this.config.groupId });
    await consumer.connect();
    await consumer.subscribe({ topic: this.config.topic, fromBeginning: false });

    await consumer.run({
      eachMessage: async ({ message }) => {
        const item = await this.messageToVehicle(message);
        if (!item) return;
        this.items.set(item.id, item);
        this.lastAt = Date.now();
        this.prune();
      },
    });
  }

  prune() {
    const cutoff = Date.now() - this.config.staleAfterMs;
    for (const [id, item] of this.items) {
      if (Date.parse(item.datetime) < cutoff) this.items.delete(id);
    }
  }

  list({ bbox = null } = {}) {
    this.prune();
    const items = [...this.items.values()];
    if (!bbox) return items;
    return items.filter((item) => {
      const [lon, lat] = item.coordinates;
      return lon >= bbox.xmin && lon <= bbox.xmax && lat >= bbox.ymin && lat <= bbox.ymax;
    });
  }

  async messageToVehicle(message) {
    const raw = message.value?.toString("utf8");
    if (!raw) return null;

    let payload;
    try {
      payload = JSON.parse(raw);
    } catch {
      return null;
    }

    for (const candidate of asArray(payload)) {
      const vehicle = await this.payloadToVehicle(candidate);
      if (vehicle) return vehicle;
    }
    return null;
  }

  async payloadToVehicle(payload) {
    const coordinates = extractCoordinates(payload) || this.coordinatesFromLocation(payload);
    if (!coordinates) return null;

    const fleetNumber = extractFleetNumber(payload);
    const vehicle =
      (await this.config.vehicleEnricher.lookup(fleetNumber)) ||
      this.config.vehicleEnricher.fallbackVehicle(fleetNumber);

    const identity =
      fleetNumber ||
      findFirst(payload, ["rid", "rsid", "trainId", "train_id", "uid"]) ||
      JSON.stringify(payload).slice(0, 256);

    const destination = extractDestination(payload);
    const lineName = extractLineName(payload);
    const stops = extractStops(payload);

    return {
      id: stableNumericId(identity),
      coordinates,
      heading: extractHeading(payload),
      datetime: extractTimestamp(payload),
      destination,
      trip_id: null,
      journey_id: null,
      route_id: findFirst(payload, ["rid", "rsid", "uid", "trainId", "train_id"]),
      trip_descriptor_id: identity,
      service: {
        line_name: destination ? `${lineName} to ${destination}` : lineName,
        url: "",
      },
      operator: extractOperator(payload),
      vehicle,
      stops,
      raw_location: extractLocationCode(payload),
    };
  }

  coordinatesFromLocation(payload) {
    const code = extractLocationCode(payload);
    const coord = coordForLocation(code);
    if (!coord) return null;
    return [coord.lon, coord.lat];
  }
}
