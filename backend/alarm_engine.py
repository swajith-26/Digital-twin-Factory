"""Alarm management (modelled on ISA-18.2 practice).

* **Debounce** - a limit must be breached on RAISE_AFTER consecutive
  readings before an alarm is raised (one noisy sample is not an alarm).
* **Hysteresis** - an alarm only clears after CLEAR_AFTER consecutive
  readings that are back inside the limit by a *deadband*, so a value
  hovering around a threshold cannot make the alarm flap on and off.
* **Escalation** - Warning -> Critical re-activates an acknowledged alarm,
  because the operator acknowledged a less severe situation.
* **Lifecycle** - active -> acknowledged -> cleared, stored in PostgreSQL with
  who/when, so history survives restarts and page refreshes.
* **One open alarm per machine + sensor** (enforced by a unique index).
"""

try:
    from . import status_rules, thresholds
except ImportError:  # pragma: no cover
    import status_rules
    import thresholds

RAISE_AFTER = 2
CLEAR_AFTER = 3

CONNECTIVITY = "connectivity"


class Tracker:
    """Pure debounce/hysteresis state machine (no database, easy to test)."""

    def __init__(self, raise_after=RAISE_AFTER, clear_after=CLEAR_AFTER):
        self.raise_after = raise_after
        self.clear_after = clear_after
        self._breaches = {}
        self._recoveries = {}

    def step(self, key, breaching, clearable, has_open):
        """Return "raise", "update", "clear" or "none" for one new reading."""
        if breaching:
            self._recoveries[key] = 0
            if has_open:
                return "update"
            self._breaches[key] = self._breaches.get(key, 0) + 1
            if self._breaches[key] >= self.raise_after:
                self._breaches[key] = 0
                return "raise"
            return "none"

        self._breaches[key] = 0
        if not has_open:
            return "none"

        if clearable:
            self._recoveries[key] = self._recoveries.get(key, 0) + 1
            if self._recoveries[key] >= self.clear_after:
                self._recoveries[key] = 0
                return "clear"
        else:
            self._recoveries[key] = 0
        return "none"


def inside_deadband(sensor_type, value, limits):
    """True when the value is back inside the warning limits by the deadband."""
    deadband = status_rules.DEADBAND.get(sensor_type, 0.0)
    high = limits.get("warning_high")
    low = limits.get("warning_low")
    if high is not None and value > high - deadband:
        return False
    if low is not None and value < low + deadband:
        return False
    return True


def _message(sensor_type, level, direction, value, limit):
    unit = status_rules.SENSORS[sensor_type]["unit"]
    side = "above" if direction == "high" else "below"
    return (
        f"{sensor_type.capitalize()} {value:.1f} {unit} {side} "
        f"{level.lower()} limit {limit:g} {unit}"
    )


class AlarmEngine:
    def __init__(self):
        self.tracker = Tracker()

    # ------------------------------------------------------------------
    # process-variable alarms
    # ------------------------------------------------------------------
    def process(self, cursor, machine_id, values):
        """Evaluate one telemetry message. Returns a list of alarm events."""
        cursor.execute(
            """
            SELECT id, sensor_type, severity, max_severity, direction, peak_value
            FROM alarms
            WHERE machine_id = %s AND cleared_at IS NULL AND sensor_type <> %s
            """,
            (machine_id, CONNECTIVITY),
        )
        open_alarms = {row[1]: row for row in cursor.fetchall()}
        events = []

        for sensor_type, value in values.items():
            limits = thresholds.get(machine_id, sensor_type)
            level, direction, limit = status_rules.evaluate_detail(sensor_type, value, limits)
            existing = open_alarms.get(sensor_type)

            action = self.tracker.step(
                (machine_id, sensor_type),
                breaching=level in (status_rules.WARNING, status_rules.CRITICAL),
                clearable=inside_deadband(sensor_type, value, limits),
                has_open=existing is not None,
            )

            if action == "raise":
                cursor.execute(
                    """
                    INSERT INTO alarms
                        (machine_id, sensor_type, severity, max_severity, direction,
                         trigger_value, peak_value, limit_value, message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (machine_id, sensor_type) WHERE cleared_at IS NULL
                    DO NOTHING
                    """,
                    (
                        machine_id, sensor_type, level, level, direction,
                        value, value, limit,
                        _message(sensor_type, level, direction, value, limit),
                    ),
                )
                events.append(("raised", machine_id, sensor_type, level, value))

            elif action == "update" and existing is not None:
                alarm_id, _, severity, max_severity, alarm_direction, peak = existing
                is_escalation = (
                    level == status_rules.CRITICAL
                    and max_severity != status_rules.CRITICAL
                )

                if is_escalation:
                    cursor.execute(
                        """
                        UPDATE alarms
                           SET severity = %s, max_severity = %s, state = 'active',
                               acknowledged_at = NULL, acknowledged_by = NULL,
                               limit_value = %s, message = %s,
                               peak_value = %s, direction = %s
                         WHERE id = %s
                        """,
                        (
                            level, level, limit,
                            _message(sensor_type, level, direction, value, limit),
                            value, direction, alarm_id,
                        ),
                    )
                    events.append(("escalated", machine_id, sensor_type, level, value))
                else:
                    if level != severity:
                        cursor.execute(
                            "UPDATE alarms SET severity = %s, limit_value = %s WHERE id = %s",
                            (level, limit, alarm_id),
                        )
                    more_extreme = peak is None or (
                        value > peak if alarm_direction != "low" else value < peak
                    )
                    if more_extreme:
                        cursor.execute(
                            "UPDATE alarms SET peak_value = %s WHERE id = %s",
                            (value, alarm_id),
                        )

            elif action == "clear" and existing is not None:
                cursor.execute(
                    "UPDATE alarms SET state = 'cleared', cleared_at = NOW() WHERE id = %s",
                    (existing[0],),
                )
                events.append(("cleared", machine_id, sensor_type, status_rules.NORMAL, value))

        return events

    # ------------------------------------------------------------------
    # connectivity alarms (device silent / MQTT Last Will "offline")
    # ------------------------------------------------------------------
    def raise_connectivity(self, cursor, machine_id, severity, message):
        cursor.execute(
            "SELECT id, severity FROM alarms "
            "WHERE machine_id = %s AND sensor_type = %s AND cleared_at IS NULL",
            (machine_id, CONNECTIVITY),
        )
        row = cursor.fetchone()

        if row is None:
            cursor.execute(
                """
                INSERT INTO alarms
                    (machine_id, sensor_type, severity, max_severity, message)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (machine_id, sensor_type) WHERE cleared_at IS NULL
                DO NOTHING
                """,
                (machine_id, CONNECTIVITY, severity, severity, message),
            )
            return [("raised", machine_id, CONNECTIVITY, severity, None)]

        if severity == status_rules.CRITICAL and row[1] != status_rules.CRITICAL:
            cursor.execute(
                """
                UPDATE alarms
                   SET severity = %s, max_severity = %s, state = 'active',
                       acknowledged_at = NULL, acknowledged_by = NULL, message = %s
                 WHERE id = %s
                """,
                (severity, severity, message, row[0]),
            )
            return [("escalated", machine_id, CONNECTIVITY, severity, None)]

        return []

    def clear_connectivity(self, cursor, machine_id):
        cursor.execute(
            "UPDATE alarms SET state = 'cleared', cleared_at = NOW() "
            "WHERE machine_id = %s AND sensor_type = %s AND cleared_at IS NULL",
            (machine_id, CONNECTIVITY),
        )
        if cursor.rowcount:
            return [("cleared", machine_id, CONNECTIVITY, status_rules.NORMAL, None)]
        return []
