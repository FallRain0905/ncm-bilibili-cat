import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 页面区块标题。
ColumnLayout {
    property string title
    property string subtitle: ""

    spacing: 2

    Label {
        text: title
        color: App.textPrimary
        font.pixelSize: Theme.fontSizeSection
        font.bold: true
    }

    Label {
        visible: subtitle !== ""
        text: subtitle
        color: App.textSecondary
        font.pixelSize: Theme.fontSizeCaption
    }
}
