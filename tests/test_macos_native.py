import sys
import queue
from pathlib import Path
import pytest

if sys.platform != "darwin":
    pytest.skip("Native macOS test", allow_module_level=True)

from clipbridge.clipboard_macos import CocoaPasteboard, ClipboardWorker
from clipbridge.config import Config
from clipbridge.images import image_formats
from clipbridge.model import Ledger, Snapshot, Stamp
from test_portability import qt_app, pump
from PIL import Image


def test_real_nspasteboard_text_image_html_files_and_marker(qt_app, tmp_path):
    board = CocoaPasteboard()
    original = list(board.board.pasteboardItems() or [])
    config = Config()
    ledger, captured = Ledger(config.device_id), queue.Queue()
    worker = ClipboardWorker(config, ledger, captured.put, lambda data: None, lambda status: None, board)
    worker.start()
    try:
        board.write(Snapshot({"text": "macOS 原生 😀".encode()}), "native-source")
        pump(qt_app, lambda: not captured.empty())
        assert captured.get().formats["text"] == "macOS 原生 😀".encode()
        stamp = Stamp(ledger.clock + 1, "ffffffff-ffff-4fff-bfff-ffffffffffff")
        ledger.claim(stamp)
        file = tmp_path / "한글.txt"
        file.write_text("실제 파일", encoding="utf-8")
        from clipbridge.formats import html_to_cfhtml
        formats = image_formats(Image.new("RGBA", (20, 16), (10, 20, 30, 180)))
        formats.update({"text": b"received", "HTML Format": html_to_cfhtml(b"<b>rich</b>"), "Rich Text Format": b"{\\rtf1 hello}"})
        result = []
        worker.apply(Snapshot(formats, [str(file)], stamp, board.count()), result.append)
        pump(qt_app, lambda: bool(result))
        assert result == [True]
        raw, paths, marker = board.read(config)
        assert raw["text"] == b"received" and raw["PNG"] == formats["PNG"]
        assert b"<b>rich</b>" in raw["HTML Format"]
        assert paths == [str(file)] and marker == worker.own_marker
        worker.tick()
        assert captured.empty()
    finally:
        worker.stop()
        board.board.clearContents()
        if original:
            board.board.writeObjects_(original)
