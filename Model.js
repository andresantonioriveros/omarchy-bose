function emptyStatus() {
  return {
    reachable: false,
    address: "",
    deviceType: "",
    model: "",
    battery: -1,
    batteries: {
      left: -1,
      right: -1,
      case: -1
    },
    mode: "",
    modeLabel: "",
    modeOptions: [],
    cnc: -1,
    cncMax: 0,
    cncAvailable: false
  }
}

function cleanText(value) {
  return String(value === undefined || value === null ? "" : value)
    .replace(/\u001b\[[0-?]*[ -\/]*[@-~]/g, "")
    .replace(/[\r\n]+/g, " ")
    .replace(/^\s+|\s+$/g, "")
}

function cleanError(value) {
  var text = cleanText(value)
  if (text.indexOf("Connection failed:") >= 0)
    text = text.substring(text.indexOf("Connection failed:") + 18).replace(/^\s+/, "")
  if (text.indexOf("Omabose:") === 0)
    text = text.substring(8).replace(/^\s+/, "")
  return text || "Bose control is unavailable"
}

function percentage(value) {
  if (value === undefined || value === null || value === "") return -1
  var number = Number(value)
  if (!isFinite(number)) return -1
  return Math.max(0, Math.min(100, Math.round(number)))
}

function parseBridgeStatus(raw) {
  var payload = JSON.parse(String(raw === undefined || raw === null ? "" : raw))
  if (!payload || Number(payload.schemaVersion) !== 1)
    throw new Error("Unsupported Bose status format")

  var status = emptyStatus()
  var device = payload.device || {}
  var battery = payload.battery || {}
  var components = battery.components || {}
  var mode = payload.mode || {}
  var noise = payload.noiseControl || {}

  status.address = String(device.address || "").toUpperCase()
  status.deviceType = String(device.type || "")
  status.model = cleanText(device.model)
  status.battery = percentage(battery.level)
  status.batteries.left = percentage(components.left)
  status.batteries.right = percentage(components.right)
  status.batteries.case = percentage(components.case)
  status.mode = String(mode.currentId || "").toLowerCase()
  status.modeLabel = cleanText(mode.currentLabel)

  var options = Array.isArray(mode.options) ? mode.options : []
  for (var i = 0; i < options.length; i++) {
    var id = String(options[i] && options[i].id || "").toLowerCase()
    if (!id) continue
    status.modeOptions.push({
      id: id,
      label: cleanText(options[i].label) || modeLabel(id),
      detail: cleanText(options[i].detail)
    })
    if (id === status.mode) status.modeLabel = status.modeOptions[status.modeOptions.length - 1].label
  }
  if (!status.modeLabel && status.mode) status.modeLabel = modeLabel(status.mode)

  status.cncAvailable = noise.available === true
  status.cnc = status.cncAvailable ? percentage(noise.level) : -1
  status.cncMax = status.cncAvailable ? Math.max(0, Math.round(Number(noise.maximum) || 0)) : 0
  status.reachable = status.address !== "" && status.deviceType !== "" && status.battery >= 0
  return status
}

function numberOrUnknown(value) {
  var number = Number(value)
  if (isNaN(number)) return -1
  if (number >= 0 && number <= 1) number *= 100
  return Math.max(0, Math.min(100, Math.round(number)))
}

function textFor(device) {
  if (!device) return ""
  return [device.name, device.deviceName].join(" ").toLowerCase()
}

function isBoseDevice(device) {
  var text = textFor(device)
  return text.indexOf("bose") >= 0
    || text.indexOf("quietcomfort") >= 0
    || /(^|[^a-z0-9])qc([^a-z0-9]|$)/.test(text)
}

function isEarbuds(device) {
  var text = textFor(device)
  return text.indexOf("earbud") >= 0 || text.indexOf("earplug") >= 0 || text.indexOf("earphone") >= 0
}

function batteryPercent(device) {
  if (!device || device.batteryAvailable === false) return -1
  return numberOrUnknown(device.battery)
}

function deviceLabel(device) {
  if (!device) return "Bose"
  return cleanText(device.deviceName || device.name) || "Bose device"
}

function deviceSnapshot(device) {
  return {
    address: String(device && device.address || ""),
    connected: !!(device && device.connected),
    paired: !!(device && (device.paired || device.bonded)),
    known: !!(device && (device.connected || device.paired || device.bonded || device.trusted)),
    battery: batteryPercent(device),
    earbuds: isEarbuds(device),
    label: deviceLabel(device)
  }
}

function sortDevices(devices) {
  return devices.slice().sort(function(a, b) {
    if (a.connected !== b.connected) return a.connected ? -1 : 1
    return a.label.localeCompare(b.label)
  })
}

function toArray(values) {
  if (!values) return []
  if (Array.isArray(values)) return values.slice()
  var length = Number(values.length || 0)
  if (!isFinite(length) || length <= 0) return []
  var result = []
  for (var i = 0; i < length; i++) result.push(values[i])
  return result
}

function boseDeviceRows(values) {
  var devices = toArray(values)
  var rows = []
  for (var i = 0; i < devices.length; i++) {
    var device = devices[i]
    if (!device || !isBoseDevice(device)) continue
    if (!(device.connected || device.paired || device.bonded || device.trusted)) continue
    rows.push(deviceSnapshot(device))
  }
  return sortDevices(rows)
}

function deviceForAddress(devices, address) {
  var wanted = String(address || "").toUpperCase()
  for (var i = 0; devices && i < devices.length; i++) {
    if (String(devices[i].address || "").toUpperCase() === wanted) return devices[i]
  }
  return null
}

function preferredDevice(devices, currentAddress, preferredAddress) {
  var preferred = deviceForAddress(devices, preferredAddress)
  if (preferred) return preferred

  var current = deviceForAddress(devices, currentAddress)
  if (current && current.connected) return current

  for (var i = 0; devices && i < devices.length; i++) {
    if (devices[i].connected) return devices[i]
  }
  return current || (devices && devices.length > 0 ? devices[0] : null)
}

function batteryRows(device, status) {
  var batteries = status && status.batteries ? status.batteries : {}
  var rows = []
  var hasBuds = Number(batteries.left) >= 0 || Number(batteries.right) >= 0

  if (hasBuds) {
    rows.push({ label: "Left", level: Number(batteries.left), detail: "" })
    rows.push({ label: "Right", level: Number(batteries.right), detail: "" })
  } else {
    rows.push({
      label: device && device.earbuds ? "Earbuds" : "Headphones",
      level: status && Number(status.battery) >= 0
        ? Number(status.battery)
        : (device && Number(device.battery) >= 0 ? Number(device.battery) : -1),
      detail: ""
    })
  }

  if (Number(batteries.case) >= 0)
    rows.push({ label: "Case", level: Number(batteries.case), detail: "" })
  return rows
}

function modeLabel(id) {
  var text = String(id || "")
  return text.length > 0 ? text.charAt(0).toUpperCase() + text.slice(1) : "Unknown"
}

function modeIconVariant(id) {
  if (id === "quiet" || id === "high") return "modeQuiet"
  if (id === "aware" || id === "low") return "modeAware"
  if (id === "relax") return "modeRelax"
  if (id === "immersion") return "modeImmersion"
  if (id === "cinema") return "modeCinema"
  if (id === "off") return "modeOff"
  return "mode"
}

function cursorRows(devices, modes, vendorAvailable, cncAvailable) {
  var rows = []
  if (devices && devices.length > 1) {
    for (var i = 0; i < devices.length; i++)
      rows.push({ key: "device:" + devices[i].address, kind: "device", id: devices[i].address, index: i })
  }
  if (vendorAvailable) {
    for (var m = 0; modes && m < modes.length; m++)
      rows.push({ key: "mode:" + modes[m].id, kind: "mode", id: modes[m].id, index: m })
    if (cncAvailable) rows.push({ key: "cnc", kind: "cnc", id: "cnc", index: -1 })
  }
  return rows
}

function rowIndex(rows, key) {
  for (var i = 0; rows && i < rows.length; i++) {
    if (rows[i].key === key) return i
  }
  return -1
}

function errorForProcess(stderr) {
  return cleanError(stderr)
}
