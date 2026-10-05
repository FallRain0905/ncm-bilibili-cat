"""Qt 线程基建：把现有回调式引擎适配为 Qt Worker（重构文档 §6.3）。

约定：
- Worker 是普通 QObject，moveToThread 后在工人线程执行；
- Worker 不触碰任何 QML 对象，通过信号报告进度/错误/完成；
- 异常必须转为 error 信号，finished 总会发出（busy 必能恢复）；
- 停止使用 threading.Event，重复调用幂等且线程安全。
"""
import threading

from PySide6.QtCore import QObject, Property, Signal, Slot, QThread


class BaseWorker(QObject):
    """耗时任务基类：子类实现 execute()，循环中检查 stop_requested。"""

    progressText = Signal(str, arguments=["message"])
    error = Signal(str, arguments=["message"])
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_event = threading.Event()

    def stop(self):
        """请求停止：幂等、可重复调用、未运行也安全。"""
        self._stop_event.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    @Slot()
    def run(self):
        """工人线程入口：异常转 error，最终必发 finished。"""
        try:
            self.execute()
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    def execute(self):
        raise NotImplementedError


class FunctionWorker(BaseWorker):
    """执行 callable(stop_event, progress) 的轻量 Worker，供一次性任务使用。"""

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self._function = function

    def execute(self):
        self._function(self._stop_event, self.progressText.emit)


class WorkerSession(QObject):
    """单工位任务会话：一个领域同一时间最多一个 Worker（文档 §6.3）。

    忙时 start() 拒绝并发出 error（调用方负责提示）；停止请求幂等。
    已结束的线程/Worker 引用暂存 graveyard，避免 Python 侧提前回收
    正在收尾的 Qt 对象；每次 start 只保留最近几个。
    """

    busyChanged = Signal()
    error = Signal(str, arguments=["message"])
    finished = Signal()

    GRAVEYARD_LIMIT = 8

    def __init__(self, name: str = "", parent=None):
        super().__init__(parent)
        self._name = name
        self._thread: QThread | None = None
        self._worker: BaseWorker | None = None
        self._graveyard: list[tuple[QThread, BaseWorker]] = []

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._thread is not None

    @Slot()
    def stop(self):
        """请求当前任务停止：幂等、可重复调用、空闲时安全。"""
        if self._worker is not None:
            self._worker.stop()

    def start(self, worker: BaseWorker) -> bool:
        """在独立线程启动 Worker；忙时拒绝并返回 False。"""
        if self._thread is not None:
            self.error.emit(f"{self._name}：已有任务正在运行")
            return False
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error.connect(self.error)
        # 收尾连接必须在启动时挂好：worker.finished 的排队调用会让线程在
        # 主线程处理完队列前就退出，事后挂接 thread.finished 会永远错过。
        thread.finished.connect(self._cleanup)
        self._thread = thread
        self._worker = worker
        self.busyChanged.emit()
        thread.start()
        return True

    def _cleanup(self):
        thread, worker = self._thread, self._worker
        if thread is not None:
            # finished 信号发出后 OS 线程可能尚未完全终止；
            # 此后任何引用回收都会销毁 QThread，必须先等它真正退出。
            thread.wait(2000)
            self._graveyard.append((thread, worker))
            if len(self._graveyard) > self.GRAVEYARD_LIMIT:
                del self._graveyard[:-4]
        self._thread = None
        self._worker = None
        self.busyChanged.emit()
        self.finished.emit()
