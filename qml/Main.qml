import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
import "components"
import "pages"

// 应用外壳：侧边导航 + 头部 + 页面栈 + 免责声明条 + 首启协议门 + Toast。
ApplicationWindow {
    id: root
    width: 1280
    height: 820
    minimumWidth: 980
    minimumHeight: 640
    visible: true
    title: App.appTitle + " v" + App.version
    color: App.windowBackground
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSizeBody

    RowLayout {
        anchors.fill: parent
        spacing: 0

        AppSidebar {
            Layout.fillHeight: true
            Layout.preferredWidth: App.sidebarExpanded ? Theme.sidebarWidth
                                                       : Theme.sidebarCollapsedWidth
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            AppHeader {
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.headerHeight
            }

            StackLayout {
                id: pageStack
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: App.pageIndex

                DashboardPage {}
                ConvertPage {}
                MusicManagerPage {}
                DownloadPage {}
                PlaylistPage {}
                SettingsPage {}
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.disclaimerHeight
                color: App.surface

                Label {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.pageMargin
                    anchors.rightMargin: Theme.pageMargin
                    text: App.disclaimerText
                    color: App.textMuted
                    font.pixelSize: Theme.fontSizeCaption
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
            }
        }
    }

    LicenseOverlay {
        anchors.fill: parent
        visible: !App.licenseAccepted
    }

    ToastHost {
        anchors.fill: parent
    }
}
