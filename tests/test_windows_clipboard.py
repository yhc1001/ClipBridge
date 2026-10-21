import queue
import struct
import time
import threading
import atexit

import pytest
cb = pytest.importorskip("win32clipboard")
import win32con
import win32gui
from PIL import Image

from clipbridge.clipboard import ClipboardWorker, raw_data, sequence
from clipbridge.config import Config
from clipbridge.images import image_formats
from clipbridge.model import Ledger, Snapshot, Stamp
from clipbridge.model import FORMATS
from clipbridge.clipboard_win import MARKER


def wait_for(predicate, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError("timed out")


class ClipboardOwner(threading.Thread):
    """Pump owner messages while the test thread waits for a clipboard worker."""
    def __init__(self):
        super().__init__(daemon=True)
        self.ready, self.stopped = threading.Event(), threading.Event()
        self.hwnd = None

    def run(self):
        self.hwnd = win32gui.CreateWindowEx(0, "STATIC", "ClipBridge test", 0, 0, 0, 0, 0, -3, 0, 0, None)
        self.ready.set()
        while not self.stopped.wait(.005):
            win32gui.PumpWaitingMessages()
        win32gui.DestroyWindow(self.hwnd)

    def stop(self):
        self.stopped.set()
        self.join(2)


_owner = ClipboardOwner()
_owner.start()
assert _owner.ready.wait(5)
atexit.register(_owner.stop)


def open_clipboard():
    # An explicit owner prevents NULL-owner opens from interfering with the
    # listener thread. The owner thread pumps WM_DESTROYCLIPBOARD messages.
    for _ in range(50):
        try:
            cb.OpenClipboard(_owner.hwnd)
            return
        except Exception:
            time.sleep(.02)
    raise AssertionError("clipboard busy")


@pytest.fixture
def native():
    open_clipboard()
    saved = {}
    try:
        fmt = cb.EnumClipboardFormats(0)
        while fmt:
            registered = fmt >= 0xC000 and cb.GetClipboardFormatName(fmt) in (FORMATS | {MARKER, "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard", "Preferred DropEffect"})
            if fmt in (13, 15, 8, 17) or registered:
                try:
                    saved[fmt] = raw_data(fmt, 128 * 1024**2)
                except Exception:
                    pass
            fmt = cb.EnumClipboardFormats(fmt)
    finally:
        cb.CloseClipboard()
    config, captured, applied, statuses = Config(), queue.Queue(), queue.Queue(), []
    ledger = Ledger(config.device_id)
    worker = ClipboardWorker(config, ledger, captured.put, applied.put, statuses.append)
    worker.start()
    assert worker.ready.wait(5) and worker.hwnd
    yield worker, ledger, captured, applied, statuses
    worker.stop()
    open_clipboard()
    try:
        cb.EmptyClipboard()
        for fmt, data in saved.items():
            cb.SetClipboardData(fmt, data.decode("utf-16-le").rstrip("\0") if fmt == 13 else data)
    finally:
        cb.CloseClipboard()


def put(formats, ids=None):
    open_clipboard()
    try:
        cb.EmptyClipboard()
        for name, data in formats.items():
            cb.SetClipboardData(13 if name == "text" else ids[name], data.decode() if name == "text" else data)
    finally:
        cb.CloseClipboard()


def test_native_unicode_detection_receive_loop_and_busy_retry(native):
    worker, ledger, captured, applied, statuses = native
    put({"text": "Main → 서버 😀".encode()})
    snapshot = captured.get(timeout=5)
    assert snapshot.formats["text"].decode() == "Main → 서버 😀"
    # Hold clipboard in this thread to exercise worker retry without blocking UI.
    open_clipboard()
    stamp = Stamp(ledger.clock + 1, "ffffffff-ffff-4fff-bfff-ffffffffffff")
    ledger.claim(stamp)
    received = Snapshot({"text": "서버 → Main".encode()}, [], stamp, sequence())
    result = queue.Queue()
    worker.apply(received, result.put)
    time.sleep(.15)
    cb.CloseClipboard()
    assert result.get(timeout=5) is True
    assert applied.get(timeout=5).formats == received.formats
    open_clipboard()
    try:
        assert cb.GetClipboardData(13) == "서버 → Main"
    finally:
        cb.CloseClipboard()
    time.sleep(.2)
    assert captured.empty(), "remote apply must never be sent back"
    # Same text copied again must be detected after an intervening received value.
    put({"text": snapshot.formats["text"]})
    assert captured.get(timeout=5).formats["text"] == snapshot.formats["text"]


def test_native_png_dib_html_rtf_and_hdrop(native, tmp_path):
    worker, ledger, captured, applied, statuses = native
    formats = image_formats(Image.new("RGBA", (40, 30), (20, 40, 80, 180)))
    formats.update({"text": b"table\tvalue", "HTML Format": b"Version:1.0\r\nStartHTML:0000000000\r\n<b>table</b>\0", "Rich Text Format": b"{\\rtf1\\ansi hello}\0"})
    put(formats, worker.ids)
    snapshot = captured.get(timeout=5)
    assert set(formats) <= snapshot.formats.keys()
    assert snapshot.formats["DIBV5"] == formats["DIBV5"]
    stamp = Stamp(ledger.clock + 1, "ffffffff-ffff-4fff-bfff-ffffffffffff")
    ledger.claim(stamp)
    first, second = tmp_path / "첫번째.txt", tmp_path / "second.bin"
    first.write_text("data")
    second.write_bytes(b"data2")
    received = Snapshot(formats, [str(first), str(second)], stamp, sequence())
    result = queue.Queue()
    worker.apply(received, result.put)
    assert result.get(timeout=5)
    open_clipboard()
    try:
        assert cb.GetClipboardData(win32con.CF_HDROP) == (str(first), str(second))
        assert raw_data(worker.ids["HTML Format"], 1000) == formats["HTML Format"]
        assert raw_data(worker.ids["DIBV5"], 100000) == formats["DIBV5"]
    finally:
        cb.CloseClipboard()
    time.sleep(.1)
    assert captured.empty()


def test_new_local_copy_is_not_overwritten_by_pending_receive(native):
    worker, ledger, captured, applied, statuses = native
    stamp = Stamp(ledger.clock + 1, "ffffffff-ffff-4fff-bfff-ffffffffffff")
    ledger.claim(stamp)
    received = Snapshot({"text": b"older incoming"}, [], stamp, sequence())
    put({"text": b"new local copy"})
    result = queue.Queue()
    worker.apply(received, result.put)
    assert result.get(timeout=5) is False
    assert captured.get(timeout=5).formats["text"] == b"new local copy"


def test_same_received_item_with_added_windows_format_does_not_cancel_file(native, tmp_path):
    worker, ledger, captured, applied, statuses = native
    first = Stamp(ledger.clock + 1, "ffffffff-ffff-4fff-bfff-ffffffffffff")
    ledger.claim(first)
    result = queue.Queue()
    worker.apply(Snapshot(image_formats(Image.new("RGB", (20, 10), "blue")), [], first, sequence()), result.put)
    assert result.get(timeout=5)
    previous_sequence = sequence()
    second = Stamp(ledger.clock + 1, first.device)
    ledger.claim(second)
    # Add a format without replacing the item, as synthesized Win32 formats do.
    open_clipboard()
    try:
        cb.SetClipboardData(cb.RegisterClipboardFormat("ClipBridge.Test.Synthesized"), b"extra\0")
    finally:
        cb.CloseClipboard()
    assert sequence() != previous_sequence
    file = tmp_path / "received.txt"
    file.write_bytes(b"file")
    worker.apply(Snapshot({}, [str(file)], second, previous_sequence), result.put)
    assert result.get(timeout=5)
    open_clipboard()
    try:
        assert cb.GetClipboardData(win32con.CF_HDROP) == (str(file),)
    finally:
        cb.CloseClipboard()
    assert captured.empty()


def test_private_pairing_code_never_sent(native):
    worker, ledger, captured, applied, statuses = native
    worker.copy_private_text("CB1-private-test-code")
    wait_for(lambda: any("복사했습니다" in text for text in statuses))
    time.sleep(.2)
    assert captured.empty()


def test_explorer_hdrop_capture_and_bitmap_only_conversion(native, tmp_path):
    worker, ledger, captured, applied, statuses = native
    file = tmp_path / "file.txt"
    file.write_text("example")
    open_clipboard()
    try:
        cb.EmptyClipboard()
        drop = struct.pack("<IiiII", 20, 0, 0, 0, 1) + (str(file) + "\0\0").encode("utf-16-le")
        cb.SetClipboardData(win32con.CF_HDROP, drop)
    finally:
        cb.CloseClipboard()
    assert captured.get(timeout=5).paths == [str(file)]
    import ctypes as C
    from ctypes import wintypes as W
    from clipbridge.clipboard import gdi32
    gdi32.CreateDIBSection.argtypes = [W.HDC, C.c_void_p, W.UINT, C.POINTER(C.c_void_p), W.HANDLE, W.DWORD]
    gdi32.CreateDIBSection.restype = W.HBITMAP
    header = C.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, 12, 10, 1, 32, 0, 480, 0, 0, 0, 0))
    pixels = C.c_void_p()
    bitmap = gdi32.CreateDIBSection(None, header, 0, C.byref(pixels), None, 0)
    assert bitmap
    C.memmove(pixels, bytes([80, 50, 20, 255]) * 120, 480)
    open_clipboard()
    try:
        cb.EmptyClipboard()
        cb.SetClipboardData(win32con.CF_BITMAP, int(bitmap))
    finally:
        cb.CloseClipboard()
    snapshot = captured.get(timeout=5)
    assert {"PNG", "DIB", "DIBV5"} <= snapshot.formats.keys()
