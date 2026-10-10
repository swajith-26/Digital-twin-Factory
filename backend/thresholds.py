"""Per-machine alarm limits, cached from the database.

Lookup order: machine-specific row -> factory default row (machine_id 0) ->
the static defaults in status_rules. A short cache means edits made through
the API reach the alarm engine within ``TTL`` seconds without restarting.
"""

import threading
import time

try:
    from . import factory_config as config, status_rules
except ImportError:  # pragma: no cover
    import factory_config as config
    import status_rules

_FIELDS = ("warning_low", "warning_high", "critical_low", "critical_high")

TTL = 15.0

_lock = threading.Lock()
_cache = {"at": 0.0, "rows": {}}


def _load():
    with config.db_cursor() as cur:
        cur.execute(
            "SELECT machine_id, sensor_type, warning_low, warning_high, "
            "critical_low, critical_high FROM sensor_thresholds"
        )
        rows = {}
        for machine_id, sensor_type, *values in cur.fetchall():
            rows[(machine_id, sensor_type)] = {
                name: (float(v) if v is not None else None)
                for name, v in zip(_FIELDS, values)
            }
    return rows


def _rows():
    now = time.monotonic()
    with _lock:
        if now - _cache["at"] > TTL:
            try:
                _cache["rows"] = _load()
                _cache["at"] = now
            except Exception:
                # Keep serving the last known limits if the DB hiccups.
                if not _cache["rows"]:
                    raise
                _cache["at"] = now - TTL + 3  # retry in ~3 s
        return _cache["rows"]


def invalidate():
    with _lock:
        _cache["at"] = 0.0


def get(machine_id, sensor_type):
    """Limits dict for one machine + sensor type."""
    rows = _rows()
    limits = rows.get((machine_id, sensor_type)) or rows.get((0, sensor_type))
    if limits is None:
        limits = status_rules.THRESHOLDS[sensor_type]
    return limits


def get_all(machine_id):
    return {sensor_type: get(machine_id, sensor_type) for sensor_type in status_rules.SENSORS}
