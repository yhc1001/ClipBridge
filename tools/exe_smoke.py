"""Launch the packaged EXE with isolated settings and require clean exit."""
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from clipbridge.config import ConfigStore
from clipbridge import __version__


def check(directory, mode):
    if mode == "legacy":
        store = ConfigStore(Path(directory) / "ClipBridge")
        config = store.load()
        config.file_policy = "ask"
        store.save(config)
        old = json.loads(store.path.read_text(encoding="utf-8"))
        del old["file_policy_version"]
        del old["limits_version"]
        old.update(clip_limit_mb=96, file_limit_mb=512)
        store.path.write_text(json.dumps(old), encoding="utf-8")
    diagnostic = Path(directory) / "startup-diagnostic.txt"
    environment = dict(os.environ, LOCALAPPDATA=directory, CLIPBRIDGE_STARTUP_DIAGNOSTIC=str(diagnostic), CLIPBRIDGE_SMOKE_INSTANCE=str(uuid.uuid4()))
    start = time.perf_counter()
    executable = root / "dist" / ("v" + __version__) / "ClipBridge.exe"
    result = subprocess.run([str(executable), "--smoke-test"], env=environment, timeout=40)
    elapsed = time.perf_counter() - start
    if result.returncode:
        raise RuntimeError(diagnostic.read_text(encoding="utf-8") if diagnostic.exists() else "EXE startup failed")
    config = json.loads((Path(directory) / "ClipBridge" / "settings.json").read_text(encoding="utf-8"))
    assert config["peer_ip"] == "" and config["port"] == 45832
    assert config["protected_secret"] and config["protected_key"]
    assert config["file_policy"] == "allow" and config["file_policy_version"] == 1
    assert config["clip_limit_mb"] == 256 and config["file_limit_mb"] == 16384
    assert not list((Path(directory) / "ClipBridge" / "transfers").iterdir())
    print(f"Packaged EXE {mode} settings / automatic files / native listener / tray / clean shutdown: PASS ({elapsed:.2f}s including 1.8s timer)")


for mode in ("fresh", "legacy"):
    with tempfile.TemporaryDirectory(prefix="ClipBridge-exe-test-") as directory:
        check(directory, mode)
