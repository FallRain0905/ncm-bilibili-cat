import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."
import "../components"

// 首页：工作台（文档 §5.2）——任务统计、快捷入口；不做营销 Hero。
ColumnLayout {
    spacing: Theme.blockSpacing

    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pageMargin
        Layout.rightMargin: Theme.pageMargin
        Layout.topMargin: Theme.pageMargin
        spacing: Theme.blockSpacing

        Repeater {
            model: [
                { "label": "待转换", "hint": "加入转换队列的 NCM 文件" },
                { "label": "待下载", "hint": "下载队列中等待的任务" },
                { "label": "已完成", "hint": "本机历史记录中的成功任务" },
                { "label": "失败", "hint": "需要重试或人工处理" }
            ]

            delegate: Rectangle {
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredHeight: 96
                radius: Theme.radiusCard
                color: App.surfaceRaised
                border.color: App.borderColor
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacingL
                    spacing: 2

                    Label {
                        text: modelData.label
                        color: App.textSecondary
                        font.pixelSize: Theme.fontSizeCaption
                    }

                    Label {
                        text: "—"
                        color: App.textPrimary
                        font.pixelSize: Theme.fontSizePageTitle
                        font.bold: true
                    }

                    Label {
                        text: modelData.hint
                        color: App.textMuted
                        font.pixelSize: Theme.fontSizeCaption
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pageMargin
        Layout.rightMargin: Theme.pageMargin
        spacing: Theme.blockSpacing

        // 快捷入口：拖入 NCM
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 140
            radius: Theme.radiusCard
            color: App.surface
            border.color: App.borderColor
            border.width: 1

            ColumnLayout {
                anchors.centerIn: parent
                spacing: Theme.spacingM

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "⇄"
                    color: App.accent
                    font.pixelSize: 30
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "转换本地 NCM 文件"
                    color: App.textPrimary
                    font.pixelSize: Theme.fontSizeBody
                    font.bold: true
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "把 .ncm 文件拖入“音乐管理”页，或到“转换”页选择文件"
                    color: App.textSecondary
                    font.pixelSize: Theme.fontSizeCaption
                }

                Button {
                    Layout.alignment: Qt.AlignHCenter
                    text: "前往转换"

                    onClicked: App.navigate("convert")

                    background: Rectangle {
                        radius: Theme.radiusButton
                        color: parent.hovered ? App.accentHover : App.accent
                    }

                    contentItem: Label {
                        text: parent.text
                        color: "#ffffff"
                        font.pixelSize: Theme.fontSizeCaption
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: Theme.spacingL
                        rightPadding: Theme.spacingL
                    }
                }
            }
        }

        // 快捷入口：网易云歌单
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 140
            radius: Theme.radiusCard
            color: App.surface
            border.color: App.borderColor
            border.width: 1

            ColumnLayout {
                anchors.centerIn: parent
                spacing: Theme.spacingM

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "☰"
                    color: App.successColor
                    font.pixelSize: 30
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "导入网易云歌单"
                    color: App.textPrimary
                    font.pixelSize: Theme.fontSizeBody
                    font.bold: true
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "扫码登录后导入歌单，批量加入下载队列"
                    color: App.textSecondary
                    font.pixelSize: Theme.fontSizeCaption
                }

                Button {
                    Layout.alignment: Qt.AlignHCenter
                    text: "前往歌单"
                    onClicked: App.navigate("playlist")

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
                        leftPadding: Theme.spacingL
                        rightPadding: Theme.spacingL
                    }
                }
            }
        }
    }

    Item { Layout.fillHeight: true }
}
