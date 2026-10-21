"""X11 clipboard MIME/URI bridge. Qt owns the selection and serves paste requests."""
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QMimeData, QUrl
from PySide6.QtGui import QGuiApplication, QImage

from .clipboard_macos import ClipboardWorker as QueuedClipboardWorker
from .formats import cfhtml_to_html, html_to_cfhtml
from .model import MAX_FILES

MARKER = "application/x-clipbridge-origin"
_sequence = 0


def sequence():
    return _sequence


def paths_from_mime(mime):
    paths = []
    urls = mime.urls()
    if not urls and mime.hasFormat("x-special/gnome-copied-files"):
        lines = bytes(mime.data("x-special/gnome-copied-files")).decode("utf-8").splitlines()
        urls = [QUrl(value) for value in lines[1:]]
    for url in urls:
        if not url.isLocalFile() or url.host() not in ("", "localhost"):
            raise ValueError("Only local file URLs are supported")
        path = url.toLocalFile()
        if not Path(path).is_absolute() or "\0" in path:
            raise ValueError("Invalid file URI")
        paths.append(path)
    if len(paths) > MAX_FILES:
        raise ValueError("file count limit")
    return paths


def image_png(image):
    if image.isNull():
        raise ValueError("Invalid image")
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("PNG conversion failed")
    return bytes(buffer.data())


class QtPasteboard:
    def __init__(self, clipboard=None):
        self.clipboard = clipboard or QGuiApplication.clipboard()
        self.clipboard.dataChanged.connect(self.changed)

    def changed(self):
        global _sequence
        _sequence += 1

    def count(self):
        return sequence()

    def read(self, config):
        mime = self.clipboard.mimeData()
        if mime is None:
            return {}, [], ""
        formats, total = {}, 0
        for native, wire, enabled in (("text/plain", "text", config.text), ("text/html", "HTML Format", config.text),
                ("text/rtf", "Rich Text Format", config.text), ("image/png", "PNG", config.images)):
            if not enabled or not mime.hasFormat(native):
                continue
            data = bytes(mime.data(native))
            if len(data) > config.clip_limit:
                continue
            if native == "text/html":
                data = html_to_cfhtml(data)
            if total + len(data) <= config.clip_limit:
                formats[wire] = data
                total += len(data)
        if config.text and "text" not in formats and mime.hasText():
            data = mime.text().encode("utf-8")
            if total + len(data) <= config.clip_limit:
                formats["text"] = data
        if config.images and "PNG" not in formats and mime.hasImage():
            image = QImage(mime.imageData())
            from .images import Image
            if image.width() * image.height() <= Image.MAX_IMAGE_PIXELS:
                data = image_png(image)
                if sum(map(len, formats.values())) + len(data) <= config.clip_limit:
                    formats["PNG"] = data
        paths = paths_from_mime(mime) if config.files and config.file_policy != "block" else []
        marker = bytes(mime.data(MARKER)).decode("ascii", errors="ignore")
        return formats, paths, marker

    def write(self, snapshot, marker):
        mime = QMimeData()
        mime.setData(MARKER, marker.encode("ascii"))
        for wire, native in (("text", "text/plain"), ("PNG", "image/png"), ("HTML Format", "text/html"), ("Rich Text Format", "text/rtf")):
            if wire not in snapshot.formats:
                continue
            data = snapshot.formats[wire]
            if wire == "text":
                mime.setText(data.decode("utf-8"))
            else:
                mime.setData(native, cfhtml_to_html(data) if wire == "HTML Format" else data)
        if snapshot.paths:
            urls = [QUrl.fromLocalFile(str(Path(path).absolute())) for path in snapshot.paths]
            mime.setUrls(urls)
            mime.setData("x-special/gnome-copied-files", ("copy\n" + "\n".join(url.toString(QUrl.ComponentFormattingOption.FullyEncoded) for url in urls)).encode())
            mime.setData("application/x-kde-cutselection", b"0")
        self.clipboard.setMimeData(mime)

    def clear_if_marker(self, marker):
        mime = self.clipboard.mimeData()
        if mime and bytes(mime.data(MARKER)).decode("ascii", errors="ignore") == marker:
            self.clipboard.clear()


class ClipboardWorker(QueuedClipboardWorker):
    def __init__(self, config, ledger, on_local, on_applied, on_status, pasteboard=None):
        super().__init__(config, ledger, on_local, on_applied, on_status, pasteboard or QtPasteboard(), platform_name="Linux")
