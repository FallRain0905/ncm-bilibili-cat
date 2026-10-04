# GUI 重构基线（GUI_REFACTOR_BASELINE）

> 重构执行依据：`GUI现代化一次性重构实施文档.md`（PySide6 + Qt Quick/QML，目标 2.0）
> 基线日期：2026-10-05　基线版本：1.2.0（Tk 版已发布）
> 原则：**在 Qt 版通过全部回归并完成打包验收之前，Tk 版（music_cat_app.py）仍是正式入口与安装包来源。**

## 1. 测试基线

- 全量测试：**124 项全部通过**（Tk/业务 118 项 + Qt 外壳 6 项）。
  - test_ncm_settings（20）、test_download（24）、test_netease（16+5=21 中含 FetchSongUrl 5 项）、
    test_netease_login（18）、test_musiccat_v4（含 QueueStore/EngineRetry/EventLoop/LicenseGate/LoginDialog）、
    test_netease_qrlogin（13）、test_qt_shell（6）。
- 1.2.0 新增能力（重构必须保留，不得回退）：
  - **扫码登录**（`netease_qrlogin` + 登录对话框扫码模式，Canvas 渲染二维码 + 轮询 + MUSIC_U 提取）。
  - 首启协议门（Tk 与 Qt 双实现，`license_agreed_version` 共享）。
  - 下载可见性（download_log、任务详情、下载中状态、忙时反馈、引擎崩溃兜底、事件循环逐事件保护）。

## 2. 环境

- Python 3.12.10；PyInstaller 6.x；PySide6 6.11.2（已验证 QML 离屏/实机均可启动）。
- Qt Quick Controls 样式：**Basic**（`QT_QUICK_CONTROLS_STYLE=Basic`，视觉完全由项目调色板控制）。
- qrcode 7.x/8.x（纯 Python，`get_matrix()` 渲染到 Tk Canvas 或 QML Canvas）。

## 3. 公共模块（Qt/Tk 共用，不复制业务逻辑）

| 模块 | 职责 | 迁移说明 |
|---|---|---|
| `app_info.py`（新） | 标题/版本/GITHUB/协议文本/免责声明 | 从 music_cat_app 抽出，两端共用 |
| `netease_client.py` | 歌单/详情/取址/下载/DPAPI Cookie 头 | 原样复用；Qt 侧由 PlaylistController/LoginController 包装 |
| `netease_qrlogin.py` | 扫码登录 unikey/轮询/MUSIC_U 提取 | 原样复用（1.2.0 新增） |
| `download_engine.py` / `bilibili_downloader.py` | 下载引擎 | 原样复用；事件 → Qt 信号在 DownloadController 适配 |
| `ncm_settings.py` | 设置白名单/迁移/原子保存；DPAPI 目录 | 原样复用 |
| `credential_store.py` | DPAPI 凭据 | 原样复用；Qt 侧绝不接触明文 |
| `download_history.py` / `download_queue.py` | 历史/队列 | 原样复用；queue.json、library.sqlite3 格式不变 |
| `converter_engine`（music_cat_app 内） | NCM 转换 | 阶段 3 抽出为独立服务模块后再接入 Qt |

## 4. Tk → Qt 映射与迁移清单

| Tk 现状 | Qt 目标 | 阶段 |
|---|---|---|
| `App.__init__` 启动流程/设置恢复 | `app_runtime.run_application` + 各控制器 | 1-2（外壳已完成） |
| Notebook 四页 + 底部免责声明 | 侧边栏六页 + AppHeader + DisclaimerBar | 1（已完成骨架） |
| 首启协议 LicenseDialog(Tk) | LicenseOverlay.qml（主窗口可见+模态覆盖层） | 1（已完成） |
| 转换页（ConverterEngine 事件队列） | ConversionController + ConvertPage.qml + FileDropZone | 3 |
| 音乐管理（扫描/筛选/拖放/历史合并） | ManagementController + MusicTableModel | 4 |
| 下载页（Bilibili+队列+日志+重试） | DownloadController + DownloadTaskModel | 5 |
| 歌单页（导入/筛选/加入队列）+ 登录对话框（扫码+粘贴） | PlaylistController + LoginDialog.qml | 6 |
| 主题 dark/light（ttkbootstrap 自定义主题） | App 调色板属性 + Theme.qml 结构令牌 | 1（已完成） |
| NCMConverter.spec / build_app.ps1 / build_installer.ps1 | 增补 PySide6/QML 资源与检查；入口切 app_main.py | 8 |

## 5. 阶段 1 已交付（本次）

- `app_main.py`、`app_runtime.py`（Basic 样式、HiDPI、图标、资源根解析）。
- `qt_bridge/app_controller.py`：导航、侧边栏折叠、深浅主题（持久化）、协议门（持久化）、调色板属性、Toast 信号。
- `qml/`：Main 外壳、Theme 单例、AppSidebar/AppHeader/PageHeader/EmptyState/LicenseOverlay/ToastHost、六个页面骨架（Dashboard 快捷入口 + 其余页空状态说明）。
- `test_qt_shell.py`：6 项（离屏加载、六页存在、导航/主题持久化、协议门、调色板切换）。
- 实机验证：Windows 真实窗口启动正常（标题 Music Cat v1.2.0）。

## 6. 剩余风险与下一阶段入口

- 风险 1：PyInstaller 打包 QML/Qt 插件清单（阶段 8 才做），当前源码运行验证充分、打包路径未验证。
- 风险 2：转换引擎仍内嵌于 music_cat_app.py，阶段 3 前需抽出为独立模块（不复制、不回归）。
- 风险 3：Tk 与 Qt 共享 settings.json / queue.json / library.sqlite3，两侧写入格式必须保持白名单兼容（已由 ncm_settings 保证）。
- 下一阶段（阶段 2）：`qt_bridge/workers.py`（BaseWorker/QThread）、`qt_bridge/models.py`、各控制器最小实现与 UI 无关测试。
