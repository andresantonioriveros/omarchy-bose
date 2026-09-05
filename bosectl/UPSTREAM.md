# bosectl provenance

This directory is a vendored copy of the runtime portion of
[bosectl](https://github.com/andresantonioriveros/bosectl), based on merged
`main` commit
[`c816a89c7b7ac293b3b27a5462c9b2e74dddb566`](https://github.com/andresantonioriveros/bosectl/commit/c816a89c7b7ac293b3b27a5462c9b2e74dddb566)
(version `0.4.0`).

The merged upstream runtime supports QuietComfort Ultra Earbuds (2nd Gen),
product `0x4062`, including one-read battery snapshots with separate right,
left, and case values. Component ID `4` supplies the generic combined-earbud
level. Case charging is intentionally not exposed because `[2.5]` tracks
earbud seating rather than charger state.

The vendored `python/pybmap`, `python/tests`, and EDITH battery fixture are
copied from that commit. The plugin keeps one local launcher overlay that
prepends this directory's bundled `python/` path. Panel-specific product
resolution, JSON output, and action routing live outside the vendored copy in
the repository-root `bridge.py`.

The plugin also carries a local BMAP `[1.10]` correction: bit 0 is parsed as
the current multipoint state, and writes preserve the capability bits reported
by the device. Discovery gained a local public `list_bmap_devices()` (also
re-exported from `pybmap`) so the panel bridge reuses it instead of
duplicating the `bluetoothctl` parsing. Both enumeration paths share one
`_iter_bmap_infos()` iterator with `parse_product_id()`, `has_bmap()`, and
`is_audio_device()` helpers; per-device reads run concurrently so one wedged
`bluetoothctl info` cannot stall the scan, and the BMAP UUID check is
case-insensitive because BlueZ may report it in uppercase. Discovery pins
the system executable at `/usr/bin/bluetoothctl` (`BLUETOOTHCTL`, validated
with `bluetoothctl_path()`): the panel path never resolves executables via
`PATH` and fails closed when the binary is missing or not executable, so a
shadow binary cannot be picked up by the long-lived shell. The original MIT
license is included in this directory. The runtime has no third-party
dependencies beyond Python 3 and the system Bluetooth stack.

Local addition on top of the vendored copy: `python/pybmap/subproc.py`
(`run_capped`), used by `discovery.py`, `cli.py`, and the repository-root
`bridge.py`. `bluetoothctl` echoes device-set fields, so its output is
untrusted: the helper retains at most 64 KiB across stdout/stderr combined,
kills the child past the cap, and preserves timeout and fail-closed behavior
it replaces. Undecodable bytes degrade to U+FFFD instead of raising.
