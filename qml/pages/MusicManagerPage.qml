import QtQuick
import QtQuick.Controls
import ".."
import "../components"

// 音乐管理页（阶段 4 接线；当前为迁移占位与说明）。
Item {
    EmptyState {
        anchors.fill: parent
        icon: "♫"
        message: "音乐管理页正在迁移到新界面"
        hint: "本页将提供本地歌曲扫描、状态筛选、搜索与批量加入转换。"
        primaryText: "查看下载"
        primaryAction: function() { App.navigate("download") }
        secondaryText: "返回首页"
        secondaryAction: function() { App.navigate("dashboard") }
    }
}
