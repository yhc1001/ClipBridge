from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import queue
import struct
import threading
import time

import win32api
import win32clipboard as cb
import win32con
import win32gui

from .images import normalize
from .model import MAX_FILES, Snapshot

user32, kernel32, gdi32 = C.WinDLL("user32", use_last_error=True), C.WinDLL("kernel32", use_last_error=True), C.WinDLL("gdi32", use_last_error=True)
for name, args, result in (
    ("AddClipboardFormatListener", [W.HWND], W.BOOL),
    ("RemoveClipboardFormatListener", [W.HWND], W.BOOL),
    ("GetClipboardSequenceNumber", [], W.DWORD),
    ("GetClipboardData", [W.UINT], W.HANDLE),
):
    function = getattr(user32, name)
    function.argtypes, function.restype = args, result
kernel32.GlobalSize.argtypes, kernel32.GlobalSize.restype = [W.HANDLE], C.c_size_t
kernel32.GlobalLock.argtypes, kernel32.GlobalLock.restype = [W.HANDLE], C.c_void_p
kernel32.GlobalUnlock.argtypes = [W.HANDLE]
gdi32.GetObjectW.argtypes, gdi32.GetObjectW.restype = [W.HANDLE, C.c_int, C.c_void_p], C.c_int
gdi32.CreateCompatibleDC.argtypes, gdi32.CreateCompatibleDC.restype = [W.HDC], W.HDC
gdi32.DeleteDC.argtypes = [W.HDC]
gdi32.GetDIBits.argtypes, gdi32.GetDIBits.restype = [W.HDC, W.HBITMAP, W.UINT, W.UINT, C.c_void_p, C.c_void_p, W.UINT], C.c_int
WM_UPDATE = 0x031D
WM_WORK = win32con.WM_APP + 17
MARKER = "ClipBridge.Origin.v1"


def sequence() -> int:
    return user32.GetClipboardSequenceNumber()


def raw_data(format_id: int, limit: int) -> bytes:
    handle = user32.GetClipboardData(format_id)
    if not handle:
        raise ValueError("format unavailable")
    size = kernel32.GlobalSize(handle)
    if not 0 < size <= limit:
        raise ValueError("format size limit")
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        raise ValueError("clipboard handle unavailable")
    try:
        return C.string_at(pointer, size)
    finally:
        kernel32.GlobalUnlock(handle)


class BITMAP(C.Structure):
    _fields_ = [("type", W.LONG), ("width", W.LONG), ("height", W.LONG), ("widthbytes", W.LONG), ("planes", W.WORD), ("bits", W.WORD), ("data", C.c_void_p)]


def bitmap_dib(limit: int) -> bytes:
    handle = user32.GetClipboardData(win32con.CF_BITMAP)
    bitmap = BITMAP()
    if not handle or not gdi32.GetObjectW(handle, C.sizeof(bitmap), C.byref(bitmap)):
        raise ValueError("invalid bitmap")
    size = bitmap.width * abs(bitmap.height) * 4
    if bitmap.width <= 0 or not 0 < size <= limit - 40:
        raise ValueError("bitmap size limit")
    header = struct.pack("<IiiHHIIiiII", 40, bitmap.width, abs(bitmap.height), 1, 32, 0, size, 0, 0, 0, 0)
    info, pixels = C.create_string_buffer(header), C.create_string_buffer(size)
    dc = gdi32.CreateCompatibleDC(None)
    try:
        if gdi32.GetDIBits(dc, handle, 0, abs(bitmap.height), pixels, info, 0) != abs(bitmap.height):
            raise ValueError("bitmap conversion failed")
        return header + pixels.raw
    finally:
        gdi32.DeleteDC(dc)


class ClipboardWorker(threading.Thread):
    """Owns a message-only Win32 window; never blocks the Qt/UI thread."""
    def __init__(self, config, ledger, on_local, on_applied, on_status):
        super().__init__(name="ClipBridge-clipboard", daemon=True)
        self.config, self.ledger = config, ledger
        self.on_local, self.on_applied, self.on_status = on_local, on_applied, on_status
        self.commands = queue.Queue()
        self.stopping, self.ready = threading.Event(), threading.Event()
        self.hwnd = None
        self.ids = {}
        self.marker_id = 0
        self.own_marker = b""
        self.last_hash = ""
        self.seen_sequence = 0
        self.capture_due = 0.0
        self.capture_attempts = 0
        self.pending = None
        self.has_received_files = False

    def _proc(self, hwnd, message, wparam, lparam):
        if message == WM_UPDATE:
            self.capture_due = time.monotonic() + .015
            self.capture_attempts = 0
            return 0
        if message == WM_WORK:
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    def run(self):
        class_name = "ClipBridge-" + self.config.device_id
        try:
            wc = win32gui.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName, wc.lpfnWndProc = class_name, self._proc
            win32gui.RegisterClass(wc)
            self.hwnd = win32gui.CreateWindowEx(0, class_name, "ClipBridge", 0, 0, 0, 0, 0, -3, 0, wc.hInstance, None)
            self.ids = {"PNG": cb.RegisterClipboardFormat("PNG"), "DIB": win32con.CF_DIB, "DIBV5": 17,
                        "Sylk": win32con.CF_SYLK, "DIF": win32con.CF_DIF,
                        **{name: cb.RegisterClipboardFormat(name) for name in ("HTML Format", "Rich Text Format", "Rich Text Format Without Objects")}}
            self.marker_id = cb.RegisterClipboardFormat(MARKER)
            if not user32.AddClipboardFormatListener(self.hwnd):
                raise C.WinError(C.get_last_error())
            self.seen_sequence = sequence()  # Existing clipboard is never sent at startup.
            self.ready.set()
            while not self.stopping.is_set():
                win32gui.PumpWaitingMessages()
                self._drain()
                if self.capture_due and time.monotonic() >= self.capture_due:
                    self._capture_retry()
                if self.pending and time.monotonic() >= self.pending[3]:
                    self._apply_retry()
                self.stopping.wait(.01)
        except Exception as error:
            self.on_status("클립보드 감시 오류 (" + type(error).__name__ + ")")
        finally:
            self.ready.set()
            if self.hwnd:
                if self.has_received_files:
                    try:
                        cb.OpenClipboard(self.hwnd)
                        try:
                            if cb.IsClipboardFormatAvailable(self.marker_id) and raw_data(self.marker_id, 2048).rstrip(b"\0") == self.own_marker:
                                cb.EmptyClipboard()
                        finally:
                            cb.CloseClipboard()
                    except Exception:
                        pass
                user32.RemoveClipboardFormatListener(self.hwnd)
                win32gui.DestroyWindow(self.hwnd)
                win32gui.UnregisterClass(class_name, win32api.GetModuleHandle(None))

    def stop(self):
        self.stopping.set()
        self.join(timeout=3)

    def apply(self, snapshot: Snapshot, callback):
        # Sequence guards against a newer local copy not yet captured by our listener.
        self.commands.put((snapshot, callback, snapshot.sequence))
        if self.hwnd:
            win32gui.PostMessage(self.hwnd, WM_WORK, 0, 0)

    def copy_private_text(self, text: str):
        self.commands.put({"private_text": text})

    def _private_text(self, text):
        self.ledger.local()
        for attempt in range(20):
            try:
                cb.OpenClipboard(self.hwnd)
                try:
                    cb.EmptyClipboard()
                    self.own_marker = ("settings:" + self.config.device_id).encode("ascii")
                    cb.SetClipboardData(self.marker_id, self.own_marker + b"\0")
                    cb.SetClipboardData(win32con.CF_UNICODETEXT, text)
                    for name in ("CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"):
                        cb.SetClipboardData(cb.RegisterClipboardFormat(name), struct.pack("<I", 0))
                    self.seen_sequence = sequence()
                finally:
                    cb.CloseClipboard()
                self.on_status("연결 코드를 복사했습니다 · 믿을 수 있는 방법으로 newserver에 전달하세요")
                return
            except Exception:
                time.sleep(.05)
        self.on_status("연결 코드 복사 실패 · 다시 시도하세요")

    def _drain(self):
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                return
            if isinstance(command, dict):
                self._private_text(command["private_text"])
                continue
            snapshot, callback, expected = command
            if self.pending:
                self.pending[1](False)
            self.pending = (snapshot, callback, expected, time.monotonic(), 0)

    def _capture_retry(self):
        try:
            self._capture()
            self.capture_due = 0
        except Exception as error:
            self.capture_attempts += 1
            if self.capture_attempts < 20:
                self.capture_due = time.monotonic() + min(.025 * self.capture_attempts, .25)
            else:
                self.capture_due = 0
                self.on_status("클립보드를 읽지 못했습니다 (" + type(error).__name__ + ") · 다음 복사 시 다시 시도")

    def _capture(self):
        if sequence() == self.seen_sequence:
            return
        cb.OpenClipboard(self.hwnd)
        try:
            seq = sequence()
            if cb.IsClipboardFormatAvailable(self.marker_id):
                marker = raw_data(self.marker_id, 2048).rstrip(b"\0")
                if self.own_marker and marker == self.own_marker:
                    self.seen_sequence = seq
                    return
            # Any local change, even unsupported/disabled content, supersedes a pending receive.
            stamp = self.ledger.local()
            formats, paths, total = {}, [], 0
            if self.config.text:
                try:
                    data = raw_data(win32con.CF_UNICODETEXT, self.config.clip_limit)
                    text = data[:len(data) // 2 * 2].decode("utf-16-le").split("\0", 1)[0]
                    formats["text"] = text.encode("utf-8")
                except ValueError:
                    if cb.IsClipboardFormatAvailable(win32con.CF_TEXT):
                        formats["text"] = raw_data(win32con.CF_TEXT, self.config.clip_limit).split(b"\0", 1)[0].decode("mbcs", errors="replace").encode("utf-8")
            for name, fmt in self.ids.items():
                if (name in ("PNG", "DIB", "DIBV5") and not self.config.images) or (name not in ("PNG", "DIB", "DIBV5") and not self.config.text):
                    continue
                if cb.IsClipboardFormatAvailable(fmt):
                    try:
                        data = raw_data(fmt, self.config.clip_limit)
                        total = sum(map(len, formats.values())) + len(data)
                        if total <= self.config.clip_limit:
                            formats[name] = data
                        else:
                            self.on_status("일부 클립보드 형식이 용량 제한을 초과하여 생략되었습니다.")
                    except ValueError:
                        self.on_status("지원 형식 중 일부를 읽지 못했습니다.")
            if self.config.images and not any(k in formats for k in ("PNG", "DIB", "DIBV5")) and cb.IsClipboardFormatAvailable(win32con.CF_BITMAP):
                formats["DIB"] = bitmap_dib(self.config.clip_limit)
            if self.config.files and self.config.file_policy != "block" and cb.IsClipboardFormatAvailable(win32con.CF_HDROP):
                raw_data(win32con.CF_HDROP, 1024 * 1024)
                paths = list(cb.GetClipboardData(win32con.CF_HDROP))
                if len(paths) > MAX_FILES:
                    self.on_status("파일 목록 개수 제한을 초과했습니다.")
                    paths = []
            self.seen_sequence = seq
        finally:
            cb.CloseClipboard()
        formats = normalize(formats, self.config.clip_limit)
        snapshot = Snapshot(formats, paths, stamp, seq)
        digest = snapshot.digest()
        if digest == self.last_hash:
            return
        self.last_hash = digest
        if self.config.can_send() and (formats or paths):
            self.on_local(snapshot)

    def _apply_retry(self):
        snapshot, callback, expected, _, attempts = self.pending
        if not self.config.can_receive() or not self.ledger.current(snapshot.stamp) or sequence() != expected or expected != self.seen_sequence:
            self.pending = None
            callback(False)
            if sequence() != self.seen_sequence:
                self.capture_due = time.monotonic()
            return
        try:
            cb.OpenClipboard(self.hwnd)
            try:
                with self.ledger.lock:
                    if self.ledger.latest != snapshot.stamp or sequence() != expected:
                        self.pending = None
                        callback(False)
                        return
                    cb.EmptyClipboard()
                    self.own_marker = str(snapshot.stamp.wire()).encode("ascii")
                    cb.SetClipboardData(self.marker_id, self.own_marker + b"\0")
                    for name, data in snapshot.formats.items():
                        if name == "text":
                            cb.SetClipboardData(win32con.CF_UNICODETEXT, data.decode("utf-8"))
                        else:
                            cb.SetClipboardData(self.ids[name], data)
                    if snapshot.paths:
                        drop = struct.pack("<IiiII", 20, 0, 0, 0, 1) + ("\0".join(snapshot.paths) + "\0\0").encode("utf-16-le")
                        cb.SetClipboardData(win32con.CF_HDROP, drop)
                        # Always copy: never propagate cut/move semantics to source files.
                        cb.SetClipboardData(cb.RegisterClipboardFormat("Preferred DropEffect"), struct.pack("<I", 1))
                    # Opt out of Windows clipboard history / cloud clipboard for received data.
                    for name in ("CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"):
                        cb.SetClipboardData(cb.RegisterClipboardFormat(name), struct.pack("<I", 0))
                    self.seen_sequence = sequence()
                    self.last_hash = snapshot.digest()
            finally:
                cb.CloseClipboard()
            self.pending = None
            self.has_received_files = bool(snapshot.paths)
            self.on_applied(snapshot)
            callback(True)
        except Exception as error:
            if attempts < 20:
                self.pending = (snapshot, callback, expected, time.monotonic() + min(.025 * (attempts + 1), .25), attempts + 1)
            else:
                self.pending = None
                self.on_status("클립보드 쓰기 실패 (" + type(error).__name__ + ")")
                callback(False)
