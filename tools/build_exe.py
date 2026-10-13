"""Build with a clean DLL search path, independent of the host application's PATH."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
system = Path(os.environ["SystemRoot"])
# Native tools (e.g. Poppler/Conda) sometimes export an incompatible icuuc.dll.
# Qt uses Windows' ICU. Do not accidentally package unrelated PATH libraries.
os.environ["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), sys.base_prefix, str(system / "System32"), str(system)])

from PyInstaller.__main__ import run

run(["--noconfirm", "--clean", "--onefile", "--windowed", "--name", "ClipBridge", "--distpath", "dist/v1.1.0",
     "--icon", "assets/clipbridge.ico", "--version-file", "assets/version_info.txt",
     "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
     "--exclude-module", "PySide6.QtPdf", "--exclude-module", "tkinter", "bootstrap.py"])
