"""Ship corresponding engine/Qt sources and rebuild instructions with binaries."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clipbridge import __version__
from prepare_input_bundle import LOCK, download

qt_sdk = "https://download.qt.io/online/qtsdkrepository/all_os/qt/qt6_6113_windows_line_endings_src/qt.qt6.6113.src/"
records = [{"name": "deskflow-1.27.0-source.tar.gz", **LOCK["source"]}]
for module in ("qtbase", "qtsvg", "qttranslations"):
    name = module + "-everywhere-src-6.11.3.zip"
    records.append({"name": name, "url": qt_sdk + "6.11.3-0-202609240252" + name})
for version in ("6.9.3", "6.12.0"):
    name = "qtbase-everywhere-src-" + version + ".tar.xz"
    records.append({"name": name, "url": "https://download.qt.io/archive/qt/" + ".".join(version.split(".")[:2]) + "/" + version + "/submodules/" + name})
records.append({"name": "pyside-setup-everywhere-src-6.12.0.tar.xz", "url": "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz"})
cache = ROOT / "dist/input-sources"
cache.mkdir(parents=True, exist_ok=True)


def retrieve(record):
    path = cache / record["name"]
    if not path.is_file():
        with urllib.request.urlopen(record["url"], timeout=120) as response, path.with_suffix(path.suffix + ".part").open("wb") as output:
            while data := response.read(1024**2):
                output.write(data)
        path.with_suffix(path.suffix + ".part").replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if record.get("sha256") and record["sha256"] != digest:
        raise ValueError("Source checksum mismatch")
    if record["name"].endswith(".zip"):
        with zipfile.ZipFile(path) as package:
            assert package.testzip() is None
    print("Corresponding source ready: " + record["name"], flush=True)
    return {**record, "sha256": digest, "bytes": path.stat().st_size}


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as workers:
        manifest = list(workers.map(retrieve, records))
    destination = ROOT / "dist" / ("v" + __version__) / "ClipBridge-input-sources.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as package:
        for record in manifest:
            package.write(cache / record["name"], "sources/" + record["name"])
        package.writestr("SOURCE-MANIFEST.json", json.dumps(manifest, indent=2))
        for name in ("docs/INPUT_COMPONENT.md", "docs/DEVELOPMENT.md", "THIRD_PARTY_NOTICES.md", "tools/prepare_input_bundle.py", "tools/build_exe.py", "tools/build_macos.py", "tools/build_linux.py", "assets/input-engine-lock.json", ".github/workflows/build-linux.yml"):
            package.write(ROOT / name, name)
        package.writestr("README.txt", "ClipBridge input component corresponding sources and rebuild scripts.\nDeskflow engine is 1.27.0. For Linux X11, two pkg_check_modules REQUIRED flags and the unconditional WINAPI_LIBEI/WINAPI_LIBPORTAL definitions are removed as documented in tools/prepare_input_bundle.py.\nQt 6.11.3 sources have Windows line endings; normalize shell script line endings when building on Unix. Qt/PySide are shared libraries and may be replaced/rebuilt with compatible modified versions.\nNo personal settings, certificates or files are included.\n")
    print("Input component source archive created", flush=True)
