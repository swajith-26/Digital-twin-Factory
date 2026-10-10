"""Sensor definitions and Normal / Warning / Critical rules.

These are the thresholds the React dashboard used to hard-code. They now live
here, in one place, so the API, the MQTT subscriber and the dashboard can never
disagree about what "Warning" means.
"""

NORMAL = "Normal"
WARNING = "Warning"
CRITICAL = "Critical"
NO_DATA = "No Data"
OFFLINE = "Offline"

_SEVERITY = {NORMAL: 0, WARNING: 1, CRITICAL: 2}

# payload key -> database sensor row + display unit.
SENSORS = {
    "temperature": {"sensor_name": "Temperature Sensor 1", "unit": "°C"},
    "humidity": {"sensor_name": "Humidity Sensor 1", "unit": "%"},
    "vibration": {"sensor_name": "Vibration Sensor 1", "unit": "m/s²"},
    "pressure": {"sensor_name": "Pressure Sensor 1", "unit": "hPa"},
}

SENSOR_NAMES = [definition["sensor_name"] for definition in SENSORS.values()]
SENSOR_NAME_TO_TYPE = {
    definition["sensor_name"]: sensor_type
    for sensor_type, definition in SENSORS.items()
}

# A value is Critical/Warning when it is strictly beyond these limits.
THRESHOLDS = {
    "temperature": {"warning_high": 40, "critical_high": 45},
    "humidity": {
        "warning_low": 30,
        "warning_high": 80,
        "critical_low": 20,
        "critical_high": 90,
    },
    "vibration": {"warning_high": 5, "critical_high": 7},
    "pressure": {
        "warning_low": 950,
        "warning_high": 1050,
        "critical_low": 900,
        "critical_high": 1100,
    },
}

# Alarm clearing deadband (hysteresis): a value must come back this far inside
# the limit before an alarm is allowed to clear, so noise around a threshold
# cannot make an alarm flap on and off.
DEADBAND = {
    "temperature": 1.0,
    "humidity": 2.0,
    "vibration": 0.3,
    "pressure": 3.0,
}

# Plausibility limits used to reject garbage MQTT payloads (wider than the
# thresholds, so genuinely critical readings are still accepted and stored).
VALID_RANGES = {
    "temperature": (-50.0, 200.0),
    "humidity": (0.0, 100.0),
    "vibration": (0.0, 200.0),
    "pressure": (0.0, 2000.0),
}


def limits_for(sensor_type, limits=None):
    """Per-machine limits if given, otherwise the factory defaults."""
    return limits if limits is not None else THRESHOLDS.get(sensor_type)


def evaluate_detail(sensor_type, value, limits=None):
    """Classify one reading.

    Returns ``(status, direction, limit)``: ``direction`` is "high"/"low" and
    ``limit`` is the threshold that was crossed (both None when Normal).
    ``limits`` is a dict like THRESHOLDS[sensor_type] (per-machine override).
    """
    limits = limits_for(sensor_type, limits)
    if limits is None or value is None:
        return NO_DATA, None, None

    value = float(value)
    checks = (
        (CRITICAL, "high", limits.get("critical_high"), lambda lim: value > lim),
        (CRITICAL, "low", limits.get("critical_low"), lambda lim: value < lim),
        (WARNING, "high", limits.get("warning_high"), lambda lim: value > lim),
        (WARNING, "low", limits.get("warning_low"), lambda lim: value < lim),
    )
    for status, direction, limit, breached in checks:
        if limit is not None and breached(limit):
            return status, direction, float(limit)
    return NORMAL, None, None


def evaluate(sensor_type, value, limits=None):
    """Return Normal / Warning / Critical for one reading."""
    return evaluate_detail(sensor_type, value, limits)[0]


def worst(statuses):
    """Overall status for a machine = the most severe sensor status."""
    ranked = [status for status in statuses if status in _SEVERITY]
    if not ranked:
        return NO_DATA
    return max(ranked, key=_SEVERITY.__getitem__)
