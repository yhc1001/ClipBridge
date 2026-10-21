"""Create reproducible source/portable bundles without settings or clipboard data."""
import hashlib
import importlib.metadata as metadata
import json
import shutil
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from clipbridge import __version__
dist = root / "dist" / ("v" + __version__)
dist.mkdir(parents=True, exist_ok=True)
licenses = root / "licenses"
licenses.mkdir(exist_ok=True)
components = []
for name in ("PySide6", "PySide6_Essentials", "shiboken6", "pywin32", "Pillow", "cryptography", "pyinstaller", "psutil"):
    package = metadata.distribution(name)
    components.append({"name": name, "version": package.version, "license": package.metadata.get("License-Expression") or package.metadata.get("License")})
    for entry in package.files or []:
        parts = Path(str(entry)).parts
        if "licenses" in parts or Path(str(entry)).name.upper().startswith(("LICENSE", "COPYING")):
            source = Path(package.locate_file(entry))
            if source.is_file():
                target = licenses / name / Path(str(entry)).name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
python_license = Path(__import__("sys").base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copyfile(python_license, licenses / "Python-LICENSE.txt")
(licenses / "components.json").write_text(json.dumps(components, indent=2, ensure_ascii=False), encoding="utf-8")

source_files = [root / name for name in ("main.py", "bootstrap.py", "build.ps1", "build-macos.sh", "Configure-Firewall.ps1", "requirements.txt", "requirements-lock.txt", "README.md", "RELEASE_NOTES.md", "THIRD_PARTY_NOTICES.md", ".gitignore", ".gitattributes")]
for directory in ("clipbridge", "tests", "tools", "assets", "licenses", "artifacts", "docs", ".github"):
    source_files += [path for path in (root / directory).rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"]
with zipfile.ZipFile(dist / "ClipBridge-source.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(source_files):
        archive.write(path, str(path.relative_to(root)))
with zipfile.ZipFile(dist / "ClipBridge-portable.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.write(dist / "ClipBridge.exe", "ClipBridge.exe")
    for name in ("README.md", "Configure-Firewall.ps1", "THIRD_PARTY_NOTICES.md"):
        archive.write(root / name, name)
    for path in licenses.rglob("*"):
        if path.is_file():
            archive.write(path, str(path.relative_to(root)))
    for path in (root / "docs").rglob("*.md"):
        archive.write(path, str(path.relative_to(root)))
    for path in (root / "artifacts").glob("*.json"):
        archive.write(path, str(path.relative_to(root)))
with (dist / "SHA256SUMS.txt").open("w", encoding="ascii") as output:
    for name in ("ClipBridge.exe", "ClipBridge-source.zip", "ClipBridge-portable.zip", "ClipBridge-macOS-arm64.zip", "ClipBridge-macOS-intel.zip", "ClipBridge-linux-x86_64.tar.gz", "ClipBridge-input-sources.zip"):
        if not (dist / name).exists():
            continue
        digest = hashlib.sha256((dist / name).read_bytes()).hexdigest()
        output.write(f"{digest}  {name}\n")
print("Release bundles: source ZIP, portable ZIP, EXE, SHA256SUMS")
