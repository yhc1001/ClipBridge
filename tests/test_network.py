import dataclasses
import queue
import socket
import time

import pytest
from PIL import Image

from clipbridge.config import ConfigStore
from clipbridge.files import TransferStore
from clipbridge.images import image_formats
from clipbridge.model import Ledger, Snapshot
from clipbridge.network import NetworkEngine
from clipbridge.security import fingerprint, protect


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(.025)
    raise AssertionError("network timed out")


class Device:
    def __init__(self, config, path, approve=True):
        self.config, self.ledger = config, Ledger(config.device_id)
        self.config_store = ConfigStore(path)
        self.store = TransferStore(path)
        self.received, self.events = queue.Queue(), []
        self.connected = False
        self.approve = approve
        self.engine = None
        self.current = None

    def notify(self, kind, info):
        self.events.append((kind, info))
        if kind == "connected":
            self.connected = info

    def apply(self, snapshot, callback):
        valid = self.ledger.current(snapshot.stamp) and self.config.can_receive()
        if valid:
            self.current = snapshot
            self.received.put(snapshot)
        callback(valid)

    def start(self):
        self.engine = NetworkEngine(self.config, self.ledger, self.store, self.apply, self.notify,
                                    lambda kind, info, future: future.set_result(self.approve), lambda peer: None, self.config_store.save)
        self.engine.start()

    def send(self, formats=None, paths=None):
        snapshot = Snapshot(formats or {}, paths or [], self.ledger.local())
        self.current = snapshot
        self.engine.submit(snapshot)
        return snapshot

    def stop(self):
        if self.engine:
            self.engine.stop()
            assert not self.engine.is_alive()


@pytest.fixture
def pair(tmp_path):
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        port = stream.getsockname()[1]
    a_config = ConfigStore(tmp_path / "a").load()
    b_config = ConfigStore(tmp_path / "b").load()
    a_config.peer_ip = b_config.peer_ip = "127.0.0.1"
    a_config.bind_ip = "127.0.0.1"
    a_config.port = b_config.port = port
    b_config.role = "server"
    b_config.peer_id, b_config.peer_pin, b_config.protected_secret = a_config.device_id, fingerprint(a_config.cert_pem), protect(a_config.secret)
    a, b = Device(a_config, tmp_path / "a"), Device(b_config, tmp_path / "b")
    a.start()
    b.start()
    wait_for(lambda: a.connected and b.connected)
    assert b.config.device_id in a.config.trusted_peers
    yield a, b
    a.stop()
    b.stop()
    a.store.close()
    b.store.close()


def test_tls_bidirectional_unicode_images_rich_formats(pair):
    a, b = pair
    a.send({"text": "Main → 서버 😀".encode()})
    assert b.received.get(timeout=5).formats["text"] == "Main → 서버 😀".encode()
    b.send({"text": "서버 → Main".encode(), "HTML Format": b"<table>one</table>", "Rich Text Format": b"{\\rtf1 hello}"})
    snapshot = a.received.get(timeout=5)
    assert {"text", "HTML Format", "Rich Text Format"} <= snapshot.formats.keys()
    formats = image_formats(Image.new("RGB", (128, 64), "purple"))
    a.send(formats)
    assert b.received.get(timeout=5).formats == formats
    wait_for(lambda: any(kind == "sent" for kind, _ in a.events))


def test_actual_multifile_and_directory_transfer(pair, tmp_path):
    a, b = pair
    root = tmp_path / "folder"
    root.mkdir()
    (root / "한글.txt").write_text("파일 내용", encoding="utf-8")
    (root / "empty").mkdir()
    other = tmp_path / "large.bin"
    other.write_bytes(bytes(range(256)) * 5000)
    a.send(paths=[str(root), str(other)])
    snapshot = b.received.get(timeout=10)
    assert len(snapshot.paths) == 2
    from pathlib import Path
    assert (Path(snapshot.paths[0]) / "한글.txt").read_text(encoding="utf-8") == "파일 내용"
    assert Path(snapshot.paths[1]).read_bytes() == other.read_bytes()


def test_reconnect_never_replays_existing_or_offline_clipboard(pair):
    a, b = pair
    a.send({"text": b"before disconnect"})
    b.received.get(timeout=5)
    a.stop()
    wait_for(lambda: not b.connected)
    b.send({"text": b"offline copy"})
    a.start()
    wait_for(lambda: a.connected and b.connected, 20)
    time.sleep(.3)
    assert a.received.empty() and b.received.empty()
    b.send({"text": b"after reconnect"})
    assert a.received.get(timeout=5).formats["text"] == b"after reconnect"


def test_file_denial_pause_and_direction(pair, tmp_path):
    a, b = pair
    b.config.paused = True
    a.send({"text": b"paused"})
    time.sleep(.2)
    assert b.received.empty()
    b.config.paused = False
    a.config.direction = b.config.direction = "main_to_server"
    b.send({"text": b"wrong direction"})
    time.sleep(.2)
    assert a.received.empty()
    a.config.direction = b.config.direction = "both"
    b.approve = False
    b.config.file_policy = "ask"
    file = tmp_path / "denied.txt"
    file.write_text("denied")
    a.send(paths=[str(file)])
    wait_for(lambda: any("허용하지" in str(info) for _, info in a.events))
    assert b.received.empty()
    assert not list(b.store.base.iterdir())


def test_wrong_certificate_pin_is_rejected(pair):
    a, b = pair
    b.stop()
    wait_for(lambda: not a.connected)
    b.config.peer_pin = "0" * 64
    b.start()
    wait_for(lambda: any(kind == "status" and "ValueError" in str(info) for kind, info in b.events))
    assert not b.connected


def test_wrong_secret_and_unapproved_device_rejected(pair):
    a, b = pair
    b.stop()
    wait_for(lambda: not a.connected)
    b.events.clear()
    b.config.protected_secret = protect(b"x" * 32)
    b.start()
    wait_for(lambda: any(kind == "status" and "끊김" in str(info) for kind, info in b.events))
    assert not b.connected
    b.stop()
    b.events.clear()
    from clipbridge.security import unprotect
    old_key = unprotect(a.config.trusted_peers[b.config.device_id]["secret"])
    b.config.protected_secret = protect(old_key)
    import uuid
    b.config.device_id = str(uuid.uuid4())
    b.ledger = Ledger(b.config.device_id)
    b.start()
    wait_for(lambda: any(kind == "status" and "끊김" in str(info) for kind, info in b.events))
    assert not b.connected


def test_simultaneous_copy_converges_and_new_copy_cancels_file(pair, tmp_path):
    a, b = pair
    for _ in range(10):
        a_snapshot = Snapshot({"text": b"a"}, [], a.ledger.local())
        b_snapshot = Snapshot({"text": b"b"}, [], b.ledger.local())
        winner = max(a_snapshot.stamp, b_snapshot.stamp)
        a.engine.submit(a_snapshot)
        b.engine.submit(b_snapshot)
        wait_for(lambda: a.ledger.latest == b.ledger.latest == winner)
    while not b.received.empty():
        b.received.get()
    file = tmp_path / "superseded.bin"
    file.write_bytes(b"123" * 3000000)
    a.send(paths=[str(file)])
    a.send({"text": b"latest text"})
    wait_for(lambda: not b.received.empty())
    assert b.received.get(timeout=5).formats["text"] == b"latest text"
