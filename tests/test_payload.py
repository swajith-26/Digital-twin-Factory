import json

import pytest

import mqtt_subscriber as m

GOOD = {"machine_id": 2, "temperature": 27.4, "humidity": 55.1, "vibration": 2.7, "pressure": 1013.2,
        "timestamp": "2026-10-06T09:30:00Z"}


def raw(**overrides):
    d = {**GOOD, **overrides}
    return json.dumps({k: v for k, v in d.items() if v is not None}).encode()


def test_valid_payload():
    mid, values = m.parse_payload(raw(), 2)
    assert mid == 2 and values["temperature"] == 27.4 and set(values) == {
        "temperature", "humidity", "vibration", "pressure"}


def test_timestamp_null_is_accepted():
    # firmware sends "timestamp":null until NTP has synced
    assert m.parse_payload(b'{"machine_id":1,"temperature":1,"humidity":1,"vibration":1,"pressure":1000,"timestamp":null}', 1)


def test_machine_id_defaults_to_topic():
    assert m.parse_payload(raw(machine_id=None), 3)[0] == 3


def test_topic_mismatch_is_rejected():
    with pytest.raises(m.PayloadError, match="does not match its topic"):
        m.parse_payload(raw(machine_id=2), 3)


@pytest.mark.parametrize("payload", [
    b"not json", b"[1,2]", b'{"machine_id":2}',
    raw(temperature="hot"), raw(temperature=True), raw(temperature=999),
    raw(humidity=-5), raw(pressure=0 - 1), raw(machine_id=0), raw(machine_id="2"),
    b'{"machine_id":2,"temperature":NaN,"humidity":1,"vibration":1,"pressure":1000}',
])
def test_bad_payloads_rejected(payload):
    with pytest.raises(m.PayloadError):
        m.parse_payload(payload, 2)


def test_critical_values_still_accepted():
    # plausible-range check must be wider than the alarm limits
    assert m.parse_payload(raw(temperature=120, vibration=15, pressure=1099), 2)


@pytest.mark.parametrize("topic,expected", [
    ("digitaltwin/factory/machine01", 1), ("digitaltwin/factory/machine12", 12),
    ("digitaltwin/factory/machine03/status", 3), ("digitaltwin/factory/other", None),
])
def test_machine_id_from_topic(topic, expected):
    assert m.machine_id_from_topic(topic) == expected
