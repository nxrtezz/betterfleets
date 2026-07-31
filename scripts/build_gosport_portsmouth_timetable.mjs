import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const outputDir = path.join(rootDir, "outputs");
const outputPath = path.join(outputDir, "gosport-portsmouth-timetable-import.xlsx");

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Timetable");
const instructions = workbook.worksheets.add("Instructions");

const headers = [
  "import_key",
  "trip_id",
  "route_id",
  "line_name",
  "calendar_id",
  "inbound",
  "sequence",
  "stop_atco_code",
  "stop_name",
  "arrival",
  "departure",
  "pick_up",
  "set_down",
  "timing_status",
  "destination_atco_code",
  "headsign",
  "block",
  "ticket_machine_code",
  "vehicle_journey_code",
  "operator_noc",
  "garage_code",
  "vehicle_type_code",
];

const rows = [headers];

const gosportCode = "676767";
const portsmouthCode = "676768";

function pad(num) {
  return String(num).padStart(2, "0");
}

function formatMinutes(totalMinutes) {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${pad(hours)}:${pad(minutes)}`;
}

let tripCounter = 1;

for (let departure = 5 * 60 + 30; departure <= 24 * 60; departure += 15) {
  const gosportTripKey = `GOS-${pad(tripCounter)}`;
  rows.push([
    gosportTripKey,
    "",
    "",
    "Gosport-Portsmouth",
    "",
    "false",
    1,
    gosportCode,
    "Gosport",
    "",
    formatMinutes(departure),
    "true",
    "true",
    "PTP",
    portsmouthCode,
    "Portsmouth",
    "",
    "",
    "",
    "",
    "",
    "",
  ]);
  rows.push([
    gosportTripKey,
    "",
    "",
    "Gosport-Portsmouth",
    "",
    "false",
    2,
    portsmouthCode,
    "Portsmouth",
    formatMinutes(departure + 7),
    "",
    "true",
    "true",
    "PTP",
    portsmouthCode,
    "Portsmouth",
    "",
    "",
    "",
    "",
    "",
    "",
  ]);
  tripCounter += 1;
}

for (let departure = 5 * 60 + 37; departure <= 24 * 60 + 7; departure += 15) {
  const portsmouthTripKey = `POR-${pad(tripCounter)}`;
  rows.push([
    portsmouthTripKey,
    "",
    "",
    "Gosport-Portsmouth",
    "",
    "true",
    1,
    portsmouthCode,
    "Portsmouth",
    "",
    formatMinutes(departure),
    "true",
    "true",
    "PTP",
    gosportCode,
    "Gosport",
    "",
    "",
    "",
    "",
    "",
    "",
  ]);
  rows.push([
    portsmouthTripKey,
    "",
    "",
    "Gosport-Portsmouth",
    "",
    "true",
    2,
    gosportCode,
    "Gosport",
    formatMinutes(departure + 7),
    "",
    "true",
    "true",
    "PTP",
    gosportCode,
    "Gosport",
    "",
    "",
    "",
    "",
    "",
    "",
  ]);
  tripCounter += 1;
}

sheet.getRange(`A1:V${rows.length}`).values = rows;

instructions.getRange("A1:B8").values = [
  ["Assumption", "Value"],
  ["Pattern", "Daily service every 15 minutes"],
  ["Gosport departures", "05:30 to 24:00 inclusive"],
  ["Portsmouth departures", "05:37 to 24:07 inclusive"],
  ["Running time", "7 minutes each way"],
  ["Gosport ATCO", gosportCode],
  ["Portsmouth ATCO", portsmouthCode],
  ["Format", "Ready for the admin timetable workbook importer"],
];

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(outputPath);
