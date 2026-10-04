"""应用外壳控制器：导航、主题、首启协议门、版本信息与 Toast。

安全边界（与 Tkinter 版一致）：
- 凭据仍由 credential_store（Windows DPAPI）管理，本控制器不接触凭据内容；
- 协议文本与免责声明来自 app_info，单一来源；
- 设置读写沿用 ncm_settings 的白名单清洗与原子保存。
"""
from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication

from app_info import (APP_TITLE, APP_VERSION, AGREEMENT_TEXT,
                      AGREEMENT_VERSION, DISCLAIMER_TEXT, GITHUB_URL)
from ncm_settings import load_settings, save_settings


class AppController(QObject):
    pageChanged = Signal()
    themeChanged = Signal()
    licenseChanged = Signal()
    sidebarChanged = Signal()
    toastRaised = Signal(str, arguments=["message"])

    PAGES = [
        {"key": "dashboard", "title": "首页", "subtitle": "任务总览与快捷入口", "icon": "⌂"},
        {"key": "convert", "title": "转换", "subtitle": "本地 NCM 转 FLAC / MP3", "icon": "⇄"},
        {"key": "manage", "title": "音乐管理", "subtitle": "扫描、筛选和管理本地歌曲", "icon": "♫"},
        {"key": "download", "title": "下载", "subtitle": "Bilibili 音频下载与下载队列", "icon": "⇩"},
        {"key": "playlist", "title": "网易云歌单", "subtitle": "歌单导入与批量下载", "icon": "☰"},
        {"key": "settings", "title": "设置", "subtitle": "外观、默认值与关于", "icon": "⚙"},
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = load_settings()
        self._page_index = 0
        self._theme_dark = self._settings.get("theme", "dark") != "light"
        self._license_accepted = (int(self._settings.get("license_agreed_version") or 0)
                                  >= AGREEMENT_VERSION)
        self._sidebar_expanded = True

    # ---- 调色板（GUI现代化文档 §4.3，深浅主题即时切换）----
    _PALETTES = {
        True: {  # 深色
            "windowBackground": "#111418", "surface": "#191D23",
            "surfaceRaised": "#20262E", "surfaceHover": "#272E38",
            "border": "#303844", "textPrimary": "#F2F4F7",
            "textSecondary": "#AAB3BF", "textMuted": "#778292",
            "accent": "#5B8DEF", "accentHover": "#729EFF",
            "success": "#3CCB8A", "warning": "#E4B455", "danger": "#E56B76",
        },
        False: {  # 浅色
            "windowBackground": "#F5F7FA", "surface": "#FFFFFF",
            "surfaceRaised": "#F0F3F7", "surfaceHover": "#E8EDF3",
            "border": "#D8DEE7", "textPrimary": "#1D2530",
            "textSecondary": "#5C6878", "textMuted": "#8792A2",
            "accent": "#376FD5", "accentHover": "#2C5DB8",
            "success": "#168A5A", "warning": "#9A6B08", "danger": "#C43F4B",
        },
    }

    def _palette_color(self, name: str) -> str:
        return self._PALETTES[self._theme_dark][name]

    @Property(str, notify=themeChanged)
    def windowBackground(self):
        return self._palette_color("windowBackground")

    @Property(str, notify=themeChanged)
    def surface(self):
        return self._palette_color("surface")

    @Property(str, notify=themeChanged)
    def surfaceRaised(self):
        return self._palette_color("surfaceRaised")

    @Property(str, notify=themeChanged)
    def surfaceHover(self):
        return self._palette_color("surfaceHover")

    @Property(str, notify=themeChanged)
    def borderColor(self):
        return self._palette_color("border")

    @Property(str, notify=themeChanged)
    def textPrimary(self):
        return self._palette_color("textPrimary")

    @Property(str, notify=themeChanged)
    def textSecondary(self):
        return self._palette_color("textSecondary")

    @Property(str, notify=themeChanged)
    def textMuted(self):
        return self._palette_color("textMuted")

    @Property(str, notify=themeChanged)
    def accent(self):
        return self._palette_color("accent")

    @Property(str, notify=themeChanged)
    def accentHover(self):
        return self._palette_color("accentHover")

    @Property(str, notify=themeChanged)
    def successColor(self):
        return self._palette_color("success")

    @Property(str, notify=themeChanged)
    def warningColor(self):
        return self._palette_color("warning")

    @Property(str, notify=themeChanged)
    def dangerColor(self):
        return self._palette_color("danger")

    # ---- 只读信息 ----
    @Property(str, constant=True)
    def appTitle(self):
        return APP_TITLE

    @Property(str, constant=True)
    def version(self):
        return APP_VERSION

    @Property(str, constant=True)
    def githubUrl(self):
        return GITHUB_URL

    @Property(str, constant=True)
    def agreementText(self):
        return AGREEMENT_TEXT

    @Property(str, constant=True)
    def disclaimerText(self):
        return DISCLAIMER_TEXT

    # ---- 导航 ----
    @Property(int, notify=pageChanged)
    def pageIndex(self):
        return self._page_index

    @Property("QVariantList", constant=True)
    def pages(self):
        return self.PAGES

    @Slot(str)
    def navigate(self, key: str):
        for index, page in enumerate(self.PAGES):
            if page["key"] == key:
                if index != self._page_index:
                    self._page_index = index
                    self.pageChanged.emit()
                return

    # ---- 侧边栏 ----
    @Property(bool, notify=sidebarChanged)
    def sidebarExpanded(self):
        return self._sidebar_expanded

    @Slot()
    def toggleSidebar(self):
        self._sidebar_expanded = not self._sidebar_expanded
        self.sidebarChanged.emit()

    # ---- 主题 ----
    @Property(bool, notify=themeChanged)
    def themeDark(self):
        return self._theme_dark

    @Slot()
    def toggleTheme(self):
        self._set_theme(not self._theme_dark)

    def _set_theme(self, dark: bool):
        if dark == self._theme_dark:
            return
        self._theme_dark = dark
        self._persist_settings({"theme": "dark" if dark else "light"})
        self.themeChanged.emit()

    # ---- 首启协议门 ----
    @Property(bool, notify=licenseChanged)
    def licenseAccepted(self):
        return self._license_accepted

    @Slot()
    def acceptLicense(self):
        if self._license_accepted:
            return
        self._license_accepted = True
        self._persist_settings({"license_agreed_version": AGREEMENT_VERSION})
        self.licenseChanged.emit()
        self.toastRaised.emit("已同意用户协议，欢迎使用 Music Cat")

    @Slot()
    def declineLicense(self):
        application = QGuiApplication.instance()
        if application is not None:
            application.quit()

    # ---- 内部 ----
    def _persist_settings(self, updates: dict):
        """在保留现有设置的前提下更新白名单字段（ncm_settings 负责清洗）。"""
        merged = load_settings()
        merged.update(updates)
        save_settings(merged)
