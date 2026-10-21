import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="ClipBridge-linux-smoke-") as directory:
    path = Path(directory).resolve()
    diagnostic = path / "startup.txt"
    environment = dict(os.environ, CLIPBRIDGE_TEST_DATA=str(path / "data"), CLIPBRIDGE_SMOKE_INSTANCE=str(uuid.uuid4()),
        CLIPBRIDGE_STARTUP_DIAGNOSTIC=str(diagnostic), XDG_DATA_HOME=str(path / "data-home"), XDG_CONFIG_HOME=str(path / "config-home"))
    executable = root / "dist" / "linux" / "ClipBridge" / "ClipBridge"
    result = subprocess.run([str(executable), "--smoke-test"], env=environment, timeout=40)
    if result.returncode:
        raise RuntimeError(diagnostic.read_text() if diagnostic.exists() else "Linux app failed")
    settings = json.loads((path / "data" / "settings.json").read_text())
    assert settings["file_policy"] == "allow" and settings["file_limit_mb"] == 16384
    assert not list((path / "data" / "transfers").iterdir())
    print("Packaged Linux app native clipboard, encrypted settings, clean exit: PASS")
