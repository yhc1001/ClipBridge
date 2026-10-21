"""Real local TLS connections; no mocked network or file streams."""
import asyncio
import socket
import queue
import json
import time
import uuid
from pathlib import Path

import pytest
from PIL import Image

from clipbridge.config import ConfigStore
from clipbridge.files import ReceiveTransfer, TransferStore, scan_sources
from clipbridge.images import image_formats
from clipbridge.model import Ledger, Snapshot
from clipbridge.security import fingerprint, pairing_token, parse_pairing, protect, unprotect
from test_network import Device, wait_for


@pytest.fixture
def group(tmp_path):
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        port = stream.getsockname()[1]
    hub_config = ConfigStore(tmp_path / "hub").load()
    hub_config.bind_ip, hub_config.port = "127.0.0.1", port
    hub = Device(hub_config, tmp_path / "hub")
    devices = [hub]
    hub.start()
    try:
        for index in range(3):
            config = ConfigStore(tmp_path / str(index)).load()
            config.role, config.peer_ip, config.port = "server", "127.0.0.1", port
            config.peer_id, config.peer_pin, secret = parse_pairing(pairing_token(hub.config))
            config.protected_secret = protect(secret)
            device = Device(config, tmp_path / str(index))
            device.config_store.save(config)
            devices.append(device)
            device.start()
            wait_for(lambda: device.connected and len(hub.engine.sessions) == len(devices) - 1)
        yield devices
    finally:
        for device in devices:
            device.stop()
        for device in devices:
            device.store.close()


def check_delivery(devices, source, formats):
    sent = source.send(formats)
    for device in devices:
        if device is not source:
            received = device.received.get(timeout=8)
            assert received.formats == formats
            assert received.stamp == sent.stamp
    assert source.received.empty()
    return sent


def test_four_devices_relay_text_images_rich_formats_without_echo(group):
    for index, source in enumerate(group):
        check_delivery(group, source, {"text": f"장치 {index} 😀".encode(), "HTML Format": b"<b>rich</b>", "Rich Text Format": b"{\\rtf1 rich}"})
    check_delivery(group, group[1], image_formats(Image.new("RGBA", (48, 24), (10, 20, 30, 40))))
    time.sleep(.2)
    assert all(device.received.empty() for device in group)
    assert len(group[0].engine.sessions) == 3


def test_four_way_simultaneous_copies_converge_to_one_clipboard(group):
    for _ in range(20):
        snapshots = [Snapshot({"text": device.config.device_id.encode()}, [], device.ledger.local()) for device in group]
        winner = max(snapshot.stamp for snapshot in snapshots)
        for device, snapshot in zip(group, snapshots):
            device.current = snapshot
        for device, snapshot in zip(group, snapshots):
            device.engine.submit(snapshot)
        wait_for(lambda: all(device.current and device.current.stamp == winner for device in group))
        assert all(device.ledger.latest == winner for device in group)


def test_offline_client_does_not_interrupt_others_or_replay_on_reconnect(group):
    hub, first, second, offline = group
    offline.stop()
    wait_for(lambda: len(hub.engine.sessions) == 2)
    offline.send({"text": b"offline clipboard"})
    check_delivery([hub, first, second], first, {"text": b"others still connected"})
    offline.start()
    wait_for(lambda: offline.connected and len(hub.engine.sessions) == 3, 20)
    time.sleep(.3)
    assert all(device.received.empty() for device in group)
    check_delivery(group, offline, {"text": b"fresh after reconnect"})


def test_file_relay_independent_recipient_approval_and_multiple_roots(group, tmp_path):
    hub, source, allowed, denied = group
    denied.approve = False
    denied.config.file_policy = "ask"
    folder = tmp_path / "폴더"
    folder.mkdir()
    (folder / "one.txt").write_text("실제 파일", encoding="utf-8")
    (folder / "empty").mkdir()
    binary = tmp_path / "two.bin"
    binary.write_bytes(bytes(range(256)) * 6000)
    sent = source.send(paths=[str(folder), str(binary)])
    for device in (hub, allowed):
        snapshot = device.received.get(timeout=15)
        assert snapshot.stamp == sent.stamp
        assert (Path(snapshot.paths[0]) / "one.txt").read_text(encoding="utf-8") == "실제 파일"
        assert (Path(snapshot.paths[0]) / "empty").is_dir()
        assert Path(snapshot.paths[1]).read_bytes() == binary.read_bytes()
    wait_for(lambda: any("허용하지" in str(info) for _, info in hub.events))
    assert denied.received.empty() and source.received.empty()
    assert not list(denied.store.base.iterdir())
    check_delivery(group, allowed, {"text": b"new copy after files"})


def test_each_device_key_is_unique_consumed_invite_and_origin_spoof_rejected(group, tmp_path):
    hub, client, *_ = group
    keys = [unprotect(record["secret"]) for record in hub.config.trusted_peers.values()]
    assert len(set(keys + [hub.config.secret])) == 4
    assert ConfigStore(hub.config_store.directory).load().trusted_peers == hub.config.trusted_peers
    rogue_config = ConfigStore(tmp_path / "rogue").load()
    rogue_config.role, rogue_config.peer_ip, rogue_config.port = "server", "127.0.0.1", hub.config.port
    rogue_config.peer_id, rogue_config.peer_pin = hub.config.device_id, fingerprint(hub.config.cert_pem)
    rogue_config.protected_secret = protect(client.config.secret)  # Consumed invitation / another device's key.
    rogue = Device(rogue_config, tmp_path / "rogue")
    try:
        rogue.start()
        wait_for(lambda: any("끊김" in str(info) for _, info in rogue.events))
        assert not rogue.connected and len(hub.config.trusted_peers) == 3
    finally:
        rogue.stop()
        rogue.store.close()
    # A valid client cannot forge a different origin, even though hubs may relay it.
    session = next(iter(client.engine.sessions.values()))
    forged = Snapshot({"text": b"spoof"})
    future = asyncio.run_coroutine_threadsafe(session.send({"type": "clipboard", "id": str(uuid.uuid4()),
        "stamp": [hub.ledger.clock + 100, str(uuid.uuid4())], "formats": forged.wire(), "digest": forged.digest()}), client.engine.loop)
    future.result(5)
    wait_for(lambda: any("ValueError" in str(info) for _, info in hub.events))
    assert all(device.received.empty() for device in group)


def test_one_pending_file_approval_does_not_block_other_recipients_or_new_text(group, tmp_path):
    hub, source, waiting, other = group
    pending = queue.Queue()
    waiting.engine.approve = lambda kind, info, future: pending.put(future)
    waiting.config.file_policy = "ask"
    file = tmp_path / "pending.txt"
    file.write_bytes(b"file content")
    source.send(paths=[str(file)])
    hub.received.get(timeout=10)
    other.received.get(timeout=10)
    approval = pending.get(timeout=10)
    assert not approval.done() and waiting.received.empty()
    check_delivery(group, source, {"text": b"new text while waiting"})
    wait_for(approval.cancelled)
    assert not list(waiting.store.base.iterdir())


def test_file_permission_remembered_for_origin_is_not_shared_with_other_devices(group, tmp_path):
    hub, source, allowed, denied = group
    allowed.approve = denied.approve = False
    allowed.config.file_policy = denied.config.file_policy = "ask"
    allowed.config.file_allow_ids.append(source.config.device_id)
    file = tmp_path / "allowed.txt"
    file.write_bytes(b"per origin")
    source.send(paths=[str(file)])
    hub.received.get(timeout=10)
    snapshot = allowed.received.get(timeout=10)
    assert Path(snapshot.paths[0]).read_bytes() == b"per origin"
    wait_for(lambda: any("허용하지" in str(info) for _, info in hub.events))
    assert denied.received.empty()


def test_hub_restart_keeps_approvals_no_clipboard_replay(group):
    hub, *clients = group
    check_delivery(group, clients[0], {"text": b"before hub restart"})
    hub.stop()
    wait_for(lambda: all(not client.connected for client in clients))
    hub.config = hub.config_store.load()
    hub.ledger = Ledger(hub.config.device_id)
    hub.start()
    wait_for(lambda: len(hub.engine.sessions) == 3 and all(client.connected for client in clients), 20)
    time.sleep(.3)
    assert all(device.received.empty() for device in group)
    check_delivery(group, hub, {"text": b"after hub restart"})


def test_revoked_device_cannot_reconnect_using_old_key(group):
    hub, removed, *remaining = group
    removed.stop()
    wait_for(lambda: len(hub.engine.sessions) == 2)
    hub.stop()
    del hub.config.trusted_peers[removed.config.device_id]
    hub.config_store.save(hub.config)
    hub.start()
    removed.events.clear()
    removed.start()
    wait_for(lambda: any("끊김" in str(info) for _, info in removed.events))
    assert not removed.connected
    wait_for(lambda: len(hub.engine.sessions) == 2 and all(device.connected for device in remaining), 20)
    check_delivery([hub, *remaining], remaining[0], {"text": b"remaining devices"})


def test_legacy_one_to_one_config_migrates_without_losing_key(tmp_path):
    store = ConfigStore(tmp_path)
    config = store.load()
    original_key = config.secret
    peer = str(uuid.uuid4())
    config.peer_id, config.peer_ip = peer, "192.168.1.2"
    config.file_policy = "allow"
    store.save(config)
    loaded = store.load()
    assert unprotect(loaded.trusted_peers[peer]["secret"]) == original_key
    assert loaded.secret != original_key and loaded.peer_id == ""
    assert loaded.file_policy == "allow"
    assert store.load().trusted_peers == loaded.trusted_peers


def test_relay_file_lease_survives_replacement_until_all_recipients_finish(tmp_path):
    store = TransferStore(tmp_path)
    source = tmp_path / "source.txt"
    source.write_bytes(b"old")
    manifest, _ = scan_sources([str(source)], 100)
    first = ReceiveTransfer(store.base, str(uuid.uuid4()), manifest)
    first.chunk("source.txt", 0, b"old")
    store.retain(first)
    leases = [store.pin(first.finish()), store.pin(first.finish())]
    second = ReceiveTransfer(store.base, str(uuid.uuid4()), manifest)
    second.chunk("source.txt", 0, b"old")
    store.retain(second)
    store.release(leases[0])
    assert first.directory.exists()
    store.release(leases[1])
    assert not first.directory.exists() and second.directory.exists()
    store.close()
    assert not list(store.base.iterdir())


@pytest.mark.parametrize("role", ["main", "server"])
def test_old_always_allow_file_setting_stays_automatic_after_upgrade(tmp_path, role):
    store = ConfigStore(tmp_path)
    config = store.load()
    config.role, config.peer_id, config.file_policy = role, str(uuid.uuid4()), "allow"
    store.save(config)
    old = json.loads(store.path.read_text(encoding="utf-8"))
    del old["trusted_peers"], old["file_allow_ids"], old["file_policy_version"]
    store.path.write_text(json.dumps(old), encoding="utf-8")
    migrated = store.load()
    assert migrated.file_policy == "allow"


def test_default_file_sharing_between_all_devices_never_requests_approval(group, tmp_path):
    approvals = []
    def reject_any_prompt(kind, info, future):
        approvals.append(kind)
        future.set_result(False)
    for device in group:
        device.engine.approve = reject_any_prompt
    for index, source in enumerate(group):
        file = tmp_path / f"automatic-{index}.txt"
        file.write_bytes(f"automatic file {index}".encode())
        sent = source.send(paths=[str(file)])
        for receiver in group:
            if receiver is not source:
                snapshot = receiver.received.get(timeout=10)
                assert snapshot.stamp == sent.stamp
                assert Path(snapshot.paths[0]).read_bytes() == file.read_bytes()
        assert source.received.empty()
    assert approvals == []


@pytest.mark.parametrize("previous,expected", [("ask", "allow"), ("allow", "allow"), ("block", "block")])
def test_old_file_policy_upgrades_once_then_preserves_explicit_user_choice(tmp_path, previous, expected):
    store = ConfigStore(tmp_path)
    config = store.load()
    config.file_policy = previous
    config.files = False
    store.save(config)
    old = json.loads(store.path.read_text(encoding="utf-8"))
    del old["file_policy_version"]
    store.path.write_text(json.dumps(old), encoding="utf-8")
    loaded = store.load()
    assert loaded.file_policy == expected and not loaded.files
    assert loaded.protected_secret == config.protected_secret
    assert loaded.peer_id == config.peer_id
    assert json.loads(store.path.read_text(encoding="utf-8"))["file_policy_version"] == 1
    loaded.file_policy = "ask"
    store.save(loaded)
    assert store.load().file_policy == "ask"
