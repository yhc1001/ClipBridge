import os
import runpy
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
with tempfile.TemporaryDirectory(prefix="ClipBridge-source-entry-") as directory:
    os.environ["LOCALAPPDATA"] = directory
    os.environ["CLIPBRIDGE_STARTUP_DIAGNOSTIC"] = str(root / "artifacts" / "source-startup-diagnostic.txt")
    sys.argv = [str(root / "bootstrap.py"), "--smoke-test"]
    sys.stdout = sys.stderr = None
    runpy.run_path(str(root / "bootstrap.py"), run_name="__main__")
