import QtQuick
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.andresariveros.omabose"
  ipcTarget: "io.github.andresariveros.omabose"

  readonly property var service: boseService
  readonly property bool hideWhenDisconnected: !!setting("hideWhenDisconnected", true)
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.45)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property real barIconSize: Style.space(13)
  readonly property bool hasDevice: service.boseDevices.length > 0
  readonly property bool hasConnectedDevice: service.connectedDevices.length > 0
  readonly property string tooltipText: {
    if (!hasDevice) return "Bose - no paired devices"
    var label = service.selectedDevice ? service.selectedDevice.label : "Bose"
    var battery = service.battery >= 0 ? " - " + service.battery + "%" : ""
    var mode = service.selectedModeLabel ? " - " + service.selectedModeLabel : ""
    return label + battery + mode
  }

  property bool cursorActive: false
  property string cursorKey: ""
  readonly property var cursorRows: Model.cursorRows(
    service.boseDevices, service.modeOptions, service.vendorAvailable, service.cncAvailable)
  readonly property int cursorIndex: Model.rowIndex(cursorRows, cursorKey)

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  visible: !hideWhenDisconnected || hasConnectedDevice

  function normalizeCursor() {
    if (cursorRows.length === 0) {
      cursorKey = ""
      return
    }
    if (cursorIndex < 0) cursorKey = cursorRows[0].key
  }

  function moveCursor(dx, dy) {
    if (!cursorActive) {
      cursorActive = true
      normalizeCursor()
      return
    }
    if (cursorRows.length === 0) return

    var current = cursorIndex >= 0 ? cursorRows[cursorIndex] : null
    if (dx !== 0 && current) {
      if (current.kind === "mode") {
        var nextMode = current.index + (dx > 0 ? 1 : -1)
        if (nextMode >= 0 && nextMode < service.modeOptions.length) {
          cursorKey = "mode:" + service.modeOptions[nextMode].id
          service.setMode(service.modeOptions[nextMode].id)
        }
      } else if (current.kind === "cnc") {
        service.setCnc(service.displayedCnc + (dx > 0 ? 1 : -1))
      }
      return
    }
    if (dy !== 0) {
      var nextIndex = (Math.max(0, cursorIndex) + dy + cursorRows.length) % cursorRows.length
      cursorKey = cursorRows[nextIndex].key
    }
  }

  function activateCursor() {
    if (!cursorActive || cursorRows.length === 0) return
    var current = cursorIndex >= 0 ? cursorRows[cursorIndex] : null
    if (!current) return
    if (current.kind === "device") {
      root.service.select(current.id)
    } else if (current.kind === "mode") {
      root.service.setMode(current.id)
    }
  }

  function selectDevice(index) {
    if (index < 0 || index >= service.boseDevices.length) return
    cursorActive = true
    cursorKey = "device:" + service.boseDevices[index].address
    service.select(service.boseDevices[index].address)
  }

  function selectMode(index) {
    if (index < 0 || index >= service.modeOptions.length) return
    cursorActive = true
    cursorKey = "mode:" + service.modeOptions[index].id
    service.setMode(service.modeOptions[index].id)
  }

  onCursorRowsChanged: normalizeCursor()
  onOpenedChanged: {
    if (opened) cursorActive = false
  }

  Service {
    id: boseService
    settings: root.settings
    active: root.opened
  }

  Component {
    id: heroIcon
    BoseIcon {
      iconSize: Style.space(42)
      variant: "logo"
      color: root.foreground
    }
  }

  Component {
    id: barIcon
    Item {
      BoseIcon {
        width: root.barIconSize
        height: root.barIconSize
        iconWidth: width
        iconHeight: iconWidth * 0.557
        anchors.centerIn: parent
        variant: "mark"
        color: root.foreground
      }
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    iconComponent: barIcon
    tooltipText: root.tooltipText
    onPressed: root.toggle()
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    borderSpec: Border.flat(Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.65), 1)
    open: root.opened && root.hasDevice
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(390))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) { root.moveCursor(dx, dy) }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: flickable
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
          id: column
          width: flickable.width
          spacing: Style.space(12)

          PanelHero {
            width: parent.width
            iconComponent: heroIcon
            title: service.selectedDevice ? service.selectedDevice.label : "Bose"
            meta: service.selectedDevice && !service.selectedDevice.connected
              ? "Disconnected"
              : (service.vendorStale
                ? ((service.selectedModeLabel || "Connected") + " - Status stale")
                : (service.vendorAvailable
                  ? (service.selectedModeLabel || "Connected")
                  : (service.vendorLoading ? "Loading Bose controls" :
                    (service.vendorError !== "" ? "Bose controls unavailable" : "Paired device"))))
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Text {
            textFormat: Text.PlainText
            visible: service.actionStatus !== ""
            width: parent.width
            text: service.actionStatus
            color: Color.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            wrapMode: Text.Wrap
          }

          PanelSeparator {
            visible: service.boseDevices.length > 1
            foreground: root.foreground
          }

          Column {
            visible: service.boseDevices.length > 1
            width: parent.width
            spacing: Style.space(6)

            PanelSectionHeader {
              text: "BOSE DEVICES"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: service.boseDevices
              CursorSurface {
                required property var modelData
                required property int index
                width: parent ? parent.width : 0
                implicitHeight: Style.space(48)
                current: service.selectedAddress === modelData.address
                hasCursor: root.cursorActive && root.cursorKey === "device:" + modelData.address
                foreground: root.foreground

                Row {
                  anchors.fill: parent
                  anchors.leftMargin: Style.space(10)
                  anchors.rightMargin: Style.space(10)
                  spacing: Style.space(10)

                  BoseIcon {
                    width: Style.space(22)
                    height: Style.space(22)
                    iconSize: width
                    variant: modelData.earbuds ? "earbuds" : "headphones"
                    fontFamily: root.fontFamily
                    color: modelData.connected ? root.foreground : root.dim
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Column {
                    width: Math.max(0, parent.width - parent.spacing - Style.space(30))
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(2)

                    Text {
                      textFormat: Text.PlainText
                      width: parent.width
                      text: modelData.label
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      elide: Text.ElideRight
                    }

                    Text {
                      textFormat: Text.PlainText
                      width: parent.width
                      text: (modelData.connected ? "Connected" : (modelData.paired ? "Paired" : "Known"))
                        + (modelData.battery >= 0 ? "  -  " + modelData.battery + "%" : "")
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                    }
                  }
                }

                HoverHandler {
                  onHoveredChanged: if (hovered) {
                    root.cursorActive = true
                    root.cursorKey = "device:" + modelData.address
                  }
                }
                MouseArea {
                  anchors.fill: parent
                  onClicked: root.selectDevice(index)
                }
              }
            }
          }

          PanelSeparator {
            visible: service.selectedDevice !== null
            foreground: root.foreground
          }

          Column {
            width: parent.width
            visible: service.selectedDevice !== null
            spacing: Style.space(8)

            PanelSectionHeader {
              text: "BATTERY"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: service.batteryRows

              Item {
                required property var modelData
                width: parent ? parent.width : 0
                implicitHeight: Style.space(22)

                Row {
                  anchors.fill: parent
                  spacing: Style.space(12)

                  Text {
                    id: batteryLabel
                    textFormat: Text.PlainText
                    width: Style.space(88)
                    text: modelData.label
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Rectangle {
                    width: Math.max(0, parent.width - batteryLabel.width - batteryValue.width - parent.spacing * 2)
                    height: Style.space(6)
                    radius: height / 2
                    color: Qt.darker(root.foreground, 3.2)
                    anchors.verticalCenter: parent.verticalCenter

                    Rectangle {
                      width: modelData.level >= 0 ? parent.width * Math.min(1, modelData.level / 100) : 0
                      height: parent.height
                      radius: parent.radius
                      color: root.foreground
                    }
                  }

                  Text {
                    id: batteryValue
                    textFormat: Text.PlainText
                    width: Style.space(42)
                    text: modelData.level >= 0 ? modelData.level + "%" : "-"
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    horizontalAlignment: Text.AlignRight
                    anchors.verticalCenter: parent.verticalCenter
                  }
                }
              }
            }
          }

          PanelSeparator {
            visible: service.vendorAvailable || service.vendorError !== ""
            foreground: root.foreground
          }

          Column {
            visible: service.vendorAvailable && service.modeOptions.length > 0
            width: parent.width
            spacing: Style.space(7)

            PanelSectionHeader {
              text: "LISTENING MODE"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: service.modeOptions
              CursorSurface {
                required property var modelData
                required property int index
                width: parent ? parent.width : 0
                implicitHeight: Style.space(44)
                current: service.selectedMode === modelData.id
                hasCursor: root.cursorActive && root.cursorKey === "mode:" + modelData.id
                foreground: root.foreground

                Row {
                  anchors.fill: parent
                  anchors.leftMargin: Style.space(10)
                  anchors.rightMargin: Style.space(10)
                  spacing: Style.space(10)
                  BoseIcon {
                    width: Style.space(22)
                    height: Style.space(22)
                    iconSize: width
                    variant: Model.modeIconVariant(modelData.id)
                    color: modelData.id === service.selectedMode ? Color.accent : root.dim
                    anchors.verticalCenter: parent.verticalCenter
                  }
                  Column {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(1)
                    Text {
                      textFormat: Text.PlainText
                      text: modelData.label
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      font.bold: true
                    }
                    Text {
                      textFormat: Text.PlainText
                      text: modelData.detail
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }
                }

                HoverHandler {
                  onHoveredChanged: if (hovered) {
                    root.cursorActive = true
                    root.cursorKey = "mode:" + modelData.id
                  }
                }
                MouseArea {
                  anchors.fill: parent
                  onClicked: root.selectMode(index)
                }
              }
            }
          }

          Column {
            visible: service.vendorAvailable && service.cncAvailable
            width: parent.width
            spacing: Style.space(6)

            PanelSectionHeader {
              text: "NOISE CONTROL"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            CursorSurface {
              width: parent.width
              implicitHeight: Style.space(56)
              hasCursor: root.cursorActive && root.cursorKey === "cnc"
              foreground: root.foreground

              Row {
                anchors.fill: parent
                anchors.leftMargin: Style.space(10)
                anchors.rightMargin: Style.space(10)
                spacing: Style.space(10)

                BoseIcon {
                  width: Style.space(22)
                  height: Style.space(22)
                  iconSize: width
                  variant: "noise"
                  color: root.foreground
                  anchors.verticalCenter: parent.verticalCenter
                }

                Column {
                  width: Math.max(0, parent.width - parent.spacing - Style.space(30))
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(3)
                  Text {
                    textFormat: Text.PlainText
                    text: "Cancellation"
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }
                  Text {
                    textFormat: Text.PlainText
                    text: service.displayedCnc + "/" + service.vendorStatus.cncMax
                      + "  -  0 is none, " + service.vendorStatus.cncMax + " is maximum"
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }
              }

              HoverHandler {
                onHoveredChanged: if (hovered) {
                  root.cursorActive = true
                  root.cursorKey = "cnc"
                }
              }
            }

            PanelSlider {
              id: cncSlider
              property real draft: -1
              bar: root.bar
              width: parent.width - Style.space(12)
              anchors.horizontalCenter: parent.horizontalCenter
              minimum: 0
              maximum: service.vendorStatus.cncMax
              step: 1
              integer: true
              value: draft >= 0 ? draft : service.displayedCnc
              onMoved: function(value) { draft = value }
              onReleased: function(value) {
                service.setCnc(value)
                draft = -1
              }
            }
          }

          Text {
            textFormat: Text.PlainText
            visible: !service.vendorAvailable && service.selectedDevice
            width: parent.width
            text: service.selectedDevice
              ? (!service.selectedDevice.connected
                ? "Disconnected"
                : (service.vendorLoading ? "Loading Bose controls..." : "Bose controls unavailable"))
              : ""
            color: service.selectedDevice && (!service.selectedDevice.connected || service.vendorLoading)
              ? root.dim
              : Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            textFormat: Text.PlainText
            visible: service.vendorError !== ""
            width: parent.width
            text: service.vendorError
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
          }
        }
      }
    }
  }
}
