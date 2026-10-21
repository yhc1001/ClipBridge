import queue
from pathlib import Path

from PySide6.QtCore import QObject, QMimeData, QUrl, Signal
from PIL import Image
import pytest

from clipbridge.clipboard_linux import ClipboardWorker, QtPasteboard, paths_from_mime
from clipbridge.config import Config
from clipbridge.formats import html_to_cfhtml
from clipbridge.images import image_formats
from clipbridge.model import Ledger, Snapshot, Stamp
from test_portability import qt_app, pump


class MemoryClipboard(QObject):
    dataChanged = Signal()

    def __init__(self):
        super().__init__()
        self.mime = QMimeData()

    def mimeData(self):
        return self.mime

    def setMimeData(self, mime):
        self.mime = mime
        self.dataChanged.emit()

    def clear(self):
        self.setMimeData(QMimeData())


def test_linux_mime_text_image_html_rtf_and_file_urls(qt_app, tmp_path):
    board = QtPasteboard(MemoryClipboard())
    paths = [str(tmp_path / "한글 # one.txt"), str(tmp_path / "directory")]
    formats = image_formats(Image.new("RGBA", (20, 10), (1, 2, 3, 200)))
    formats.update({"text": "다른 OS 😀".encode(), "HTML Format": html_to_cfhtml(b"<b>html</b>"), "Rich Text Format": b"{\\rtf1 rich}"})
    board.write(Snapshot(formats, paths), "origin-marker")
    actual, actual_paths, marker = board.read(Config())
    assert {"text", "PNG", "HTML Format", "Rich Text Format"} <= actual.keys()
    assert actual["text"] == formats["text"] and actual["PNG"] == formats["PNG"]
    assert list(map(Path, actual_paths)) == list(map(Path, paths)) and marker == "origin-marker"
    assert bytes(board.clipboard.mimeData().data("x-special/gnome-copied-files")).startswith(b"copy\nfile:")
    assert bytes(board.clipboard.mimeData().data("application/x-kde-cutselection")) == b"0"
    board.clear_if_marker("other")
    assert list(map(Path, board.read(Config())[1])) == list(map(Path, paths))
    board.clear_if_marker(marker)
    assert board.read(Config()) == ({}, [], "")


def test_linux_worker_detects_copy_applies_files_and_never_echoes(qt_app, tmp_path):
    board = QtPasteboard(MemoryClipboard())
    config, local, applied = Config(), queue.Queue(), []
    ledger = Ledger(config.device_id)
    worker = ClipboardWorker(config, ledger, local.put, applied.append, lambda status: None, board)
    worker.start()
    try:
        external = QMimeData()
        external.setText("Linux -> Windows")
        board.clipboard.setMimeData(external)
        pump(qt_app, lambda: not local.empty())
        assert local.get().formats["text"] == b"Linux -> Windows"
        stamp = Stamp(ledger.clock + 1, "ffffffff-ffff-4fff-bfff-ffffffffffff")
        ledger.claim(stamp)
        result = []
        worker.apply(Snapshot({"text": b"incoming"}, [str(tmp_path / "file")], stamp, board.count()), result.append)
        pump(qt_app, lambda: bool(result))
        assert result == [True]
        worker.tick()
        assert local.empty()
        worker.copy_private_text("CB1-private")
        worker.tick()
        worker.tick()
        assert local.empty()
    finally:
        worker.stop()


def test_linux_rejects_remote_file_urls_and_preserves_copy_semantics(qt_app):
    mime = QMimeData()
    mime.setUrls([QUrl("file://other-host/shared/file.txt")])
    with pytest.raises(ValueError):
        paths_from_mime(mime)


def test_linux_encryption_tamper_and_desktop_arguments(monkeypatch, tmp_path):
    from clipbridge import linux_security, linux_startup
    monkeypatch.setattr(linux_security, "local_key", lambda: b"k" * 32)
    value = linux_security.protect(b"local secret")
    assert linux_security.unprotect(value) == b"local secret"
    import base64
    raw = bytearray(base64.b64decode(value[5:]))
    raw[-1] ^= 1
    with pytest.raises(Exception):
        linux_security.unprotect("LIN1-" + base64.b64encode(raw).decode())
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    linux_startup.set_autostart(True)
    path = tmp_path / "autostart" / "clipbridge.desktop"
    text = path.read_text(encoding="utf-8")
    assert "Terminal=false" in text and "--background" in text
    assert "Exec=\"" in text
    linux_startup.set_autostart(False)
    assert not path.exists()
