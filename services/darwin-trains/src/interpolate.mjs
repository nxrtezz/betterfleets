import { DateTime } from "luxon";

/**
 * @typedef {{ crs: string, st?: string, et?: string, at?: string, cancelled?: boolean }} CallingPoint
 */

export function parseDarwinHmToMillis(hm) {
  if (!hm || typeof hm !== "string") return null;
  const m = hm.match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return null;
  const h = Number.parseInt(m[1], 10);
  const min = Number.parseInt(m[2], 10);
  const zone = "Europe/London";
  const nowZ = DateTime.now().setZone(zone);
  let dt = nowZ.set({ hour: h, minute: min, second: 0, millisecond: 0 });
  if (dt > nowZ.plus({ hours: 18 })) dt = dt.minus({ days: 1 });
  if (dt < nowZ.minus({ hours: 18 })) dt = dt.plus({ days: 1 });
  return dt.toMillis();
}

function pointTimeMs(cp) {
  const raw = cp.at || cp.et || cp.st;
  return parseDarwinHmToMillis(raw);
}

function bearingDeg(lat1, lon1, lat2, lon2) {
  const φ1 = (lat1 * Math.PI) / 180;
  const φ2 = (lat2 * Math.PI) / 180;
  const Δλ = ((lon2 - lon1) * Math.PI) / 180;
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x =
    Math.cos(φ1) * Math.sin(φ2) -
    Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  let θ = (Math.atan2(y, x) * 180) / Math.PI;
  return (θ + 360) % 360;
}

/**
 * @param {CallingPoint[]} points
 * @param {{ lat: number, lon: number }[]} coords
 * @param {number} nowMs
 */
export function interpolateAlongRoute(points, coords, nowMs) {
  if (points.length < 2 || coords.length !== points.length) return null;
  const times = points.map((p) => pointTimeMs(p));

  for (let i = 0; i < points.length - 1; i++) {
    if (points[i].cancelled) continue;
    const t1 = times[i];
    const t2 = times[i + 1];
    if (t1 == null || t2 == null) continue;
    if (nowMs < t1) {
      const c = coords[i];
      return {
        lon: c.lon,
        lat: c.lat,
        bearing: bearingDeg(c.lat, c.lon, coords[i + 1].lat, coords[i + 1].lon),
        ratio: 0,
      };
    }
    if (nowMs <= t2) {
      const c1 = coords[i];
      const c2 = coords[i + 1];
      const denom = Math.max(1, t2 - t1);
      let ratio = (nowMs - t1) / denom;
      ratio = Math.max(0, Math.min(1, ratio));
      return {
        lon: c1.lon + (c2.lon - c1.lon) * ratio,
        lat: c1.lat + (c2.lat - c1.lat) * ratio,
        bearing: bearingDeg(c1.lat, c1.lon, c2.lat, c2.lon),
        ratio,
      };
    }
  }
  const last = coords[coords.length - 1];
  return {
    lon: last.lon,
    lat: last.lat,
    bearing: null,
    ratio: 1,
  };
}

export function delaySecondsAtPoint(cp) {
  if (!cp?.st || !cp?.et) return null;
  const a = parseDarwinHmToMillis(cp.st);
  const b = parseDarwinHmToMillis(cp.et);
  if (a == null || b == null) return null;
  return Math.round((b - a) / 1000);
}
