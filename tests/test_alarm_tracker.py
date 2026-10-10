import alarm_engine as a

LIMITS = {"warning_high": 40.0, "critical_high": 45.0}
K = (1, "temperature")


def run(tracker, steps):
    """steps: list of (breaching, clearable, has_open) -> list of actions."""
    return [tracker.step(K, *s) for s in steps]


def test_single_noisy_sample_does_not_raise():
    t = a.Tracker()
    assert run(t, [(True, False, False), (False, True, False), (True, False, False)]) == ["none"] * 3


def test_raises_after_consecutive_breaches():
    t = a.Tracker()
    assert run(t, [(True, False, False), (True, False, False)]) == ["none", "raise"]


def test_open_alarm_updates_while_breaching():
    t = a.Tracker()
    assert t.step(K, True, False, True) == "update"


def test_clears_only_after_consecutive_recoveries_inside_deadband():
    t = a.Tracker()
    seq = [(False, True, True)] * 3
    assert run(t, seq) == ["none", "none", "clear"]


def test_hovering_in_deadband_never_clears():
    t = a.Tracker()
    # value is Normal but not far enough inside the limit -> not clearable
    assert run(t, [(False, False, True)] * 10) == ["none"] * 10


def test_recovery_streak_resets_on_relapse():
    t = a.Tracker()
    seq = [(False, True, True), (False, True, True), (True, False, True), (False, True, True), (False, True, True)]
    assert run(t, seq) == ["none", "none", "update", "none", "none"]


def test_deadband_check():
    assert a.inside_deadband("temperature", 38.5, LIMITS)       # 1.5 below 40
    assert not a.inside_deadband("temperature", 39.5, LIMITS)   # inside deadband of 1.0
    assert not a.inside_deadband("temperature", 41.0, LIMITS)
    low = {"warning_low": 30.0}
    assert a.inside_deadband("humidity", 33, low)
    assert not a.inside_deadband("humidity", 31, low)
