import status_rules as r


def test_default_thresholds():
    assert r.evaluate("temperature", 39.9) == r.NORMAL
    assert r.evaluate("temperature", 40.1) == r.WARNING
    assert r.evaluate("temperature", 45.1) == r.CRITICAL
    assert r.evaluate("humidity", 15) == r.CRITICAL
    assert r.evaluate("humidity", 25) == r.WARNING
    assert r.evaluate("pressure", 1060) == r.WARNING
    assert r.evaluate("pressure", 890) == r.CRITICAL


def test_boundaries_are_strict():
    assert r.evaluate("vibration", 5.0) == r.NORMAL
    assert r.evaluate("vibration", 7.0) == r.WARNING


def test_per_machine_limits_override_defaults():
    press = {"warning_high": 6.0, "critical_high": 8.5}
    assert r.evaluate("vibration", 5.5) == r.WARNING          # factory default
    assert r.evaluate("vibration", 5.5, press) == r.NORMAL    # hydraulic press
    assert r.evaluate("vibration", 9.0, press) == r.CRITICAL


def test_detail_reports_direction_and_limit():
    assert r.evaluate_detail("humidity", 15) == (r.CRITICAL, "low", 20.0)
    assert r.evaluate_detail("temperature", 41) == (r.WARNING, "high", 40.0)
    assert r.evaluate_detail("temperature", 20) == (r.NORMAL, None, None)


def test_worst_status():
    assert r.worst([r.NORMAL, r.WARNING, r.NORMAL]) == r.WARNING
    assert r.worst([r.WARNING, r.CRITICAL]) == r.CRITICAL
    assert r.worst([]) == r.NO_DATA
