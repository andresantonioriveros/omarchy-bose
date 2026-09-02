"""Auto-detect paired BMAP devices (Linux/macOS)."""

import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from .catalog import BMAP_UUID, lookup_device

# Only a literal MAC is handed on to bluetoothctl, mirroring the C++ guard.
_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

_MODALIAS_RE = re.compile(
    r"Modalias:\s*bluetooth:v[0-9A-Fa-f]{4}p([0-9A-Fa-f]{4})",
    re.IGNORECASE,
)


def parse_product_id(info_text):
    """Extract the Bluetooth Modalias product ID from `bluetoothctl info` output.

    Returns the product ID as an int, or None when the output carries none.
    """
    match = _MODALIAS_RE.search(info_text or "")
    if not match:
        return None
    try:
        return int(match.group(1), 16)
    except ValueError:
        return None


def has_bmap(info_text):
    """Check whether `bluetoothctl info` output advertises the BMAP service."""
    return BMAP_UUID.lower() in (info_text or "").lower()


def is_audio_device(info_text):
    """Check whether `bluetoothctl info` output describes an audio endpoint."""
    text = info_text or ""
    return "audio-headset" in text or "audio-headphones" in text


def is_bmap_audio(info_text):
    """Check whether output describes a BMAP audio endpoint."""
    return is_audio_device(info_text) and has_bmap(info_text)


def bose_identity(info_text):
    """Return (product_id, entry) for `bluetoothctl info` output.

    Shared by enumeration and single-device resolution so both agree on
    how a Modalias maps to the catalog. product_id is None when the
    output carries none; entry is None when unknown.
    """
    product_id = parse_product_id(info_text)
    entry = lookup_device(product_id) if product_id is not None else None
    return product_id, entry


def _prefer_connected(candidates):
    """Return (mac, device_type) preferring connected entries.

    Candidates are (mac, device_type, connected) tuples. Returns
    (None, None) when empty.
    """
    for mac, device_type, connected in candidates:
        if connected:
            return (mac, device_type)
    for mac, device_type, _connected in candidates:
        return (mac, device_type)
    return (None, None)

if sys.platform == "darwin":
    from IOBluetooth import IOBluetoothDevice

    def list_bmap_devices():
        """macOS has no BlueZ enumeration; the panel bridge is Linux-only."""
        return []

    def find_bmap_device():
        """Auto-detect a paired, connected BMAP-capable Bluetooth device on macOS.

        Prioritizes connected devices over paired-but-disconnected ones.
        Returns (mac, device_type) tuple, or (None, None) if not found.
        """
        candidates = []
        try:
            for device in IOBluetoothDevice.pairedDevices():
                pid = device.productID()
                entry = lookup_device(pid)
                if entry and entry.config:
                    # device.getAddressString() returns something like "68-f2-1f-0d-f5-11"
                    candidates.append((device.getAddressString(), entry.config, device.isConnected()))
        except Exception:
            pass

        return _prefer_connected(candidates)

else:
    def find_bmap_device():
        """Auto-detect a paired, connected BMAP-capable Bluetooth device (Linux).

        Prioritizes connected devices over paired-but-disconnected ones.
        Returns (mac, device_type) tuple, or (None, None) if not found.
        """
        return _prefer_connected(_scan_paired_devices())


    def _paired_macs():
        """List MAC addresses reported by `bluetoothctl devices Paired`."""
        try:
            result = subprocess.run(
                ["bluetoothctl", "devices", "Paired"],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        macs = []
        for line in result.stdout.strip().splitlines():
            parts = line.split(None, 2)
            if len(parts) < 2:
                continue
            mac = parts[1]
            if _MAC_RE.match(mac):
                macs.append(mac)
        return macs


    def _bluetoothctl_info(mac):
        """Return `bluetoothctl info` output for one MAC, or None on failure."""
        try:
            info = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True, text=True, timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return info.stdout


    def _iter_bmap_infos():
        """Yield (mac, info output) for paired BMAP audio devices, in order.

        Per-device reads run concurrently so one wedged `bluetoothctl info`
        cannot stall the whole enumeration behind its timeout.
        """
        macs = _paired_macs()
        if not macs:
            return
        with ThreadPoolExecutor(max_workers=min(4, len(macs))) as pool:
            infos = list(pool.map(_bluetoothctl_info, macs))
        for mac, info_text in zip(macs, infos):
            if info_text is None:
                continue
            if is_bmap_audio(info_text):
                yield mac, info_text


    def list_bmap_devices():
        """List every paired Bose audio device advertising BMAP.

        Returns a list of dicts with address, productId, name, config and
        connected keys. Unknown or not-yet-supported products are included
        with a None productId/config so callers can decide their own policy.
        """
        devices = []
        for mac, info_text in _iter_bmap_infos():
            product_id, entry = bose_identity(info_text)
            devices.append({
                "address": mac.upper(),
                "productId": ("0x%04X" % product_id) if product_id is not None else None,
                "name": entry.name if entry is not None else "",
                "config": entry.config if entry is not None else None,
                "connected": "Connected: yes" in info_text,
            })
        return devices


    def _scan_paired_devices():
        """Scan paired Bluetooth devices for BMAP-capable headphones."""
        return [
            (device["address"], device["config"] or "qc_ultra2", device["connected"])
            for device in list_bmap_devices()
        ]


    def _detect_device_type(info_text):
        """Extract device type from bluetoothctl info output via catalog lookup."""
        _product_id, entry = bose_identity(info_text)
        if entry and entry.config:
            return entry.config
        return "qc_ultra2"  # default for unknown BMAP devices
