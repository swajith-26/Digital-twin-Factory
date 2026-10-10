"""Digital Twin Factory - MQTT subscriber / ingestion service.

Receives telemetry from every machine and stores EVERY reading in PostgreSQL
(rows are only ever inserted). In the same transaction it runs the alarm
engine and wakes the dashboards via PostgreSQL NOTIFY.

Run from the ``backend`` folder (run exactly ONE instance):

    python mqtt_subscriber.py

Topics (prefix defaults to ``digitaltwin/factory``):

    <prefix>/machine01            telemetry JSON from machine 1
    <prefix>/machine02 ...        telemetry JSON from machine 2 ...
    <prefix>/machineNN/status     "online" / "offline" (MQTT Last Will, retained)

Telemetry payload (identical for the ESP32 and the simulator)::

    {"machine_id": 1, "temperature": 27.4, "humidity": 55.1,
     "vibration": 2.7, "pressure": 1013.2, "timestamp": "2026-10-06T09:30:00Z"}

``timestamp`` is informational. ``recorded_at`` is set by PostgreSQL when the
message is received, so ordering never depends on a device clock.
"""

import json
import logging
import math
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import psycopg2
from psycopg2.extras import Json, execute_values

try:
    from . import alarm_engine, factory_config as config, status_rules
except ImportError:
    import alarm_engine
    import factory_config as config
    import status_rules

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("digital_twin.subscriber")

_MACHINE_TOPIC = re.compile(r"machine0*(\d+)$")


# ==========================================
# PAYLOAD VALIDATION
# ==========================================

class PayloadError(ValueError):
    """The MQTT message does not match the agreed JSON structure."""


def machine_id_from_topic(topic):
    """``.../machine03`` -> 3 (``.../machine03/status`` -> 3). None if no match."""
    parts = topic.split("/")
    for part in reversed(parts):
        match = _MACHINE_TOPIC.fullmatch(part)
        if match:
            return int(match.group(1))
    return None


def parse_payload(raw_payload, topic_machine_id=None):
    """Validate a raw MQTT payload.

    Returns ``(machine_id, {sensor_type: float})`` or raises PayloadError.
    A payload that names a different machine than the topic it was published
    on is rejected (misconfigured or spoofed device).
    """
    try:
        data = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PayloadError(f"payload is not valid JSON ({error})") from error

    if not isinstance(data, dict):
        raise PayloadError("payload must be a JSON object")

    default_id = topic_machine_id or config.DEFAULT_MACHINE_ID
    machine_id = data.get("machine_id", default_id)
    if isinstance(machine_id, bool) or not isinstance(machine_id, int) or machine_id < 1:
        raise PayloadError(f"machine_id must be a positive integer, got {machine_id!r}")

    if topic_machine_id is not None and machine_id != topic_machine_id:
        raise PayloadError(
            f"payload machine_id {machine_id} does not match its topic (machine {topic_machine_id})"
        )

    values = {}
    for sensor_type in status_rules.SENSORS:
        if sensor_type not in data:
            raise PayloadError(f"missing field '{sensor_type}'")

        value = data[sensor_type]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PayloadError(f"'{sensor_type}' must be a number, got {value!r}")

        value = float(value)
        if not math.isfinite(value):
            raise PayloadError(f"'{sensor_type}' must be finite")

        low, high = status_rules.VALID_RANGES[sensor_type]
        if not low <= value <= high:
            raise PayloadError(
                f"'{sensor_type}' value {value} is outside the plausible range {low}..{high}"
            )

        values[sensor_type] = value

    return machine_id, values


# ==========================================
# INGESTION SERVICE
# ==========================================

class Ingestor:
    def __init__(self):
        self.engine = alarm_engine.AlarmEngine()
        self.started_at = datetime.now(timezone.utc)
        self.stored = 0
        self.rejected = 0
        self.last_message_at = None
        self.mqtt_connected = False

        self._lock = threading.Lock()
        self._last_seen = {}          # machine_id -> time.monotonic()
        self._silent_alarm = set()    # machines with an open connectivity alarm
        self.stop = threading.Event()

    # ---- telemetry -----------------------------------------------------
    def store_reading(self, machine_id, values):
        """Insert one row per sensor + evaluate alarms, in ONE transaction."""
        with config.db_cursor(commit=True) as cursor:
            cursor.execute(
                "SELECT sensor_name, id FROM sensors WHERE sensor_name = ANY(%s)",
                (status_rules.SENSOR_NAMES,),
            )
            sensor_ids = dict(cursor.fetchall())

            missing = set(status_rules.SENSOR_NAMES) - set(sensor_ids)
            if missing:
                raise RuntimeError(
                    "Missing sensors in database: " + ", ".join(sorted(missing))
                    + ". Run database/schema.sql."
                )

            # NOW() is the transaction time: all four sensors of one message
            # share exactly the same recorded_at.
            execute_values(
                cursor,
                "INSERT INTO sensor_readings (sensor_id, value, recorded_at, machine_id) VALUES %s",
                [
                    (sensor_ids[status_rules.SENSORS[st]["sensor_name"]], v, machine_id)
                    for st, v in values.items()
                ],
                template="(%s, %s, NOW(), %s)",
            )

            events = self.engine.process(cursor, machine_id, values)

            with self._lock:
                recovered = machine_id in self._silent_alarm
                self._silent_alarm.discard(machine_id)
                self._last_seen[machine_id] = time.monotonic()
            if recovered:
                events += self.engine.clear_connectivity(cursor, machine_id)

            # Delivered to listeners only if the transaction commits.
            cursor.execute("SELECT pg_notify('telemetry', %s)", (str(machine_id),))

        return events

    # ---- MQTT callbacks ------------------------------------------------
    def handle_telemetry(self, topic, payload):
        topic_machine = machine_id_from_topic(topic)
        try:
            machine_id, values = parse_payload(payload, topic_machine)
        except PayloadError as error:
            self.rejected += 1
            logger.warning("Rejected message on %s: %s | payload=%r", topic, error, payload[:200])
            return

        try:
            events = self.store_reading(machine_id, values)
        except config.DatabaseNotConfigured as error:
            logger.error("%s", error)
            return
        except (psycopg2.Error, RuntimeError) as error:
            logger.error("Database insert failed, reading dropped: %s", str(error).strip())
            return

        self.stored += 1
        self.last_message_at = datetime.now(timezone.utc)

        statuses = {
            st: status_rules.evaluate(st, v, self._limits(machine_id, st))
            for st, v in values.items()
        }
        summary = "  ".join(f"{st[:4]}={v:.2f}" for st, v in values.items())
        flagged = ", ".join(f"{st}:{s}" for st, s in statuses.items() if s != status_rules.NORMAL)
        logger.info(
            "Stored M%02d | %s | %s%s", machine_id, summary,
            status_rules.worst(statuses.values()), f" ({flagged})" if flagged else "",
        )
        for kind, mid, sensor, severity, value in events:
            logger.warning("ALARM %s: M%02d %s %s %s", kind.upper(), mid, sensor, severity,
                           "" if value is None else f"(value {value:.2f})")

    @staticmethod
    def _limits(machine_id, sensor_type):
        try:
            from . import thresholds
        except ImportError:
            import thresholds
        return thresholds.get(machine_id, sensor_type)

    def handle_status(self, topic, payload):
        machine_id = machine_id_from_topic(topic)
        state = payload.decode("utf-8", "replace").strip().lower()
        if machine_id is None or state not in ("online", "offline"):
            logger.warning("Ignoring status message on %s: %r", topic, payload[:50])
            return

        try:
            with config.db_cursor(commit=True) as cursor:
                cursor.execute(
                    """
                    INSERT INTO device_status (machine_id, state, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (machine_id) DO UPDATE
                        SET state = EXCLUDED.state, updated_at = NOW()
                    """,
                    (machine_id, state),
                )
                events = []
                if state == "offline":
                    events = self.engine.raise_connectivity(
                        cursor, machine_id, status_rules.CRITICAL,
                        "Device went offline (MQTT connection lost)",
                    )
                    with self._lock:
                        self._silent_alarm.add(machine_id)
                cursor.execute("SELECT pg_notify('telemetry', %s)", (str(machine_id),))
        except (psycopg2.Error, config.DatabaseNotConfigured) as error:
            logger.error("Could not record device status: %s", str(error).strip())
            return

        logger.info("Device M%02d is %s", machine_id, state.upper())
        for kind, mid, sensor, severity, _ in events:
            logger.warning("ALARM %s: M%02d %s %s", kind.upper(), mid, sensor, severity)

    # ---- background jobs -----------------------------------------------
    def load_last_seen(self):
        """After a restart, work out how long each machine has been silent."""
        with config.db_cursor() as cursor:
            cursor.execute(
                "SELECT machine_id, EXTRACT(EPOCH FROM (NOW() - MAX(recorded_at))) "
                "FROM sensor_readings GROUP BY machine_id"
            )
            now = time.monotonic()
            with self._lock:
                for machine_id, age in cursor.fetchall():
                    self._last_seen[machine_id] = now - float(age)
            cursor.execute(
                "SELECT machine_id FROM alarms "
                "WHERE sensor_type = %s AND cleared_at IS NULL",
                (alarm_engine.CONNECTIVITY,),
            )
            with self._lock:
                self._silent_alarm.update(row[0] for row in cursor.fetchall())

    def silence_monitor(self):
        """Raise a connectivity alarm when a machine stops sending data."""
        while not self.stop.wait(5):
            now = time.monotonic()
            with self._lock:
                snapshot = dict(self._last_seen)

            for machine_id, seen in snapshot.items():
                silent_for = now - seen
                if silent_for <= config.STALE_AFTER_SECONDS:
                    continue

                severity = (
                    status_rules.CRITICAL
                    if silent_for > 5 * config.STALE_AFTER_SECONDS
                    else status_rules.WARNING
                )
                try:
                    with config.db_cursor(commit=True) as cursor:
                        events = self.engine.raise_connectivity(
                            cursor, machine_id, severity,
                            f"No telemetry received for {int(silent_for)} s",
                        )
                        if events:
                            cursor.execute("SELECT pg_notify('telemetry', %s)", (str(machine_id),))
                    with self._lock:
                        self._silent_alarm.add(machine_id)
                    for kind, mid, sensor, sev, _ in events:
                        logger.warning("ALARM %s: M%02d %s %s", kind.upper(), mid, sensor, sev)
                except (psycopg2.Error, config.DatabaseNotConfigured) as error:
                    logger.error("Silence monitor DB error: %s", str(error).strip())

    def heartbeat(self):
        """Tell the API this service is alive (shown on the System page)."""
        while not self.stop.wait(5):
            details = {
                "mqtt_connected": self.mqtt_connected,
                "broker": f"{config.MQTT_BROKER}:{config.MQTT_PORT}",
                "topic_filter": config.MQTT_TELEMETRY_FILTER,
                "stored_messages": self.stored,
                "rejected_messages": self.rejected,
                "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
                "started_at": self.started_at.isoformat(),
            }
            try:
                with config.db_cursor(commit=True) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO service_heartbeats (service, updated_at, details)
                        VALUES ('subscriber', NOW(), %s)
                        ON CONFLICT (service) DO UPDATE
                            SET updated_at = NOW(), details = EXCLUDED.details
                        """,
                        (Json(details),),
                    )
            except (psycopg2.Error, config.DatabaseNotConfigured) as error:
                logger.error("Heartbeat failed: %s", str(error).strip())

    def retention(self):
        """Purge raw readings older than RETENTION_DAYS (and old cleared alarms)."""
        if config.RETENTION_DAYS <= 0:
            logger.info("Data retention: keeping all readings (RETENTION_DAYS=0)")
            return

        logger.info("Data retention: keeping %d days of raw readings", config.RETENTION_DAYS)
        while not self.stop.wait(1):  # first pass shortly after start
            try:
                total = 0
                while True:
                    with config.db_cursor(commit=True) as cursor:
                        cursor.execute(
                            """
                            DELETE FROM sensor_readings WHERE id IN (
                                SELECT id FROM sensor_readings
                                WHERE recorded_at < NOW() - make_interval(days => %s)
                                LIMIT 20000)
                            """,
                            (config.RETENTION_DAYS,),
                        )
                        deleted = cursor.rowcount
                        cursor.execute(
                            "DELETE FROM alarms WHERE cleared_at IS NOT NULL "
                            "AND cleared_at < NOW() - INTERVAL '365 days'"
                        )
                    total += deleted
                    if deleted < 20000:
                        break
                if total:
                    logger.info("Data retention: purged %d old readings", total)
            except (psycopg2.Error, config.DatabaseNotConfigured) as error:
                logger.error("Retention job failed: %s", str(error).strip())

            if self.stop.wait(3600):  # then hourly
                return
            continue


# ==========================================
# MQTT WIRING
# ==========================================

def build_client(ingestor):
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        # Unique per process: two clients sharing an ID would kick each other
        # off the broker in an endless reconnect loop.
        client_id=f"DigitalTwin-Subscriber-{socket.gethostname()}-{os.getpid()}",
    )
    if config.MQTT_USERNAME:
        client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            logger.error("MQTT connection refused (reason: %s)", reason_code)
            return
        ingestor.mqtt_connected = True
        logger.info("Connected to MQTT broker %s:%s", config.MQTT_BROKER, config.MQTT_PORT)
        # Subscribing here restores the subscriptions after every reconnect.
        client.subscribe([(config.MQTT_TELEMETRY_FILTER, 0), (config.MQTT_STATUS_FILTER, 1)])
        logger.info("Subscribed to %s and %s", config.MQTT_TELEMETRY_FILTER, config.MQTT_STATUS_FILTER)

    def on_message(client, userdata, msg):
        if msg.topic.endswith("/status"):
            # Retained status messages ARE meaningful (last known state).
            ingestor.handle_status(msg.topic, msg.payload)
            return
        # A retained telemetry message is replayed on every (re)subscribe;
        # storing it would create duplicate "new" readings from old data.
        if msg.retain:
            logger.info("Ignoring retained telemetry message on %s", msg.topic)
            return
        ingestor.handle_telemetry(msg.topic, msg.payload)

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        ingestor.mqtt_connected = False
        logger.warning("Disconnected from MQTT broker (reason: %s) - reconnecting...", reason_code)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def main():
    print("========================================")
    print(" DIGITAL TWIN FACTORY - MQTT SUBSCRIBER")
    print("========================================")

    # Fail early and clearly when the database is not usable.
    try:
        config.ensure_schema()
    except config.DatabaseNotConfigured as error:
        raise SystemExit(f"ERROR: {error}")
    except psycopg2.Error as error:
        raise SystemExit(
            f"ERROR: cannot use PostgreSQL ({str(error).strip()}).\n"
            "Check the DB_* settings and run database/schema.sql."
        )

    ingestor = Ingestor()
    ingestor.load_last_seen()

    for job in (ingestor.silence_monitor, ingestor.heartbeat, ingestor.retention):
        threading.Thread(target=job, name=job.__name__, daemon=True).start()

    client = build_client(ingestor)
    logger.info("Connecting to MQTT broker %s:%s ...", config.MQTT_BROKER, config.MQTT_PORT)
    client.connect_async(config.MQTT_BROKER, config.MQTT_PORT, keepalive=30)

    try:
        # retry_first_connection keeps trying if the broker is briefly down.
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        logger.info("Stopping subscriber...")
    finally:
        ingestor.stop.set()
        client.disconnect()
        config.close_pool()
        time.sleep(0.1)


if __name__ == "__main__":
    main()
