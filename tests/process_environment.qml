import QtQuick
import Quickshell
import Quickshell.Io

ShellRoot {
  property string output: ""

  Process {
    clearEnvironment: true
    environment: ({})
    command: ["/usr/bin/env"]
    running: true
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: output = text
    }
    onExited: function(exitCode) {
      console.log("RESULT " + (exitCode === 0 && output === "" ? "pass" : "fail"))
      Qt.quit()
    }
  }

  Timer {
    interval: 5000
    running: true
    onTriggered: {
      console.log("RESULT timeout")
      Qt.quit()
    }
  }
}
