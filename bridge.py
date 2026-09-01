#!/usr/bin/python3
"""Small machine-readable adapter between the Omarchy panel and pybmap."""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bosectl" / "python"))

import pybmap
from pybmap.catalog import BMAP_UUID, lookup_device
from pybmap.errors import BmapConnectionError, BmapError


SCHEMA_VERSION = 1
MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
PRODUCT_RE = re.compile(
    r"Modalias:\s*bluetooth:v[0-9A-Fa-f]{4}p([0-9A-Fa-f]{4})"
)
CONNECTION_RETRY_DELAYS = (0.5, 1.0, 1.5)
EQ_BANDS = (
    (0, "bass", "Bass"),
    (1, "mid", "Mid"),
    (2, "treble", "Treble"),
)


def resolve_device(mac):
    """Resolve a selected BlueZ device to an explicitly supported config."""
    if not MAC_RE.fullmatch(mac or ""):
        raise BmapError("Invalid Bluetooth address")

    try:
        result = subprocess.run(
            ["bluetoothctl", "info", mac],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError as error:
        raise BmapError("bluetoothctl is required") from error
    except subprocess.TimeoutExpired as error:
        raise BmapError("Timed out reading the Bluetooth device") from error

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise BmapError(detail or "Bluetooth device was not found")

    info = result.stdout
    if BMAP_UUID.lower() not in info.lower():
        raise BmapError("The selected device does not advertise Bose BMAP")

    match = PRODUCT_RE.search(info)
    if not match:
        raise BmapError("The selected device has no Bose product identifier")

    product_id = int(match.group(1), 16)
    device = lookup_device(product_id)
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

    normalized = []
    for band_id, name, label in EQ_BANDS:
        band = by_id.get(band_id)
        if band is None:
            raise BmapError("Equalizer did not return all three bands")
        minimum = int(band.min_val)
        maximum = int(band.max_val)
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
    cnc_level, cnc_max = safe_read(device.cnc, (-1, 0)) if noise_available else (-1, 0)
    cancellation = cnc_max - cnc_level if cnc_level >= 0 else -1

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
    _, maximum = device.cnc()
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


def argument_parser():
    parser = argparse.ArgumentParser(description="Omabose panel bridge")
    parser.add_argument("--mac", required=True, help="selected Bluetooth address")
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
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        identity = resolve_device(args.mac)
        with connect_device(args.mac, identity.config) as device:
            if args.command == "status":
                print(json.dumps(panel_status(device, identity, args.mac), separators=(",", ":")))
            elif args.command == "mode":
                set_mode(device, args.name)
            elif args.command == "cnc":
                set_cancellation(device, args.level)
            elif args.command == "eq":
                set_equalizer(device, args.bass, args.mid, args.treble)
    except (BmapError, OSError, ValueError) as error:
        print("Omabose: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
