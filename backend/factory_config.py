"""Shared configuration for the Digital Twin Factory backend.

Used by both ``api.py`` (FastAPI) and ``mqtt_subscriber.py`` so that the two
processes always agree on database settings, the MQTT topic and the schema.

Settings come from environment variables. A ``backend/.env`` file is loaded
automatically when ``python-dotenv`` is installed (see ``.env.example``).
"""

import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from psycopg2 import pool as pg_pool

try:  # optional convenience; plain environment variables work without it
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:  # pragma: no cover
    pass

logger = logging.getLogger("digital_twin.config")


def _int_env(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


# ==========================================
# POSTGRESQL
# ==========================================

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = _int_env("DB_PORT", 5432)
DB_NAME = os.getenv("DB_NAME", "digital_twin_factory")
DB_USER = os.getenv("DB_USER", "postgres")
# Both names are accepted (the original api.py looked for either one).
DB_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")

# ==========================================
# MQTT  (publisher, subscriber and simulator must all agree on these)
# ==========================================

MQTT_BROKER = os.getenv("MQTT_BROKER", "test.mosquitto.org")
MQTT_PORT = _int_env("MQTT_PORT", 1883)
MQTT_USERNAME = os.getenv("MQTT_USERNAME") or None
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD") or None

# Every machine publishes to  <prefix>/machine01, <prefix>/machine02 ...
# and reports its connection state (online/offline, via MQTT Last Will) on
# <prefix>/machineNN/status.  The old single-topic setting MQTT_TOPIC is still
# honoured: its parent path becomes the prefix.
_legacy_topic = os.getenv("MQTT_TOPIC", "")
MQTT_TOPIC_PREFIX = (
    os.getenv("MQTT_TOPIC_PREFIX")
    or (_legacy_topic.rsplit("/", 1)[0] if "/" in _legacy_topic else "")
    or "digitaltwin/factory"
).strip("/")
MQTT_TELEMETRY_FILTER = f"{MQTT_TOPIC_PREFIX}/+"
MQTT_STATUS_FILTER = f"{MQTT_TOPIC_PREFIX}/+/status"

# ==========================================
# DASHBOARD BEHAVIOUR
# ==========================================

# Telemetry is published every ~3 s. If nothing new arrives for this long the
# API reports the machine as "Offline" instead of pretending it is healthy.
STALE_AFTER_SECONDS = _int_env("STALE_AFTER_SECONDS", 15)

# Optional shared secret protecting the WRITE endpoints (acknowledge alarms,
# edit thresholds, work orders). Clients send it as the X-API-Key header.
# When unset, writes are open - fine on an isolated lab network only.
API_KEY = os.getenv("API_KEY") or None

# Raw readings older than this are purged by the subscriber (0 = keep forever).
RETENTION_DAYS = _int_env("RETENTION_DAYS", 30)

# Machine that telemetry belongs to when a payload/row has no machine_id.
DEFAULT_MACHINE_ID = 1


class DatabaseNotConfigured(RuntimeError):
    """Raised when no database password has been provided."""


# ==========================================
# CONNECTION POOL
# ==========================================

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool

    if _pool is not None:
        return _pool

    if not DB_PASSWORD:
        raise DatabaseNotConfigured(
            "PostgreSQL credentials are not configured. "
            "Set DB_PASSWORD (or POSTGRES_PASSWORD)."
        )

    with _pool_lock:
        if _pool is None:
            _pool = pg_pool.ThreadedConnectionPool(
                1,
                10,
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=5,
            )
    return _pool


def _checkout():
    """Get a healthy connection (replaces ones broken by a DB restart)."""
    pool = _get_pool()

    for _ in range(3):
        conn = pool.getconn()
        try:
            if conn.closed:
                raise psycopg2.InterfaceError("connection closed")
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.rollback()
            return conn
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            pool.putconn(conn, close=True)

    raise psycopg2.OperationalError("Could not obtain a healthy database connection")


@contextmanager
def db_cursor(commit=False):
    """Yield a cursor and ALWAYS hand the connection back to the pool.

    Commits when ``commit=True`` and the block succeeds, otherwise rolls back.
    """
    conn = _checkout()
    broken = False
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
        else:
            conn.rollback()
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        broken = True
        raise
    except Exception:
        if not conn.closed:
            conn.rollback()
        raise
    finally:
        _get_pool().putconn(conn, close=broken)


def close_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None


# ==========================================
# SCHEMA
# ==========================================

_SCHEMA_STATEMENTS = [
    # --- readings: which machine produced them -----------------------------
    """ALTER TABLE sensor_readings
           ADD COLUMN IF NOT EXISTS machine_id INTEGER NOT NULL DEFAULT 1""",
    """CREATE INDEX IF NOT EXISTS idx_sensor_readings_machine_sensor_time
           ON sensor_readings (machine_id, sensor_id, recorded_at DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_sensor_readings_time
           ON sensor_readings (recorded_at)""",

    # --- asset metadata -----------------------------------------------------
    """ALTER TABLE machines
           ADD COLUMN IF NOT EXISTS machine_code TEXT,
           ADD COLUMN IF NOT EXISTS machine_type TEXT,
           ADD COLUMN IF NOT EXISTS zone TEXT""",

    # --- thresholds: machine_id 0 = factory default, others = per-asset ----
    """CREATE TABLE IF NOT EXISTS sensor_thresholds (
           machine_id     INTEGER NOT NULL,
           sensor_type    TEXT    NOT NULL,
           warning_low    DOUBLE PRECISION,
           warning_high   DOUBLE PRECISION,
           critical_low   DOUBLE PRECISION,
           critical_high  DOUBLE PRECISION,
           updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
           updated_by     TEXT,
           PRIMARY KEY (machine_id, sensor_type)
       )""",

    # --- alarms (persisted lifecycle: active -> acknowledged -> cleared) ----
    """CREATE TABLE IF NOT EXISTS alarms (
           id               BIGSERIAL PRIMARY KEY,
           machine_id       INTEGER NOT NULL,
           sensor_type      TEXT    NOT NULL,
           severity         TEXT    NOT NULL,
           max_severity     TEXT    NOT NULL,
           state            TEXT    NOT NULL DEFAULT 'active'
                            CHECK (state IN ('active', 'acknowledged', 'cleared')),
           direction        TEXT,
           trigger_value    DOUBLE PRECISION,
           peak_value       DOUBLE PRECISION,
           limit_value      DOUBLE PRECISION,
           message          TEXT,
           raised_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
           acknowledged_at  TIMESTAMPTZ,
           acknowledged_by  TEXT,
           cleared_at       TIMESTAMPTZ
       )""",
    # At most ONE open alarm per machine+sensor - this also makes a second,
    # accidentally started subscriber harmless.
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_alarms_one_open
           ON alarms (machine_id, sensor_type) WHERE cleared_at IS NULL""",
    """CREATE INDEX IF NOT EXISTS idx_alarms_raised ON alarms (raised_at DESC)""",

    # --- device connectivity (MQTT Last Will) and service heartbeats --------
    """CREATE TABLE IF NOT EXISTS device_status (
           machine_id  INTEGER PRIMARY KEY,
           state       TEXT NOT NULL,
           updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
       )""",
    """CREATE TABLE IF NOT EXISTS service_heartbeats (
           service     TEXT PRIMARY KEY,
           updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
           details     JSONB NOT NULL DEFAULT '{}'::jsonb
       )""",

    # --- technician directory and maintenance workflow ---------------------
    """CREATE TABLE IF NOT EXISTS technicians (
           id          SERIAL PRIMARY KEY,
           employee_code TEXT NOT NULL UNIQUE,
           name        TEXT NOT NULL,
           skills      TEXT NOT NULL DEFAULT 'General maintenance',
           shift       TEXT NOT NULL DEFAULT 'Day',
           active      BOOLEAN NOT NULL DEFAULT TRUE
       )""",
    """INSERT INTO technicians (employee_code, name, skills, shift) VALUES
           ('TECH-01', 'Arjun Rao', 'Mechanical, bearings, alignment', 'Day'),
           ('TECH-02', 'Priya Sharma', 'Electrical, sensors, controls', 'Day'),
           ('TECH-03', 'Rahul Verma', 'Hydraulics, pressure systems', 'Evening'),
           ('TECH-04', 'Sneha Reddy', 'Motors, vibration analysis', 'Day')
       ON CONFLICT (employee_code) DO NOTHING""",
    """CREATE TABLE IF NOT EXISTS maintenance_orders (
           id          BIGSERIAL PRIMARY KEY,
           machine_id  INTEGER NOT NULL,
           title       TEXT    NOT NULL,
           note        TEXT,
           priority    TEXT    NOT NULL DEFAULT 'medium'
                       CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
           status      TEXT    NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open', 'in_progress', 'done')),
           created_by  TEXT,
           created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
           updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
           closed_at   TIMESTAMPTZ,
           assigned_to INTEGER REFERENCES technicians(id),
           due_at      TIMESTAMPTZ,
           repair_notes TEXT
       )""",
    "ALTER TABLE maintenance_orders ADD COLUMN IF NOT EXISTS assigned_to INTEGER REFERENCES technicians(id)",
    "ALTER TABLE maintenance_orders ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ",
    "ALTER TABLE maintenance_orders ADD COLUMN IF NOT EXISTS repair_notes TEXT",
    "ALTER TABLE maintenance_orders DROP CONSTRAINT IF EXISTS maintenance_orders_status_check",
    "ALTER TABLE maintenance_orders ADD CONSTRAINT maintenance_orders_status_check CHECK (status IN ('open', 'assigned', 'in_progress', 'verification', 'done'))",
]


def ensure_schema():
    """Idempotent, additive migration run by both processes at start-up.

    Never drops or rewrites existing data. Existing readings default to
    machine 1 (every legacy reading came from ``machine01``). Rows you edit
    later (thresholds, machine names) are never overwritten.
    """
    try:
        from . import fleet
    except ImportError:  # pragma: no cover
        import fleet

    with db_cursor(commit=True) as cur:
        # Serialise concurrent start-ups (API + subscriber).
        cur.execute("SELECT pg_advisory_xact_lock(727001)")

        for statement in _SCHEMA_STATEMENTS:
            cur.execute(statement)

        fleet.seed(cur)

    logger.info("Database schema verified")
