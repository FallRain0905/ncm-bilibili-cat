"""网易云公开歌单导入：解析歌单 ID、获取完整歌曲列表和详情。

只访问公开接口、只读取公开数据，不使用、不存储任何 Cookie 或登录凭据。
HTTP 访问集中在 _get_json，便于测试替换。
"""
import json
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from download_models import DownloadCancelled, PermanentDownloadError

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
PLAYLIST_DETAIL_URL = "https://music.163.com/api/v3/playlist/detail?id={}"
SONG_DETAIL_URL = "https://music.163.com/api/song/detail?{}"
SONG_URL_URL = "https://music.163.com/api/song/enhance/player/url?{}"
USER_ACCOUNT_URL = "https://music.163.com/api/nuser/account/get"

# 音质码（与界面“音质”下拉一致）→ 网易云 br 参数
NETEASE_BR = {"0": 320000, "320": 320000, "192": 192000, "128": 128000}
LOSSLESS_BR = 999000
LEVEL_LABELS = {"standard": "标准", "higher": "较高", "exhigh": "极高",
                "lossless": "无损", "hires": "Hi-Res", "jyeffect": "高清环绕声",
                "sky": "沉浸环绕声", "jymaster": "超清母带"}

_ID_RE = re.compile(r"id=(\d{1,20})")
_PATH_RE = re.compile(r"playlist/(\d{1,20})")
_DIGITS_RE = re.compile(r"^\d{1,20}$")

STATUS_FREE = "免费"
STATUS_VIP = "VIP"
STATUS_ALBUM = "购买专辑"
STATUS_LIMITED = "限免"
STATUS_BLOCKED = "无版权"
STATUS_UNAVAILABLE = "不可用"
STATUS_UNKNOWN = "未知"


class NeteaseError(RuntimeError):
    """网易云接口错误，message 面向用户显示。"""


class NeteaseRestrictedError(NeteaseError, PermanentDownloadError):
    """不可自动重试的限制类错误（登录/VIP/版权/不存在等）。"""


def _get_json(url: str, timeout: float = 15.0, cookie: str | None = None) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://music.163.com/",
    }
    if cookie:
        # Cookie 仅通过请求头传递，绝不写入日志、设置或错误信息。
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except OSError as exc:
        raise NeteaseError(f"网络请求失败：{exc}") from exc
    try:
        payload = json.loads(data.decode("utf-8"))
    except ValueError as exc:
        raise NeteaseError("接口返回了无法解析的数据。") from exc
    if not isinstance(payload, dict):
        raise NeteaseError("接口返回了意外的数据格式。")
    return payload


def parse_playlist_input(text: str) -> str | None:
    """从纯数字 ID、歌单链接（含 /#/playlist?id= 形式）提取歌单 ID。"""
    if not text or not text.strip():
        return None
    value = text.strip()
    if _DIGITS_RE.match(value):
        return value
    if "playlist" not in value.lower():
        return None
    match = _ID_RE.search(value) or _PATH_RE.search(value)
    if match:
        return match.group(1)
    return None


def track_status(song: dict, privilege: dict) -> str:
    if song.get("name") is None:
        return STATUS_UNAVAILABLE
    state = int(privilege.get("st") or 0)
    if state < 0:
        return STATUS_BLOCKED
    fee = int(song.get("fee") or 0)
    if fee == 0:
        return STATUS_FREE
    if fee == 1:
        return STATUS_VIP
    if fee == 4:
        return STATUS_ALBUM
    if fee == 8:
        return STATUS_LIMITED
    return STATUS_UNKNOWN


def parse_track(song: dict, privilege: dict) -> dict:
    artists_field = song.get("artists") or song.get("ar") or []
    artists = ", ".join(str(a.get("name") or "") for a in artists_field if a.get("name"))
    album_field = song.get("album") or song.get("al") or {}
    album = str(album_field.get("name") or "")
    return {
        "id": str(song.get("id") or ""),
        "name": str(song.get("name") or ""),
        "artist": artists,
        "album": album,
        "status": track_status(song, privilege),
    }


def fetch_playlist(playlist_id: str) -> dict:
    """获取歌单信息与完整歌曲 ID 列表；嵌入的详情用于减少后续请求。"""
    payload = _get_json(PLAYLIST_DETAIL_URL.format(int(playlist_id)))
    code = payload.get("code")
    if code == 404:
        raise NeteaseError("歌单不存在，请检查歌单 ID 或链接。")
    if code != 200:
        raise NeteaseError(f"获取歌单失败（错误码 {code}）。")
    result = payload.get("result") or payload.get("playlist") or {}
    name = str(result.get("name") or "未知歌单")
    creator = str((result.get("creator") or {}).get("nickname") or "")
    track_count = int(result.get("trackCount") or 0)
    track_ids = [int(item.get("id")) for item in (result.get("trackIds") or [])
                 if isinstance(item, dict) and item.get("id") is not None]
    if not track_ids:
        track_ids = [int(song.get("id")) for song in (result.get("tracks") or [])
                     if isinstance(song, dict) and song.get("id") is not None]
    if not track_ids:
        raise NeteaseError("歌单为空，或该歌单需要登录后才能查看。")
    known = {track["id"]: track for track in
             (parse_track(song, song.get("privilege") or {})
              for song in (result.get("tracks") or []) if isinstance(song, dict))}
    return {"id": str(playlist_id), "name": name, "creator": creator,
            "track_count": track_count or len(track_ids), "track_ids": track_ids,
            "known_tracks": known}


def fetch_song_details(track_ids: list[int], known: dict | None = None,
                       chunk_size: int = 100, chunk_delay: float = 0.15,
                       progress=None) -> list[dict]:
    """分批获取歌曲详情；已知的嵌入详情会被补齐状态后复用。"""
    known = dict(known or {})
    results: list[dict] = []
    total = len(track_ids)
    for start in range(0, total, chunk_size):
        chunk = track_ids[start:start + chunk_size]
        missing = [item for item in chunk if str(item) not in known]
        if not missing:
            results.extend(known[str(item)] for item in chunk)
        else:
            query = urllib.parse.urlencode({
                "id": missing[0],
                "ids": json.dumps(missing, separators=(",", ":")),
            })
            payload = _get_json(SONG_DETAIL_URL.format(query))
            if payload.get("code") != 200:
                raise NeteaseError(f"获取歌曲详情失败（错误码 {payload.get('code')}）。")
            privileges = {int(item.get("id")): item for item in (payload.get("privileges") or [])
                          if isinstance(item, dict) and item.get("id") is not None}
            parsed = {track["id"]: track for track in
                      (parse_track(song, privileges.get(int(song.get("id")), {}))
                       for song in (payload.get("songs") or []) if isinstance(song, dict))}
            for item in chunk:
                results.append(parsed.get(str(item)) or known.get(str(item)) or
                               {"id": str(item), "name": "", "artist": "", "album": "",
                                "status": STATUS_UNAVAILABLE})
        if progress:
            progress(min(start + chunk_size, total), total)
        if start + chunk_size < total and chunk_delay > 0:
            time.sleep(chunk_delay)
    return results


def fetch_user_account(cookie: str) -> str | None:
    """校验 MUSIC_U 是否有效；有效返回昵称，无效返回 None。"""
    if not cookie:
        return None
    payload = _get_json(USER_ACCOUNT_URL, cookie=f"MUSIC_U={cookie}")
    account = payload.get("account")
    if not account:
        return None
    return str((payload.get("profile") or {}).get("nickname") or "")


def fetch_song_url(song_id: int, br: int, cookie: str | None) -> dict:
    """获取歌曲音频地址；无权限/受限时抛出带原因的 NeteaseError。"""
    query = urllib.parse.urlencode({"ids": f"[{int(song_id)}]", "br": int(br)})
    payload = _get_json(SONG_URL_URL.format(query), cookie=f"MUSIC_U={cookie}" if cookie else None)
    if payload.get("code") != 200:
        raise NeteaseError(f"获取音频地址失败（错误码 {payload.get('code')}）。")
    items = payload.get("data") or []
    item = items[0] if isinstance(items, list) and items else None
    if not isinstance(item, dict):
        raise NeteaseRestrictedError("未获取到歌曲音频信息。")
    code = item.get("code")
    if code == -110:
        raise NeteaseRestrictedError("这首歌需要登录后才能获取音频（可能需要 VIP）。")
    if code == 404:
        raise NeteaseRestrictedError("歌曲不存在或已下架。")
    url = item.get("url")
    if not url:
        raise NeteaseRestrictedError("无法获取音频地址：歌曲无版权或当前账号无权限。")
    # 限免歌曲的 CDN 地址带 authSecret 防盗链签名：签名串以问号结尾，而接口
    # 返回的地址把它截掉了，直接请求会 403；补回结尾问号即可通过校验。
    # 同时统一升级为 https，避免明文传输。
    audio_url = str(url)
    if audio_url.startswith("http://"):
        audio_url = "https://" + audio_url[len("http://"):]
    if "authSecret=" in audio_url and not audio_url.endswith("?"):
        audio_url += "?"
    return {
        "url": audio_url,
        "type": str(item.get("type") or "mp3").lower(),
        "level": str(item.get("level") or ""),
        "br": int(item.get("br") or 0),
        "size": int(item.get("size") or 0),
        "trial": item.get("freeTrialInfo") is not None,
    }


def download_stream(url: str, dest, stop_event=None, progress=None):
    """把音频流下载到 dest；按 2% 粒度回调 progress(percent)。"""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Referer": "https://music.163.com/",
    })
    try:
        response = urllib.request.urlopen(request, timeout=30)
    except OSError as exc:
        raise NeteaseError(f"音频下载失败：网络错误（{exc}）") from exc
    with response:
        total = int(response.headers.get("Content-Length") or 0)
        last_percent = -2
        done = 0
        try:
            with open(dest, "wb") as stream:
                while True:
                    if stop_event is not None and stop_event.is_set():
                        raise DownloadCancelled()
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    stream.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        percent = int(done * 100 / total)
                        if percent >= last_percent + 2 or percent == 100:
                            last_percent = percent
                            progress(percent)
        except OSError as exc:
            raise NeteaseError(f"音频写入失败：{exc}") from exc
    if total and done < total:
        raise NeteaseError("音频下载不完整，请重试。")
    return done


def _transcode(source, target, fmt: str, kbps: int, ffmpeg_path, stop_event=None):
    codec_args = {
        "mp3": ["-codec:a", "libmp3lame", "-q:a", "2"],
        "m4a": ["-codec:a", "aac", "-b:a", f"{kbps}k"],
        "flac": ["-codec:a", "flac"],
    }.get(fmt)
    if codec_args is None:
        raise NeteaseError(f"不支持的目标格式：{fmt}")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(source), *codec_args, str(target)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
    while process.poll() is None:
        if stop_event is not None and stop_event.is_set():
            process.terminate()
            raise DownloadCancelled()
        time.sleep(0.1)
    code = process.returncode
    if code != 0 or not target.is_file():
        raise NeteaseError(f"FFmpeg 转码失败（退出码 {code}）。")


def download_track(job, cookie: str | None, temp_root, stop_event=None,
                   progress=None, ffmpeg_dir=None):
    """下载一首网易云歌曲并转为 job.fmt；返回 (目标路径, 音质说明)。"""
    song_id = int(job.info.source_id)
    if job.fmt == "flac":
        br = LOSSLESS_BR
    else:
        br = NETEASE_BR.get(str(job.quality), 320000)
    info = fetch_song_url(song_id, br, cookie)
    temp_dir = temp_root / f"job-{job.job_id or time.time_ns()}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw = temp_dir / f"audio.{info['type']}"
        percent_title = job.info.title

        def report_percent(percent):
            if progress:
                progress(percent, percent_title)

        download_stream(info["url"], raw, stop_event, report_percent)
        level = LEVEL_LABELS.get(info["level"], info["level"] or "未知")
        detail = f"试听片段（实际音质 {level}）" if info["trial"] else f"实际音质 {level}"
        target = job.target
        target.parent.mkdir(parents=True, exist_ok=True)
        if info["type"] == job.fmt:
            # temp_root 与目标同卷，replace 为原子操作。
            raw.replace(target)
            return target, detail
        if ffmpeg_dir is None:
            raise NeteaseError("找不到 ffmpeg.exe，无法转换音频格式。")
        ffmpeg_path = Path(ffmpeg_dir) / "ffmpeg.exe"
        if not ffmpeg_path.is_file():
            raise NeteaseError("找不到 ffmpeg.exe，无法转换音频格式。")
        kbps = int(job.quality) if str(job.quality).isdigit() and int(job.quality) > 0 else 320
        _transcode(raw, target, job.fmt, kbps, ffmpeg_path, stop_event)
        raw.unlink(missing_ok=True)
        return target, detail
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            temp_root.rmdir()
        except OSError:
            pass
