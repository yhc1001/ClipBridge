"""Build a native-architecture macOS app; run on macOS, not Windows."""
import os
import platform
import subprocess
import sys
from pathlib import Path

if sys.platform != "darwin":
    raise SystemExit("Mac 빌드는 macOS에서 실행하세요.")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
from PyInstaller.__main__ import run
run(["--noconfirm", "--clean", "--windowed", "--onedir", "--name", "ClipBridge",
     "--osx-bundle-identifier", "com.clipbridge.app", "--distpath", "dist/macos",
     "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
     "--exclude-module", "PySide6.QtPdf", "--exclude-module", "tkinter", "bootstrap.py"])
architecture = "arm64" if platform.machine() == "arm64" else "intel"
target = root / "dist" / f"ClipBridge-macOS-{architecture}.zip"
subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", "dist/macos/ClipBridge.app", str(target)], check=True)
print("Mac app built: " + target.name)
