"""Digital Twin Factory - FastAPI backend.

Run from the ``backend`` folder:

    uvicorn api:app --port 8000

Reads are open; WRITE endpoints (acknowledge alarms, edit thresholds, work
orders) require the ``X-API-Key`` header when API_KEY is configured.
"""

import asyncio
import hmac
import json
import logging
import os
import select
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

import psycopg2
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

try:  # works both as `uvicorn api:app` (inside backend/) and `uvicorn backend.api:app`
    from . import factory_config as config, overview, status_rules, thresholds
except ImportError:  # pragma: no cover
    import factory_config as config
    import overview
    import status_rules
    import thresholds

logger = logging.getLogger("digital_twin.api")

snapshot_cache = overview.SnapshotCache()


# ==========================================
# LIVE PUSH: PostgreSQL NOTIFY -> Server-Sent Events
# ==========================================

class StreamHub:
    """Fans a 'new data' wake-up out to every connected dashboard."""

    def __init__(self):
        self._queues = set()
        self._loop = None

    @property
    def count(self):
        return len(self._queues)

    def attach(self, loop):
        self._loop = loop

    def subscribe(self):
        queue = asyncio.Queue(maxsize=1)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue):
        self._queues.discard(queue)

    def notify_threadsafe(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._broadcast)

    def _broadcast(self):
        for queue in list(self._queues):
            try:
                queue.put_nowait(True)  # a pending wake-up already covers this one
            except asyncio.QueueFull:
                pass


hub = StreamHub()


def _listen_loop(stop):
    """Dedicated connection that LISTENs for telemetry/alarm notifications."""
    while not stop.is_set():
        conn = None
        try:
            if not config.DB_PASSWORD:
                stop.wait(5)
                continue
            conn = psycopg2.connect(
                host=config.DB_HOST, port=config.DB_PORT, dbname=config.DB_NAME,
                user=config.DB_USER, password=config.DB_PASSWORD, connect_timeout=5,
            )
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("LISTEN telemetry")
            logger.info("Listening for live telemetry notifications")

            while not stop.is_set():
                ready, _, _ = select.select([conn], [], [], 2.0)
                if not ready:
                    continue
                conn.poll()
                if conn.notifies:
                    conn.notifies.clear()
                    snapshot_cache.invalidate()
                    hub.notify_threadsafe()
        except (psycopg2.Error, OSError) as error:
            logger.warning("Notification listener lost (%s); retrying in 3 s", str(error).strip())
            stop.wait(3)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


# ==========================================
# APP LIFECYCLE
# ==========================================

@asynccontextmanager
async def lifespan(_app):
    try:
        config.ensure_schema()
    except config.DatabaseNotConfigured as error:
        logger.warning("%s", error)
    except psycopg2.Error as error:
        logger.warning(
            "Could not verify the database schema (%s). "
            "Is PostgreSQL running and database/schema.sql applied?",
            str(error).strip(),
        )

    hub.attach(asyncio.get_running_loop())
    stop = threading.Event()
    listener = threading.Thread(target=_listen_loop, args=(stop,), name="pg-listen", daemon=True)
    listener.start()

    yield

    stop.set()
    config.close_pool()


app = FastAPI(
    title="Digital Twin Factory API",
    description="Backend API for Industrial IoT monitoring",
    version="3.0",
    lifespan=lifespan,
)

# ==========================================
# CORS
# ==========================================
# Any localhost / 127.0.0.1 port is allowed (Vite moves to 5174, 5175... when
# 5173 is busy). Add other origins with CORS_ORIGINS="https://a.com,https://b.com".

extra_origins = [
    "https://digital-twin-factory-seven.vercel.app",
    "https://digital-twin-factory-git-main-swajith-26s-projects.vercel.app",
    "https://digital-twin-factory-i34vf9fvm-swajith-26s-projects.vercel.app",
]
extra_origins += [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=extra_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoStoreMiddleware:
    """Live data must never be served from a browser/proxy cache.

    Written as plain ASGI (not BaseHTTPMiddleware) so it never buffers or
    interferes with the streaming /api/stream response.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api"):
            await self.app(scope, receive, send)
            return

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != b"cache-control"]
                headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_header)


app.add_middleware(NoStoreMiddleware)


# ==========================================
# ERROR HANDLING / AUTH
# ==========================================

@app.exception_handler(config.DatabaseNotConfigured)
async def database_not_configured_handler(_request, error):
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.exception_handler(psycopg2.Error)
async def database_error_handler(_request, error):
    logger.error("Database error: %s", str(error).strip())
    return JSONResponse(
        status_code=503,
        content={"detail": "Database unavailable. Check that PostgreSQL is running."},
    )


def require_write_access(x_api_key: Optional[str] = Header(default=None)):
    """Protect write endpoints when API_KEY is configured."""
    if config.API_KEY and not hmac.compare_digest(x_api_key or "", config.API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")


def _iso(timestamp):
    return timestamp.isoformat() if timestamp is not None else None


def _notify(cursor, payload="api"):
    cursor.execute("SELECT pg_notify('telemetry', %s)", (payload,))


# ==========================================
# HOME / HEALTH
# ==========================================

@app.get("/")
def home():
    return {"message": "Digital Twin Factory API is running", "status": "online"}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "Digital Twin Factory API"}


@app.get("/api/health/db")
def health_db():
    """Deeper check: can the API reach PostgreSQL, and is data still flowing?"""
    with config.db_cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*), EXTRACT(EPOCH FROM (NOW() - MAX(recorded_at))) "
            "FROM sensor_readings"
        )
        total, age = cursor.fetchone()

    return {
        "status": "ok",
        "database": "connected",
        "total_readings": total,
        "seconds_since_last_reading": round(float(age), 1) if age is not None else None,
        "write_protection": "api-key" if config.API_KEY else "open",
    }


# ==========================================
# LIVE FACTORY VIEW (snapshot + push stream)
# ==========================================

def _with_stream_info(snapshot):
    return {**snapshot, "system": {**snapshot["system"], "stream_clients": hub.count}}


@app.get("/api/overview")
def get_overview():
    """Everything the dashboard needs, in one consistent snapshot."""
    return _with_stream_info(snapshot_cache.get())


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.get("/api/stream")
async def stream(request: Request):
    """Server-Sent Events: a fresh snapshot the moment new data is stored.

    Latency is a few milliseconds (PostgreSQL NOTIFY), there is no polling,
    and a snapshot is still sent at least every 5 s so staleness/offline
    detection keeps working when nothing is being published.
    """

    async def events():
        queue = hub.subscribe()
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break

                started = time.monotonic()
                try:
                    snapshot = await run_in_threadpool(snapshot_cache.get)
                    yield _sse("snapshot", _with_stream_info(snapshot))
                except (psycopg2.Error, config.DatabaseNotConfigured) as error:
                    yield _sse("error", {"detail": "Database unavailable"})
                    logger.error("Stream snapshot failed: %s", str(error).strip())
                    await asyncio.sleep(3)
                    continue

                try:
                    await asyncio.wait_for(queue.get(), timeout=5)
                except asyncio.TimeoutError:
                    pass

                # At most one snapshot per second per client.
                remaining = 1.0 - (time.monotonic() - started)
                if remaining > 0:
                    await asyncio.sleep(remaining)
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ==========================================
# MACHINES
# ==========================================

def _latest_by_machine(cursor, machine_id=None):
    """Newest reading of every canonical sensor, per machine.

    Returns {machine_id: {sensor_type: (value, timestamp, age_seconds)}}.
    """
    cursor.execute(
        """
        SELECT m.machine_id, s.sensor_name, lr.value, lr.ts, lr.age
        FROM machines m
        CROSS JOIN sensors s
        JOIN LATERAL (
            SELECT sr.value,
                   sr.recorded_at::timestamptz AS ts,
                   EXTRACT(EPOCH FROM (NOW() - sr.recorded_at)) AS age
            FROM sensor_readings sr
            WHERE sr.sensor_id = s.id AND sr.machine_id = m.machine_id
            ORDER BY sr.recorded_at DESC, sr.id DESC
            LIMIT 1
        ) lr ON TRUE
        WHERE s.sensor_name = ANY(%s)
          AND (%s::int IS NULL OR m.machine_id = %s::int)
        """,
        (status_rules.SENSOR_NAMES, machine_id, machine_id),
    )

    latest = {}
    for mid, sensor_name, value, ts, age in cursor.fetchall():
        sensor_type = status_rules.SENSOR_NAME_TO_TYPE[sensor_name]
        latest.setdefault(mid, {})[sensor_type] = (float(value), ts, max(float(age), 0.0))
    return latest


def _summarise(machine_id, sensors):
    """Per-sensor statuses + overall machine status (uses per-machine limits)."""
    if not sensors:
        return {"status": status_rules.NO_DATA, "sensor_status": {}, "timestamp": None,
                "age_seconds": None, "stale": True}

    sensor_status = {
        sensor_type: status_rules.evaluate(sensor_type, value, thresholds.get(machine_id, sensor_type))
        for sensor_type, (value, _ts, _age) in sensors.items()
    }
    newest = max(ts for _value, ts, _age in sensors.values())
    freshest_age = min(age for _value, _ts, age in sensors.values())
    stale = freshest_age > config.STALE_AFTER_SECONDS

    return {
        # A machine whose feed stopped is "Offline", never "Normal".
        "status": status_rules.OFFLINE if stale else status_rules.worst(sensor_status.values()),
        "sensor_status": sensor_status,
        "timestamp": _iso(newest),
        "age_seconds": round(freshest_age, 1),
        "stale": stale,
    }


@app.get("/api/machines")
def get_machines():
    with config.db_cursor() as cursor:
        machine_rows = overview.fetch_machines(cursor)
        latest = _latest_by_machine(cursor)

    machines = []
    for machine_id, name, stored_status, code, mtype, zone in machine_rows:
        sensors = latest.get(machine_id)
        summary = _summarise(machine_id, sensors)
        has_telemetry = bool(sensors)

        machines.append({
            "id": machine_id,
            "code": code,
            "name": name,
            "type": mtype,
            "zone": zone,
            # Live status calculated from the newest readings. Machines that
            # have never reported keep the status stored in the database.
            "status": summary["status"] if has_telemetry else stored_status,
            "status_source": "telemetry" if has_telemetry else "stored",
            "stored_status": stored_status,
            "last_reading_at": summary["timestamp"],
            "age_seconds": summary["age_seconds"],
            "stale": summary["stale"] if has_telemetry else None,
        })

    return machines


@app.get("/api/machines/{machine_id}/latest")
def get_latest_machine_reading(machine_id: int):
    with config.db_cursor() as cursor:
        latest = _latest_by_machine(cursor, machine_id).get(machine_id, {})

    if set(status_rules.SENSORS) - set(latest):
        raise HTTPException(
            status_code=404,
            detail=f"No complete sensor data found for machine {machine_id}",
        )

    summary = _summarise(machine_id, latest)

    return {
        "machine_id": machine_id,
        "temperature": latest["temperature"][0],
        "humidity": latest["humidity"][0],
        "vibration": latest["vibration"][0],
        "pressure": latest["pressure"][0],
        "timestamp": summary["timestamp"],
        "status": summary["status"],
        "sensor_status": summary["sensor_status"],
        "age_seconds": summary["age_seconds"],
        "stale": summary["stale"],
    }


# ==========================================
# THRESHOLDS
# ==========================================

class ThresholdBody(BaseModel):
    warning_low: Optional[float] = None
    warning_high: Optional[float] = None
    critical_low: Optional[float] = None
    critical_high: Optional[float] = None
    updated_by: Optional[str] = Field(default=None, max_length=60)


def _validate_limits(body):
    wl, wh, cl, ch = body.warning_low, body.warning_high, body.critical_low, body.critical_high
    if all(v is None for v in (wl, wh, cl, ch)):
        raise HTTPException(422, "At least one limit is required")
    if wh is not None and ch is not None and not wh < ch:
        raise HTTPException(422, "warning_high must be below critical_high")
    if wl is not None and cl is not None and not cl < wl:
        raise HTTPException(422, "critical_low must be below warning_low")
    if wl is not None and wh is not None and not wl < wh:
        raise HTTPException(422, "warning_low must be below warning_high")


@app.get("/api/thresholds")
def get_default_thresholds():
    return {
        "stale_after_seconds": config.STALE_AFTER_SECONDS,
        "sensors": {
            sensor_type: {**thresholds.get(0, sensor_type), "unit": definition["unit"]}
            for sensor_type, definition in status_rules.SENSORS.items()
        },
    }


@app.get("/api/machines/{machine_id}/thresholds")
def get_machine_thresholds(machine_id: int):
    return {
        "machine_id": machine_id,
        "sensors": {
            sensor_type: {**limits, "unit": status_rules.SENSORS[sensor_type]["unit"]}
            for sensor_type, limits in thresholds.get_all(machine_id).items()
        },
    }


@app.put("/api/machines/{machine_id}/thresholds/{sensor_type}",
         dependencies=[Depends(require_write_access)])
def put_machine_thresholds(machine_id: int, sensor_type: str, body: ThresholdBody):
    """Set alarm limits for one machine+sensor (machine_id 0 = factory default)."""
    if sensor_type not in status_rules.SENSORS:
        raise HTTPException(404, f"Unknown sensor type '{sensor_type}'")
    _validate_limits(body)

    with config.db_cursor(commit=True) as cursor:
        if machine_id != 0:
            cursor.execute("SELECT 1 FROM machines WHERE machine_id = %s", (machine_id,))
            if cursor.fetchone() is None:
                raise HTTPException(404, f"Machine {machine_id} not found")
        cursor.execute(
            """
            INSERT INTO sensor_thresholds
                (machine_id, sensor_type, warning_low, warning_high,
                 critical_low, critical_high, updated_at, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (machine_id, sensor_type) DO UPDATE SET
                warning_low = EXCLUDED.warning_low, warning_high = EXCLUDED.warning_high,
                critical_low = EXCLUDED.critical_low, critical_high = EXCLUDED.critical_high,
                updated_at = NOW(), updated_by = EXCLUDED.updated_by
            """,
            (machine_id, sensor_type, body.warning_low, body.warning_high,
             body.critical_low, body.critical_high, body.updated_by or "api"),
        )
        _notify(cursor)

    thresholds.invalidate()
    snapshot_cache.invalidate()
    return {"machine_id": machine_id, "sensor_type": sensor_type,
            "limits": thresholds.get(machine_id, sensor_type),
            "note": "The alarm engine picks up new limits within about 15 seconds."}


# ==========================================
# HISTORY / SENSOR DATA
# ==========================================

@app.get("/api/history")
def get_history(
    machine_id: int = Query(1, ge=1),
    sensor: str = Query("temperature"),
    minutes: int = Query(10, ge=1, le=10080),
    points: int = Query(120, ge=10, le=600),
):
    """Downsampled history (avg/min/max per bucket) for charts of any range."""
    if sensor not in status_rules.SENSORS:
        raise HTTPException(404, f"Unknown sensor '{sensor}'")
    with config.db_cursor() as cursor:
        result = overview.fetch_history(cursor, machine_id, sensor, minutes, points)
    result["limits"] = thresholds.get(machine_id, sensor)
    return result


@app.get("/api/sensors")
def get_sensors():
    with config.db_cursor() as cursor:
        cursor.execute(
            """
            SELECT sr.id, s.sensor_name, s.sensor_type, sr.value, sr.recorded_at::timestamptz
            FROM sensor_readings sr
            JOIN sensors s ON sr.sensor_id = s.id
            ORDER BY sr.recorded_at DESC, sr.id DESC
            LIMIT 50;
            """
        )
        rows = cursor.fetchall()

    return [
        {"id": r[0], "sensor_name": r[1], "sensor_type": r[2], "value": float(r[3]),
         "recorded_at": _iso(r[4])}
        for r in rows
    ]


@app.get("/api/sensors/latest")
def get_latest_sensors():
    """Newest reading of each sensor (any machine), with its status."""
    with config.db_cursor() as cursor:
        cursor.execute(
            """
            SELECT s.sensor_name, s.sensor_type, lr.value, lr.ts, lr.age, lr.machine_id
            FROM sensors s
            JOIN LATERAL (
                SELECT sr.value, sr.recorded_at::timestamptz AS ts,
                       EXTRACT(EPOCH FROM (NOW() - sr.recorded_at)) AS age, sr.machine_id
                FROM sensor_readings sr
                WHERE sr.sensor_id = s.id
                ORDER BY sr.recorded_at DESC, sr.id DESC
                LIMIT 1
            ) lr ON TRUE
            WHERE s.sensor_name = ANY(%s)
            ORDER BY s.sensor_type;
            """,
            (status_rules.SENSOR_NAMES,),
        )
        rows = cursor.fetchall()

    latest = []
    for sensor_name, sensor_type, value, ts, age, machine_id in rows:
        canonical = status_rules.SENSOR_NAME_TO_TYPE[sensor_name]
        age = max(float(age), 0.0)
        latest.append({
            "sensor_name": sensor_name,
            "sensor_type": sensor_type,
            "value": float(value),
            "recorded_at": _iso(ts),
            "machine_id": machine_id,
            "unit": status_rules.SENSORS[canonical]["unit"],
            "status": status_rules.evaluate(canonical, value, thresholds.get(machine_id, canonical)),
            "age_seconds": round(age, 1),
            "stale": age > config.STALE_AFTER_SECONDS,
        })
    return latest


@app.get("/api/readings")
def get_readings(
    limit: int = Query(100, ge=1, le=2000),
    machine_id: Optional[int] = Query(None, ge=1),
):
    """Most recent readings, newest first."""
    with config.db_cursor() as cursor:
        cursor.execute(
            """
            SELECT sr.id, sr.sensor_id, s.sensor_name, s.sensor_type, sr.value,
                   sr.recorded_at::timestamptz, sr.machine_id
            FROM sensor_readings sr
            JOIN sensors s ON sr.sensor_id = s.id
            WHERE (%s::int IS NULL OR sr.machine_id = %s::int)
            ORDER BY sr.recorded_at DESC, sr.id DESC
            LIMIT %s;
            """,
            (machine_id, machine_id, limit),
        )
        rows = cursor.fetchall()

    def reading_status(sensor_type, value, machine_id):
        canonical = status_rules.SENSOR_NAME_TO_TYPE.get(sensor_type) or sensor_type
        if canonical not in status_rules.SENSORS:
            return status_rules.NO_DATA
        return status_rules.evaluate(canonical, value, thresholds.get(machine_id, canonical))

    return [
        {"id": r[0], "sensor_id": r[1], "sensor_name": r[2], "sensor_type": r[3],
         "value": float(r[4]), "recorded_at": _iso(r[5]), "machine_id": r[6],
         "unit": status_rules.SENSORS.get(r[3], {}).get("unit"),
         "status": reading_status(r[3], float(r[4]), r[6])}
        for r in rows
    ]


@app.get("/api/analytics")
def get_analytics(machine_id: Optional[int] = Query(None, ge=1)):
    with config.db_cursor() as cursor:
        cursor.execute(
            """
            SELECT s.sensor_name, s.sensor_type, MIN(sr.value), MAX(sr.value), AVG(sr.value),
                   COUNT(sr.id), MAX(sr.recorded_at)::timestamptz
            FROM sensor_readings sr
            JOIN sensors s ON sr.sensor_id = s.id
            WHERE (%s::int IS NULL OR sr.machine_id = %s::int)
            GROUP BY s.sensor_name, s.sensor_type
            ORDER BY s.sensor_type;
            """,
            (machine_id, machine_id),
        )
        rows = cursor.fetchall()

    return [
        {"sensor_name": r[0], "sensor_type": r[1], "minimum": float(r[2]),
         "maximum": float(r[3]), "average": float(r[4]), "count": r[5],
         "latest_recorded_at": _iso(r[6])}
        for r in rows
    ]


# ==========================================
# ALARMS
# ==========================================

class AckBody(BaseModel):
    by: Optional[str] = Field(default=None, max_length=60)


@app.get("/api/alarms")
def get_alarms(
    state: str = Query("all", pattern="^(all|open|active)$"),
    limit: int = Query(50, ge=1, le=500),
    machine_id: Optional[int] = Query(None, ge=1),
):
    with config.db_cursor() as cursor:
        alarms = overview.fetch_alarms(cursor, open_only=state != "all", limit=limit,
                                       machine_id=machine_id)
    if state == "active":
        alarms = [a for a in alarms if a["state"] == "active"]
    return alarms


@app.post("/api/alarms/{alarm_id}/ack", dependencies=[Depends(require_write_access)])
def acknowledge_alarm(alarm_id: int, body: AckBody):
    with config.db_cursor(commit=True) as cursor:
        cursor.execute(
            f"""
            UPDATE alarms SET state = 'acknowledged', acknowledged_at = NOW(),
                              acknowledged_by = %s
            WHERE id = %s AND cleared_at IS NULL AND state = 'active'
            RETURNING {overview.ALARM_COLUMNS}
            """,
            (body.by or "operator", alarm_id),
        )
        row = cursor.fetchone()
        if row is None:
            cursor.execute("SELECT state FROM alarms WHERE id = %s", (alarm_id,))
            existing = cursor.fetchone()
            if existing is None:
                raise HTTPException(404, f"Alarm {alarm_id} not found")
            raise HTTPException(409, f"Alarm {alarm_id} is already {existing[0]}")
        _notify(cursor)

    snapshot_cache.invalidate()
    return overview.alarm_row_to_dict(row)


@app.post("/api/alarms/acknowledge-all", dependencies=[Depends(require_write_access)])
def acknowledge_all_alarms(body: AckBody):
    with config.db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE alarms SET state = 'acknowledged', acknowledged_at = NOW(),
                              acknowledged_by = %s
            WHERE cleared_at IS NULL AND state = 'active'
            """,
            (body.by or "operator",),
        )
        count = cursor.rowcount
        _notify(cursor)
    snapshot_cache.invalidate()
    return {"acknowledged": count}


# ==========================================
# MAINTENANCE WORK ORDERS
# ==========================================

class WorkOrderBody(BaseModel):
    machine_id: int = Field(ge=1)
    title: str = Field(min_length=3, max_length=160)
    note: Optional[str] = Field(default=None, max_length=2000)
    priority: str = Field(default="medium", pattern="^(low|medium|high|urgent)$")
    created_by: Optional[str] = Field(default=None, max_length=60)
    assigned_to: Optional[int] = Field(default=None, ge=1)
    due_at: Optional[str] = Field(default=None, max_length=40)


class WorkOrderUpdate(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(open|assigned|in_progress|verification|done)$")
    assigned_to: Optional[int] = Field(default=None, ge=1)
    repair_notes: Optional[str] = Field(default=None, max_length=4000)
    due_at: Optional[str] = Field(default=None, max_length=40)


_WORK_ORDER_COLUMNS = """mo.id, mo.machine_id, mo.title, mo.note, mo.priority, mo.status,
    mo.created_by, mo.created_at, mo.updated_at, mo.closed_at, mo.assigned_to,
    t.name AS assigned_to_name, t.employee_code, mo.due_at, mo.repair_notes"""
_WORK_ORDER_FROM = "maintenance_orders mo LEFT JOIN technicians t ON t.id = mo.assigned_to"


def _work_order(row):
    return {
        "id": row[0], "machine_id": row[1], "title": row[2], "note": row[3],
        "priority": row[4], "status": row[5], "created_by": row[6],
        "created_at": _iso(row[7]), "updated_at": _iso(row[8]), "closed_at": _iso(row[9]),
        "assigned_to": row[10], "assigned_to_name": row[11], "employee_code": row[12],
        "due_at": _iso(row[13]), "repair_notes": row[14],
    }


@app.get("/api/technicians")
def list_technicians():
    with config.db_cursor() as cursor:
        cursor.execute("""
            SELECT t.id, t.employee_code, t.name, t.skills, t.shift, t.active,
                   COUNT(mo.id) FILTER (WHERE mo.status <> 'done') AS active_jobs
              FROM technicians t
              LEFT JOIN maintenance_orders mo ON mo.assigned_to = t.id
             GROUP BY t.id
             ORDER BY t.active DESC, t.name
        """)
        return [{"id": r[0], "employee_code": r[1], "name": r[2], "skills": r[3],
                 "shift": r[4], "active": r[5], "active_jobs": r[6]} for r in cursor.fetchall()]


@app.get("/api/maintenance")
def list_work_orders(
    status: str = Query("all", pattern="^(all|open|assigned|in_progress|verification|done|active)$"),
    limit: int = Query(100, ge=1, le=500),
):
    with config.db_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {_WORK_ORDER_COLUMNS} FROM {_WORK_ORDER_FROM}
            WHERE (%s = 'all' OR mo.status = %s OR (%s = 'active' AND mo.status <> 'done'))
            ORDER BY (mo.status = 'done'),
                     CASE mo.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                                      WHEN 'medium' THEN 2 ELSE 3 END,
                     mo.created_at DESC
            LIMIT %s
            """,
            (status, status, status, limit),
        )
        return [_work_order(r) for r in cursor.fetchall()]


def _parse_due_at(value):
    if not value:
        return None
    from datetime import datetime, timezone
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(422, "due_at must be an ISO datetime")


def _fetch_work_order(cursor, order_id):
    cursor.execute(f"SELECT {_WORK_ORDER_COLUMNS} FROM {_WORK_ORDER_FROM} WHERE mo.id = %s", (order_id,))
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(404, f"Work order {order_id} not found")
    return _work_order(row)


@app.post("/api/maintenance", status_code=201, dependencies=[Depends(require_write_access)])
def create_work_order(body: WorkOrderBody):
    with config.db_cursor(commit=True) as cursor:
        cursor.execute("SELECT 1 FROM machines WHERE machine_id = %s", (body.machine_id,))
        if cursor.fetchone() is None:
            raise HTTPException(404, f"Machine {body.machine_id} not found")
        if body.assigned_to is not None:
            cursor.execute("SELECT 1 FROM technicians WHERE id = %s AND active = TRUE", (body.assigned_to,))
            if cursor.fetchone() is None:
                raise HTTPException(422, "Selected technician is not active or does not exist")
        status = "assigned" if body.assigned_to else "open"
        cursor.execute(
            """INSERT INTO maintenance_orders
                 (machine_id, title, note, priority, created_by, assigned_to, due_at, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (body.machine_id, body.title.strip(), body.note, body.priority,
             body.created_by or "operator", body.assigned_to, _parse_due_at(body.due_at), status),
        )
        order_id = cursor.fetchone()[0]
        return _fetch_work_order(cursor, order_id)


@app.patch("/api/maintenance/{order_id}", dependencies=[Depends(require_write_access)])
def update_work_order(order_id: int, body: WorkOrderUpdate):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(422, "Provide at least one field to update")
    if "assigned_to" in updates and updates["assigned_to"] is not None:
        with config.db_cursor() as cursor:
            cursor.execute("SELECT 1 FROM technicians WHERE id = %s AND active = TRUE", (updates["assigned_to"],))
            if cursor.fetchone() is None:
                raise HTTPException(422, "Selected technician is not active or does not exist")
    if "due_at" in updates:
        updates["due_at"] = _parse_due_at(updates["due_at"])
    assignments, values = [], []
    for field, value in updates.items():
        assignments.append(f"{field} = %s")
        values.append(value)
    if "status" in updates:
        assignments.append("closed_at = CASE WHEN %s = 'done' THEN NOW() ELSE NULL END")
        values.append(updates["status"])
    assignments.append("updated_at = NOW()")
    values.append(order_id)
    with config.db_cursor(commit=True) as cursor:
        cursor.execute(f"UPDATE maintenance_orders SET {', '.join(assignments)} WHERE id = %s", values)
        if cursor.rowcount == 0:
            raise HTTPException(404, f"Work order {order_id} not found")
        return _fetch_work_order(cursor, order_id)
