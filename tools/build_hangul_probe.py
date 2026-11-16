"""Build the opt-in diagnostic without unrelated DLLs from the host PATH."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
system = Path(os.environ["SystemRoot"])
os.environ["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), sys.base_prefix, str(system / "System32"), str(system)])

from PyInstaller.__main__ import run

run(["--noconfirm", "--clean", "--onefile", "--windowed", "--name", "ClipBridge-Hangul-Check",
     "--distpath", "dist/hangul-diagnostic", "--workpath", "build/hangul-diagnostic", "--specpath", "build/hangul-diagnostic",
     "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
     "--exclude-module", "PySide6.QtPdf", "tools/hangul_key_probe.py"])
