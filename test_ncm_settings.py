import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ncm_settings import (
    cloudmusic_library_directories,
    detect_source_directory,
    load_settings,
    save_settings,
    startup_settings,
)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = self.root / "profile" / "settings.json"
        self.source = self.root / "music (test)"
        self.source.mkdir()
        self.config = self.root / "CloudMusicConfig"
        self.output = self.root / "output"

    def make_library(self, directory):
        library = self.config / "Library"
        library.mkdir(parents=True)
        connection = sqlite3.connect(library / "library.dat")
        try:
            with connection:
                connection.execute("CREATE TABLE track (dir TEXT, parentdir TEXT, file TEXT)")
                connection.execute("INSERT INTO track VALUES (?, ?, ?)",
                                   (str(directory), str(directory / "VipSongsDownload"), "unused.ncm"))
        finally:
            connection.close()

    def startup(self):
        return startup_settings(self.output, self.settings, [self.config], [])

    def test_round_trip(self):
        values = {"source_dir": str(self.source), "output_dir": str(self.root / "custom output"),
                  "format": "mp3", "recursive": False,
                  "download_dir": str(self.root / "dl"), "download_format": "m4a",
                  "last_playlist_url": "https://music.163.com/#/playlist?id=123456",
                  "theme": "light", "license_agreed_version": 1}
        save_settings(values, self.settings)
        self.assertEqual(load_settings(self.settings), values)
        self.assertEqual(self.startup(), values)
        self.assertEqual(list(self.settings.parent.glob("*.tmp")), [])

    def test_missing_config_defaults(self):
        self.assertEqual(self.startup(), {"source_dir": "", "output_dir": str(self.output / "flac"),
                                         "format": "flac", "recursive": True,
                                         "download_dir": str(self.root / "downloads"),
                                         "download_format": "mp3",
                                         "last_playlist_url": "",
                                         "theme": "dark",
                                         "license_agreed_version": 0})

    def test_corrupt_json_and_invalid_types(self):
        self.settings.parent.mkdir()
        for content in ("{broken", "[]", json.dumps({"source_dir": [], "output_dir": 3,
                                                   "format": "wav", "recursive": "false"})):
            self.settings.write_text(content, encoding="utf-8")
            self.assertEqual(load_settings(self.settings), {})
        self.settings.write_bytes(b"\xff\xfe")
        self.assertEqual(load_settings(self.settings), {})

    def test_saved_source_has_priority(self):
        save_settings({"source_dir": str(self.source)}, self.settings)
        with patch("ncm_settings.detect_source_directory", side_effect=AssertionError("must not detect")):
            self.assertEqual(self.startup()["source_dir"], str(self.source.resolve()))

    def test_stale_source_detected_and_other_values_retained(self):
        self.make_library(self.source)
        save_settings({"source_dir": str(self.root / "gone"), "output_dir": str(self.root / "not-created"),
                       "format": "mp3", "recursive": False}, self.settings)
        values = self.startup()
        self.assertEqual(values["source_dir"], str(self.source.resolve()))
        self.assertEqual(values["output_dir"], str(self.root / "not-created"))
        self.assertEqual(values["format"], "mp3")
        self.assertIs(values["recursive"], False)

    def test_database_detection_is_read_only(self):
        self.make_library(self.source)
        database = self.config / "Library" / "library.dat"
        before = database.read_bytes()
        self.assertEqual(detect_source_directory([self.config], []), self.source.resolve())
        self.assertEqual(database.read_bytes(), before)

    def test_corrupt_database_falls_back(self):
        library = self.config / "Library"
        library.mkdir(parents=True)
        (library / "library.dat").write_bytes(b"not sqlite")
        candidate = self.root / "CloudMusic"
        candidate.mkdir()
        self.assertEqual(detect_source_directory([self.config], [candidate]), candidate.resolve())

    def test_parent_directory_fallback(self):
        missing = self.root / "missing-root"
        self.make_library(missing)
        (missing / "VipSongsDownload").mkdir(parents=True)
        self.assertEqual(detect_source_directory([self.config], []), missing.resolve())
        missing.rename(self.root / "moved")
        self.assertIsNone(detect_source_directory([self.config], []))

    def test_unrelated_music_directory_is_not_selected(self):
        self.assertIsNone(detect_source_directory([], [self.source]))
        (self.source / "song.NCM").touch()
        self.assertEqual(detect_source_directory([], [self.source]), self.source.resolve())

    def test_only_requested_settings_are_saved(self):
        save_settings({"source_dir": str(self.source), "remove_source": True,
                       "token": "not-a-credential", "format": "mp3"}, self.settings)
        self.assertEqual(load_settings(self.settings), {"source_dir": str(self.source), "format": "mp3"})
        raw = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertNotIn("remove_source", raw)
        self.assertNotIn("token", raw)

    def test_license_agreed_version_round_trip(self):
        save_settings({"license_agreed_version": 1}, self.settings)
        self.assertEqual(self.startup()["license_agreed_version"], 1)
        save_settings({"license_agreed_version": -1}, self.settings)
        self.assertEqual(self.startup()["license_agreed_version"], 0)
        save_settings({"license_agreed_version": "1"}, self.settings)
        self.assertEqual(self.startup()["license_agreed_version"], 0)

    def test_failed_write_keeps_previous_file(self):
        save_settings({"format": "flac"}, self.settings)
        with patch("ncm_settings.os.replace", side_effect=PermissionError("test")):
            with self.assertRaises(PermissionError):
                save_settings({"format": "mp3"}, self.settings)
        self.assertEqual(load_settings(self.settings), {"format": "flac"})
        self.assertEqual(list(self.settings.parent.glob("*.tmp")), [])

    def test_unicode_paths(self):
        source = self.root / "音乐 (下载)"
        source.mkdir()
        save_settings({"source_dir": str(source), "output_dir": str(self.root / "转码 输出")}, self.settings)
        self.assertEqual(self.startup()["source_dir"], str(source.resolve()))
        self.assertEqual(self.startup()["output_dir"], str(self.root / "转码 输出"))

    def test_app_debounced_autosave(self):
        from music_cat_app import App
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"), "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                app.source_dir.set(str(self.source))
                app.output_dir.set(str(self.root / "autosaved output"))
                app.format_var.set("mp3")
                app.recursive.set(False)
                app.after(800, app.quit)
                app.mainloop()
                saved = load_settings()
                self.assertEqual(saved["source_dir"], str(self.source))
                self.assertEqual(saved["output_dir"], str(self.root / "autosaved output"))
                self.assertEqual(saved["format"], "mp3")
                self.assertIs(saved["recursive"], False)
                self.assertIsNone(app.worker)
                self.assertIsNone(app.settings_save_id)
            finally:
                app.close()

    def test_app_restart_restores_values_without_conversion(self):
        from music_cat_app import App
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata"), "APPDATA": str(self.root / "roaming")}):
            app = App()
            try:
                app.withdraw()
                app.source_dir.set(str(self.source))
                app.output_dir.set(str(self.root / "chosen output"))
                app.format_var.set("mp3")
                app.recursive.set(False)
                app.remove_source.set(True)
                app.close()
                app = App()
                app.withdraw()
                self.assertEqual(app.source_dir.get(), str(self.source.resolve()))
                self.assertEqual(app.output_dir.get(), str(self.root / "chosen output"))
                self.assertEqual(app.format_var.get(), "mp3")
                self.assertIs(app.recursive.get(), False)
                self.assertIs(app.remove_source.get(), False)
                self.assertIsNone(app.worker)
                app.persist_settings()
                app.update_idletasks()
            finally:
                if app.winfo_exists():
                    app.close()


if __name__ == "__main__":
    unittest.main()
