"""Set (and read) the macOS desktop wallpaper via AppleScript."""
from __future__ import annotations

import os
import subprocess


class WallpaperError(RuntimeError):
    pass


def _osascript(script: str) -> str:
    try:
        out = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=20)
    except FileNotFoundError as e:
        raise WallpaperError("osascript not found (are you on macOS?)") from e
    if out.returncode != 0:
        raise WallpaperError(out.stderr.strip() or "osascript failed")
    return out.stdout.strip()


def current_wallpaper() -> str:
    """POSIX path of the current desktop picture."""
    return _osascript('tell application "System Events" to get picture of current desktop')


def set_wallpaper(path: str) -> None:
    """Set the given image as the wallpaper on every desktop/space."""
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(p):
        raise WallpaperError(f"image not found: {p}")
    # Launch System Events first (avoids a -600 "not running" race), then set
    # on every desktop. POSIX file avoids quoting issues with spaces in paths.
    _osascript(
        'tell application "System Events"\n'
        '    launch\n'
        f'    set picture of every desktop to POSIX file {_as_applescript_string(p)}\n'
        'end tell'
    )


def _as_applescript_string(s: str) -> str:
    """Quote a Python string as an AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


if __name__ == "__main__":
    print("current wallpaper:", current_wallpaper())
