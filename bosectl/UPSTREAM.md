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

The original MIT license is included in this directory. The runtime has no
third-party dependencies beyond Python 3 and the system Bluetooth stack.
