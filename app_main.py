"""Music Cat 桌面应用（Qt Quick 版）入口。

旧 Tkinter 版入口仍是 music_cat_app.py；Qt 版完成全部迁移并
通过回归后（重构文档阶段 8），打包入口将切换到本文件。
"""
import sys

from app_runtime import run_application

if __name__ == "__main__":
    sys.exit(run_application())
