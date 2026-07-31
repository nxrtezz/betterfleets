import http from "node:http";
import { config as dotenvConfig } from "dotenv";
import { loadGtfsStops } from "./gtfs.mjs";
import { refreshTrains, parseConfig, parseBbox } from "./refreshTrains.mjs";
import {
  DarwinPushPortStore,
  parsePushPortConfig,
} from "./darwinPushPort.mjs";

// Load environment variables from .env file
dotenvConfig();

let config;
try {
  if ((process.env.TRAIN_SOURCE || "").trim().toLowerCase() === "push-port") {
    config = parsePushPortConfig(process.env);
  } else {
    config = parseConfig(process.env);
  }
} catch (e) {
  console.error(e.message);
  process.exit(1);
}

const n = loadGtfsStops(config.gtfsStopsPath);
console.error(`darwin-trains: loaded ${n} GTFS stops by CRS (stop_code)`);

let lastGood = { items: [], at: 0, stale: false };
let inFlight = null;
let pushPortStore = null;

async function tickLdb() {
  if (inFlight) return;
  inFlight = (async () => {
    try {
      const items = await refreshTrains(config, null);
      lastGood = { items, at: Date.now(), stale: false };
    } catch (e) {
      console.error("darwin-trains poll error:", e.message);
      lastGood = { ...lastGood, stale: true };
    } finally {
      inFlight = null;
    }
  })();
  await inFlight;
}

if (config.source === "push-port") {
  pushPortStore = new DarwinPushPortStore(config);
  pushPortStore.start().catch((e) => {
    console.error("darwin-trains push-port error:", e.message);
    process.exit(1);
  });
} else {
  await tickLdb();
  setInterval(tickLdb, config.pollMs);
}

const port = Number.parseInt(process.env.PORT || "8765", 10);

const server = http.createServer((req, res) => {
  const url = new URL(req.url || "/", `http://127.0.0.1:${port}`);

  if (req.method === "GET" && url.pathname === "/healthz") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        ok: true,
        source: config.source || "ldb",
        stops: n,
        lastAt: pushPortStore ? pushPortStore.lastAt : lastGood.at,
        stale: pushPortStore
          ? Date.now() - pushPortStore.lastAt > config.staleAfterMs
          : lastGood.stale,
        count: pushPortStore ? pushPortStore.list().length : lastGood.items.length,
      }),
    );
    return;
  }

  if (req.method === "GET" && url.pathname === "/trains.json") {
    const bbox = parseBbox(url.searchParams);
    const items = pushPortStore ? pushPortStore.list({ bbox }) : getLdbItems(bbox);
    res.writeHead(200, {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=5",
      "X-Train-Cache": lastGood.stale ? "stale" : "fresh",
      "X-Train-Computed-At": String(lastGood.at),
    });
    res.end(JSON.stringify(items));
    return;
  }

  res.writeHead(404);
  res.end();
});

server.listen(port, () => {
  console.error(`darwin-trains listening on :${port}`);
});

function getLdbItems(bbox) {
  if (!bbox) return lastGood.items;
  return lastGood.items.filter((v) => {
    const [lon, lat] = v.coordinates;
    return (
      lon >= bbox.xmin &&
      lon <= bbox.xmax &&
      lat >= bbox.ymin &&
      lat <= bbox.ymax
    );
  });
}
