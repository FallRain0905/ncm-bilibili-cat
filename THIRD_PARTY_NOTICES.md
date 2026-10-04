# 第三方组件与许可证声明

本应用（NCM 转换器）分发包中包含以下第三方组件。各组件为独立程序或独立库，通过进程调用或以独立库形式使用。

## 随包分发的外部程序

### FFmpeg（ffmpeg.exe / ffprobe.exe）

- 版本：9.0.2 essentials build（www.gyan.dev）
- 许可证：GPL v3（构建启用了 GPL 组件）
- 用途：音频转码（MP3/M4A/FLAC）与格式探测
- 说明：本应用通过独立进程调用 FFmpeg，二者属于独立程序聚合分发。FFmpeg 的源代码可在其官方站点获取：<https://ffmpeg.org/download.html>，构建来源：<https://www.gyan.dev/ffmpeg/builds/>
- 源代码对应：FFmpeg 为开源软件，上述站点提供完整源代码及构建脚本。

### ncmdump（ncmdump.exe）

- 许可证：MIT License
- 用途：解码网易云 `.ncm` 加密音频为 FLAC
- 来源：<https://github.com/taurusxin/ncmdump>

## 打包的 Python 库

| 组件 | 版本范围 | 许可证 | 用途 |
| --- | --- | --- | --- |
| yt-dlp | ≥2026.8.19 | Unlicense | Bilibili 视频信息获取与音频下载 |
| ttkbootstrap | ≥1.10 | MIT | 现代主题界面 |
| tkinterdnd2 | ≥0.4 | MIT | Windows 文件拖放（含 tkdnd 扩展，BSD 风格许可） |
| pycryptodome | ≥3.x | BSD / Public Domain | 供 yt-dlp 使用的加密后端 |

各 Python 库随应用一起分发，其源代码可在 PyPI 对应项目页获取：

- <https://pypi.org/project/yt-dlp/>
- <https://pypi.org/project/ttkbootstrap/>
- <https://pypi.org/project/tkinterdnd2/>
- <https://pypi.org/project/pycryptodome/>

## 应用自身

本应用代码由项目作者提供，随安装包分发。应用不包含、不收集任何用户凭据；网易云登录凭据仅保存在本机并经 Windows DPAPI 加密。

## 使用限制

本应用仅用于处理用户有权访问的内容。使用者须遵守 Bilibili、网易云音乐的平台条款及著作权法。应用不提供任何绕过付费、会员、地区或访问限制的功能。
