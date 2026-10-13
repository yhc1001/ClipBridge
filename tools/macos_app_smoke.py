import os
from pathlib import Path
import subprocess
import tempfile
import uuid

root = Path(__file__).resolve().parents[1]
scope = str(uuid.uuid4())
with tempfile.TemporaryDirectory(prefix="ClipBridge-mac-smoke-") as directory:
    path = Path(directory).resolve()  # macOS /var is a system symlink to /private/var.
    diagnostic = path / "startup.txt"
    environment = dict(os.environ, CLIPBRIDGE_TEST_DATA=str(path / "data"), CLIPBRIDGE_SMOKE_INSTANCE=scope,
                       CLIPBRIDGE_STARTUP_DIAGNOSTIC=str(diagnostic), QT_QPA_PLATFORM="offscreen")
    executable = root / "dist" / "macos" / "ClipBridge.app" / "Contents" / "MacOS" / "ClipBridge"
    result = subprocess.run([str(executable), "--smoke-test"], env=environment, timeout=40)
    if result.returncode:
        raise RuntimeError(diagnostic.read_text() if diagnostic.exists() else "macOS app failed")
    assert (path / "data" / "settings.json").exists()
    print("Packaged macOS .app startup, native pasteboard, Keychain and clean exit: PASS")
import Security as S
S.SecItemDelete({S.kSecClass: S.kSecClassGenericPassword, S.kSecAttrService: "ClipBridge.test." + scope, S.kSecAttrAccount: "local-settings-key-v1"})
