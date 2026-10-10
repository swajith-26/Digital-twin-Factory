# Digital Twin Factory (v4)

A real-time industrial IoT platform: edge devices → MQTT → ingestion service → PostgreSQL → FastAPI → live React dashboard with a 3D digital twin.

```
 Edge devices (ESP32/Wokwi = M01, real machines)      Simulator (virtual M02-M04, demo)
              │  JSON telemetry + MQTT Last Will              │
              └──────────────────────┬────────────────────────┘
                              MQTT broker (Mosquitto)
                                     │
                       backend/mqtt_subscriber.py   validate → store → alarm engine → NOTIFY
                                     │
                               PostgreSQL           readings, alarms, thresholds, work orders
                                     │
                          FastAPI (backend/api.py)  REST + Server-Sent Events push
                                     │
                       React dashboard (frontend/)  3D twin · alarms · analytics · maintenance
```

## What makes it plant-ready

| Capability | How it works |
|---|---|
| **Multi-machine fleet** | Each machine has its own sensors, topic (`digitaltwin/factory/machineNN`), alarm limits and failure behaviour. |
| **Per-asset alarm limits** | Stored in PostgreSQL (`sensor_thresholds`), editable via API. A hydraulic press and a compressor don't share one threshold. |
| **Real alarm management** | Debounce (2 consecutive breaches), hysteresis (clears only after 3 readings inside a deadband), escalation, acknowledge with *who/when*, full history. One open alarm per machine+sensor, enforced by the database. |
| **Predictive maintenance** | Least-squares trend + z-score anomaly detection → "vibration reaches warning limit in ~4 min". Transparent statistics, not a black box. |
| **Computed health index** | 0-100 per machine from distance to limits, trends and anomalies (no hardcoded numbers). |
| **True real time** | PostgreSQL `LISTEN/NOTIFY` → Server-Sent Events. Dashboards update within milliseconds of a reading; a single 3 s fallback timer only runs if the stream stalls. |
| **Device connectivity** | MQTT Last Will: a dead device is flagged the second the broker notices. A silence monitor catches devices that stay connected but stop sending. |
| **Maintenance work orders** | Create from a recommendation, track open → in progress → done, stored in the database. |
| **Operations** | Data retention job, service heartbeats, health endpoints, authenticated broker with per-device ACLs, optional API key, Docker Compose. |

## Quick start (local, Windows PowerShell)

```powershell
# 1. Database (creates the base tables; the backend adds the rest automatically on start)
createdb -U postgres digital_twin_factory
psql -U postgres -d digital_twin_factory -f database\schema.sql

# 2. Backend
cd backend
pip install -r requirements.txt
copy .env.example .env          # then set DB_PASSWORD

# 3. Frontend
cd ..\frontend
npm install
```

Run (4 terminals, each exactly once):

```powershell
cd backend ; uvicorn api:app --port 8000                 # API + live stream
cd backend ; python mqtt_subscriber.py                   # ingestion + alarm engine
cd frontend ; npm run dev                                # http://localhost:5173
cd simulator ; python simulator.py                       # virtual M02-M04 (M01 = Wokwi)
```

* **No Wokwi?** `python simulator.py --all` simulates all four machines.
* **Never** simulate a machine that a real/Wokwi device already publishes as: readings would interleave.
* Demo faster: `python simulator.py --speed 4` (faults and the bearing-wear degradation play out 4× faster).
* **Rebuild the Wokwi firmware** (`wokwi/sketch.ino` changed: MQTT Last Will). Delete `wokwi/build` and run `arduino-cli compile --fqbn esp32:esp32:esp32 --output-dir build .` inside `wokwi/`.

## Docker (full stack)

```bash
cp .env.example .env                       # set passwords
deploy/mosquitto/make-passwords.sh <backend-pw> <device-m01-pw> <simulator-pw>
docker compose up -d --build
docker compose --profile demo up -d simulator      # optional virtual M02-M04
# dashboard: http://localhost:8080   (nginx serves the UI and proxies /api)
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for TLS, authentication, backups and connecting real machines.

## Configuration (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `DB_PASSWORD` | **required** | PostgreSQL password (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` also available) |
| `MQTT_BROKER` / `MQTT_PORT` | test.mosquitto.org / 1883 | Broker. Use your own broker for anything real |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | none | Broker credentials |
| `MQTT_TOPIC_PREFIX` | `digitaltwin/factory` | Topics are `<prefix>/machineNN` and `<prefix>/machineNN/status`. The old `MQTT_TOPIC` still works (its parent path becomes the prefix) |
| `API_KEY` | none | If set, write actions need header `X-API-Key` (frontend: `VITE_API_KEY` in `frontend/.env`) |
| `RETENTION_DAYS` | 30 | Raw readings older than this are purged (0 = keep forever) |
| `STALE_AFTER_SECONDS` | 15 | Silence before a machine is reported Offline |
| `CORS_ORIGINS` | none | Extra browser origins (localhost always allowed) |
| `VITE_API_URL` (frontend) | http://127.0.0.1:8000 | API address; empty = same origin |

## MQTT contract

`<prefix>/machine01` ... telemetry, every ~3 s:
`{"machine_id":1,"temperature":27.4,"humidity":55.1,"vibration":2.7,"pressure":1013.2,"timestamp":"2026-10-06T09:30:00Z"}`
(`timestamp` optional/informational; `recorded_at` is set by PostgreSQL on arrival. A payload whose `machine_id` doesn't match its topic is rejected.)
`<prefix>/machine01/status` ... retained `online` / `offline` (Last Will).

## Main API

| Endpoint | Purpose |
|---|---|
| `GET /api/overview` | Full live snapshot (machines, status, health, predictions, alarms, system) |
| `GET /api/stream` | Server-Sent Events: a snapshot pushed as soon as data arrives |
| `GET /api/history?machine_id=&sensor=&minutes=&points=` | Downsampled history (10 min … 7 days) |
| `GET /api/alarms`, `POST /api/alarms/{id}/ack`, `POST /api/alarms/acknowledge-all` | Alarm log and acknowledgement |
| `GET /api/machines/{id}/thresholds`, `PUT …/thresholds/{sensor}` | Per-machine alarm limits |
| `GET/POST /api/maintenance`, `PATCH /api/maintenance/{id}` | Work orders |
| `GET /api/health`, `GET /api/health/db` | Liveness / database + data-flow check |
| `/api/machines`, `/api/sensors/latest`, `/api/readings`, `/api/analytics` | Original endpoints, still supported |

Edit a limit: `curl -X PUT localhost:8000/api/machines/2/thresholds/vibration -H "Content-Type: application/json" -d '{"warning_high":6.5,"critical_high":9}'` (alarm engine applies it within ~15 s).

## Testing

```powershell
pip install -r backend\requirements-dev.txt
python -m pytest tests                                  # 49 tests: alarms, thresholds, prediction, payloads, firmware parity
python scripts\verify_pipeline.py --seconds 30          # live end-to-end check of the running system
cd frontend ; npm run lint ; npm run build
```

Manual walkthrough: start everything → dashboard header shows **LIVE** → machines move on the 3D floor → within ~2 min Warning/Critical alarms appear (acknowledge one, reload: it stays acknowledged) → M03's vibration trend predicts its bearing limit before it is reached → stop the simulator: devices go **Offline** instantly with connectivity alarms.

## Honest limitations

* The health index and predictions are **statistical heuristics**, not a trained model. Validate against your machines before relying on them for safety decisions.
* The demo sensors measure temperature, humidity, vibration and pressure only. **OEE** (availability × performance × quality) needs production counters from the machine's PLC and is deliberately not faked.
* The dashboard shows "Availability (24 h)" as data availability, not production uptime.
* The API key is a shared secret visible in the browser bundle. For a real plant put the dashboard behind your reverse proxy / SSO (see the deployment guide).
* Docker files and the broker ACL were written to standard practice; the broker config was tested locally, the Docker build itself was not run in the authoring environment.


## OEE demo module

The Analytics page includes an explicitly labelled **SIMULATED DATA** OEE demonstration. It calculates Availability, Performance, Quality and OEE from illustrative production counters and provides controls to add simulated production, rejects and downtime. These values are not PLC readings and must not be used for real production reporting. For real OEE, integrate validated PLC/production-counter data for planned time, run time, ideal cycle time, total output and good output.

## Operator Control Center and technician dispatch

The Operations page adds a control-room workflow on top of the existing maintenance queue:

- Demo technician roster with employee code, shift, skills and active workload (`GET /api/technicians`).
- Assign and reassign technicians to work orders; assignments and repair notes are persisted in PostgreSQL.
- Work-order lifecycle: `open` → `assigned` → `in_progress` → `verification` → `done`.
- Due-time tracking, overdue indicators, queue filters and an operator verification step before closing a repair.
- The existing Maintenance page remains available for creating work orders from machine recommendations.

The backend performs additive, idempotent schema updates at startup. Existing work orders and telemetry are preserved. The initial technician names are sample/demo records and should be replaced with actual staff records before any real operational use. A work order is a tracking workflow; it does not automatically stop a machine or certify equipment as safe. The operator must verify the repair and follow site safety procedures.
