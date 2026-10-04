"""Bilibili 视频解析与音频下载，基于 yt-dlp 的 Python API。

模块级只依赖标准库；yt-dlp 在函数内部延迟导入，保证未安装时本地 NCM 转换不受影响。
"""
import re
import shutil
import time
import urllib.request
from pathlib import Path

from download_models import DownloadCancelled

BILIBILI_VIDEO_URL = "https://www.bilibili.com/video/{}"

_BV_RE = re.compile(r"(?<![A-Za-z0-9])BV[0-9A-Za-z]{10}(?![0-9A-Za-z])")
_AV_RE = re.compile(r"(?<![0-9A-Za-z])av(\d{1,15})(?!\d)", re.IGNORECASE)
_P_RE = re.compile(r"[?&]p=(\d{1,4})")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 兼容旧引用：停止异常统一定义在 download_models。
DownloadCancelled = DownloadCancelled


def resolve_short_url(url: str, timeout: float = 10.0) -> str:
    request = urllib.request.Request(url if "://" in url else f"https://{url}",
                                     headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.geturl()


def parse_bilibili_input(text: str, _resolve_shorts: bool = True) -> str | None:
    """从 BV 号、av 号、视频链接或 b23.tv 短链接提取标准视频地址。"""
    if not text or not text.strip():
        return None
    value = text.strip()
    match = _BV_RE.search(value)
    if match:
        part = _P_RE.search(value)
        url = BILIBILI_VIDEO_URL.format(match.group(0))
        return f"{url}?p={part.group(1)}" if part else url
    match = _AV_RE.search(value)
    if match:
        return BILIBILI_VIDEO_URL.format(f"av{match.group(1)}")
    if "b23.tv" in value.lower() and _resolve_shorts:
        try:
            return parse_bilibili_input(resolve_short_url(value), _resolve_shorts=False)
        except OSError:
            return None
    return None


def extract_video_id(url: str) -> str:
    match = _BV_RE.search(url or "")
    if match:
        return match.group(0)
    match = _AV_RE.search(url or "")
    return f"av{match.group(1)}" if match else ""


class VideoPreview:
    def __init__(self, url: str, title: str, uploader: str, parts: list[dict]):
        self.url = url
        self.title = title
        self.uploader = uploader
        self.parts = parts


def preview_video(url: str) -> VideoPreview:
    """获取视频标题、作者和分 P 列表；不做任何下载。"""
    from yt_dlp import YoutubeDL

    options = {"quiet": True, "no_warnings": True, "skip_download": True,
               "extract_flat": "in_playlist"}
    with YoutubeDL(options) as ydl:
        data = ydl.extract_info(url, download=False)
    if not data:
        raise RuntimeError("未能获取视频信息，请检查链接或稍后重试。")
    if data.get("_type") == "playlist":
        entries = [entry for entry in (data.get("entries") or []) if entry]
        if not entries:
            raise RuntimeError("该视频没有可下载的分 P。")
        parts = []
        for index, entry in enumerate(entries, 1):
            parts.append({
                "index": index,
                "title": str(entry.get("title") or f"P{index}"),
                "url": str(entry.get("url") or entry.get("webpage_url") or url),
            })
        return VideoPreview(str(data.get("webpage_url") or url),
                            str(data.get("title") or "未知标题"),
                            str(data.get("uploader") or data.get("channel") or ""),
                            parts)
    return VideoPreview(str(data.get("webpage_url") or url),
                        str(data.get("title") or "未知标题"),
                        str(data.get("uploader") or data.get("channel") or ""),
                        [{"index": 1, "title": str(data.get("title") or "P1"),
                          "url": str(data.get("webpage_url") or url)}])


def download_audio(job, ffmpeg_dir: Path | None, temp_root: Path,
                   stop_event=None, progress=None) -> Path:
    """下载单个任务的音频并转换为 job.fmt，完成后原子移动到 job.target。"""
    from yt_dlp import YoutubeDL

    temp_dir = temp_root / f"job-{job.job_id or time.time_ns()}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    state = {"percent": -1, "time": 0.0}

    def hook(progress_data):
        if stop_event is not None and stop_event.is_set():
            raise DownloadCancelled()
        if not isinstance(progress_data, dict) or progress_data.get("status") != "downloading":
            return
        total = progress_data.get("total_bytes") or progress_data.get("total_bytes_estimate") or 0
        done = progress_data.get("downloaded_bytes") or 0
        if not total:
            return
        percent = int(done * 100 / total)
        now = time.monotonic()
        if progress and percent != state["percent"] and now - state["time"] >= 0.4:
            state.update(percent=percent, time=now)
            try:
                progress(percent, job.info.title)
            except Exception:
                pass

    options = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": str(temp_dir / "%(title).80B [%(id)s].%(ext)s"),
        "ffmpeg_location": str(ffmpeg_dir) if ffmpeg_dir is not None else None,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": job.fmt,
            "preferredquality": str(job.quality),
        }],
        "progress_hooks": [hook],
        "retries": 2,
        "socket_timeout": 20,
    }
    options = {key: value for key, value in options.items() if value is not None}
    try:
        with YoutubeDL(options) as ydl:
            ydl.download([job.info.url])
        produced = [item for item in temp_dir.iterdir()
                    if item.is_file() and item.suffix.lower() == f".{job.fmt}"]
        if not produced:
            produced = [item for item in temp_dir.iterdir() if item.is_file()]
        if not produced:
            raise RuntimeError("下载结束但没有生成音频文件。")
        source_file = max(produced, key=lambda item: item.stat().st_size)
        job.target.parent.mkdir(parents=True, exist_ok=True)
        # temp_root 位于目标目录下，同一卷内 os.replace 为原子操作。
        source_file.replace(job.target)
        return job.target
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            temp_root.rmdir()
        except OSError:
            pass
