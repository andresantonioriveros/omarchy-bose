pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Column {
  id: root

  property var service: null
  property color foreground: Color.foreground
  property color background: Color.background
  property color dim: Qt.darker(foreground, 1.45)
  property string fontFamily: Style.font.family
  property bool cursorActive: false
  property string cursorKey: "band:bass"
  property bool drafting: false
  property var draftValues: []

  readonly property var confirmedBands: service ? service.displayedEqBands : []
  readonly property var displayBands: drafting
    ? Model.equalizerBandsWithValues(confirmedBands, draftValues) : confirmedBands
  readonly property var presets: service ? service.eqPresets : []
  readonly property var navigationKeys: [
    "back", "reset", "band:bass", "band:mid", "band:treble",
    "preset:bassBoost", "preset:bassReducer",
    "preset:trebleBoost", "preset:trebleReducer"
  ]

  signal backRequested()
  signal cursorEngaged()

  width: parent ? parent.width : 0
  spacing: Style.space(14)

  function navigationIndex() {
    return navigationKeys.indexOf(cursorKey)
  }

  function moveCursor(dx, dy) {
    cursorEngaged()
    var index = Math.max(0, navigationIndex())
    if (dx !== 0 && cursorKey.indexOf("band:") === 0) {
      var bandId = cursorKey.substring(5)
      for (var b = 0; b < displayBands.length; b++) {
        if (displayBands[b].id === bandId) {
          adjustBand(b, dx > 0 ? 1 : -1)
          return
        }
      }
    }
    var direction = dy !== 0 ? dy : dx
    if (direction === 0) return
    index = (index + (direction > 0 ? 1 : -1) + navigationKeys.length) % navigationKeys.length
    cursorKey = navigationKeys[index]
  }

  function activateCursor() {
    if (!cursorActive) return
    if (cursorKey === "back") {
      backRequested()
      return
    }
    if (cursorKey === "reset") {
      resetEqualizer()
      return
    }
    if (cursorKey.indexOf("preset:") === 0) {
      var id = cursorKey.substring(7)
      for (var i = 0; i < presets.length; i++) {
        if (presets[i].id === id) {
          applyPreset(presets[i])
          return
        }
      }
    }
  }

  function beginDraft() {
    if (drafting || displayBands.length !== 3) return
    draftValues = Model.equalizerValues(displayBands)
    drafting = true
  }

  function previewBand(index, value) {
    if (index < 0 || index >= displayBands.length) return
    beginDraft()
    var band = confirmedBands[index]
    var next = draftValues.slice()
    next[index] = Math.max(band.minimum, Math.min(band.maximum, Math.round(value)))
    draftValues = next
  }

  function adjustBand(index, delta) {
    previewBand(index, displayBands[index].value + delta)
    keyboardCommit.restart()
  }

  function commitDraft() {
    keyboardCommit.stop()
    if (!drafting || !service) return
    var values = draftValues.slice()
    drafting = false
    draftValues = []
    service.setEqualizer(values, "Equalizer: "
      + Model.formatEqualizerValue(values[0]) + " / "
      + Model.formatEqualizerValue(values[1]) + " / "
      + Model.formatEqualizerValue(values[2]))
  }

  function discardDraft() {
    keyboardCommit.stop()
    drafting = false
    draftValues = []
  }

  function presetSupported(preset) {
    if (!preset || !preset.values || confirmedBands.length !== 3) return false
    for (var i = 0; i < 3; i++) {
      if (preset.values[i] < confirmedBands[i].minimum
          || preset.values[i] > confirmedBands[i].maximum) return false
    }
    return true
  }

  function applyPreset(preset) {
    if (!service || !presetSupported(preset)) return
    discardDraft()
    service.setEqualizer(preset.values, preset.label)
  }

  function resetEqualizer() {
    if (!service) return
    discardDraft()
    service.resetEqualizer()
  }

  Timer {
    id: keyboardCommit
    interval: 350
    repeat: false
    onTriggered: root.commitDraft()
  }

  Item {
    width: parent.width
    implicitHeight: Style.space(34)

    CursorSurface {
      width: Style.space(34)
      height: width
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      hasCursor: root.cursorActive && root.cursorKey === "back"
      foreground: root.foreground

      BoseIcon {
        anchors.centerIn: parent
        iconSize: Style.space(20)
        variant: "back"
        color: root.foreground
      }

      HoverHandler {
        onHoveredChanged: if (hovered) {
          root.cursorEngaged()
          root.cursorKey = "back"
        }
      }
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.backRequested()
      }
    }

    Text {
      textFormat: Text.PlainText
      anchors.centerIn: parent
      text: "EQUALIZER"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      font.bold: true
    }

    CursorSurface {
      width: resetLabel.implicitWidth + Style.space(16)
      height: Style.space(30)
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      hasCursor: root.cursorActive && root.cursorKey === "reset"
      foreground: root.foreground

      Text {
        id: resetLabel
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: "Reset"
        color: Model.equalizerValuesMatch(root.displayBands, [0, 0, 0]) ? root.dim : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      HoverHandler {
        onHoveredChanged: if (hovered) {
          root.cursorEngaged()
          root.cursorKey = "reset"
        }
      }
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.resetEqualizer()
      }
    }
  }

  Text {
    textFormat: Text.PlainText
    visible: root.service && root.service.actionStatus !== ""
    width: parent.width
    text: root.service ? root.service.actionStatus : ""
    color: Color.accent
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
    horizontalAlignment: Text.AlignHCenter
  }

  Row {
    width: parent.width

    Repeater {
      model: root.displayBands

      Item {
        required property var modelData
        width: root.width / 3
        implicitHeight: valueColumn.implicitHeight

        Column {
          id: valueColumn
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(2)

          Text {
            textFormat: Text.PlainText
            anchors.horizontalCenter: parent.horizontalCenter
            text: modelData.label
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
          Text {
            textFormat: Text.PlainText
            anchors.horizontalCenter: parent.horizontalCenter
            text: Model.formatEqualizerValue(modelData.value)
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }
        }
      }
    }
  }

  Item {
    id: graph
    width: parent.width
    height: Style.space(150)

    function xForBand(index) {
      return Style.space(36) + index * (width - Style.space(72)) / 2
    }

    function yForBand(band) {
      var padding = Style.space(20)
      var range = Math.max(1, band.maximum - band.minimum)
      return padding + (band.maximum - band.value) / range * (height - padding * 2)
    }

    function valueForY(index, y) {
      var band = root.confirmedBands[index]
      var padding = Style.space(20)
      var progress = Math.max(0, Math.min(1, (y - padding) / (height - padding * 2)))
      return band.maximum - progress * (band.maximum - band.minimum)
    }

    Canvas {
      id: curve
      anchors.fill: parent

      onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        if (root.displayBands.length !== 3) return

        var center = graph.height / 2
        ctx.lineWidth = 1
        ctx.strokeStyle = Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.16)
        for (var line = -2; line <= 2; line++) {
          ctx.beginPath()
          ctx.moveTo(Style.space(16), center + line * Style.space(7))
          ctx.lineTo(graph.width - Style.space(16), center + line * Style.space(7))
          ctx.stroke()
        }

        var x0 = graph.xForBand(0)
        var x1 = graph.xForBand(1)
        var x2 = graph.xForBand(2)
        var y0 = graph.yForBand(root.displayBands[0])
        var y1 = graph.yForBand(root.displayBands[1])
        var y2 = graph.yForBand(root.displayBands[2])
        ctx.beginPath()
        ctx.moveTo(Style.space(12), y0)
        ctx.lineTo(x0, y0)
        ctx.bezierCurveTo((x0 + x1) / 2, y0, (x0 + x1) / 2, y1, x1, y1)
        ctx.bezierCurveTo((x1 + x2) / 2, y1, (x1 + x2) / 2, y2, x2, y2)
        ctx.lineTo(graph.width - Style.space(12), y2)
        ctx.lineWidth = Math.max(3, Style.space(3))
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        ctx.strokeStyle = root.foreground
        ctx.stroke()
      }

      onWidthChanged: requestPaint()
      onHeightChanged: requestPaint()
    }

    Connections {
      target: root
      function onDisplayBandsChanged() { curve.requestPaint() }
    }

    Repeater {
      model: root.displayBands

      Rectangle {
        required property var modelData
        required property int index
        width: Style.space(23)
        height: width
        radius: width / 2
        x: graph.xForBand(index) - width / 2
        y: graph.yForBand(modelData) - height / 2
        color: root.background
        border.width: Math.max(1, Style.space(1))
        border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.32)
        scale: root.cursorActive && root.cursorKey === "band:" + modelData.id ? 1.14 : 1

        Behavior on x { NumberAnimation { duration: 100; easing.type: Easing.OutCubic } }
        Behavior on y { NumberAnimation { duration: 100; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: 90 } }
      }
    }

    MouseArea {
      id: graphMouse
      property int draggingIndex: -1
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.SizeVerCursor

      function nearestBand(x) {
        var nearest = 0
        var distance = Math.abs(x - graph.xForBand(0))
        for (var i = 1; i < 3; i++) {
          var next = Math.abs(x - graph.xForBand(i))
          if (next < distance) {
            nearest = i
            distance = next
          }
        }
        return distance <= Style.space(34) ? nearest : -1
      }

      onPressed: function(mouse) {
        draggingIndex = nearestBand(mouse.x)
        if (draggingIndex < 0) {
          mouse.accepted = false
          return
        }
        root.cursorEngaged()
        root.cursorKey = "band:" + root.displayBands[draggingIndex].id
        root.previewBand(draggingIndex, graph.valueForY(draggingIndex, mouse.y))
      }
      onPositionChanged: function(mouse) {
        if (draggingIndex >= 0) {
          root.previewBand(draggingIndex, graph.valueForY(draggingIndex, mouse.y))
          return
        }
        var nearest = nearestBand(mouse.x)
        if (nearest >= 0) {
          root.cursorEngaged()
          root.cursorKey = "band:" + root.displayBands[nearest].id
        }
      }
      onReleased: function(mouse) {
        if (draggingIndex < 0) return
        root.previewBand(draggingIndex, graph.valueForY(draggingIndex, mouse.y))
        draggingIndex = -1
        root.commitDraft()
      }
      onCanceled: {
        draggingIndex = -1
        root.discardDraft()
      }
    }
  }

  Grid {
    width: parent.width
    columns: 2
    columnSpacing: Style.space(8)
    rowSpacing: Style.space(8)

    Repeater {
      model: root.presets

      CursorSurface {
        required property var modelData
        width: (root.width - Style.space(8)) / 2
        implicitHeight: Style.space(52)
        current: root.service && root.service.selectedEqPreset === modelData.id
        hasCursor: root.cursorActive && root.cursorKey === "preset:" + modelData.id
        foreground: root.foreground
        bordered: true
        enabled: root.presetSupported(modelData)
        opacity: enabled ? 1 : 0.45

        Text {
          textFormat: Text.PlainText
          anchors.centerIn: parent
          text: modelData.label
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        HoverHandler {
          onHoveredChanged: if (hovered) {
            root.cursorEngaged()
            root.cursorKey = "preset:" + modelData.id
          }
        }
        MouseArea {
          anchors.fill: parent
          enabled: parent.enabled
          cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
          onClicked: root.applyPreset(modelData)
        }
      }
    }
  }
}
