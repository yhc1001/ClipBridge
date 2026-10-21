import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

if not sys.platform.startswith("linux"):
    pytest.skip("Linux native clipboard", allow_module_level=True)

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QGuiApplication
from clipbridge.clipboard_linux import QtPasteboard
from clipbridge.config import Config
from clipbridge.model import Snapshot
from test_portability import qt_app, pump


def test_actual_x11_clipboard_unicode_html_and_local_file_urls(qt_app, tmp_path):
    board = QtPasteboard()
    path = tmp_path / "파일 # one.txt"
    path.write_bytes(b"file bytes")
    board.write(Snapshot({"text": "Linux 네이티브 😀".encode(), "HTML Format": b"<b>native</b>", "Rich Text Format": b"{\\rtf1 native}"}, [str(path)]), "native-test")
    qt_app.processEvents()
    formats, paths, marker = board.read(Config())
    assert formats["text"].decode() == "Linux 네이티브 😀"
    assert paths == [str(path)] and Path(paths[0]).read_bytes() == b"file bytes"
    assert marker == "native-test" and b"<b>native</b>" in formats["HTML Format"]
    board.clear_if_marker(marker)


def test_separate_x11_application_copy_detected_in_background(qt_app):
    import shutil
    if not shutil.which("xclip"):
        pytest.skip("xclip is needed for external-owner verification")
    board = QtPasteboard()
    initial = board.count()
    process = subprocess.Popen(["xclip", "-selection", "clipboard", "-in"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process.communicate("외부 X11 복사".encode(), timeout=5)
    pump(qt_app, lambda: board.count() != initial)
    assert board.read(Config())[0]["text"].decode() == "외부 X11 복사"
    board.write(Snapshot({"text": b"release external clipboard owner"}), "cleanup")
    board.clear_if_marker("cleanup")


def test_linux_local_key_owner_permissions_and_roundtrip(monkeypatch, tmp_path):
    from clipbridge import linux_security
    monkeypatch.setattr(linux_security, "key_path", lambda: tmp_path / "secret" / "local.key")
    key = linux_security.local_key()
    assert len(key) == 32 and (tmp_path / "secret" / "local.key").stat().st_mode & 0o077 == 0
    protected = linux_security.protect(b"native secret")
    assert linux_security.unprotect(protected) == b"native secret"
