import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import bridge
from pybmap import subproc
from pybmap.catalog import BMAP_UUID
from pybmap.errors import BmapConnectionError, BmapError
from pybmap.types import BatteryReading, BatteryStatus, EqBand


def bluez_info(product_id="4082", bmap=True):
    uuid = "UUID: %s\n" % BMAP_UUID if bmap else ""
    return "%sModalias: bluetooth:v009Ep%sd0000\n" % (uuid, product_id)


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        ["bluetoothctl", "info"], returncode, stdout=stdout, stderr=stderr
    )


def test_resolve_device_uses_bluez_product_id(monkeypatch):
    monkeypatch.setattr(
        bridge, "run_capped", lambda *args, **kwargs: completed(bluez_info())
    )

    device = bridge.resolve_device("E4:58:BC:D4:97:95")

    assert device.config == "qc_ultra2"


@pytest.mark.parametrize("mac", ["", "not-a-mac", "AA:BB:CC:DD:EE:FF extra"])
def test_resolve_device_rejects_invalid_mac(mac):
    with pytest.raises(BmapError, match="Invalid Bluetooth address"):
        bridge.resolve_device(mac)


def test_resolve_device_rejects_non_bmap_device(monkeypatch):
    monkeypatch.setattr(
        bridge, "run_capped", lambda *args, **kwargs: completed(bluez_info(bmap=False))
    )

    with pytest.raises(BmapError, match="does not advertise Bose BMAP"):
        bridge.resolve_device("AA:BB:CC:DD:EE:FF")


def test_resolve_device_rejects_recognized_unsupported_product(monkeypatch):
    monkeypatch.setattr(
        bridge,
        "run_capped",
        lambda *args, **kwargs: completed(bluez_info(product_id="4024")),
    )

    with pytest.raises(BmapError, match="recognized but not supported"):
        bridge.resolve_device("AA:BB:CC:DD:EE:FF")


def test_resolve_device_ignores_shadow_bluetoothctl_in_path(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    shadow = tmp_path / "bluetoothctl"
    shadow.write_text("#!/bin/sh\necho shadow > \"%s\"\n" % marker)
    shadow.chmod(0o755)
    monkeypatch.setenv(
        "PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", "")
    )
    # Prove the shadow would win a PATH lookup.
    assert shutil.which("bluetoothctl") == str(shadow)

    seen = {}

    def fake_run(args, **kwargs):
        seen["argv0"] = args[0]
        return completed(bluez_info())

    monkeypatch.setattr(bridge, "run_capped", fake_run)

    device = bridge.resolve_device("AA:BB:CC:DD:EE:FF")

    assert device.config == "qc_ultra2"
    assert seen["argv0"] == "/usr/bin/bluetoothctl"
    assert not marker.exists()


def test_resolve_device_fails_closed_without_system_bluetoothctl(monkeypatch):
    monkeypatch.setattr(
        "pybmap.discovery.BLUETOOTHCTL", "/nonexistent/bluetoothctl"
    )

    with pytest.raises(BmapError, match="bluetoothctl is required"):
        bridge.resolve_device("AA:BB:CC:DD:EE:FF")


def test_resolve_device_fails_closed_on_gushing_bluetoothctl(tmp_path, monkeypatch):
    stub = tmp_path / "bluetoothctl"
    stub.write_text(
        "#!%s\nimport sys; sys.stdout.write('A' * 300000)\n" % sys.executable
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr("pybmap.discovery.BLUETOOTHCTL", str(stub))

    with pytest.raises(BmapError, match="too much data"):
        bridge.resolve_device("AA:BB:CC:DD:EE:FF")


def test_panel_path_needs_no_environment(tmp_path, monkeypatch):
    # The panel launches children with a scrubbed environment: prove the
    # panel path functions with nothing in it at all. Note this must empty
    # the real process environment, not just rebind os.environ -- execve
    # with env=None inherits the C-level environ either way, which is
    # exactly why the scrubbing has to happen panel-side. (A Python stub
    # would self-report LC_CTYPE, and shells self-add PWD/SHLVL, so the
    # assertion is function -- not byte-identical emptiness.)
    for key in list(os.environ):
        monkeypatch.delenv(key, raising=False)
    assert bridge.bluetoothctl_path() in (None, "/usr/bin/bluetoothctl")

    stub = tmp_path / "probe"
    stub.write_text("#!%s\nprint('ok')\n" % sys.executable)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    result = bridge.run_capped([str(stub)], timeout=5)
    assert result.returncode == 0
    assert result.stdout == "ok\n"


def test_hostile_loader_env_fails_closed(tmp_path, monkeypatch):
    # LD_PRELOAD / PYTHONPATH poison hits every child at exec time; the
    # bridge must still fail closed as BmapError, never crash or hang.
    monkeypatch.setenv("LD_PRELOAD", "/nonexistent/evil.so")
    monkeypatch.setenv("PYTHONPATH", "/nonexistent/evil")
    stub = tmp_path / "bluetoothctl"
    stub.write_text(
        "#!%s\nimport sys; sys.stdout.write('x')\n" % sys.executable
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr("pybmap.discovery.BLUETOOTHCTL", str(stub))

    with pytest.raises(BmapError):
        bridge.resolve_device("AA:BB:CC:DD:EE:FF")


def _wait_for_pid_files(paths, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(path.exists() for path in paths):
            return [int(path.read_text()) for path in paths]
        time.sleep(0.02)
    raise AssertionError("child pid files were not created")


def _pid_is_running(pid):
    try:
        state = Path("/proc/%d/stat" % pid).read_text().split()[2]
    except (OSError, IndexError):
        return False
    return state != "Z"


def _wait_for_pids_to_stop(pids, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_pid_is_running(pid) for pid in pids):
            return
        time.sleep(0.02)
    raise AssertionError("child processes still running: %r" % pids)


def _cleanup_processes(proc, pids):
    if proc.poll() is None:
        proc.kill()
        proc.wait()
    for pid in pids:
        if _pid_is_running(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _sleep_probe(tmp_path):
    probe = tmp_path / "sleep_probe.py"
    probe.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    return probe


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process lifecycle")
def test_sigterm_forwards_to_all_concurrent_children(tmp_path):
    python_dir = Path(__file__).resolve().parent.parent / "bosectl" / "python"
    probe = _sleep_probe(tmp_path)
    pid_files = [tmp_path / ("child-%d.pid" % index) for index in range(3)]
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import concurrent.futures, sys\n"
        "sys.path.insert(0, %r)\n" % str(python_dir)
        + "from pybmap import subproc\n"
        + "subproc.install_terminate_forwarding()\n"
        + "def run(path):\n"
        + "    subproc.run_capped([sys.executable, %r, path], timeout=60)\n"
        % str(probe)
        + "with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:\n"
        + "    list(pool.map(run, sys.argv[1:]))\n"
    )
    proc = subprocess.Popen(
        [sys.executable, str(driver), *map(str, pid_files)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pids = []
    try:
        pids = _wait_for_pid_files(pid_files)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 143
        _wait_for_pids_to_stop(pids)
    finally:
        _cleanup_processes(proc, pids)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux parent-death signal")
def test_child_dies_when_bridge_is_sigkilled(tmp_path):
    python_dir = Path(__file__).resolve().parent.parent / "bosectl" / "python"
    probe = _sleep_probe(tmp_path)
    pid_file = tmp_path / "child.pid"
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import sys\n"
        "sys.path.insert(0, %r)\n" % str(python_dir)
        + "from pybmap import subproc\n"
        + "subproc.run_capped([sys.executable, %r, %r], timeout=60)\n"
        % (str(probe), str(pid_file))
    )
    proc = subprocess.Popen([sys.executable, str(driver)])
    pids = []
    try:
        pids = _wait_for_pid_files([pid_file])
        proc.kill()
        assert proc.wait(timeout=10) == -signal.SIGKILL
        _wait_for_pids_to_stop(pids)
    finally:
        _cleanup_processes(proc, pids)


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX process groups")
def test_sigterm_kills_descendants_in_child_process_group(tmp_path):
    python_dir = Path(__file__).resolve().parent.parent / "bosectl" / "python"
    direct_pid = tmp_path / "direct.pid"
    nested_pid = tmp_path / "nested.pid"
    probe = tmp_path / "tree_probe.py"
    probe.write_text(
        "import os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "subprocess.Popen([sys.executable, '-c', "
        "'import os,sys,time; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)', "
        "sys.argv[2]])\n"
        "time.sleep(60)\n"
    )
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import sys\n"
        "sys.path.insert(0, %r)\n" % str(python_dir)
        + "from pybmap import subproc\n"
        + "subproc.install_terminate_forwarding()\n"
        + "subproc.run_capped([sys.executable, %r, %r, %r], timeout=60)\n"
        % (str(probe), str(direct_pid), str(nested_pid))
    )
    proc = subprocess.Popen([sys.executable, str(driver)])
    pids = []
    try:
        pids = _wait_for_pid_files([direct_pid, nested_pid])
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 143
        _wait_for_pids_to_stop(pids)
    finally:
        _cleanup_processes(proc, pids)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux parent-death signal")
def test_spawn_registration_window_cannot_orphan_child(tmp_path):
    python_dir = Path(__file__).resolve().parent.parent / "bosectl" / "python"
    probe = _sleep_probe(tmp_path)
    pid_file = tmp_path / "child.pid"
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import sys, time\n"
        "sys.path.insert(0, %r)\n" % str(python_dir)
        + "from pybmap import subproc\n"
        + "real_popen = subproc.subprocess.Popen\n"
        + "def delayed_popen(*args, **kwargs):\n"
        + "    child = real_popen(*args, **kwargs)\n"
        + "    time.sleep(60)\n"
        + "    return child\n"
        + "subproc.subprocess.Popen = delayed_popen\n"
        + "subproc.install_terminate_forwarding()\n"
        + "subproc.run_capped([sys.executable, %r, %r], timeout=60)\n"
        % (str(probe), str(pid_file))
    )
    proc = subprocess.Popen([sys.executable, str(driver)])
    pids = []
    try:
        pids = _wait_for_pid_files([pid_file])
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 143
        _wait_for_pids_to_stop(pids)
    finally:
        _cleanup_processes(proc, pids)


def test_active_children_cleared_after_run():
    subproc.run_capped(
        [sys.executable, "-c", "print('hi')"], timeout=10
    )
    assert subproc._active_children == set()


def test_main_does_not_replace_callers_sigterm_handler(monkeypatch, capsys):
    previous = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(bridge, "scan_bose_devices", lambda: [])

    assert bridge.main(["scan"]) == 0
    capsys.readouterr()

    assert signal.getsignal(signal.SIGTERM) is previous


@pytest.mark.skipif(shutil.which("qs") is None, reason="requires Quickshell")
def test_quickshell_process_clears_environment():
    fixture = Path(__file__).with_name("process_environment.qml")

    result = subprocess.run(
        ["qs", "--no-color", "--path", str(fixture)],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "RESULT pass" in result.stdout + result.stderr


def test_resolve_device_truncates_hostile_error_detail(monkeypatch):
    def hostile(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="E" * 5000)

    monkeypatch.setattr(bridge, "run_capped", hostile)

    with pytest.raises(BmapError) as caught:
        bridge.resolve_device("AA:BB:CC:DD:EE:FF")

    assert len(str(caught.value)) <= bridge.ERROR_DETAIL_LIMIT


def test_emit_json_prints_small_payloads(capsys):
    bridge.emit_json({"schemaVersion": 1})

    assert json.loads(capsys.readouterr().out) == {"schemaVersion": 1}


def test_emit_json_refuses_huge_payloads():
    with pytest.raises(BmapError, match="exceeded"):
        bridge.emit_json({"devices": ["D" * 100000]})


def test_emit_json_cap_includes_trailing_newline(monkeypatch, capsys):
    payload = {"schemaVersion": 1, "padding": "x"}
    wire = json.dumps(payload, separators=(",", ":")) + "\n"
    monkeypatch.setattr(bridge, "OUTPUT_CAP_BYTES", len(wire.encode("utf-8")))

    bridge.emit_json(payload)
    assert capsys.readouterr().out == wire

    monkeypatch.setattr(bridge, "OUTPUT_CAP_BYTES", len(wire.encode("utf-8")) - 1)
    with pytest.raises(BmapError, match="exceeded"):
        bridge.emit_json(payload)


def test_main_caps_all_error_output(monkeypatch, capsys):
    monkeypatch.setattr(
        bridge,
        "scan_bose_devices",
        lambda: (_ for _ in ()).throw(BmapError("😀" * 10000)),
    )

    assert bridge.main(["scan"]) == 1
    error = capsys.readouterr().err
    assert len(error.encode("utf-8")) <= bridge.ERROR_OUTPUT_CAP_BYTES
    assert error.endswith("\n")


def test_scan_fails_closed_on_huge_device_list(monkeypatch, capsys):
    monkeypatch.setattr(
        bridge,
        "scan_bose_devices",
        lambda: [
            {"address": "AA:BB:CC:DD:EE:%02X" % i, "name": "D" * 500}
            for i in range(500)
        ],
    )

    assert bridge.main(["scan"]) == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "message",
    [
        "[Errno 16] Device or resource busy",
        "[Errno 111] Connection refused",
    ],
)
def test_connect_device_retries_transient_error(monkeypatch, message):
    connection = object()
    attempts = []
    delays = []

    def connect(**kwargs):
        attempts.append(kwargs)
        if len(attempts) < 3:
            raise BmapConnectionError(message)
        return connection

    monkeypatch.setattr(bridge.pybmap, "connect", connect)
    monkeypatch.setattr(bridge.time, "sleep", delays.append)

    result = bridge.connect_device("AA:BB:CC:DD:EE:FF", "qc_ultra2")

    assert result is connection
    assert len(attempts) == 3
    assert delays == [0.5, 1.0]


def test_connect_device_does_not_retry_other_errors(monkeypatch):
    delays = []

    def connect(**_kwargs):
        raise BmapConnectionError("Host is down")

    monkeypatch.setattr(bridge.pybmap, "connect", connect)
    monkeypatch.setattr(bridge.time, "sleep", delays.append)

    with pytest.raises(BmapConnectionError, match="Host is down"):
        bridge.connect_device("AA:BB:CC:DD:EE:FF", "qc_ultra2")

    assert delays == []


class StatusDevice:
    battery_components = {1: "Right", 2: "Left", 3: "Case"}
    preset_modes = {
        "quiet": {"idx": 0, "description": "Quiet - full cancellation"},
        "aware": {"idx": 1, "description": "Aware - transparency"},
    }

    def battery_status(self):
        return BatteryStatus(
            aggregate=60,
            readings=[
                BatteryReading(1, 50),
                BatteryReading(2, 60),
                BatteryReading(3, 80),
                BatteryReading(4, 60),
            ],
        )

    def has_feature(self, name):
        return name in ("current_mode", "cnc")

    def mode(self):
        return "My\nCommute"

    def cnc(self):
        return (3, 10)


def test_panel_status_is_lean_structured_snapshot():
    identity = SimpleNamespace(
        config="qc_ultra2_earbuds",
        name="QuietComfort Ultra Earbuds (2nd Gen)",
        product_id=0x4062,
    )

    status = bridge.panel_status(StatusDevice(), identity, "aa:bb:cc:dd:ee:ff")

    assert status["schemaVersion"] == 1
    assert status["device"]["type"] == "qc_ultra2_earbuds"
    assert status["battery"] == {
        "level": 60,
        "components": {"right": 50, "left": 60, "case": 80},
    }
    assert status["mode"]["currentId"] == ""
    assert status["mode"]["currentLabel"] == "My\nCommute"
    assert status["noiseControl"] == {"available": True, "level": 7, "maximum": 10}
    assert status["multipoint"] == {
        "available": False,
        "enabled": False,
        "activeSource": None,
    }
    assert status["equalizer"] == {"available": False, "bands": []}
    assert json.loads(json.dumps(status))["mode"]["currentLabel"] == "My\nCommute"


def test_panel_status_hides_unresolved_mode_index():
    device = StatusDevice()
    device.mode = lambda: "unknown(255)"
    identity = SimpleNamespace(
        config="qc_ultra2",
        name="QuietComfort Ultra Headphones (2nd Gen)",
        product_id=0x4082,
    )

    status = bridge.panel_status(device, identity, "aa:bb:cc:dd:ee:ff")

    assert status["mode"]["currentId"] == ""
    assert status["mode"]["currentLabel"] == ""


class MultipointStatusDevice(StatusDevice):
    def has_feature(self, name):
        return name in ("current_mode", "cnc", "multipoint", "source")

    def multipoint(self):
        return True

    def source(self):
        return SimpleNamespace(
            source_type="bluetooth",
            source_mac="ac:f2:3c:35:10:de",
        )


def test_panel_status_includes_multipoint_and_active_source():
    identity = SimpleNamespace(
        config="qc_ultra2",
        name="QuietComfort Ultra Headphones (2nd Gen)",
        product_id=0x4082,
    )

    status = bridge.panel_status(
        MultipointStatusDevice(), identity, "aa:bb:cc:dd:ee:ff"
    )

    assert status["multipoint"] == {
        "available": True,
        "enabled": True,
        "activeSource": {
            "type": "bluetooth",
            "address": "AC:F2:3C:35:10:DE",
        },
    }


def test_panel_status_tolerates_unavailable_multipoint_reads():
    device = MultipointStatusDevice()

    def unavailable():
        raise BmapError("unavailable")

    device.multipoint = unavailable
    device.source = unavailable
    identity = SimpleNamespace(
        config="qc_ultra2",
        name="QuietComfort Ultra Headphones (2nd Gen)",
        product_id=0x4082,
    )

    status = bridge.panel_status(device, identity, "aa:bb:cc:dd:ee:ff")

    assert status["battery"]["level"] == 60
    assert status["multipoint"] == {
        "available": False,
        "enabled": False,
        "activeSource": None,
    }


class EqDevice:
    def __init__(self, bands=None):
        self.bands = bands or [
            EqBand(2, "Treble", -10, 10, 3),
            EqBand(0, "Bass", -10, 10, -2),
            EqBand(1, "Mid", -10, 10, 0),
        ]
        self.values = None

    def has_feature(self, name):
        return name == "eq"

    def eq(self):
        return self.bands

    def set_eq(self, bass, mid, treble):
        self.values = (bass, mid, treble)


def test_equalizer_status_normalizes_band_order_and_labels():
    assert bridge.equalizer_status(EqDevice()) == {
        "available": True,
        "bands": [
            {"id": "bass", "label": "Bass", "minimum": -10, "maximum": 10, "value": -2},
            {"id": "mid", "label": "Mid", "minimum": -10, "maximum": 10, "value": 0},
            {"id": "treble", "label": "Treble", "minimum": -10, "maximum": 10, "value": 3},
        ],
    }


def test_equalizer_status_rejects_incomplete_response():
    device = EqDevice([EqBand(0, "Bass", -10, 10, 0)])

    assert bridge.equalizer_status(device) == {"available": False, "bands": []}


@pytest.mark.parametrize(
    "bands",
    [
        [
            EqBand(0, "Bass", -10, 10, 0),
            EqBand(0, "Bass", -10, 10, 0),
            EqBand(2, "Treble", -10, 10, 0),
        ],
        [
            EqBand(0, "Bass", -10, 10, 0),
            EqBand(1, "Mid", -10, 10, 0),
            EqBand(2, "Treble", -10, 10, 0),
            EqBand(3, "Extra", -10, 10, 0),
        ],
        [
            EqBand(0, "Bass", -10, 10, 11),
            EqBand(1, "Mid", -10, 10, 0),
            EqBand(2, "Treble", -10, 10, 0),
        ],
    ],
)
def test_equalizer_status_rejects_invalid_band_sets(bands):
    assert bridge.equalizer_status(EqDevice(bands)) == {
        "available": False,
        "bands": [],
    }


def test_equalizer_status_limits_values_to_writable_range():
    device = EqDevice([
        EqBand(0, "Bass", -20, 20, -10),
        EqBand(1, "Mid", -20, 20, 0),
        EqBand(2, "Treble", -20, 20, 10),
    ])

    status = bridge.equalizer_status(device)

    assert status["available"] is True
    assert [(band["minimum"], band["maximum"]) for band in status["bands"]] == [
        (-10, 10),
        (-10, 10),
        (-10, 10),
    ]


def test_set_equalizer_validates_reported_band_ranges():
    device = EqDevice()

    bridge.set_equalizer(device, -8, -2, 0)

    assert device.values == (-8, -2, 0)
    with pytest.raises(ValueError, match="Bass must be -10-10"):
        bridge.set_equalizer(device, -11, 0, 0)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ((11, 0, 0), "Bass must be -10-10"),
        ((0, -11, 0), "Mid must be -10-10"),
        ((0, 0, 11), "Treble must be -10-10"),
    ],
)
def test_set_equalizer_rejects_each_out_of_range_band(values, message):
    device = EqDevice()

    with pytest.raises(ValueError, match=message):
        bridge.set_equalizer(device, *values)

    assert device.values is None


def test_equalizer_arguments_require_three_integers():
    args = bridge.argument_parser().parse_args([
        "--mac", "AA:BB:CC:DD:EE:FF", "eq", "-8", "-2", "0"
    ])

    assert (args.bass, args.mid, args.treble) == (-8, -2, 0)


class ModeDevice:
    preset_modes = {"high": {"idx": 0}}

    def __init__(self, features):
        self.features = features
        self.calls = []

    def has_feature(self, name):
        return name in self.features

    def set_anr(self, name):
        self.calls.append(("anr", name))

    def set_mode(self, name):
        self.calls.append(("mode", name))


def test_set_mode_uses_anr_for_qc35():
    device = ModeDevice({"anr"})

    bridge.set_mode(device, "high")

    assert device.calls == [("anr", "high")]


def test_set_mode_uses_audio_modes_for_newer_devices():
    device = ModeDevice({"current_mode"})

    bridge.set_mode(device, "high")

    assert device.calls == [("mode", "high")]


def test_set_mode_rejects_unadvertised_option():
    with pytest.raises(BmapError, match="Unsupported listening mode"):
        bridge.set_mode(ModeDevice({"current_mode"}), "custom")


class CncDevice:
    def __init__(self):
        self.level = None

    def has_feature(self, name):
        return name == "cnc"

    def cnc(self):
        return (2, 10)

    def set_cnc(self, level):
        self.level = level


def test_set_cancellation_converts_to_vendor_scale():
    device = CncDevice()

    bridge.set_cancellation(device, 7)

    assert device.level == 3


def test_set_cancellation_rejects_malformed_reading():
    device = CncDevice()
    device.cnc = lambda: None

    with pytest.raises(BmapError, match="invalid state"):
        bridge.set_cancellation(device, 7)


def test_panel_status_degrades_malformed_cnc_to_unavailable():
    device = StatusDevice()
    device.cnc = lambda: None
    identity = SimpleNamespace(
        config="qc_ultra2",
        name="QuietComfort Ultra Headphones (2nd Gen)",
        product_id=0x4082,
    )

    status = bridge.panel_status(device, identity, "aa:bb:cc:dd:ee:ff")

    assert status["battery"]["level"] == 60
    assert status["noiseControl"] == {
        "available": False,
        "level": -1,
        "maximum": 0,
    }


def test_scan_bose_devices_keeps_only_supported_configs(monkeypatch):
    monkeypatch.setattr(
        bridge,
        "list_bmap_devices",
        lambda: [
            {
                "address": "AA:BB:CC:DD:EE:01",
                "productId": "0x4082",
                "name": "QuietComfort Ultra Headphones (2nd Gen)",
                "config": "qc_ultra2",
                "connected": True,
            },
            {
                "address": "AA:BB:CC:DD:EE:02",
                "productId": "0x4024",
                "name": "Noise Cancelling Headphones 700",
                "config": None,
                "connected": False,
            },
        ],
    )

    devices = bridge.scan_bose_devices()

    assert devices == [
        {
            "address": "AA:BB:CC:DD:EE:01",
            "productId": "0x4082",
            "name": "QuietComfort Ultra Headphones (2nd Gen)",
            "config": "qc_ultra2",
            "connected": True,
        }
    ]


@pytest.mark.parametrize("command", ["scan", "list"])
def test_scan_commands_emit_versioned_device_list(monkeypatch, capsys, command):
    monkeypatch.setattr(
        bridge,
        "scan_bose_devices",
        lambda: [
            {
                "address": "AA:BB:CC:DD:EE:FF",
                "productId": "0x4082",
                "name": "QuietComfort Ultra Headphones (2nd Gen)",
                "config": "qc_ultra2",
                "connected": True,
            }
        ],
    )

    assert bridge.main([command]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "schemaVersion": 1,
        "devices": [
            {
                "address": "AA:BB:CC:DD:EE:FF",
                "productId": "0x4082",
                "name": "QuietComfort Ultra Headphones (2nd Gen)",
                "config": "qc_ultra2",
                "connected": True,
            }
        ],
    }
