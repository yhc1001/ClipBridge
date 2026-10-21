"""Desktop-session autostart; never starts a system service or shell."""
import os
from pathlib import Path
import sys


def desktop_quote(value):
    if any(c in value for c in "\n\r\0"):
        raise ValueError("Invalid desktop argument")
    value = value.replace("%", "%%")
    for char in ('\\', '"', '`', '$'):
        value = value.replace(char, "\\" + char)
    return '"' + value + '"'


def set_autostart(enabled):
    directory = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "autostart"
    path = directory / "clipbridge.desktop"
    if path.is_symlink():
        raise ValueError("Unsafe autostart path")
    if not enabled:
        path.unlink(missing_ok=True)
        return
    directory.mkdir(parents=True, exist_ok=True)
    args = [sys.executable]
    if not getattr(sys, "frozen", False):
        args.append(str(Path(__file__).resolve().parents[1] / "main.py"))
    args.append("--background")
    content = "[Desktop Entry]\nType=Application\nName=ClipBridge\nTerminal=false\nX-GNOME-Autostart-enabled=true\nExec=" + " ".join(map(desktop_quote, args)) + "\n"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
