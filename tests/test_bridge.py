import json
import subprocess
from types import SimpleNamespace

import pytest

import bridge
from pybmap.errors import BmapConnectionError, BmapError
from pybmap.types import BatteryReading, BatteryStatus, EqBand


def bluez_info(product_id="4082", bmap=True):
    uuid = "UUID: %s\n" % bridge.BMAP_UUID if bmap else ""
    return "%sModalias: bluetooth:v009Ep%sd0000\n" % (uuid, product_id)


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        ["bluetoothctl", "info"], returncode, stdout=stdout, stderr=stderr
    )


def test_resolve_device_uses_bluez_product_id(monkeypatch):
    monkeypatch.setattr(
        bridge.subprocess, "run", lambda *args, **kwargs: completed(bluez_info())
    )

    device = bridge.resolve_device("E4:58:BC:D4:97:95")

    assert device.config == "qc_ultra2"


@pytest.mark.parametrize("mac", ["", "not-a-mac", "AA:BB:CC:DD:EE:FF extra"])
def test_resolve_device_rejects_invalid_mac(mac):
    with pytest.raises(BmapError, match="Invalid Bluetooth address"):
        bridge.resolve_device(mac)


def test_resolve_device_rejects_non_bmap_device(monkeypatch):
    monkeypatch.setattr(
        bridge.subprocess, "run", lambda *args, **kwargs: completed(bluez_info(bmap=False))
    )

    with pytest.raises(BmapError, match="does not advertise Bose BMAP"):
        bridge.resolve_device("AA:BB:CC:DD:EE:FF")


def test_resolve_device_rejects_recognized_unsupported_product(monkeypatch):
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: completed(bluez_info(product_id="4024")),
    )

    with pytest.raises(BmapError, match="recognized but not supported"):
        bridge.resolve_device("AA:BB:CC:DD:EE:FF")


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


def test_set_equalizer_validates_reported_band_ranges():
    device = EqDevice()

    bridge.set_equalizer(device, -8, -2, 0)

    assert device.values == (-8, -2, 0)
    with pytest.raises(ValueError, match="Bass must be -10-10"):
        bridge.set_equalizer(device, -11, 0, 0)


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
