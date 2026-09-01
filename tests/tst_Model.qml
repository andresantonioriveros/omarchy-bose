import QtQuick
import QtTest
import "../Model.js" as Model

TestCase {
  name: "OmaboseModel"

  function bridgePayload(overrides) {
    var payload = {
      schemaVersion: 1,
      device: {
        address: "AA:BB:CC:DD:EE:FF",
        type: "qc_ultra2_earbuds",
        model: "QuietComfort Ultra Earbuds (2nd Gen)"
      },
      battery: {
        level: 60,
        components: { left: 60, right: 50, case: 80 }
      },
      mode: {
        currentId: "quiet",
        currentLabel: "quiet",
        options: [
          { id: "quiet", label: "Quiet", detail: "Full cancellation" },
          { id: "aware", label: "Aware", detail: "Transparency" }
        ]
      },
      noiseControl: { available: true, level: 7, maximum: 10 }
    }
    for (var key in overrides || {}) payload[key] = overrides[key]
    return JSON.stringify(payload)
  }

  function test_parseBridgeStatus() {
    var status = Model.parseBridgeStatus(bridgePayload())

    verify(status.reachable)
    compare(status.address, "AA:BB:CC:DD:EE:FF")
    compare(status.deviceType, "qc_ultra2_earbuds")
    compare(status.battery, 60)
    compare(status.batteries.left, 60)
    compare(status.batteries.right, 50)
    compare(status.batteries.case, 80)
    compare(status.mode, "quiet")
    compare(status.modeLabel, "Quiet")
    compare(status.modeOptions.length, 2)
    compare(status.cnc, 7)
    compare(status.cncMax, 10)
  }

  function test_parseBridgeStatusSanitizesCustomMode() {
    var status = Model.parseBridgeStatus(bridgePayload({
      mode: { currentId: "", currentLabel: "My\nCommute", options: [] }
    }))

    compare(status.mode, "")
    compare(status.modeLabel, "My Commute")
  }

  function test_parseBridgeStatusRejectsUnknownSchema() {
    var failed = false
    try {
      Model.parseBridgeStatus(JSON.stringify({ schemaVersion: 2 }))
    } catch (error) {
      failed = true
    }
    verify(failed)
  }

  function test_deviceRowsFilterAndSortKnownBoseDevices() {
    var rows = Model.boseDeviceRows([
      {
        address: "00:00:00:00:00:02",
        name: "aar-qc-ultra-2-earbuds",
        deviceName: "aar-qc-ultra-2-earbuds",
        connected: false,
        paired: true,
        batteryAvailable: false
      },
      {
        address: "00:00:00:00:00:01",
        name: "Bose Connected",
        deviceName: "Bose Connected",
        connected: true,
        batteryAvailable: true,
        battery: 0.42
      },
      {
        address: "00:00:00:00:00:03",
        name: "Bose Discovered",
        connected: false,
        paired: false,
        bonded: false,
        trusted: false
      },
      {
        address: "00:00:00:00:00:04",
        name: "MX Mouse",
        connected: true
      }
    ])

    compare(rows.length, 2)
    compare(rows[0].address, "00:00:00:00:00:01")
    compare(rows[0].battery, 42)
    compare(rows[1].address, "00:00:00:00:00:02")
    verify(rows[1].earbuds)
  }

  function test_boseNameMatchingDoesNotUseLooseSubstring() {
    verify(Model.isBoseDevice({ name: "aar-qc-ultra-2-hp" }))
    verify(!Model.isBoseDevice({ name: "aqua-color speaker" }))
  }

  function test_preferredDeviceWinsEvenWhenDisconnected() {
    var devices = [
      { address: "AA:BB:CC:DD:EE:01", connected: true },
      { address: "AA:BB:CC:DD:EE:02", connected: false }
    ]

    compare(Model.preferredDevice(
      devices, devices[0].address, devices[1].address).address, devices[1].address)
  }

  function test_preferredDeviceUsesConnectedFallbackWithoutLosingPreference() {
    var fallback = { address: "AA:BB:CC:DD:EE:01", connected: true }
    var disconnected = { address: "AA:BB:CC:DD:EE:02", connected: false }

    compare(Model.preferredDevice(
      [fallback, disconnected], disconnected.address, "AA:BB:CC:DD:EE:03").address,
      fallback.address)

    var restored = { address: "AA:BB:CC:DD:EE:03", connected: false }
    compare(Model.preferredDevice(
      [fallback, restored], fallback.address, restored.address).address,
      restored.address)
  }

  function test_batteryRowsUseBluezFallback() {
    var rows = Model.batteryRows(
      { earbuds: false, battery: 34 }, Model.emptyStatus())

    compare(rows.length, 1)
    compare(rows[0].label, "Headphones")
    compare(rows[0].level, 34)
  }

  function test_batteryRowsUseVendorComponents() {
    var status = Model.parseBridgeStatus(bridgePayload())
    var rows = Model.batteryRows({ earbuds: true, battery: 20 }, status)

    compare(rows.length, 3)
    compare(rows[0].label, "Left")
    compare(rows[0].level, 60)
    compare(rows[1].label, "Right")
    compare(rows[1].level, 50)
    compare(rows[2].label, "Case")
    compare(rows[2].level, 80)
  }

  function test_cursorRowsOnlyContainVisibleControls() {
    var devices = [{ address: "AA:BB:CC:DD:EE:FF" }]
    var modes = [{ id: "quiet" }, { id: "aware" }]
    var rows = Model.cursorRows(devices, modes, true, true)

    compare(rows.length, 3)
    compare(rows[0].key, "mode:quiet")
    compare(rows[1].key, "mode:aware")
    compare(rows[2].key, "cnc")
    compare(Model.rowIndex(rows, "mode:aware"), 1)
  }

  function test_cursorRowsIncludeVisibleDeviceSection() {
    var devices = [
      { address: "AA:BB:CC:DD:EE:01" },
      { address: "AA:BB:CC:DD:EE:02" }
    ]
    var rows = Model.cursorRows(devices, [], false, false)

    compare(rows.length, 2)
    compare(rows[0].key, "device:AA:BB:CC:DD:EE:01")
  }

  function test_deviceOrderDoesNotChangeWithConnectionState() {
    var devices = [
      { address: "AA:BB:CC:DD:EE:01", label: "Z Headphones", earbuds: false, connected: true },
      { address: "AA:BB:CC:DD:EE:02", label: "A Earbuds", earbuds: true, connected: false }
    ]
    var initial = Model.sortDevices(devices)

    devices[0].connected = false
    devices[1].connected = true
    var updated = Model.sortDevices(devices)

    compare(initial[0].address, "AA:BB:CC:DD:EE:01")
    compare(initial[1].address, "AA:BB:CC:DD:EE:02")
    compare(updated[0].address, initial[0].address)
    compare(updated[1].address, initial[1].address)
  }

  function test_cleanErrorRemovesBridgePrefix() {
    compare(Model.errorForProcess("Omabose: device unavailable\n"), "device unavailable")
  }
}
