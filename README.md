# Bose for Omarchy

A Bose QuietComfort widget for the Omarchy Quattro bar. It shows Bluetooth
connection and battery state, with Bose listening-mode and noise-control actions
through the bundled `bosectl` implementation.

<p align="center">
  <img src="preview.png" width="360" alt="Bose QuietComfort Ultra 2 Earbuds panel" />
</p>

The plugin does not use Bose cloud or account services.

## Install

```bash
omarchy plugin add https://github.com/andresantonioriveros/omarchy-bose.git --enable
"$HOME/.config/omarchy/plugins/io.github.andresariveros.omabose/setup"
```

The command clones the current repository into the user-owned Omarchy plugin
directory and enables the bar widget. The plugin defaults to the right bar
section and can be moved with:

```bash
omarchy bar move io.github.andresariveros.omabose --section right
```

## Requirements

- Omarchy Quattro with the Omarchy shell and Quickshell Bluetooth support.
- BlueZ and a Bose device paired through the system Bluetooth tools.
- Python 3 and RFCOMM support for the required `bosectl` control path.

## Install bosectl

Run the setup script after installing the plugin. This is required for the
widget to read vendor status and expose its controls:

```bash
"$HOME/.config/omarchy/plugins/io.github.andresariveros.omabose/setup"
```

The script links the repository-owned `bosectl` implementation into
`~/.local/bin/bosectl`. It does not use `sudo`, modify system configuration,
install packages, or download external code. The bundled source is based on
merged `main` commit
[`c816a89`](https://github.com/andresantonioriveros/bosectl/commit/c816a89c7b7ac293b3b27a5462c9b2e74dddb566)
and includes the QuietComfort Ultra Earbuds (2nd Gen) support required for
separate left, right, and case battery readings. Its original MIT license is
included at `bosectl/LICENSE`.

For safety, setup will not replace a different existing `~/.local/bin/bosectl`
executable. It may replace the legacy symlink created by an earlier plugin
version, which pointed to `~/.local/share/bosectl/bosectl`.

The setup script requires Python 3. To update the bundled dependency, review the
upstream source and the changes recorded in `bosectl/UPSTREAM.md`, then publish
a new plugin version.

## Usage

Open the Bose widget from the bar. Select a paired device to inspect its
battery, listening modes, and noise-cancellation level.

The panel selects bundled `bosectl` configurations for these device families:

- QuietComfort Ultra Headphones 2
- QuietComfort Ultra Earbuds 2 (product `0x4062`)
- QuietComfort Headphones (`prince`)
- QuietComfort 35 and 35 II
- QuietComfort 45
- QuietComfort Earbuds

Available controls depend on each device configuration and its verified BMAP
capabilities. QuietComfort 45 support is inherited and has not been validated
on physical hardware. QuietComfort Ultra Earbuds 2 report separate left, right,
and case battery rows through vendor BMAP readings.

The bundled runtime contains a partial Ultra Open Earbuds configuration, but
the panel does not yet distinguish Ultra Open from QuietComfort Ultra earbuds;
Ultra Open is therefore not currently supported by the widget.

Protocol observations and the case-charging investigation plan are documented
in [`knowledge/`](knowledge/).

The runtime migration roadmap is documented in [`TODO.md`](TODO.md). Python is
the current implementation; a persistent Rust daemon is planned for a future
iteration.

## Reload and removal

The Omarchy shell watches user plugins. Force discovery after a manual change:

```bash
omarchy-shell shell rescanPlugins
```

Disable and remove the plugin with:

```bash
omarchy plugin disable io.github.andresariveros.omabose
omarchy plugin remove io.github.andresariveros.omabose
```

Removal deletes only the plugin checkout. The `bosectl` symlink is a separate
user-local file; remove it manually if no longer needed:

```bash
rm -f "$HOME/.local/bin/bosectl"
```

## License and trademarks

The plugin code is available under the MIT License. Bose and QuietComfort are
trademarks of Bose Corporation. This project is independent and is not
endorsed by Bose.
