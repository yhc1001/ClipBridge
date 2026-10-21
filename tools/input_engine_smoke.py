"""Probe installed Deskflow CLI in a private profile, without starting input hooks."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from PySide6.QtCore import QCoreApplication
from clipbridge.config import ConfigStore
from clipbridge.input_engine import default_profile, defaults, find_engine, import_profile, prepare_profile

application = QCoreApplication([])
engine = find_engine()
if not engine:
    raise SystemExit("No installed native Deskflow core; input integration remains unverified")
original = default_profile()
digest = hashlib.sha256(original.read_bytes()).digest() if original.is_file() else None
with tempfile.TemporaryDirectory(prefix="ClipBridge-input-probe-") as temporary:
    directory = Path(temporary)
    config = ConfigStore(directory / "data").load()
    settings = import_profile(original) if original.is_file() else defaults()
    settings["engine"] = engine
    program, arguments, environment = prepare_profile(config, settings, directory / "runtime")
    env = {key: environment.value(key) for key in environment.keys()}
    result = subprocess.run([program, "--version"], env=env, capture_output=True, timeout=15, check=True)
    version = result.stdout.decode("utf-8", errors="replace")
    assert "1.27" in version, "This validation records Deskflow 1.27 only"
    assert "--settings" in arguments
    assert not digest or hashlib.sha256(original.read_bytes()).digest() == digest
    print("Installed Deskflow 1.27: private portable profile, CLI dependencies, existing profile preservation: PASS")
print("Private input profile and temporary identity removed: PASS; mouse/keyboard hooks were not started")
