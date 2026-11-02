"""File-copy regressions use synthetic clipboards and private loopback TLS only."""
import asyncio
import hashlib
import os
import queue
import sys
import threading
import uuid
from pathlib import Path

import pytest

from clipbridge.config import Config
from clipbridge.files import ReceiveTransfer, scan_sources, validate_manifest
from clipbridge.model import Ledger, Snapshot, Stamp
from test_network import pair, wait_for
from test_multidevice import group
from test_portability import qt_app


@pytest.mark.skipif(sys.platform != "win32", reason="Windows clipboard backend")
def test_delayed_hdrop_render_is_one_copy_not_a_second_cancellation(monkeypatch):
    from clipbridge import clipboard_win as backend
    config, local, counter = Config(), queue.Queue(), [1]
    worker = backend.ClipboardWorker(config, Ledger(config.device_id), local.put, lambda _: None, lambda _: None)
    monkeypatch.setattr(backend, "sequence", lambda: counter[0])
    monkeypatch.setattr(backend.cb, "OpenClipboard", lambda *_: None)
    monkeypatch.setattr(backend.cb, "CloseClipboard", lambda: None)
    monkeypatch.setattr(backend.cb, "IsClipboardFormatAvailable", lambda fmt: fmt == 15)
    def raw(fmt, limit):
        if fmt != 15:
            raise ValueError("unavailable")
        return b"synthetic drop metadata"
    monkeypatch.setattr(backend, "raw_data", raw)
    def render(_):
        counter[0] += 1  # GetClipboardData can render a delayed shell format.
        return ("C:/synthetic/file.txt",)
    monkeypatch.setattr(backend.cb, "GetClipboardData", render)
    worker._capture()
    first = local.get(timeout=1)
    worker._capture()
    assert first.sequence == counter[0]
    assert local.empty(), "rendering the same copy must not restart its transfer"


def test_temporarily_busy_source_retries_without_another_ctrl_c(pair, monkeypatch, tmp_path):
    import clipbridge.network as network
    original, calls = network.scan_sources, []
    def busy_once(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise PermissionError("synthetic temporary file lock")
        return original(*args, **kwargs)
    monkeypatch.setattr(network, "scan_sources", busy_once)
    source = tmp_path / "busy.txt"
    source.write_bytes(b"file after a temporary lock")
    a, b = pair
    a.send(paths=[str(source)])
    received = b.received.get(timeout=5)
    assert Path(received.paths[0]).read_bytes() == source.read_bytes()
    assert len(calls) == 2


def test_one_directory_scan_per_copy_even_with_three_recipients(group, monkeypatch, tmp_path):
    import clipbridge.network as network
    original, calls = network.scan_sources, []
    def counted(paths, *args, **kwargs):
        calls.append(tuple(paths))
        return original(paths, *args, **kwargs)
    monkeypatch.setattr(network, "scan_sources", counted)
    hub, *clients = group
    source = tmp_path / "shared.bin"
    source.write_bytes(bytes(range(256)) * 5000)
    hub.send(paths=[str(source)])
    for client in clients:
        received = client.received.get(timeout=10)
        assert Path(received.paths[0]).read_bytes() == source.read_bytes()
    assert calls == [(str(source),)]


def test_new_file_protocol_never_pre_reads_source_bytes(pair, monkeypatch, tmp_path):
    a, b = pair
    source = tmp_path / "single-pass.bin"
    data = bytes(range(256)) * 5000
    source.write_bytes(data)
    original, read_bytes = Path.open, [0]
    class Counted:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def read(self, *args):
            result = self.stream.read(*args)
            read_bytes[0] += len(result)
            return result
    def opened(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        return Counted(result) if path == source and args and args[0] == "rb" else result
    monkeypatch.setattr(Path, "open", opened)
    a.send(paths=[str(source)])
    received = b.received.get(timeout=10)
    assert Path(received.paths[0]).read_bytes() == data
    assert read_bytes[0] == len(data), "a copy must be hashed while sending, not pre-read in full"


def test_streamed_file_hashes_required_before_exposing_paths(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"verified bytes")
    manifest, _ = scan_sources([str(source)], 100, hash_files=False)
    validate_manifest(manifest, 100, streaming=True)
    with pytest.raises(ValueError):
        validate_manifest(manifest, 100)  # Never weaken the legacy protocol.
    transfer = ReceiveTransfer(tmp_path, str(uuid.uuid4()), manifest, streaming=True)
    try:
        transfer.chunk("source.bin", 0, b"verified bytes")
        for hashes in (None, {}, {"source.bin": "0" * 64}, {"source.bin": "bad"},
                       {"source.bin": hashlib.sha256(b"verified bytes").hexdigest(), "extra": "0" * 64}):
            with pytest.raises(ValueError):
                transfer.finish(hashes)
        assert transfer.finish({"source.bin": hashlib.sha256(b"verified bytes").hexdigest()})
    finally:
        transfer.remove()


def test_legacy_file_peer_still_gets_prehashed_protocol(pair, tmp_path):
    a, b = pair
    for sender, receiver in ((a, b), (b, a)):
        async def legacy():
            sender.engine.sessions[receiver.config.device_id].caps["file_stream"] = False
        asyncio.run_coroutine_threadsafe(legacy(), sender.engine.loop).result(5)
        source = tmp_path / (sender.config.device_id + ".txt")
        source.write_bytes(b"old protocol still verified")
        sender.send(paths=[str(source)])
        snapshot = receiver.received.get(timeout=10)
        assert Path(snapshot.paths[0]).read_bytes() == source.read_bytes()


def test_file_open_lock_after_offer_is_retried(pair, monkeypatch, tmp_path):
    a, b = pair
    source = tmp_path / "locked-at-open.txt"
    source.write_bytes(b"retry without a second copy")
    original, attempts = Path.open, []
    def opened(path, *args, **kwargs):
        if path == source and args and args[0] == "rb":
            attempts.append(True)
            if len(attempts) == 1:
                raise PermissionError("synthetic short lock")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", opened)
    a.send(paths=[str(source)])
    received = b.received.get(timeout=5)
    assert Path(received.paths[0]).read_bytes() == b"retry without a second copy"
    assert len(attempts) == 2


def test_corrupt_final_file_hash_never_reaches_clipboard_and_cleans_stage(pair, monkeypatch, tmp_path):
    from clipbridge.network import Session
    a, b = pair
    source = tmp_path / "corrupt.txt"
    source.write_bytes(b"bytes with a deliberately wrong final hash")
    original = Session.send
    async def corrupt(session, value):
        if value.get("type") == "file_end":
            value = dict(value, hashes={source.name: "0" * 64})
        await original(session, value)
    monkeypatch.setattr(Session, "send", corrupt)
    a.send(paths=[str(source)])
    wait_for(lambda: any("ValueError" in str(info) for _, info in b.events))
    assert b.received.empty() and b.current is None
    assert not list(b.store.base.iterdir())


def test_zero_byte_files_and_empty_directories_in_both_directions(pair, tmp_path):
    a, b = pair
    for source, receiver in ((a, b), (b, a)):
        folder = tmp_path / source.config.device_id
        folder.mkdir()
        (folder / "zero.txt").touch()
        (folder / "empty").mkdir()
        source.send(paths=[str(folder)])
        received = receiver.received.get(timeout=5)
        assert (Path(received.paths[0]) / "zero.txt").read_bytes() == b""
        assert (Path(received.paths[0]) / "empty").is_dir()


@pytest.mark.parametrize("streaming", [True, False])
def test_file_changed_during_send_aborts_and_removes_unfinished_stage(pair, monkeypatch, tmp_path, streaming):
    from clipbridge.network import Session
    a, b = pair
    source = tmp_path / "changing.bin"
    source.write_bytes(b"a" * (256 * 1024 * 3))
    async def configure():
        a.engine.sessions[b.config.device_id].caps["file_stream"] = streaming
    asyncio.run_coroutine_threadsafe(configure(), a.engine.loop).result(5)
    original, changed = Session.send, []
    async def change(session, value):
        await original(session, value)
        if value.get("type") == "file_chunk" and not changed:
            changed.append(True)
            info = source.stat()
            source.write_bytes(b"b" * info.st_size)
            os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    monkeypatch.setattr(Session, "send", change)
    a.send(paths=[str(source)])
    wait_for(lambda: any("ValueError" in str(info) for _, info in a.events))
    wait_for(lambda: not list(b.store.base.iterdir()))
    assert changed and b.received.empty()
    a.send({"text": b"connection still usable"})
    assert b.received.get(timeout=5).formats["text"] == b"connection still usable"


def test_permanent_source_lock_has_bounded_retry_and_next_copy_works(pair, monkeypatch, tmp_path):
    a, b = pair
    source = tmp_path / "permanently-locked.txt"
    source.write_bytes(b"unavailable")
    original, attempts = Path.open, []
    def opened(path, *args, **kwargs):
        if path == source and args and args[0] == "rb":
            attempts.append(True)
            raise PermissionError("synthetic persistent lock")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", opened)
    a.send(paths=[str(source)])
    wait_for(lambda: any("PermissionError" in str(info) for _, info in a.events))
    wait_for(lambda: not list(b.store.base.iterdir()))
    assert len(attempts) == 5 and b.received.empty()
    a.send({"text": b"next copy works"})
    assert b.received.get(timeout=5).formats["text"] == b"next copy works"


def test_repeated_same_path_edits_and_bidirectional_small_file_bursts(pair, tmp_path):
    a, b = pair
    source = tmp_path / "recopy.txt"
    for index in range(24):
        sender, receiver = (a, b) if index % 2 else (b, a)
        data = f"fresh copy {index}".encode()
        source.write_bytes(data)
        sender.send(paths=[str(source)])
        snapshot = receiver.received.get(timeout=5)
        assert Path(snapshot.paths[0]).read_bytes() == data
        wait_for(lambda: any(kind == "sent" for kind, _ in sender.events))
    assert a.received.empty() and b.received.empty()


def test_queued_receive_wakes_without_waiting_for_poll(qt_app):
    from clipbridge.clipboard_macos import ClipboardWorker
    from test_portability import FakePasteboard, pump
    config, board, applied = Config(), FakePasteboard(), []
    ledger = Ledger(config.device_id)
    worker = ClipboardWorker(config, ledger, lambda _: None, lambda _: None, lambda _: None, board)
    # Deliberately leave its polling timer stopped. A queued receive must wake
    # the UI loop itself, including on macOS and Linux.
    stamp = Stamp(1, str(uuid.uuid4()))
    ledger.claim(stamp)
    try:
        worker.apply(Snapshot({"text": b"immediate receive"}, [], stamp, board.count()), applied.append)
        pump(qt_app, lambda: bool(applied))
        assert applied == [True] and board.formats["text"] == b"immediate receive"
    finally:
        worker.stop()


def test_superseded_preparation_cannot_deliver_old_file(pair, monkeypatch, tmp_path):
    import clipbridge.network as network
    original, started = network.scan_sources, threading.Event()
    def slow(paths, limit, cancelled, **kwargs):
        started.set()
        assert threading.Event().wait(.12) is False
        return original(paths, limit, cancelled, **kwargs)
    monkeypatch.setattr(network, "scan_sources", slow)
    a, b = pair
    source = tmp_path / "superseded.txt"
    source.write_bytes(b"old")
    a.send(paths=[str(source)])
    assert started.wait(3)
    a.send({"text": b"newer copy wins immediately"})
    assert b.received.get(timeout=3).formats["text"] == b"newer copy wins immediately"
    wait_for(lambda: not a.engine.sessions[b.config.device_id].tasks)
    assert b.received.empty()
    assert not list(b.store.base.iterdir())
