import json
import os
import shutil
import sqlite3
import string
import tempfile
from pathlib import Path

APP_DATA_DIRNAME = "MusicCat"
LEGACY_APP_DATA_DIRNAME = "NCMConverter"


def app_data_dir() -> Path:
    """应用数据目录；首次调用时把旧的 NCMConverter 目录整体迁移到 MusicCat。"""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    new_dir = base / APP_DATA_DIRNAME
    legacy = base / LEGACY_APP_DATA_DIRNAME
    if not new_dir.is_dir() and legacy.is_dir():
        try:
            shutil.move(str(legacy), str(new_dir))
        except OSError:
            return legacy
    return new_dir


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def clean_settings(values: dict) -> dict:
    result = {}
    for key in ("source_dir", "output_dir", "download_dir"):
        value = values.get(key)
        if isinstance(value, str) and value.strip() and "\x00" not in value:
            result[key] = value.strip()
    for key in ("download_format", "last_playlist_url"):
        value = values.get(key)
        if isinstance(value, str) and "\x00" not in value:
            result[key] = value.strip()
    if values.get("theme") in ("dark", "light"):
        result["theme"] = values["theme"]
    if values.get("format") in ("flac", "mp3"):
        result["format"] = values["format"]
    if isinstance(values.get("recursive"), bool):
        result["recursive"] = values["recursive"]
    if isinstance(values.get("license_agreed_version"), int) and values["license_agreed_version"] >= 0:
        result["license_agreed_version"] = values["license_agreed_version"]
    return result


def load_settings(path: Path | None = None) -> dict:
    path = path if path is not None else settings_path()
    try:
        with path.open("r", encoding="utf-8") as stream:
            values = json.load(stream)
        return clean_settings(values) if isinstance(values, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(values: dict, path: Path | None = None):
    path = path if path is not None else settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="settings-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"version": 1, **clean_settings(values)}, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def existing_directory(value: str | Path | None) -> Path | None:
    if not value:
        return None
    try:
        path = Path(os.path.expandvars(str(value))).expanduser()
        return path.resolve() if path.is_dir() else None
    except (OSError, ValueError, RuntimeError):
        return None


def cloudmusic_library_directories(config_roots: list[Path]) -> list[Path]:
    candidates = []
    for root in config_roots:
        database = root / "Library" / "library.dat"
        if not database.is_file():
            continue
        try:
            # Read-only SQLite queries preserve the live database and its journal.
            connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)
            try:
                rows = connection.execute(
                    "SELECT dir, parentdir, COUNT(*) FROM track "
                    "GROUP BY dir, parentdir ORDER BY COUNT(*) DESC LIMIT 1000"
                ).fetchall()
            finally:
                connection.close()
            for directory, parent, _count in rows:
                for value in (directory, parent):
                    if isinstance(value, str) and value:
                        candidates.append(Path(value))
        except (OSError, ValueError, sqlite3.Error):
            continue
    return candidates


def common_download_directories() -> list[Path]:
    home = Path.home()
    music = home / "Music"
    drives = []
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                music = Path(os.path.expandvars(winreg.QueryValueEx(key, "My Music")[0]))
        except (OSError, ValueError):
            pass
        import ctypes
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:
                drives.append(Path(root) / "CloudMusic")
    return [music / "CloudMusic", home / "CloudMusic", home / "Downloads" / "CloudMusic", *drives, music, home / "Downloads"]


def looks_like_download_directory(path: Path) -> bool:
    try:
        if path.name.lower() in {"cloudmusic", "vipsongsdownload"}:
            return True
        if (path / "VipSongsDownload").is_dir():
            return True
        return any(child.is_file() and child.suffix.lower() == ".ncm" for child in path.iterdir())
    except OSError:
        return False


def detect_source_directory(config_roots: list[Path] | None = None,
                            common_candidates: list[Path] | None = None) -> Path | None:
    if config_roots is None:
        config_roots = [Path(os.environ[key]) / "Netease" / "CloudMusic"
                        for key in ("LOCALAPPDATA", "APPDATA") if os.environ.get(key)]
    for candidate in cloudmusic_library_directories(config_roots):
        directory = existing_directory(candidate)
        if directory is not None:
            return directory
    if common_candidates is None:
        common_candidates = common_download_directories()
    for candidate in common_candidates:
        directory = existing_directory(candidate)
        if directory is not None and looks_like_download_directory(directory):
            return directory
    return None


def startup_settings(default_output: Path, path: Path | None = None,
                     config_roots: list[Path] | None = None,
                     common_candidates: list[Path] | None = None,
                     default_download: Path | None = None) -> dict:
    saved = load_settings(path)
    source = existing_directory(saved.get("source_dir"))
    if source is None:
        source = detect_source_directory(config_roots, common_candidates)
    fmt = saved.get("format", "flac")
    if default_download is None:
        default_download = default_output.parent / "downloads"
    return {
        "source_dir": str(source) if source is not None else "",
        "output_dir": saved.get("output_dir", str(default_output / fmt)),
        "format": fmt,
        "recursive": saved.get("recursive", True),
        "download_dir": saved.get("download_dir", str(default_download)),
        "download_format": saved.get("download_format", "mp3"),
        "last_playlist_url": saved.get("last_playlist_url", ""),
        "theme": saved.get("theme", "dark"),
        "license_agreed_version": saved.get("license_agreed_version", 0),
    }
