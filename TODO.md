# Omabose TODO

## Runtime measurements

- [ ] Measure panel-open latency and packet counts on each verified device.
- [ ] Measure the additional EQ read on devices that expose equalizer controls.
- [ ] Measure repeated status refreshes before lowering the default interval.
- [ ] Add unreachable-device backoff if open-panel retries create observable
  BlueZ churn.
- [ ] Consider a persistent daemon only if the measured RFCOMM reconnect cost
  remains user-visible after the lean bridge snapshot.
- [ ] If a daemon is justified, require reconnect/backoff behavior, a versioned
  local IPC contract, reproducible packaging, and hardware parity before
  replacing the Python bridge.
