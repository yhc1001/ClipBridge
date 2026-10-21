"""Resolve the shipped input runtime without consulting installed applications."""
import hashlib
import json
from pathlib import Path
import sys


def bundle_directory():
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).parent.parent / "Resources" if sys.platform == "darwin" else Path(sys._MEIPASS)
        return root / "input-engine"
    return Path(__file__).resolve().parents[1] / "vendor/input-engine"


def bundled_engine():
    directory = bundle_directory()
    manifest = directory / "bundle.json"
    if not manifest.is_file():
        return ""
    value = json.loads(manifest.read_text(encoding="utf-8"))
    relative = Path(value["executable"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid input bundle path")
    executable = directory / relative
    if not executable.is_file() or hashlib.sha256(executable.read_bytes()).hexdigest() != value["hashes"].get(relative.as_posix()):
        raise ValueError("내장 마우스 구성 요소가 손상됐습니다. ClipBridge를 다시 받아 실행하세요.")
    return str(executable.absolute())
