"""One-time developer migration for existing PCs; excluded from the app UI/build.

Normal ClipBridge setup never reads another application's settings. This helper
is retained only to migrate the original development machine, without commands.
"""
import os
from pathlib import Path
import re
import sys
from PySide6.QtCore import QSettings
from clipbridge.input_engine import SCREEN_BOOLEANS, SCREEN_MODIFIERS, defaults, migrate_identity, screen_options, validate


def default_profile():
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Deskflow" / "Deskflow.conf"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Deskflow" / "Deskflow.conf"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "Deskflow" / "Deskflow.conf"


def import_profile(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("Deskflow 설정 파일을 찾지 못했습니다.")
    source = QSettings(str(path), QSettings.Format.IniFormat)
    data = defaults()
    data["name"] = str(source.value("core/computerName", data["name"]))
    data["mode"] = "client" if int(source.value("core/coreMode", 2)) == 1 else "server"
    data["port"] = int(source.value("core/port", 24800))
    data["server_ip"] = str(source.value("client/remoteHost", "")).split(",")[0]
    data["scroll_scale"] = float(source.value("client/yScrollScale", 1.0))
    data["invert_scroll"] = source.value("client/invertYScroll", False, type=bool)
    data["relative_mouse"] = source.value("server/relativeMouseMoves", False, type=bool)
    data["switch_delay"] = int(source.value("server/switchDelay", 250)) if source.value("server/enableSwitchDelay", True, type=bool) else 0
    width = max(1, min(9, int(source.value("server/gridWidth", 5))))
    screens = []
    for index in range(1, min(81, int(source.value("internalConfig/screens/size", 0))) + 1):
        name = str(source.value(f"internalConfig/screens/{index}/name", ""))
        if name:
            screens.append({"name": name, "x": (index - 1) % width, "y": (index - 1) // width})
    data["screens"] = screens or [{"name": data["name"], "x": 1, "y": 1}]
    for screen in data["screens"]:
        options, prefix = {}, "computer_" + screen["name"] + "/"
        for key in SCREEN_BOOLEANS | SCREEN_MODIFIERS | {"switchCornerSize"}:
            if source.contains(prefix + key):
                kind = bool if key in SCREEN_BOOLEANS else int if key == "switchCornerSize" else str
                options[key] = source.value(prefix + key, type=kind)
        if options:
            screen["options"] = screen_options(options)
    roots = [path.parent]
    if sys.platform == "win32":
        roots.append(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Deskflow")
    certificate = str(source.value("security/certificate", ""))
    for root in roots:
        if not certificate and (root / "tls" / "deskflow.pem").is_file():
            certificate = str(root / "tls" / "deskflow.pem")
        for kind in ("servers", "clients"):
            database = root / "tls" / ("trusted-" + kind)
            if database.is_file():
                pins = re.findall(r"(?im)^v2:sha256:([0-9a-f]{64})\s*$", database.read_text(encoding="utf-8"))
                data["trusted_" + kind] = list(dict.fromkeys(data["trusted_" + kind] + [pin.lower() for pin in pins]))
    data["certificate"] = certificate
    migrate_identity(data)
    data["enabled"] = False
    validate(data)
    return data
