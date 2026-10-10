import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

import simulator as s

ZERO = lambda amplitude: 0.0
ROOT = Path(__file__).resolve().parent.parent


def test_m01_default_profile_stays_in_normal_range_without_faults():
    for t in range(0, 600):
        temp, hum, vib, press = s.twin_values(t, 24, 40, 1013.25, faults=False, noise=ZERO)
        assert 20 < temp < 33 and 40 <= hum <= 71 and 1 <= vib <= 4.1 and 1007 < press < 1019


def test_m01_fault_cycle_reaches_each_alarm_state():
    # humidity's sine wave only lines up with the leak in some cycles -> look at 3
    rows = [s.twin_values(t, 24, 40, 1013.25, noise=ZERO) for t in range(0, 360)]
    assert max(r[0] for r in rows) > 45      # temperature critical
    assert max(r[1] for r in rows) > 80      # humidity warning
    assert max(r[2] for r in rows) > 7       # vibration critical
    assert max(r[3] for r in rows) > 1050    # pressure warning


def test_m03_degradation_is_a_slow_monotonic_ramp():
    p = s.profile_for(3)
    vib = [s.twin_values(t, 24, 40, 1013.25, noise=ZERO, profile={**p, "faults": [], "vib_amp": 0})[2]
           for t in range(0, 800, 20)]
    assert vib == sorted(vib) and vib[-1] - vib[0] > 4


def test_payload_contract():
    payload = s.build_payload(2, 10.0)
    assert set(payload) == {"machine_id", "temperature", "humidity", "vibration", "pressure", "timestamp"}
    assert payload["machine_id"] == 2


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not installed")
def test_firmware_model_matches_python_model(tmp_path):
    """Compile the TWIN MODEL block of wokwi/sketch.ino and compare it with Python."""
    sketch = (ROOT / "wokwi" / "sketch.ino").read_text(encoding="utf-8")
    block = sketch[sketch.index("// BEGIN TWIN MODEL"):sketch.index("// END TWIN MODEL")]
    (tmp_path / "block.inc").write_text(block)
    (tmp_path / "h.cpp").write_text(textwrap.dedent("""
        #include <cmath>
        #include <cstdio>
        #define PI 3.14159265358979f
        #define constrain(x,a,b) ((x)<(a)?(a):((x)>(b)?(b):(x)))
        long random(long, long) { return 0; }
        #include "block.inc"
        int main() { for (int t = 0; t < 240; t++) { float T,H,V,P;
          twinValues((float)t, 24.0f, 40.0f, 1013.25f, 0.0f, true, T,H,V,P);
          printf("%d %.4f %.4f %.4f %.4f\\n", t, T,H,V,P); } }
    """))
    subprocess.run(["g++", "-std=c++17", "-o", str(tmp_path / "h"), str(tmp_path / "h.cpp")], check=True)
    out = subprocess.run([str(tmp_path / "h")], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        t, *vals = line.split()
        expected = s.twin_values(float(t), 24, 40, 1013.25, noise=ZERO)
        assert all(abs(float(a) - b) < 1e-3 for a, b in zip(vals, expected)), f"mismatch at t={t}"
