import math
import random

import insights as i

VIB = {"warning_high": 4.5, "critical_high": 6.5}
TEMP = {"warning_high": 40.0, "critical_high": 45.0}


def series(fn, seconds=180, step=3):
    return [(t, fn(t)) for t in range(0, seconds, step)]


def test_linear_trend_recovers_slope():
    slope, r2, fitted = i.linear_trend([(t, 2 + 0.01 * t) for t in range(0, 100, 5)])
    assert math.isclose(slope, 0.01, rel_tol=1e-6)
    assert r2 > 0.999
    assert math.isclose(fitted, 2 + 0.01 * 95, rel_tol=1e-6)


def test_flat_noisy_signal_makes_no_prediction():
    rnd = random.Random(1)
    out = i.sensor_insight("vibration", series(lambda t: 2 + rnd.uniform(-0.3, 0.3)), VIB)
    assert out["prediction"] is None
    assert not out["anomaly"]


def test_oscillation_makes_no_false_prediction():
    out = i.sensor_insight("temperature", series(lambda t: 29 + 4 * math.sin(t / 12)), TEMP)
    assert out["prediction"] is None


def test_degrading_bearing_predicts_warning():
    rnd = random.Random(2)
    out = i.sensor_insight("vibration", series(lambda t: 2 + 0.006 * t + rnd.uniform(-0.2, 0.2)), VIB)
    p = out["prediction"]
    assert p and p["level"] == "Warning" and p["limit"] == 4.5
    assert 2 < p["minutes"] < 6          # (4.5 - ~3.1) / 0.36 per min


def test_already_beyond_warning_predicts_critical():
    rnd = random.Random(3)
    out = i.sensor_insight("vibration", series(lambda t: 4.6 + 0.006 * t + rnd.uniform(-0.1, 0.1)), VIB)
    assert out["prediction"]["level"] == "Critical"


def test_falling_value_predicts_low_limit():
    limits = {"warning_low": 30.0, "critical_low": 20.0}
    out = i.sensor_insight("humidity", series(lambda t: 50 - 0.05 * t), limits)
    assert out["prediction"]["level"] == "Warning"


def test_too_little_data_is_safe():
    out = i.sensor_insight("vibration", [(0, 1.0), (3, 1.1)], VIB)
    assert out["prediction"] is None and out["anomaly"] is False


def test_spike_is_flagged_as_anomaly():
    data = series(lambda t: 2.0 + (0.05 if t % 6 else -0.05))
    data[-5:] = [(t, 4.0) for t, _ in data[-5:]]
    assert i.sensor_insight("vibration", data, VIB)["anomaly"]


def test_sensor_health_curve_is_monotonic_and_anchored():
    scores = [i.sensor_health(v, 2.0, VIB) for v in (2, 3, 4, 4.5, 5.5, 6.5, 8, 12)]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 100
    assert 60 <= i.sensor_health(4.5, 2.0, VIB) <= 66      # at the warning limit
    assert 30 <= i.sensor_health(6.5, 2.0, VIB) <= 36      # at the critical limit
    assert i.sensor_health(20, 2.0, VIB) == 0


def test_two_sided_health_uses_the_nearer_limit():
    humid = {"warning_low": 30.0, "warning_high": 80.0, "critical_low": 20.0, "critical_high": 90.0}
    assert i.sensor_health(55, 55, humid) == 100
    assert i.sensor_health(25, 55, humid) < 60          # below warning-low
    assert i.sensor_health(85, 55, humid) < 60          # above warning-high


def test_machine_health_penalties():
    base = i.machine_health([100, 100, 100, 100], 0, None)
    assert base == 100
    assert i.machine_health([100, 100, 100, 100], 1, None) == 96
    assert i.machine_health([100, 100, 100, 100], 0, 5) == 90     # failure within 10 min
    assert i.machine_health([100, 100, 100, 100], 0, 20) == 95    # failure within 30 min
    assert i.machine_health([], 0, None) is None
    assert i.machine_health([10, 100, 100, 100], 0, None) < 60


def test_recommendations_are_prioritised():
    recs = i.recommendations({
        "temperature": {"status": "Normal", "prediction": None, "anomaly": True},
        "vibration": {"status": "Critical", "prediction": None, "anomaly": False},
        "pressure": {"status": "Normal", "prediction": {"level": "Warning", "minutes": 12.0}, "anomaly": False},
    })
    assert [r["priority"] for r in recs] == ["urgent", "medium", "low"]
    assert "bearings" in recs[0]["text"]
