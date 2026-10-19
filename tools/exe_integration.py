"""Packaged EXE <-> independent TLS engine + actual Windows clipboard."""
import os
import queue
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / "tests")]
import win32clipboard as cb
from PIL import Image
from clipbridge.clipboard import raw_data
from clipbridge.config import ConfigStore
from clipbridge.images import image_formats
from clipbridge.security import fingerprint, protect
from test_network import Device, wait_for
from test_windows_clipboard import open_clipboard, put


def read_text():
    try:
        open_clipboard()
        try:
            return cb.GetClipboardData(13) if cb.IsClipboardFormatAvailable(13) else ""
        finally:
            cb.CloseClipboard()
    except Exception:
        return ""


saved = {}
open_clipboard()
try:
    fmt = cb.EnumClipboardFormats(0)
    while fmt:
        if fmt in (13, 15, 8, 17) or fmt >= 0xC000:
            try:
                saved[fmt] = raw_data(fmt, 128 * 1024**2)
            except Exception:
                pass
        fmt = cb.EnumClipboardFormats(fmt)
finally:
    cb.CloseClipboard()

try:
    with tempfile.TemporaryDirectory(prefix="ClipBridge-exe-integration-") as temporary:
        base = Path(temporary)
        store = ConfigStore(base / "ClipBridge")
        local = store.load()
        peer = ConfigStore(base / "peer").load()
        with socket.socket() as stream:
            stream.bind(("127.0.0.1", 0))
            port = stream.getsockname()[1]
        local.role, peer.role = "server", "main"
        local.peer_ip = peer.peer_ip = "127.0.0.1"
        peer.bind_ip = "127.0.0.1"
        local.port = peer.port = port
        local.peer_id, local.peer_pin, local.protected_secret = peer.device_id, fingerprint(peer.cert_pem), protect(peer.secret)
        local.file_policy = "allow"  # Explicit isolated fixture trust; normal UI defaults to ask.
        peer.peer_id = local.device_id
        store.save(local)
        device = Device(peer, base / "peer")
        device.start()
        process = subprocess.Popen([str(root / "dist" / "v1.2.0" / "ClipBridge.exe"), "--background", "--smoke-test", "--smoke-seconds=12"], env=dict(os.environ, LOCALAPPDATA=str(base), CLIPBRIDGE_SMOKE_INSTANCE=str(uuid.uuid4())))
        try:
            wait_for(lambda: device.connected, 15)
            start = time.perf_counter()
            device.send({"text": "EXE 수신 한글 😀".encode()})
            wait_for(lambda: read_text() == "EXE 수신 한글 😀")
            latency = (time.perf_counter() - start) * 1000
            print(f"Packaged EXE TLS -> native Unicode clipboard: PASS ({latency:.0f} ms, loopback)")
            put({"text": "EXE 송신 텍스트".encode()})
            assert device.received.get(timeout=5).formats["text"] == "EXE 송신 텍스트".encode()
            print("Packaged EXE native clipboard -> TLS peer: PASS")
            formats = image_formats(Image.new("RGBA", (64, 48), (20, 60, 90, 128)))
            formats.update({"text": b"rich sample", "HTML Format": b"<b>rich sample</b>", "Rich Text Format": b"{\\rtf1 rich sample}"})
            device.send(formats)
            wait_for(lambda: read_text() == "rich sample")
            open_clipboard()
            try:
                assert raw_data(17, 100000) == formats["DIBV5"]
                assert raw_data(cb.RegisterClipboardFormat("HTML Format"), 1000) == formats["HTML Format"]
                assert raw_data(cb.RegisterClipboardFormat("Rich Text Format"), 1000) == formats["Rich Text Format"]
            finally:
                cb.CloseClipboard()
            print("Packaged EXE PNG/DIB/DIBV5 + HTML/RTF registration: PASS")
            file = base / "source.txt"
            file.write_text("실제 파일 내용", encoding="utf-8")
            device.send(paths=[str(file)])
            def paths():
                open_clipboard()
                try:
                    return list(cb.GetClipboardData(15)) if cb.IsClipboardFormatAvailable(15) else []
                finally:
                    cb.CloseClipboard()
            received = wait_for(paths)
            assert Path(received[0]).read_bytes() == file.read_bytes()
            print("Packaged EXE real file transfer -> native CF_HDROP: PASS")
            time.sleep(.2)
            assert device.received.empty(), "received content must not loop back"
            process.wait(timeout=20)
            assert process.returncode == 0
            assert not list((base / "ClipBridge" / "transfers").iterdir())
            print("Packaged EXE loop prevention / normal shutdown / transfer cleanup: PASS")
        finally:
            if process.poll() is None:
                process.wait(timeout=25)
            device.stop()
            device.store.close()
finally:
    open_clipboard()
    try:
        cb.EmptyClipboard()
        for fmt, data in saved.items():
            cb.SetClipboardData(fmt, data.decode("utf-16-le").rstrip("\0") if fmt == 13 else data)
    finally:
        cb.CloseClipboard()
