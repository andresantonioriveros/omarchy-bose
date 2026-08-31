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

  property var boseDevices: []
  property string selectedAddress: ""
  property string selectedDeviceSignature: ""
  property var vendorStatus: Model.emptyStatus()
  property string vendorStatusAddress: ""
  property string pendingMode: ""
  property int pendingCnc: -1
  property string vendorError: ""
  property string actionStatus: ""
  property string statusOutput: ""
  property string statusError: ""
  property string actionOutput: ""
  property string actionError: ""

  readonly property var connectedDevices: boseDevices.filter(function(device) { return device.connected })
  readonly property var selectedDevice: {
    for (var i = 0; i < boseDevices.length; i++) {
      if (boseDevices[i].address === selectedAddress) return boseDevices[i]
    }
    return null
  }
  readonly property int battery: selectedDevice
    ? (vendorStatus.reachable && vendorStatus.battery >= 0 ? vendorStatus.battery : -1)
    : -1
  readonly property string selectedMode: pendingMode !== ""
    ? pendingMode : (vendorStatus.reachable ? vendorStatus.mode : "")
  readonly property int displayedCnc: pendingCnc >= 0
    ? pendingCnc
    : (vendorStatus.cnc >= 0 ? vendorStatus.cncMax - vendorStatus.cnc : -1)
  readonly property var modeOptions: Model.modeOptions(vendorStatus)
  readonly property var batteryRows: Model.batteryRows(selectedDevice, vendorStatus)
  readonly property bool vendorAvailable: vendorStatus.reachable
  readonly property bool vendorLoading: active && selectedDevice && selectedDevice.connected
    && (!vendorStatus.reachable || vendorStatusAddress !== selectedAddress)
    && vendorError === ""
  readonly property bool cncAvailable: vendorStatus.reachable && vendorStatus.cnc >= 0
  readonly property string controlPath: "bosectl"

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function refreshDevices() {
    var next = []
    for (var i = 0; i < rawDevices.length; i++) {
      if (Model.isBoseDevice(rawDevices[i])) next.push(Model.deviceSnapshot(rawDevices[i]))
    }
    boseDevices = Model.sortDevices(next)

    var current = selectedDevice
    var target = current
    if (!target) {
      for (var j = 0; j < boseDevices.length; j++) {
        if (boseDevices[j].connected) {
          target = boseDevices[j]
          break
        }
      }
    }
    if (!target && boseDevices.length > 0) target = boseDevices[0]

    var nextAddress = target ? target.address : ""
    var nextSignature = target ? target.address + ":" + (target.connected ? "connected" : "paired") : ""
    var stateChanged = nextSignature !== selectedDeviceSignature
    if (stateChanged) vendorGeneration++
    selectedDeviceSignature = nextSignature
    if (nextAddress !== selectedAddress) selectedAddress = nextAddress
    else if (stateChanged) refreshVendor()
  }

  function select(address) {
    if (!address || address === selectedAddress) return
    selectedAddress = address
  }

  function command(args) {
    if (!selectedDevice || !selectedDevice.connected) return []
    return [
      "env",
      "BOSE_MAC=" + selectedDevice.address,
      "BMAP_DEVICE=" + Model.deviceType(selectedDevice),
      controlPath
    ].concat(args)
  }

  function refreshVendor() {
    vendorError = ""
    if (!active || !selectedDevice || !selectedDevice.connected) {
      refreshQueued = false
      vendorStatus = Model.emptyStatus()
      vendorStatusAddress = ""
      pendingMode = ""
      pendingCnc = -1
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
    statusOutput = ""
    statusError = ""
    statusRequestAddress = selectedDevice.address
    statusRequestGeneration = vendorGeneration
    statusProcess.command = command(["status"])
    statusProcess.running = true
  }

  function runAction(args, successText) {
    if (!active || !selectedDevice || !selectedDevice.connected || actionProcess.running) return false
    if (statusProcess.running) {
      actionStatus = "Bose controls are refreshing; try again shortly"
      actionMessageTimer.restart()
      return false
    }
    actionStatus = ""
    vendorError = ""
    actionOutput = ""
    actionError = ""
    actionSuccessText = successText
    actionRequestAddress = selectedDevice.address
    actionRequestGeneration = vendorGeneration
    actionProcess.command = command(args)
    actionProcess.running = true
    return true
  }

  function setMode(mode) {
    if (!mode) return
    if (runAction([mode], "Mode: " + Model.modeLabel(mode))) pendingMode = mode
  }

  function setCnc(value) {
    if (!cncAvailable) return
    var level = Math.max(0, Math.min(vendorStatus.cncMax, Math.round(value)))
    var vendorLevel = vendorStatus.cncMax - level
    if (runAction(["cnc", String(vendorLevel)], "Cancellation: " + level + "/" + vendorStatus.cncMax)) pendingCnc = level
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

  onRawDevicesChanged: refreshDevices()
  onSelectedAddressChanged: {
    vendorGeneration++
    vendorStatus = Model.emptyStatus()
    vendorStatusAddress = ""
    pendingMode = ""
    pendingCnc = -1
    actionStatus = ""
    refreshVendor()
  }
  onActiveChanged: {
    vendorGeneration++
    if (active) refreshVendor()
    else {
      refreshQueued = false
      if (statusProcess.running) statusProcess.running = false
      if (actionProcess.running) actionProcess.running = false
      vendorStatus = Model.emptyStatus()
      vendorStatusAddress = ""
      pendingMode = ""
      pendingCnc = -1
      vendorError = ""
      actionStatus = ""
    }
  }

  Timer {
    id: deviceTimer
    interval: 2500
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refreshDevices()
  }

  Timer {
    id: vendorTimer
    interval: Math.max(5, Number(root.setting("pollIntervalSec", 15))) * 1000
    repeat: true
    running: root.active
    onTriggered: root.refreshVendor()
  }

  Timer {
    id: delayedRefresh
    interval: 450
    repeat: false
    onTriggered: root.refreshVendor()
  }

  Timer {
    id: actionMessageTimer
    interval: 2600
    repeat: false
    onTriggered: root.clearActionStatus()
  }

  Process {
    id: statusProcess
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
      if (exitCode === 0) {
        var parsed = Model.parseStatus(output)
        if (parsed.reachable) {
          root.vendorStatus = parsed
          root.vendorStatusAddress = root.statusRequestAddress
          if (root.pendingMode !== "" && parsed.mode === root.pendingMode)
            root.pendingMode = ""
          if (root.pendingCnc >= 0 && parsed.cnc >= 0
              && parsed.cncMax - parsed.cnc === root.pendingCnc)
            root.pendingCnc = -1
          root.vendorError = ""
        } else if (!root.vendorStatus.reachable || root.vendorStatusAddress !== root.statusRequestAddress) {
          root.vendorError = "Bose returned no readable status"
        }
      } else if (!root.vendorStatus.reachable || root.vendorStatusAddress !== root.statusRequestAddress) {
        root.vendorStatus = Model.emptyStatus()
        root.vendorStatusAddress = ""
        root.vendorError = Model.errorForProcess(error || output, root.controlPath)
      }
      if (root.refreshQueued) root.refreshVendor()
    }
  }

  Process {
    id: actionProcess
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
        actionMessageTimer.restart()
        delayedRefresh.restart()
      } else {
        root.pendingMode = ""
        root.pendingCnc = -1
        var output = String(actionStderr.text || root.actionError || actionStdout.text || root.actionOutput || "")
        root.vendorError = Model.errorForProcess(output, root.controlPath)
        actionMessageTimer.restart()
        delayedRefresh.restart()
      }
    }
  }
}
