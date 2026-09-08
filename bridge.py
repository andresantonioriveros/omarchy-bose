#!/usr/bin/python3
"""Small machine-readable adapter between the Omarchy panel and pybmap."""

import argparse
import errno
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
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
# Errors are rendered as short UI labels. Bound the wire form separately so
# every exception path is safe for the panel's streaming collector.
ERROR_OUTPUT_CAP_BYTES = 2048
# bluetoothctl stderr on failure is device-influenced free text echoed into
# our one-line errors: keep the gist, drop the rest.
ERROR_DETAIL_LIMIT = 500
# The persisted selection is one tiny JSON document; anything bigger is not
# ours. All checks below run against the opened fd (never a re-looked-up
# path), so a swap between check and use cannot redirect them.
SELECTION_MAX_BYTES = 4096
SELECTION_DIRECTORY_PARTS = (".local", "state", "omarchy")
SELECTION_FILENAME = "omabose.json"
UNSAFE_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH
MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def selection_path():
    """Where the panel persists the explicitly selected device address."""
    return Path.home().joinpath(*SELECTION_DIRECTORY_PARTS, SELECTION_FILENAME)


def _validate_selection_directory(fd, name):
    info = os.fstat(fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & UNSAFE_WRITE_BITS
    ):
        raise PermissionError(errno.EPERM, "Unsafe selection directory", name)


def _open_selection_directory(create):
    """Open the state directory without following application-path symlinks."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    current = os.open(Path.home(), flags)
    try:
        _validate_selection_directory(current, str(Path.home()))
        for part in SELECTION_DIRECTORY_PARTS:
            try:
                child = os.open(part, flags | os.O_NOFOLLOW, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                    os.fsync(current)
                except FileExistsError:
                    pass
                child = os.open(part, flags | os.O_NOFOLLOW, dir_fd=current)
            try:
                _validate_selection_directory(child, part)
            except BaseException:
                os.close(child)
                raise
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def selection_load():
    """Read the persisted selection, degrading to empty on any problem.

    Missing, oversized, non-regular, foreign-owned, symlinked, or
    unparsable state all mean the same thing: no usable preference.
    Returns {"selectedAddress": mac-or-""}.
    """
    try:
        directory_fd = _open_selection_directory(create=False)
    except OSError:
        return {"selectedAddress": ""}
    try:
        try:
            fd = os.open(
                SELECTION_FILENAME,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
        except OSError:
            return {"selectedAddress": ""}
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & UNSAFE_WRITE_BITS
                or info.st_size > SELECTION_MAX_BYTES
            ):
                return {"selectedAddress": ""}
            raw = bytearray()
            while len(raw) <= SELECTION_MAX_BYTES:
                piece = os.read(fd, SELECTION_MAX_BYTES + 1 - len(raw))
                if not piece:
                    break
                raw.extend(piece)
        except OSError:
            return {"selectedAddress": ""}
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)
    if len(raw) > SELECTION_MAX_BYTES:
        return {"selectedAddress": ""}
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        return {"selectedAddress": ""}
    if not isinstance(obj, dict):
        return {"selectedAddress": ""}
    addr = str(obj.get("selectedAddress") or "").upper()
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
    data = text.encode("utf-8")
    directory_fd = _open_selection_directory(create=True)
    fd = None
    tmp_name = None
    try:
        for _attempt in range(16):
            candidate = ".omabose-%s.tmp" % secrets.token_hex(8)
            tmp_name = candidate
            try:
                fd = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                    mode=0o600,
                    dir_fd=directory_fd,
                )
                break
            except FileExistsError:
                tmp_name = None
                continue
        if fd is None:
            raise FileExistsError("Could not create selection temporary file")

        written = 0
        while written < len(data):
            count = os.write(fd, data[written:])
            if count == 0:
                raise OSError(errno.EIO, "Selection write made no progress")
            written += count
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(
            tmp_name,
            SELECTION_FILENAME,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        tmp_name = None
        os.fsync(directory_fd)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_name is not None:
            try:
                os.unlink(tmp_name, dir_fd=directory_fd)
            except OSError:
                pass
        raise
    finally:
        os.close(directory_fd)


def _exit_cleanly_on_terminate(signum, frame):
    raise SystemExit(128 + signum)


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
    text = json.dumps(payload, separators=(",", ":")) + "\n"
    if len(text.encode("utf-8")) > OUTPUT_CAP_BYTES:
        raise BmapError(
            "Bridge output exceeded %d bytes" % OUTPUT_CAP_BYTES
        )
    sys.stdout.write(text)


def emit_error(error):
    """Write one UTF-8 error line without exceeding the stderr cap."""
    prefix = "Omabose: "
    suffix = "\n"
    available = ERROR_OUTPUT_CAP_BYTES - len((prefix + suffix).encode("utf-8"))
    detail = str(error).encode("utf-8", "replace")[:available].decode(
        "utf-8", "ignore"
    )
    sys.stderr.write(prefix + detail + suffix)


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
        default=argparse.SUPPRESS,
        help="selected Bluetooth address (omit to clear the preference)",
    )
    return parser


def main(argv=None, *, install_signal_handlers=False):
    args = argument_parser().parse_args(argv)
    if install_signal_handlers:
        if args.command == "selection-save":
            signal.signal(signal.SIGTERM, _exit_cleanly_on_terminate)
        elif args.command != "selection-load":
            install_terminate_forwarding()
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
        emit_error(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(install_signal_handlers=True))
