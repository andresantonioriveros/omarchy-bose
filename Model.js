.pragma library

function emptyStatus() {
  return {
    reachable: false,
    model: "",
    name: "",
    battery: -1,
    batteries: {
      left: -1,
      right: -1,
      case: -1,
      headphones: -1,
      earbuds: -1
    },
    mode: "",
    cnc: -1,
    cncMax: 10,
    error: ""
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
    text = text.substring(text.indexOf("Connection failed:") + 18)
  return text || "Bose control is unavailable"
}

function parseStatus(raw) {
  var result = emptyStatus()
  var lines = String(raw === undefined || raw === null ? "" : raw).split(/\r?\n/)

  for (var i = 0; i < lines.length; i++) {
    var line = cleanText(lines[i])
    var component = line.match(/^\s*(Left|Right|Case|Headphones|Earbuds)\s+.*?(\d{1,3})%/i)
    if (component) {
      var componentName = component[1].toLowerCase()
      if (componentName === "left") result.batteries.left = parseInt(component[2], 10)
      else if (componentName === "right") result.batteries.right = parseInt(component[2], 10)
      else if (componentName === "case") result.batteries.case = parseInt(component[2], 10)
      else if (componentName === "headphones") result.batteries.headphones = parseInt(component[2], 10)
      else if (componentName === "earbuds") result.batteries.earbuds = parseInt(component[2], 10)
      continue
    }
    var match = line.match(/^\s*(Model|Battery|Mode|CNC|Name)\s+(.+?)\s*$/i)
    if (!match) continue

    var key = match[1].toLowerCase()
    var value = match[2]
    if (key === "model") result.model = value
    else if (key === "name") result.name = value
    else if (key === "battery") {
      var battery = value.match(/-?\d+/)
      if (battery) result.battery = Math.max(0, Math.min(100, parseInt(battery[0], 10)))
    } else if (key === "mode") {
      result.mode = value.toLowerCase().replace(/\s+.*$/, "")
    } else if (key === "cnc") {
      var cnc = value.match(/(\d+)\s*\/\s*(\d+)/)
      if (cnc) {
        result.cnc = parseInt(cnc[1], 10)
        result.cncMax = parseInt(cnc[2], 10)
      }
    }
  }

  result.reachable = result.model !== "" || result.battery >= 0 || result.mode !== "" || result.cnc >= 0
    || result.batteries.left >= 0 || result.batteries.right >= 0 || result.batteries.case >= 0
    || result.batteries.headphones >= 0 || result.batteries.earbuds >= 0
  return result
}

function numberOrUnknown(value) {
  var number = Number(value)
  if (isNaN(number)) return -1
  if (number >= 0 && number <= 1) number *= 100
  return Math.max(0, Math.min(100, Math.round(number)))
}

function textFor(device) {
  if (!device) return ""
  return [device.name, device.deviceName, device.alias, device.description, device.modalias, device.label]
    .join(" ").toLowerCase()
}

function isBoseDevice(device) {
  var text = textFor(device)
  return text.indexOf("bose") >= 0
    || text.indexOf("quietcomfort") >= 0
    || text.indexOf("qc-") >= 0
    || text.indexOf("qc_") >= 0
    || /(^|\s)qc(\s|$)/.test(text)
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
  var text = textFor(device)
  if (text.indexOf("earbud") >= 0 || text.indexOf("earplug") >= 0)
    return text.indexOf("ultra") >= 0 ? "QuietComfort Ultra 2 Earbuds" : "QuietComfort Earbuds"
  if (text.indexOf("headphone") >= 0 || text.indexOf("qc-") >= 0 || text.indexOf("qc_") >= 0)
    return text.indexOf("ultra") >= 0 ? "QuietComfort Ultra 2 Headphones" : "QuietComfort Headphones"
    return "QuietComfort Headphones"
  return device.name || device.deviceName || "Bose device"
}

function deviceSnapshot(device) {
  return {
    address: String(device && device.address || ""),
    name: String(device && device.name || ""),
    deviceName: String(device && device.deviceName || ""),
    connected: !!(device && device.connected),
    battery: batteryPercent(device),
    earbuds: isEarbuds(device),
    label: deviceLabel(device)
  }
}

function sortDevices(devices) {
  return devices.sort(function(a, b) {
    if (a.connected !== b.connected) return a.connected ? -1 : 1
    return a.label.localeCompare(b.label)
  })
}

function deviceType(device) {
  var text = textFor(device)
  var earbuds = device && device.earbuds === true || isEarbuds(device)
  if (/(^|\s)(qc[-_ ]?35|quietcomfort[-_ ]?35)(\s|$)/.test(text)) return "qc35"
  if (/(^|\s)(qc[-_ ]?45|quietcomfort[-_ ]?45)(\s|$)/.test(text)) return "qc45"
  if (earbuds) return text.indexOf("ultra") >= 0 ? "qc_ultra2_earbuds" : "qc_earbuds"
  if (text.indexOf("ultra") >= 0) return "qc_ultra2"
  return "qc_prince"
}

function modeOptions(status) {
  var text = String((status && status.model) || "") .toLowerCase()
  if (text.indexOf("qc35") >= 0 || text.indexOf("quietcomfort 35") >= 0) {
    return [
      { id: "high", label: "High", detail: "Maximum cancellation" },
      { id: "low", label: "Low", detail: "Reduced cancellation" },
      { id: "off", label: "Off", detail: "No cancellation" }
    ]
  }
  if (text.indexOf("ultra") >= 0) {
    return [
      { id: "quiet", label: "Quiet", detail: "Maximum cancellation" },
      { id: "aware", label: "Aware", detail: "Transparency" },
      { id: "immersion", label: "Immersion", detail: "Spatial audio" },
      { id: "cinema", label: "Cinema", detail: "Spatial audio" }
    ]
  }
  return [
    { id: "quiet", label: "Quiet", detail: "Maximum cancellation" },
    { id: "aware", label: "Aware", detail: "Transparency" }
  ]
}

function batteryRows(device, status) {
  var batteries = status && status.batteries ? status.batteries : {}
  var rows = []
  var hasBuds = Number(batteries.left) >= 0 || Number(batteries.right) >= 0
  var hasHeadphones = Number(batteries.headphones) >= 0
  var hasEarbuds = Number(batteries.earbuds) >= 0

  if (hasBuds) {
    rows.push({ label: "Left", level: Number(batteries.left), detail: "" })
    rows.push({ label: "Right", level: Number(batteries.right), detail: "" })
  } else if (hasHeadphones) {
    rows.push({ label: "Headphones", level: Number(batteries.headphones), detail: "" })
  } else if (hasEarbuds) {
    rows.push({ label: "Earbuds", level: Number(batteries.earbuds), detail: "" })
  } else {
    rows.push({
      label: device && device.earbuds ? "Earbuds" : "Headphones",
      level: status && Number(status.battery) >= 0
        ? Number(status.battery)
        : -1,
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

function errorForProcess(stderr, path) {
  var error = cleanError(stderr)
  if (String(path || "") === "bosectl"
      && (error.indexOf("not found") >= 0
        || error.indexOf("No such file") >= 0
        || error.indexOf("Failed to start") >= 0))
    return "Run the Omabose setup script to install bosectl"
  return error
}
