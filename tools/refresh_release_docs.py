"""Refresh external release documentation without modifying app/native bytes."""
from pathlib import Path
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clipbridge import __version__


def documents():
    paths = [ROOT / "README.md", *(ROOT / "docs").glob("*.md"), *(ROOT / "artifacts").glob("setup-*.png"),
             *(ROOT / "artifacts").glob("*.json")]
    return [(path, path.relative_to(ROOT).as_posix()) for path in paths]


def refresh():
    directory = ROOT / "dist" / ("v" + __version__)
    files = documents()
    for architecture in ("arm64", "intel"):
        target = directory / ("ClipBridge-macOS-" + architecture + ".zip")
        temporary = target.with_suffix(".docs-tmp.zip")
        names = {name for _, name in files}
        with zipfile.ZipFile(target) as source, zipfile.ZipFile(temporary, "w") as result:
            for info in source.infolist():
                if info.filename not in names:
                    # Preserve original entry metadata, links and every byte
                    # inside the signed .app; docs live outside the bundle.
                    result.writestr(info, source.read(info))
            for path, name in files:
                result.write(path, name, compress_type=zipfile.ZIP_DEFLATED)
        temporary.replace(target)
        print("Updated external documentation: " + target.name, flush=True)
    target = directory / "ClipBridge-linux-x86_64.tar.gz"
    temporary = target.with_suffix(".docs-tmp.gz")
    names = {"ClipBridge/" + name for _, name in files}
    with tarfile.open(target, "r:gz") as source, tarfile.open(temporary, "w:gz") as result:
        for member in source:
            if member.name in names:
                continue
            content = source.extractfile(member) if member.isfile() else None
            result.addfile(member, content)
        for path, name in files:
            result.add(path, arcname="ClipBridge/" + name)
    temporary.replace(target)
    print("Updated Linux documentation; executable bytes/modes preserved", flush=True)


if __name__ == "__main__":
    refresh()
