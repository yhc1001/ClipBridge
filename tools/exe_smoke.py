"""Launch the packaged EXE with isolated settings and require clean exit."""
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="ClipBridge-exe-test-") as directory:
    diagnostic = Path(directory) / "startup-diagnostic.txt"
    environment = dict(os.environ, LOCALAPPDATA=directory, CLIPBRIDGE_STARTUP_DIAGNOSTIC=str(diagnostic), CLIPBRIDGE_SMOKE_INSTANCE=str(uuid.uuid4()))
    start = time.perf_counter()
    executable = root / "dist" / "v1.1.0" / "ClipBridge.exe"
    result = subprocess.run([str(executable), "--smoke-test"], env=environment, timeout=40)
    elapsed = time.perf_counter() - start
    if result.returncode:
        raise RuntimeError(diagnostic.read_text(encoding="utf-8") if diagnostic.exists() else "EXE startup failed")
    config = json.loads((Path(directory) / "ClipBridge" / "settings.json").read_text(encoding="utf-8"))
    assert config["peer_ip"] == "" and config["port"] == 45832
    assert config["protected_secret"] and config["protected_key"]
    assert not list((Path(directory) / "ClipBridge" / "transfers").iterdir())
    print(f"Packaged EXE startup / native listener / tray / clean shutdown: PASS ({elapsed:.2f}s including 1.8s timer)")
