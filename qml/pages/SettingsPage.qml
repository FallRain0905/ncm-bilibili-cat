import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."
import "../components"

// 设置页（阶段 1 可用部分：外观与关于；其余在阶段 7 补全）。
ColumnLayout {
    spacing: Theme.blockSpacing

    ColumnLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pageMargin
        Layout.rightMargin: Theme.pageMargin
        Layout.topMargin: Theme.pageMargin
        spacing: Theme.spacingM

        PageHeader {
            title: "外观"
            subtitle: "主题即时生效，重启后保持"
        }

        RowLayout {
            spacing: Theme.spacingM

            Button {
                text: App.themeDark ? "当前：深色" : "当前：浅色"
                enabled: false

                background: Rectangle {
                    radius: Theme.radiusButton
                    color: App.surfaceRaised
                    border.color: App.borderColor
                    border.width: 1
                }

                contentItem: Label {
                    text: parent.text
                    color: App.textPrimary
                    font.pixelSize: Theme.fontSizeBody
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: Theme.spacingL
                    rightPadding: Theme.spacingL
                }
            }

            Button {
                text: "切换深浅主题"
                onClicked: App.toggleTheme()

                background: Rectangle {
                    radius: Theme.radiusButton
                    color: parent.hovered ? App.accentHover : App.accent
                }

                contentItem: Label {
                    text: parent.text
                    color: "#ffffff"
                    font.pixelSize: Theme.fontSizeBody
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: Theme.spacingL
                    rightPadding: Theme.spacingL
                }
            }
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.pageMargin
        Layout.rightMargin: Theme.pageMargin
        spacing: Theme.spacingM

        PageHeader {
            title: "关于"
            subtitle: "开源 · 非商业 · 仅限下载本人有权访问的内容"
        }

        Label {
            text: "版本：v" + App.version
            color: App.textSecondary
            font.pixelSize: Theme.fontSizeBody
        }

        Label {
            text: '项目主页：<a href="' + App.githubUrl + '">' + App.githubUrl + "</a>"
            onLinkActivated: function(link) { Qt.openUrlExternally(link) }
            color: App.textSecondary
            font.pixelSize: Theme.fontSizeBody
        }

        Label {
            text: "许可证与第三方组件声明见安装目录下的 LICENSE.md 与 THIRD_PARTY_NOTICES.md。"
            color: App.textMuted
            font.pixelSize: Theme.fontSizeCaption
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    Item { Layout.fillHeight: true }
}
