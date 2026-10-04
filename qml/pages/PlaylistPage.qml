import QtQuick
import QtQuick.Controls
import ".."
import "../components"

// 网易云歌单页（阶段 6 接线；当前为迁移占位与说明）。
Item {
    EmptyState {
        anchors.fill: parent
        icon: "☰"
        message: "网易云歌单页正在迁移到新界面"
        hint: "本页将提供扫码登录、歌单导入、状态筛选与批量加入下载。"
        primaryText: "返回首页"
        primaryAction: function() { App.navigate("dashboard") }
        secondaryText: "查看设置"
        secondaryAction: function() { App.navigate("settings") }
    }
}
