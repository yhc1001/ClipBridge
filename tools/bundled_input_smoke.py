"""Probe the shipped engine with system Deskflow discovery disabled."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from clipbridge import __version__

if sys.platform == "win32":
    executable = root / "dist" / ("v" + __version__) / "ClipBridge.exe"
elif sys.platform == "darwin":
    executable = root / "dist/macos/ClipBridge.app/Contents/MacOS/ClipBridge"
else:
    executable = root / "dist/linux/ClipBridge/ClipBridge"
with tempfile.TemporaryDirectory(prefix="ClipBridge-bundled-input-") as temporary:
    directory = Path(temporary).resolve()
    scope = str(uuid.uuid4())
    environment = dict(os.environ, CLIPBRIDGE_TEST_DATA=str(directory / "data"), CLIPBRIDGE_SMOKE_INSTANCE=scope,
        CLIPBRIDGE_STARTUP_DIAGNOSTIC=str(directory / "error.txt"), ProgramFiles=str(directory / "no-installed-programs"))
    result = subprocess.run([str(executable), "--smoke-test", "--input-probe"], env=environment, timeout=40)
    if result.returncode:
        raise RuntimeError((directory / "error.txt").read_text() if (directory / "error.txt").exists() else "Bundled engine probe failed")
    probe = json.loads((directory / "data/input-probe.json").read_text())
    assert probe["bundled"] and probe["version"] == "1.27.0" and probe["private_profile_cleaned"]
    print("Packaged input engine without system Deskflow: dependencies, version, isolated profile and cleanup PASS")
if sys.platform == "darwin":
    import Security as S
    S.SecItemDelete({S.kSecClass: S.kSecClassGenericPassword, S.kSecAttrService: "ClipBridge.test." + scope, S.kSecAttrAccount: "local-settings-key-v1"})
