"""The factory's asset catalogue and per-asset alarm limits.

This is only *seed data*: it is written to the database the first time the
backend starts and never overwrites anything you edit afterwards (machine
names, thresholds). Change the fleet here before first start, or edit the
``machines`` / ``sensor_thresholds`` tables later.
"""

try:
    from . import status_rules
except ImportError:  # pragma: no cover
    import status_rules

FLEET = {
    1: {
        "code": "M01",
        "name": "CNC Milling Center",
        "type": "CNC machine",
        "zone": "Zone A · Machining",
    },
    2: {
        "code": "M02",
        "name": "Hydraulic Press",
        "type": "Hydraulic press",
        "zone": "Zone A · Machining",
    },
    3: {
        "code": "M03",
        "name": "Conveyor Drive Motor",
        "type": "Conveyor drive",
        "zone": "Zone B · Assembly",
    },
    4: {
        "code": "M04",
        "name": "Air Compressor",
        "type": "Compressor",
        "zone": "Zone B · Assembly",
    },
}

# Different machines run at different normal temperatures and vibration
# levels, so alarm limits are set per asset. Anything not listed here uses the
# factory defaults in status_rules.THRESHOLDS.
THRESHOLD_OVERRIDES = {
    2: {  # hydraulic press: oil runs warm, heavy vibration is normal
        "temperature": {"warning_high": 55, "critical_high": 65},
        "vibration": {"warning_high": 6.0, "critical_high": 8.5},
    },
    3: {  # conveyor motor: winding temperature, early bearing-wear detection
        "temperature": {"warning_high": 55, "critical_high": 65},
        "vibration": {"warning_high": 4.5, "critical_high": 6.5},
    },
    4: {  # compressor: runs hot
        "temperature": {"warning_high": 70, "critical_high": 80},
        "vibration": {"warning_high": 5.5, "critical_high": 7.5},
    },
}


def default_limits_for(machine_id, sensor_type):
    """Seed limits for one machine/sensor (defaults + overrides)."""
    limits = dict(status_rules.THRESHOLDS[sensor_type])
    limits.update(THRESHOLD_OVERRIDES.get(machine_id, {}).get(sensor_type, {}))
    return limits


def seed(cursor):
    """Insert missing machines / metadata / thresholds. Never overwrites edits."""
    cursor.execute("SELECT machine_id FROM machines")
    existing = {row[0] for row in cursor.fetchall()}

    for machine_id, meta in FLEET.items():
        if machine_id not in existing:
            cursor.execute(
                "INSERT INTO machines (machine_id, machine_name, status) "
                "VALUES (%s, %s, 'Running')",
                (machine_id, meta["name"]),
            )

        cursor.execute(
            "UPDATE machines SET machine_code = %s, machine_type = %s, zone = %s "
            "WHERE machine_id = %s AND machine_code IS NULL",
            (meta["code"], meta["type"], meta["zone"], machine_id),
        )
        # Only replace the generic placeholder names ("Machine 01").
        cursor.execute(
            "UPDATE machines SET machine_name = %s "
            "WHERE machine_id = %s AND machine_name ~ '^Machine [0-9]+$'",
            (meta["name"], machine_id),
        )

    # Keep the SERIAL sequence ahead of the ids inserted explicitly above.
    cursor.execute(
        "SELECT setval(pg_get_serial_sequence('machines', 'machine_id'), "
        "(SELECT MAX(machine_id) FROM machines))"
    )

    rows = []
    for sensor_type, limits in status_rules.THRESHOLDS.items():
        rows.append((0, sensor_type, limits))
    for machine_id in FLEET:
        for sensor_type in THRESHOLD_OVERRIDES.get(machine_id, {}):
            rows.append((machine_id, sensor_type, default_limits_for(machine_id, sensor_type)))

    for machine_id, sensor_type, limits in rows:
        cursor.execute(
            """
            INSERT INTO sensor_thresholds
                (machine_id, sensor_type, warning_low, warning_high,
                 critical_low, critical_high, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s, 'seed')
            ON CONFLICT (machine_id, sensor_type) DO NOTHING
            """,
            (
                machine_id,
                sensor_type,
                limits.get("warning_low"),
                limits.get("warning_high"),
                limits.get("critical_low"),
                limits.get("critical_high"),
            ),
        )
