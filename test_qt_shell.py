"""Qt 版应用冒烟测试：离屏加载 QML 外壳，验证导航/主题/协议门逻辑。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine


class _QtTestBase(unittest.TestCase):
    """每个测试独占一次 QGuiApplication 生命周期（Qt 不允许多实例并存）。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self._app = QGuiApplication.instance() or QGuiApplication([])
        self.addCleanup(self._cleanup_qt)

    def _cleanup_qt(self):
        if QGuiApplication.instance() is self._app:
            self._app.quit()

    def _load_shell(self, env_patch=None):
        """加载 Main.qml 外壳；返回 (engine, root_object)。"""
        context = None
        if env_patch:
            context = patch.dict(os.environ, env_patch)
            context.start()
            self.addCleanup(context.stop)
        from qt_bridge.app_controller import AppController
        controller = AppController()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("App", controller)
        root = Path(__file__).parent
        engine.addImportPath(str(root / "qml"))
        engine.load(QUrl.fromLocalFile(str(root / "qml" / "Main.qml")))
        self.addCleanup(engine.deleteLater)
        self.assertTrue(engine.rootObjects(), "QML 外壳应成功加载")
        return controller


class QtShellSmokeTests(_QtTestBase):
    def test_main_window_loads(self):
        controller = self._load_shell({"LOCALAPPDATA": str(self.root / "appdata"),
                                       "APPDATA": str(self.root / "roaming")})
        self.assertEqual(controller.pageIndex, 0)
        self.assertFalse(controller.licenseAccepted)

    def test_all_six_pages_exist(self):
        controller = self._load_shell({"LOCALAPPDATA": str(self.root / "appdata"),
                                       "APPDATA": str(self.root / "roaming")})
        self.assertEqual(len(controller.pages), 6)


class AppControllerLogicTests(_QtTestBase):
    def test_navigation_and_theme_persist(self):
        from ncm_settings import load_settings
        appdata = self.root / "appdata"
        controller = self._load_shell({"LOCALAPPDATA": str(appdata),
                                       "APPDATA": str(self.root / "roaming")})
        controller.navigate("download")
        self.assertEqual(controller.pageIndex, 3)
        controller.navigate("download")  # 重复导航不重复发信号
        self.assertEqual(controller.pageIndex, 3)
        controller.navigate("不存在的页面")
        self.assertEqual(controller.pageIndex, 3)

        self.assertTrue(controller.themeDark)
        controller.toggleTheme()
        self.assertFalse(controller.themeDark)
        persisted = load_settings()
        self.assertEqual(persisted["theme"], "light")

    def test_license_gate_persists_and_skips(self):
        from ncm_settings import load_settings
        appdata = self.root / "appdata"
        controller = self._load_shell({"LOCALAPPDATA": str(appdata),
                                       "APPDATA": str(self.root / "roaming")})
        self.assertFalse(controller.licenseAccepted)
        controller.acceptLicense()
        self.assertTrue(controller.licenseAccepted)
        self.assertEqual(load_settings()["license_agreed_version"], 1)
        # 已同意后重复调用不再变化
        controller.acceptLicense()
        self.assertTrue(controller.licenseAccepted)

    def test_decline_does_not_persist(self):
        from ncm_settings import load_settings
        controller = self._load_shell({"LOCALAPPDATA": str(self.root / "appdata"),
                                       "APPDATA": str(self.root / "roaming")})
        controller.declineLicense()
        self.assertFalse(controller.licenseAccepted)
        self.assertNotIn("license_agreed_version", load_settings())

    def test_palette_switches_with_theme(self):
        controller = self._load_shell({"LOCALAPPDATA": str(self.root / "appdata"),
                                       "APPDATA": str(self.root / "roaming")})
        dark_bg = controller.windowBackground
        dark_accent = controller.accent
        controller.toggleTheme()
        self.assertNotEqual(controller.windowBackground, dark_bg)
        self.assertNotEqual(controller.accent, dark_accent)


if __name__ == "__main__":
    unittest.main()
