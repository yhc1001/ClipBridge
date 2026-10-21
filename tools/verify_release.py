"""Inspect shipped resources without running apps or touching the clipboard."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import plistlib
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clipbridge import __version__
from PyInstaller.archive.readers import CArchiveReader

DIST = ROOT / "dist" / ("v" + __version__)


def component(read, prefix):
    manifest = json.loads(read(prefix + "bundle.json"))
    assert manifest["version"] == "1.27.0"
    assert manifest["executable"] in manifest["hashes"]
    for name, digest in manifest["hashes"].items():
        path = PurePosixPath(name)
        assert not path.is_absolute() and ".." not in path.parts
        assert hashlib.sha256(read(prefix + name)).hexdigest() == digest, name
    print("Bundled resources verified: " + manifest["platform"])


if __name__ == "__main__":
    executable = CArchiveReader(str(DIST / "ClipBridge.exe"))
    modules = executable.open_embedded_archive("PYZ.pyz").toc
    assert not any(name == "tools.legacy_input" or name.startswith("tools.legacy_input.") for name in modules)
    names = {name.replace("\\", "/"): name for name in executable.toc}
    component(lambda name: executable.extract(names[name]), "input-engine/")
    for architecture in ("arm64", "intel"):
        with zipfile.ZipFile(DIST / ("ClipBridge-macOS-" + architecture + ".zip")) as archive:
            assert archive.testzip() is None
            info = plistlib.loads(archive.read("ClipBridge.app/Contents/Info.plist"))
            assert info["CFBundleShortVersionString"] == __version__
            component(archive.read, "ClipBridge.app/Contents/Resources/input-engine/")
    with tarfile.open(DIST / "ClipBridge-linux-x86_64.tar.gz", "r:gz") as archive:
        component(lambda name: archive.extractfile(name).read(), "ClipBridge/_internal/input-engine/")
        assert archive.getmember("ClipBridge/ClipBridge").mode & 0o111
        assert archive.getmember("ClipBridge/_internal/input-engine/deskflow-core").mode & 0o111
    for name in ("ClipBridge-source.zip", "ClipBridge-portable.zip"):
        with zipfile.ZipFile(DIST / name) as archive:
            assert archive.testzip() is None
            for path in archive.namelist():
                normalized = PurePosixPath(path)
                assert not normalized.is_absolute() and ".." not in normalized.parts
                assert normalized.name != "settings.json" and normalized.suffix not in (".pem", ".key", ".log")
            assert "licenses/Deskflow/DESKFLOW-LICENSE.txt" in archive.namelist()
    for line in (DIST / "SHA256SUMS.txt").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((DIST / name).read_bytes()).hexdigest() == digest
    print("Release versions, native resource hashes, executable modes, source/portable privacy and checksums: PASS")
