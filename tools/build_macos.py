"""Build a native-architecture macOS app; run on macOS, not Windows."""
import os
import platform
import plistlib
import subprocess
import sys
from pathlib import Path

if sys.platform != "darwin":
    raise SystemExit("Mac 빌드는 macOS에서 실행하세요.")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
from PyInstaller.__main__ import run
extra = []
if platform.machine() == "x86_64":
    # Intel cryptography is built from source against Homebrew OpenSSL. Python
    # ships another libssl.3; flattening both can select the incompatible older DLL.
    prefix = subprocess.check_output(["brew", "--prefix", "openssl@3"], text=True).strip()
    for name in ("libssl.3.dylib", "libcrypto.3.dylib"):
        library = Path(prefix) / "lib" / name
        if not library.exists():
            raise RuntimeError("OpenSSL build dependency missing: " + name)
        extra += ["--add-binary", str(library) + ":."]
run(["--noconfirm", "--clean", "--windowed", "--onedir", "--name", "ClipBridge",
     "--osx-bundle-identifier", "com.clipbridge.app", "--distpath", "dist/macos",
     "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
     "--exclude-module", "PySide6.QtPdf", "--exclude-module", "tkinter", *extra, "bootstrap.py"])
bundle = root / "dist" / "macos" / "ClipBridge.app"
info = bundle / "Contents" / "Info.plist"
value = plistlib.loads(info.read_bytes())
value.update({"CFBundleShortVersionString": "1.2.0", "CFBundleVersion": "1.2.0", "LSUIElement": True,
              "NSPasteboardUsageDescription": "복사한 내용을 연결한 컴퓨터와 공유합니다."})
info.write_bytes(plistlib.dumps(value))
subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=True)
subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
architecture = "arm64" if platform.machine() == "arm64" else "intel"
target = root / "dist" / f"ClipBridge-macOS-{architecture}.zip"
subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", "dist/macos/ClipBridge.app", str(target)], check=True)
print("Mac app built: " + target.name)
