pragma Singleton
import QtQuick

// 结构令牌（间距/尺寸/字号/圆角），与主题无关；颜色来自 AppController。
QtObject {
    readonly property int pageMargin: 24
    readonly property int blockSpacing: 20
    readonly property int spacingS: 8
    readonly property int spacingM: 12
    readonly property int spacingL: 16

    readonly property int radiusCard: 8
    readonly property int radiusButton: 6

    readonly property int sidebarWidth: 224
    readonly property int sidebarCollapsedWidth: 68
    readonly property int headerHeight: 64
    readonly property int disclaimerHeight: 32

    readonly property int fontSizePageTitle: 24
    readonly property int fontSizeSection: 16
    readonly property int fontSizeBody: 14
    readonly property int fontSizeCaption: 12

    readonly property string fontFamily: "Microsoft YaHei UI"
}
