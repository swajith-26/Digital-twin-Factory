"""Builds the live factory snapshot the dashboard renders.

One consistent view of every machine: live values, Normal/Warning/Critical
status, health score, predictions, open alarms, device connectivity and
platform health - computed from PostgreSQL.
"""

import threading
import time
from datetime import datetime, timezone

try:
    from . import factory_config as config, insights, status_rules, thresholds
except ImportError:  # pragma: no cover
    import factory_config as config
    import insights
    import status_rules
    import thresholds

SERIES_POINTS = 100  # recent readings per machine+sensor used for insights
SEVERITY_ORDER = {"Critical": 0, "Warning": 1}


def _iso(ts):
    return ts.isoformat() if ts is not None else None


# ----------------------------------------------------------------------
# queries
# ----------------------------------------------------------------------

def fetch_machines(cur):
    cur.execute(
        """
        SELECT machine_id, machine_name, status, machine_code, machine_type, zone
        FROM machines ORDER BY machine_id
        """
    )
    return cur.fetchall()


def fetch_series(cur, points=SERIES_POINTS):
    """{machine_id: {sensor_type: [(epoch_seconds, value, age_seconds, ts)]}} oldest->newest."""
    cur.execute(
        """
        SELECT m.machine_id, s.sensor_name, r.value, r.epoch, r.age, r.ts
        FROM machines m
        CROSS JOIN sensors s
        CROSS JOIN LATERAL (
            SELECT sr.value,
                   EXTRACT(EPOCH FROM sr.recorded_at) AS epoch,
                   EXTRACT(EPOCH FROM (NOW() - sr.recorded_at)) AS age,
                   sr.recorded_at::timestamptz AS ts
            FROM sensor_readings sr
            WHERE sr.sensor_id = s.id AND sr.machine_id = m.machine_id
            ORDER BY sr.recorded_at DESC, sr.id DESC
            LIMIT %s
        ) r
        WHERE s.sensor_name = ANY(%s)
        """,
        (points, status_rules.SENSOR_NAMES),
    )
    series = {}
    for machine_id, name, value, epoch, age, ts in cur.fetchall():
        sensor_type = status_rules.SENSOR_NAME_TO_TYPE[name]
        series.setdefault(machine_id, {}).setdefault(sensor_type, []).append(
            (float(epoch), float(value), max(float(age), 0.0), ts)
        )
    for per_machine in series.values():
        for rows in per_machine.values():
            rows.reverse()  # query returned newest first
    return series


ALARM_COLUMNS = (
    "id, machine_id, sensor_type, severity, max_severity, state, direction, "
    "trigger_value, peak_value, limit_value, message, raised_at, "
    "acknowledged_at, acknowledged_by, cleared_at"
)


def alarm_row_to_dict(row):
    (alarm_id, machine_id, sensor_type, severity, max_severity, state, direction,
     trigger_value, peak_value, limit_value, message, raised_at,
     acknowledged_at, acknowledged_by, cleared_at) = row
    end = cleared_at or datetime.now(timezone.utc)
    return {
        "id": alarm_id,
        "machine_id": machine_id,
        "sensor_type": sensor_type,
        "severity": severity,
        "max_severity": max_severity,
        "state": state,
        "direction": direction,
        "trigger_value": trigger_value,
        "peak_value": peak_value,
        "limit_value": limit_value,
        "message": message,
        "raised_at": _iso(raised_at),
        "acknowledged_at": _iso(acknowledged_at),
        "acknowledged_by": acknowledged_by,
        "cleared_at": _iso(cleared_at),
        "duration_seconds": int((end - raised_at).total_seconds()),
    }


def fetch_alarms(cur, open_only=False, limit=50, machine_id=None):
    cur.execute(
        f"""
        SELECT {ALARM_COLUMNS} FROM alarms
        WHERE (NOT %s OR cleared_at IS NULL)
          AND (%s::int IS NULL OR machine_id = %s::int)
        ORDER BY (cleared_at IS NULL) DESC, raised_at DESC
        LIMIT %s
        """,
        (open_only, machine_id, machine_id, limit),
    )
    return [alarm_row_to_dict(row) for row in cur.fetchall()]


def fetch_alarm_stats(cur):
    cur.execute(
        """
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE max_severity = 'Critical'),
               AVG(EXTRACT(EPOCH FROM (acknowledged_at - raised_at)))
                   FILTER (WHERE acknowledged_at IS NOT NULL)
        FROM alarms WHERE raised_at > NOW() - INTERVAL '24 hours'
        """
    )
    total, critical, mtta = cur.fetchone()
    return {
        "raised_24h": total,
        "critical_24h": critical,
        "mean_time_to_acknowledge_seconds": round(float(mtta), 1) if mtta is not None else None,
    }


def fetch_devices(cur):
    cur.execute("SELECT machine_id, state, updated_at FROM device_status")
    return {mid: {"state": state, "updated_at": _iso(ts)} for mid, state, ts in cur.fetchall()}


def fetch_heartbeat(cur, service="subscriber"):
    cur.execute(
        "SELECT updated_at, EXTRACT(EPOCH FROM (NOW() - updated_at)), details "
        "FROM service_heartbeats WHERE service = %s",
        (service,),
    )
    row = cur.fetchone()
    if row is None:
        return {"alive": False, "age_seconds": None, "details": {}}
    _, age, details = row
    return {"alive": float(age) < 20, "age_seconds": round(float(age), 1), "details": details or {}}


_availability_cache = {"at": 0.0, "value": {}}
_availability_lock = threading.Lock()


def fetch_availability(cur):
    """Share of the last 24 h (or of the time since first data) with live data.

    Counts the one-minute buckets that contain at least one temperature
    reading, so it measures real data availability per machine.
    """
    with _availability_lock:
        if time.monotonic() - _availability_cache["at"] < 60:
            return _availability_cache["value"]

    cur.execute(
        """
        SELECT sr.machine_id,
               COUNT(DISTINCT date_trunc('minute', sr.recorded_at)),
               GREATEST(1, CEIL(EXTRACT(EPOCH FROM (NOW() - MIN(sr.recorded_at))) / 60))
        FROM sensor_readings sr
        JOIN sensors s ON s.id = sr.sensor_id
        WHERE s.sensor_name = %s AND sr.recorded_at > NOW() - INTERVAL '24 hours'
        GROUP BY sr.machine_id
        """,
        (status_rules.SENSORS["temperature"]["sensor_name"],),
    )
    value = {
        mid: round(min(100.0, 100.0 * float(buckets) / float(span)), 1)
        for mid, buckets, span in cur.fetchall()
    }
    with _availability_lock:
        _availability_cache.update(at=time.monotonic(), value=value)
    return value


def fetch_history(cur, machine_id, sensor_type, minutes, points):
    """Downsampled history (avg/min/max per time bucket), oldest first."""
    seconds = minutes * 60
    bucket = max(1, int(round(seconds / points)))
    cur.execute(
        """
        SELECT to_timestamp(floor(EXTRACT(EPOCH FROM sr.recorded_at) / %s) * %s)::timestamptz,
               AVG(sr.value), MIN(sr.value), MAX(sr.value), COUNT(*)
        FROM sensor_readings sr
        JOIN sensors s ON s.id = sr.sensor_id
        WHERE s.sensor_name = %s
          AND sr.machine_id = %s
          AND sr.recorded_at > NOW() - make_interval(secs => %s)
        GROUP BY 1 ORDER BY 1
        """,
        (bucket, bucket, status_rules.SENSORS[sensor_type]["sensor_name"], machine_id, seconds),
    )
    return {
        "machine_id": machine_id,
        "sensor_type": sensor_type,
        "unit": status_rules.SENSORS[sensor_type]["unit"],
        "bucket_seconds": bucket,
        "points": [
            {"t": _iso(ts), "avg": round(float(avg), 3), "min": float(lo), "max": float(hi), "n": n}
            for ts, avg, lo, hi, n in cur.fetchall()
        ],
    }


# ----------------------------------------------------------------------
# snapshot
# ----------------------------------------------------------------------

def _machine_status(sensor_status, stale, device_state, has_data):
    if not has_data:
        return status_rules.NO_DATA
    if stale or device_state == "offline":
        return status_rules.OFFLINE
    return status_rules.worst(sensor_status.values())


def build_snapshot():
    with config.db_cursor() as cur:
        machine_rows = fetch_machines(cur)
        series = fetch_series(cur)
        open_alarms = fetch_alarms(cur, open_only=True, limit=200)
        recent_alarms = fetch_alarms(cur, limit=40)
        stats = fetch_alarm_stats(cur)
        devices = fetch_devices(cur)
        heartbeat = fetch_heartbeat(cur)
        availability = fetch_availability(cur)

    alarms_by_machine = {}
    for alarm in open_alarms:
        alarms_by_machine.setdefault(alarm["machine_id"], []).append(alarm)

    machines = []
    for machine_id, name, stored_status, code, mtype, zone in machine_rows:
        per_sensor = series.get(machine_id, {})
        device = devices.get(machine_id, {"state": "unknown", "updated_at": None})
        limits_for_machine = thresholds.get_all(machine_id)

        sensors = {}
        sensor_status = {}
        scores, anomalies, predictions = [], 0, []
        ages, newest = [], None

        for sensor_type, rows in per_sensor.items():
            value = rows[-1][1]
            limits = limits_for_machine[sensor_type]
            status = status_rules.evaluate(sensor_type, value, limits)
            insight = insights.sensor_insight(sensor_type, [(r[0], r[1]) for r in rows], limits)

            sensor_status[sensor_type] = status
            ages.append(rows[-1][2])
            newest = rows[-1][3] if newest is None or rows[-1][3] > newest else newest

            nominal = insight["nominal"] if insight["nominal"] is not None else value
            scores.append(insights.sensor_health(value, nominal, limits))
            anomalies += 1 if insight["anomaly"] else 0
            if insight["prediction"]:
                predictions.append(insight["prediction"]["minutes"])

            sensors[sensor_type] = {
                "value": round(value, 3),
                "unit": status_rules.SENSORS[sensor_type]["unit"],
                "status": status,
                "limits": limits,
                **insight,
            }

        has_data = bool(per_sensor)
        age = min(ages) if ages else None
        stale = age is None or age > config.STALE_AFTER_SECONDS
        status = _machine_status(sensor_status, stale, device["state"], has_data)
        machine_alarms = alarms_by_machine.get(machine_id, [])
        offline_alarm = any(a["sensor_type"] == "connectivity" for a in machine_alarms)

        health = insights.machine_health(scores, anomalies, min(predictions) if predictions else None)
        if status == status_rules.OFFLINE:
            health = None

        machines.append({
            "id": machine_id,
            "code": code or f"M{machine_id:02d}",
            "name": name,
            "type": mtype,
            "zone": zone,
            "stored_status": stored_status,
            "status": status,
            "health": health,
            "stale": stale,
            "age_seconds": round(age, 1) if age is not None else None,
            "last_reading_at": _iso(newest),
            "device": device,
            "availability_24h": availability.get(machine_id),
            "sensors": sensors,
            "alarms": machine_alarms,
            "recommendations": insights.recommendations(
                {
                    st: {
                        "status": info["status"],
                        "prediction": info["prediction"],
                        "anomaly": info["anomaly"],
                    }
                    for st, info in sensors.items()
                },
                open_connectivity=offline_alarm or status == status_rules.OFFLINE,
            ) if has_data or offline_alarm else [],
        })

    reporting = [m for m in machines if m["status"] != status_rules.NO_DATA]
    online = [m for m in reporting if m["status"] != status_rules.OFFLINE]
    healths = [m["health"] for m in online if m["health"] is not None]

    if any(m["status"] == status_rules.CRITICAL for m in machines):
        factory_status = status_rules.CRITICAL
    elif any(m["status"] == status_rules.WARNING for m in machines):
        factory_status = status_rules.WARNING
    elif not online:
        factory_status = status_rules.OFFLINE
    else:
        factory_status = status_rules.NORMAL

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "factory": {
            "status": factory_status,
            "health": int(round(sum(healths) / len(healths))) if healths else None,
            "machines_total": len(machines),
            "machines_online": len(online),
            "machines_offline": len(reporting) - len(online),
            "active_alarms": len(open_alarms),
            "critical_alarms": sum(1 for a in open_alarms if a["severity"] == "Critical"),
            "unacknowledged_alarms": sum(1 for a in open_alarms if a["state"] == "active"),
            **stats,
        },
        "machines": machines,
        "alarms": {
            "open": sorted(open_alarms, key=lambda a: (SEVERITY_ORDER.get(a["severity"], 9), a["raised_at"])),
            "recent": recent_alarms,
        },
        "system": {
            "database": "ok",
            "subscriber": heartbeat,
            "stale_after_seconds": config.STALE_AFTER_SECONDS,
            "retention_days": config.RETENTION_DAYS,
        },
    }


class SnapshotCache:
    """Share one computation between all connected dashboards."""

    def __init__(self, ttl=0.8):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._at = 0.0
        self._value = None

    def get(self, force=False):
        with self._lock:
            if force or self._value is None or time.monotonic() - self._at > self.ttl:
                self._value = build_snapshot()
                self._at = time.monotonic()
            return self._value

    def invalidate(self):
        with self._lock:
            self._at = 0.0
