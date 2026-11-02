"""Selection and disconnect tests without touching the real desktop or connections."""
import concurrent.futures
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QWidget

from clipbridge.config import Config
from clipbridge.input_engine import defaults
from clipbridge.input_ui import ComputerTile, InputDialog
from test_portability import qt_app
from test_input_setup import devices, wait


def test_clicking_screen_card_keeps_selection_and_disconnects_that_pc(qt_app):
    class Owner(QWidget):
        def __init__(self):
            super().__init__()
            self.config = Config()
            self.config.input_settings = {**defaults(), "name": "Main", "screens": [
                {"name": "Main", "x": 1, "y": 1}, {"name": "Laptop", "x": 2, "y": 1}]}
            self.requests = []
            self.input_setup = self
        def device_addresses(self):
            return []
        def disconnect(self, name):
            self.requests.append(name)
            future = concurrent.futures.Future()
            future.set_result(None)
            return future
        def change_layout(self, *args):
            future = concurrent.futures.Future()
            future.set_result(None)
            return future
    owner = Owner()
    dialog = InputDialog(owner)
    try:
        dialog.show()
        qt_app.processEvents()
        tile = next(item for item in dialog.scene.items() if isinstance(item, ComputerTile) and item.row == 1)
        position = dialog.preview.mapFromScene(tile.sceneBoundingRect().center())
        QTest.mouseClick(dialog.preview.viewport(), Qt.MouseButton.LeftButton, pos=position)
        qt_app.processEvents()
        assert any(isinstance(item, ComputerTile) and item.row == 1 for item in dialog.scene.selectedItems())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.disconnect_selected()
        assert owner.requests == ["Laptop"]
    finally:
        dialog.close()
        owner.close()


def test_client_disconnect_clears_local_state_when_peer_socket_fails(devices, monkeypatch):
    import clipbridge.input_setup as setup
    host, client = devices("Main"), devices("Laptop")
    client.join(host)
    wait(lambda: client.data.get("easy_controller") and client.engine.client_writer)
    writer = client.engine.client_writer
    original = setup.write_frame
    async def broken(target, value):
        if target is writer and value.get("type") == "leave":
            raise ConnectionError("synthetic broken connection")
        return await original(target, value)
    monkeypatch.setattr(setup, "write_frame", broken)
    client.engine.disconnect(client.data["name"]).result(5)
    assert not client.data.get("easy_controller") and not client.config.peer_id


def test_host_disconnect_notifies_other_screens_even_if_removed_peer_socket_is_broken(devices, monkeypatch):
    import clipbridge.input_setup as setup
    host, removed, other = devices("Main"), devices("Laptop"), devices("Server")
    removed.join(host)
    wait(lambda: removed.data.get("easy_controller"))
    other.join(host)
    wait(lambda: len(other.data["screens"]) == 3 and removed.config.device_id in host.engine.clients)
    writer = host.engine.clients[removed.config.device_id]
    original = setup.write_frame
    async def broken(target, value):
        if target is writer and value.get("type") == "revoked":
            raise ConnectionError("synthetic broken connection")
        return await original(target, value)
    monkeypatch.setattr(setup, "write_frame", broken)
    host.engine.disconnect(removed.data["name"]).result(5)
    wait(lambda: len(other.data["screens"]) == 2)
    assert removed.config.device_id not in host.config.trusted_peers


def test_removing_a_peer_does_not_reenable_mouse_if_user_disabled_it(devices):
    host, removed, other = devices("Main"), devices("Laptop"), devices("Server")
    removed.join(host)
    wait(lambda: removed.data.get("easy_controller"))
    other.join(host)
    wait(lambda: len(host.data.get("easy_peers", {})) == 2)
    host.config.mouse_enabled = False
    host.engine.disconnect(removed.data["name"]).result(5)
    assert not host.data["enabled"] and not host.config.mouse_enabled
