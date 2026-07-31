import { XMLParser } from "fast-xml-parser";

const LDB_NS = "http://thalesgroup.com/RTTI/2017-02-02/ldb/";
const TOKEN_NS = "http://thalesgroup.com/RTTI/2013-11-28/Token/types";
const SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/";

const parser = new XMLParser({
  ignoreAttributes: false,
  attributeNamePrefix: "@_",
  removeNSPrefix: true,
  isArray: (name) =>
    ["trainServices", "callingPoint", "callingPointList", "location"].includes(
      name,
    ),
});

function envelope(body, accessToken) {
  return `<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="${SOAP_ENV}">
  <soap:Header>
    <AccessToken xmlns="${TOKEN_NS}">
      <TokenValue>${escapeXml(accessToken)}</TokenValue>
    </AccessToken>
  </soap:Header>
  <soap:Body>
    ${body}
  </soap:Body>
</soap:Envelope>`;
}

function escapeXml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export async function soapRequest(url, accessToken, innerBody, soapAction) {
  const xml = envelope(innerBody, accessToken);
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "text/xml; charset=utf-8",
      SOAPAction: soapAction,
    },
    body: xml,
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`Darwin HTTP ${res.status}: ${text.slice(0, 200)}`);
  }
  const parsed = parser.parse(text);
  const fault = parsed?.Envelope?.Body?.Fault;
  if (fault) {
    const reason =
      fault.faultstring ?? fault.Reason?.Text ?? JSON.stringify(fault);
    throw new Error(`Darwin SOAP Fault: ${reason}`);
  }
  return parsed;
}

export function getDepartureBoardXml(crs, numRows, timeWindow) {
  return `
    <GetDepartureBoardRequest xmlns="${LDB_NS}">
      <numRows>${numRows}</numRows>
      <crs>${escapeXml(crs)}</crs>
      <timeWindow>${timeWindow}</timeWindow>
    </GetDepartureBoardRequest>`;
}

export function getServiceDetailsXml(serviceID) {
  return `
    <GetServiceDetailsRequest xmlns="${LDB_NS}">
      <serviceID>${escapeXml(serviceID)}</serviceID>
    </GetServiceDetailsRequest>`;
}

const SOAP_ACTION_BASE = "http://thalesgroup.com/RTTI/2017-02-02/ldb/";

export async function fetchDepartureBoard(
  url,
  accessToken,
  crs,
  { numRows = 15, timeWindow = 120 } = {},
) {
  const parsed = await soapRequest(
    url,
    accessToken,
    getDepartureBoardXml(crs, numRows, timeWindow),
    `${SOAP_ACTION_BASE}GetDepartureBoard`,
  );
  const body = parsed?.Envelope?.Body;
  const result = body?.GetDepartureBoardResponse?.GetDepartureBoardResult;
  const raw = result?.trainServices?.service ?? result?.trainServices;
  const list = ensureArray(raw);
  return list.map(normalizeBoardService).filter(Boolean);
}

export async function fetchServiceDetails(url, accessToken, serviceID) {
  const parsed = await soapRequest(
    url,
    accessToken,
    getServiceDetailsXml(serviceID),
    `${SOAP_ACTION_BASE}GetServiceDetails`,
  );
  const body = parsed?.Envelope?.Body;
  const result = body?.GetServiceDetailsResponse?.GetServiceDetailsResult;
  if (!result) return null;
  const points = extractCallingPoints(result);
  return {
    serviceID: String(result.serviceID ?? serviceID),
    rsid: result.rsid ? String(result.rsid) : "",
    operator: result.operator ? String(result.operator) : "",
    std: result.std ? String(result.std) : "",
    platform: result.platform ? String(result.platform) : "",
    destination: result.destination?.locationName
      ? String(result.destination.locationName)
      : "",
    origin: result.origin?.locationName
      ? String(result.origin.locationName)
      : "",
    points,
  };
}

function ensureArray(x) {
  if (x == null) return [];
  return Array.isArray(x) ? x : [x];
}

function normalizeBoardService(s) {
  if (!s || typeof s !== "object") return null;
  const serviceID = s.serviceID != null ? String(s.serviceID) : null;
  if (!serviceID) return null;
  return {
    serviceID,
    std: s.std != null ? String(s.std) : "",
    platform: s.platform != null ? String(s.platform) : "",
    operator: s.operator != null ? String(s.operator) : "",
    destination: s.destination?.locationName
      ? String(s.destination.locationName)
      : "",
    origin: s.origin?.locationName ? String(s.origin.locationName) : "",
    crs: s.origin?.crs ? String(s.origin.crs) : "",
  };
}

function extractCallingPoints(result) {
  const lists = ensureArray(result?.callingPointLists?.callingPointList);
  const out = [];
  for (const cpl of lists) {
    const pts = ensureArray(cpl?.callingPoint);
    for (const p of pts) {
      if (!p?.crs) continue;
      out.push({
        crs: String(p.crs).toUpperCase(),
        st: p.st != null ? String(p.st) : undefined,
        et: p.et != null ? String(p.et) : undefined,
        at: p.at != null ? String(p.at) : undefined,
        cancelled: p.isCancelled === true || p.isCancelled === "true",
      });
    }
  }
  return out;
}

export async function fetchWithRetry(fn, { retries = 3, baseMs = 400 } = {}) {
  let last;
  for (let i = 0; i < retries; i++) {
    try {
      return await fn();
    } catch (e) {
      last = e;
      await new Promise((r) => setTimeout(r, baseMs * 2 ** i));
    }
  }
  throw last;
}
