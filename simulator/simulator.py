"""Digital Twin Factory - virtual machine fleet.

Each simulated machine behaves like a real edge device: its own MQTT
connection, the same topic and JSON structure as wokwi/sketch.ino, and an MQTT
*Last Will* so the platform learns immediately if it drops off the network.

    <prefix>/machineNN           telemetry (JSON, every few seconds)
    <prefix>/machineNN/status    "online" / "offline" (retained, Last Will)

Default: simulates M02, M03, M04 and leaves **M01 to the Wokwi ESP32**.
No Wokwi?  ``python simulator.py --all`` simulates all four machines.
Never simulate a machine that a real/Wokwi device is already publishing as -
their readings would interleave.

    python simulator.py                  # M02-M04, run until Ctrl+C
    python simulator.py --all            # M01-M04
    python simulator.py --machines 3     # only M03
    python simulator.py --speed 4        # 4x faster faults/degradation (demos)
    python simulator.py --count 20       # 20 messages per machine, then stop
    python simulator.py --no-faults      # healthy plant (no alarms)

Settings (optional env vars, same names as the backend): MQTT_BROKER,
MQTT_PORT, MQTT_TOPIC_PREFIX, MQTT_USERNAME, MQTT_PASSWORD.
"""

import argparse
import json
import math
import os
import random
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER = os.getenv("MQTT_BROKER", "test.mosquitto.org")
PORT = int(os.getenv("MQTT_PORT", "1883"))
_legacy_topic = os.getenv("MQTT_TOPIC", "")
TOPIC_PREFIX = (
    os.getenv("MQTT_TOPIC_PREFIX")
    or (_legacy_topic.rsplit("/", 1)[0] if "/" in _legacy_topic else "")
    or "digitaltwin/factory"
).strip("/")
PUBLISH_INTERVAL_SECONDS = 3

# Wokwi's default sensor readings (what the real DHT22 / BMP180 report while
# nobody touches the sliders). The twin varies around these ambient values.
AMBIENT_TEMPERATURE_C = 24.0
AMBIENT_HUMIDITY_PCT = 40.0
AMBIENT_PRESSURE_HPA = 1013.25

# ============================================================
# DIGITAL TWIN MODEL
# The default profile is identical to the "TWIN MODEL" block in
# wokwi/sketch.ino (a unit test keeps the two in sync).
# ============================================================

DEFAULT_PROFILE = {
    "cycle": 120.0,                       # fault scenario repeats every N s
    "heat": 3.0, "heat_amp": 4.0, "heat_period": 12.0,
    "hum": 15.0, "hum_amp": 15.0, "hum_period": 15.0,
    "vib": 2.5, "vib_amp": 1.5, "vib_period": 5.0,
    "press_amp": 5.0, "press_period": 20.0,
    "noise_t": 1.0, "noise_h": 2.0, "noise_v": 0.8, "noise_p": 1.0,
    # (sensor, start s, duration s, peak added)
    "faults": [
        ("vibration", 40, 20, 5.5),      # bearing wear
        ("temperature", 80, 24, 17.0),   # overheating
        ("humidity", 80, 24, 18.0),      # coolant leak
        ("pressure", 108, 10, 50.0),     # pressure surge
    ],
    # slow degradation: (sensor, slope per second, restart period s) - the
    # value creeps up until "maintenance" resets it. Great for prediction.
    "degrade": None,
}

# Each machine runs at its own operating point and fails in its own way.
MACHINE_PROFILES = {
    1: {},  # CNC Milling Center (normally the Wokwi ESP32)
    2: {    # Hydraulic Press: warm oil, heavy vibration, overheats mid-cycle
        "cycle": 150.0, "heat": 21.0, "heat_amp": 3.0,
        "vib": 3.5, "vib_amp": 1.0,
        "faults": [("temperature", 30, 30, 24.0), ("vibration", 95, 15, 4.5)],
    },
    3: {    # Conveyor Drive Motor: bearing slowly wears out (predictable!)
        "cycle": 180.0, "heat": 16.0, "heat_amp": 2.0,
        "vib": 2.0, "vib_amp": 0.5, "noise_v": 0.4,
        "faults": [("temperature", 60, 25, 20.0)],
        "degrade": ("vibration", 0.006, 840.0),
    },
    4: {    # Air Compressor: runs hot, pressure surges
        "cycle": 150.0, "heat": 34.0, "heat_amp": 4.0,
        "vib": 3.0, "vib_amp": 1.0, "press_amp": 6.0,
        "faults": [("pressure", 60, 12, 55.0), ("temperature", 100, 25, 24.0)],
    },
}


def profile_for(machine_id):
    return {**DEFAULT_PROFILE, **MACHINE_PROFILES.get(machine_id, {})}


def pulse(phase, start, duration, peak):
    """Smooth half-sine bump: 0 -> peak -> 0 between start and start+duration."""
    if phase < start or phase >= start + duration:
        return 0.0
    return peak * math.sin(math.pi * (phase - start) / duration)


def twin_values(t, ambient_t, ambient_h, ambient_p, jolt=0.0, faults=True,
                noise=None, profile=None):
    """Return (temperature, humidity, vibration, pressure) at time t (seconds).

    ambient_*: the base sensor readings the variation is applied around.
    jolt:      extra vibration measured by the accelerometer (|a| - 9.81).
    noise:     function(amplitude) -> random value in [-amplitude, +amplitude].
    profile:   machine profile (defaults to the ESP32 firmware's model).
    """
    p = profile or DEFAULT_PROFILE
    if noise is None:
        def noise(amplitude):
            return random.uniform(-amplitude, amplitude)

    phase = t % p["cycle"]
    bumps = {"temperature": 0.0, "humidity": 0.0, "vibration": 0.0, "pressure": 0.0}
    if faults:
        for sensor, start, duration, peak in p["faults"]:
            bumps[sensor] += pulse(phase, start, duration, peak)
        if p["degrade"]:
            sensor, slope, period = p["degrade"]
            bumps[sensor] += slope * (t % period)

    temperature = (ambient_t + p["heat"] + p["heat_amp"] * math.sin(t / p["heat_period"])
                   + noise(p["noise_t"]) + bumps["temperature"])
    humidity = (ambient_h + p["hum"] + p["hum_amp"] * math.sin(t / p["hum_period"])
                + noise(p["noise_h"]) + bumps["humidity"])
    vibration = (jolt + p["vib"] + p["vib_amp"] * math.sin(t / p["vib_period"])
                 + noise(p["noise_v"]) + bumps["vibration"])
    pressure = (ambient_p + p["press_amp"] * math.sin(t / p["press_period"])
                + noise(p["noise_p"]) + bumps["pressure"])

    return (
        min(max(temperature, -40.0), 80.0),     # DHT22 operating range
        min(max(humidity, 0.0), 100.0),
        min(max(vibration, 0.0), 20.0),
        min(max(pressure, 300.0), 1100.0),      # BMP180 operating range
    )


def build_payload(machine_id, t, faults=True):
    temperature, humidity, vibration, pressure = twin_values(
        t, AMBIENT_TEMPERATURE_C, AMBIENT_HUMIDITY_PCT, AMBIENT_PRESSURE_HPA,
        faults=faults, profile=profile_for(machine_id),
    )
    return {
        "machine_id": machine_id,
        "temperature": round(temperature, 2),
        "humidity": round(humidity, 2),
        "vibration": round(vibration, 2),
        "pressure": round(pressure, 2),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ============================================================
# ONE VIRTUAL EDGE DEVICE
# ============================================================

class VirtualMachine:
    def __init__(self, machine_id):
        self.machine_id = machine_id
        self.topic = f"{TOPIC_PREFIX}/machine{machine_id:02d}"
        self.status_topic = f"{self.topic}/status"
        self.connected = threading.Event()
        self.sent = 0

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"DigitalTwin-Sim-M{machine_id:02d}-{os.getpid()}",
        )
        username = os.getenv("MQTT_USERNAME")
        if username:
            self.client.username_pw_set(username, os.getenv("MQTT_PASSWORD"))
        # If this "device" dies, the broker tells everyone it is offline.
        self.client.will_set(self.status_topic, "offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.publish(self.status_topic, "online", qos=1, retain=True)
            self.connected.set()
        else:
            print(f"M{self.machine_id:02d}: MQTT connection refused ({reason_code})")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.connected.clear()

    def start(self):
        self.client.connect_async(BROKER, PORT, keepalive=30)
        self.client.loop_start()

    def stop(self):
        if self.connected.is_set():
            # Graceful shutdown: say so explicitly (the Last Will only fires
            # on an unexpected disconnect).
            self.client.publish(self.status_topic, "offline", qos=1, retain=True).wait_for_publish(2)
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, t, faults):
        payload = json.dumps(build_payload(self.machine_id, t, faults))
        result = self.client.publish(self.topic, payload)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            self.sent += 1
            return payload
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--machines", default="2,3,4",
                        help="comma-separated machine ids (default: 2,3,4 - M01 is the Wokwi ESP32)")
    parser.add_argument("--all", action="store_true", help="simulate M01-M04 (no Wokwi)")
    parser.add_argument("--count", type=int, default=0, help="stop after N messages per machine (0 = forever)")
    parser.add_argument("--interval", type=float, default=PUBLISH_INTERVAL_SECONDS)
    parser.add_argument("--speed", type=float, default=1.0,
                        help="run the fault/degradation scenarios N times faster")
    parser.add_argument("--no-faults", action="store_true", help="never simulate faults")
    args = parser.parse_args()

    ids = [1, 2, 3, 4] if args.all else sorted({int(x) for x in args.machines.split(",") if x.strip()})
    fleet = [VirtualMachine(i) for i in ids]

    print(f"Connecting {len(fleet)} virtual machine(s) to MQTT broker {BROKER}:{PORT} ...")
    for machine in fleet:
        machine.start()
    for machine in fleet:
        if not machine.connected.wait(timeout=15):
            for m in fleet:
                m.client.loop_stop()
            raise SystemExit(f"ERROR: could not connect to MQTT broker {BROKER}:{PORT}")

    print("Publishing to: " + ", ".join(m.topic for m in fleet))
    if 1 not in ids:
        print("M01 is expected from the Wokwi ESP32 (use --all to simulate it too).")
    print("Virtual factory running (Ctrl+C to stop)...\n")

    started = time.monotonic()
    faults = not args.no_faults
    rounds = 0
    try:
        while args.count == 0 or rounds < args.count:
            t = (time.monotonic() - started) * args.speed
            for machine in fleet:
                if not machine.connected.is_set():
                    print(f"M{machine.machine_id:02d}: waiting for MQTT reconnect...")
                    continue
                payload = machine.publish(t, faults)
                if payload:
                    print(f"[M{machine.machine_id:02d} #{machine.sent}] {payload}")
                time.sleep(0.05)  # devices don't all transmit in the same instant
            rounds += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopping virtual machines (publishing offline status)...")
    finally:
        for machine in fleet:
            machine.stop()


if __name__ == "__main__":
    main()
