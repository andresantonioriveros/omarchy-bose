"""Tests for pybmap.discovery — BlueZ enumeration and BMAP identification."""

import subprocess
import sys

import pytest

from pybmap import discovery
from pybmap.catalog import BMAP_UUID


QC_ULTRA2 = "AA:BB:CC:DD:EE:01"
NCH_700 = "AA:BB:CC:DD:EE:02"
UNKNOWN_PID = "AA:BB:CC:DD:EE:03"
NON_BMAP = "AA:BB:CC:DD:EE:04"
NON_AUDIO = "AA:BB:CC:DD:EE:05"


def info_body(*lines):
    return "Device %s\n%s" % ("XX", "\n".join(lines))


def bose_info(product="4082", connected=True, uuid=BMAP_UUID,
              icon="audio-headphones"):
    lines = [
        "Name: Bose QC Ultra",
        "Icon: %s" % icon,
        "Paired: yes",
        "Connected: %s" % ("yes" if connected else "no"),
        "UUID: %s" % uuid,
        "Modalias: bluetooth:v009Ep%sd0000" % product,
    ]
    return info_body(*lines)


INFOS = {
    QC_ULTRA2: bose_info("4082", connected=True),
    NCH_700: bose_info("4024", connected=False),
    UNKNOWN_PID: bose_info("9999", connected=False),
    NON_BMAP: info_body(
        "Name: Other Headphones",
        "Icon: audio-headphones",
        "Paired: yes",
        "Connected: no",
        "Modalias: bluetooth:v009Ep9999d0000",
    ),
    NON_AUDIO: info_body(
        "Name: Bose Speaker",
        "Icon: audio-speaker",
        "Paired: yes",
        "Connected: no",
        "UUID: %s" % BMAP_UUID,
        "Modalias: bluetooth:v009Ep4085d0000",
    ),
}

PAIRED_OUTPUT = "".join(
    "Device %s Name\n" % mac
    for mac in [QC_ULTRA2, NCH_700, UNKNOWN_PID, NON_BMAP, NON_AUDIO,
                "not-a-mac"]
)


def fake_run_factory(infos=None, paired=PAIRED_OUTPUT, strict_macs=True):
    infos = infos if infos is not None else INFOS

    def fake_run(args, **kwargs):
        assert args[0] == discovery.BLUETOOTHCTL, args[0]
        if args[1:2] == ["devices"]:
            return subprocess.CompletedProcess(args, 0, stdout=paired)
        assert args[1:2] == ["info"]
        mac = args[2]
        if strict_macs:
            assert discovery._MAC_RE.match(mac), mac
        return subprocess.CompletedProcess(args, 0, stdout=infos[mac])

    return fake_run


requires_linux = pytest.mark.skipif(
    sys.platform == "darwin", reason="Linux BlueZ discovery"
)


def test_parse_product_id():
    assert discovery.parse_product_id("Modalias: bluetooth:v009Ep4082d0000") == 0x4082
    assert discovery.parse_product_id("Modalias: bluetooth:v009EP4024D0000") == 0x4024
    assert discovery.parse_product_id("no modalias here") is None
    assert discovery.parse_product_id("") is None
    assert discovery.parse_product_id(None) is None


def test_has_bmap_is_case_insensitive():
    assert discovery.has_bmap("UUID: %s" % BMAP_UUID)
    assert discovery.has_bmap("UUID: %s" % BMAP_UUID.upper())
    assert not discovery.has_bmap("UUID: 0000110b-0000-1000-8000-00805f9b34fb")
    assert not discovery.has_bmap("")


def test_is_audio_device():
    assert discovery.is_audio_device("Icon: audio-headphones")
    assert discovery.is_audio_device("Icon: audio-headset")
    assert not discovery.is_audio_device("Icon: audio-speaker")
    assert not discovery.is_audio_device("")


@requires_linux
def test_list_bmap_devices_enriches_supported_and_unsupported(monkeypatch):
    monkeypatch.setattr(
        discovery, "run_capped", fake_run_factory())

    devices = discovery.list_bmap_devices()
    by_address = {device["address"]: device for device in devices}

    assert set(by_address) == {QC_ULTRA2, NCH_700, UNKNOWN_PID}

    ultra2 = by_address[QC_ULTRA2]
    assert ultra2["productId"] == "0x4082"
    assert ultra2["config"] == "qc_ultra2"
    assert ultra2["name"] == "QuietComfort Ultra Headphones (2nd Gen)"
    assert ultra2["connected"] is True

    unsupported = by_address[NCH_700]
    assert unsupported["productId"] == "0x4024"
    assert unsupported["config"] is None
    assert unsupported["connected"] is False

    unknown = by_address[UNKNOWN_PID]
    assert unknown["productId"] == "0x9999"
    assert unknown["config"] is None
    assert unknown["name"] == ""


@requires_linux
def test_list_bmap_devices_empty_without_system_bluetoothctl(monkeypatch):
    monkeypatch.setattr(discovery, "BLUETOOTHCTL", "/nonexistent/bluetoothctl")

    assert discovery.list_bmap_devices() == []


@requires_linux
def test_list_bmap_devices_empty_without_bluetoothctl(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("bluetoothctl")

    monkeypatch.setattr(discovery, "run_capped", missing)

    assert discovery.list_bmap_devices() == []


@requires_linux
def test_list_bmap_devices_empty_on_gushing_paired_list(tmp_path, monkeypatch):
    stub = tmp_path / "bluetoothctl"
    stub.write_text(
        "#!%s\n" % sys.executable
        + "import sys\n"
        + "sys.stdout.write('Z' * 200000 + '\\nDevice %s Name\\n')\n" % QC_ULTRA2
    )
    stub.chmod(0o755)
    monkeypatch.setattr(discovery, "BLUETOOTHCTL", str(stub))

    # The valid MAC line sits past the cap: uncapped parsing would find it,
    # so [] proves the byte cap fired rather than the parser missing.
    assert discovery.list_bmap_devices() == []


@requires_linux
def test_list_bmap_devices_skips_gushing_device_info(tmp_path, monkeypatch):
    valid = bose_info("4082", connected=True)
    stub = tmp_path / "bluetoothctl"
    stub.write_text(
        "#!%s\n" % sys.executable
        + "import sys\n"
        + "if sys.argv[1:2] == ['devices']:\n"
        + "    sys.stdout.write('Device %s Name\\n')\n" % QC_ULTRA2
        + "else:\n"
        + "    sys.stdout.write('Z' * 200000 + '\\n' + %r + '\\n')\n" % valid
    )
    stub.chmod(0o755)
    monkeypatch.setattr(discovery, "BLUETOOTHCTL", str(stub))

    # The valid BMAP block sits past the cap: uncapped parsing would list
    # the device, so [] proves the byte cap fired rather than a parse miss.
    assert discovery.list_bmap_devices() == []


@requires_linux
def test_list_bmap_devices_skips_unreadable_device(monkeypatch):
    def flaky(args, **kwargs):
        assert args[0] == discovery.BLUETOOTHCTL, args[0]
        if args[1:2] == ["devices"]:
            paired = "".join(
                "Device %s Name\n" % mac for mac in [QC_ULTRA2, NCH_700])
            return subprocess.CompletedProcess(args, 0, stdout=paired)
        if args[2] == NCH_700:
            raise subprocess.TimeoutExpired(args, timeout=3)
        return subprocess.CompletedProcess(args, 0, stdout=INFOS[args[2]])

    monkeypatch.setattr(discovery, "run_capped", flaky)

    devices = discovery.list_bmap_devices()

    assert [device["address"] for device in devices] == [QC_ULTRA2]


@requires_linux
def test_list_bmap_devices_preserves_paired_order(monkeypatch):
    monkeypatch.setattr(
        discovery, "run_capped", fake_run_factory())

    devices = discovery.list_bmap_devices()

    assert [device["address"] for device in devices] == [
        QC_ULTRA2, NCH_700, UNKNOWN_PID]


def test_list_bmap_devices_is_public_api():
    import pybmap

    assert pybmap.list_bmap_devices is discovery.list_bmap_devices


@requires_linux
def test_find_bmap_device_prefers_connected(monkeypatch):
    monkeypatch.setattr(
        discovery, "run_capped", fake_run_factory())

    mac, device_type = discovery.find_bmap_device()

    assert mac == QC_ULTRA2
    assert device_type == "qc_ultra2"
