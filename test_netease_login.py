import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import netease_client as nc
from credential_store import CredentialStore
from download_engine import DownloadEngine
from download_models import (SOURCE_NETEASE, STATUS_COMPLETED, STATUS_FAILED,
                             DownloadJob, TrackInfo)


def make_job(job_id=1, title="歌手 - 歌曲", target=None, fmt="mp3", quality="320"):
    info = TrackInfo(title=title, source_kind=SOURCE_NETEASE, source_id="123", url="")
    return DownloadJob(info=info, fmt=fmt, quality=quality, job_id=job_id, target=target)


@unittest.skipUnless(os.name == "nt", "DPAPI 仅在 Windows 上可测")
class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "credentials.bin"
        self.store = CredentialStore(self.path)

    def test_round_trip(self):
        self.store.save({"music_u": "secret-cookie-value"})
        self.assertEqual(self.store.load(), {"music_u": "secret-cookie-value"})

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.store.load())

    def test_clear_removes_file(self):
        self.store.save({"music_u": "x"})
        self.store.clear()
        self.assertIsNone(self.store.load())
        self.assertFalse(self.path.exists())

    def test_corrupt_file_returns_none(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("garbage content", encoding="ascii")
        self.assertIsNone(self.store.load())


class FetchSongUrlTests(unittest.TestCase):
    def test_success_forwards_cookie_header(self):
        captured = {}

        def fake_get_json(url, timeout=15.0, cookie=None):
            captured["cookie"] = cookie
            return {"code": 200, "data": [{"url": "http://m801.music.126.net/x",
                                           "type": "mp3", "level": "exhigh",
                                           "br": 320000, "size": 100,
                                           "freeTrialInfo": None, "code": 200}]}

        with patch.object(nc, "_get_json", fake_get_json):
            info = nc.fetch_song_url(123, 320000, "cookie-value")
        self.assertEqual(captured["cookie"], "MUSIC_U=cookie-value")
        self.assertEqual(info["type"], "mp3")
        self.assertEqual(info["level"], "exhigh")
        self.assertFalse(info["trial"])

    def test_vip_song_reports_login_requirement(self):
        with patch.object(nc, "_get_json",
                          lambda url, timeout=15.0, cookie=None:
                          {"code": 200, "data": [{"url": None, "code": -110, "fee": 1}]}):
            with self.assertRaises(nc.NeteaseError) as ctx:
                nc.fetch_song_url(1, 999000, None)
            self.assertIn("登录", str(ctx.exception))

    def test_missing_song_reports_404(self):
        with patch.object(nc, "_get_json",
                          lambda url, timeout=15.0, cookie=None:
                          {"code": 200, "data": [{"url": None, "code": 404}]}):
            with self.assertRaises(nc.NeteaseError) as ctx:
                nc.fetch_song_url(1, 320000, None)
            self.assertIn("不存在", str(ctx.exception))

    def test_null_url_reports_restriction(self):
        with patch.object(nc, "_get_json",
                          lambda url, timeout=15.0, cookie=None:
                          {"code": 200, "data": [{"url": None, "code": 200}]}):
            with self.assertRaises(nc.NeteaseError) as ctx:
                nc.fetch_song_url(1, 320000, None)
            self.assertIn("无法获取", str(ctx.exception))


class FakeResponse:
    def __init__(self, chunks, length):
        self._chunks = list(chunks)
        self.headers = {"Content-Length": str(length)}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self._chunks.pop(0) if self._chunks else b""


class DownloadStreamTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dest = Path(self.temporary.name) / "audio.mp3"

    def test_writes_all_chunks_and_reports_progress(self):
        chunks = [b"a" * 50, b"b" * 50]
        percents = []
        with patch.object(nc.urllib.request, "urlopen",
                          return_value=FakeResponse(chunks, 100)):
            done = nc.download_stream("http://x", self.dest, None,
                                      lambda pct: percents.append(pct))
        self.assertEqual(done, 100)
        self.assertEqual(self.dest.read_bytes(), b"a" * 50 + b"b" * 50)
        self.assertIn(100, percents)

    def test_stop_cancels_download(self):
        stop = threading.Event()
        stop.set()
        with patch.object(nc.urllib.request, "urlopen",
                          return_value=FakeResponse([b"data"], 4)):
            with self.assertRaises(nc.DownloadCancelled):
                nc.download_stream("http://x", self.dest, stop, None)


class DownloadTrackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.download_dir = self.root / "downloads"
        self.download_dir.mkdir()
        self.ffmpeg_dir = self.root / "bin"
        self.ffmpeg_dir.mkdir()
        (self.ffmpeg_dir / "ffmpeg.exe").write_bytes(b"fake")
        self.job = make_job(target=self.download_dir / "歌手 - 歌曲.mp3")

    def test_same_format_moves_atomically(self):
        info = {"url": "http://x/audio", "type": "mp3", "level": "exhigh",
                "br": 320000, "size": 10, "trial": False}
        with patch.object(nc, "fetch_song_url", return_value=info), \
                patch.object(nc, "download_stream",
                             side_effect=lambda url, dest, stop, progress: dest.write_bytes(b"data")):
            target, detail = nc.download_track(self.job, "cookie", self.download_dir / ".tmp",
                                               None, None, self.ffmpeg_dir)
        self.assertEqual(target, self.job.target)
        self.assertEqual(self.job.target.read_bytes(), b"data")
        self.assertIn("极高", detail)

    def test_trial_flag_labeled(self):
        info = {"url": "http://x", "type": "mp3", "level": "standard",
                "br": 128000, "size": 10, "trial": True}
        with patch.object(nc, "fetch_song_url", return_value=info), \
                patch.object(nc, "download_stream",
                             side_effect=lambda url, dest, stop, progress: dest.write_bytes(b"d")):
            _target, detail = nc.download_track(self.job, "cookie", self.download_dir / ".tmp",
                                                None, None, self.ffmpeg_dir)
        self.assertIn("试听片段", detail)

    def test_format_mismatch_triggers_transcode(self):
        info = {"url": "http://x", "type": "m4a", "level": "exhigh",
                "br": 320000, "size": 10, "trial": False}
        transcribed = []

        def fake_transcode(source, target, fmt, kbps, ffmpeg_path, stop_event=None):
            transcribed.append((fmt, kbps, str(ffmpeg_path)))
            target.write_bytes(b"converted")

        with patch.object(nc, "fetch_song_url", return_value=info), \
                patch.object(nc, "download_stream",
                             side_effect=lambda url, dest, stop, progress: dest.write_bytes(b"raw")), \
                patch.object(nc, "_transcode", side_effect=fake_transcode):
            target, _detail = nc.download_track(self.job, "cookie", self.download_dir / ".tmp",
                                                None, None, self.ffmpeg_dir)
        self.assertEqual(target.read_bytes(), b"converted")
        self.assertEqual(transcribed[0][0], "mp3")
        self.assertTrue(transcribed[0][2].endswith("ffmpeg.exe"))

    def test_missing_ffmpeg_reports_error(self):
        info = {"url": "http://x", "type": "m4a", "level": "exhigh",
                "br": 320000, "size": 10, "trial": False}
        with patch.object(nc, "fetch_song_url", return_value=info), \
                patch.object(nc, "download_stream",
                             side_effect=lambda url, dest, stop, progress: dest.write_bytes(b"raw")):
            with self.assertRaises(nc.NeteaseError) as ctx:
                nc.download_track(self.job, "cookie", self.download_dir / ".tmp",
                                  None, None, None)
            self.assertIn("ffmpeg", str(ctx.exception))


class EngineNeteaseTests(unittest.TestCase):
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
        self.job = make_job(target=self.download_dir / "歌手 - 歌曲.mp3")

    def test_netease_download_success_records_detail(self):
        def fake_download_track(job, cookie, temp_root, stop_event=None,
                                progress=None, ffmpeg_dir=None):
            self.assertEqual(cookie, "cookie-value")
            job.target.write_bytes(b"audio")
            return job.target, "实际音质 极高"

        with patch.object(nc, "download_track", side_effect=fake_download_track):
            engine = DownloadEngine(self.root, self.emit, threading.Event(),
                                    netease_cookie="cookie-value")
            engine.run([self.job])
        results = [values for kind, values in self.events if kind == "download_result"]
        self.assertEqual(results[0][1], STATUS_COMPLETED)
        self.assertEqual(results[0][2], "实际音质 极高")
        done = [values for kind, values in self.events if kind == "download_done"][0]
        self.assertEqual(done[0]["success"], 1)

    def test_netease_without_cookie_fails_cleanly(self):
        with patch.object(nc, "download_track",
                          side_effect=AssertionError("must not download")):
            DownloadEngine(self.root, self.emit, threading.Event(),
                           netease_cookie=None).run([self.job])
        results = [values for kind, values in self.events if kind == "download_result"]
        self.assertEqual(results[0][1], STATUS_FAILED)
        self.assertIn("尚未登录", results[0][2])


class LoginFlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_dialog_saves_credential_and_updates_status(self):
        from music_cat_app import App, LoginDialog
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                     "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                self.assertIn("未登录", app.login_status.get())
                with patch.object(nc, "fetch_user_account", return_value="测试昵称"):
                    app.open_login_dialog()
                    dialog = next(child for child in app.winfo_children()
                                  if isinstance(child, LoginDialog))
                    dialog.value_entry.insert(0, "cookie-value")
                    dialog._validate("cookie-value")
                    app.process_events()
                self.assertEqual(app.netease_cookie(), "cookie-value")
                self.assertIn("已登录", app.login_status.get())
                self.assertIn("测试昵称", app.login_status.get())
                # 退出登录删除凭据
                with patch("music_cat_app.messagebox.askyesno", return_value=True):
                    app.logout()
                self.assertIsNone(app.netease_cookie())
                self.assertIn("已退出登录", app.login_status.get())
            finally:
                if app.winfo_exists():
                    app.close()

    def test_invalid_cookie_rejected_without_save(self):
        from music_cat_app import App, LoginDialog
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                     "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                with patch.object(nc, "fetch_user_account", return_value=None):
                    app.open_login_dialog()
                    dialog = next(child for child in app.winfo_children()
                                  if isinstance(child, LoginDialog))
                    dialog.show_mode("cookie")
                    dialog._validate("bad-cookie")
                    app.process_events()
                self.assertIsNone(app.netease_cookie())
                self.assertIn("无效", dialog.message.get())
            finally:
                if app.winfo_exists():
                    app.close()

    def test_qr_trust_cookie_saved_even_when_validation_fails(self):
        """扫码登录：昵称验证遇到网络异常时凭据仍要保存，不能丢弃。"""
        from music_cat_app import App, LoginDialog
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                     "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                with patch.object(nc, "fetch_user_account",
                                  side_effect=Exception("网络请求失败：模拟抖动")):
                    app.open_login_dialog()
                    dialog = next(child for child in app.winfo_children()
                                  if isinstance(child, LoginDialog))
                    dialog._validate("qr-issued-cookie", trust_cookie=True)
                    app.process_events()
                self.assertEqual(app.netease_cookie(), "qr-issued-cookie")
                self.assertIn("已保存登录凭据", app.login_status.get())
                self.assertFalse(dialog.winfo_exists())
            finally:
                if app.winfo_exists():
                    app.close()


if __name__ == "__main__":
    unittest.main()
