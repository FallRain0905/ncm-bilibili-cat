import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 顶部页头：当前页标题与说明 + 主题切换。
Rectangle {
    color: App.surface

    property var pageInfo: App.pages[Math.max(0, App.pageIndex)]

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: App.borderColor
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.pageMargin
        anchors.rightMargin: Theme.pageMargin
        spacing: Theme.spacingM

        ColumnLayout {
            spacing: 0
            Layout.fillWidth: true

            Label {
                text: pageInfo.title
                color: App.textPrimary
                font.pixelSize: Theme.fontSizeSection + 4
                font.bold: true
            }

            Label {
                text: pageInfo.subtitle
                color: App.textSecondary
                font.pixelSize: Theme.fontSizeCaption
            }
        }

        Button {
            text: App.themeDark ? "☀ 浅色" : "🌙 深色"
            onClicked: App.toggleTheme()

            background: Rectangle {
                radius: Theme.radiusButton
                color: parent.hovered ? App.surfaceHover : App.surfaceRaised
                border.color: App.borderColor
                border.width: 1
            }

            contentItem: Label {
                text: parent.text
                color: App.textPrimary
                font.pixelSize: Theme.fontSizeCaption
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
}
