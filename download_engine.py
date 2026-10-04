"""串行下载引擎：与 ConverterEngine 并列，复用同一事件队列和停止机制。

失败自动重试一次；权限/版权类永久错误与用户停止不重试。
失败只在最终定案时计数并写入历史，重试成功的任务只计成功。
"""
import os
import threading
from pathlib import Path

import bilibili_downloader as bilibili
import download_history
import netease_client
from download_models import (SOURCE_BILIBILI, SOURCE_NETEASE, STATUS_COMPLETED,
                             STATUS_DOWNLOADING, STATUS_FAILED, STATUS_SKIPPED,
                             STATUS_STOPPED, PermanentDownloadError)

MAX_AUTO_RETRIES = 1


class DownloadEngine:
    def __init__(self, root: Path, emit, stop_event: threading.Event,
                 netease_cookie: str | None = None):
        self.root = root
        self.emit = emit
        self.stop_event = stop_event
        self.netease_cookie = netease_cookie

    def stop(self):
        self.stop_event.set()

    def _locate(self, name: str) -> Path | None:
        candidates = [
            self.root / "bin" / name,
            self.root / "_internal" / "bin" / name,
            self.root / "tools" / "ffmpeg-9.0.2-essentials_build" / "bin" / name,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            candidate = Path(entry) / name
            if candidate.is_file():
                return candidate
        return None

    def _record(self, job, status: str, detail: str):
        try:
            download_history.record({
                "source_kind": job.info.source_kind,
                "source_id": job.info.source_id,
                "title": job.info.title,
                "artist": job.info.artist,
                "url": job.info.url,
                "path": str(job.target) if status in (STATUS_COMPLETED, STATUS_SKIPPED) else "",
                "fmt": job.fmt,
                "status": status,
                "detail": detail,
            })
        except Exception as exc:
            self.emit("download_log", f"写入下载记录失败：{exc}")

    def run(self, jobs: list):
        counts = {"success": 0, "skipped": 0, "failed": 0}
        failures: list[str] = []
        stopped = False
        ffmpeg = self._locate("ffmpeg.exe")
        ffmpeg_dir = ffmpeg.parent if ffmpeg else None
        if ffmpeg_dir is None:
            self.emit("download_log", "警告：找不到 ffmpeg.exe，音频转换类下载将失败。")

        queue_now = list(jobs)
        while queue_now:
            total = len(queue_now)
            retry_round: list = []
            for index, job in enumerate(queue_now, 1):
                if self.stop_event.is_set():
                    stopped = True
                    job.status = STATUS_STOPPED
                    self.emit("download_result", job.job_id, STATUS_STOPPED, "", "")
                    continue
                self.emit("download_progress", index, total, job.info.title)
                self.emit("download_status", job.job_id, STATUS_DOWNLOADING)
                self.emit("download_log", f"开始下载（第 {job.attempts + 1} 次尝试）：{job.info.title}")
                error = self._download_one(job, counts, ffmpeg_dir)
                if error is None or self.stop_event.is_set():
                    continue
                if not isinstance(error, PermanentDownloadError) and job.attempts < MAX_AUTO_RETRIES:
                    job.attempts += 1
                    retry_round.append(job)
                    self.emit("download_log", f"下载出错，将自动重试：{job.info.title}：{error}")
                else:
                    job.status = STATUS_FAILED
                    counts["failed"] += 1
                    failures.append(f"{job.info.title}：{error}")
                    self._record(job, STATUS_FAILED, str(error))
                    self.emit("download_result", job.job_id, STATUS_FAILED, str(error), "")
                    self.emit("download_log", f"下载失败：{job.info.title}：{error}")
            queue_now = retry_round
            if queue_now and not self.stop_event.is_set():
                self.emit("download_log", f"开始自动重试 {len(queue_now)} 个失败任务。")
        self.emit("download_done", counts, failures, stopped)

    def _download_one(self, job, counts: dict, ffmpeg_dir) -> Exception | None:
        """执行单个任务；返回捕获到的异常（成功/跳过返回 None），不负责失败定案。"""
        try:
            if job.target.is_file() and job.target.stat().st_size > 0:
                job.status = STATUS_SKIPPED
                counts["skipped"] += 1
                self._record(job, STATUS_SKIPPED, "输出已存在")
                self.emit("download_result", job.job_id, STATUS_SKIPPED, "输出已存在", str(job.target))
                self.emit("download_log", f"跳过：{job.info.title}（输出已存在）")
                return None
            progress_callback = lambda percent, name: self.emit("download_bytes", percent, name)
            detail = ""
            if job.info.source_kind == SOURCE_NETEASE:
                if not self.netease_cookie:
                    raise PermanentDownloadError("尚未登录网易云：请先在“歌单”页登录。")
                _, detail = netease_client.download_track(
                    job, self.netease_cookie, job.target.parent / ".downloads-tmp",
                    self.stop_event, progress=progress_callback, ffmpeg_dir=ffmpeg_dir)
            elif job.info.source_kind == SOURCE_BILIBILI:
                if ffmpeg_dir is None:
                    raise RuntimeError("找不到 ffmpeg.exe，请检查应用目录的 bin 文件夹。")
                bilibili.download_audio(
                    job, ffmpeg_dir, job.target.parent / ".downloads-tmp",
                    self.stop_event, progress=progress_callback)
            else:
                raise PermanentDownloadError(f"不支持的任务来源：{job.info.source_kind}")
            job.status = STATUS_COMPLETED
            counts["success"] += 1
            self._record(job, STATUS_COMPLETED, detail)
            self.emit("download_result", job.job_id, STATUS_COMPLETED, detail, str(job.target))
            suffix = f"（{detail}）" if detail else ""
            self.emit("download_log", f"下载完成：{job.info.title} -> {job.target.name}{suffix}")
            return None
        except Exception as exc:
            if self.stop_event.is_set():
                job.status = STATUS_STOPPED
                self._record(job, STATUS_STOPPED, "")
                self.emit("download_result", job.job_id, STATUS_STOPPED, "", "")
                self.emit("download_log", f"已停止：{job.info.title}")
            return exc
