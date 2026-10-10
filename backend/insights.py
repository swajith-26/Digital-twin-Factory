"""Condition monitoring: trends, anomalies, failure prediction, health score.

Everything here is a pure function of recent readings and alarm limits - no
database access - so it is deterministic and unit-tested.

These are transparent statistical heuristics (least-squares trend + z-score),
not a trained machine-learning model. They are intended to give operators
early warning, and are explained to the user in the dashboard.
"""

import math
import statistics

# Look at this much recent history when judging a trend.
TREND_WINDOW_SECONDS = 180
MIN_POINTS = 12

# A trend must be at least this steep (units per minute) and fit the data
# well (R^2) before we are willing to make a prediction from it.
MIN_SLOPE_PER_MIN = {
    "temperature": 0.8,
    "humidity": 2.0,
    "vibration": 0.25,
    "pressure": 3.0,
}
MIN_R2 = 0.55
PREDICTION_HORIZON_MIN = 30.0

# Smallest believable noise level per sensor, so a flat signal does not give
# huge z-scores from tiny wiggles.
MIN_STD = {"temperature": 0.3, "humidity": 0.8, "vibration": 0.15, "pressure": 0.8}
ANOMALY_Z = 3.5
RECENT_POINTS = 5


def linear_trend(points):
    """Least-squares line through ``[(t_seconds, value), ...]``.

    Returns ``(slope_per_second, r_squared, fitted_value_at_last_t)``.
    """
    n = len(points)
    if n < 2:
        return 0.0, 0.0, points[-1][1] if points else 0.0

    t0 = points[0][0]
    xs = [p[0] - t0 for p in points]
    ys = [p[1] for p in points]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, 0.0, mean_y

    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x

    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 0.0 if ss_tot == 0 else max(0.0, 1.0 - ss_res / ss_tot)

    return slope, r2, intercept + slope * xs[-1]


def anomaly_score(values, sensor_type):
    """Z-score of the newest few readings against the earlier baseline."""
    if len(values) < RECENT_POINTS + 8:
        return 0.0

    baseline, recent = values[:-RECENT_POINTS], values[-RECENT_POINTS:]
    std = max(statistics.pstdev(baseline), MIN_STD.get(sensor_type, 0.1))
    return (sum(recent) / len(recent) - sum(baseline) / len(baseline)) / std


def predict_breach(current, slope_per_min, limits):
    """When will the trend cross the *next* limit? ``None`` if it won't soon.

    Returns ``{"level", "limit", "minutes"}``.
    """
    if slope_per_min > 0:
        candidates = [
            ("Warning", limits.get("warning_high")),
            ("Critical", limits.get("critical_high")),
        ]
        candidates = [(lv, lim) for lv, lim in candidates if lim is not None and lim > current]
    else:
        candidates = [
            ("Warning", limits.get("warning_low")),
            ("Critical", limits.get("critical_low")),
        ]
        candidates = [(lv, lim) for lv, lim in candidates if lim is not None and lim < current]

    if not candidates:
        return None

    level, limit = candidates[0]
    minutes = (limit - current) / slope_per_min
    if not math.isfinite(minutes) or minutes < 0 or minutes > PREDICTION_HORIZON_MIN:
        return None

    return {"level": level, "limit": float(limit), "minutes": round(minutes, 1)}


def sensor_insight(sensor_type, series, limits):
    """Trend, anomaly and prediction for one sensor.

    ``series`` is ``[(t_seconds, value), ...]`` oldest -> newest.
    """
    if len(series) < MIN_POINTS:
        return {
            "trend_per_min": 0.0,
            "confidence": 0.0,
            "z_score": 0.0,
            "anomaly": False,
            "nominal": series[-1][1] if series else None,
            "prediction": None,
        }

    last_t = series[-1][0]
    window = [p for p in series if p[0] >= last_t - TREND_WINDOW_SECONDS]
    values = [p[1] for p in series]

    slope, r2, fitted = linear_trend(window) if len(window) >= MIN_POINTS else (0.0, 0.0, values[-1])
    slope_per_min = slope * 60.0
    z = anomaly_score([p[1] for p in window], sensor_type)

    prediction = None
    if r2 >= MIN_R2 and abs(slope_per_min) >= MIN_SLOPE_PER_MIN.get(sensor_type, 0.0):
        prediction = predict_breach(fitted, slope_per_min, limits)

    return {
        "trend_per_min": round(slope_per_min, 3),
        "confidence": round(r2, 2),
        "z_score": round(z, 2),
        "anomaly": abs(z) >= ANOMALY_Z,
        "nominal": round(statistics.median(values), 3),
        "prediction": prediction,
    }


def sensor_health(value, nominal, limits):
    """0-100 health of one sensor from how close it is to its limits.

    100 = at its usual level, ~65 = at the warning limit, ~35 = at the
    critical limit, 0 = well beyond critical.
    """
    def side(limit_warn, limit_crit, sign):
        # sign=+1 for a high limit, -1 for a low limit; work in "distance up".
        v, n = sign * value, sign * nominal
        w = sign * limit_warn
        c = sign * limit_crit if limit_crit is not None else w + abs(w) * 0.1 + 1
        if v <= w:
            span = max(w - n, 1e-9)
            stress = min(max((v - n) / span, 0.0), 1.0)
            return 100 - 35 * stress ** 2
        if v <= c:
            return 65 - 30 * (v - w) / max(c - w, 1e-9)
        return max(0.0, 35 - 35 * (v - c) / max(c - w, 1e-9))

    scores = []
    if limits.get("warning_high") is not None:
        scores.append(side(limits["warning_high"], limits.get("critical_high"), +1))
    if limits.get("warning_low") is not None:
        scores.append(side(limits["warning_low"], limits.get("critical_low"), -1))
    return min(scores) if scores else 100.0


def machine_health(sensor_scores, anomalies, soonest_prediction_min):
    """Combine sensor scores into one 0-100 machine health index."""
    if not sensor_scores:
        return None

    score = 0.6 * min(sensor_scores) + 0.4 * (sum(sensor_scores) / len(sensor_scores))
    score -= 4 * min(anomalies, 2)
    if soonest_prediction_min is not None:
        score -= 10 if soonest_prediction_min <= 10 else 5
    return int(round(max(0.0, min(100.0, score))))


_ADVICE = {
    "vibration": "Inspect bearings, shaft alignment and mounting bolts",
    "temperature": "Check cooling, lubrication and airflow",
    "pressure": "Inspect seals, relief valve and supply line",
    "humidity": "Check enclosure sealing and coolant/steam leaks",
    "connectivity": "Verify device power, network and MQTT connection",
}


def recommendations(sensor_states, open_connectivity=False):
    """Plain-language actions from live status, predictions and anomalies.

    ``sensor_states``: ``{sensor_type: {"status", "prediction", "anomaly"}}``.
    """
    actions = []

    if open_connectivity:
        actions.append({"priority": "high", "sensor": "connectivity", "text": _ADVICE["connectivity"]})

    for sensor_type, state in sensor_states.items():
        advice = _ADVICE.get(sensor_type, "Inspect the machine")
        prediction = state.get("prediction")

        if state.get("status") == "Critical":
            actions.append({"priority": "urgent", "sensor": sensor_type,
                            "text": f"Critical {sensor_type}: stop or derate the machine. {advice}"})
        elif state.get("status") == "Warning":
            actions.append({"priority": "high", "sensor": sensor_type,
                            "text": f"{sensor_type.capitalize()} above warning limit. {advice} soon"})
        elif prediction:
            actions.append({
                "priority": "medium" if prediction["minutes"] > 10 else "high",
                "sensor": sensor_type,
                "text": (f"{sensor_type.capitalize()} is trending towards its {prediction['level'].lower()} "
                         f"limit in about {prediction['minutes']:.0f} min. {advice}"),
            })
        elif state.get("anomaly"):
            actions.append({"priority": "low", "sensor": sensor_type,
                            "text": f"Unusual {sensor_type} behaviour detected (still within limits). Keep watching"})

    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    actions.sort(key=lambda a: order[a["priority"]])
    return actions
