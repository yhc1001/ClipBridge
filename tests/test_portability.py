import queue
import time
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from clipbridge.config import Config
from clipbridge.formats import cfhtml_to_html, html_to_cfhtml
from clipbridge.model import Ledger, Snapshot, Stamp
from clipbridge.clipboard_macos import ClipboardWorker


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


def pump(app, predicate, timeout=4):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Qt event timed out")


class FakePasteboard:
    def __init__(self):
        self.sequence = 1
        self.formats, self.paths, self.marker = {}, [], ""

    def count(self):
        return self.sequence

    def read(self, config):
        return dict(self.formats), list(self.paths), self.marker

    def write(self, snapshot, marker):
        self.formats, self.paths, self.marker = snapshot.formats, snapshot.paths, marker
        self.sequence += 1

    def clear_if_marker(self, marker):
        if self.marker == marker:
            self.write(Snapshot(), "")


def test_cfhtml_utf8_byte_offsets_and_header_removal():
    html = "<html><body><b>한글 😀</b><table><tr><td>値</td></tr></table></body></html>".encode()
    converted = html_to_cfhtml(html)
    assert converted.startswith(b"Version:1.0\r\n")
    restored = cfhtml_to_html(converted)
    assert "<b>한글 😀</b>".encode() in restored
    assert b"StartHTML" not in restored
    assert cfhtml_to_html(b"<b>plain</b>\0") == b"<b>plain</b>"
    with pytest.raises(ValueError):
        cfhtml_to_html(b"Version:1.0\r\nStartHTML:9999\r\nEndHTML:10000\r\n")


def test_mac_worker_detects_hidden_changes_and_prevents_loops(qt_app):
    config, board = Config(), FakePasteboard()
    ledger, local, remote = Ledger(config.device_id), queue.Queue(), []
    worker = ClipboardWorker(config, ledger, local.put, remote.append, lambda status: None, board)
    worker.start()
    try:
        board.write(Snapshot({"text": "Mac → Windows 😀".encode()}), "other app")
        pump(qt_app, lambda: not local.empty())
        assert local.get().formats["text"] == "Mac → Windows 😀".encode()
        stamp = Stamp(ledger.clock + 1, "ffffffff-ffff-4fff-bfff-ffffffffffff")
        ledger.claim(stamp)
        result = []
        worker.apply(Snapshot({"text": b"received"}, [], stamp, board.count()), result.append)
        pump(qt_app, lambda: bool(result))
        assert result == [True] and board.formats["text"] == b"received"
        for _ in range(3):
            worker.tick()
        assert local.empty()
        worker.copy_private_text("CB1-test-code")
        worker.tick()
        worker.tick()
        assert local.empty()
    finally:
        worker.stop()


def test_mac_worker_new_copy_wins_and_files_clear_on_exit(qt_app, tmp_path):
    config, board = Config(), FakePasteboard()
    ledger = Ledger(config.device_id)
    worker = ClipboardWorker(config, ledger, lambda data: None, lambda data: None, lambda status: None, board)
    worker.start()
    try:
        stamp = Stamp(1, "ffffffff-ffff-4fff-bfff-ffffffffffff")
        ledger.claim(stamp)
        result = []
        worker.apply(Snapshot({"text": b"old"}, [], stamp, board.count()), result.append)
        board.write(Snapshot({"text": b"new"}), "local app")
        worker.tick()
        assert result == [False] and board.formats["text"] == b"new"
        stamp = Stamp(ledger.clock + 1, "ffffffff-ffff-4fff-bfff-ffffffffffff")
        ledger.claim(stamp)
        result = []
        worker.apply(Snapshot({}, [str(tmp_path / "file")], stamp, board.count()), result.append)
        worker.tick()
        assert result == [True] and board.paths
    finally:
        worker.stop()
    assert not board.paths


def test_mac_encryption_tampering_rejected_without_keychain(monkeypatch):
    from clipbridge import macos_security as security
    monkeypatch.setattr(security, "_key", b"k" * 32)
    protected = security.protect(b"local-secret")
    assert security.unprotect(protected) == b"local-secret"
    import base64
    raw = bytearray(base64.b64decode(protected[5:]))
    raw[-1] ^= 1
    with pytest.raises(Exception):
        security.unprotect("MAC1-" + base64.b64encode(raw).decode())


def test_mac_login_agent_arguments_and_permissions(monkeypatch, tmp_path):
    from clipbridge import macos_startup as startup
    import plistlib
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(startup.os, "getuid", lambda: 501, raising=False)
    calls = []
    monkeypatch.setattr(startup.subprocess, "run", lambda args, **kwargs: calls.append(args))
    startup.set_autostart(True)
    path = tmp_path / "Library" / "LaunchAgents" / "com.clipbridge.login.plist"
    data = plistlib.loads(path.read_bytes())
    assert data["RunAtLoad"] and data["ProgramArguments"][-1] == "--background"
    assert data["LimitLoadToSessionType"] == "Aqua"
    assert not any("bootout" in call for call in calls)
    startup.set_autostart(False)
    assert not path.exists()
