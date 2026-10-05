"""本地 NCM 转换引擎与工具定位。

从 music_cat_app.py 抽出（Tk 版与 Qt 版共用）；事件仍走
emit(kind, *values) 回调，由各界面层自行适配。
"""
import os
import subprocess
import sys
import threading
from pathlib import Path


def app_root() -> Path:
    """应用根目录：冻结运行取 EXE 所在目录，源码运行取本模块所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_tool(name: str, bundled: Path) -> Path | None:
    if bundled.is_file():
        return bundled
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(entry) / name
        if candidate.is_file():
            return candidate
    return None


def expected_target(source: Path, source_root: Path | None, output_root: Path, fmt: str) -> Path:
    target_dir = output_root
    if source_root:
        target_dir = output_root / source.relative_to(source_root).parent
    return target_dir / f"{source.stem}.{fmt}"


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


class ConverterEngine:
    def __init__(self, root: Path, emit, stop_event: threading.Event):
        self.root = root
        self.emit = emit
        self.stop_event = stop_event
        self.process: subprocess.Popen | None = None

    def run_process(self, args: list[str]) -> int:
        self.emit("command", " ".join(self.quote(arg) for arg in args))
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        assert self.process.stdout is not None
        for line in self.process.stdout:
            if line.strip():
                self.emit("log", line.rstrip())
            if self.stop_event.is_set():
                self.process.terminate()
        code = self.process.wait()
        self.process = None
        return code

    @staticmethod
    def quote(value: str) -> str:
        return '"' + value.replace('"', '\\"') + '"'

    def stop(self):
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def convert(self, files: list[Path], source_root: Path | None, output_root: Path,
                fmt: str, remove_source: bool):
        ncmdump = find_tool("ncmdump.exe", self.root / "bin" / "ncmdump.exe") or find_tool(
            "ncmdump.exe", self.root / "_internal" / "bin" / "ncmdump.exe") or find_tool(
            "ncmdump.exe", self.root / "ncmdump" / "tools" / "ncmdump-1.5.1" / "ncmdump.exe")
        ffmpeg = find_tool("ffmpeg.exe", self.root / "bin" / "ffmpeg.exe") or find_tool(
            "ffmpeg.exe", self.root / "_internal" / "bin" / "ffmpeg.exe") or find_tool(
            "ffmpeg.exe", self.root / "tools" / "ffmpeg-9.0.2-essentials_build" / "bin" / "ffmpeg.exe")
        if not ncmdump:
            raise RuntimeError("找不到 ncmdump.exe，请检查应用目录的 bin 文件夹。")
        if fmt == "mp3" and not ffmpeg:
            raise RuntimeError("找不到 ffmpeg.exe，请检查应用目录的 bin 文件夹。")

        output_root.mkdir(parents=True, exist_ok=True)
        counts = {"success": 0, "skipped": 0, "failed": 0}
        failures: list[str] = []
        for index, source in enumerate(files, 1):
            if self.stop_event.is_set():
                self.emit("log", "任务已停止。")
                break
            self.emit("progress", index, len(files), source.name)
            target = expected_target(source, source_root, output_root, fmt)
            target_dir = target.parent
            target_dir.mkdir(parents=True, exist_ok=True)
            decoded = target_dir / f"{source.stem}.flac"
            if target.is_file():
                counts["skipped"] += 1
                self.emit("result", source, target, "已转换", "输出已存在")
                self.emit("log", f"跳过：{source.name}（输出已存在）")
                continue
            try:
                code = self.run_process([str(ncmdump), str(source), "-o", str(target_dir)])
                if code != 0 or not decoded.is_file():
                    raise RuntimeError(f"ncmdump 失败，退出码 {code}")
                if fmt == "mp3":
                    code = self.run_process([
                        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-n", "-i", str(decoded),
                        "-map_metadata", "0", "-codec:a", "libmp3lame", "-q:a", "2", str(target),
                    ])
                    if code != 0 or not target.is_file():
                        raise RuntimeError(f"FFmpeg 失败，退出码 {code}")
                    decoded.unlink(missing_ok=True)
                if remove_source:
                    source.unlink()
                counts["success"] += 1
                self.emit("result", source, target, "已转换", "")
                self.emit("log", f"完成：{source.name} -> {target.name}")
            except Exception as exc:
                counts["failed"] += 1
                failures.append(str(source))
                self.emit("result", source, target, "失败", str(exc))
                self.emit("log", f"失败：{source.name}：{exc}")
        self.emit("done", counts, failures, self.stop_event.is_set())
