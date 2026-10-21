"""Refresh archive documentation while preserving CI-built native binaries/modes."""
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(root))
from clipbridge import __version__

path = root / "dist" / ("v" + __version__) / "ClipBridge-linux-x86_64.tar.gz"
temporary = path.with_suffix(".updated.gz")
with tarfile.open(path, "r:gz") as original, tarfile.open(temporary, "w:gz") as updated:
    for member in original:
        if member.name == "ClipBridge/README.md" or member.name == "ClipBridge/docs" or member.name.startswith("ClipBridge/docs/"):
            continue
        updated.addfile(member, original.extractfile(member) if member.isfile() else None)
    updated.add(root / "README.md", arcname="ClipBridge/README.md")
    updated.add(root / "docs", arcname="ClipBridge/docs")
temporary.replace(path)
print("Linux documentation refreshed; CI-built native binaries preserved")
