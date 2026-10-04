import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import bilibili_downloader as bilibili
import download_engine
import download_history
from download_engine import DownloadEngine
from download_models import (STATUS_COMPLETED, STATUS_FAILED, STATUS_PENDING,
                             STATUS_SKIPPED, STATUS_STOPPED, DownloadJob,
                             TrackInfo, safe_filename)


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, kind, *values):
        self.events.append((kind, values))

    def kinds(self, name):
        return [values for kind, values in self.events if kind == name]


def make_job(job_id, title="Test Video", fmt="mp3", target=None, url="https://www.bilibili.com/video/BV1GJ411x7h7"):
    info = TrackInfo(title=title, source_kind="bilibili",
                     source_id="BV1GJ411x7h7", url=url)
    return DownloadJob(info=info, fmt=fmt, quality="0", job_id=job_id, target=target)


class FakeYoutubeDL:
    options = None
    behaviour = "single"

    def __init__(self, options):
        FakeYoutubeDL.options = options

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        assert download is False
        if FakeYoutubeDL.behaviour == "playlist":
            return {"_type": "playlist", "title": "多P视频", "uploader": "UP主",
                    "webpage_url": url,
                    "entries": [{"title": "P1 开场", "url": f"{url}&p=1"},
                                {"title": "P2 结尾", "url": f"{url}&p=2"}]}
        if FakeYoutubeDL.behaviour == "empty":
            return {"_type": "playlist", "title": "空视频", "uploader": "UP主",
                    "webpage_url": url, "entries": []}
        return {"title": "单个视频", "uploader": "UP主",
                "webpage_url": "https://www.bilibili.com/video/BV1GJ411x7h7"}

    def download(self, urls):
        out = Path(FakeYoutubeDL.options["outtmpl"])
        for hook in FakeYoutubeDL.options.get("progress_hooks", []):
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            hook({"status": "finished"})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.with_suffix(".mp3").write_bytes(b"audio-bytes")


class ParseTests(unittest.TestCase):
    def test_bv_number(self):
        self.assertEqual(bilibili.parse_bilibili_input("BV1GJ411x7h7"),
                         "https://www.bilibili.com/video/BV1GJ411x7h7")

    def test_bv_url_with_part(self):
        url = "https://www.bilibili.com/video/BV1GJ411x7h7?spm_id_from=333.5&p=2"
        self.assertEqual(bilibili.parse_bilibili_input(url),
                         "https://www.bilibili.com/video/BV1GJ411x7h7?p=2")

    def test_av_number(self):
        self.assertEqual(bilibili.parse_bilibili_input("av170001"),
                         "https://www.bilibili.com/video/av170001")
        self.assertEqual(bilibili.parse_bilibili_input("https://www.bilibili.com/video/av170001?p=3"),
                         "https://www.bilibili.com/video/av170001")

    def test_invalid_input(self):
        self.assertIsNone(bilibili.parse_bilibili_input(""))
        self.assertIsNone(bilibili.parse_bilibili_input("随便一段文字"))
        self.assertIsNone(bilibili.parse_bilibili_input("BV123"))

    def test_short_link_resolved_without_network(self):
        with patch.object(bilibili, "resolve_short_url",
                          return_value="https://www.bilibili.com/video/BV1GJ411x7h7"):
            self.assertEqual(bilibili.parse_bilibili_input("https://b23.tv/abc123"),
                             "https://www.bilibili.com/video/BV1GJ411x7h7")

    def test_extract_video_id(self):
        self.assertEqual(bilibili.extract_video_id("https://www.bilibili.com/video/BV1GJ411x7h7?p=1"),
                         "BV1GJ411x7h7")
        self.assertEqual(bilibili.extract_video_id("https://www.bilibili.com/video/av170001"),
                         "av170001")


class SafeFilenameTests(unittest.TestCase):
    def test_illegal_characters_removed(self):
        self.assertEqual(safe_filename('a<b>c:"d/e\\f|g?h*i'), "a b c d e f g h i")

    def test_control_characters_and_spacing(self):
        self.assertEqual(safe_filename("  歌名\n\t第二行  "), "歌名 第二行")

    def test_length_limited(self):
        self.assertEqual(len(safe_filename("长" * 200)), 80)

    def test_empty_falls_back(self):
        self.assertEqual(safe_filename("???"), "download")


class PreviewTests(unittest.TestCase):
    def test_single_video(self):
        FakeYoutubeDL.behaviour = "single"
        with patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
            preview = bilibili.preview_video("https://www.bilibili.com/video/BV1GJ411x7h7")
        self.assertEqual(preview.title, "单个视频")
        self.assertEqual(preview.uploader, "UP主")
        self.assertEqual(len(preview.parts), 1)
        self.assertEqual(preview.parts[0]["index"], 1)

    def test_multi_part_playlist(self):
        FakeYoutubeDL.behaviour = "playlist"
        url = "https://www.bilibili.com/video/BV1GJ411x7h7"
        with patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
            preview = bilibili.preview_video(url)
        self.assertEqual(preview.title, "多P视频")
        self.assertEqual([part["index"] for part in preview.parts], [1, 2])
        self.assertEqual(preview.parts[1]["url"], f"{url}&p=2")

    def test_empty_playlist_raises(self):
        FakeYoutubeDL.behaviour = "empty"
        with patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
            with self.assertRaises(RuntimeError):
                bilibili.preview_video("https://www.bilibili.com/video/BV1GJ411x7h7")


class DownloadAudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.download_dir = self.root / "downloads"
        self.download_dir.mkdir()

    def test_download_moves_file_to_target(self):
        FakeYoutubeDL.behaviour = "single"
        job = make_job(1, target=self.download_dir / "测试视频.mp3")
        captured = []
        with patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
            result = bilibili.download_audio(job, self.root / "bin", self.download_dir / ".tmp",
                                             None, lambda pct, name: captured.append(pct))
        self.assertEqual(result, job.target)
        self.assertEqual(job.target.read_bytes(), b"audio-bytes")
        self.assertIn(50, captured)
        self.assertFalse((self.download_dir / ".tmp").exists())

    def test_cancel_keeps_target_absent_and_cleans_temp(self):
        stop_event = threading.Event()
        stop_event.set()
        job = make_job(2, target=self.download_dir / "取消.mp3")
        with patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
            with self.assertRaises(bilibili.DownloadCancelled):
                bilibili.download_audio(job, self.root / "bin", self.download_dir / ".tmp",
                                        stop_event, None)
        self.assertFalse(job.target.exists())
        self.assertFalse((self.download_dir / ".tmp").exists())


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.download_dir = self.root / "downloads"
        self.download_dir.mkdir()
        self.recorder = Recorder()
        self.stop_event = threading.Event()
        patcher = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata")})
        patcher.start()
        self.addCleanup(patcher.stop)
        locate_patcher = patch.object(DownloadEngine, "_locate",
                                      lambda _self, name: Path(self.root / "bin" / name))
        locate_patcher.start()
        self.addCleanup(locate_patcher.stop)

    def engine(self):
        return DownloadEngine(self.root, self.recorder, self.stop_event)

    def fake_download(self, fail_job_ids=()):
        def fake(job, ffmpeg_dir, temp_root, stop_event, progress):
            if job.job_id in fail_job_ids:
                raise RuntimeError("模拟网络错误")
            job.target.parent.mkdir(parents=True, exist_ok=True)
            job.target.write_bytes(b"data")
        return MagicMock(side_effect=fake)

    def test_success_sequence(self):
        jobs = [make_job(1, title="第一首", target=self.download_dir / "第一首.mp3"),
                make_job(2, title="第二首", target=self.download_dir / "第二首.mp3")]
        with patch.object(download_engine.bilibili, "download_audio", self.fake_download()):
            self.engine().run(jobs)
        results = {values[0]: values[1] for values in self.recorder.kinds("download_result")}
        self.assertEqual(results[1], STATUS_COMPLETED)
        self.assertEqual(results[2], STATUS_COMPLETED)
        done = self.recorder.kinds("download_done")[0]
        self.assertEqual(done[0], {"success": 2, "skipped": 0, "failed": 0})
        self.assertFalse(done[2])
        self.assertTrue(jobs[0].target.is_file())

    def test_skip_existing_output(self):
        existing = self.download_dir / "已存在.mp3"
        existing.write_bytes(b"old")
        jobs = [make_job(1, title="已存在", target=existing)]
        with patch.object(download_engine.bilibili, "download_audio", self.fake_download()) as fake:
            self.engine().run(jobs)
        fake.assert_not_called()
        self.assertEqual(self.recorder.kinds("download_result")[0][1], STATUS_SKIPPED)

    def test_failure_continues_next_job(self):
        jobs = [make_job(1, title="坏任务", target=self.download_dir / "坏任务.mp3"),
                make_job(2, title="好任务", target=self.download_dir / "好任务.mp3")]
        with patch.object(download_engine.bilibili, "download_audio", self.fake_download(fail_job_ids={1})):
            self.engine().run(jobs)
        results = {values[0]: values[1] for values in self.recorder.kinds("download_result")}
        self.assertEqual(results[1], STATUS_FAILED)
        self.assertEqual(results[2], STATUS_COMPLETED)
        done = self.recorder.kinds("download_done")[0]
        self.assertEqual(done[0]["failed"], 1)
        self.assertTrue(done[1])

    def test_stop_marks_pending_jobs(self):
        jobs = [make_job(1, title="任务一", target=self.download_dir / "任务一.mp3"),
                make_job(2, title="任务二", target=self.download_dir / "任务二.mp3")]
        self.stop_event.set()
        with patch.object(download_engine.bilibili, "download_audio", self.fake_download()):
            self.engine().run(jobs)
        results = {values[0]: values[1] for values in self.recorder.kinds("download_result")}
        self.assertEqual(results[1], STATUS_STOPPED)
        self.assertEqual(results[2], STATUS_STOPPED)
        self.assertTrue(self.recorder.kinds("download_done")[0][2])
        self.assertFalse(jobs[0].target.exists())

    def test_history_written_for_final_statuses(self):
        jobs = [make_job(1, title="记录任务", target=self.download_dir / "记录任务.mp3")]
        with patch.object(download_engine.bilibili, "download_audio", self.fake_download()):
            self.engine().run(jobs)
        entries = download_history.load_completed()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "记录任务")
        self.assertEqual(entries[0]["status"], STATUS_COMPLETED)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "history.sqlite3"

    def test_load_without_file(self):
        self.assertEqual(download_history.load_completed(self.path), [])

    def test_record_and_load_round_trip(self):
        download_history.record({"source_kind": "bilibili", "source_id": "BV1GJ411x7h7",
                                 "title": "歌曲", "artist": "歌手",
                                 "url": "https://www.bilibili.com/video/BV1GJ411x7h7",
                                 "path": str(Path(self.temporary.name) / "歌曲.mp3"),
                                 "fmt": "mp3", "status": STATUS_COMPLETED, "detail": ""}, self.path)
        entries = download_history.load_completed(self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "歌曲")
        self.assertEqual(entries[0]["artist"], "歌手")

    def test_failed_records_not_loaded(self):
        download_history.record({"title": "失败任务", "status": STATUS_FAILED,
                                 "path": "ignored", "fmt": "mp3"}, self.path)
        self.assertEqual(download_history.load_completed(self.path), [])


class DownloadPageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_app_builds_download_page_and_defaults(self):
        from music_cat_app import App
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                     "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                self.assertIn("下载", [app.notebook.tab(tab, "text")
                                      for tab in app.notebook.tabs()])
                self.assertEqual(app.download_format.get(), "mp3")
                self.assertEqual(app.download_dir.get(), str((app_root_default())))
                self.assertEqual(app.download_jobs, [])
                app.bv_entry.insert(0, "BV1GJ411x7h7")
                app.apply_preview(bilibili.VideoPreview(
                    "https://www.bilibili.com/video/BV1GJ411x7h7", "测试视频", "UP主",
                    [{"index": 1, "title": "测试视频", "url": "https://www.bilibili.com/video/BV1GJ411x7h7"}]))
                app.parts_tree.selection_set("1")
                app.add_download_jobs()
                self.assertEqual(len(app.download_jobs), 1)
                self.assertEqual(app.download_jobs[0].status, STATUS_PENDING)
                self.assertEqual(app.download_tree.item("1", "values")[2], STATUS_PENDING)
            finally:
                if app.winfo_exists():
                    app.close()


def app_root_default():
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "downloads"
    return Path(music_cat_app_file()).resolve().parent / "downloads"


def music_cat_app_file():
    import music_cat_app
    return music_cat_app.__file__


if __name__ == "__main__":
    unittest.main()
