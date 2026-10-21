"""Fresh copy actions are retries, even when their content/path is unchanged.

Only synthetic pasteboards are used: these tests never open the user's clipboard.
"""
import queue
import sys

import pytest

from clipbridge.config import Config
from clipbridge.model import Ledger, Snapshot
from test_portability import FakePasteboard, pump, qt_app


@pytest.fixture(params=["queued", pytest.param("windows", marks=pytest.mark.skipif(sys.platform != "win32", reason="Windows backend"))])
def capture(request, monkeypatch, qt_app):
    config, board, local = Config(), FakePasteboard(), queue.Queue()
    ledger = Ledger(config.device_id)
    if request.param == "queued":
        from clipbridge.clipboard_macos import ClipboardWorker
        from PySide6.QtCore import Qt
        worker = ClipboardWorker(config, ledger, local.put, lambda _: None, lambda _: None, board)
        prepared = []
        worker.prepared.connect(lambda _: prepared.append(True), Qt.ConnectionType.QueuedConnection)
        def tick():
            previous, count = worker.capture_future, len(prepared)
            worker.tick()
            if worker.capture_future is not previous:
                # Future.done() can precede its queued Qt delivery. Wait until
                # capture_done has actually run before inspecting its output.
                pump(qt_app, lambda: len(prepared) > count)
    else:
        from clipbridge import clipboard_win as backend
        worker = backend.ClipboardWorker(config, ledger, local.put, lambda _: None, lambda _: None)
        monkeypatch.setattr(backend, "sequence", board.count)
        monkeypatch.setattr(backend.cb, "OpenClipboard", lambda *args: None)
        monkeypatch.setattr(backend.cb, "CloseClipboard", lambda: None)
        monkeypatch.setattr(backend.cb, "IsClipboardFormatAvailable", lambda fmt: fmt == 15 and bool(board.paths))
        monkeypatch.setattr(backend.cb, "GetClipboardData", lambda fmt: tuple(board.paths))
        def raw(fmt, limit):
            if fmt == 13 and "text" in board.formats:
                return board.formats["text"].decode().encode("utf-16-le") + b"\0\0"
            if fmt == 15 and board.paths:
                return b"synthetic drop metadata"
            raise ValueError("format unavailable")
        monkeypatch.setattr(backend, "raw_data", raw)
        tick = worker._capture
    try:
        yield config, board, local, tick
    finally:
        if request.param == "queued":
            worker.stop()


def test_same_text_can_be_copied_again_after_missing_the_first_delivery(capture):
    _, board, local, tick = capture
    board.write(Snapshot({"text": b"retry after reconnect"}), "local app")
    tick()
    first = local.get(timeout=1)
    tick()
    assert local.empty(), "an unchanged clipboard must never echo"
    board.write(Snapshot(first.formats), "local app")
    tick()
    second = local.get(timeout=1)
    assert second.formats == first.formats and second.stamp > first.stamp


def test_new_copy_of_same_file_path_transfers_edited_contents(capture, tmp_path):
    _, board, local, tick = capture
    source = tmp_path / "edited.txt"
    source.write_bytes(b"first revision")
    board.write(Snapshot(paths=[str(source)]), "file manager")
    tick()
    first = local.get(timeout=1)
    source.write_bytes(b"second revision")
    board.write(Snapshot(paths=[str(source)]), "file manager")
    tick()
    second = local.get(timeout=1)
    assert second.paths == first.paths and second.stamp > first.stamp


def test_recopy_after_pause_is_sent_even_if_identical(capture):
    config, board, local, tick = capture
    config.paused = True
    board.write(Snapshot({"text": b"copied while paused"}), "local app")
    tick()
    assert local.empty()
    config.paused = False
    board.write(Snapshot({"text": b"copied while paused"}), "local app")
    tick()
    assert local.get(timeout=1).formats["text"] == b"copied while paused"
