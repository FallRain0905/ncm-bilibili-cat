import QtQuick
import QtQuick.Controls
import ".."

// Toast 提示：淡入停留后淡出（文档 §5.9）。
Item {
    id: host

    function showToast(message) {
        toastLabel.text = message
        toastRectangle.opacity = 1
        toastTimer.restart()
    }

    Connections {
        target: App
        function onToastRaised(message) {
            host.showToast(message)
        }
    }

    Rectangle {
        id: toastRectangle
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.disclaimerHeight + Theme.spacingL
        width: Math.min(toastLabel.implicitWidth + Theme.spacingL * 3, parent.width - 80)
        height: toastLabel.implicitHeight + Theme.spacingM * 1.6
        radius: Theme.radiusButton
        color: App ? App.surfaceRaised : "transparent"
        border.color: App ? App.borderColor : "transparent"
        border.width: 1
        opacity: 0

        Behavior on opacity {
            NumberAnimation { duration: 180 }
        }

        Label {
            id: toastLabel
            anchors.centerIn: parent
            color: App.textPrimary
            font.pixelSize: Theme.fontSizeBody
        }
    }

    Timer {
        id: toastTimer
        interval: 3000
        onTriggered: toastRectangle.opacity = 0
    }
}
