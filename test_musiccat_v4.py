import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import download_engine
from download_engine import DownloadEngine
from download_models import (SOURCE_BILIBILI, SOURCE_NETEASE, STATUS_COMPLETED,
                             STATUS_FAILED, STATUS_PENDING, DownloadJob,
                             TrackInfo, PermanentDownloadError)
import download_queue
from download_queue import load_queue, save_queue


def make_job(job_id=1, title="歌曲", source_kind=SOURCE_BILIBILI, target=None,
             url="https://www.bilibili.com/video/BV1GJ411x7h7", attempts=0):
    info = TrackInfo(title=title, source_kind=source_kind, source_id="BV1GJ411x7h7", url=url)
    return DownloadJob(info=info, fmt="mp3", quality="0", job_id=job_id,
                       target=target, attempts=attempts)


class QueueStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "queue.json"

    def test_round_trip_keeps_pending_only(self):
        pending = make_job(1, title="等待中", target=Path(self.temporary.name) / "a.mp3")
        done = make_job(2, title="已完成", target=Path(self.temporary.name) / "b.mp3")
        done.status = STATUS_COMPLETED
        save_queue([pending, done], self.path)
        restored = load_queue(self.path)
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].info.title, "等待中")
        self.assertEqual(restored[0].status, STATUS_PENDING)
        self.assertEqual(restored[0].fmt, "mp3")
        self.assertEqual(restored[0].target, Path(self.temporary.name) / "a.mp3")

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_queue(self.path), [])

    def test_corrupt_queue_returns_empty(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{broken", encoding="utf-8")
        self.assertEqual(load_queue(self.path), [])

    def test_netease_job_fields_preserved(self):
        job = make_job(5, title="歌手 - 歌曲", source_kind=SOURCE_NETEASE, url="")
        job.info.source_id = "123456"
        save_queue([job], self.path)
        restored = load_queue(self.path)
        self.assertEqual(restored[0].info.source_kind, SOURCE_NETEASE)
        self.assertEqual(restored[0].info.source_id, "123456")


class EngineRetryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.download_dir = self.root / "downloads"
        self.download_dir.mkdir()
        self.events = []

        def emit(kind, *values):
            self.events.append((kind, values))

        patcher = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata")})
        patcher.start()
        self.addCleanup(patcher.stop)
        locate_patcher = patch.object(DownloadEngine, "_locate",
                                      lambda _self, name: Path(self.root / "bin" / name))
        locate_patcher.start()
        self.addCleanup(locate_patcher.stop)
        self.emit = emit
        self.job = make_job(target=self.download_dir / "歌曲.mp3")

    def results(self):
        return [values for kind, values in self.events if kind == "download_result"]

    def test_engine_logs_go_to_download_log_channel(self):
        fake_mock = MagicMock(side_effect=Exception("模拟网络错误"))
        with patch.object(download_engine.bilibili, "download_audio", fake_mock):
            DownloadEngine(self.root, self.emit, threading.Event()).run([self.job])
        logs = [values[0] for kind, values in self.events if kind == "download_log"]
        self.assertTrue(any("下载失败" in text and "模拟网络错误" in text for text in logs))
        # 下载日志不再写入通用 log 通道
        self.assertEqual([values for kind, values in self.events if kind == "log"], [])

    def test_engine_reports_downloading_status_before_attempt(self):
        def fake(job, ffmpeg_dir, temp_root, stop_event, progress):
            # 断言在下载执行前已发出“下载中”状态
            statuses = [values for kind, values in self.events if kind == "download_status"]
            self.assertEqual(statuses, [(1, "下载中")])
            job.target.write_bytes(b"data")

        with patch.object(download_engine.bilibili, "download_audio", MagicMock(side_effect=fake)):
            DownloadEngine(self.root, self.emit, threading.Event()).run([self.job])
        statuses = [values for kind, values in self.events if kind == "download_status"]
        self.assertIn((1, "下载中"), statuses)
        logs = [values[0] for kind, values in self.events if kind == "download_log"]
        self.assertTrue(any("开始下载" in text for text in logs))

    def test_transient_failure_retried_then_succeeds(self):
        outcomes = [Exception("网络断开"), None]

        def fake(job, ffmpeg_dir, temp_root, stop_event, progress):
            result = outcomes.pop(0)
            if result is not None:
                raise result
            job.target.write_bytes(b"data")

        fake_mock = MagicMock(side_effect=fake)
        with patch.object(download_engine.bilibili, "download_audio", fake_mock):
            DownloadEngine(self.root, self.emit, threading.Event()).run([self.job])
        self.assertEqual(self.job.status, STATUS_COMPLETED)
        done = [values for kind, values in self.events if kind == "download_done"][0]
        self.assertEqual(done[0], {"success": 1, "skipped": 0, "failed": 0})
        completed = [values for values in self.results() if values[1] == STATUS_COMPLETED]
        self.assertEqual(len(completed), 1)
        self.assertEqual(fake_mock.call_count, 2)

    def test_permanent_error_not_retried(self):
        fake_mock = MagicMock(side_effect=PermanentDownloadError("需要 VIP"))
        with patch.object(download_engine.bilibili, "download_audio", fake_mock):
            DownloadEngine(self.root, self.emit, threading.Event()).run([self.job])
        self.assertEqual(self.job.status, STATUS_FAILED)
        fake_mock.assert_called_once()
        done = [values for kind, values in self.events if kind == "download_done"][0]
        self.assertEqual(done[0]["failed"], 1)

    def test_retry_exhausted_marks_failed(self):
        fake_mock = MagicMock(side_effect=Exception("一直失败"))
        with patch.object(download_engine.bilibili, "download_audio", fake_mock):
            DownloadEngine(self.root, self.emit, threading.Event()).run([self.job])
        self.assertEqual(self.job.status, STATUS_FAILED)
        self.assertEqual(fake_mock.call_count, 2)
        failed = [values for values in self.results() if values[1] == STATUS_FAILED]
        self.assertEqual(len(failed), 1)


class LegacyMigrationTests(unittest.TestCase):
    def test_ncmconverter_dir_migrates_to_musiccat(self):
        from ncm_settings import app_data_dir, load_settings
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        legacy = base / "NCMConverter"
        legacy.mkdir(parents=True)
        (legacy / "settings.json").write_text(
            json.dumps({"version": 1, "format": "mp3"}), encoding="utf-8")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(base)}):
            new_dir = app_data_dir()
            values = load_settings()
        self.assertEqual(new_dir, base / "MusicCat")
        self.assertEqual(values["format"], "mp3")
        self.assertTrue((base / "MusicCat" / "settings.json").is_file())
        self.assertFalse(legacy.exists())

    def test_migration_failure_keeps_legacy(self):
        from ncm_settings import app_data_dir
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        legacy = base / "NCMConverter"
        legacy.mkdir()
        with patch.dict(os.environ, {"LOCALAPPDATA": str(base)}), \
                patch("ncm_settings.shutil.move", side_effect=OSError("locked")):
            new_dir = app_data_dir()
        self.assertEqual(new_dir, legacy)


class QueueResumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_pending_jobs_survive_restart(self):
        from music_cat_app import App
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                     "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                app.apply_preview(type("P", (), {
                    "url": "https://www.bilibili.com/video/BV1GJ411x7h7",
                    "title": "视频", "uploader": "UP",
                    "parts": [{"index": 1, "title": "视频",
                               "url": "https://www.bilibili.com/video/BV1GJ411x7h7"}],
                })())
                app.parts_tree.selection_set("1")
                app.add_download_jobs()
                self.assertEqual(len(app.download_jobs), 1)
            finally:
                if app.winfo_exists():
                    app.close()

            queue_file = self.root / "appdata" / "MusicCat" / "queue.json"
            self.assertTrue(queue_file.is_file())
            self.assertEqual(len(json.loads(queue_file.read_text(encoding="utf-8"))), 1)

            app2 = App()
            try:
                app2.withdraw()
                self.assertEqual(len(app2.download_jobs), 1)
                self.assertEqual(app2.download_jobs[0].status, STATUS_PENDING)
                self.assertEqual(len(app2.download_tree.get_children()), 1)
                self.assertIn("已恢复", app2.download_status.get())
            finally:
                if app2.winfo_exists():
                    app2.close()
                # 队列中任务仍为等待中
                self.assertEqual(len(json.loads(queue_file.read_text(encoding="utf-8"))), 1)


class DownloadLogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.download_dir = self.root / "downloads"
        self.download_dir.mkdir()
        self.events = []

        def emit(kind, *values):
            self.events.append((kind, values))

        patcher = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata")})
        patcher.start()
        self.addCleanup(patcher.stop)
        locate_patcher = patch.object(DownloadEngine, "_locate",
                                      lambda _self, name: Path(self.root / "bin" / name))
        locate_patcher.start()
        self.addCleanup(locate_patcher.stop)
        self.emit = emit
        self.job = make_job(target=self.download_dir / "歌曲.mp3")

    def test_engine_logs_go_to_download_log_channel(self):
        fake_mock = MagicMock(side_effect=Exception("模拟网络错误"))
        with patch.object(download_engine.bilibili, "download_audio", fake_mock):
            DownloadEngine(self.root, self.emit, threading.Event()).run([self.job])
        logs = [values[0] for kind, values in self.events if kind == "download_log"]
        self.assertTrue(any("下载失败" in text and "模拟网络错误" in text for text in logs))
        # 下载日志不再写入通用 log 通道
        self.assertEqual([values for kind, values in self.events if kind == "log"], [])

    def test_failure_log_never_uses_generic_channel(self):
        with patch.object(download_engine.bilibili, "download_audio",
                          MagicMock(side_effect=PermanentDownloadError("需要 VIP"))):
            DownloadEngine(self.root, self.emit, threading.Event(),
                           netease_cookie=None).run(
                [make_job(2, source_kind=SOURCE_NETEASE, url="", target=self.download_dir / "a.mp3")])
        self.assertEqual([values for kind, values in self.events if kind == "log"], [])
        logs = [values[0] for kind, values in self.events if kind == "download_log"]
        self.assertTrue(any("下载失败" in text for text in logs))


class DownloadPageLogUITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_log_panel_and_error_detail(self):
        from music_cat_app import App
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                     "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                app.append_download_log("下载完成：测试")
                content = app.download_log.get("1.0", "end").strip()
                self.assertIn("下载完成：测试", content)
                self.assertRegex(content, r"\[\d{2}:\d{2}:\d{2}\]")

                app.apply_preview(type("P", (), {
                    "url": "https://www.bilibili.com/video/BV1GJ411x7h7",
                    "title": "视频", "uploader": "UP",
                    "parts": [{"index": 1, "title": "视频",
                               "url": "https://www.bilibili.com/video/BV1GJ411x7h7"}],
                })())
                app.parts_tree.selection_set("1")
                app.add_download_jobs()
                job = app.download_jobs[0]

                app.download_tree.selection_set(str(job.job_id))
                app.on_download_tree_select()
                self.assertIn("[等待中]", app.download_detail.get("1.0", "end"))

                app.on_download_result(job.job_id, STATUS_FAILED, "模拟网络错误", "")
                self.assertIn("[失败]", app.download_detail.get("1.0", "end"))
                self.assertIn("模拟网络错误", app.download_detail.get("1.0", "end"))
                tags = app.download_tree.item(str(job.job_id), "tags")
                self.assertEqual(tuple(tags), ("failed",))
                app.download_log.see("end")
            finally:
                if app.winfo_exists():
                    app.close()

    def test_failed_row_tag_cleared_on_retry(self):
        from music_cat_app import App
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                     "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                app.apply_preview(type("P", (), {
                    "url": "https://www.bilibili.com/video/BV1GJ411x7h7",
                    "title": "视频", "uploader": "UP",
                    "parts": [{"index": 1, "title": "视频",
                               "url": "https://www.bilibili.com/video/BV1GJ411x7h7"}],
                })())
                app.parts_tree.selection_set("1")
                app.add_download_jobs()
                job = app.download_jobs[0]
                app.on_download_result(job.job_id, STATUS_FAILED, "出错", "")
                app.download_tree.selection_set(str(job.job_id))
                app.retry_failed_downloads()
                self.assertEqual(app.download_jobs[0].status, STATUS_PENDING)
                self.assertEqual(tuple(app.download_tree.item(str(job.job_id), "tags")), ())
            finally:
                if app.winfo_exists():
                    app.close()

    def test_downloading_status_updates_tree_row(self):
        from music_cat_app import App
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                     "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                app.apply_preview(type("P", (), {
                    "url": "https://www.bilibili.com/video/BV1GJ411x7h7",
                    "title": "视频", "uploader": "UP",
                    "parts": [{"index": 1, "title": "视频",
                               "url": "https://www.bilibili.com/video/BV1GJ411x7h7"}],
                })())
                app.parts_tree.selection_set("1")
                app.add_download_jobs()
                job = app.download_jobs[0]
                app.on_download_status(job.job_id, "下载中")
                self.assertEqual(app.download_tree.item(str(job.job_id), "values")[2], "下载中")
                self.assertEqual(app.download_jobs[0].status, "下载中")
            finally:
                if app.winfo_exists():
                    app.close()

    def test_start_download_busy_gives_feedback(self):
        from music_cat_app import App
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                     "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                blocker = threading.Event()
                worker = threading.Thread(target=blocker.wait, args=(2,), daemon=True)
                worker.start()
                app.worker = worker
                app.start_download()
                self.assertIn("正在运行", app.download_status.get())
                blocker.set()
                worker.join(timeout=2)
                app.worker = None
            finally:
                if app.winfo_exists():
                    app.close()


class EventLoopResilienceTests(unittest.TestCase):
    """界面事件循环与引擎线程的健壮性：任何单点异常都不能让界面永久冻结。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _make_app(self):
        from music_cat_app import App
        context = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                          "APPDATA": str(self.root / "roaming")})
        context.start()
        self.addCleanup(context.stop)
        app = App()
        self.addCleanup(self._close_app, app)
        app.withdraw()
        return app

    @staticmethod
    def _close_app(app):
        if app.winfo_exists():
            app.close()

    def _add_bilibili_job(self, app):
        app.apply_preview(type("P", (), {
            "url": "https://www.bilibili.com/video/BV1GJ411x7h7",
            "title": "视频", "uploader": "UP",
            "parts": [{"index": 1, "title": "视频",
                       "url": "https://www.bilibili.com/video/BV1GJ411x7h7"}],
        })())
        app.parts_tree.selection_set("1")
        app.add_download_jobs()
        return app.download_jobs[0]

    def test_event_loop_survives_handler_error(self):
        app = self._make_app()
        original = app.append_download_log
        calls = []

        def flaky(text):
            calls.append(text)
            if len(calls) == 1:
                raise RuntimeError("模拟界面处理异常")
            original(text)

        app.append_download_log = flaky
        app.emit("download_log", "第一条（处理会出错）")
        app.emit("download_log", "第二条")
        app.process_events()
        content = app.download_log.get("1.0", "end")
        self.assertIn("第二条", content)
        self.assertIn("界面事件处理异常", content)
        self.assertIn("模拟界面处理异常", content)

    def test_engine_crash_still_reports_done_and_recovers(self):
        app = self._make_app()
        self._add_bilibili_job(app)
        app.download_dir.set(str(self.root / "downloads"))
        with patch.object(DownloadEngine, "run", side_effect=RuntimeError("引擎崩溃模拟")):
            app.start_download()
        for _ in range(100):
            app.process_events()
            if str(app.start_download_button["state"]) == "normal":
                break
            time.sleep(0.02)
        self.assertEqual(str(app.start_download_button["state"]), "normal")
        self.assertIn("下载已停止", app.download_status.get())
        content = app.download_log.get("1.0", "end")
        self.assertIn("下载引擎异常终止", content)
        self.assertIn("引擎崩溃模拟", content)

    def test_busy_start_writes_hint_to_download_log(self):
        app = self._make_app()
        self._add_bilibili_job(app)
        blocker = threading.Event()
        holder = threading.Thread(target=blocker.wait, args=(5,))
        holder.start()
        self.addCleanup(blocker.set)
        self.addCleanup(holder.join)
        app.worker = holder
        app.start_download()
        self.assertIn("开始下载被跳过", app.download_log.get("1.0", "end"))
        self.assertIn("当前有任务正在运行", app.download_log.get("1.0", "end"))


class LicenseGateTests(unittest.TestCase):
    """首启用户协议门：拒绝不放行，同意后记住选择。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _app(self):
        import music_cat_app as mca
        context = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                          "APPDATA": str(self.root / "roaming")})
        context.start()
        self.addCleanup(context.stop)
        app = mca.App()
        self.addCleanup(self._close, app)
        app.withdraw()
        return app, mca

    @staticmethod
    def _close(app):
        if app.winfo_exists():
            app.close()

    def test_decline_blocks_and_accept_persists(self):
        import json
        app, mca = self._app()
        self.assertEqual(app.license_agreed_version, 0)

        declined = MagicMock()
        declined.dialog = MagicMock()
        declined.accepted = False
        with patch.object(mca, "LicenseDialog", return_value=declined) as factory, \
                patch.object(app, "wait_window", lambda *_: None):
            self.assertFalse(app.ensure_license_agreed())
            factory.assert_called_once()

        accepted = MagicMock()
        accepted.dialog = MagicMock()
        accepted.accepted = True
        with patch.object(mca, "LicenseDialog", return_value=accepted), \
                patch.object(app, "wait_window", lambda *_: None):
            self.assertTrue(app.ensure_license_agreed())
        self.assertEqual(app.license_agreed_version, mca.AGREEMENT_VERSION)

        settings_file = self.root / "appdata" / "MusicCat" / "settings.json"
        self.assertEqual(json.loads(settings_file.read_text(encoding="utf-8"))["license_agreed_version"], 1)

    def test_accepted_app_skips_dialog(self):
        import json
        settings_file = self.root / "appdata" / "MusicCat" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(json.dumps({"license_agreed_version": 1}), encoding="utf-8")
        app, mca = self._app()
        self.assertEqual(app.license_agreed_version, 1)
        with patch.object(mca, "LicenseDialog") as factory:
            self.assertTrue(app.ensure_license_agreed())
            factory.assert_not_called()


class LoginDialogTests(unittest.TestCase):
    """登录对话框：扫码模式与 Cookie 模式切换，二维码渲染与关闭清理。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _open_dialog(self):
        import music_cat_app as mca
        context = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                          "APPDATA": str(self.root / "roaming")})
        context.start()
        self.addCleanup(context.stop)
        app = mca.App()
        self.addCleanup(self._close, app)
        app.withdraw()
        with patch.object(mca.netease_qrlogin, "create_qr_key", return_value="test-unikey"):
            dialog = mca.LoginDialog(app)
        self.addCleanup(self._close_dialog, dialog)
        return app, mca, dialog

    @staticmethod
    def _close(app):
        if app.winfo_exists():
            app.close()

    @staticmethod
    def _close_dialog(dialog):
        try:
            if dialog.winfo_exists():
                dialog.close()
        except Exception:
            pass

    def test_mode_switch_and_defaults(self):
        app, mca, dialog = self._open_dialog()
        dialog.update()
        self.assertEqual(dialog._mode, "qr")
        self.assertTrue(dialog.qr_frame.grid_info())
        dialog.show_mode("cookie")
        self.assertEqual(dialog._mode, "cookie")
        self.assertFalse(dialog.qr_frame.grid_info())
        self.assertTrue(dialog.cookie_frame.grid_info())
        dialog.show_mode("qr")
        self.assertEqual(dialog._mode, "qr")
        self.assertFalse(dialog.cookie_frame.grid_info())

    def test_qr_key_requested_and_render_draws(self):
        app, mca, dialog = self._open_dialog()
        dialog.update()
        self.assertEqual(dialog._qr_unikey, "test-unikey")
        dialog.render_qr("https://music.163.com/login?keyuuid=test-unikey")
        self.assertTrue(dialog.qr_canvas.find_all(), "二维码应绘制出模块矩形")

    def test_copy_qr_url_puts_link_on_clipboard(self):
        app, mca, dialog = self._open_dialog()
        dialog.update()
        dialog.render_qr("https://music.163.com/login?keyuuid=test-unikey")
        dialog.copy_qr_url()
        self.assertEqual(dialog.clipboard_get(),
                         "https://music.163.com/login?keyuuid=test-unikey")
        self.assertIn("链接已复制", dialog.qr_status.get())

    def test_close_stops_polling(self):
        app, mca, dialog = self._open_dialog()
        dialog.update()
        dialog.close()
        self.assertTrue(dialog._qr_stop.is_set())
        self.assertFalse(dialog.winfo_exists())

    def test_validation_error_routes_to_active_mode(self):
        app, mca, dialog = self._open_dialog()
        dialog.update()
        dialog.show_mode("qr")
        dialog.show_validation_error("验证失败：测试")
        self.assertIn("验证失败", dialog.qr_status.get())
        dialog.show_mode("cookie")
        dialog.show_validation_error("验证失败：测试二")
        self.assertIn("测试二", dialog.message.get())


if __name__ == "__main__":
    unittest.main()
