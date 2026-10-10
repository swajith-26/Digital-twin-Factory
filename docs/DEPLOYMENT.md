# From demo to a real factory

## 1. Network and security checklist

1. **Own your broker.** `test.mosquitto.org` is public: anyone can read and publish. Run Mosquitto (see `docker-compose.yml`) on the plant network.
2. **Authenticate every client** and give each device only its own topics (`deploy/mosquitto/acl`). A compromised M01 can then never impersonate M02.
3. **Turn on TLS** for anything that leaves a trusted VLAN: add a `listener 8883` with `cafile/certfile/keyfile` in `mosquitto.conf`, and use port 8883 + the CA certificate on devices and the backend.
4. **Put the dashboard behind your reverse proxy / SSO** (nginx basic auth, Authentik, Azure AD, …). `API_KEY` protects write actions but cannot hide a key shipped in a browser bundle.
5. Set strong, unique values for `DB_PASSWORD`, `MQTT_*_PASSWORD`, `API_KEY`. Never commit `.env`.
6. Keep PostgreSQL off the plant network; only the API and the ingestion service need it.

## 2. Connecting real machines

The platform only needs one MQTT message per machine every few seconds:

```json
{"machine_id": 5, "temperature": 61.2, "humidity": 40.1, "vibration": 3.4, "pressure": 1012.0}
```

published to `digitaltwin/factory/machine05`, plus a retained `online`/`offline` on `.../machine05/status` (use the MQTT Last Will).

* **ESP32 / microcontrollers:** `wokwi/sketch.ino` is the reference firmware (replace the simulated twin layer with your real sensor readings; keep the payload).
* **PLCs / OPC UA / Modbus:** use a gateway such as Node-RED, Telegraf or a vendor edge box to map tags to this JSON.
* **Add the machine** to `backend/fleet.py` (name, zone, limits) *before first start*, or insert rows into `machines` / `sensor_thresholds`. Give its device an ACL entry.
* **Sensors you don't have:** the payload requires all four values; send a constant for an unused one, or extend `status_rules.SENSORS`.
* The 3D scene shows four machines; add more `FactoryMachine` blocks in `frontend/src/components/Factory3D.jsx`.

## 3. Alarm limits

Defaults live in `backend/status_rules.py`; per-asset seeds in `backend/fleet.py`; the live values are in the `sensor_thresholds` table and editable through `PUT /api/machines/{id}/thresholds/{sensor}`. Debounce/hysteresis constants are in `backend/alarm_engine.py` (`RAISE_AFTER`, `CLEAR_AFTER`) and `status_rules.DEADBAND`.

## 4. Operations

* **Run exactly one `mqtt_subscriber`.** A second one is harmless for data integrity (alarms are unique per machine+sensor) but would store every reading twice.
* **Retention:** `RETENTION_DAYS` purges raw readings hourly. Alarms are kept for a year.
* **Backups:** `pg_dump digital_twin_factory` nightly (alarms and work orders are your audit trail).
* **Monitoring:** `GET /api/health/db` (database + data flow), and the dashboard's System page (service heartbeats, device Last-Will state).
* **Scale:** plain PostgreSQL comfortably handles tens of machines at 3 s intervals. Beyond that, install TimescaleDB and convert `sensor_readings` to a hypertable with compression.
* **Upgrades:** the schema migration at start-up is additive and idempotent; it never drops data or overwrites edited names/limits.

## 5. Offline plants

The dashboard works without internet: the 3D scene uses procedural lighting (no CDN assets). The only external request is the optional Google Fonts stylesheet; without internet the UI falls back to system fonts. To self-host fonts, install `@fontsource/inter` and `@fontsource/space-grotesk` and import them in `src/main.jsx`.
