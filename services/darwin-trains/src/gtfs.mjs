import fs from "node:fs";
import { parse } from "csv-parse/sync";

/** @type {Map<string, { lat: number; lon: number }>} */
let byCrs = new Map();

export function loadGtfsStops(stopsPath) {
  if (!stopsPath || !fs.existsSync(stopsPath)) {
    throw new Error(`GTFS stops file not found: ${stopsPath}`);
  }
  const buf = fs.readFileSync(stopsPath);
  const rows = parse(buf, { columns: true, relax_column_count: true, trim: true });
  const next = new Map();
  for (const row of rows) {
    const crs = String(row.stop_code ?? "")
      .trim()
      .toUpperCase();
    if (!crs || crs.length < 3) continue;
    const lat = Number.parseFloat(row.stop_lat);
    const lon = Number.parseFloat(row.stop_lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    next.set(crs, { lat, lon });
  }
  byCrs = next;
  return byCrs.size;
}

export function coordForCrs(crs) {
  if (!crs) return null;
  return byCrs.get(String(crs).toUpperCase()) ?? null;
}

export const coordForLocation = coordForCrs;
