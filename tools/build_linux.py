"""Build a native Linux directory bundle (X11 clipboard backend)."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

if not sys.platform.startswith("linux"):
    raise SystemExit("Build this bundle on Linux")
root = Path(__file__).resolve().parents[1]
os.chdir(root)
from PyInstaller.__main__ import run
run(["--noconfirm", "--clean", "--onedir", "--windowed", "--name", "ClipBridge", "--distpath", "dist/linux",
    "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtPdf", "--exclude-module", "tkinter", "bootstrap.py"])
directory = root / "dist" / "linux" / "ClipBridge"
shutil.copyfile(root / "README.md", directory / "README.md")
shutil.copytree(root / "docs", directory / "docs", dirs_exist_ok=True)
shutil.copytree(root / "licenses", directory / "licenses", dirs_exist_ok=True)
shutil.copyfile(root / "THIRD_PARTY_NOTICES.md", directory / "THIRD_PARTY_NOTICES.md")
name = "ClipBridge-linux-x86_64.tar.gz" if __import__("platform").machine() == "x86_64" else "ClipBridge-linux-arm64.tar.gz"
with tarfile.open(root / "dist" / name, "w:gz") as archive:
    archive.add(directory, arcname="ClipBridge")
print("Built " + name)
