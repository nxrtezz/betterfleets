#!/usr/bin/env python3
"""Critical Betterfleets monitoring. Run every five minutes on the Docker host."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOGS = Path(os.environ.get("BF_LOG_DIR", "/home/noel/betterfleets-logs"))
STATE = LOGS / "critical-monitor-state.json"
REPEAT_SECONDS = 3600
CRITICAL_PROGRAMS = (
    "listen", "distribute_vehicle_locations", "run_huey", "import_redfunnel", "import_stagecoach_avl",
    "lothian", "import_translink_avl",
)
CRITICAL_LOGS = (
    "listen", "distribute_vehicle_locations", "redfunnel", "stagecoach", "lothian", "translink_avl",
)
ERROR = re.compile(r"Traceback \(most recent call last\):|^(?:ERROR|CRITICAL|FATAL)\b", re.M)

def run(args, timeout=30):
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout)

def load_state():
    try:
        return json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"faults": {}, "offsets": {}}

def webhook():
    # The host cron must see updated secrets without recreating tracking containers.
    url = os.environ.get("CRITICAL_ERROR_WEBHOOK_URL", "")
    if not url:
        try:
            for line in (ROOT / ".env").read_text().splitlines():
                if line.startswith("CRITICAL_ERROR_WEBHOOK_URL="):
                    url = line.partition("=")[2].strip().strip("\"'")
                    break
        except FileNotFoundError:
            pass
    if not url:
        result = run(["docker", "exec", "django_web", "python", "-c",
                      "import os; print(os.environ.get('CRITICAL_ERROR_WEBHOOK_URL', ''))"])
        url = result.stdout.strip()
    if not url.startswith(("https://discord.com/api/webhooks/",
                           "https://discordapp.com/api/webhooks/")):
        raise RuntimeError("A Discord CRITICAL_ERROR_WEBHOOK_URL is required")
    return url

def send(url, content):
    req = urllib.request.Request(
        url, data=json.dumps({"content": content[:1900], "allowed_mentions": {"parse": []}}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "Betterfleets critical monitor"},
    )
    # Do not include URL or response body in exceptions: webhook URL is secret.
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status not in (200, 204):
                raise RuntimeError("Discord rejected critical alert")
    except Exception:
        raise RuntimeError("Discord critical alert delivery failed") from None

def checks(state, now):
    faults = {}
    for mount in ("/", "/srv"):
        if Path(mount).exists():
            usage = shutil.disk_usage(mount)
            if usage.free < 1024**3 and usage.used / usage.total > 0.95:
                faults["disk:" + mount] = f"Critical disk space on {mount}: {usage.free // (1024**2)} MiB free"
    for container in ("django_web", "django_bod_avl", "django_signalbox",
                      "betterfleets-postgres-1", "betterfleets-redis-1"):
        result = run(["docker", "inspect", "-f", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}", container])
        if result.returncode or not result.stdout.startswith("running") or "unhealthy" in result.stdout:
            faults["container:" + container] = "Critical container unavailable: " + container
    result = run(["docker", "top", "django_web", "-eo", "pid,args"])
    if result.returncode == 0:
        for program in CRITICAL_PROGRAMS:
            if not re.search(r"manage\.py\s+" + re.escape(program) + r"(?:\s|$)", result.stdout):
                faults["process:" + program] = "Critical tracking worker missing: " + program
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/up", timeout=10) as response:
            if response.status != 200:
                faults["web"] = "Betterfleets health endpoint failed"
    except Exception:
        faults["web"] = "Betterfleets health endpoint unavailable"
    # Probe DB and Redis and detect the complete disappearance of timetable
    # coverage for the two operators that prompted this incident.
    code = """import json
from django.db import connection
from vehicles.utils import redis_client
from busstops.models import Service
with connection.cursor() as c: c.execute("SELECT 1")
assert redis_client.ping()
print(json.dumps([noc for noc in ("FHAM","BHBC") if not Service.objects.filter(operator=noc,current=True,route__trip__isnull=False).exists()]))
"""
    result = run(["docker", "exec", "django_web", "python", "manage.py", "shell", "-c", code], timeout=40)
    if result.returncode:
        faults["data-health"] = "Database, Redis or timetable health probe failed"
    else:
        try:
            missing = json.loads(result.stdout.strip().splitlines()[-1])
            for noc in missing:
                faults["coverage:" + noc] = noc + " has lost timetable services/trips"
        except (ValueError, IndexError):
            faults["data-health"] = "Timetable health probe returned invalid output"
    result = run(["docker", "exec", "django_web", "python", "manage.py",
                  "audit_tracking_coverage", "--json"], timeout=60)
    if result.returncode == 0:
        rows = json.loads(result.stdout)
        missing = [row for row in rows if row["timetable_expected"] and row["tracking"] >= 10
                   and (row["services"] == 0 or row["trips"] == 0) and row["live_with_trip"] == 0]
        if missing:
            examples = ", ".join(f'{row["noc"]} ({row["tracking"]} live)' for row in missing[:8])
            faults["timetable-coverage"] = f"{len(missing)} tracking operators lack timetable services/trips: {examples}"
    else:
        faults["coverage-audit"] = "Live operator timetable coverage audit failed"
    status_path = ROOT / "data/nightly-import-status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text())
            if status["state"] == "failed":
                faults["nightly"] = "Nightly timetable import failed: " + status.get("failures", "").strip()
            elif now - status["updated"] > (8 * 3600 if status["state"] == "running" else 30 * 3600):
                faults["nightly"] = "Nightly timetable importer is stalled or overdue"
        except (ValueError, KeyError):
            faults["nightly"] = "Nightly timetable status is unreadable"
    else:
        # Before the first run of the new wrapper, preserve the known outcome
        # of the existing 2AM job without copying its credential-bearing text.
        old_log = LOGS / "import_timetables.log"
        if old_log.exists():
            with old_log.open("rb") as stream:
                stream.seek(max(0, old_log.stat().st_size - 1024 * 1024))
                previous = stream.read().decode(errors="replace")
            if previous.rfind("completed with failures:") > previous.rfind("all done"):
                faults["nightly"] = "Previous nightly timetable import failed; awaiting a successful run"
    # Only new exceptions in critical workers; ordinary warnings are ignored.
    for name in CRITICAL_LOGS:
        path = LOGS / (name + ".err")
        if not path.exists():
            continue
        stat = path.stat()
        previous = state["offsets"].get(name)
        offset = previous["offset"] if previous and previous["inode"] == stat.st_ino else stat.st_size
        if stat.st_size < offset:
            offset = 0
        with path.open("rb") as stream:
            stream.seek(max(offset, stat.st_size - 1024 * 1024))
            new = stream.read().decode(errors="replace")
        state["offsets"][name] = {"inode": stat.st_ino, "offset": stat.st_size}
        if ERROR.search(new):
            faults["errors:" + name] = "New unhandled exceptions in critical worker: " + name
    # Docker logs from a bounded time window, not full history.
    for container in ("django_web", "django_bod_avl", "django_signalbox"):
        since = max(state.get("last_check", now), now - 600)
        result = run(["docker", "logs", "--since", str(int(since)), "--tail", "300", container])
        if ERROR.search(result.stdout + result.stderr):
            faults["errors:" + container] = "New unhandled exceptions in critical container: " + container
    return faults

def monitor(state, faults, now, send_message):
    pending = []
    for key, message in faults.items():
        fault = state["faults"].setdefault(key, {"first": now, "last_sent": 0})
        fault["last_seen"] = now
        fault["message"] = message
        if now - fault["last_sent"] >= REPEAT_SECONDS:
            pending.append(key)
    # Log exceptions clear after an hour without recurrence. Health faults
    # clear on a successful check.
    recovered = []
    for key, fault in list(state["faults"].items()):
        if key not in faults and (not key.startswith("errors:") or now - fault["last_seen"] >= REPEAT_SECONDS):
            if fault["last_sent"]:
                recovered.append(fault["message"])
            del state["faults"][key]
    if pending:
        send_message("Betterfleets critical alert\n" + "\n".join("- " + faults[key] for key in pending)
                     + "\nReminders are limited to once an hour per continuing fault.")
        for key in pending:
            state["faults"][key]["last_sent"] = now
    if recovered:
        send_message("Betterfleets recovered\n" + "\n".join("- " + message for message in recovered))
    state["last_check"] = now
    return state

def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "critical-monitor.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        state = load_state()
        now = time.time()
        url = webhook()
        if "--test-notification" in sys.argv:
            send(url, "Betterfleets critical monitoring enabled. Alerts cover core tracking, database/Redis, timetable coverage and nightly imports. Each active fault alerts once, then at most hourly.")
            return
        faults = checks(state, now)
        monitor(state, faults, now, lambda text: send(url, text))
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(STATE)
        print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
              "critical monitoring OK; active faults:", len(state["faults"]))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Critical monitor failed:", type(exc).__name__, file=sys.stderr)
        sys.exit(1)
