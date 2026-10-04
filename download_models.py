"""下载任务的数据模型和状态定义，供下载引擎和界面共用。"""
from dataclasses import dataclass, field
from pathlib import Path

SOURCE_BILIBILI = "bilibili"
SOURCE_NETEASE = "netease"


class DownloadCancelled(Exception):
    """用户停止下载时在进度回调中抛出，用于中断下载过程。"""


class PermanentDownloadError(Exception):
    """不可自动重试的下载错误（权限、版权、配置缺失等）。"""

STATUS_PENDING = "等待中"
STATUS_DOWNLOADING = "下载中"
STATUS_COMPLETED = "已完成"
STATUS_SKIPPED = "已跳过"
STATUS_FAILED = "失败"
STATUS_STOPPED = "已停止"

RECORDED_STATUSES = frozenset({STATUS_COMPLETED, STATUS_SKIPPED, STATUS_FAILED, STATUS_STOPPED})


@dataclass
class TrackInfo:
    title: str
    artist: str = ""
    album: str = ""
    source_kind: str = SOURCE_BILIBILI
    source_id: str = ""
    url: str = ""


@dataclass
class DownloadJob:
    info: TrackInfo
    fmt: str
    quality: str = "0"
    job_id: int = 0
    target: Path | None = None
    status: str = STATUS_PENDING
    detail: str = ""
    attempts: int = 0


@dataclass
class DownloadResult:
    job_id: int
    status: str
    detail: str = ""
    path: str = ""


def safe_filename(name: str, max_length: int = 80) -> str:
    """生成可安全用作文件名的标题：过滤非法字符、控制字符并限制长度。"""
    cleaned = []
    for char in name:
        if char in '<>:"/\\|?*' or ord(char) < 32:
            cleaned.append(" ")
        else:
            cleaned.append(char)
    text = "".join(cleaned)
    text = " ".join(text.split())
    text = text.strip(" .")
    if len(text) > max_length:
        text = text[:max_length].strip(" .")
    return text or "download"
