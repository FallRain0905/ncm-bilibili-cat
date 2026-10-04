import QtQuick
import QtQuick.Controls
import ".."
import "../components"

// 下载页（阶段 5 接线；当前为迁移占位与说明）。
Item {
    EmptyState {
        anchors.fill: parent
        icon: "⇩"
        message: "下载页正在迁移到新界面"
        hint: "本页将提供 Bilibili 音频下载、下载队列、任务详情与运行日志。"
        primaryText: "查看歌单"
        primaryAction: function() { App.navigate("playlist") }
        secondaryText: "返回首页"
        secondaryAction: function() { App.navigate("dashboard") }
    }
}
