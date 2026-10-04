"""Qt 版应用运行时：初始化、异常与退出流程。"""
import os
import sys
from pathlib import Path

# 必须在 QApplication 创建前设置：Basic 样式支持完全自定义视觉（文档 §4）。
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from qt_bridge.app_controller import AppController

PROJECT_ROOT = Path(__file__).parent


def resource_root() -> Path:
    """源码运行指向项目根目录；PyInstaller 冻结运行指向资源目录。"""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return PROJECT_ROOT


def run_application(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # Basic 样式：视觉完全由项目调色板控制（GUI现代化文档 §4）
    app = QGuiApplication(argv)
    app.setApplicationName("Music Cat")
    app.setOrganizationName("FallRain0905")

    icon_path = resource_root() / "assets" / "icon.ico"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    controller = AppController()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("App", controller)
    engine.addImportPath(str(resource_root() / "qml"))
    engine.load(QUrl.fromLocalFile(str(resource_root() / "qml" / "Main.qml")))
    if not engine.rootObjects():
        return 1
    return app.exec()
