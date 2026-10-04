import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 空状态：一句说明 + 主操作 + 次操作（文档 §5.2 要求，不允许纯空白）。
Rectangle {
    id: emptyState

    property string icon: "◌"
    property string message: "暂无内容"
    property string hint: ""
    property alias primaryText: primaryButton.text
    property var primaryAction: null
    property alias secondaryText: secondaryButton.text
    property var secondaryAction: null

    color: "transparent"

    ColumnLayout {
        anchors.centerIn: parent
        spacing: Theme.spacingM
        width: Math.min(parent.width - Theme.pageMargin * 2, 420)

        Label {
            Layout.alignment: Qt.AlignHCenter
            text: emptyState.icon
            color: App.textMuted
            font.pixelSize: 42
        }

        Label {
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            text: emptyState.message
            color: App.textSecondary
            font.pixelSize: Theme.fontSizeBody
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
        }

        Label {
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            visible: emptyState.hint !== ""
            text: emptyState.hint
            color: App.textMuted
            font.pixelSize: Theme.fontSizeCaption
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: Theme.spacingM

            Button {
                id: primaryButton
                visible: text !== ""
                onClicked: if (emptyState.primaryAction) emptyState.primaryAction()

                background: Rectangle {
                    radius: Theme.radiusButton
                    color: primaryButton.hovered ? App.accentHover : App.accent
                }

                contentItem: Label {
                    text: primaryButton.text
                    color: "#ffffff"
                    font.pixelSize: Theme.fontSizeBody
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: Theme.spacingL
                    rightPadding: Theme.spacingL
                }
            }

            Button {
                id: secondaryButton
                visible: text !== ""
                onClicked: if (emptyState.secondaryAction) emptyState.secondaryAction()

                background: Rectangle {
                    radius: Theme.radiusButton
                    color: secondaryButton.hovered ? App.surfaceHover : App.surfaceRaised
                    border.color: App.borderColor
                    border.width: 1
                }

                contentItem: Label {
                    text: secondaryButton.text
                    color: App.textPrimary
                    font.pixelSize: Theme.fontSizeBody
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: Theme.spacingL
                    rightPadding: Theme.spacingL
                }
            }
        }
    }
}
