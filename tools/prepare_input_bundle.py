"""Prepare a pinned, self-contained input component; no system Deskflow install.

Build-time network access only. Runtime code never downloads executables.
Windows/macOS use official portable artifacts; Linux builds the same source for
Ubuntu 24.04 X11 with the documented two-line optional-Wayland patch.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "assets/input-engine-lock.json").read_text(encoding="utf-8"))
DESTINATION = ROOT / "vendor/input-engine"
CACHE = ROOT / "dist/input-downloads"


def download(record, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        request = urllib.request.Request(record["url"], headers={"User-Agent": "ClipBridge-build"})
        with urllib.request.urlopen(request, timeout=120) as response:
            path.write_bytes(response.read())
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise RuntimeError("Input component checksum mismatch: " + name)
    return path


def engine_source():
    archive = download(LOCK["source"], "deskflow-1.27.0-source.tar.gz")
    directory = ROOT / "build/input-source"
    if not (directory / "CMakeLists.txt").exists():
        directory.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as package:
            prefix = package.getmembers()[0].name.split("/")[0] + "/"
            for entry in package:
                if not entry.name.startswith(prefix) or entry.name == prefix:
                    continue
                entry.name = entry.name[len(prefix):]
                package.extract(entry, directory, filter="data")
    return directory


def windows_bundle():
    archive = download(LOCK["windows-x64"], "deskflow-win-x64.zip")
    with zipfile.ZipFile(archive) as package:
        for name in package.namelist():
            relative = Path(*Path(name).parts[1:])
            # Only the core and its runtime, no Deskflow GUI/daemon/settings.
            allowed = (len(relative.parts) == 1 and (relative.suffix.lower() == ".dll" or relative.name == "deskflow-core.exe"))
            allowed |= len(relative.parts) > 1 and relative.parts[:2] in (("plugins", "platforms"), ("plugins", "styles"), ("plugins", "tls"), ("plugins", "networkinformation"))
            if not allowed or name.endswith("/") or relative.name == "Qt6Svg.dll":
                continue
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe upstream path")
            target = DESTINATION / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(name))
    return "deskflow-core.exe"


def macos_bundle():
    architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
    image = download(LOCK["macos-" + architecture], "deskflow-" + architecture + ".dmg")
    with tempfile.TemporaryDirectory(prefix="ClipBridge-mount-") as temporary:
        mount = Path(temporary).resolve() / "volume"
        mount.mkdir()
        subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(image)],
            input="Y\n", text=True, timeout=60, check=True)
        try:
            applications = list(mount.glob("*.app"))
            if len(applications) != 1:
                raise RuntimeError("Unexpected upstream app bundle")
            shutil.copytree(applications[0], DESTINATION / "Deskflow.app", symlinks=True)
        finally:
            subprocess.run(["hdiutil", "detach", "-quiet", str(mount)], check=True)
    return "Deskflow.app/Contents/MacOS/deskflow-core"


def linux_bundle(source):
    cmake = source / "src/lib/platform/CMakeLists.txt"
    original = cmake.read_text(encoding="utf-8")
    patched = original.replace("pkg_check_modules(LIBEI REQUIRED QUIET", "pkg_check_modules(LIBEI QUIET").replace("pkg_check_modules(LIBPORTAL REQUIRED QUIET", "pkg_check_modules(LIBPORTAL QUIET")
    patched = patched.replace("target_compile_definitions(platform PUBLIC WINAPI_LIBEI WINAPI_LIBPORTAL)", "# ClipBridge X11-only build: Wayland compile definitions disabled")
    cmake.write_text(patched, encoding="utf-8")
    build = ROOT / "build/input-linux"
    subprocess.run(["cmake", "-S", str(source), "-B", str(build), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_TESTS=OFF", "-DBUILD_INSTALLER=OFF", "-DBUILD_X11_SUPPORT=ON", "-DCMAKE_DISABLE_FIND_PACKAGE_Git=ON"], check=True)
    subprocess.run(["cmake", "--build", str(build), "--target", "deskflow-core", "--parallel", "3"], check=True)
    executable = build / "bin/deskflow-core"
    shutil.copy2(executable, DESTINATION / "deskflow-core")
    libraries = DESTINATION / "lib"
    libraries.mkdir()
    initial = subprocess.check_output(["ldd", str(executable)], text=True)
    qt_core = re.search(r"libQt6Core\.so\.6\s+=>\s+(/[^\s]+)", initial)
    if not qt_core:
        raise RuntimeError("Qt runtime not found")
    plugin_root = Path(qt_core[1]).parent.parent / "plugins"
    for category in ("platforms",):
        source_plugins = plugin_root / category
        if source_plugins.is_dir():
            target_plugins = DESTINATION / "plugins" / category
            target_plugins.mkdir(parents=True)
            for name in ("libqxcb.so", "libqoffscreen.so", "libqminimal.so"):
                shutil.copy2(source_plugins / name, target_plugins / name)
    # Bundle native runtime dependencies except the standard OS ABI libraries.
    base = re.compile(r"^(lib(c|m|dl|pthread|rt|resolv|util|stdc\+\+|gcc_s)\.so|ld-linux)")
    pending, seen = [executable, *(DESTINATION / "plugins").rglob("*.so")], set()
    while pending:
        library = pending.pop()
        listing = subprocess.check_output(["ldd", str(library)], text=True)
        if "not found" in listing:
            raise RuntimeError("Unresolved native input dependency: " + listing)
        for full in re.findall(r"=>\s+(/[^\s]+)", listing):
            path = Path(full)
            if path.name in seen or base.match(path.name):
                continue
            seen.add(path.name)
            shutil.copy2(path, libraries / path.name, follow_symlinks=True)
            pending.append(path)
    return "deskflow-core"


def prepare():
    marker = DESTINATION / "bundle.json"
    target = "windows-x64" if sys.platform == "win32" else "macos-" + platform.machine() if sys.platform == "darwin" else "linux-x86_64"
    if marker.is_file():
        metadata = json.loads(marker.read_text())
        if metadata["platform"] == target and all((DESTINATION / name).is_file() and hashlib.sha256((DESTINATION / name).read_bytes()).hexdigest() == digest for name, digest in metadata["hashes"].items()):
            return DESTINATION
        raise RuntimeError("Existing input component is inconsistent; use a fresh build checkout")
    DESTINATION.mkdir(parents=True, exist_ok=True)
    source = engine_source()
    executable = windows_bundle() if sys.platform == "win32" else macos_bundle() if sys.platform == "darwin" else linux_bundle(source)
    for name, destination in (("LICENSE", "DESKFLOW-LICENSE.txt"), ("LICENSES/LicenseRef-OpenSSL-Exception.txt", "DESKFLOW-OPENSSL-EXCEPTION.txt")):
        shutil.copyfile(source / name, DESTINATION / destination)
    shutil.copyfile(ROOT / "docs/INPUT_COMPONENT.md", DESTINATION / "INPUT_COMPONENT.md")
    hashes = {path.relative_to(DESTINATION).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(DESTINATION.rglob("*")) if path.is_file() and not path.is_symlink()}
    marker.write_text(json.dumps({"version": LOCK["version"], "platform": target, "executable": executable,
        "source": LOCK["source"], "hashes": hashes}, indent=2), encoding="utf-8")
    print("Self-contained input component ready: " + target, flush=True)
    return DESTINATION


if __name__ == "__main__":
    prepare()
