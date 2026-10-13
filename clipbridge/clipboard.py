"""Select the native clipboard backend without importing other OS libraries."""
import sys

if sys.platform == "win32":
    from .clipboard_win import ClipboardWorker, sequence, raw_data, gdi32
elif sys.platform == "darwin":
    from .clipboard_macos import ClipboardWorker, sequence
else:
    raise RuntimeError("ClipBridge는 Windows와 macOS에서 실행할 수 있습니다.")
