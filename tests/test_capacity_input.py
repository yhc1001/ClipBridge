import dataclasses
import json
from pathlib import Path
import uuid

import pytest
from PySide6.QtCore import QSettings

from clipbridge.config import ConfigStore
from clipbridge.input_engine import connection_code, defaults, parse_code, prepare_profile, server_configuration, validate
from tools.legacy_input import import_profile
from clipbridge.model import CHUNK, MAX_TOTAL, Snapshot, Stamp
from clipbridge.streaming import ClipboardAssembly
from test_network import pair
from test_network import wait_for
from test_multidevice import group, check_delivery
from test_portability import qt_app


def test_streamed_multi_megabyte_clipboard_both_directions_and_relay(pair):
    a, b = pair
    payload = ("큰 클립보드 😀\n" * 180000).encode()
    for source, receiver in ((a, b), (b, a)):
        source.send({"text": payload, "Rich Text Format": b"{\\rtf1 big}"})
        received = receiver.received.get(timeout=15)
        assert received.formats["text"] == payload
        assert receiver.engine.sessions


def test_stream_manifest_limits_chunk_offsets_hash_and_truncation():
    snapshot = Snapshot({"text": b"large text"})
    stamp = Stamp(1, str(uuid.uuid4()))
    def create(limit=100):
        return ClipboardAssembly(str(uuid.uuid4()), stamp, 1, {"text": 10}, snapshot.digest(), limit)
    with pytest.raises(ValueError):
        create(9)
    received = create()
    with pytest.raises(ValueError):
        received.chunk("text", 1, b"large")
    received.chunk("text", 0, b"large")
    with pytest.raises(ValueError):
        received.finish()
    received.chunk("text", 5, b" text")
    assert received.finish().formats == snapshot.formats
    received = create()
    received.chunk("text", 0, b"wrong text")
    with pytest.raises(ValueError):
        received.finish()


def test_capacity_migration_and_large_file_range(tmp_path):
    store = ConfigStore(tmp_path)
    config = store.load()
    assert config.clip_limit_mb == 256 and config.file_limit_mb == 16384
    value = json.loads(store.path.read_text(encoding="utf-8"))
    value.pop("limits_version")
    value.update(clip_limit_mb=96, file_limit_mb=512)
    store.path.write_text(json.dumps(value), encoding="utf-8")
    updated = store.load()
    assert updated.clip_limit_mb == 256 and updated.file_limit_mb == 16384
    updated.file_limit_mb = 1024 * 1024
    updated.clip_limit_mb = 512
    store.save(updated)
    assert store.load().file_limit == MAX_TOTAL
    updated.file_limit_mb += 1
    with pytest.raises(ValueError):
        updated.validate(False)


def test_deskflow_configuration_layout_tls_and_command_blocking(qt_app, tmp_path):
    config = ConfigStore(tmp_path / "data").load()
    settings = defaults()
    settings.update(name="Main", mode="server", screens=[{"name": "Main", "x": 1, "y": 0}, {"name": "Linux", "x": 2, "y": 0}],
        trusted_clients=["a" * 64])
    output = server_configuration(settings)
    assert "right = Linux" in output and "left = Main" in output
    engine = tmp_path / "deskflow-core.exe"
    engine.write_bytes(b"fixture; never executed")
    settings["engine"] = str(engine)
    program, args, environment = prepare_profile(config, settings, tmp_path / "runtime")
    native = QSettings(str(tmp_path / "runtime" / "settings" / "Deskflow.conf"), QSettings.Format.IniFormat)
    assert native.value("security/tlsEnabled", type=bool)
    assert native.value("security/checkPeerFingerprints", type=bool)
    assert not native.value("core/enableEnterCommand", type=bool)
    assert not native.value("core/enableExitCommand", type=bool)
    assert not native.value("server/enableClipboard", type=bool)
    assert native.value("computer_Main/name") == "Main" and native.value("computer_Linux/name") == "Linux"
    assert native.value("server/enableSwitchDelay", type=bool) and native.value("server/switchDelay", type=int) == 250
    assert "--settings" in args and "--new-instance" in args
    assert (tmp_path / "runtime" / "settings" / "tls" / "trusted-clients").read_text().strip() == "v2:sha256:" + "a" * 64
    own_code = connection_code(config, settings)
    assert parse_code(own_code)["name"] == "Main"
    settings["screens"][1]["name"] = "x\nsection: options"
    with pytest.raises(ValueError):
        server_configuration(settings)


def test_import_deskflow_whitelists_layout_and_ignores_external_commands(qt_app, tmp_path):
    path = tmp_path / "Deskflow.conf"
    path.write_text("[core]\ncomputerName=Main\ncoreMode=2\nenableEnterCommand=true\nenterCommand=evil\n[server]\ngridWidth=5\nexternalConfig=true\nexternalConfigFile=bad.conf\n[internalConfig]\nscreens\\1\\name=Main\nscreens\\2\\name=Linux\nscreens\\size=2\n")
    value = import_profile(path)
    assert value["screens"] == [{"name": "Main", "x": 0, "y": 0}, {"name": "Linux", "x": 1, "y": 0}]
    assert not value["enabled"] and "enterCommand" not in value
    assert "evil" not in json.dumps(value)


def test_streamed_clipboard_relay_and_file_formats(group, tmp_path):
    payload = b"large clipboard text " * 120000
    check_delivery(group, group[1], {"text": payload})
    source = tmp_path / "shared.txt"
    source.write_bytes(b"real file payload")
    sent = group[2].send({"text": payload}, [str(source)])
    for device in (group[0], group[1], group[3]):
        received = device.received.get(timeout=15)
        assert received.stamp == sent.stamp and received.formats["text"] == payload
        assert Path(received.paths[0]).read_bytes() == source.read_bytes()


def test_sender_respects_negotiated_clipboard_limit_without_disconnect(pair):
    a, b = pair
    session = a.engine.sessions[b.config.device_id]
    session.caps["clip"] = 1024**2
    a.send({"text": b"x" * (2 * 1024**2)})
    wait_for(lambda: any(kind == "status" and "용량 제한" in str(value) for kind, value in a.events))
    assert b.received.empty() and a.connected and b.connected
    a.send({"text": b"small copy after rejected item"})
    assert b.received.get(timeout=5).formats["text"] == b"small copy after rejected item"


def test_insufficient_file_storage_rejected_before_creating_stage(tmp_path, monkeypatch):
    import shutil
    from clipbridge import files
    monkeypatch.setattr(files.shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(100, 99, 1))
    identifier = str(uuid.uuid4())
    with pytest.raises(ValueError, match="공간"):
        files.ReceiveTransfer(tmp_path, identifier, {"total": 2})
    assert not (tmp_path / identifier).exists()


def test_advanced_dialog_and_screen_layout_remain_usable(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QScrollArea
    from clipbridge import ui
    class DummyClipboard:
        def __init__(self, *args):
            pass
        def start(self):
            pass
    monkeypatch.setattr(ui, "ClipboardWorker", DummyClipboard)
    monkeypatch.setattr(ui.Window, "reconnect", lambda self: None)
    store = ConfigStore(tmp_path / "ui")
    config = store.load()
    window = ui.Window(store, config)
    try:
        assert window.centralWidget().findChild(QScrollArea)
        assert isinstance(window.advanced_dialog, QDialog) and window.advanced_dialog.isWindow()
        assert window.clip_limit.window() is window.advanced_dialog
        assert window.advanced_dialog.findChild(QDialogButtonBox).parent() is window.advanced_dialog
        window.clip_limit.setValue(512)
        window.advanced_dialog.reject()
        assert window.clip_limit.value() == config.clip_limit_mb == 256
        from clipbridge.input_ui import InputDialog
        config.input_settings = defaults()
        config.input_settings.update(name="Main", screens=[{"name": "Main", "x": 1, "y": 0}, {"name": "Linux", "x": 2, "y": 0}])
        dialog = InputDialog(window)
        dialog.move_screen(1, 1, 1)
        assert dialog.collect()["screens"][1] == {"name": "Linux", "x": 1, "y": 1}
        dialog.move_screen(1, 1, 0)
        assert dialog.collect()["screens"][1]["y"] == 1
        validate(dialog.collect())
        dialog.table.setCurrentCell(1, 0)
        dialog.remove_screen()
        assert dialog.table.rowCount() == 1
        dialog.deleteLater()
        qt_app.processEvents()
    finally:
        window.input_manager.stop()
        window.transfers.close()
        window.tray.hide()
        window.closing = True
        window.close()
        window.deleteLater()
        qt_app.processEvents()
