import { createHash } from "node:crypto";
import { coordForCrs } from "./gtfs.mjs";
import {
  fetchDepartureBoard,
  fetchServiceDetails,
  fetchWithRetry,
} from "./darwin.mjs";
import {
  interpolateAlongRoute,
  delaySecondsAtPoint,
} from "./interpolate.mjs";

function stableNumericId(s) {
  const h = createHash("sha256").update(String(s)).digest();
  return h.readUInt32BE(0) & 0x7fffffff;
}

function inBbox(lon, lat, bbox) {
  if (!bbox) return true;
  return (
    lon >= bbox.xmin &&
    lon <= bbox.xmax &&
    lat >= bbox.ymin &&
    lat <= bbox.ymax
  );
}

const detailsCache = new Map();
const DETAIL_TTL_MS = 45_000;

function getCachedDetail(serviceID) {
  const e = detailsCache.get(serviceID);
  if (!e) return null;
  if (Date.now() - e.at > DETAIL_TTL_MS) {
    detailsCache.delete(serviceID);
    return null;
  }
  return e.data;
}

function setCachedDetail(serviceID, data) {
  detailsCache.set(serviceID, { data, at: Date.now() });
}

async function runInBatchesFlat(items, batchSize, fn) {
  const out = [];
  for (let i = 0; i < items.length; i += batchSize) {
    const batch = items.slice(i, i + batchSize);
    const part = await Promise.all(
      batch.map(async (item) => {
        try {
          return await fn(item);
        } catch {
          return null;
        }
      }),
    );
    for (const p of part) {
      if (p == null) continue;
      if (Array.isArray(p)) out.push(...p);
      else out.push(p);
    }
  }
  return out;
}

function buildVehicle(detail, pos, nowIso) {
  const line =
    [detail.std, detail.destination].filter(Boolean).join(" → ") ||
    detail.rsid ||
    detail.serviceID;
  const delay =
    detail.points.length > 1
      ? delaySecondsAtPoint(
          detail.points.find((p) => p.et && p.st) ?? detail.points[1],
        )
      : null;

  return {
    id: stableNumericId(detail.serviceID),
    coordinates: [pos.lon, pos.lat],
    heading: pos.bearing != null ? pos.bearing : undefined,
    datetime: nowIso,
    destination: detail.destination || "",
    delay: delay != null && Math.abs(delay) >= 45 ? delay : undefined,
    trip_id: null,
    journey_id: null,
    route_id: detail.operator || "",
    trip_descriptor_id: detail.serviceID,
    start_time: detail.std || "",
    service: {
      line_name: line.slice(0, 48),
      url: "",
    },
    vehicle: {
      url: "",
      name: (detail.rsid || detail.serviceID).slice(0, 32),
      livery: null,
      colour: "#2d6a9f",
      text_colour: "#ffffff",
      css: "#2d6a9f",
      right_css: "#2d6a9f",
    },
  };
}

/**
 * @param {object} config
 * @param {{ xmin?: number, ymin?: number, xmax?: number, ymax?: number }} bbox
 */
export async function refreshTrains(config, bbox) {
  const {
    soapUrl,
    accessToken,
    crsList,
    numRows,
    timeWindow,
    maxServiceDetails,
    boardConcurrency,
    detailConcurrency,
  } = config;

  const nowMs = Date.now();
  const nowIso = new Date(nowMs).toISOString().replace(/\.\d{3}Z$/, "Z");

  const boardRows = [];
  for (let i = 0; i < crsList.length; i += boardConcurrency) {
    const chunk = crsList.slice(i, i + boardConcurrency);
    const part = await Promise.all(
      chunk.map((crs) =>
        fetchWithRetry(() =>
          fetchDepartureBoard(soapUrl, accessToken, crs, {
            numRows,
            timeWindow,
          }),
        ).catch(() => []),
      ),
    );
    boardRows.push(...part);
  }

  const seen = new Map();
  for (const services of boardRows) {
    for (const s of services) {
      if (!seen.has(s.serviceID)) seen.set(s.serviceID, s);
    }
  }

  const ids = [...seen.keys()].slice(0, maxServiceDetails);

  const details = await runInBatchesFlat(ids, detailConcurrency, async (serviceID) => {
    let d = getCachedDetail(serviceID);
    if (!d) {
      d = await fetchWithRetry(() =>
        fetchServiceDetails(soapUrl, accessToken, serviceID),
      );
      if (d) setCachedDetail(serviceID, d);
    }
    return d;
  });

  const vehicles = [];

  for (const detail of details) {
    if (!detail?.points?.length) continue;
    const coords = detail.points.map((p) => coordForCrs(p.crs));
    const ok = coords.every((c) => c != null);
    if (!ok) continue;
    const pos = interpolateAlongRoute(detail.points, coords, nowMs);
    if (!pos) continue;
    if (!inBbox(pos.lon, pos.lat, bbox)) continue;
    vehicles.push(buildVehicle(detail, pos, nowIso));
  }

  return vehicles;
}

export function parseConfig(env) {
  const soapUrl =
    env.DARWIN_SOAP_URL?.trim() ||
    "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb9.asmx";
  const accessToken = env.DARWIN_ACCESS_TOKEN?.trim();
  if (!accessToken) {
    throw new Error("DARWIN_ACCESS_TOKEN is required");
  }
  if (!env.GTFS_STOPS_PATH?.trim()) {
    throw new Error("GTFS_STOPS_PATH is required (path to GTFS stops.txt)");
  }
  const crsRaw =
    env.DARWIN_CRS_LIST?.trim() ||
    "EUS,PAD,KGX,MOG,BHM,MAN,MCV,LIV,LDS,NCL,YRK,GLC,EDB,ABD,DEE,PLY,BRI,RDG,SWI,BTN,STP,VIC,CHX,CST,WAT,LBG,ECR,MYB";
  const crsList = crsRaw
    .split(/[\s,]+/)
    .map((c) => c.trim().toUpperCase())
    .filter(Boolean);

  return {
    source: "ldb",
    soapUrl,
    accessToken,
    crsList,
    numRows: Math.min(15, Number.parseInt(env.DARWIN_NUM_ROWS || "15", 10) || 15),
    timeWindow:
      Math.min(120, Number.parseInt(env.DARWIN_TIME_WINDOW || "120", 10) || 120),
    maxServiceDetails: Math.min(
      200,
      Number.parseInt(env.DARWIN_MAX_SERVICE_DETAILS || "100", 10) || 100,
    ),
    boardConcurrency: Number.parseInt(env.DARWIN_BOARD_CONCURRENCY || "4", 10) || 4,
    detailConcurrency:
      Number.parseInt(env.DARWIN_DETAIL_CONCURRENCY || "5", 10) || 5,
    pollMs: Number.parseInt(env.DARWIN_POLL_MS || "12000", 10) || 12000,
    cacheTtlMs: Number.parseInt(env.CACHE_TTL_MS || "10000", 10) || 10000,
    gtfsStopsPath: env.GTFS_STOPS_PATH?.trim() || "",
  };
}

export function parseBbox(searchParams) {
  const xmin = Number.parseFloat(searchParams.get("xmin") ?? "");
  const ymin = Number.parseFloat(searchParams.get("ymin") ?? "");
  const xmax = Number.parseFloat(searchParams.get("xmax") ?? "");
  const ymax = Number.parseFloat(searchParams.get("ymax") ?? "");
  if (
    [xmin, ymin, xmax, ymax].every((n) => Number.isFinite(n)) &&
    xmin < xmax &&
    ymin < ymax
  ) {
    return { xmin, ymin, xmax, ymax };
  }
  return null;
}
