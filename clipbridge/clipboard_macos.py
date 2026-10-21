"""Native macOS NSPasteboard polling, including changes while app is hidden."""
from __future__ import annotations

import concurrent.futures
import io
from pathlib import Path
import queue
import threading
import time
import uuid
from urllib.parse import unquote, urlparse

from PIL import Image
from PySide6.QtCore import QObject, QTimer, Signal, Qt

from .formats import cfhtml_to_html, html_to_cfhtml
from .images import image_formats, normalize
from .model import MAX_FILES, Snapshot

TEXT, PNG, TIFF, HTML, RTF, FILE = "public.utf8-plain-text", "public.png", "public.tiff", "public.html", "public.rtf", "public.file-url"
MARKER = "com.clipbridge.origin.v1"


def sequence():
    import objc
    from AppKit import NSPasteboard
    with objc.autorelease_pool():
        return int(NSPasteboard.generalPasteboard().changeCount())


class CocoaPasteboard:
    def __init__(self):
        from AppKit import NSPasteboard
        self.board = NSPasteboard.generalPasteboard()

    def count(self):
        return int(self.board.changeCount())

    def read(self, config):
        formats, paths = {}, []
        types = set(self.board.types() or [])
        marker = self.board.stringForType_(MARKER) if MARKER in types else ""
        mapping = {TEXT: "text", HTML: "HTML Format", RTF: "Rich Text Format", PNG: "PNG"}
        total = 0
        for native, wire in mapping.items():
            if native not in types or (native == PNG and not config.images) or (native != PNG and not config.text):
                continue
            data = self.board.dataForType_(native)
            if data is None or len(data) > config.clip_limit:
                continue
            raw = bytes(data)
            if native == HTML:
                raw = html_to_cfhtml(raw)
            if total + len(raw) <= config.clip_limit:
                formats[wire] = raw
                total += len(raw)
        if config.images and "PNG" not in formats and TIFF in types:
            data = self.board.dataForType_(TIFF)
            if data is not None and len(data) <= config.clip_limit - total:
                formats["_TIFF"] = bytes(data)
        if config.files and config.file_policy != "block":
            for item in self.board.pasteboardItems() or []:
                url = item.stringForType_(FILE)
                if url:
                    parsed = urlparse(str(url))
                    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
                        raise ValueError("Only local file URLs are supported")
                    paths.append(unquote(parsed.path))
                    if len(paths) > MAX_FILES:
                        raise ValueError("file count limit")
        return formats, paths, str(marker or "")

    def write(self, snapshot, marker):
        from AppKit import NSPasteboardItem
        from Foundation import NSData
        items = []
        paths = snapshot.paths or [None]
        for index, path in enumerate(paths):
            item = NSPasteboardItem.alloc().init()
            item.setString_forType_(marker, MARKER)
            if path:
                item.setString_forType_(Path(path).absolute().as_uri(), FILE)
            if index == 0:
                for wire, native in (("text", TEXT), ("PNG", PNG), ("HTML Format", HTML), ("Rich Text Format", RTF)):
                    if wire not in snapshot.formats:
                        continue
                    data = snapshot.formats[wire]
                    if wire == "text":
                        ok = item.setString_forType_(data.decode("utf-8"), native)
                    else:
                        if wire == "HTML Format":
                            data = cfhtml_to_html(data)
                        ok = item.setData_forType_(NSData.dataWithBytes_length_(data, len(data)), native)
                    if not ok:
                        raise ValueError("pasteboard format unavailable")
            items.append(item)
        # Keep received data and pairing secrets out of Apple's Universal Clipboard.
        self.board.prepareForNewContentsWithOptions_(1)  # NSPasteboardContentsCurrentHostOnly
        if not self.board.writeObjects_(items):
            raise ValueError("pasteboard write failed")

    def clear_if_marker(self, marker):
        if str(self.board.stringForType_(MARKER) or "") == marker:
            self.board.clearContents()


def prepare_formats(formats, limit):
    formats = dict(formats)
    tiff = formats.pop("_TIFF", None)
    if tiff:
        with Image.open(io.BytesIO(tiff)) as image:
            if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError("image size limit")
            image.load()
            formats["PNG"] = image_formats(image)["PNG"]
    return normalize(formats, limit)


class ClipboardWorker(QObject):
    prepared = Signal(object)

    def __init__(self, config, ledger, on_local, on_applied, on_status, pasteboard=None, platform_name="macOS"):
        super().__init__()
        self.config, self.ledger = config, ledger
        self.on_local, self.on_applied, self.on_status = on_local, on_applied, on_status
        self.platform_name = platform_name
        self.board = pasteboard or CocoaPasteboard()
        self.commands = queue.Queue()
        self.ready = threading.Event()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="ClipBridge-image")
        self.capture_future = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.prepared.connect(self.capture_done, Qt.ConnectionType.QueuedConnection)
        self.seen_sequence = self.board.count()
        self.own_marker, self.last_hash = "", ""
        self.last_hash_sequence = None
        self.pending = None
        self.has_received_files = False
        self.stopped = False

    def start(self):
        self.timer.start()
        self.ready.set()

    def is_alive(self):
        return self.timer.isActive()

    def stop(self):
        self.stopped = True
        self.timer.stop()
        if self.pending:
            self.pending[1](False)
            self.pending = None
        self.executor.shutdown(wait=False, cancel_futures=True)
        if self.has_received_files:
            self.board.clear_if_marker(self.own_marker)

    def apply(self, snapshot, callback):
        self.commands.put((snapshot, callback))

    def copy_private_text(self, text):
        self.commands.put({"private_text": text})

    def tick(self):
        try:
            self.capture()
            while not self.commands.empty():
                command = self.commands.get_nowait()
                if isinstance(command, dict):
                    self.ledger.local()
                    self.own_marker = "settings:" + str(uuid.uuid4())
                    self.board.write(Snapshot({"text": command["private_text"].encode()}), self.own_marker)
                    self.seen_sequence = self.board.count()
                    self.on_status("연결 코드를 복사했습니다.")
                else:
                    if self.pending:
                        self.pending[1](False)
                    self.pending = (*command, time.monotonic() + 4)
            self.apply_pending()
        except Exception as error:
            self.on_status(self.platform_name + " 클립보드 접근 실패 (" + type(error).__name__ + ") · 접근 허용을 확인하세요")

    def capture(self):
        seq = self.board.count()
        if seq == self.seen_sequence:
            return
        formats, paths, marker = self.board.read(self.config)
        self.seen_sequence = seq
        if marker and marker == self.own_marker:
            return
        stamp = self.ledger.local()
        if not self.config.can_send() or not (formats or paths):
            return
        snapshot = Snapshot(formats, paths, stamp, seq)
        if self.capture_future:
            self.capture_future.cancel()
        self.capture_future = self.executor.submit(prepare_formats, formats, self.config.clip_limit)
        def done(future):
            if self.stopped or future.cancelled():
                return
            try:
                snapshot.formats = future.result()
                self.prepared.emit(snapshot)
            except Exception as error:
                self.prepared.emit(type(error).__name__)
        self.capture_future.add_done_callback(done)

    def capture_done(self, snapshot):
        if self.stopped:
            return
        if not isinstance(snapshot, Snapshot):
            self.on_status("이미지를 읽지 못했습니다 (" + snapshot + ")")
            return
        if not self.ledger.current(snapshot.stamp) or self.board.count() != snapshot.sequence:
            return
        digest = snapshot.digest()
        # A new copy action must retry even if the previous content/path was
        # identical. Only the same change-count and hash identify a duplicate.
        if digest == self.last_hash and snapshot.sequence == self.last_hash_sequence:
            return
        self.last_hash = digest
        self.last_hash_sequence = snapshot.sequence
        self.on_local(snapshot)

    def apply_pending(self):
        if not self.pending:
            return
        snapshot, callback, deadline = self.pending
        if not self.config.can_receive() or not self.ledger.current(snapshot.stamp) or snapshot.sequence != self.board.count() or snapshot.sequence != self.seen_sequence:
            self.pending = None
            callback(False)
            return
        try:
            with self.ledger.lock:
                if not self.ledger.current(snapshot.stamp) or snapshot.sequence != self.board.count():
                    self.pending = None
                    callback(False)
                    return
                self.own_marker = str(uuid.uuid4())
                self.board.write(snapshot, self.own_marker)
                self.seen_sequence = self.board.count()
                self.last_hash = snapshot.digest()
                self.last_hash_sequence = self.seen_sequence
                self.has_received_files = bool(snapshot.paths)
            self.pending = None
            self.on_applied(snapshot)
            callback(True)
        except Exception:
            if time.monotonic() >= deadline:
                self.pending = None
                callback(False)
