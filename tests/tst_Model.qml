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
      noiseControl: { available: true, level: 7, maximum: 10 },
      multipoint: {
        available: true,
        enabled: true,
        activeSource: { type: "bluetooth", address: "AC:F2:3C:35:10:DE" }
      },
      equalizer: {
        available: true,
        bands: [
          { id: "bass", label: "Bass", minimum: -10, maximum: 10, value: -2 },
          { id: "mid", label: "Mid", minimum: -10, maximum: 10, value: 0 },
          { id: "treble", label: "Treble", minimum: -10, maximum: 10, value: 2 }
        ]
      }
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
    verify(status.multipointAvailable)
    verify(status.multipointEnabled)
    compare(status.activeSourceType, "bluetooth")
    compare(status.activeSourceAddress, "AC:F2:3C:35:10:DE")
    verify(status.eqAvailable)
    compare(status.eqBands.length, 3)
    compare(status.eqBands[0].id, "bass")
    compare(status.eqBands[0].value, -2)
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

  function test_parseBridgeStatusIgnoresMalformedEqualizer() {
    var status = Model.parseBridgeStatus(bridgePayload({
      equalizer: {
        available: true,
        bands: [
          { id: "bass", minimum: -10, maximum: 10, value: 0 },
          { id: "bass", minimum: -10, maximum: 10, value: 0 },
          { id: "treble", minimum: -10, maximum: 10, value: 0 }
        ]
      }
    }))

    verify(status.reachable)
    verify(!status.eqAvailable)
    compare(status.eqBands.length, 0)
  }

  function test_parseBridgeStatusAccepts03PayloadWithoutEqualizer() {
    var payload = JSON.parse(bridgePayload())
    delete payload.equalizer

    var status = Model.parseBridgeStatus(JSON.stringify(payload))

    verify(status.reachable)
    verify(!status.eqAvailable)
    compare(status.eqBands.length, 0)
  }

  function test_parseBridgeStatusAcceptsPayloadWithoutMultipoint() {
    var payload = JSON.parse(bridgePayload())
    delete payload.multipoint

    var status = Model.parseBridgeStatus(JSON.stringify(payload))

    verify(status.reachable)
    verify(!status.multipointAvailable)
    verify(!status.multipointEnabled)
    compare(status.activeSourceType, "")
    compare(status.activeSourceAddress, "")
  }

  function test_equalizerPresetsMatchOfficialValues() {
    var presets = Model.equalizerPresets()

    compare(presets.length, 4)
    compare(presets[0].id, "bassBoost")
    compare(presets[0].values.join(","), "8,0,0")
    compare(presets[1].values.join(","), "-8,-2,0")
    compare(presets[2].values.join(","), "0,0,6")
    compare(presets[3].values.join(","), "0,-2,-6")
  }

  function test_equalizerHelpersApplyAndRecognizeValues() {
    var status = Model.parseBridgeStatus(bridgePayload())
    var applied = Model.equalizerBandsWithValues(status.eqBands, [-8, -2, 0])

    compare(Model.equalizerPresetId(applied), "bassReducer")
    compare(Model.equalizerValues(applied).join(","), "-8,-2,0")
    compare(Model.formatEqualizerValue(3), "+3")
    compare(Model.formatEqualizerValue(-2), "-2")
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
    var rows = Model.cursorRows(devices, modes, true, true, true)

    compare(rows.length, 4)
    compare(rows[0].key, "mode:quiet")
    compare(rows[1].key, "mode:aware")
    compare(rows[2].key, "cnc")
    compare(rows[3].key, "eq")
    compare(Model.rowIndex(rows, "mode:aware"), 1)
  }

  function test_cursorRowsIncludeVisibleDeviceSection() {
    var devices = [
      { address: "AA:BB:CC:DD:EE:01" },
      { address: "AA:BB:CC:DD:EE:02" }
    ]
    var rows = Model.cursorRows(devices, [], false, false, false)

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

  function test_errorForProcessTruncatesHostileDetail() {
    var hostile = "Omabose: "
    for (var i = 0; i < 2000; i++) hostile += "E"
    var shown = Model.errorForProcess(hostile)
    verify(shown.length <= Model.MAX_ERROR_CHARS)
    verify(shown.length > 0)
  }

  function test_parseBridgeStatusRejectsOversizedPayload() {
    var big = "x"
    while (big.length <= Model.MAX_JSON_BYTES) big += big
    var threw = false
    try { Model.parseBridgeStatus(big) } catch (e) { threw = true }
    verify(threw)
  }

  function test_parseDiscoveryAddressesRejectsOversizedPayload() {
    var big = "x"
    while (big.length <= Model.MAX_JSON_BYTES) big += big
    compare(Model.parseDiscoveryAddresses(big).length, 0)
  }

  function test_sizeGuardsCountBytesNotCharacters() {
    // 40000 chars but 80000 UTF-8 bytes: a character count waves it
    // through at nearly triple the byte cap, so it must still refuse.
    var wide = ""
    for (var i = 0; i < 40000; i++) wide += "é"
    var threw = false
    try { Model.parseBridgeStatus(wide) } catch (e) { threw = true }
    verify(threw)
    compare(Model.parseDiscoveryAddresses(wide).length, 0)
  }
}
