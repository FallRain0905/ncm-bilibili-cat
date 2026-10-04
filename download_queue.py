"""未完成下载队列的持久化：应用关闭后保留等待中的任务，下次启动恢复。"""
import json
import os
import tempfile
from pathlib import Path

from download_models import STATUS_PENDING, DownloadJob, TrackInfo
from ncm_settings import app_data_dir


def queue_path() -> Path:
    return app_data_dir() / "queue.json"


def save_queue(jobs: list, path: Path | None = None):
    """只持久化“等待中”的任务；已完成/失败/已跳过的任务不入队。"""
    path = path if path is not None else queue_path()
    data = []
    for job in jobs:
        if job.status != STATUS_PENDING:
            continue
        data.append({
            "info": {
                "title": job.info.title,
                "artist": job.info.artist,
                "album": job.info.album,
                "source_kind": job.info.source_kind,
                "source_id": job.info.source_id,
                "url": job.info.url,
            },
            "fmt": job.fmt,
            "quality": job.quality,
            "target": str(job.target) if job.target else None,
            "attempts": job.attempts,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="queue-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_queue(path: Path | None = None) -> list:
    path = path if path is not None else queue_path()
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    jobs = []
    for item in data:
        try:
            info = TrackInfo(
                title=str(item["info"].get("title", "")),
                artist=str(item["info"].get("artist", "")),
                album=str(item["info"].get("album", "")),
                source_kind=str(item["info"].get("source_kind", "")),
                source_id=str(item["info"].get("source_id", "")),
                url=str(item["info"].get("url", "")),
            )
            target = item.get("target")
            job = DownloadJob(
                info=info,
                fmt=str(item.get("fmt", "mp3")),
                quality=str(item.get("quality", "0")),
                target=Path(target) if target else None,
                attempts=int(item.get("attempts", 0)),
            )
        except (KeyError, TypeError, ValueError, OSError):
            continue
        jobs.append(job)
    return jobs
