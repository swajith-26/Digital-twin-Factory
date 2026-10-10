"""End-to-end check of the Digital Twin pipeline (standard library only).

    python scripts/verify_pipeline.py                  # watch for 30 s
    python scripts/verify_pipeline.py --seconds 60 --api http://127.0.0.1:8000

Checks the live system the way the dashboard sees it: the API and database are
healthy, the ingestion service is alive, every machine is reporting fresh data,
values really change, new rows keep being inserted, the SSE push stream
delivers, and statuses / health scores are present.
Exit code 0 = healthy, 1 = a check failed.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def get(api, path, timeout=8):
    with urllib.request.urlopen(api + path, timeout=timeout) as response:
        return json.load(response)


def first_sse_event(api, timeout=8):
    """Read /api/stream until the first snapshot event (returns seconds, snapshot)."""
    started = time.time()
    with urllib.request.urlopen(api + "/api/stream", timeout=timeout) as response:
        event = None
        for raw in response:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "snapshot":
                return time.time() - started, json.loads(line[5:])
    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--seconds", type=int, default=30)
    args = parser.parse_args()

    failures = []

    def check(ok, message):
        print(("  PASS  " if ok else "  FAIL  ") + message)
        if not ok:
            failures.append(message)

    try:
        check(get(args.api, "/api/health").get("status") == "ok", "GET /api/health")
        db = get(args.api, "/api/health/db")
        check(db.get("database") == "connected", "API can reach PostgreSQL")
        start_count = db["total_readings"]
    except (urllib.error.URLError, OSError, KeyError) as error:
        print(f"  FAIL  API not reachable at {args.api}: {error}")
        return 1

    overview = get(args.api, "/api/overview")
    sub = overview["system"]["subscriber"]
    check(sub["alive"] and sub["details"].get("mqtt_connected"),
          f"ingestion service alive and connected to MQTT (heartbeat {sub['age_seconds']} s ago)")

    latency, snapshot = first_sse_event(args.api)
    check(snapshot is not None and latency < 3, f"SSE push stream delivers a snapshot ({latency:.2f} s)" if latency else "SSE push stream")

    print(f"\nWatching for {args.seconds} s ...\n")
    seen = {}
    deadline = time.time() + args.seconds
    while time.time() < deadline:
        overview = get(args.api, "/api/overview")
        line = []
        for m in overview["machines"]:
            line.append(f"{m['code']}:{m['status']}/{m['health']}")
            for sensor, info in m["sensors"].items():
                seen.setdefault((m["id"], sensor), set()).add(info["value"])
        print("  " + "  ".join(line))
        time.sleep(3)

    print()
    reporting = [m for m in overview["machines"] if m["status"] != "No Data"]
    check(len(reporting) > 0, f"{len(reporting)} machine(s) have reported data")
    for m in overview["machines"]:
        if m["status"] == "No Data":
            print(f"  note  {m['code']} {m['name']} has never reported (e.g. Wokwi M01 not started)")
            continue
        check(not m["stale"], f"{m['code']} is reporting fresh data ({m['age_seconds']} s old, status {m['status']})")
        changed = all(len(seen.get((m["id"], s), ())) > 1 for s in ("temperature", "humidity", "vibration", "pressure"))
        check(changed, f"{m['code']}: all four sensor values changed over time")
        check(m["health"] is not None or m["status"] == "Offline", f"{m['code']}: health score computed")

    end_count = get(args.api, "/api/health/db")["total_readings"]
    check(end_count > start_count, f"new rows inserted ({start_count} -> {end_count}), none overwritten")

    print("\nRESULT:", "HEALTHY" if not failures else f"{len(failures)} check(s) failed")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
