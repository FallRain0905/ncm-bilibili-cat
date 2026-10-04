import QtQuick
import QtQuick.Controls
import ".."
import "../components"

// 转换页（阶段 3 接线；当前为迁移占位与说明）。
Item {
    EmptyState {
        anchors.fill: parent
        icon: "⇄"
        message: "转换页正在迁移到新界面"
        hint: "当前版本请先使用旧版界面的“转换”功能；\n本页将在后续版本提供完整的选择、拖放、进度与日志能力。"
        primaryText: "查看音乐管理"
        primaryAction: function() { App.navigate("manage") }
        secondaryText: "查看下载"
        secondaryAction: function() { App.navigate("download") }
    }
}
