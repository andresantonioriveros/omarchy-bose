import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Bluetooth
import "Model.js" as Model

Item {
  id: root

  property var settings: ({})
  property bool active: false
  readonly property var rawDevices: Bluetooth.devices ? Bluetooth.devices.values : []

  property var discoveredBoseAddresses: []
  property string discoveryOutput: ""
  property string discoveryError: ""
  property bool discoveryQueued: false

  readonly property var boseDevices: Model.boseDeviceRows(rawDevices, discoveredBoseAddresses)
  property string selectedAddress: ""
  property string selectedDeviceSignature: ""
  property var vendorStatus: Model.emptyStatus()
  property string vendorStatusAddress: ""
  property string vendorState: "idle"
  property string pendingMode: ""
  property int pendingCnc: -1
  property var pendingEq: []
  property int pendingVerificationAttempts: 0
  property string vendorError: ""
  property string actionStatus: ""
  property string statusOutput: ""
  property string statusError: ""
  property string actionOutput: ""
  property string actionError: ""
  property string selectionLoadOutput: ""
  property bool statusTimedOut: false
  property bool actionTimedOut: false

  property bool selectionLoaded: false
  property string preferredAddress: ""

  readonly property var connectedDevices: boseDevices.filter(function(device) { return device.connected })
  readonly property var selectedDevice: Model.deviceForAddress(boseDevices, selectedAddress)
  readonly property bool vendorMatchesSelection: selectedDevice
    && vendorStatus.reachable
    && vendorStatusAddress === selectedDevice.address
  readonly property int battery: selectedDevice
    ? (vendorMatchesSelection && vendorStatus.battery >= 0
      ? vendorStatus.battery : selectedDevice.battery)
    : -1
  readonly property string selectedMode: pendingMode !== ""
    ? pendingMode : (vendorMatchesSelection ? vendorStatus.mode : "")
  readonly property string selectedModeLabel: pendingMode !== ""
    ? Model.modeLabel(pendingMode)
    : (vendorMatchesSelection ? vendorStatus.modeLabel : "")
  readonly property int displayedCnc: pendingCnc >= 0
    ? pendingCnc : (vendorMatchesSelection ? vendorStatus.cnc : -1)
  readonly property var modeOptions: vendorMatchesSelection ? vendorStatus.modeOptions : []
  readonly property var displayedEqBands: pendingEq.length === 3
    ? Model.equalizerBandsWithValues(vendorStatus.eqBands, pendingEq)
    : (vendorMatchesSelection ? vendorStatus.eqBands : [])
  readonly property var eqPresets: Model.equalizerPresets()
  readonly property string selectedEqPreset: Model.equalizerPresetId(displayedEqBands)
  readonly property var batteryRows: Model.batteryRows(selectedDevice, vendorStatus)
  readonly property bool vendorAvailable: vendorMatchesSelection
  readonly property bool vendorLoading: vendorState === "loading"
  readonly property bool vendorStale: vendorState === "stale"
  readonly property bool cncAvailable: vendorMatchesSelection && vendorStatus.cncAvailable
  readonly property bool eqAvailable: vendorMatchesSelection && vendorStatus.eqAvailable
  readonly property string bridgePath: decodeURIComponent(
    Qt.resolvedUrl("bridge.py").toString().replace(/^file:\/\//, ""))
  readonly property int pollIntervalMs: {
    var seconds = Number(setting("pollIntervalSec", 15))
    if (!isFinite(seconds)) seconds = 15
    return Math.max(5, Math.min(120, seconds)) * 1000
  }

  function refreshDiscovery() {
    if (discoveryProcess.running) {
      discoveryQueued = true
      return
    }
    discoveryQueued = false
    discoveryOutput = ""
    discoveryError = ""
    discoveryProcess.command = ["/usr/bin/python3", bridgePath, "scan"]
    discoveryProcess.running = true
  }

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function findDevice(address) {
    return Model.deviceForAddress(boseDevices, address)
  }

  function parsePersistedAddress(raw) {
    try {
      var obj = JSON.parse(String(raw || ""))
      var addr = String(obj && obj.selectedAddress || "").toUpperCase()
      if (/^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$/.test(addr)) return addr
    } catch (e) {}
    return ""
  }

  function loadSelection(raw) {
    if (selectionLoaded) return
    var addr = parsePersistedAddress(raw)
    preferredAddress = addr
    selectionLoaded = true
    reconcileDevices()
  }

  function runSelectionLoad() {
    if (selectionLoadProcess.running) return
    selectionLoadOutput = ""
    selectionLoadProcess.command = ["/usr/bin/python3", bridgePath, "selection-load"]
    selectionLoadProcess.running = true
  }

  function flushSelection() {
    if (!selectionLoaded || selectionSaveProcess.running) return
    var args = ["selection-save"]
    if (preferredAddress) args.push("--mac", preferredAddress.toUpperCase())
    selectionSaveProcess.command = ["/usr/bin/python3", bridgePath].concat(args)
    selectionSaveProcess.running = true
  }

  function reconcileDevices() {
    var target = Model.preferredDevice(
      boseDevices, selectedAddress, selectionLoaded ? preferredAddress : "")

    var nextAddress = target ? target.address : ""
    var nextSignature = target ? target.address + ":" + (target.connected ? "connected" : "paired") : ""
    var stateChanged = nextSignature !== selectedDeviceSignature
    selectedDeviceSignature = nextSignature
    if (nextAddress !== selectedAddress) selectedAddress = nextAddress
    else if (stateChanged) {
      vendorGeneration++
      clearPending()
      if (!target || !target.connected) clearVendor("idle")
      refreshVendor()
    }
  }

  function select(address) {
    var selected = findDevice(address)
    if (!selected) return
    preferredAddress = selected.address
    if (selectionLoaded) selectionSaveTimer.restart()
    if (selected.address !== selectedAddress) selectedAddress = selected.address
  }

  function command(args) {
    if (!selectedDevice || !selectedDevice.connected) return []
    return ["/usr/bin/python3", bridgePath, "--mac", selectedDevice.address].concat(args)
  }

  function clearPending() {
    pendingMode = ""
    pendingCnc = -1
    pendingEq = []
    pendingVerificationAttempts = 0
  }

  function retryPendingChange() {
    if (pendingMode === "" && pendingCnc < 0 && pendingEq.length !== 3) {
      pendingVerificationAttempts = 0
      return
    }
    if (pendingVerificationAttempts < 2) {
      pendingVerificationAttempts++
      verificationRefresh.restart()
      return
    }
    clearPending()
    actionStatus = "Device did not confirm the requested change"
    actionMessageTimer.restart()
  }

  function clearVendor(state) {
    vendorStatus = Model.emptyStatus()
    vendorStatusAddress = ""
    vendorState = state || "idle"
  }

  function refreshVendor() {
    if (!active || !selectedDevice || !selectedDevice.connected) {
      refreshQueued = false
      clearVendor("idle")
      clearPending()
      vendorError = ""
      return
    }
    if (vendorStatusAddress !== selectedDevice.address) {
      vendorStatus = Model.emptyStatus()
      vendorStatusAddress = ""
    }
    if (statusProcess.running || actionProcess.running) {
      refreshQueued = true
      return
    }
    refreshQueued = false
    vendorState = vendorAvailable ? vendorState : "loading"
    vendorError = ""
    statusOutput = ""
    statusError = ""
    statusTimedOut = false
    statusRequestAddress = selectedDevice.address
    statusRequestGeneration = vendorGeneration
    statusProcess.command = command(["status"])
    statusProcess.running = true
  }

  function runAction(args, successText) {
    if (!active || !selectedDevice || !selectedDevice.connected
        || !vendorAvailable || actionProcess.running) return false
    if (statusProcess.running) {
      actionStatus = "Bose controls are refreshing; try again shortly"
      actionMessageTimer.restart()
      return false
    }
    actionStatus = ""
    vendorError = ""
    actionOutput = ""
    actionError = ""
    actionTimedOut = false
    actionSuccessText = successText
    actionRequestAddress = selectedDevice.address
    actionRequestGeneration = vendorGeneration
    actionProcess.command = command(args)
    actionProcess.running = true
    return true
  }

  function setMode(mode) {
    if (!mode) return
    if (runAction(["mode", mode], "Mode: " + Model.modeLabel(mode))) pendingMode = mode
  }

  function setCnc(value) {
    if (!cncAvailable) return
    var level = Math.max(0, Math.min(vendorStatus.cncMax, Math.round(value)))
    if (runAction(["cnc", String(level)], "Cancellation: " + level + "/" + vendorStatus.cncMax)) pendingCnc = level
  }

  function setEqualizer(values, successText) {
    if (!eqAvailable || !values || values.length !== 3) return false
    var normalized = []
    for (var i = 0; i < 3; i++) {
      var value = Number(values[i])
      var band = vendorStatus.eqBands[i]
      if (!isFinite(value) || Math.round(value) !== value
          || value < band.minimum || value > band.maximum) return false
      normalized.push(value)
    }
    if (Model.equalizerValuesMatch(displayedEqBands, normalized)) return true
    var message = successText || "Equalizer updated"
    if (!runAction([
      "eq", String(normalized[0]), String(normalized[1]), String(normalized[2])
    ], message)) return false
    pendingEq = normalized
    return true
  }

  function resetEqualizer() {
    return setEqualizer([0, 0, 0], "Equalizer reset")
  }

  function clearActionStatus() {
    actionStatus = ""
  }

  property bool refreshQueued: false
  property string statusRequestAddress: ""
  property string actionRequestAddress: ""
  property string actionSuccessText: ""
  property int vendorGeneration: 0
  property int statusRequestGeneration: -1
  property int actionRequestGeneration: -1

  onBoseDevicesChanged: reconcileDevices()
  onSelectedAddressChanged: {
    vendorGeneration++
    var selected = findDevice(selectedAddress)
    var isConnected = selected ? selected.connected : false
    selectedDeviceSignature = selectedAddress ? selectedAddress + ":" + (isConnected ? "connected" : "paired") : ""
    refreshQueued = false
    if (statusProcess.running) statusProcess.running = false
    if (actionProcess.running) actionProcess.running = false
    clearVendor(active && isConnected ? "loading" : "idle")
    clearPending()
    vendorError = ""
    actionStatus = ""
    // The selectedDevice binding updates after this property handler.
    Qt.callLater(refreshVendor)
  }
  onActiveChanged: {
    vendorGeneration++
    if (active) {
      refreshDiscovery()
      refreshVendor()
    } else {
      refreshQueued = false
      if (statusProcess.running) statusProcess.running = false
      if (actionProcess.running) actionProcess.running = false
      clearVendor("idle")
      clearPending()
      vendorError = ""
      actionStatus = ""
    }
  }

  Timer {
    id: vendorTimer
    interval: root.pollIntervalMs
    repeat: true
    running: root.active
    onTriggered: root.refreshVendor()
  }

  Timer {
    id: discoveryDebounce
    interval: 800
    repeat: false
    onTriggered: root.refreshDiscovery()
  }

  Timer {
    id: discoveryTimer
    interval: 30000
    repeat: true
    running: root.active
    onTriggered: root.refreshDiscovery()
  }

  onRawDevicesChanged: discoveryDebounce.restart()

  Timer {
    id: verificationRefresh
    interval: 700 + root.pendingVerificationAttempts * 700
    repeat: false
    onTriggered: root.refreshVendor()
  }

  Timer {
    id: actionMessageTimer
    interval: 2600
    repeat: false
    onTriggered: root.clearActionStatus()
  }

  Timer {
    id: selectionSaveTimer
    interval: 250
    repeat: false
    onTriggered: root.flushSelection()
  }

  Timer {
    interval: 20000
    repeat: false
    running: statusProcess.running
    onTriggered: {
      root.statusTimedOut = true
      statusProcess.running = false
    }
  }

  Timer {
    interval: 20000
    repeat: false
    running: actionProcess.running
    onTriggered: {
      root.actionTimedOut = true
      actionProcess.running = false
    }
  }

  Timer {
    interval: 10000
    repeat: false
    running: discoveryProcess.running
    onTriggered: discoveryProcess.running = false
  }

  // Selection persistence lives in the bridge, where the path itself can
  // be validated (regular file, owned by us, no symlinks, size-capped)
  // instead of trusting FileView blindly. Load always succeeds with a
  // (possibly empty) document; save fails loudly on invalid input.
  Process {
    id: selectionLoadProcess
    clearEnvironment: true
    environment: ({})
    command: []
    stdout: StdioCollector {
      id: selectionLoadStdout
      waitForEnd: true
      onStreamFinished: root.selectionLoadOutput = text
    }
    onExited: function(exitCode) {
      root.loadSelection(exitCode === 0
        ? String(selectionLoadStdout.text || root.selectionLoadOutput || "")
        : "")
    }
  }

  Process {
    id: selectionSaveProcess
    clearEnvironment: true
    environment: ({})
    command: []
  }

  // Child processes start with a scrubbed environment: the bridge reads
  // nothing from env (absolute paths everywhere, explicit UTF-8 decoding),
  // so ambient variables like LD_PRELOAD or PYTHONPATH cannot reach it or
  // the bluetoothctl it spawns. Buffering to end-of-stream stays safe
  // because the producer is capped and the parsers refuse past
  // MAX_JSON_BYTES (kept equal to OUTPUT_CAP_BYTES). A compromised child
  // degrades to the stale/empty states below instead of growing here.
  Process {
    id: discoveryProcess
    clearEnvironment: true
    environment: ({})
    command: []
    stdout: StdioCollector {
      id: discoveryStdout
      waitForEnd: true
      onStreamFinished: root.discoveryOutput = text
    }
    stderr: StdioCollector {
      id: discoveryStderr
      waitForEnd: true
      onStreamFinished: root.discoveryError = text
    }
    onExited: function(exitCode) {
      var output = String(discoveryStdout.text || root.discoveryOutput || "")
      if (exitCode === 0) {
        var addrs = Model.parseDiscoveryAddresses(output)
        if (!Model.sameAddresses(addrs, root.discoveredBoseAddresses))
          root.discoveredBoseAddresses = addrs
      }
      // On failure or timeout the previous allowlist stays in place and the
      // alias fallback in Model.js keeps devices visible until the next tick.
      if (root.discoveryQueued && root.active) root.refreshDiscovery()
      else root.discoveryQueued = false
    }
  }

  Process {
    id: statusProcess
    clearEnvironment: true
    environment: ({})
    command: []
    stdout: StdioCollector {
      id: statusStdout
      waitForEnd: true
      onStreamFinished: root.statusOutput = text
    }
    stderr: StdioCollector {
      id: statusStderr
      waitForEnd: true
      onStreamFinished: root.statusError = text
    }
    onExited: function(exitCode) {
      var output = String(statusStdout.text || root.statusOutput || "")
      var error = String(statusStderr.text || root.statusError || "")
      var selected = root.selectedDevice
      if (root.statusRequestGeneration !== root.vendorGeneration
          || !root.active || !selected || !selected.connected
          || root.statusRequestAddress !== selected.address) {
        if (root.active && root.refreshQueued && selected && selected.connected)
          root.refreshVendor()
        return
      }
      var failure = ""
      if (root.statusTimedOut) {
        failure = "Bose status request timed out"
      } else if (exitCode !== 0) {
        failure = Model.errorForProcess(error || output)
      } else {
        try {
          var parsed = Model.parseBridgeStatus(output)
          if (!parsed.reachable || parsed.address !== root.statusRequestAddress.toUpperCase())
            throw new Error("Bose returned status for a different device")
          root.vendorStatus = parsed
          root.vendorStatusAddress = root.statusRequestAddress
          root.vendorState = "ready"
          root.vendorError = ""

          var pendingMismatch = false
          if (root.pendingMode !== "" && parsed.mode === root.pendingMode)
            root.pendingMode = ""
          else if (root.pendingMode !== "") pendingMismatch = true
          if (root.pendingCnc >= 0 && parsed.cnc === root.pendingCnc)
            root.pendingCnc = -1
          else if (root.pendingCnc >= 0) pendingMismatch = true
          if (root.pendingEq.length === 3
              && parsed.eqAvailable
              && Model.equalizerValuesMatch(parsed.eqBands, root.pendingEq))
            root.pendingEq = []
          else if (root.pendingEq.length === 3) pendingMismatch = true

          if (pendingMismatch) root.retryPendingChange()
          else root.pendingVerificationAttempts = 0
        } catch (parseError) {
          failure = String(parseError)
        }
      }
      if (failure !== "") {
        root.vendorError = Model.errorForProcess(failure)
        if (root.vendorMatchesSelection) root.vendorState = "stale"
        else root.clearVendor("error")
        root.retryPendingChange()
      }
      if (root.refreshQueued) root.refreshVendor()
    }
  }

  Process {
    id: actionProcess
    clearEnvironment: true
    environment: ({})
    command: []
    stdout: StdioCollector {
      id: actionStdout
      waitForEnd: true
      onStreamFinished: root.actionOutput = text
    }
    stderr: StdioCollector {
      id: actionStderr
      waitForEnd: true
      onStreamFinished: root.actionError = text
    }
    onExited: function(exitCode) {
      var selected = root.selectedDevice
      if (root.actionRequestGeneration !== root.vendorGeneration
          || !root.active || !selected || !selected.connected
          || root.actionRequestAddress !== selected.address) return
      if (exitCode === 0) {
        root.vendorError = ""
        root.actionStatus = root.actionSuccessText
        root.pendingVerificationAttempts = 0
        actionMessageTimer.restart()
        verificationRefresh.restart()
      } else {
        root.clearPending()
        var output = String(actionStderr.text || root.actionError || actionStdout.text || root.actionOutput || "")
        root.vendorError = root.actionTimedOut
          ? "Bose control request timed out" : Model.errorForProcess(output)
        actionMessageTimer.restart()
        verificationRefresh.restart()
      }
    }
  }

  Component.onCompleted: {
    runSelectionLoad()
    reconcileDevices()
    refreshDiscovery()
  }

  Component.onDestruction: {
    // Reap path: a disabled or removed plugin must not leave bridge or
    // bluetoothctl processes behind. Stopping here sends SIGTERM, which
    // the bridge forwards down to its own child, so the whole tree dies
    // together; anything wedged past signals is unreachable by definition
    // and expires on its own timeouts. Best effort by nature -- teardown
    // does not wait -- which is why every call below is also bounded.
    if (discoveryProcess.running) discoveryProcess.running = false
    if (statusProcess.running) statusProcess.running = false
    if (actionProcess.running) actionProcess.running = false
    if (selectionLoadProcess.running) selectionLoadProcess.running = false
    if (selectionSaveProcess.running) selectionSaveProcess.running = false
  }
}
