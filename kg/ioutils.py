"""控制台输出编码处理 —— Windows 下管道/重定向时的中文保护。"""

from __future__ import annotations

import sys


def setup_stdout():
    """管道/重定向时用 UTF-8 输出，避免 Windows 代码页把中文打成乱码。

    真实控制台（isatty）不处理：Python 3.6+ 在 Windows 控制台上走 WriteConsoleW。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
