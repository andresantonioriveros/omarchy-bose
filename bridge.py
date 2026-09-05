#!/usr/bin/python3
"""Small machine-readable adapter between the Omarchy panel and pybmap."""

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bosectl" / "python"))

import pybmap
from pybmap.discovery import (
    bluetoothctl_path,
    bose_identity,
    has_bmap,
    list_bmap_devices,
)
from pybmap.errors import BmapConnectionError, BmapError
from pybmap.subproc import (
    OutputTooLarge,
    install_terminate_forwarding,
    run_capped,
)


SCHEMA_VERSION = 1
# Producer-side cap for everything this bridge prints: the panel buffers
# child output to end-of-stream, so the bridge itself must guarantee small
# output rather than trusting it. Real payloads are a few KiB; anything past
# the cap fails closed instead of reaching the panel's JSON parser.
OUTPUT_CAP_BYTES = 65536
# bluetoothctl stderr on failure is device-influenced free text echoed into
# our one-line errors: keep the gist, drop the rest.
ERROR_DETAIL_LIMIT = 500
# The persisted selection is one tiny JSON document; anything bigger is not
# ours. All checks below run against the opened fd (never a re-looked-up
# path), so a swap between check and use cannot redirect them.
SELECTION_MAX_BYTES = 4096
MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def selection_path():
    """Where the panel persists the explicitly selected device address."""
    return Path.home() / ".local" / "state" / "omarchy" / "omabose.json"


def selection_load():
    """Read the persisted selection, degrading to empty on any problem.

    Missing, oversized, non-regular, foreign-owned, symlinked, or
    unparsable state all mean the same thing: no usable preference.
    Returns {"selectedAddress": mac-or-""}.
    """
    try:
        fd = os.open(selection_path(), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return {"selectedAddress": ""}
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_size > SELECTION_MAX_BYTES
        ):
            return {"selectedAddress": ""}
        # Regular files return up to the request in one read; anything past
        # the cap means the file grew under us, which also refuses.
        raw = os.read(fd, SELECTION_MAX_BYTES + 1)
        text = raw.decode("utf-8", "replace")
    except OSError:
        return {"selectedAddress": ""}
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    if len(raw) > SELECTION_MAX_BYTES:
        return {"selectedAddress": ""}
    try:
        obj = json.loads(text)
    except ValueError:
        return {"selectedAddress": ""}
    addr = str((obj or {}).get("selectedAddress") or "").upper()
    return {"selectedAddress": addr if MAC_RE.fullmatch(addr) else ""}


def selection_save(mac):
    """Persist the explicitly selected device address, atomically.

    Empty mac clears the preference. Refuses anything that is not a MAC
    (raising, for the CLI caller to report).
    Writes to a fresh O_EXCL temp file (0600) and renames over the state
    path, so a pre-existing symlink is replaced rather than followed and
    a partial write can never be observed.
    """
    if mac and not MAC_RE.fullmatch(mac):
        raise BmapError("Invalid Bluetooth address")
    payload = {"selectedAddress": mac.upper()} if mac else {}
    # Same shape the panel historically wrote, so existing state keeps
    # working byte for byte.
    text = json.dumps(payload, indent=2) + "\n"
    path = selection_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".omabose-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
CONNECTION_RETRY_DELAYS = (0.5, 1.0, 1.5)
EQ_BANDS = (
    (0, "bass", "Bass"),
    (1, "mid", "Mid"),
    (2, "treble", "Treble"),
)
EQ_MINIMUM = -10
EQ_MAXIMUM = 10


def resolve_device(mac):
    """Resolve a selected BlueZ device to an explicitly supported config."""
    if not MAC_RE.fullmatch(mac or ""):
        raise BmapError("Invalid Bluetooth address")

    # Pinned system path only: never resolve bluetoothctl via PATH, so a
    # shadow binary cannot be picked up on panel status/action requests.
    exe = bluetoothctl_path()
    if exe is None:
        raise BmapError("bluetoothctl is required")

    try:
        # Bounded: `info` echoes device-set fields, so the child must not be
        # able to grow our buffers without limit (see pybmap.subproc).
        result = run_capped([exe, "info", mac], timeout=5)
    except FileNotFoundError as error:
        raise BmapError("bluetoothctl is required") from error
    except subprocess.TimeoutExpired as error:
        raise BmapError("Timed out reading the Bluetooth device") from error
    except OutputTooLarge as error:
        raise BmapError("Bluetooth device returned too much data") from error

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise BmapError((detail[:ERROR_DETAIL_LIMIT] or "Bluetooth device was not found"))

    info = result.stdout
    if not has_bmap(info):
        raise BmapError("The selected device does not advertise Bose BMAP")

    product_id, device = bose_identity(info)
    if product_id is None:
        raise BmapError("The selected device has no Bose product identifier")
    if device is None:
        raise BmapError("Unknown Bose product 0x%04X" % product_id)
    if device.config is None:
        raise BmapError("%s is recognized but not supported" % device.name)
    return device


def safe_read(operation, fallback):
    try:
        return operation()
    except BmapError:
        return fallback


def emit_json(payload):
    """Print one JSON document, refusing to emit past the output cap.

    Raises BmapError instead, which main turns into a one-line stderr error
    and a nonzero exit -- the panel then keeps its previous state rather
    than parsing an unbounded document.
    """
    text = json.dumps(payload, separators=(",", ":"))
    if len(text.encode("utf-8")) > OUTPUT_CAP_BYTES:
        raise BmapError(
            "Bridge output exceeded %d bytes" % OUTPUT_CAP_BYTES
        )
    print(text)


def connect_device(mac, device_type):
    """Retry transient failures while BlueZ hands off the RFCOMM socket."""
    for attempt in range(len(CONNECTION_RETRY_DELAYS) + 1):
        try:
            return pybmap.connect(mac=mac, device_type=device_type)
        except BmapConnectionError as error:
            message = str(error).lower()
            transient = (
                "resource busy" in message
                or "errno 16" in message
                or "connection refused" in message
                or "errno 111" in message
            )
            if not transient or attempt == len(CONNECTION_RETRY_DELAYS):
                raise
            time.sleep(CONNECTION_RETRY_DELAYS[attempt])


def mode_options(device):
    options = []
    for mode_id, config in device.preset_modes.items():
        options.append({
            "id": mode_id,
            "label": mode_id.replace("_", " ").title(),
            "detail": str(config.get("description", "")),
        })
    return options


def equalizer_bands(device):
    """Return the three validated EQ bands in stable display order."""
    if not device.has_feature("eq"):
        raise BmapError("Equalizer is not supported by this device")

    by_id = {}
    for band in device.eq():
        band_id = int(band.band_id)
        if band_id in by_id:
            raise BmapError("Equalizer returned a duplicate band")
        by_id[band_id] = band
    if len(by_id) != len(EQ_BANDS):
        raise BmapError("Equalizer returned unexpected bands")

    normalized = []
    for band_id, name, label in EQ_BANDS:
        band = by_id.get(band_id)
        if band is None:
            raise BmapError("Equalizer did not return all three bands")
        minimum = max(int(band.min_val), EQ_MINIMUM)
        maximum = min(int(band.max_val), EQ_MAXIMUM)
        current = int(band.current)
        if minimum > maximum or current < minimum or current > maximum:
            raise BmapError("Equalizer returned invalid band values")
        normalized.append({
            "id": name,
            "label": label,
            "minimum": minimum,
            "maximum": maximum,
            "value": current,
        })
    return normalized


def equalizer_status(device):
    if not device.has_feature("eq"):
        return {"available": False, "bands": []}
    try:
        bands = equalizer_bands(device)
    except (BmapError, TypeError, ValueError):
        return {"available": False, "bands": []}
    return {"available": True, "bands": bands}


def multipoint_status(device):
    """Read optional multipoint state without making panel status depend on it."""
    enabled = (
        safe_read(device.multipoint, None)
        if device.has_feature("multipoint") else None
    )
    source = (
        safe_read(device.source, None)
        if device.has_feature("source") else None
    )
    active_source = None
    if source is not None:
        address = str(getattr(source, "source_mac", "") or "").upper()
        active_source = {
            "type": str(getattr(source, "source_type", "") or "").lower(),
            "address": address if MAC_RE.fullmatch(address) else "",
        }
    return {
        "available": isinstance(enabled, bool) or active_source is not None,
        "enabled": enabled if isinstance(enabled, bool) else False,
        "activeSource": active_source,
    }


def panel_status(device, identity, mac):
    """Read only the status fields rendered by the panel."""
    battery = device.battery_status()
    components = {}
    for reading in battery.readings:
        label = device.battery_components.get(reading.component_id)
        if label:
            components[label.lower()] = reading.level

    if device.has_feature("anr"):
        current_mode = safe_read(device.anr, "")
    elif device.has_feature("current_mode"):
        current_mode = safe_read(device.mode, "")
    else:
        current_mode = ""

    options = mode_options(device)
    option_ids = {option["id"] for option in options}
    normalized_mode = str(current_mode or "").strip()
    mode_key = normalized_mode.lower()
    current_id = mode_key if mode_key in option_ids else ""
    current_label = "" if re.fullmatch(r"unknown\(\d+\)", mode_key) else normalized_mode

    noise_available = device.has_feature("cnc")
    try:
        cnc_level, cnc_max = device.cnc() if noise_available else (-1, 0)
        cancellation = cnc_max - cnc_level if cnc_level >= 0 else -1
    except (BmapError, TypeError, ValueError):
        # A malformed optional reading must degrade to unavailable,
        # mirroring equalizer_status, never fail the whole snapshot.
        cnc_level, cnc_max, cancellation = -1, 0, -1

    return {
        "schemaVersion": SCHEMA_VERSION,
        "device": {
            "address": mac.upper(),
            "type": identity.config,
            "model": identity.name,
            "productId": "0x%04X" % identity.product_id,
        },
        "battery": {
            "level": battery.aggregate,
            "components": components,
        },
        "mode": {
            "currentId": current_id,
            "currentLabel": current_label,
            "options": options,
        },
        "noiseControl": {
            "available": noise_available and cnc_level >= 0,
            "level": cancellation,
            "maximum": cnc_max,
        },
        "multipoint": multipoint_status(device),
        "equalizer": equalizer_status(device),
    }


def set_mode(device, mode):
    if mode not in device.preset_modes:
        raise BmapError("Unsupported listening mode: %s" % mode)
    if device.has_feature("anr") and not device.has_feature("current_mode"):
        device.set_anr(mode)
    else:
        device.set_mode(mode)


def set_cancellation(device, level):
    if not device.has_feature("cnc"):
        raise BmapError("Noise control is not supported by this device")
    try:
        _, maximum = device.cnc()
    except (TypeError, ValueError) as error:
        raise BmapError("Noise control returned invalid state") from error
    if level < 0 or level > maximum:
        raise ValueError("Cancellation level must be 0-%d" % maximum)
    device.set_cnc(maximum - level)


def set_equalizer(device, bass, mid, treble):
    bands = equalizer_bands(device)
    values = {"bass": bass, "mid": mid, "treble": treble}
    for band in bands:
        value = values[band["id"]]
        if value < band["minimum"] or value > band["maximum"]:
            raise ValueError(
                "%s must be %d-%d" % (
                    band["label"], band["minimum"], band["maximum"]
                )
            )
    device.set_eq(bass, mid, treble)


def scan_bose_devices():
    """Enumerate paired Bose devices via bosectl discovery.

    Returns a list of dicts with address, productId, name, config, connected.
    Only devices with an implemented pybmap config are listed, matching
    resolve_device: recognized-but-unsupported products stay out of the
    allowlist (Model.js may still show them via the alias fallback, and
    selecting one reports it as unsupported). This is the authoritative
    allowlist for Model.js filtering.
    """
    return [device for device in list_bmap_devices() if device["config"] is not None]


def argument_parser():
    parser = argparse.ArgumentParser(description="Omabose panel bridge")
    parser.add_argument("--mac", required=False, help="selected Bluetooth address")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")

    mode = commands.add_parser("mode")
    mode.add_argument("name")

    cnc = commands.add_parser("cnc")
    cnc.add_argument("level", type=int)

    equalizer = commands.add_parser("eq")
    equalizer.add_argument("bass", type=int)
    equalizer.add_argument("mid", type=int)
    equalizer.add_argument("treble", type=int)
    # "scan" is the name the panel invokes; "list" is an alias for shell use.
    commands.add_parser("scan")
    commands.add_parser("list")
    commands.add_parser("selection-load")
    save = commands.add_parser("selection-save")
    save.add_argument(
        "--mac",
        required=False,
        help="selected Bluetooth address (omit to clear the preference)",
    )
    return parser


def main(argv=None):
    # The shell stops us with SIGTERM; forward it to the bluetoothctl
    # grandchild (if any) instead of orphaning it. See subproc.
    install_terminate_forwarding()
    args = argument_parser().parse_args(argv)
    try:
        if args.command in ("scan", "list"):
            devices = scan_bose_devices()
            emit_json({"schemaVersion": SCHEMA_VERSION, "devices": devices})
            return 0
        if args.command == "selection-load":
            emit_json(selection_load())
            return 0
        if args.command == "selection-save":
            selection_save(args.mac or "")
            return 0
        if not args.mac or not MAC_RE.fullmatch(args.mac):
            raise BmapError("Invalid Bluetooth address")
        identity = resolve_device(args.mac)
        with connect_device(args.mac, identity.config) as device:
            if args.command == "status":
                emit_json(panel_status(device, identity, args.mac))
            elif args.command == "mode":
                set_mode(device, args.name)
            elif args.command == "cnc":
                set_cancellation(device, args.level)
            elif args.command == "eq":
                set_equalizer(device, args.bass, args.mid, args.treble)
    except (BmapError, OSError, ValueError, TypeError) as error:
        print("Omabose: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
