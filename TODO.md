# Omabose TODO

## Persistent Rust Runtime

- [ ] Define a Rust daemon that owns one persistent BMAP RFCOMM connection per
  selected Bose device.
- [ ] Add reconnect, device-disconnect, and backoff handling to the daemon.
- [ ] Define a local IPC API for status updates and control actions.
- [ ] Update `Service.qml` to use the daemon IPC instead of starting Python
  `bosectl` for every poll or action.
- [ ] Match the current Python runtime's controls, battery parsing, and error
  behavior on physical hardware.
- [ ] Package the Rust daemon for supported architectures and make setup safe
  and reproducible.
- [ ] Retire the bundled Python CLI after Rust hardware parity is confirmed.
