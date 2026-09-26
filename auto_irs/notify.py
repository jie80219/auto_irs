"""macOS 系統通知。"""

from __future__ import annotations

import subprocess
import sys


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str, sound: str = "Glass") -> None:
    print(f"[{title}] {message}")
    if sys.platform != "darwin":
        return
    script = f'display notification "{_escape(message)}" with title "{_escape(title)}" sound name "{sound}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
