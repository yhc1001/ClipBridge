"""Render our own Qt window and shut it down; runs with isolated AppData."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temporary = tempfile.TemporaryDirectory(prefix="ClipBridge-smoke-")
os.environ["LOCALAPPDATA"] = temporary.name

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from clipbridge.config import ConfigStore
from clipbridge.ui import Window

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
store = ConfigStore()
window = Window(store, store.load())
window.show()
output = Path(__file__).resolve().parents[1] / "artifacts" / "settings-preview.png"
output.parent.mkdir(exist_ok=True)
def finish():
    window.grab().save(str(output))
    window.quit()
QTimer.singleShot(1200, finish)
result = app.exec()
temporary.cleanup()
sys.exit(result)
