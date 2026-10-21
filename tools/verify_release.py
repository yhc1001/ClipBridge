"""Inspect shipped resources without running apps or touching the clipboard."""
import hashlib
import argparse
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows-only", action="store_true", help="Windows-only release; Mac/Linux remain on their earlier release")
    arguments = parser.parse_args()
    executable = CArchiveReader(str(DIST / "ClipBridge.exe"))
    modules = executable.open_embedded_archive("PYZ.pyz").toc
    assert not any(name == "tools.legacy_input" or name.startswith("tools.legacy_input.") for name in modules)
    names = {name.replace("\\", "/"): name for name in executable.toc}
    component(lambda name: executable.extract(names[name]), "input-engine/")
    for architecture in ("arm64", "intel"):
        if arguments.windows_only:
            break
        with zipfile.ZipFile(DIST / ("ClipBridge-macOS-" + architecture + ".zip")) as archive:
            assert archive.testzip() is None
            info = plistlib.loads(archive.read("ClipBridge.app/Contents/Info.plist"))
            assert info["CFBundleShortVersionString"] == __version__
            component(archive.read, "ClipBridge.app/Contents/Resources/input-engine/")
    if not arguments.windows_only:
        with tarfile.open(DIST / "ClipBridge-linux-x86_64.tar.gz", "r:gz") as archive:
            component(lambda name: archive.extractfile(name).read(), "ClipBridge/_internal/input-engine/")
            assert archive.getmember("ClipBridge/ClipBridge").mode & 0o111
            assert archive.getmember("ClipBridge/_internal/input-engine/deskflow-core").mode & 0o111
    else:
        # Read-only MSI database inspection: never installs or executes it.
        from win32com.client.dynamic import Dispatch
        installer = Dispatch("WindowsInstaller.Installer")
        database = installer.OpenDatabase(str(DIST / "ClipBridge-UAC-setup-x64.msi"), 0)
        view = database.OpenView("SELECT `Name`, `StartType`, `StartName` FROM `ServiceInstall`")
        view.Execute(None)
        record = view.Fetch()
        assert record.StringData(1) == "ClipBridgeInput" and record.IntegerData(2) == 2
        assert record.StringData(3) in ("LocalSystem", "")
        assert view.Fetch() is None
        view.Close()
        view = database.OpenView("SELECT `Directory`, `DefaultDir` FROM `Directory`")
        view.Execute(None)
        directories = {}
        while (record := view.Fetch()) is not None:
            directories[record.StringData(1)] = record.StringData(2)
        assert directories.get("ClipBridgeInstallRoot") == "ClipBridge"
        assert "INSTALLFOLDER" not in directories
        view.Close()
        print("MSI fixed install location and automatic SYSTEM input service: PASS")
    for name in ("ClipBridge-source.zip", "ClipBridge-portable.zip"):
        with zipfile.ZipFile(DIST / name) as archive:
            assert archive.testzip() is None
            for path in archive.namelist():
                normalized = PurePosixPath(path)
                assert not normalized.is_absolute() and ".." not in normalized.parts
                assert normalized.name != "settings.json" and normalized.suffix not in (".pem", ".key", ".log")
            assert "licenses/Deskflow/DESKFLOW-LICENSE.txt" in archive.namelist()
            if name == "ClipBridge-source.zip":
                assert "service_bootstrap.py" in archive.namelist()
    for line in (DIST / "SHA256SUMS.txt").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((DIST / name).read_bytes()).hexdigest() == digest
    print("Release versions, native resource hashes, executable modes, source/portable privacy and checksums: PASS")
