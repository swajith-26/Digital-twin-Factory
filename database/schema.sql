-- Digital Twin Factory - PostgreSQL schema
--
-- Base tables only. The backend (api.py / mqtt_subscriber.py) automatically adds the
-- rest at start-up: alarms, sensor_thresholds, device_status, service_heartbeats,
-- maintenance_orders, and seeds the machine fleet and per-machine limits.
--
-- Safe to run on a fresh database AND on your existing one: every statement is
-- idempotent (IF NOT EXISTS / WHERE NOT EXISTS) and nothing is dropped.
--
--   createdb -U postgres digital_twin_factory          (only if it doesn't exist)
--   psql -U postgres -d digital_twin_factory -f database/schema.sql

CREATE TABLE IF NOT EXISTS machines (
    machine_id   SERIAL PRIMARY KEY,
    machine_name VARCHAR(100) NOT NULL,
    status       VARCHAR(30)  NOT NULL DEFAULT 'Running'
);

CREATE TABLE IF NOT EXISTS sensors (
    id          SERIAL PRIMARY KEY,
    sensor_name VARCHAR(100) NOT NULL UNIQUE,
    sensor_type VARCHAR(50)  NOT NULL
);

-- One row per sensor per MQTT message. Readings are only ever INSERTed.
CREATE TABLE IF NOT EXISTS sensor_readings (
    id          BIGSERIAL PRIMARY KEY,
    sensor_id   INTEGER          NOT NULL REFERENCES sensors (id),
    value       DOUBLE PRECISION NOT NULL,
    recorded_at TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    machine_id  INTEGER          NOT NULL DEFAULT 1
);

-- Added for existing databases that were created before machine_id existed.
-- (api.py and mqtt_subscriber.py also run these two statements on start-up.)
ALTER TABLE sensor_readings
    ADD COLUMN IF NOT EXISTS machine_id INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_sensor_readings_machine_sensor_time
    ON sensor_readings (machine_id, sensor_id, recorded_at DESC);

-- Seed data (only inserted when missing).
INSERT INTO machines (machine_name)
SELECT v.name
FROM (VALUES ('Machine 01'), ('Machine 02'), ('Machine 03'), ('Machine 04')) AS v (name)
WHERE NOT EXISTS (SELECT 1 FROM machines);

INSERT INTO sensors (sensor_name, sensor_type)
SELECT v.sensor_name, v.sensor_type
FROM (VALUES
    ('Temperature Sensor 1', 'temperature'),
    ('Humidity Sensor 1',    'humidity'),
    ('Vibration Sensor 1',   'vibration'),
    ('Pressure Sensor 1',    'pressure')
) AS v (sensor_name, sensor_type)
WHERE NOT EXISTS (SELECT 1 FROM sensors s WHERE s.sensor_name = v.sensor_name);
