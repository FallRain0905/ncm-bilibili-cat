import itertools
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    import ttkbootstrap as ttk
    BOOTSTRAP_AVAILABLE = True
except ImportError:
    from tkinter import ttk
    BOOTSTRAP_AVAILABLE = False

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_FILES = None

    class _TkFallback:
        Tk = tk.Tk

    TkinterDnD = _TkFallback
    DND_AVAILABLE = False

import bilibili_downloader as bilibili
import netease_client
from credential_store import CredentialStore, CredentialUnavailable
from download_engine import DownloadEngine
from download_history import load_completed
from download_queue import load_queue, save_queue
from download_models import (SOURCE_BILIBILI, SOURCE_NETEASE, STATUS_COMPLETED,
                             STATUS_FAILED, STATUS_PENDING, STATUS_SKIPPED,
                             STATUS_STOPPED, DownloadJob, TrackInfo, safe_filename)
from ncm_settings import save_settings, startup_settings

APP_TITLE = "Music Cat"
APP_VERSION = "1.1.1"
GITHUB_URL = "https://github.com/FallRain0905/ncm-bilibili-cat"

AGREEMENT_VERSION = 1
AGREEMENT_TEXT = f"""Music Cat（ncm-bilibili-cat）用户协议与使用条款

一、开源声明
本项目为开源软件，源码托管于：
{GITHUB_URL}
欢迎学习、研究、改进与反馈问题。

二、禁止商业用途
本软件仅供个人学习与非商业用途使用。严禁倒卖、收费分发、捆绑销售，
或以任何形式将本软件用于商业牟利。再分发时必须保留本协议与原作者署名，
修改后的版本同样受本协议约束。

三、内容与合规
1. 本软件仅允许下载：你本人登录自己的网易云账号后有权收听/下载的歌曲，
   以及你自己有权访问的 Bilibili 视频音频。
2. 请勿利用本软件获取未授权内容或侵犯他人版权；由此产生的一切责任由使用者自行承担。
3. 本软件不破解、不绕过任何平台的会员、付费或其他访问控制，也不提供第三方替代音源。

四、免责声明
1. 本软件与网易云音乐、Bilibili 官方无关，仅是一个第三方个人学习项目。
2. 通过本软件下载内容的版权归原权利人所有，仅供个人学习、研究欣赏之用，
   请尊重版权、支持正版。
3. 使用本软件产生的一切风险与后果由使用者自行承担；作者不对任何直接或间接
   损失负责，也不对任何第三方内容承担责任。
4. 第三方组件的许可信息见随附的《第三方组件声明》（THIRD_PARTY_NOTICES）。

点击“同意并继续”即表示你已阅读、理解并接受以上全部条款。
"""

QUALITY_CHOICES = {"最佳": "0", "320kbps": "320", "192kbps": "192", "128kbps": "128"}

BOOTSTRAP_THEMES = {"dark": "darkly", "light": "flatly"}


def _bootstyle(name: str) -> dict:
    return {"bootstyle": name} if BOOTSTRAP_AVAILABLE else {}


if DND_AVAILABLE and BOOTSTRAP_AVAILABLE:
    class _AppBase(ttk.Window, TkinterDnD.DnDWrapper):
        pass

    _NEED_DND_REQUIRE = True
elif BOOTSTRAP_AVAILABLE:
    _AppBase = ttk.Window
    _NEED_DND_REQUIRE = False
elif DND_AVAILABLE:
    _AppBase = TkinterDnD.Tk
    _NEED_DND_REQUIRE = False
else:
    _AppBase = tk.Tk
    _NEED_DND_REQUIRE = False


def _enable_windows_hi_dpi():
    if os.name != "nt" or BOOTSTRAP_AVAILABLE:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (OSError, AttributeError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (OSError, AttributeError):
            pass


def app_root() -> Path:
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


class LoginDialog(tk.Toplevel):
    """导入用户自己的 MUSIC_U 并验证；凭据只用 DPAPI 加密保存到本机。"""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        if BOOTSTRAP_AVAILABLE:
            self.configure(bg=app.style.colors.bg)
        self.title("登录网易云")
        self.resizable(False, False)
        self.columnconfigure(0, weight=1)
        padding = {"padx": 16, "pady": 8}
        ttk.Label(self, text=(
            "网易云的登录接口需要完整的浏览器环境，应用改用导入 MUSIC_U 的方式登录：\n\n"
            "方法一（推荐）：使用浏览器插件 Cookie Control Center（或任意 Cookie 管理插件，"
            "如 Cookie-Editor）——\n"
            "  1. 在浏览器登录 music.163.com；\n"
            "  2. 点击插件图标，在 Cookie 列表中搜索 MUSIC_U；\n"
            "  3. 复制它的 Value，粘贴到下方。\n\n"
            "方法二：按 F12 打开开发者工具 → “应用/存储” → Cookie → https://music.163.com，"
            "找到名为 MUSIC_U 的条目并复制它的值（条目较多，建议用开发者工具的筛选框）。\n\n"
            "凭据仅保存在本机，使用 Windows DPAPI 加密，不会写入设置文件或日志。"
        ), wraplength=500, justify="left").grid(row=0, column=0, sticky="w", **padding)
        self.value_entry = ttk.Entry(self, show="*", width=64)
        self.value_entry.grid(row=1, column=0, sticky="ew", **padding)
        self.message = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.message, wraplength=480,
                  justify="left").grid(row=2, column=0, sticky="w", **padding)
        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, sticky="e", **padding)
        ttk.Button(buttons, text="保存并登录", command=self.apply).pack(side="left")
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="left", padx=(8, 0))
        self.value_entry.focus_set()
        self.transient(app)
        self.grab_set()

    def apply(self):
        value = self.value_entry.get().strip()
        if not value:
            self.message.set("请先粘贴 MUSIC_U 的值。")
            return
        self.message.set("正在验证登录状态…")
        for widget in self.winfo_children():
            if isinstance(widget, ttk.Button):
                widget.configure(state="disabled")
        threading.Thread(target=self._validate, args=(value,), daemon=True).start()

    def _validate(self, value: str):
        try:
            nickname = netease_client.fetch_user_account(value)
            error = ""
        except Exception as exc:
            nickname, error = None, str(exc)
        self.app.emit("login_dialog_result", self, value, nickname, error)


class LicenseDialog:
    """首启用户协议对话框：模态展示，accepted 表示用户同意条款。"""

    def __init__(self, app):
        self.accepted = False
        self.dialog = tk.Toplevel(app)
        self.dialog.title("用户协议与使用条款")
        self.dialog.geometry("660x540")
        self.dialog.minsize(560, 440)
        self.dialog.transient(app)
        self.dialog.protocol("WM_DELETE_WINDOW", self.decline)
        body = ttk.Frame(self.dialog, padding=14)
        body.pack(fill="both", expand=True)
        text = tk.Text(body, wrap="word", relief="flat", padx=10, pady=8,
                       height=16)
        text.pack(fill="both", expand=True)
        text.insert("1.0", AGREEMENT_TEXT)
        text.configure(state="disabled")
        link = tk.Label(body, text=f"项目主页：{GITHUB_URL}", fg="#4f8cff", cursor="hand2")
        link.pack(pady=(6, 0))
        link.bind("<Button-1>", lambda _event: webbrowser.open(GITHUB_URL))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="不同意（退出）", command=self.decline,
                   **_bootstyle("danger-outline")).pack(side="right", padx=(4, 0))
        ttk.Button(buttons, text="同意并继续", command=self.accept,
                   **_bootstyle("success")).pack(side="right")

    def accept(self):
        self.accepted = True
        self.dialog.destroy()

    def decline(self):
        self.accepted = False
        self.dialog.destroy()


class App(_AppBase):
    def __init__(self):
        restored = startup_settings(app_root() / "output", default_download=app_root() / "downloads")
        if not BOOTSTRAP_AVAILABLE:
            _enable_windows_hi_dpi()
        if BOOTSTRAP_AVAILABLE:
            super().__init__(themename=BOOTSTRAP_THEMES.get(restored["theme"], "darkly"))
        else:
            super().__init__()
        if _NEED_DND_REQUIRE:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:
                pass
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("960x700")
        self.minsize(780, 600)
        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.engine: ConverterEngine | None = None
        self.scan_worker: threading.Thread | None = None
        self.scan_request_id = 0
        self.selected_files: list[Path] = []
        self.settings_save_id = None
        self.license_agreed_version = int(restored.get("license_agreed_version") or 0)
        self.source_mode = tk.StringVar(value="folder")
        self.source_dir = tk.StringVar(value=restored["source_dir"])
        self.output_dir = tk.StringVar(value=restored["output_dir"])
        self.format_var = tk.StringVar(value=restored["format"])
        self.recursive = tk.BooleanVar(value=restored["recursive"])
        self.remove_source = tk.BooleanVar(value=False)
        self.download_dir = tk.StringVar(value=restored["download_dir"])
        self.download_format = tk.StringVar(value=restored["download_format"])
        self.download_quality = tk.StringVar(value="最佳")
        self.preview_parts: list[dict] = []
        self.preview_meta: dict = {}
        self.preview_worker: threading.Thread | None = None
        self.playlist_url = tk.StringVar(value=restored["last_playlist_url"])
        self.playlist_meta: dict = {}
        self.playlist_rows: list[dict] = []
        self.playlist_worker: threading.Thread | None = None
        self.playlist_filter = tk.StringVar(value="全部")
        self.playlist_info = tk.StringVar(value="输入歌单链接或 ID 后点击“导入歌单”")
        self.playlist_status = tk.StringVar(value="尚未导入歌单")
        self.login_status = tk.StringVar(value="未登录")
        self.credential_store = CredentialStore()
        self.login_nickname: str | None = None
        self.login_worker: threading.Thread | None = None
        self.theme_var = tk.StringVar(value=restored["theme"])
        self.download_jobs: list[DownloadJob] = []
        self.job_counter = itertools.count(1)
        self.download_rows: list[dict] = []
        self.base_scan_rows: list[dict] = []
        self.bv_info = tk.StringVar(value="输入 BV 号或视频链接后点击“获取信息”")
        self.download_status = tk.StringVar(value="尚未开始下载")
        self.download_counts = tk.StringVar(value="完成 0    跳过 0    失败 0")
        self.status = tk.StringVar(value="请选择输入文件或文件夹")
        self.progress_text = tk.StringVar(value="0 / 0")
        self.count_text = tk.StringVar(value="成功 0    跳过 0    失败 0")
        self.management_filter = tk.StringVar(value="全部")
        self.management_status = tk.StringVar(value="尚未扫描")
        self.management_rows: list[dict] = []
        self.build_ui()
        if BOOTSTRAP_AVAILABLE:
            self.style.configure(".", font=("Microsoft YaHei UI", 10))
            self.style.configure("Treeview", rowheight=28)
            self.style.configure("TNotebook.Tab", padding=(18, 8))
            self.apply_theme_colors()
        self.on_download_tree_select()
        self.setup_drop_target()
        self.load_download_history()
        self.refresh_login_status()
        self.restore_queue()
        self.after(100, self.process_events)
        self.format_var.trace_add("write", self.on_format_changed)
        for variable in (self.source_dir, self.output_dir, self.format_var, self.recursive,
                         self.download_dir, self.download_format, self.playlist_url,
                         self.theme_var):
            variable.trace_add("write", self.schedule_settings_save)
        self.theme_var.trace_add("write", self.on_theme_changed)
        self.schedule_settings_save()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(150, self.refresh_management)

    def on_theme_changed(self, *_):
        if not BOOTSTRAP_AVAILABLE:
            return
        self.style.theme_use(BOOTSTRAP_THEMES.get(self.theme_var.get(), "darkly"))
        self.apply_theme_colors()

    def apply_theme_colors(self):
        if not BOOTSTRAP_AVAILABLE or not hasattr(self, "log"):
            return
        colors = self.style.colors
        for widget in (self.log, self.download_log, self.download_detail):
            widget.configure(bg=colors.bg, fg=colors.fg, insertbackground=colors.fg,
                             highlightthickness=0, relief="flat")
        if hasattr(self, "disclaimer_label"):
            self.disclaimer_label.configure(foreground=colors.secondary)
        self._apply_tree_tags()

    def _apply_tree_tags(self):
        if not BOOTSTRAP_AVAILABLE or not hasattr(self, "download_tree"):
            return
        colors = self.style.colors
        self.download_tree.tag_configure("failed", foreground=colors.danger)
        self.download_tree.tag_configure("ok", foreground=colors.success)
        self.download_tree.tag_configure("skipped", foreground=colors.warning)

    def toggle_theme(self):
        self.theme_var.set("light" if self.theme_var.get() == "dark" else "dark")

    def build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook = notebook
        self.convert_page = ttk.Frame(notebook, padding=4)
        self.manage_page = ttk.Frame(notebook, padding=8)
        self.download_page = ttk.Frame(notebook, padding=8)
        self.playlist_page = ttk.Frame(notebook, padding=8)
        notebook.add(self.convert_page, text="转换")
        notebook.add(self.manage_page, text="音乐管理")
        notebook.add(self.download_page, text="下载")
        notebook.add(self.playlist_page, text="歌单")
        self.build_convert_page()
        self.build_manage_page()
        self.build_download_page()
        self.build_playlist_page()
        disclaimer = ttk.Label(
            self, text="免责声明：本工具仅供个人学习交流，禁止倒卖与商业用途；下载内容的版权归原权利人所有，"
                       "请尊重版权、支持正版；本工具与网易云音乐、Bilibili 官方无关，仅限下载本人有权访问的内容。",
            foreground="#9aa0a6")
        disclaimer.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))
        self.disclaimer_label = disclaimer

    def build_convert_page(self):
        page = self.convert_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        pad = {"padx": 12, "pady": 8}
        source = ttk.LabelFrame(page, text="输入来源")
        source.grid(row=0, column=0, sticky="ew", **pad)
        source.columnconfigure(1, weight=1)
        ttk.Radiobutton(source, text="文件夹", variable=self.source_mode, value="folder", command=self.update_mode).grid(row=0, column=0, sticky="w")
        self.source_entry = ttk.Entry(source, textvariable=self.source_dir)
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.source_button = ttk.Button(source, text="选择文件夹", command=self.choose_folder)
        self.source_button.grid(row=0, column=2)
        ttk.Radiobutton(source, text="文件", variable=self.source_mode, value="files", command=self.update_mode).grid(row=1, column=0, sticky="w")
        self.file_label = ttk.Label(source, text="未选择文件")
        self.file_label.grid(row=1, column=1, sticky="w", padx=8)
        self.file_button = ttk.Button(source, text="选择文件", command=self.choose_files)
        self.file_button.grid(row=1, column=2)
        self.recursive_check = ttk.Checkbutton(source, text="递归处理子目录", variable=self.recursive, command=self.refresh_management)
        self.recursive_check.grid(row=2, column=1, sticky="w", padx=8)

        settings = ttk.LabelFrame(page, text="输出设置")
        settings.grid(row=1, column=0, sticky="ew", **pad)
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="格式").grid(row=0, column=0, sticky="w")
        self.format_box = ttk.Combobox(settings, textvariable=self.format_var, values=("flac", "mp3"), state="readonly", width=10)
        self.format_box.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(settings, text="输出目录").grid(row=1, column=0, sticky="w")
        self.output_entry = ttk.Entry(settings, textvariable=self.output_dir)
        self.output_entry.grid(row=1, column=1, sticky="ew", padx=8)
        self.output_button = ttk.Button(settings, text="选择目录", command=self.choose_output)
        self.output_button.grid(row=1, column=2)
        self.remove_check = ttk.Checkbutton(settings, text="转换成功后删除源文件", variable=self.remove_source)
        self.remove_check.grid(row=2, column=1, sticky="w", padx=8)

        actions = ttk.Frame(page)
        actions.grid(row=2, column=0, sticky="ew", **pad)
        self.start_button = ttk.Button(actions, text="开始转换", command=self.start,
                                       **_bootstyle("success"))
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="停止", command=self.stop, state="disabled",
                                      **_bootstyle("danger-outline"))
        self.stop_button.pack(side="left", padx=8)
        ttk.Button(actions, text="打开输出目录", command=self.open_output).pack(side="left")
        ttk.Button(actions, text="工具信息", command=self.show_tools).pack(side="right")
        self.theme_button = ttk.Button(actions, text="切换主题", command=self.toggle_theme,
                                       **_bootstyle("secondary-outline"))
        self.theme_button.pack(side="right", padx=(0, 8))
        ttk.Button(actions, text="清空日志", command=self.clear_log).pack(side="right", padx=8)

        task = ttk.LabelFrame(page, text="任务状态")
        task.grid(row=3, column=0, sticky="nsew", **pad)
        task.columnconfigure(0, weight=1)
        task.rowconfigure(2, weight=1)
        ttk.Label(task, textvariable=self.status).grid(row=0, column=0, sticky="w")
        ttk.Label(task, textvariable=self.progress_text).grid(row=0, column=1, sticky="e")
        self.progress = ttk.Progressbar(task, mode="determinate")
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
        self.log = tk.Text(task, height=16, state="disabled", wrap="word")
        self.log.grid(row=2, column=0, columnspan=2, sticky="nsew")
        ttk.Label(task, textvariable=self.count_text).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.update_mode()

    def build_manage_page(self):
        page = self.manage_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        intro = ttk.LabelFrame(page, text="拖放导入")
        intro.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        intro.columnconfigure(0, weight=1)
        self.drop_label = ttk.Label(intro, text="将 .ncm 文件或包含 .ncm 的文件夹拖到这里\n拖入后只加入待转换列表，不会自动删除源文件", anchor="center", padding=16)
        self.drop_label.grid(row=0, column=0, sticky="ew")
        if not DND_AVAILABLE:
            self.drop_label.configure(text="当前环境未启用拖放支持，请使用转换页的选择按钮\n也可以安装 tkinterdnd2 后重新构建应用")

        toolbar = ttk.Frame(page)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.management_refresh_button = ttk.Button(toolbar, text="刷新列表", command=self.refresh_management)
        self.management_refresh_button.pack(side="left")
        self.management_convert_button = ttk.Button(toolbar, text="加入转换", command=self.convert_selected)
        self.management_convert_button.pack(side="left", padx=8)
        self.management_source_button = ttk.Button(toolbar, text="打开源目录", command=self.open_selected_source)
        self.management_source_button.pack(side="left")
        self.management_output_button = ttk.Button(toolbar, text="打开输出目录", command=self.open_output)
        self.management_output_button.pack(side="left", padx=8)
        ttk.Label(toolbar, text="筛选").pack(side="right", padx=(12, 4))
        filter_box = ttk.Combobox(toolbar, textvariable=self.management_filter,
                                  values=("全部", "未转换", "已转换", "目标缺失", "已下载"),
                                  state="readonly", width=10)
        self.management_filter_box = filter_box
        filter_box.pack(side="right")
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.render_management())

        table_frame = ttk.Frame(page)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = ("name", "folder", "size", "format", "status", "output", "source")
        self.management_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        headings = {"name": "文件名", "folder": "所在目录", "size": "大小", "format": "格式", "status": "状态", "output": "输出文件", "source": "源文件"}
        widths = {"name": 220, "folder": 180, "size": 90, "format": 70, "status": 90, "output": 240, "source": 0}
        for column in columns:
            self.management_tree.heading(column, text=headings[column])
            self.management_tree.column(column, width=widths[column], anchor="w", stretch=column != "source")
        self.management_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.management_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.management_tree.configure(yscrollcommand=scrollbar.set)
        ttk.Label(page, textvariable=self.management_status).grid(row=3, column=0, sticky="w", pady=(8, 0))

    def build_download_page(self):
        page = self.download_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        pad = {"padx": 12, "pady": 8}

        source = ttk.LabelFrame(page, text="Bilibili 视频")
        source.grid(row=0, column=0, sticky="ew", **pad)
        source.columnconfigure(0, weight=1)
        input_row = ttk.Frame(source)
        input_row.grid(row=0, column=0, sticky="ew")
        input_row.columnconfigure(0, weight=1)
        self.bv_entry = ttk.Entry(input_row)
        self.bv_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.bv_entry.bind("<Return>", lambda _event: self.fetch_preview())
        self.bv_preview_button = ttk.Button(input_row, text="获取信息", command=self.fetch_preview)
        self.bv_preview_button.grid(row=0, column=1)
        ttk.Label(source, textvariable=self.bv_info).grid(row=1, column=0, sticky="w", pady=(6, 0))
        parts_frame = ttk.Frame(source)
        parts_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        parts_frame.columnconfigure(0, weight=1)
        self.parts_tree = ttk.Treeview(parts_frame, columns=("part", "title"), show="headings",
                                       height=5, selectmode="extended")
        self.parts_tree.heading("part", text="分P")
        self.parts_tree.heading("title", text="标题")
        self.parts_tree.column("part", width=60, anchor="w", stretch=False)
        self.parts_tree.column("title", width=560, anchor="w", stretch=True)
        self.parts_tree.grid(row=0, column=0, sticky="nsew")
        parts_scroll = ttk.Scrollbar(parts_frame, orient="vertical", command=self.parts_tree.yview)
        parts_scroll.grid(row=0, column=1, sticky="ns")
        self.parts_tree.configure(yscrollcommand=parts_scroll.set)
        parts_frame.rowconfigure(0, weight=1)

        settings = ttk.LabelFrame(page, text="下载设置")
        settings.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Label(settings, text="音频格式").grid(row=0, column=0, sticky="w")
        self.download_format_box = ttk.Combobox(settings, textvariable=self.download_format,
                                                values=("mp3", "m4a", "flac"), state="readonly", width=10)
        self.download_format_box.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(settings, text="音质").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.download_quality_box = ttk.Combobox(settings, textvariable=self.download_quality,
                                                 values=tuple(QUALITY_CHOICES), state="readonly", width=10)
        self.download_quality_box.grid(row=0, column=3, sticky="w", padx=8)
        ttk.Label(settings, text="下载目录").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.download_dir_entry = ttk.Entry(settings, textvariable=self.download_dir)
        self.download_dir_entry.grid(row=1, column=1, columnspan=3, sticky="ew", padx=8, pady=(6, 0))
        self.download_dir_button = ttk.Button(settings, text="选择目录", command=self.choose_download_dir)
        self.download_dir_button.grid(row=1, column=4, sticky="w", pady=(6, 0))

        actions = ttk.Frame(page)
        actions.grid(row=2, column=0, sticky="ew", **pad)
        self.add_download_button = ttk.Button(actions, text="加入下载", command=self.add_download_jobs)
        self.add_download_button.pack(side="left")
        self.start_download_button = ttk.Button(actions, text="开始下载", command=self.start_download,
                                                **_bootstyle("success"))
        self.start_download_button.pack(side="left", padx=8)
        self.download_stop_button = ttk.Button(actions, text="停止", command=self.stop,
                                               state="disabled", **_bootstyle("danger-outline"))
        self.download_stop_button.pack(side="left")
        self.download_open_button = ttk.Button(actions, text="打开下载目录", command=self.open_download_dir)
        self.download_open_button.pack(side="left", padx=(16, 0))
        self.download_retry_button = ttk.Button(actions, text="重试失败", command=self.retry_failed_downloads)
        self.download_retry_button.pack(side="right", padx=(0, 8))
        self.download_clear_button = ttk.Button(actions, text="清空列表", command=self.clear_download_list)
        self.download_clear_button.pack(side="right")

        task = ttk.LabelFrame(page, text="下载任务")
        task.grid(row=3, column=0, sticky="nsew", **pad)
        task.columnconfigure(0, weight=1)
        task.rowconfigure(0, weight=3)
        task.rowconfigure(4, weight=2)
        columns = ("name", "format", "status", "output")
        self.download_tree = ttk.Treeview(task, columns=columns, show="headings")
        download_headings = {"name": "名称", "format": "格式", "status": "状态", "output": "输出文件"}
        download_widths = {"name": 300, "format": 70, "status": 90, "output": 420}
        for column in columns:
            self.download_tree.heading(column, text=download_headings[column])
            self.download_tree.column(column, width=download_widths[column], anchor="w",
                                      stretch=column in ("name", "output"))
        self.download_tree.grid(row=0, column=0, sticky="nsew")
        task_scroll = ttk.Scrollbar(task, orient="vertical", command=self.download_tree.yview)
        task_scroll.grid(row=0, column=1, sticky="ns")
        self.download_tree.configure(yscrollcommand=task_scroll.set)
        self.download_tree.bind("<<TreeviewSelect>>", self.on_download_tree_select)
        self.download_progress = ttk.Progressbar(task, mode="determinate")
        self.download_progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(task, textvariable=self.download_status).grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(task, textvariable=self.download_counts).grid(row=2, column=1, sticky="e", pady=(4, 0))

        detail = ttk.LabelFrame(task, text="任务详情（选中任务后显示错误或输出信息）")
        detail.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        detail.columnconfigure(0, weight=1)
        self.download_detail = tk.Text(detail, height=3, wrap="word", state="disabled")
        self.download_detail.grid(row=0, column=0, sticky="ew")

        logs = ttk.LabelFrame(task, text="运行日志")
        logs.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)
        self.download_log = tk.Text(logs, height=8, wrap="word", state="disabled")
        self.download_log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(logs, orient="vertical", command=self.download_log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.download_log.configure(yscrollcommand=log_scroll.set)

    def build_playlist_page(self):
        page = self.playlist_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        pad = {"padx": 12, "pady": 8}

        login = ttk.LabelFrame(page, text="网易云登录")
        login.grid(row=0, column=0, sticky="ew", **pad)
        login.columnconfigure(0, weight=1)
        ttk.Label(login, textvariable=self.login_status).grid(row=0, column=0, sticky="w")
        self.login_button = ttk.Button(login, text="登录…", command=self.open_login_dialog,
                                       **_bootstyle("primary"))
        self.login_button.grid(row=0, column=1, padx=(8, 0))
        self.logout_button = ttk.Button(login, text="退出登录", command=self.logout,
                                        **_bootstyle("secondary-outline"))
        self.logout_button.grid(row=0, column=2, padx=(8, 0))

        source = ttk.LabelFrame(page, text="网易云歌单")
        source.grid(row=1, column=0, sticky="ew", **pad)
        source.columnconfigure(0, weight=1)
        input_row = ttk.Frame(source)
        input_row.grid(row=0, column=0, sticky="ew")
        input_row.columnconfigure(0, weight=1)
        self.playlist_entry = ttk.Entry(input_row, textvariable=self.playlist_url)
        self.playlist_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.playlist_entry.bind("<Return>", lambda _event: self.fetch_playlist())
        self.playlist_import_button = ttk.Button(input_row, text="导入歌单", command=self.fetch_playlist)
        self.playlist_import_button.grid(row=0, column=1)
        ttk.Label(source, textvariable=self.playlist_info).grid(row=1, column=0, sticky="w", pady=(6, 0))

        toolbar = ttk.Frame(page)
        toolbar.grid(row=2, column=0, sticky="ew", **pad)
        self.playlist_select_all_button = ttk.Button(toolbar, text="全选", command=self.select_all_playlist)
        self.playlist_select_all_button.pack(side="left")
        self.playlist_deselect_button = ttk.Button(toolbar, text="取消全选", command=self.deselect_all_playlist)
        self.playlist_deselect_button.pack(side="left", padx=(8, 0))
        self.playlist_add_button = ttk.Button(toolbar, text="加入下载", command=self.add_playlist_to_queue)
        self.playlist_add_button.pack(side="left", padx=(16, 0))
        ttk.Label(toolbar, text="筛选").pack(side="right", padx=(12, 4))
        self.playlist_filter_box = ttk.Combobox(toolbar, textvariable=self.playlist_filter,
                                                values=("全部", "免费", "VIP", "限免", "购买专辑",
                                                        "无版权", "不可用"),
                                                state="readonly", width=10)
        self.playlist_filter_box.pack(side="right")
        self.playlist_filter_box.bind("<<ComboboxSelected>>", lambda _event: self.render_playlist())

        table_frame = ttk.Frame(page)
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = ("name", "artist", "album", "status", "song_id")
        self.playlist_tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                          selectmode="extended")
        playlist_headings = {"name": "歌曲", "artist": "歌手", "album": "专辑",
                             "status": "状态", "song_id": "歌曲 ID"}
        playlist_widths = {"name": 280, "artist": 200, "album": 220, "status": 80, "song_id": 100}
        for column in columns:
            self.playlist_tree.heading(column, text=playlist_headings[column])
            self.playlist_tree.column(column, width=playlist_widths[column], anchor="w",
                                      stretch=column in ("name", "artist", "album"))
        self.playlist_tree.grid(row=0, column=0, sticky="nsew")
        playlist_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.playlist_tree.yview)
        playlist_scroll.grid(row=0, column=1, sticky="ns")
        self.playlist_tree.configure(yscrollcommand=playlist_scroll.set)
        self.playlist_tree.bind("<<TreeviewSelect>>", lambda _event: self.update_playlist_selection_count())
        ttk.Label(page, textvariable=self.playlist_status).grid(row=4, column=0, sticky="w", pady=(8, 0))

    def setup_drop_target(self):
        if not DND_AVAILABLE:
            return
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind("<<Drop>>", self.on_drop)
        self.manage_page.drop_target_register(DND_FILES)
        self.manage_page.dnd_bind("<<Drop>>", self.on_drop)

    def on_drop(self, event):
        if self.worker and self.worker.is_alive():
            return
        paths = [Path(item).expanduser().resolve() for item in self.tk.splitlist(event.data)]
        files: list[Path] = []
        folders: list[Path] = []
        for path in paths:
            if path.is_file() and path.suffix.lower() == ".ncm":
                files.append(path)
            elif path.is_dir():
                folders.append(path)
        if files and not folders:
            self.selected_files = sorted(set(files))
            self.source_mode.set("files")
            self.file_label.configure(text=f"已选择 {len(self.selected_files)} 个文件")
            self.update_mode()
            self.management_status.set(f"已加入 {len(files)} 个待转换文件")
        elif folders:
            self.source_dir.set(str(folders[0]))
            self.source_mode.set("folder")
            self.update_mode()
            self.management_status.set(f"已载入文件夹：{folders[0]}")
        else:
            messagebox.showwarning(APP_TITLE, "拖入的内容中没有找到 .ncm 文件或文件夹。")
        self.refresh_management()

    def update_mode(self):
        is_folder = self.source_mode.get() == "folder"
        self.source_entry.configure(state="normal" if is_folder else "disabled")
        self.source_button.configure(state="normal" if is_folder else "disabled")
        self.file_button.configure(state="normal" if not is_folder else "disabled")
        self.recursive_check.configure(state="normal" if is_folder else "disabled")
        if hasattr(self, "management_tree"):
            self.refresh_management()

    def on_format_changed(self, *_):
        self.update_default_output()
        if hasattr(self, "management_tree"):
            self.refresh_management()

    def update_default_output(self):
        current = Path(self.output_dir.get())
        if current.name in {"flac", "mp3"} and current.parent.name == "output":
            self.output_dir.set(str(current.parent / self.format_var.get()))

    def choose_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.source_dir.get())
        if chosen:
            self.source_dir.set(chosen)
            self.refresh_management()

    def choose_files(self):
        chosen = filedialog.askopenfilenames(filetypes=[("NCM 文件", "*.ncm"), ("所有文件", "*.*")])
        if chosen:
            self.selected_files = [Path(item).resolve() for item in chosen]
            self.source_mode.set("files")
            self.file_label.configure(text=f"已选择 {len(self.selected_files)} 个文件")
            self.update_mode()

    def choose_output(self):
        chosen = filedialog.askdirectory(initialdir=self.output_dir.get())
        if chosen:
            self.output_dir.set(chosen)
            self.refresh_management()

    def collect_files(self):
        if self.source_mode.get() == "files":
            if not self.selected_files:
                raise ValueError("请先选择至少一个 NCM 文件。")
            return [item.expanduser().resolve() for item in self.selected_files], None
        if not self.source_dir.get().strip():
            raise ValueError("未识别到网易云下载目录，请选择输入文件夹。")
        source = Path(self.source_dir.get()).expanduser()
        if not source.is_dir():
            raise ValueError(f"输入文件夹不存在：{source}")
        source = source.resolve()
        files = list(source.rglob("*.ncm") if self.recursive.get() else source.glob("*.ncm"))
        return sorted(item.resolve() for item in files), source

    def start(self, files_override: list[Path] | None = None):
        if self.worker and self.worker.is_alive():
            self.status.set("当前有任务正在运行，请等待完成或先点击“停止”。")
            return
        try:
            if files_override is None:
                files, source_root = self.collect_files()
            else:
                files, source_root = files_override, None
            output = Path(self.output_dir.get()).expanduser().resolve()
            if not files:
                raise ValueError("没有找到 NCM 文件。")
            if source_root and output == source_root:
                raise ValueError("输出目录不能与输入目录相同。")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.persist_settings()
        self.stop_event.clear()
        self.progress.configure(maximum=len(files), value=0)
        self.progress_text.set(f"0 / {len(files)}")
        self.count_text.set("成功 0    跳过 0    失败 0")
        self.status.set("正在转换…")
        self.set_running(True)
        self.engine = ConverterEngine(app_root(), self.emit, self.stop_event)
        self.worker = threading.Thread(target=self.engine.convert, args=(files, source_root, output, self.format_var.get(), self.remove_source.get()), daemon=True)
        self.worker.start()

    def convert_selected(self):
        selection = self.management_tree.selection()
        selected_paths = []
        for item in selection:
            values = self.management_tree.item(item, "values")
            if len(values) > 6 and values[6]:
                selected_paths.append(Path(values[6]))
        if not selected_paths:
            messagebox.showinfo(APP_TITLE, "请先在列表中选择要转换的歌曲。")
            return
        self.source_mode.set("files")
        self.selected_files = selected_paths
        self.file_label.configure(text=f"已选择 {len(selected_paths)} 个文件")
        self.update_mode()
        self.notebook.select(self.convert_page)
        self.start(files_override=selected_paths)

    def choose_download_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.download_dir.get())
        if chosen:
            self.download_dir.set(chosen)

    def open_download_dir(self):
        directory = self.download_dir.get().strip()
        if directory and Path(directory).is_dir():
            os.startfile(directory)
        else:
            messagebox.showwarning(APP_TITLE, "下载目录不存在。")

    def append_download_log(self, text: str):
        if not hasattr(self, "download_log"):
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.download_log.configure(state="normal")
        self.download_log.insert("end", f"[{stamp}] {text}\n")
        line_count = int(float(self.download_log.index("end-1c")))
        if line_count > 800:
            self.download_log.delete("1.0", "200.0")
        self.download_log.see("end")
        self.download_log.configure(state="disabled")

    def on_download_tree_select(self, _event=None):
        if not hasattr(self, "download_detail"):
            return
        selection = self.download_tree.selection()
        job = None
        if selection:
            item_id = selection[0]
            job = next((item for item in self.download_jobs
                        if str(item.job_id) == item_id), None)
        self.download_detail.configure(state="normal")
        self.download_detail.delete("1.0", "end")
        if job is None:
            self.download_detail.insert("1.0", "选择一个任务查看详情或错误信息。")
        else:
            lines = [f"[{job.status}] {job.info.title}"]
            if job.detail:
                lines.append(job.detail)
            if job.target is not None:
                lines.append(f"输出：{job.target}")
            self.download_detail.insert("1.0", "\n".join(lines))
        self.download_detail.configure(state="disabled")

    def _mark_tree_status(self, job_id: int, status: str):
        if not self.download_tree.exists(str(job_id)):
            return
        tag = {"失败": "failed", "已完成": "ok", "已跳过": "skipped"}.get(status, "")
        self.download_tree.item(str(job_id), tags=(tag,) if tag else ())

    def clear_download_list(self):
        if self.worker and self.worker.is_alive():
            return
        self.download_jobs.clear()
        self.download_tree.delete(*self.download_tree.get_children())
        self.download_progress.configure(value=0)
        self.download_status.set("已清空下载列表")
        self.on_download_tree_select()
        self._save_queue()

    def retry_failed_downloads(self):
        if self.worker and self.worker.is_alive():
            return
        retried = 0
        for job in self.download_jobs:
            if job.status == STATUS_FAILED:
                job.status = STATUS_PENDING
                job.detail = ""
                job.attempts = 0
                if self.download_tree.exists(str(job.job_id)):
                    self.download_tree.set(str(job.job_id), "status", STATUS_PENDING)
                    self.download_tree.item(str(job.job_id), tags=())
                retried += 1
        if not retried:
            messagebox.showinfo(APP_TITLE, "没有失败的任务。")
            return
        self.download_status.set(f"已重置 {retried} 个失败任务，点击“开始下载”重试。")
        self.on_download_tree_select()
        self._save_queue()

    def _save_queue(self):
        try:
            save_queue(self.download_jobs)
        except Exception as exc:
            self.append_log(f"保存下载队列失败：{exc}")

    def restore_queue(self):
        stored = load_queue()
        for item in stored:
            item.status = STATUS_PENDING
            item.job_id = next(self.job_counter)
            self.download_jobs.append(item)
            self.download_tree.insert("", "end", iid=str(item.job_id),
                                      values=(item.info.title, item.fmt.upper(), STATUS_PENDING, ""))
        if stored:
            self.download_status.set(f"已恢复 {len(stored)} 个未完成下载任务，点击“开始下载”继续。")

    def fetch_preview(self):
        if self.worker and self.worker.is_alive():
            return
        if self.preview_worker and self.preview_worker.is_alive():
            return
        text = self.bv_entry.get().strip()
        if not text:
            messagebox.showwarning(APP_TITLE, "请先输入 BV 号或视频链接。")
            return
        self.bv_preview_button.configure(state="disabled")
        self.bv_info.set("正在获取视频信息…")
        self.preview_worker = threading.Thread(target=self._preview_worker, args=(text,), daemon=True)
        self.preview_worker.start()

    def _preview_worker(self, text: str):
        try:
            url = bilibili.parse_bilibili_input(text)
            if not url:
                raise ValueError("无法识别 BV 号或 Bilibili 视频链接。")
            preview = bilibili.preview_video(url)
            self.emit("preview_result", preview)
        except Exception as exc:
            self.emit("preview_error", str(exc))

    def apply_preview(self, preview):
        self.preview_meta = {"title": preview.title, "uploader": preview.uploader}
        self.preview_parts = preview.parts
        self.parts_tree.delete(*self.parts_tree.get_children())
        for part in preview.parts:
            self.parts_tree.insert("", "end", iid=str(part["index"]),
                                   values=(f"P{part['index']}", part["title"]))
        for child in self.parts_tree.get_children():
            self.parts_tree.selection_add(child)
        uploader = f" · {preview.uploader}" if preview.uploader else ""
        self.bv_info.set(f"{preview.title}（共 {len(preview.parts)} 个分P）{uploader}")
        self.download_status.set("已获取视频信息，选择分P后点击“加入下载”。")

    def add_download_jobs(self):
        if not self.preview_parts:
            messagebox.showinfo(APP_TITLE, "请先获取视频信息。")
            return
        selection = self.parts_tree.selection()
        if not selection:
            messagebox.showinfo(APP_TITLE, "请先在分P列表中选择要下载的分P。")
            return
        fmt = self.download_format.get()
        quality = QUALITY_CHOICES.get(self.download_quality.get(), "0")
        multi = len(self.preview_parts) > 1
        pending_urls = {job.info.url for job in self.download_jobs if job.status == STATUS_PENDING}
        added = 0
        for item_id in selection:
            part = next((item for item in self.preview_parts if str(item["index"]) == item_id), None)
            if part is None or part["url"] in pending_urls:
                continue
            title = f"{self.preview_meta.get('title', '')} P{part['index']}" if multi else str(part["title"])
            info = TrackInfo(
                title=title,
                artist=self.preview_meta.get("uploader", ""),
                source_kind=SOURCE_BILIBILI,
                source_id=bilibili.extract_video_id(part["url"]),
                url=part["url"],
            )
            job = DownloadJob(info=info, fmt=fmt, quality=quality, job_id=next(self.job_counter))
            self.download_jobs.append(job)
            self.download_tree.insert("", "end", iid=str(job.job_id),
                                      values=(title, fmt.upper(), STATUS_PENDING, ""))
            pending_urls.add(part["url"])
            added += 1
        if added:
            self.download_status.set(f"已加入 {added} 个下载任务。")
            self.append_download_log(f"已加入 {added} 个下载任务，点击“开始下载”开始。")
            self._save_queue()

    def start_download(self):
        if self.worker and self.worker.is_alive():
            message = "当前有任务正在运行（转换或下载），请等待完成或先点击“停止”。"
            self.download_status.set(message)
            self.append_download_log(f"开始下载被跳过：{message}")
            return
        pending = [job for job in self.download_jobs if job.status == STATUS_PENDING]
        if not pending:
            messagebox.showinfo(APP_TITLE, "没有等待下载的任务，请先加入下载。")
            return
        directory = self.download_dir.get().strip()
        if not directory:
            messagebox.showerror(APP_TITLE, "请先选择下载目录。")
            return
        download_root = Path(directory).expanduser()
        try:
            download_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"无法创建下载目录：{exc}")
            return
        for job in pending:
            job.target = download_root / f"{safe_filename(job.info.title)}.{job.fmt}"
            job.detail = ""
        self.persist_settings()
        self.stop_event.clear()
        self.download_progress.configure(maximum=len(pending), value=0)
        self.download_counts.set("完成 0    跳过 0    失败 0")
        self.status.set("正在下载…")
        self.download_status.set("准备下载…")
        try:
            engine = DownloadEngine(app_root(), self.emit, self.stop_event,
                                    netease_cookie=self.netease_cookie())
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"无法启动下载引擎：{exc}")
            return
        self.engine = engine
        self.set_running(True)

        def runner():
            try:
                engine.run(pending)
            except Exception as exc:
                # 引擎线程意外崩溃时也必须回报 download_done，否则界面永久停留在运行态。
                self.emit("download_log", f"下载引擎异常终止：{exc}")
                self.emit("download_done", {"success": 0, "skipped": 0, "failed": 0},
                          [f"引擎异常：{exc}"], True)

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()

    def load_download_history(self):
        try:
            entries = load_completed()
        except Exception:
            entries = []
        rows: dict[str, dict] = {}
        for entry in entries:
            row = self.history_row(entry)
            if row is not None:
                rows.setdefault(str(row["source"]), row)
        self.download_rows = list(rows.values())
        self.remerge_management()

    def history_row(self, entry: dict) -> dict | None:
        path_value = entry.get("path") or ""
        if not path_value:
            return None
        path = Path(path_value)
        try:
            if not path.is_file():
                status = "目标缺失"
            else:
                status = "已下载"
            size = format_size(path.stat().st_size)
        except OSError:
            return None
        fmt = str(entry.get("fmt") or path.suffix.lstrip(".") or "?").upper()
        return {"source": path, "target": path, "name": path.name, "folder": path.parent.name,
                "size": size, "format": fmt, "status": status, "output": str(path)}

    def remerge_management(self):
        if not hasattr(self, "management_tree"):
            return
        self.management_rows = list(self.base_scan_rows) + self.download_rows
        self.render_management()

    def on_download_status(self, job_id: int, status: str):
        """引擎回报单个任务的状态变化（如“下载中”），同步任务树与详情面板。"""
        job = next((item for item in self.download_jobs if item.job_id == job_id), None)
        if job is not None:
            job.status = status
        if self.download_tree.exists(str(job_id)):
            self.download_tree.set(str(job_id), "status", status)
            self._mark_tree_status(job_id, status)
            if str(job_id) in self.download_tree.selection():
                self.on_download_tree_select()

    def on_download_result(self, job_id: int, status: str, detail: str, path: str):
        job = next((item for item in self.download_jobs if item.job_id == job_id), None)
        if job is not None:
            job.status = status
            job.detail = detail
        if self.download_tree.exists(str(job_id)):
            self.download_tree.set(str(job_id), "status", status)
            if path:
                self.download_tree.set(str(job_id), "output", path)
            self._mark_tree_status(job_id, status)
        if status in (STATUS_COMPLETED, STATUS_SKIPPED) and path and job is not None:
            row = self.history_row({"path": path, "fmt": job.fmt})
            if row is not None:
                self.download_rows = [item for item in self.download_rows
                                      if item["source"] != row["source"]] + [row]
            self.remerge_management()
        if job is not None and str(job_id) in self.download_tree.selection():
            self.on_download_tree_select()
        self._save_queue()

    def fetch_playlist(self):
        if self.worker and self.worker.is_alive():
            return
        if self.playlist_worker and self.playlist_worker.is_alive():
            return
        text = self.playlist_url.get().strip()
        playlist_id = netease_client.parse_playlist_input(text)
        if not playlist_id:
            messagebox.showwarning(APP_TITLE, "请先输入网易云歌单链接或歌单 ID（纯数字）。")
            return
        self.playlist_import_button.configure(state="disabled")
        self.playlist_info.set("正在导入歌单…")
        self.playlist_worker = threading.Thread(target=self._playlist_worker,
                                                args=(playlist_id,), daemon=True)
        self.playlist_worker.start()

    def _playlist_worker(self, playlist_id: str):
        try:
            meta = netease_client.fetch_playlist(playlist_id)
            rows: list[dict] = []

            def report_progress(loaded, total_count):
                self.emit("playlist_progress", loaded, total_count)

            rows = netease_client.fetch_song_details(
                meta["track_ids"], meta["known_tracks"], progress=report_progress)
            self.emit("playlist_result", meta, rows)
        except Exception as exc:
            self.emit("playlist_error", str(exc))

    def apply_playlist(self, meta: dict, rows: list[dict]):
        self.playlist_meta = meta
        self.playlist_rows = rows
        self.playlist_tree.delete(*self.playlist_tree.get_children())
        for row in rows:
            self.playlist_tree.insert("", "end", iid=row["id"],
                                      values=(row["name"], row["artist"], row["album"],
                                              row["status"], row["id"]))
        creator = f" · {meta['creator']}" if meta.get("creator") else ""
        self.playlist_info.set(f"{meta['name']}（共 {meta['track_count']} 首）{creator}")
        self.playlist_status.set("导入完成，请选择歌曲后点击“加入下载”。")
        self.render_playlist()

    def render_playlist(self):
        if not hasattr(self, "playlist_tree"):
            return
        selected_filter = self.playlist_filter.get()
        shown = 0
        for item in self.playlist_tree.get_children():
            self.playlist_tree.detach(item)
            values = self.playlist_tree.item(item, "values")
            if selected_filter == "全部" or (values and values[3] == selected_filter):
                self.playlist_tree.reattach(item, "", "end")
                shown += 1
        self.update_playlist_selection_count()

    def select_all_playlist(self):
        for item in self.playlist_tree.get_children():
            self.playlist_tree.selection_add(item)
        self.update_playlist_selection_count()

    def deselect_all_playlist(self):
        self.playlist_tree.selection_remove(self.playlist_tree.selection())
        self.update_playlist_selection_count()

    def update_playlist_selection_count(self):
        if not hasattr(self, "playlist_tree"):
            return
        total = len(self.playlist_rows)
        selected = len(self.playlist_tree.selection())
        if total:
            self.playlist_status.set(
                f"歌单共 {total} 首，当前显示 {len(self.playlist_tree.get_children())} 首，已选择 {selected} 首")
        else:
            self.playlist_status.set("尚未导入歌单")

    def add_playlist_to_queue(self):
        selection = self.playlist_tree.selection()
        if not selection:
            messagebox.showinfo(APP_TITLE, "请先选择要加入下载的歌曲。")
            return
        fmt = self.download_format.get()
        pending_keys = {(job.info.source_kind, job.info.source_id)
                        for job in self.download_jobs if job.status == STATUS_PENDING}
        added = 0
        for song_id in selection:
            if (SOURCE_NETEASE, song_id) in pending_keys:
                continue
            row = self.playlist_tree.item(song_id, "values")
            name, artist, album = row[0], row[1], row[2]
            if not name:
                continue
            title = f"{artist} - {name}" if artist else name
            info = TrackInfo(title=title, artist=artist, album=album,
                             source_kind=SOURCE_NETEASE, source_id=song_id, url="")
            job = DownloadJob(info=info, fmt=fmt, quality="0", job_id=next(self.job_counter))
            self.download_jobs.append(job)
            self.download_tree.insert("", "end", iid=str(job.job_id),
                                      values=(title, fmt.upper(), STATUS_PENDING, ""))
            pending_keys.add((SOURCE_NETEASE, song_id))
            added += 1
        if added:
            hint = "" if self.netease_cookie() else "（未登录：网易云歌曲将下载失败，请先在“歌单”页登录）"
            self.playlist_status.set(f"已加入 {added} 首歌曲到下载队列，开始后逐首批量下载。{hint}")
            self.append_download_log(
                f"已加入 {added} 首歌曲到下载队列，点击“开始下载”开始。{hint}")
            self._save_queue()
            self.notebook.select(self.download_page)

    def refresh_login_status(self):
        if not self.credential_store.available():
            self.login_status.set("当前系统不支持安全凭据存储，网易云登录下载不可用。")
            return
        values = self.credential_store.load()
        cookie = values.get("music_u") if values else None
        if not cookie:
            self.login_nickname = None
            self.login_status.set("未登录：网易云歌曲下载需要登录，点击“登录…”导入 MUSIC_U。")
            return
        if self.login_worker and self.login_worker.is_alive():
            return
        self.login_status.set("已保存登录凭据，正在验证…")
        self.login_worker = threading.Thread(target=self._login_check_worker,
                                             args=(cookie,), daemon=True)
        self.login_worker.start()

    def _login_check_worker(self, cookie: str):
        try:
            nickname = netease_client.fetch_user_account(cookie)
            self.emit("login_check_result", nickname, "")
        except Exception as exc:
            self.emit("login_check_result", None, str(exc))

    def apply_login_state(self, nickname: str | None, error: str):
        if nickname is not None:
            self.login_nickname = nickname
            shown = nickname or "网易云用户"
            self.login_status.set(f"已登录：{shown}（凭据已用 Windows 加密保存在本机）")
        elif error:
            self.login_status.set("已保存登录凭据（暂时无法验证，可能是网络问题）。")
        else:
            self.login_nickname = None
            self.login_status.set("登录凭据已失效，请重新登录。")

    def open_login_dialog(self):
        if not self.credential_store.available():
            messagebox.showerror(APP_TITLE, "当前系统无法提供安全凭据存储（DPAPI），登录功能不可用。")
            return
        LoginDialog(self)

    def on_login_dialog_result(self, dialog, value: str, nickname: str | None, error: str):
        if nickname is not None:
            try:
                self.credential_store.save({"music_u": value})
            except CredentialUnavailable as exc:
                messagebox.showerror(APP_TITLE, f"凭据保存失败：{exc}")
                return
            self.apply_login_state(nickname, "")
            self.append_log(f"网易云登录成功：{nickname or '用户'}")
            self.append_download_log(f"网易云登录成功：{nickname or '用户'}，凭据已加密保存。")
            try:
                dialog.destroy()
            except tk.TclError:
                pass
        elif error:
            if dialog.winfo_exists():
                dialog.message.set(f"验证失败：{error}\n请检查网络后重试。")
                for widget in dialog.winfo_children():
                    if isinstance(widget, ttk.Button):
                        widget.configure(state="normal")
        else:
            if dialog.winfo_exists():
                dialog.message.set("MUSIC_U 无效或已过期，请重新复制。")
                for widget in dialog.winfo_children():
                    if isinstance(widget, ttk.Button):
                        widget.configure(state="normal")

    def logout(self):
        if not self.credential_store.load():
            messagebox.showinfo(APP_TITLE, "当前没有保存的登录凭据。")
            return
        if not messagebox.askyesno(APP_TITLE, "确定退出登录并删除本机保存的凭据吗？"):
            return
        self.credential_store.clear()
        self.login_nickname = None
        self.login_status.set("已退出登录，本机凭据已删除。")

    def netease_cookie(self) -> str | None:
        values = self.credential_store.load()
        cookie = values.get("music_u") if values else None
        return cookie or None

    def stop(self):
        self.stop_event.set()
        if self.engine:
            self.engine.stop()
        self.status.set("正在停止…")

    def set_running(self, running: bool):
        state = "disabled" if running else "normal"
        for widget in (self.start_button, self.source_button, self.file_button, self.output_button, self.format_box, self.remove_check, self.recursive_check):
            widget.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")
        if hasattr(self, "management_refresh_button"):
            self.management_refresh_button.configure(state=state)
        management_widgets = (
            self.management_refresh_button,
            self.management_convert_button,
            self.management_source_button,
            self.management_output_button,
            self.management_filter_box,
        )
        for widget in management_widgets:
            widget.configure(state=state)
        download_widgets = (
            self.bv_preview_button,
            self.add_download_button,
            self.start_download_button,
            self.download_dir_button,
            self.download_format_box,
            self.download_quality_box,
            self.download_clear_button,
            self.download_open_button,
            self.download_retry_button,
        )
        for widget in download_widgets:
            widget.configure(state=state)
        # 注意：ttk.Treeview 没有 -state 选项，不能 configure 禁用；
        # 曾因对 parts_tree 配置 state 抛 TclError，导致引擎未启动、任务永远“等待中”。
        self.download_stop_button.configure(state="normal" if running else "disabled")
        playlist_widgets = (
            self.playlist_import_button,
            self.playlist_select_all_button,
            self.playlist_deselect_button,
            self.playlist_add_button,
            self.playlist_filter_box,
            self.login_button,
            self.logout_button,
        )
        for widget in playlist_widgets:
            widget.configure(state=state)
        if not running:
            self.engine = None

    def emit(self, kind, *values):
        self.events.put((kind, values))

    def report_callback_exception(self, exc, val, tb):
        """Tk 回调（按钮命令等）的未捕获异常写入日志，避免静默失败。"""
        message = f"界面操作异常：{val}"
        try:
            self.append_log(message)
        except Exception:
            pass
        try:
            self.append_download_log(message)
        except Exception:
            pass

    def process_events(self):
        try:
            while True:
                kind, values = self.events.get_nowait()
                try:
                    if kind == "log":
                        self.append_log(values[0])
                    elif kind == "command":
                        self.append_log(f"命令：{values[0]}")
                    elif kind == "progress":
                        current, total, name = values
                        self.progress.configure(maximum=total, value=current)
                        self.progress_text.set(f"{current} / {total}")
                        self.status.set(f"正在处理：{name}")
                    elif kind == "result":
                        source, target, status, detail = values
                        self.update_management_result(source, target, status, detail)
                    elif kind == "scan":
                        request_id, rows = values
                        if request_id == self.scan_request_id:
                            self.base_scan_rows = rows
                            self.management_rows = rows + self.download_rows
                            self.render_management()
                    elif kind == "preview_result":
                        self.apply_preview(values[0])
                        self.append_download_log(
                            f"已获取视频信息：{values[0].title}（共 {len(values[0].parts)} 个分P）")
                        if not (self.worker and self.worker.is_alive()):
                            self.bv_preview_button.configure(state="normal")
                    elif kind == "preview_error":
                        message = values[0]
                        self.preview_parts = []
                        self.preview_meta = {}
                        self.parts_tree.delete(*self.parts_tree.get_children())
                        self.bv_info.set("获取视频信息失败")
                        self.append_download_log(f"获取视频信息失败：{message}")
                        messagebox.showerror(APP_TITLE, f"获取视频信息失败：\n{message}")
                        if not (self.worker and self.worker.is_alive()):
                            self.bv_preview_button.configure(state="normal")
                    elif kind == "download_log":
                        self.append_download_log(values[0])
                    elif kind == "download_status":
                        self.on_download_status(values[0], values[1])
                    elif kind == "download_progress":
                        current, total, name = values
                        self.download_progress.configure(maximum=total, value=current)
                        self.download_status.set(f"正在下载 {current}/{total}：{name}")
                    elif kind == "download_bytes":
                        percent, name = values
                        self.download_status.set(f"正在下载：{name}（{percent}%）")
                    elif kind == "download_result":
                        job_id, status, detail, path = values
                        self.on_download_result(job_id, status, detail, path)
                    elif kind == "playlist_progress":
                        loaded, total = values
                        self.playlist_info.set(f"正在导入歌单…（已获取 {loaded}/{total} 首详情）")
                    elif kind == "playlist_result":
                        self.apply_playlist(values[0], values[1])
                        if not (self.worker and self.worker.is_alive()):
                            self.playlist_import_button.configure(state="normal")
                    elif kind == "playlist_error":
                        message = values[0]
                        self.playlist_rows = []
                        self.playlist_meta = {}
                        self.playlist_tree.delete(*self.playlist_tree.get_children())
                        self.playlist_info.set("导入歌单失败")
                        self.playlist_status.set("导入失败")
                        self.append_log(f"导入歌单失败：{message}")
                        messagebox.showerror(APP_TITLE, f"导入歌单失败：\n{message}")
                        if not (self.worker and self.worker.is_alive()):
                            self.playlist_import_button.configure(state="normal")
                    elif kind == "login_check_result":
                        self.apply_login_state(values[0], values[1])
                    elif kind == "login_dialog_result":
                        self.on_login_dialog_result(values[0], values[1], values[2], values[3])
                    elif kind == "download_done":
                        counts, failures, stopped = values
                        self.download_counts.set(
                            f"完成 {counts['success']}    跳过 {counts['skipped']}    失败 {counts['failed']}")
                        self.download_status.set("下载已停止" if stopped else "下载完成")
                        self.set_running(False)
                        if failures:
                            self.append_download_log(f"共 {len(failures)} 个任务最终失败：")
                            for item in failures:
                                self.append_download_log(item)
                        self.refresh_management()
                    elif kind == "done":
                        counts, failures, stopped = values
                        self.count_text.set(f"成功 {counts['success']}    跳过 {counts['skipped']}    失败 {counts['failed']}")
                        self.status.set("任务已停止" if stopped else "转换完成")
                        self.set_running(False)
                        if failures:
                            self.append_log("失败文件：")
                            for item in failures:
                                self.append_log(item)
                        self.refresh_management()
                except Exception as exc:
                    # 单个事件处理出错不能拖垮事件循环，否则界面将永久冻结在旧状态。
                    message = f"界面事件处理异常（{kind}）：{exc}"
                    try:
                        self.append_log(message)
                        self.append_download_log(message)
                    except Exception:
                        pass
        except queue.Empty:
            pass
        self.after(100, self.process_events)

    def refresh_management(self):
        if not hasattr(self, "management_tree"):
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self.scan_request_id += 1
        request_id = self.scan_request_id
        try:
            files, source_root = self.collect_files()
        except Exception:
            self.management_rows = []
            self.render_management()
            return
        output = Path(self.output_dir.get()).expanduser().resolve()
        fmt = self.format_var.get()
        self.management_status.set("正在扫描音乐文件…")
        self.scan_worker = threading.Thread(target=self.scan_files, args=(request_id, files, source_root, output, fmt), daemon=True)
        self.scan_worker.start()

    def scan_files(self, request_id: int, files: list[Path], source_root: Path | None, output: Path, fmt: str):
        rows = []
        for source in files:
            target = expected_target(source, source_root, output, fmt)
            if target.is_file():
                status = "已转换"
            elif any(candidate.is_file() for candidate in output.rglob(f"{source.stem}.{fmt}")):
                status = "目标缺失"
            else:
                status = "未转换"
            try:
                size = format_size(source.stat().st_size)
            except OSError:
                size = "未知"
            try:
                folder = str(source.parent if source_root is None else source.parent.relative_to(source_root))
            except ValueError:
                folder = str(source.parent)
            rows.append({"source": source, "target": target, "name": source.name, "folder": folder or ".", "size": size, "format": fmt.upper(), "status": status, "output": str(target)})
        self.emit("scan", request_id, rows)

    def render_management(self):
        if not hasattr(self, "management_tree"):
            return
        for item in self.management_tree.get_children():
            self.management_tree.delete(item)
        selected_filter = self.management_filter.get()
        shown = 0
        for row in self.management_rows:
            if selected_filter != "全部" and row["status"] != selected_filter:
                continue
            self.management_tree.insert("", "end", values=(row["name"], row["folder"], row["size"], row["format"], row["status"], row["output"], str(row["source"])))
            shown += 1
        self.management_status.set(f"共 {len(self.management_rows)} 个文件，当前显示 {shown} 个")

    def update_management_result(self, source: Path, target: Path, status: str, detail: str):
        for row in self.management_rows:
            if row["source"] == source:
                row["target"] = target
                row["output"] = str(target)
                row["status"] = status
                break
        self.render_management()

    def open_selected_source(self):
        selection = self.management_tree.selection()
        if not selection:
            self.open_source_folder()
            return
        values = self.management_tree.item(selection[0], "values")
        source = Path(values[6]) if len(values) > 6 else None
        if source and source.is_file():
            os.startfile(source.parent)
        else:
            self.open_source_folder()

    def open_source_folder(self):
        path = Path(self.source_dir.get())
        if path.is_dir():
            os.startfile(path)

    def append_log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def open_output(self):
        path = Path(self.output_dir.get())
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def show_tools(self):
        ncmdump = find_tool("ncmdump.exe", app_root() / "bin" / "ncmdump.exe") or find_tool("ncmdump.exe", app_root() / "_internal" / "bin" / "ncmdump.exe")
        ffmpeg = find_tool("ffmpeg.exe", app_root() / "bin" / "ffmpeg.exe") or find_tool("ffmpeg.exe", app_root() / "_internal" / "bin" / "ffmpeg.exe")
        lines = []
        for label, tool, args in (("ncmdump", ncmdump, ["--version"]), ("FFmpeg", ffmpeg, ["-version"])):
            if not tool:
                lines.append(f"{label}：未找到")
                continue
            try:
                result = subprocess.run([str(tool), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                lines.append(f"{label}：\n{result.stdout.strip()[:800]}")
            except Exception as exc:
                lines.append(f"{label}：读取失败：{exc}")
        messagebox.showinfo("工具信息", "\n\n".join(lines))

    def schedule_settings_save(self, *_):
        if self.settings_save_id is not None:
            self.after_cancel(self.settings_save_id)
        self.settings_save_id = self.after(500, self.persist_settings)

    def ensure_license_agreed(self) -> bool:
        """用户协议门：未同意协议时模态展示；同意后记录版本并放行，拒绝则退出。"""
        if self.license_agreed_version >= AGREEMENT_VERSION:
            return True
        dialog = LicenseDialog(self)
        self.wait_window(dialog.dialog)
        if not dialog.accepted:
            return False
        self.license_agreed_version = AGREEMENT_VERSION
        self.persist_settings()
        return True

    def persist_settings(self):
        if self.settings_save_id is not None:
            self.after_cancel(self.settings_save_id)
            self.settings_save_id = None
        try:
            save_settings({
                "source_dir": self.source_dir.get(),
                "output_dir": self.output_dir.get(),
                "format": self.format_var.get(),
                "recursive": self.recursive.get(),
                "download_dir": self.download_dir.get(),
                "download_format": self.download_format.get(),
                "last_playlist_url": self.playlist_url.get(),
                "theme": self.theme_var.get(),
                "license_agreed_version": self.license_agreed_version,
            })
        except (OSError, ValueError) as exc:
            self.append_log(f"无法保存设置：{exc}")

    def close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_TITLE, "任务仍在运行，确定退出吗？"):
                return
            self.stop()
        self.persist_settings()
        self._save_queue()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.withdraw()
    if app.ensure_license_agreed():
        app.deiconify()
        app.mainloop()
    else:
        app.destroy()
