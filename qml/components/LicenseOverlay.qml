import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 首启协议门：主窗口保持可见，模态覆盖层展示协议全文（文档 §5.8）。
Rectangle {
    id: overlay
    color: "#cc0b0e13"

    // 阻断下层交互
    MouseArea { anchors.fill: parent; onClicked: function() {} }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 720)
        height: Math.min(parent.height - 80, 640)
        radius: Theme.radiusCard
        color: App.surfaceRaised
        border.color: App.borderColor
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.spacingL
            spacing: Theme.spacingM

            Label {
                text: "用户协议与使用条款"
                color: App.textPrimary
                font.pixelSize: Theme.fontSizeSection
                font.bold: true
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true

                TextArea {
                    readOnly: true
                    text: App.agreementText
                    color: App.textSecondary
                    font.pixelSize: Theme.fontSizeBody
                    wrapMode: Text.WordWrap
                    background: Rectangle {
                        color: App.surface
                        radius: Theme.radiusButton
                        border.color: App.borderColor
                        border.width: 1
                    }
                }
            }

            Label {
                text: '<a href="' + App.githubUrl + '">' + App.githubUrl + "</a>"
                onLinkActivated: function(link) { Qt.openUrlExternally(link) }
                color: App.accent
                font.pixelSize: Theme.fontSizeCaption
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: Theme.spacingM

                Button {
                    text: "不同意（退出）"
                    onClicked: App.declineLicense()

                    background: Rectangle {
                        radius: Theme.radiusButton
                        color: parent.hovered ? App.surfaceHover : App.surfaceRaised
                        border.color: App.dangerColor
                        border.width: 1
                    }

                    contentItem: Label {
                        text: parent.text
                        color: App.dangerColor
                        font.pixelSize: Theme.fontSizeBody
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: Theme.spacingL
                        rightPadding: Theme.spacingL
                    }
                }

                Button {
                    text: "同意并继续"
                    onClicked: App.acceptLicense()

                    background: Rectangle {
                        radius: Theme.radiusButton
                        color: parent.hovered ? App.accentHover : App.accent
                    }

                    contentItem: Label {
                        text: parent.text
                        color: "#ffffff"
                        font.pixelSize: Theme.fontSizeBody
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: Theme.spacingL * 1.5
                        rightPadding: Theme.spacingL * 1.5
                    }
                }
            }
        }
    }
}
