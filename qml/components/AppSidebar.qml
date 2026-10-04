import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 侧边导航：图标 + 文字，当前项高亮；底部显示版本与 GitHub 入口。
Rectangle {
    id: sidebar
    color: App.surface

    property bool collapsed: !App.sidebarExpanded

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: Theme.spacingM
        spacing: 0

        // 顶部品牌
        Item {
            Layout.preferredHeight: Theme.headerHeight
            Layout.fillWidth: true

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: sidebar.collapsed ? Theme.spacingS : Theme.spacingM
                anchors.rightMargin: Theme.spacingM
                spacing: Theme.spacingM

                Rectangle {
                    width: 32; height: 32; radius: 8
                    color: App.accent
                    Label {
                        anchors.centerIn: parent
                        text: "♪"
                        color: "#ffffff"
                        font.pixelSize: 18
                        font.bold: true
                    }
                }

                Label {
                    visible: !sidebar.collapsed
                    text: App.appTitle
                    color: App.textPrimary
                    font.pixelSize: Theme.fontSizeSection
                    font.bold: true
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: App.borderColor
        }

        // 导航项
        Repeater {
            model: App.pages

            delegate: ItemDelegate {
                id: navItem
                required property var modelData
                required property int index

                Layout.fillWidth: true
                Layout.preferredHeight: 48
                onClicked: App.navigate(modelData.key)

                background: Rectangle {
                    color: App.pageIndex === navItem.index
                           ? App.surfaceHover : (navItem.hovered ? App.surfaceRaised : "transparent")

                    // 当前选中态的强调条（不只靠颜色区分，还有图标与缩进）
                    Rectangle {
                        width: 3
                        height: 24
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        color: App.accent
                        visible: App.pageIndex === navItem.index
                    }
                }

                contentItem: RowLayout {
                    spacing: Theme.spacingM

                    Item {
                        width: Theme.sidebarCollapsedWidth - Theme.spacingL
                        height: 24

                        Label {
                            anchors.centerIn: parent
                            text: navItem.modelData.icon
                            color: App.pageIndex === navItem.index ? App.accent : App.textSecondary
                            font.pixelSize: 16
                        }
                    }

                    Label {
                        visible: !sidebar.collapsed
                        text: navItem.modelData.title
                        color: App.pageIndex === navItem.index ? App.textPrimary : App.textSecondary
                        font.pixelSize: Theme.fontSizeBody
                        font.bold: App.pageIndex === navItem.index
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }

                ToolTip.visible: sidebar.collapsed && navItem.hovered
                ToolTip.text: navItem.modelData.title
                ToolTip.delay: 400
            }
        }

        Item { Layout.fillHeight: true }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: App.borderColor
        }

        // 折叠/展开
        ItemDelegate {
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            onClicked: App.toggleSidebar()

            background: Rectangle {
                color: parent.hovered ? App.surfaceHover : "transparent"
            }

            contentItem: Label {
                text: sidebar.collapsed ? "»" : "« 收起"
                color: App.textMuted
                horizontalAlignment: sidebar.collapsed ? Text.AlignHCenter : Text.AlignLeft
                leftPadding: sidebar.collapsed ? 0 : Theme.spacingM
            }
        }

        // 版本与 GitHub
        ColumnLayout {
            visible: !sidebar.collapsed
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spacingM
            Layout.rightMargin: Theme.spacingM
            Layout.bottomMargin: Theme.spacingM
            spacing: 2

            Label {
                text: "v" + App.version
                color: App.textMuted
                font.pixelSize: Theme.fontSizeCaption
            }

            Label {
                text: "GitHub 项目主页"
                color: App.accent
                font.pixelSize: Theme.fontSizeCaption
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Qt.openUrlExternally(App.githubUrl)
                }
            }
        }
    }
}
