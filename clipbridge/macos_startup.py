import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.clipbridge.login"


def startup_arguments():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--background"]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), "--background"]


def set_autostart(enabled: bool):
    directory = Path.home() / "Library" / "LaunchAgents"
    path = directory / (LABEL + ".plist")
    domain = f"gui/{os.getuid()}"
    if not enabled:
        subprocess.run(["/bin/launchctl", "disable", domain + "/" + LABEL], capture_output=True, check=False)
        path.unlink(missing_ok=True)
        return
    directory.mkdir(parents=True, exist_ok=True)
    value = {"Label": LABEL, "ProgramArguments": startup_arguments(), "RunAtLoad": True,
             "LimitLoadToSessionType": "Aqua", "ProcessType": "Interactive"}
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(plistlib.dumps(value))
    temporary.chmod(0o600)
    os.replace(temporary, path)
    subprocess.run(["/bin/launchctl", "enable", domain + "/" + LABEL], capture_output=True, check=False)
