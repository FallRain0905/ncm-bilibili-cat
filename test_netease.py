import json
import os
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

import netease_client as nc
import download_engine
from download_engine import DownloadEngine
from download_models import (SOURCE_NETEASE, STATUS_FAILED, STATUS_PENDING,
                             DownloadJob, TrackInfo)


class ParsePlaylistTests(unittest.TestCase):
    def test_plain_id(self):
        self.assertEqual(nc.parse_playlist_input("3778678"), "3778678")

    def test_url_with_query_id(self):
        for url in ("https://music.163.com/#/playlist?id=9269335204",
                    "https://music.163.com/playlist?id=9269335204&userid=1",
                    "music.163.com/#/playlist?id=9269335204"):
            self.assertEqual(nc.parse_playlist_input(url), "9269335204")

    def test_url_with_path_id(self):
        self.assertEqual(nc.parse_playlist_input("https://music.163.com/playlist/9269335204/user/1/"),
                         "9269335204")

    def test_invalid_inputs(self):
        self.assertIsNone(nc.parse_playlist_input(""))
        self.assertIsNone(nc.parse_playlist_input("看看这个歌单"))
        self.assertIsNone(nc.parse_playlist_input("https://music.163.com/#/song?id=1"))


class TrackStatusTests(unittest.TestCase):
    def test_blocked_when_state_negative(self):
        self.assertEqual(nc.track_status({"name": "x"}, {"st": -200}), nc.STATUS_BLOCKED)

    def test_fee_mapping(self):
        self.assertEqual(nc.track_status({"name": "x"}, {"st": 0}), nc.STATUS_FREE)
        self.assertEqual(nc.track_status({"name": "x", "fee": 1}, {}), nc.STATUS_VIP)
        self.assertEqual(nc.track_status({"name": "x", "fee": 4}, {}), nc.STATUS_ALBUM)
        self.assertEqual(nc.track_status({"name": "x", "fee": 8}, {}), nc.STATUS_LIMITED)
        self.assertEqual(nc.track_status({"name": "x", "fee": 9}, {}), nc.STATUS_UNKNOWN)

    def test_unavailable_when_name_missing(self):
        self.assertEqual(nc.track_status({"name": None}, {}), nc.STATUS_UNAVAILABLE)

    def test_parse_track_both_formats(self):
        old = nc.parse_track({"id": 1, "name": "老格式", "fee": 1,
                              "artists": [{"name": "甲"}, {"name": "乙"}],
                              "album": {"name": "专辑一"}}, {"st": 0})
        self.assertEqual((old["artist"], old["album"], old["status"]), ("甲, 乙", "专辑一", nc.STATUS_VIP))
        new = nc.parse_track({"id": 2, "name": "新格式", "fee": 0,
                              "ar": [{"name": "丙"}], "al": {"name": "专辑二"}}, {"st": 0})
        self.assertEqual((new["artist"], new["album"], new["status"]), ("丙", "专辑二", nc.STATUS_FREE))


class FakeTransport:
    def __init__(self):
        self.calls: list[str] = []

    def playlist_detail(self, result):
        def fake(url):
            self.calls.append(url)
            return {"code": 200, "result": result}
        return fake

    def song_detail(self, songs, privileges):
        calls = self.calls

        def _impl(url):
            calls.append(url)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            ids = json.loads(query["ids"][0])
            picked = [song for song in songs if song["id"] in ids]
            return {"code": 200, "songs": picked,
                    "privileges": [p for p in privileges if p["id"] in ids]}

        return MagicMock(side_effect=_impl)


class FetchPlaylistTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_full_track_ids_with_embedded_details(self):
        transport = FakeTransport()
        result = {"name": "大歌单", "creator": {"nickname": "官方"},
                  "trackCount": 3,
                  "trackIds": [{"id": 1}, {"id": 2}, {"id": 3}],
                  "tracks": [{"id": 1, "name": "歌一", "fee": 0, "ar": [{"name": "歌手一"}],
                              "al": {"name": "专辑一"}, "privilege": {"st": 0}}]}
        with patch.object(nc, "_get_json", transport.playlist_detail(result)):
            meta = nc.fetch_playlist("9269335204")
        self.assertEqual(meta["name"], "大歌单")
        self.assertEqual(meta["creator"], "官方")
        self.assertEqual(meta["track_count"], 3)
        self.assertEqual(meta["track_ids"], [1, 2, 3])
        self.assertEqual(meta["known_tracks"]["1"]["artist"], "歌手一")
        self.assertEqual(meta["known_tracks"]["1"]["status"], nc.STATUS_FREE)

    def test_fallback_to_embedded_tracks_when_no_ids(self):
        transport = FakeTransport()
        result = {"name": "小歌单", "creator": {}, "trackCount": 2,
                  "tracks": [{"id": 7, "name": "歌七", "fee": 1},
                             {"id": 8, "name": "歌八", "fee": 0}]}
        with patch.object(nc, "_get_json", transport.playlist_detail(result)):
            meta = nc.fetch_playlist("1")
        self.assertEqual(meta["track_ids"], [7, 8])

    def test_errors(self):
        transport = FakeTransport()
        with patch.object(nc, "_get_json", lambda url: {"code": 404}):
            with self.assertRaises(nc.NeteaseError) as ctx:
                nc.fetch_playlist("404")
            self.assertIn("歌单不存在", str(ctx.exception))
        with patch.object(nc, "_get_json", lambda url: {"code": 301}):
            with self.assertRaises(nc.NeteaseError) as ctx:
                nc.fetch_playlist("1")
            self.assertIn("301", str(ctx.exception))
        with patch.object(nc, "_get_json", transport.playlist_detail({"name": "空", "tracks": []})):
            with self.assertRaises(nc.NeteaseError) as ctx:
                nc.fetch_playlist("1")
            self.assertIn("歌单为空", str(ctx.exception))


class FetchSongDetailsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.songs = [{"id": 1, "name": "歌一", "fee": 0, "artists": [{"name": "甲"}], "album": {"name": "专一"}},
                      {"id": 2, "name": "歌二", "fee": 1, "artists": [{"name": "乙"}], "album": {"name": "专二"}},
                      {"id": 3, "name": None, "fee": 0, "artists": [], "album": {}}]
        self.privileges = [{"id": 1, "st": 0}, {"id": 2, "st": 0}, {"id": 3, "st": 0}]
        self.transport = FakeTransport()

    def test_chunking_and_progress(self):
        progress = []
        with patch.object(nc, "_get_json",
                          self.transport.song_detail(self.songs, self.privileges)):
            rows = nc.fetch_song_details([1, 2, 3], chunk_size=2, chunk_delay=0,
                                         progress=lambda loaded, total: progress.append((loaded, total)))
        self.assertEqual(len(self.transport.calls), 2)
        self.assertEqual(progress, [(2, 3), (3, 3)])
        self.assertEqual([row["id"] for row in rows], ["1", "2", "3"])
        self.assertEqual(rows[0]["artist"], "甲")
        self.assertEqual(rows[2]["status"], nc.STATUS_UNAVAILABLE)

    def test_known_tracks_reused_without_request(self):
        known = {"1": {"id": "1", "name": "歌一", "artist": "甲", "album": "专一", "status": nc.STATUS_FREE}}
        with patch.object(nc, "_get_json",
                          self.transport.song_detail(self.songs, self.privileges)) as fake:
            rows = nc.fetch_song_details([1, 2], known=known, chunk_size=10, chunk_delay=0)
        requested = json.loads(urllib.parse.parse_qs(urllib.parse.urlparse(fake.call_args[0][0]).query)["ids"][0])
        self.assertEqual(requested, [2])
        self.assertEqual(rows[0]["name"], "歌一")

    def test_missing_song_becomes_unavailable(self):
        with patch.object(nc, "_get_json", self.transport.song_detail(self.songs[:2], self.privileges[:2])):
            rows = nc.fetch_song_details([99], chunk_size=10, chunk_delay=0)
        self.assertEqual(rows[0]["status"], nc.STATUS_UNAVAILABLE)


class FetchSongUrlTests(unittest.TestCase):
    def test_http_url_upgraded_to_https(self):
        payload = {"code": 200, "data": [{"code": 200, "url": "http://m704.music.126.net/a.mp3?vuutv=x",
                                          "type": "mp3", "level": "exhigh", "br": 320001,
                                          "size": 10, "freeTrialInfo": None}]}
        with patch.object(nc, "_get_json", lambda url, **kwargs: payload):
            info = nc.fetch_song_url(1, 320000, "cookie-value")
        self.assertTrue(info["url"].startswith("https://"))

    def test_https_url_unchanged(self):
        payload = {"code": 200, "data": [{"code": 200, "url": "https://m10.music.126.net/b.mp3?vuutv=y",
                                          "type": "mp3", "level": "exhigh", "br": 320000,
                                          "size": 10, "freeTrialInfo": None}]}
        with patch.object(nc, "_get_json", lambda url, **kwargs: payload):
            info = nc.fetch_song_url(1, 320000, None)
        self.assertEqual(info["url"], "https://m10.music.126.net/b.mp3?vuutv=y")

    def test_auth_secret_url_gets_trailing_question_mark(self):
        payload = {"code": 200, "data": [{"code": 200,
                                          "url": "http://m704.music.126.net/a.mp3?vuutv=x&authSecret=y",
                                          "type": "mp3", "level": "exhigh", "br": 320001,
                                          "size": 10, "freeTrialInfo": None}]}
        with patch.object(nc, "_get_json", lambda url, **kwargs: payload):
            info = nc.fetch_song_url(1, 320000, "cookie-value")
        self.assertTrue(info["url"].startswith("https://"))
        self.assertTrue(info["url"].endswith("authSecret=y?"))

    def test_cookie_passed_only_in_header(self):
        seen = {}

        def fake(url, timeout=15.0, cookie=None):
            seen["cookie"] = cookie
            return {"code": 200, "data": [{"code": 200, "url": "https://m10.music.126.net/c.mp3",
                                           "type": "mp3", "level": "standard", "br": 128000,
                                           "size": 10, "freeTrialInfo": None}]}

        with patch.object(nc, "_get_json", fake):
            nc.fetch_song_url(1, 128000, "cookie-value")
        self.assertEqual(seen["cookie"], "MUSIC_U=cookie-value")

    def test_restricted_codes_raise_permanent(self):
        for payload in ({"code": 200, "data": [{"code": -110}]},
                        {"code": 200, "data": [{"code": 404}]},
                        {"code": 200, "data": [{"code": 200, "url": None}]}):
            with patch.object(nc, "_get_json", lambda url, p=payload, **kwargs: p):
                with self.assertRaises(nc.NeteaseRestrictedError):
                    nc.fetch_song_url(1, 320000, None)


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

    def test_netease_job_fails_with_login_hint(self):
        job = DownloadJob(info=TrackInfo(title="歌手 - 歌曲", source_kind=SOURCE_NETEASE,
                                         source_id="123", url=""),
                          fmt="mp3", job_id=1, target=self.download_dir / "歌手 - 歌曲.mp3")
        fake = MagicMock(side_effect=AssertionError("must not download netease"))
        with patch.object(download_engine.bilibili, "download_audio", fake):
            DownloadEngine(self.root, self.emit, threading.Event()).run([job])
        results = [values for kind, values in self.events if kind == "download_result"]
        self.assertEqual(results[0][1], STATUS_FAILED)
        self.assertIn("登录", results[0][2])
        fake.assert_not_called()


class PlaylistPageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_app_builds_playlist_page_and_joins_queue(self):
        from music_cat_app import App
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"),
                                     "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                self.assertIn("歌单", [app.notebook.tab(tab, "text")
                                      for tab in app.notebook.tabs()])
                rows = [{"id": "1", "name": "歌一", "artist": "甲", "album": "专一", "status": "免费"},
                        {"id": "2", "name": "歌二", "artist": "乙", "album": "专二", "status": "VIP"}]
                app.apply_playlist({"id": "9", "name": "测试歌单", "creator": "官方",
                                    "track_count": 2}, rows)
                self.assertEqual(app.playlist_tree.get_children(), ("1", "2"))
                app.playlist_tree.selection_set("1", "2")
                app.add_playlist_to_queue()
                self.assertEqual(len(app.download_jobs), 2)
                self.assertEqual(app.download_jobs[0].info.source_kind, SOURCE_NETEASE)
                self.assertEqual(app.download_jobs[0].status, STATUS_PENDING)
                self.assertEqual(app.notebook.select(), str(app.download_page))
                # 重复加入同一首歌不会产生新任务
                app.playlist_tree.selection_set("1")
                app.add_playlist_to_queue()
                self.assertEqual(len(app.download_jobs), 2)
            finally:
                if app.winfo_exists():
                    app.close()


if __name__ == "__main__":
    unittest.main()
