"""WorkerSession 行为测试：完成/异常/停止/忙时拒绝（重构文档阶段 2 完成定义）。

不使用 QSignalSpy：PySide6 6.11 下 QSignalSpy.wait 与本项目的
跨线程收尾链存在兼容问题（探针确认生产代码收尾正常），改用
信号计数 + processEvents 轮询。
"""
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QThread
from PySide6.QtGui import QGuiApplication

from qt_bridge.workers import BaseWorker, FunctionWorker, WorkerSession


class LoopWorker(BaseWorker):
    """循环等待停止信号的最小 Worker。"""

    def __init__(self, cycles=100, interval=0.02, parent=None):
        super().__init__(parent)
        self._cycles = cycles
        self._interval = interval
        self.completed_cycles = 0

    def execute(self):
        for _ in range(self._cycles):
            if self.stop_requested:
                break
            time.sleep(self._interval)
            self.completed_cycles += 1
            self.progressText.emit(f"cycle {self.completed_cycles}")


class BoomWorker(BaseWorker):
    def execute(self):
        raise RuntimeError("引擎爆炸模拟")


def wait_until(predicate, timeout_ms=5000):
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if predicate():
            return True
        QGuiApplication.processEvents()
        time.sleep(0.01)
    return predicate()


class WorkerSessionTests(unittest.TestCase):
    def setUp(self):
        self.app = QGuiApplication.instance() or QGuiApplication([])
        self.addCleanup(self._quit_app)
        self.errors = []

    def _quit_app(self):
        if QGuiApplication.instance() is self.app:
            self.app.quit()

    def _make_session(self):
        session = WorkerSession("测试")
        finished_count = {"n": 0}
        session.finished.connect(lambda: finished_count.__setitem__("n", finished_count["n"] + 1))
        session.error.connect(self.errors.append)
        def teardown():
            session.stop()
            # 断言失败后也必须等线程收尾完成，否则 GC 会销毁运行中的 QThread。
            wait_until(lambda: not session.busy, 5000)
            QGuiApplication.processEvents()
        self.addCleanup(teardown)
        return session, finished_count

    def test_success_flow_recovers_busy(self):
        session, finished = self._make_session()
        session.start(FunctionWorker(lambda stop, progress: progress("进行中")))
        self.assertTrue(session.busy)
        self.assertTrue(wait_until(lambda: finished["n"] == 1))
        self.assertFalse(session.busy)
        self.assertEqual(self.errors, [])

    def test_exception_emits_error_and_finished(self):
        session, finished = self._make_session()
        session.start(BoomWorker())
        self.assertTrue(wait_until(lambda: finished["n"] == 1))
        self.assertEqual(len(self.errors), 1)
        self.assertIn("引擎爆炸", self.errors[0])
        self.assertFalse(session.busy)

    def test_stop_is_idempotent_and_effective(self):
        session, finished = self._make_session()
        worker = LoopWorker(cycles=200)
        session.start(worker)
        session.stop()
        session.stop()  # 重复调用安全
        self.assertTrue(wait_until(lambda: finished["n"] == 1))
        self.assertLess(worker.completed_cycles, 200)
        session.stop()  # 结束后调用同样安全
        self.assertFalse(session.busy)

    def test_stop_when_idle_is_safe(self):
        session, _ = self._make_session()
        session.stop()
        session.stop()
        self.assertFalse(session.busy)

    def test_busy_start_is_rejected(self):
        session, finished = self._make_session()
        session.start(LoopWorker(cycles=200))
        self.assertTrue(session.busy)
        rejected = FunctionWorker(lambda stop, progress: None)
        self.assertFalse(session.start(rejected))
        self.assertEqual(len(self.errors), 1)
        self.assertIn("已有任务正在运行", self.errors[0])
        session.stop()
        self.assertTrue(wait_until(lambda: finished["n"] >= 1))
        self.assertFalse(session.busy)
        # 结束后可再次启动
        self.assertTrue(session.start(FunctionWorker(lambda stop, progress: None)))
        session.stop()
        self.assertTrue(wait_until(lambda: finished["n"] >= 2))
        self.assertFalse(session.busy)

    def test_worker_thread_affinity(self):
        session, finished = self._make_session()
        worker = FunctionWorker(lambda stop, progress: None)
        session.start(worker)
        self.assertIsNot(worker.thread(), self.app.thread())
        self.assertIsInstance(worker.thread(), QThread)
        session.stop()
        self.assertTrue(wait_until(lambda: finished["n"] == 1))


if __name__ == "__main__":
    unittest.main()
