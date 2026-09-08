import QtQuick
import Quickshell

ShellRoot {
  Service {
    id: service
  }

  Timer {
    interval: 20
    repeat: true
    running: true
    onTriggered: {
      if (!service.selectionLoaded) return
      console.log("RESULT selection " + service.preferredAddress)
      Qt.quit()
    }
  }

  Timer {
    interval: 10000
    running: true
    onTriggered: {
      console.log("RESULT timeout")
      Qt.quit()
    }
  }
}
