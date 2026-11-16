"""Check patch application against the pinned upstream source, without input hooks."""
import hashlib
import json
from pathlib import Path
import tarfile

import pytest

from tools.windows_hangul_patch import AFTER, BEFORE, apply

ROOT = Path(__file__).resolve().parents[1]


def test_applies_once_to_pinned_source_and_refuses_unknown_source(tmp_path):
    archive = ROOT / "dist/input-downloads/deskflow-1.27.0-source.tar.gz"
    if not archive.exists():
        pytest.skip("Pinned upstream archive is obtained during input component preparation")
    lock = json.loads((ROOT / "assets/input-engine-lock.json").read_text())
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == lock["source"]["sha256"]
    with tarfile.open(archive) as package:
        member = next(item for item in package.getmembers() if item.name.endswith("/src/lib/platform/MSWindowsComputer.cpp"))
        original = package.extractfile(member).read().decode("utf-8")
    target = tmp_path / "src/lib/platform/MSWindowsComputer.cpp"
    target.parent.mkdir(parents=True)
    target.write_text(original, encoding="utf-8", newline="\n")
    apply(tmp_path)
    patched = target.read_text(encoding="utf-8")
    assert patched == original.replace(BEFORE, AFTER, 1)
    apply(tmp_path)
    assert target.read_text(encoding="utf-8") == patched
    target.write_text("unrecognized version", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected Deskflow source"):
        apply(tmp_path)
