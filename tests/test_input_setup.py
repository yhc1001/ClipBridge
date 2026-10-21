"""Real loopback TLS enrollment/layout/reconnect; no native input or clipboard."""
import copy
import queue
import socket
import time
import pytest

from clipbridge.config import ConfigStore
from clipbridge.input_engine import defaults
from clipbridge.input_setup import InputSetup, certificate_pin, identity, layout_settings


def wait(predicate, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError("Input setup did not converge")


class Device:
    def __init__(self, path, name, approve=True, port=0):
        self.store = ConfigStore(path)
        self.config = self.store.load()
        if not self.config.input_settings:
            self.config.input_settings = {**defaults(), "name": name, "screens": [{"name": name, "x": 1, "y": 1}]}
        self.events, self.approvals, self.shown = [], [], 0
        def apply(value, show, clipboard):
            self.config.input_settings = copy.deepcopy(value)
            for key, item in (clipboard or {}).items():
                setattr(self.config, key, copy.deepcopy(item))
            self.store.save(self.config)
            self.shown += int(show)
        def approval(kind, info, future):
            assert kind == "input_pair"
            self.approvals.append(info)
            if callable(approve):
                approve(info, future)
            else:
                future.set_result(approve)
        self.engine = InputSetup(self.config, apply, lambda kind, info: self.events.append((kind, info)), approval, bind="127.0.0.1", port=port)
        self.engine.start()
        assert self.engine.ready.wait(5)
        assert self.engine.last_error is None

    @property
    def data(self):
        return self.config.input_settings

    def join(self, host):
        self.engine.connect_to("127.0.0.1", host.engine.port).result(3)

    def stop(self):
        self.engine.stop()
        assert not self.engine.is_alive()


@pytest.fixture
def devices(tmp_path):
    values = []
    def create(name, approve=True):
        device = Device(tmp_path / str(len(values)), name, approve)
        values.append(device)
        return device
    yield create
    for device in reversed(values):
        device.stop()


def test_ip_approval_automatically_registers_pins_roles_screens_on_both_pcs(devices):
    host, client = devices("Main"), devices("newserver")
    client.join(host)
    wait(lambda: client.data.get("easy_controller") == host.config.device_id and client.shown == 1)
    assert len(host.approvals) == 1 and host.shown == client.shown == 1
    assert host.approvals[0]["code"] in " ".join(str(info) for _, info in client.events)
    assert host.data["mode"] == "server" and client.data["mode"] == "client"
    assert host.data["enabled"] and client.data["enabled"]
    assert host.data["screens"] == client.data["screens"]
    assert client.data["trusted_servers"] == [certificate_pin(identity(host.config)[0])]
    assert host.data["trusted_clients"] == [certificate_pin(identity(client.config)[0])]
    assert client.config.peer_id == host.config.device_id
    assert client.config.peer_pin == __import__("clipbridge.security", fromlist=["fingerprint"]).fingerprint(host.config.cert_pem)
    assert client.config.role == "server" and host.config.role == "main"
    from clipbridge.security import unprotect
    assert client.config.secret == unprotect(host.config.trusted_peers[client.config.device_id]["secret"])
    # The saved topology makes native screen links in both directions.
    from clipbridge.input_engine import server_configuration
    output = server_configuration(host.data)
    assert "right = newserver" in output and "left = Main" in output


def test_three_pcs_share_layout_and_client_can_move_screens_without_renaming(devices):
    host, one, two = devices("Main"), devices("Client"), devices("Client")
    one.join(host)
    wait(lambda: one.data.get("easy_controller"))
    two.join(host)
    wait(lambda: len(one.data["screens"]) == len(two.data["screens"]) == 3)
    assert len({item["name"] for item in host.data["screens"]}) == 3
    screens = [{"name": item["name"], "x": i, "y": 2} for i, item in enumerate(one.data["screens"])]
    one.engine.change_layout(screens, one.data["easy_revision"]).result(3)
    wait(lambda: host.data["screens"] == one.data["screens"] == two.data["screens"] == screens)
    bad = copy.deepcopy(screens)
    bad[-1]["name"] = "not-enrolled"
    with pytest.raises(ValueError):
        one.engine.change_layout(bad, one.data["easy_revision"]).result(3)


def test_denied_request_does_not_add_trust_enable_input_or_reprompt(devices):
    host, client = devices("Main", approve=False), devices("Other")
    client.join(host)
    wait(lambda: len(host.approvals) == 1)
    wait(lambda: any("거절" in str(info) for _, info in client.events))
    assert not host.data["enabled"] and not client.data.get("easy_controller")
    assert not host.data["trusted_clients"]
    time.sleep(.25)
    assert len(host.approvals) == 1


def test_remembered_tls_connection_reconnects_without_second_approval_and_revokes(devices):
    host, client = devices("Main"), devices("Other")
    client.join(host)
    wait(lambda: client.data.get("easy_controller"))
    port = host.engine.port
    host.stop()
    # Start a new controller thread with exactly the persisted identity/config.
    host.engine = InputSetup(host.config, lambda value, show, clipboard: setattr(host.config, "input_settings", copy.deepcopy(value)),
        lambda *args: None, lambda *args: pytest.fail("Remembered device asked again"), bind="127.0.0.1", port=port)
    host.engine.start()
    assert host.engine.ready.wait(5)
    wait(lambda: client.config.device_id in host.engine.clients)
    host.engine.disconnect(client.data["name"]).result(5)
    wait(lambda: not client.data.get("easy_controller"))
    assert not client.data["enabled"] and not host.data["trusted_clients"]


def test_changed_client_key_and_server_pin_are_rejected(devices):
    host, client, impostor = devices("Main"), devices("Other"), devices("Impostor")
    client.join(host)
    wait(lambda: client.data.get("easy_controller"))
    client.stop()
    impostor.config.device_id = client.config.device_id
    impostor.join(host)
    wait(lambda: any("인증서가 달라" in str(info) for _, info in impostor.events))
    assert len(host.approvals) == 1


def test_rejects_layout_gaps_commands_and_public_addresses(devices):
    host = devices("Main")
    with pytest.raises(ValueError):
        host.engine.connect_to("8.8.8.8")
    current = {**defaults(), "name": "Main", "screens": [{"name": "Main", "x": 1, "y": 1}, {"name": "Other", "x": 2, "y": 1}]}
    with pytest.raises(ValueError):
        layout_settings(current, [{"name": "Main", "x": 1, "y": 1}, {"name": "Other", "x": 4, "y": 4}])
    with pytest.raises(ValueError):
        layout_settings(current, [{"name": "Main", "x": 1, "y": 1, "command": "bad"}, {"name": "Other", "x": 2, "y": 1}])


def test_one_approval_enables_real_clipboard_and_file_tls_without_second_code_or_prompt(devices, tmp_path):
    from test_network import Device as ClipboardDevice
    from clipbridge.images import image_formats
    from PIL import Image
    from pathlib import Path
    host, client = devices("Main"), devices("Other")
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        host.config.port = stream.getsockname()[1]
    host.config.bind_ip = "127.0.0.1"
    host.config.mouse_enabled = client.config.mouse_enabled = False
    client.join(host)
    wait(lambda: client.engine.client_writer)
    assert not host.data["enabled"] and not client.data["enabled"]
    a = ClipboardDevice(host.config, tmp_path / "clip-main", approve=False)
    b = ClipboardDevice(client.config, tmp_path / "clip-other", approve=False)
    a.start()
    b.start()
    try:
        wait(lambda: a.connected and b.connected)
        a.send({"text": "한 번 승인한 연결 😀".encode()})
        assert b.received.get(timeout=5).formats["text"] == "한 번 승인한 연결 😀".encode()
        formats = image_formats(Image.new("RGB", (16, 12), "blue"))
        b.send(formats)
        assert a.received.get(timeout=5).formats == formats
        source = tmp_path / "실제 파일.txt"
        source.write_text("자동 파일 전송", encoding="utf-8")
        a.send(paths=[str(source)])
        assert Path(b.received.get(timeout=8).paths[0]).read_bytes() == source.read_bytes()
        assert len(host.approvals) == 1
    finally:
        a.stop()
        b.stop()
        a.store.close()
        b.store.close()


def test_three_unified_pcs_relay_every_direction_even_with_legacy_one_way_settings(devices, tmp_path):
    from test_network import Device as ClipboardDevice
    from clipbridge.images import image_formats
    from PIL import Image
    from pathlib import Path
    setups = [devices(name) for name in ("Main", "newserver", "Laptop")]
    host = setups[0]
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        host.config.port = free.getsockname()[1]
    host.config.bind_ip = "127.0.0.1"
    for device in setups:
        device.config.direction = "main_to_server"
        device.config.mouse_enabled = False
    for participant in setups[1:]:
        participant.join(host)
        wait(lambda: participant.engine.client_writer)
    wait(lambda: all(len(device.data["screens"]) == 3 for device in setups))
    assert all(device.config.direction == "both" for device in setups)
    clips = [ClipboardDevice(device.config, tmp_path / f"clip-{i}", approve=False) for i, device in enumerate(setups)]
    try:
        for device in clips:
            device.start()
        wait(lambda: all(device.connected for device in clips) and clips[0].connected == 2)
        for index, sender in enumerate(clips):
            formats = {"text": f"three PC source {index}".encode(), "HTML Format": b"<b>formatted</b>"}
            sender.send(formats)
            for receiver in clips:
                if receiver is not sender:
                    assert receiver.received.get(timeout=8).formats == formats
            formats = image_formats(Image.new("RGB", (18, 12), (index * 80, 40, 90)))
            sender.send(formats)
            for receiver in clips:
                if receiver is not sender:
                    assert receiver.received.get(timeout=8).formats == formats
            folder = tmp_path / f"folder-{index}"
            folder.mkdir()
            (folder / "한글.txt").write_bytes(f"folder payload {index}".encode())
            source = tmp_path / f"file-{index}.bin"
            source.write_bytes(bytes([index]) * 600000)
            sender.send(paths=[str(folder), str(source)])
            for receiver in clips:
                if receiver is not sender:
                    received = receiver.received.get(timeout=10)
                    assert (Path(received.paths[0]) / "한글.txt").read_bytes() == (folder / "한글.txt").read_bytes()
                    assert Path(received.paths[1]).read_bytes() == source.read_bytes()
            assert sender.received.empty()
        assert len(host.approvals) == 2
    finally:
        for device in clips:
            device.stop()
        for device in clips:
            device.store.close()


@pytest.mark.parametrize("unified", [False, True])
def test_loading_unified_groups_restores_bidirectional_but_preserves_legacy_choice(tmp_path, unified):
    import uuid
    store = ConfigStore(tmp_path)
    config = store.load()
    config.direction = "main_to_server"
    if unified:
        config.input_settings = {"easy_controller": str(uuid.uuid4())}
    store.save(config)
    loaded = store.load()
    assert loaded.direction == ("both" if unified else "main_to_server")
    assert store.load().direction == loaded.direction


def test_canceled_approval_cannot_enroll_after_client_exits(devices):
    pending = []
    host = devices("Main", approve=lambda info, future: pending.append(future))
    client = devices("Other")
    client.join(host)
    wait(lambda: pending)
    client.stop()
    wait(lambda: pending[0].cancelled())
    assert not host.data.get("easy_peers") and not host.config.trusted_peers


def test_signature_is_bound_to_server_and_client_certificates_and_fresh_challenge(devices):
    from clipbridge.input_setup import transcript, signature, verify_signature
    from cryptography.exceptions import InvalidSignature
    one, two = devices("One"), devices("Two")
    cert, key = identity(one.config)
    challenge = {"device": two.config.device_id, "nonce": "a" * 64}
    original = transcript(challenge, one.config.device_id, "One", "b" * 64, "c" * 64, certificate_pin(cert))
    signed = signature(key, original)
    verify_signature(cert, original, signed)
    changed = transcript(challenge, one.config.device_id, "One", "b" * 64, "d" * 64, certificate_pin(cert))
    with pytest.raises(InvalidSignature):
        verify_signature(cert, changed, signed)
